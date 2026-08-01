"""visibility.py — 1P 채널 비노출 필터 (v2.19.1) 회귀 테스트.

DB에는 1P 행이 남아 있어도 읽기 API에서 "(1P)" 라벨이 걸러지는지,
env HIDDEN_MODEL_PATTERNS 재정의로 재노출이 가능한지 확인한다.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import visibility


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(session_factory):
    s = session_factory()
    now = datetime.now(timezone.utc)
    run = models.ProbeRun(is_auto=1, status="completed", created_at=now, prompt="p")
    s.add(run)
    s.flush()
    for name, mid in [
        ("OpenAI GPT 5.4 (us-east-1)", "openai:us-east-1:openai.gpt-5.4"),
        ("OpenAI GPT 5.4 (1P)", "openai:1p:gpt-5.4"),
        ("Bedrock Claude Haiku 4.5 (Global)", "global.anthropic.claude-haiku-4-5"),
    ]:
        s.add(models.ProbeResult(
            run_id=run.id, model_id=mid, model_name=name, timestamp=now, prompt="p", status="success",
            ttft_ms=500.0, total_latency_ms=1500.0, tps=40.0,
            input_tokens=100, output_tokens=50,
        ))
    s.commit()
    s.close()


@pytest.fixture()
def client(session_factory):
    from database import get_db
    from routers import results as results_router

    app = FastAPI()
    app.include_router(results_router.router)

    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_results_hides_1p_rows(session_factory, client):
    _seed(session_factory)
    names = [r["model_name"] for r in client.get("/api/results/").json()]
    assert "OpenAI GPT 5.4 (us-east-1)" in names
    assert "Bedrock Claude Haiku 4.5 (Global)" in names
    assert all("(1P)" not in n for n in names)  # DB에는 있어도 응답에서 제외


def test_env_override_reexposes(session_factory, client, monkeypatch):
    _seed(session_factory)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "")  # 빈 값 = 숨김 해제
    names = [r["model_name"] for r in client.get("/api/results/").json()]
    assert "OpenAI GPT 5.4 (1P)" in names


def test_hidden_patterns_parsing(monkeypatch):
    assert visibility.hidden_patterns() == ["(1P)"]
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", " (1P) , Opus 4.5 ")
    assert visibility.hidden_patterns() == ["(1P)", "Opus 4.5"]


def test_insights_stats_exclude_1p(session_factory):
    """AI 인사이트 잡의 통계 수집도 1P 채널을 제외한다 (v2.19.2)."""
    from insights_runner import collect_stats_for_window

    _seed(session_factory)
    s = session_factory()
    try:
        stats = collect_stats_for_window(s, "6h")
    finally:
        s.close()
    text = str(stats)
    assert "(1P)" not in text
    assert "OpenAI GPT 5.4 (us-east-1)" in text
