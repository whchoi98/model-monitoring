"""/api/auto-probe/trend 쿼리 다이어트 회귀 테스트.

2026-07-08 성능 개선: trend가 ORM 전체 컬럼(output_text 모델 응답 전문, prompt 등)을
로드해 hours=24에 1.87MB DB I/O를 유발했다. 응답에 필요한 8개 필드만 SELECT하고
run_id IN 리스트 대신 JOIN을 쓰도록 고정한다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import get_db
from routers import auto_probe


@pytest.fixture()
def db_env():
    # StaticPool: TestClient 워커 스레드와 시드 코드가 같은 in-memory DB를 공유.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(auto_probe.router)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield engine, Session(), TestClient(app)


def _seed(session, *, now=None):
    now = now or datetime.now(timezone.utc)
    runs = {
        # 윈도우 안 auto run — 포함되어야 함
        "recent_auto": models.ProbeRun(
            prompt="p", status="completed", is_auto=1, created_at=now - timedelta(hours=1)
        ),
        # 윈도우 밖 auto run — 제외
        "old_auto": models.ProbeRun(
            prompt="p", status="completed", is_auto=1, created_at=now - timedelta(hours=100)
        ),
        # 윈도우 안 manual run — 제외
        "recent_manual": models.ProbeRun(
            prompt="p", status="completed", is_auto=0, created_at=now - timedelta(hours=1)
        ),
    }
    session.add_all(runs.values())
    session.flush()

    def result(run, model_name, category, ttft):
        return models.ProbeResult(
            run_id=run.id,
            model_id="m1",
            model_name=model_name,
            timestamp=run.created_at,
            prompt="probe prompt text",
            status="success",
            ttft_ms=ttft,
            total_latency_ms=ttft * 2,
            tps=42.0,
            output_text="X" * 5000,  # 큰 응답 본문 — trend가 절대 읽으면 안 되는 컬럼
            category=category,
        )

    session.add_all(
        [
            result(runs["recent_auto"], "Bedrock Claude Haiku 4.5 (US)", "chat-short", 100.0),
            result(runs["recent_auto"], "OpenAI GPT 5.5 (1P)", "reasoning", 200.0),
            result(runs["old_auto"], "Bedrock Claude Haiku 4.5 (US)", "chat-short", 300.0),
            result(runs["recent_manual"], "Bedrock Claude Haiku 4.5 (US)", "chat-short", 400.0),
        ]
    )
    session.commit()


EXPECTED_KEYS = {
    "model_id", "model_name", "timestamp", "ttft_ms",
    "total_latency_ms", "tps", "status", "category",
}


def test_trend_shape_and_window_filtering(db_env):
    engine, session, client = db_env
    _seed(session)

    rows = client.get("/api/auto-probe/trend", params={"hours": 24}).json()

    # 최근 auto run의 2건만 — old/manual run 제외
    assert len(rows) == 2
    assert all(set(r.keys()) == EXPECTED_KEYS for r in rows)
    assert sorted(r["ttft_ms"] for r in rows) == [100.0, 200.0]


def test_trend_category_filter(db_env):
    engine, session, client = db_env
    _seed(session)

    rows = client.get(
        "/api/auto-probe/trend", params={"hours": 24, "category": "reasoning"}
    ).json()

    assert [r["model_name"] for r in rows] == ["OpenAI GPT 5.5 (1P)"]


def test_trend_does_not_select_large_text_columns(db_env):
    engine, session, client = db_env
    _seed(session)

    captured: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    client.get("/api/auto-probe/trend", params={"hours": 24})

    selects = [s for s in captured if s.lstrip().upper().startswith("SELECT")]
    assert selects, "trend 호출이 SELECT를 실행해야 한다"
    joined = "\n".join(selects)
    # 응답에 불필요한 대형 TEXT 컬럼을 DB에서 읽지 않는다 (쿼리 다이어트 회귀 방지).
    assert "output_text" not in joined
    assert "error_message" not in joined
