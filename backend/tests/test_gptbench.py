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
    "OPENAI_GLOBAL_BASE_URL": "http://gl",
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
    """5.4×3 + 5.5×2(us-west-2 미제공) + terra×4(Global 포함, v2.20.1) = 9채널."""
    import gptbench

    chans = gptbench.bench_channels()
    assert len(chans) == 9
    assert sum(1 for c in chans if c["family"] == "GPT 5.5") == 2
    assert not any(c["family"] == "GPT 5.5" and c["region"] == "us-west-2" for c in chans)
    # Global CRIS는 Terra만 — id는 global. 접두사 파생, 라벨 "(Global)" 대문자 (prober 규약).
    glb = [c for c in chans if c["region"] == "global"]
    assert len(glb) == 1 and glb[0]["family"] == "GPT 5.6 Terra"
    assert glb[0]["model_id"] == "openai:global:global.openai.gpt-5.6-terra"
    assert glb[0]["model_name"] == "OpenAI GPT 5.6 Terra (Global)"


def test_bench_channels_no_global_env(bench_env, monkeypatch):
    """OPENAI_GLOBAL_BASE_URL 미설정이면 Global 채널만 조용히 빠지고 기존 8채널 유지."""
    import gptbench

    monkeypatch.delenv("OPENAI_GLOBAL_BASE_URL")
    chans = gptbench.bench_channels()
    assert len(chans) == 8
    assert not any(c["region"] == "global" for c in chans)


def test_run_cycle_persists_rows(bench_env, session_factory, monkeypatch):
    import database
    import gptbench

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gptbench, "one_call", _fake_call())
    monkeypatch.setattr(gptbench, "RUNS_PER_CHANNEL", 2)

    res = gptbench.run_cycle()
    assert res["rows"] == 18 and res["errors"] == 0  # 9ch × 2

    s = session_factory()
    rows = s.query(models.GptBenchResult).all()
    assert len(rows) == 18
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
    assert len(res["skipped_channels"]) == 9


def _seed(session_factory, cycles=3, channels=2, runs=3, base_ttfb=700.0, start_min_ago=20):
    """사이클 시드 — 기본은 모두 '완료'(14분 이상 경과) 사이클."""
    s = session_factory()
    now = datetime.now(timezone.utc)
    for c in range(cycles):
        cts = now - timedelta(minutes=start_min_ago + 15 * c)
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


def test_latest_skips_in_progress_cycle(session_factory, client):
    """진행 중(14분 미경과·부분 커밋) 사이클은 건너뛰고 직전 완료 사이클을 반환.

    2026-07-22 실사고: 채널 단위 커밋 때문에 실행 중 사이클의 4채널만 노출됨.
    """
    _seed(session_factory, cycles=1, channels=8, runs=2, start_min_ago=20)  # 완료 사이클 (8채널)
    # 진행 중 사이클: 3분 전 시작, 4채널만 커밋된 상태
    s = session_factory()
    cts = datetime.now(timezone.utc) - timedelta(minutes=3)
    for ch in range(4):
        s.add(models.GptBenchResult(
            cycle_ts=cts, timestamp=cts, model_id=f"openai:us-east-{ch+1}:m",
            model_name=f"OpenAI GPT 5.4 (r{ch})", family="GPT 5.4", region=f"r{ch}",
            run_no=1, status="success", ttfb_ms=800, ttft_ms=1700, gap_ms=900,
        ))
    s.commit(); s.close()

    data = client.get("/api/gptbench/latest").json()
    assert len(data["channels"]) == 8  # 부분(4채널) 사이클이 아니라 완료 사이클

    # trend도 진행 중 사이클 끝점을 제외
    tr = client.get("/api/gptbench/trend?hours=24").json()
    assert all(len(sr["points"]) == 1 for sr in tr["series"])


def test_latest_uses_only_cycle_even_if_fresh(session_factory, client):
    """사이클이 하나뿐이면 진행 중이어도 그것을 반환 (첫 배포 직후 빈 화면 방지)."""
    _seed(session_factory, cycles=1, channels=2, runs=2, start_min_ago=3)
    data = client.get("/api/gptbench/latest").json()
    assert len(data["channels"]) == 2
