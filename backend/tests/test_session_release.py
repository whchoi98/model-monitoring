"""느린 외부 호출 전에 읽기 트랜잭션을 끝낸다 — 인사이트 락 조사(2026-09-30, v2.32.2)에서 찾은 같은 모양의 경로들.

PostgreSQL에서 읽기 트랜잭션은 끝날 때까지 읽은 테이블(+ 인덱스)의 ACCESS SHARE 락을 쥔다. backend 기동의
`ALTER TABLE … ADD COLUMN IF NOT EXISTS`(main.py lifespan)는 열이 있는지 보기 전에 ACCESS EXCLUSIVE를 요청하므로, 그
락 뒤에서 lock_timeout 5초까지 기다렸다가 마이그레이션 블록 전체를 되돌린다. 배포 중에는 옛 태스크가 요청을 받는 동안 새
태스크가 기동하므로, 요청 하나가 Bedrock을 기다리며 쥔 락도 기동을 실패시킨다. 인사이트 경로는 tests/test_insights_locks.py다.

고정하는 것(SQLite, 느린 호출 순간에 열린 세션 트랜잭션이 없다):
- 패리티 런(parity/runner.run_parity)과 Claude API Features 런(claude_features/runner.run_features): 런 행을 만든 뒤
  `db.refresh(run)`이 다시 연 읽기 트랜잭션을 스윕(5~11분) 내내 쥐었다 → flush로 id를 받고 commit한다.
- 챗봇(POST /api/chat/stream): 도구가 요청 세션으로 probe_runs, probe_results를 읽은 뒤 다음 Bedrock hop, follow-up,
  AgentCore Memory 기록 내내 트랜잭션이 남았다. FastAPI 0.142에서는 인증의 users 조회도 스트림 끝까지 남았다
  → 스트림을 시작할 때와 도구 호출마다 rollback한다.
- OptimizePrompt(POST /api/prompts/optimize)와 Comparison Lab(POST /api/compare/run): 인증의 users 조회가 OptimizePrompt
  호출 동안, 또는 스트림 끝까지 남았다 → 요청 세션을 닫고 부른다.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import agent.bedrock
import agent.memory
import database
import models
import prober
from auth import create_access_token
from database import get_db

_USER = "tester@example.com"
_MODEL = "global.anthropic.claude-sonnet-4-6"


@pytest.fixture()
def tracked():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    sessions: list = []

    class Tracked(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

    factory = sessionmaker(bind=engine, class_=Tracked)
    with factory() as db:
        db.add(models.User(username=_USER, password_hash="x", approved=1))
        db.commit()
    sessions.clear()

    def open_txns() -> list[int]:
        return [i for i, s in enumerate(sessions) if s.in_transaction()]

    try:
        yield SimpleNamespace(factory=factory, sessions=sessions, open_txns=open_txns,
                              auth={"Authorization": f"Bearer {create_access_token(_USER)}"})
    finally:
        engine.dispose()


def _app(router, factory) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    def db_override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_override
    return app


# ───────────────────────────────────────────────────────────────────────
# 스케줄 러너 — 스윕 동안 런 테이블 트랜잭션 없음
# ───────────────────────────────────────────────────────────────────────


def test_parity_run_holds_no_transaction_during_the_sweep(tracked, monkeypatch):
    import parity.runner as parity_runner
    from parity.probes import ProbeOutcome

    monkeypatch.setattr(prober, "AVAILABLE_MODELS", {_MODEL: "Bedrock Claude Sonnet 4.6 (Global)"})
    monkeypatch.setattr(parity_runner, "SessionLocal", tracked.factory)
    seen: list[list[int]] = []

    def execute(model_id, surface, feature):
        seen.append(tracked.open_txns())
        return ProbeOutcome("supported", latency_ms=1.0, evidence={})

    monkeypatch.setattr(parity_runner, "_execute", execute)
    run_id = parity_runner.run_parity()
    assert seen and all(s == [] for s in seen), seen
    with tracked.factory() as db:
        run = db.get(models.ParityRun, run_id)
        assert run.status == "completed" and run.totals["supported"] == len(seen)
        assert db.query(models.ParityResult).filter_by(run_id=run_id).count() >= len(seen)


def test_features_run_holds_no_transaction_during_the_sweep(tracked, monkeypatch):
    import claude_features.runner as features_runner
    from claude_features import engine

    monkeypatch.setattr(database, "SessionLocal", tracked.factory)  # run_features가 부를 때 import한다
    seen: list[list[int]] = []

    def run_jobs(jobs, on_result):
        seen.append(tracked.open_txns())
        return {s: 0 for s in engine.STATUSES}

    monkeypatch.setattr(features_runner, "_run_jobs", run_jobs)
    run_id = features_runner.run_features()
    assert seen == [[]]
    with tracked.factory() as db:
        assert db.get(models.FeatureRun, run_id).status == "completed"


# ───────────────────────────────────────────────────────────────────────
# 요청 — Bedrock을 기다리는 동안 요청 세션 트랜잭션 없음
# ───────────────────────────────────────────────────────────────────────


def test_chat_stream_holds_no_transaction_during_bedrock_hops_and_followups(tracked, monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(agent.memory, "append_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent.memory, "list_recent_messages", lambda *args, **kwargs: [])
    seen: list = []

    async def converse_stream_chat(messages, **kwargs):
        seen.append(("hop", tracked.open_txns()))
        if len([s for s in seen if s[0] == "hop"]) == 1:  # 첫 hop — 도구를 부른다(요청 세션으로 probe_* 조회)
            yield {"type": "tool_use", "tool_use": {"name": "get_latest_results", "input": {}, "toolUseId": "t1"}}
            yield {"type": "stop", "stop_reason": "tool_use"}
            return
        yield {"type": "text_delta", "text": "최신 자동 프로브 결과를 모델별로 정리했습니다."}
        yield {"type": "stop", "stop_reason": "end_turn"}

    async def followups(question, answer):
        seen.append(("followups", tracked.open_txns()))
        return ["다음 질문?"]

    monkeypatch.setattr(agent.bedrock, "converse_stream_chat", converse_stream_chat)
    monkeypatch.setattr(chat_router, "_generate_followups", followups)
    with TestClient(_app(chat_router.router, tracked.factory)) as client:
        resp = client.post("/api/chat/stream", json={"message": "최신 결과 알려줘"}, headers=tracked.auth)
    assert resp.status_code == 200 and "event: tool_call" in resp.text and "event: followups" in resp.text, resp.text
    assert seen == [("hop", []), ("hop", []), ("followups", [])]


def test_optimize_prompt_holds_no_transaction_during_the_bedrock_call(tracked, monkeypatch):
    from routers import prompts as prompts_router

    seen: list[list[int]] = []

    class FakeOptimize:
        def optimize_prompt(self, **kwargs):
            seen.append(tracked.open_txns())
            return {"ResponseMetadata": {"RequestId": "req-1"},
                    "optimizedPrompt": [{"optimizedPromptEvent": {"optimizedPrompt": {"textPrompt": {"text": "더 나은"}}}}]}

    monkeypatch.setattr(prompts_router, "_get_optimize_client", lambda: FakeOptimize())
    with TestClient(_app(prompts_router.router, tracked.factory)) as client:
        resp = client.post("/api/prompts/optimize", json={"prompt": "요약해 줘", "target_model_id": _MODEL},
                           headers=tracked.auth)
    assert resp.status_code == 200 and resp.json()["optimized_prompt"] == "더 나은"
    assert seen == [[]]


def test_compare_run_holds_no_transaction_while_streaming(tracked, monkeypatch):
    from routers import compare as compare_router

    seen: list[list[int]] = []

    def stream_compare_events(model_ids, prompt, max_tokens, temperature):
        seen.append(tracked.open_txns())
        yield "event: complete\ndata: {}\n\n"

    monkeypatch.setattr(compare_router, "stream_compare_events", stream_compare_events)
    with TestClient(_app(compare_router.router, tracked.factory)) as client:
        resp = client.post("/api/compare/run", json={"prompt": "안녕", "model_ids": [_MODEL]}, headers=tracked.auth)
    assert resp.status_code == 200 and "event: complete" in resp.text
    assert seen == [[]]
