"""GPT on AWS 벤치 (v2.18.0) — run_cycle 저장·데드라인과 라우터 집계 회귀 테스트."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine)


BENCH_ENV = {
    "OPENAI_API_KEY": "test",
    "OPENAI_US_EAST_1_BASE_URL": "http://e1",
    "OPENAI_US_EAST_2_BASE_URL": "http://e2",
    "OPENAI_US_WEST_2_BASE_URL": "http://w2",
    "BEDROCK_OPENAI_GPT_54_MODEL_ID": "openai.gpt-5.4",
    "BEDROCK_OPENAI_GPT_55_MODEL_ID": "openai.gpt-5.5",
    "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID": "openai.gpt-5.6-terra",
}


@pytest.fixture()
def bench_env(monkeypatch):
    for k, v in BENCH_ENV.items():
        monkeypatch.setenv(k, v)


def _fake_call(ttfb=800.0, ttft=1700.0, error=None):
    def call(region, actual_id):
        return dict(ttfb_ms=None if error else ttfb, ttft_ms=None if error else ttft,
                    cached_tokens=55646, reasoning_tokens=60, output_tokens=90,
                    input_tokens=55839, error=error)
    return call


def test_bench_channels_matrix(bench_env):
    """5.4×3 + 5.5×2(us-west-2 미제공) + terra×3 = 8채널."""
    import gptbench

    chans = gptbench.bench_channels()
    assert len(chans) == 8
    assert sum(1 for c in chans if c["family"] == "GPT 5.5") == 2
    assert not any(c["family"] == "GPT 5.5" and c["region"] == "us-west-2" for c in chans)


def test_run_cycle_persists_rows(bench_env, session_factory, monkeypatch):
    import database
    import gptbench

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gptbench, "one_call", _fake_call())
    monkeypatch.setattr(gptbench, "RUNS_PER_CHANNEL", 2)

    res = gptbench.run_cycle()
    assert res["rows"] == 16 and res["errors"] == 0  # 8ch × 2

    s = session_factory()
    rows = s.query(models.GptBenchResult).all()
    assert len(rows) == 16
    assert all(r.cycle_ts == rows[0].cycle_ts for r in rows)  # 사이클 그룹 키 동일
    assert rows[0].gap_ms == pytest.approx(900.0)
    s.close()


def test_run_cycle_deadline_skips_channels(bench_env, session_factory, monkeypatch):
    """데드라인 초과 시 남은 채널은 skip으로 보고 (15분 스케줄 겹침 방지)."""
    import database
    import gptbench

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gptbench, "one_call", _fake_call())
    monkeypatch.setattr(gptbench, "RUNS_PER_CHANNEL", 1)
    monkeypatch.setattr(gptbench, "CYCLE_DEADLINE_S", 0.0)  # 즉시 초과

    res = gptbench.run_cycle()
    assert res["rows"] == 0
    assert len(res["skipped_channels"]) == 8


def _seed(session_factory, cycles=3, channels=2, runs=3, base_ttfb=700.0):
    s = session_factory()
    now = datetime.now(timezone.utc)
    for c in range(cycles):
        cts = now - timedelta(minutes=15 * c)
        for ch in range(channels):
            for run_no in range(1, runs + 1):
                s.add(models.GptBenchResult(
                    cycle_ts=cts, timestamp=cts, model_id=f"openai:us-east-{ch+1}:m",
                    model_name=f"OpenAI GPT 5.4 (us-east-{ch+1})", family="GPT 5.4",
                    region=f"us-east-{ch+1}", run_no=run_no, status="success",
                    ttfb_ms=base_ttfb + run_no, ttft_ms=base_ttfb + 900 + run_no,
                    gap_ms=900.0, input_tokens=55839, cached_tokens=55646,
                    reasoning_tokens=60, output_tokens=90,
                ))
    s.commit()
    s.close()


@pytest.fixture()
def client(session_factory):
    from database import get_db
    from routers import gptbench as gr

    app = FastAPI()
    app.include_router(gr.router)

    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_latest_aggregates_last_cycle_only(session_factory, client):
    _seed(session_factory, cycles=3, channels=2, runs=3)
    data = client.get("/api/gptbench/latest").json()
    assert len(data["channels"]) == 2
    card = data["channels"][0]
    assert card["runs"] == 3 and card["success"] == 3
    assert card["median_ttfb_ms"] == pytest.approx(702.0)  # 701/702/703의 median
    assert card["cache_hit_rate"] == 1.0


def test_trend_series_grouped_by_cycle(session_factory, client):
    _seed(session_factory, cycles=3, channels=2, runs=3)
    data = client.get("/api/gptbench/trend?hours=24").json()
    assert len(data["series"]) == 2
    assert all(len(sr["points"]) == 3 for sr in data["series"])
    p = data["series"][0]["points"][0]
    assert p["median_gap_ms"] == pytest.approx(900.0)


def test_latest_empty_db(client):
    data = client.get("/api/gptbench/latest").json()
    assert data["cycle_ts"] is None and data["channels"] == []
