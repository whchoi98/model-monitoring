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


# ---------------------------------------------------------------------------
# 다운샘플링 (hours > 24 → 시간 버킷 평균)
# 168h 원본은 56k행/13.3MB JSON — 브라우저 렌더링까지 마비시키므로 서버에서 축약한다.
# ---------------------------------------------------------------------------


def _seed_hourly(session, *, now=None):
    """같은 시각 버킷 안에 5분 간격 cycle 2개 × 모델 1개, 다른 버킷에 1개."""
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    base = now - timedelta(hours=30)  # hours=72 윈도우 안, 24h 밖

    def run_at(ts):
        r = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=ts)
        session.add(r)
        session.flush()
        return r

    def add_result(run, ts, ttft):
        session.add(
            models.ProbeResult(
                run_id=run.id, model_id="m1", model_name="Bedrock Claude Haiku 4.5 (US)",
                timestamp=ts, prompt="p", status="success",
                ttft_ms=ttft, total_latency_ms=ttft * 2, tps=40.0,
                output_text="X", category="chat-short",
            )
        )

    # 버킷 1 (base시각대): 10:00, 10:05 → 평균 ttft (100+300)/2=200
    r1 = run_at(base)
    add_result(r1, base, 100.0)
    r2 = run_at(base + timedelta(minutes=5))
    add_result(r2, base + timedelta(minutes=5), 300.0)
    # 버킷 2 (base+1h): 단독 → 평균 500
    r3 = run_at(base + timedelta(hours=1))
    add_result(r3, base + timedelta(hours=1), 500.0)
    session.commit()
    return base


def test_trend_over_24h_downsamples_to_hour_buckets(db_env):
    engine, session, client = db_env
    base = _seed_hourly(session)

    rows = client.get("/api/auto-probe/trend", params={"hours": 72}).json()

    assert len(rows) == 2  # 3 cycle → 시간 버킷 2개
    assert all(set(r.keys()) == EXPECTED_KEYS for r in rows)
    # sqlite는 naive datetime(+00:00 없음), PG는 tz-aware — 양쪽 호환 키 조회.
    def find(ts):
        by_ts = {r["timestamp"]: r for r in rows}
        return by_ts.get(ts.isoformat()) or by_ts[ts.replace(tzinfo=None).isoformat()]

    b1 = find(base)
    assert b1["ttft_ms"] == 200.0  # (100+300)/2
    assert b1["total_latency_ms"] == 400.0
    assert b1["status"] == "success"
    b2 = find(base + timedelta(hours=1))
    assert b2["ttft_ms"] == 500.0


def test_trend_at_or_under_24h_stays_raw(db_env):
    engine, session, client = db_env
    _seed(session)

    rows = client.get("/api/auto-probe/trend", params={"hours": 24}).json()

    # 다운샘플링 없이 cycle 단위 원본 유지 (5분 해상도)
    assert sorted(r["ttft_ms"] for r in rows) == [100.0, 200.0]
