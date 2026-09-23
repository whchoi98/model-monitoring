"""GPT on AWS 벤치 (v2.18.0) — run_cycle 저장·데드라인, 호출 wall-clock 상한(v2.28.0)과 라우터 집계 회귀 테스트."""

import sys
import threading
import time
import types
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
    "OPENAI_US_BASE_URL": "http://us",
    "BEDROCK_OPENAI_GPT_54_MODEL_ID": "openai.gpt-5.4",
    "BEDROCK_OPENAI_GPT_55_MODEL_ID": "openai.gpt-5.5",
    "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID": "openai.gpt-5.6-terra",
    "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID": "openai.gpt-6-astra",
    "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID": "openai.gpt-6-sol",
    "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID": "openai.gpt-6-luna",
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


def test_bench_channels_includes_gpt6_astra_three_channels(bench_env):
    """GPT 6 Astra 3채널 편입 (v2.25.1 사용자 결정) — Global CRIS, US CRIS, Mantle us-west-2.

    Mantle us-east-1 / us-east-2는 현재 미지원(404 not_found_error, 2026-09-09·09-23 실측) —
    사용자 결정(2026-09-23)으로 제외했으므로 채널이 생기면 안 된다.
    """
    import gptbench

    astra = [c for c in gptbench.bench_channels() if c["family"] == "GPT 6 Astra"]
    assert [(c["model_id"], c["model_name"]) for c in astra] == [
        ("openai:global:global.openai.gpt-6-astra", "OpenAI GPT 6 Astra (Global)"),
        ("openai:us:us.openai.gpt-6-astra", "OpenAI GPT 6 Astra (US)"),
        ("openai:us-west-2:openai.gpt-6-astra", "OpenAI GPT 6 Astra (us-west-2)"),
    ]
    assert not [c for c in astra if c["region"] in ("us-east-1", "us-east-2")]


def test_bench_channels_includes_gpt6_sol_luna_three_channels_each(bench_env):
    """GPT 6 Sol/Luna 각 3채널 편입 (v2.28.0 사용자 결정) — Global CRIS, US CRIS, Mantle us-east-1.

    Mantle 인리전은 us-east-1 단독(us-east-2/us-west-2는 404, 2026-09-23 실측). 라벨은 prober 등록
    라벨과 바이트 동일해야 한다(아래 test_bench_channel_keys_match_prober_registration이 교차 검증).
    """
    import gptbench

    chans = gptbench.bench_channels()
    new = [(c["family"], c["region"], c["model_id"], c["model_name"])
           for c in chans if c["family"] in ("GPT 6 Sol", "GPT 6 Luna")]
    assert new == [
        ("GPT 6 Sol", "global", "openai:global:global.openai.gpt-6-sol", "OpenAI GPT 6 Sol (Global)"),
        ("GPT 6 Sol", "us", "openai:us:us.openai.gpt-6-sol", "OpenAI GPT 6 Sol (US)"),
        ("GPT 6 Sol", "us-east-1", "openai:us-east-1:openai.gpt-6-sol", "OpenAI GPT 6 Sol (us-east-1)"),
        ("GPT 6 Luna", "global", "openai:global:global.openai.gpt-6-luna", "OpenAI GPT 6 Luna (Global)"),
        ("GPT 6 Luna", "us", "openai:us:us.openai.gpt-6-luna", "OpenAI GPT 6 Luna (US)"),
        ("GPT 6 Luna", "us-east-1", "openai:us-east-1:openai.gpt-6-luna", "OpenAI GPT 6 Luna (us-east-1)"),
    ]
    # 목록 끝 6채널 — 데드라인 컷이 신규 채널에 떨어져 기존 12채널 시계열이 끊기지 않는다.
    assert [c["family"] for c in chans[-6:]] == ["GPT 6 Sol"] * 3 + ["GPT 6 Luna"] * 3
    # GPT 5.6 Sol/Luna는 벤치 대상 아님 ("6 Sol" 부분 문자열 혼동 방지).
    assert not any(c["family"].startswith("GPT 5.6 Sol") or c["family"].startswith("GPT 5.6 Luna")
                   for c in chans)


def test_bench_channels_matrix(bench_env):
    """5.4×3 + 5.5×2(us-west-2 미제공) + terra×4(Global 포함, v2.20.1)
    + astra×3(Global, US CRIS, us-west-2 — v2.25.1)
    + sol×3 + luna×3(Global, US CRIS, us-east-1 — v2.28.0) = 18채널 (Mantle 인리전 11 + CRIS 7)."""
    import gptbench

    chans = gptbench.bench_channels()
    assert [(c["model_id"], c["model_name"]) for c in chans] == [
        ("openai:us-east-1:openai.gpt-5.4", "OpenAI GPT 5.4 (us-east-1)"),
        ("openai:us-east-2:openai.gpt-5.4", "OpenAI GPT 5.4 (us-east-2)"),
        ("openai:us-west-2:openai.gpt-5.4", "OpenAI GPT 5.4 (us-west-2)"),
        ("openai:us-east-1:openai.gpt-5.5", "OpenAI GPT 5.5 (us-east-1)"),
        ("openai:us-east-2:openai.gpt-5.5", "OpenAI GPT 5.5 (us-east-2)"),
        ("openai:global:global.openai.gpt-5.6-terra", "OpenAI GPT 5.6 Terra (Global)"),
        ("openai:us-east-1:openai.gpt-5.6-terra", "OpenAI GPT 5.6 Terra (us-east-1)"),
        ("openai:us-east-2:openai.gpt-5.6-terra", "OpenAI GPT 5.6 Terra (us-east-2)"),
        ("openai:us-west-2:openai.gpt-5.6-terra", "OpenAI GPT 5.6 Terra (us-west-2)"),
        ("openai:global:global.openai.gpt-6-astra", "OpenAI GPT 6 Astra (Global)"),
        ("openai:us:us.openai.gpt-6-astra", "OpenAI GPT 6 Astra (US)"),
        ("openai:us-west-2:openai.gpt-6-astra", "OpenAI GPT 6 Astra (us-west-2)"),
        ("openai:global:global.openai.gpt-6-sol", "OpenAI GPT 6 Sol (Global)"),
        ("openai:us:us.openai.gpt-6-sol", "OpenAI GPT 6 Sol (US)"),
        ("openai:us-east-1:openai.gpt-6-sol", "OpenAI GPT 6 Sol (us-east-1)"),
        ("openai:global:global.openai.gpt-6-luna", "OpenAI GPT 6 Luna (Global)"),
        ("openai:us:us.openai.gpt-6-luna", "OpenAI GPT 6 Luna (US)"),
        ("openai:us-east-1:openai.gpt-6-luna", "OpenAI GPT 6 Luna (us-east-1)"),
    ]
    assert len(chans) == 18
    assert sum(1 for c in chans if c["region"] in ("global", "us")) == 7
    assert sum(1 for c in chans if c["family"] == "GPT 5.5") == 2
    assert not any(c["family"] == "GPT 5.5" and c["region"] == "us-west-2" for c in chans)
    # pseudo-region 채널 id는 접두사 파생, 라벨은 "(Global)"/"(US)" 대문자 (prober 규약).
    glb = [c for c in chans if c["region"] == "global"]
    assert [c["family"] for c in glb] == ["GPT 5.6 Terra", "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna"]


def test_bench_channel_keys_match_prober_registration(bench_env, monkeypatch):
    """벤치 채널 키/라벨은 prober._register_openai_models 산출물과 바이트 동일해야 한다.

    gpt_bench_results.model_id/model_name은 대시보드 채널과 같은 스킴이어야 화면(MODEL_COLORS,
    channelRank)과 정렬되고, id 파생 규칙이 두 곳에 중복되면 조용히 드리프트한다.
    """
    import gptbench
    import prober

    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    prober._register_openai_models()

    for c in gptbench.bench_channels():
        assert prober.AVAILABLE_MODELS.get(c["model_id"]) == c["model_name"], c["model_id"]


def test_bench_channels_no_global_env(bench_env, monkeypatch):
    """OPENAI_GLOBAL_BASE_URL 미설정이면 Global 채널(Terra, Astra, Sol, Luna)만 조용히 빠진다."""
    import gptbench

    monkeypatch.delenv("OPENAI_GLOBAL_BASE_URL")
    chans = gptbench.bench_channels()
    assert len(chans) == 14
    assert not any(c["region"] == "global" for c in chans)


def test_bench_channels_no_us_env(bench_env, monkeypatch):
    """OPENAI_US_BASE_URL 미설정이면 US CRIS 채널(Astra, Sol, Luna)만 빠지고(KeyError 없이) 나머지 15채널 유지."""
    import gptbench

    monkeypatch.delenv("OPENAI_US_BASE_URL")
    chans = gptbench.bench_channels()
    assert len(chans) == 15
    assert not any(c["region"] == "us" for c in chans)
    for fam in ("GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna"):
        assert sum(1 for c in chans if c["family"] == fam) == 2


def test_run_cycle_persists_rows(bench_env, session_factory, monkeypatch):
    import database
    import gptbench

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gptbench, "one_call", _fake_call())
    monkeypatch.setattr(gptbench, "RUNS_PER_CHANNEL", 2)

    res = gptbench.run_cycle()
    assert res["rows"] == 36 and res["errors"] == 0  # 18ch × 2

    s = session_factory()
    rows = s.query(models.GptBenchResult).all()
    assert len(rows) == 36
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
    assert len(res["skipped_channels"]) == 18


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
    s.commit()
    s.close()

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


def test_latest_orders_gpt6_family_first(session_factory, client):
    """카드 정렬은 family(카탈로그 순) → region — Astra → Sol → Luna → Terra → 5.5 → 5.4,
    각 family 안에서 리전은 Global, US, 인리전 순.

    fam_rank에 누락된 family는 rank 9로 밀려 맨 뒤에 찍힌다 (v2.25.1 Astra, v2.28.0 Sol/Luna).
    """
    s = session_factory()
    cts = datetime.now(timezone.utc) - timedelta(minutes=20)  # 완료 사이클
    seeded = [
        ("GPT 5.4", "us-west-2", "openai:us-west-2:openai.gpt-5.4"),
        ("GPT 5.6 Terra", "us-east-1", "openai:us-east-1:openai.gpt-5.6-terra"),
        ("GPT 6 Astra", "us-west-2", "openai:us-west-2:openai.gpt-6-astra"),
        ("GPT 5.5", "us-east-1", "openai:us-east-1:openai.gpt-5.5"),
        ("GPT 6 Astra", "global", "openai:global:global.openai.gpt-6-astra"),
        ("GPT 5.6 Terra", "global", "openai:global:global.openai.gpt-5.6-terra"),
        ("GPT 6 Astra", "us", "openai:us:us.openai.gpt-6-astra"),
        ("GPT 6 Luna", "us-east-1", "openai:us-east-1:openai.gpt-6-luna"),
        ("GPT 6 Sol", "us", "openai:us:us.openai.gpt-6-sol"),
        ("GPT 6 Luna", "global", "openai:global:global.openai.gpt-6-luna"),
        ("GPT 6 Sol", "us-east-1", "openai:us-east-1:openai.gpt-6-sol"),
        ("GPT 6 Luna", "us", "openai:us:us.openai.gpt-6-luna"),
        ("GPT 6 Sol", "global", "openai:global:global.openai.gpt-6-sol"),
    ]
    for family, region, model_id in seeded:
        label = "Global" if region == "global" else ("US" if region == "us" else region)
        s.add(models.GptBenchResult(
            cycle_ts=cts, timestamp=cts, model_id=model_id,
            model_name=f"OpenAI {family} ({label})", family=family, region=region,
            run_no=1, status="success", ttfb_ms=800, ttft_ms=1700, gap_ms=900,
        ))
    s.commit()
    s.close()

    data = client.get("/api/gptbench/latest").json()
    assert [c["model_name"] for c in data["channels"]] == [
        "OpenAI GPT 6 Astra (Global)",
        "OpenAI GPT 6 Astra (US)",
        "OpenAI GPT 6 Astra (us-west-2)",
        "OpenAI GPT 6 Sol (Global)",
        "OpenAI GPT 6 Sol (US)",
        "OpenAI GPT 6 Sol (us-east-1)",
        "OpenAI GPT 6 Luna (Global)",
        "OpenAI GPT 6 Luna (US)",
        "OpenAI GPT 6 Luna (us-east-1)",
        "OpenAI GPT 5.6 Terra (Global)",
        "OpenAI GPT 5.6 Terra (us-east-1)",
        "OpenAI GPT 5.5 (us-east-1)",
        "OpenAI GPT 5.4 (us-west-2)",
    ]


def test_bench_channels_unknown_region_skipped(bench_env, monkeypatch):
    """_BENCH_SPECS에 프로버 테이블(_OPENAI_REGION_ENV)에 없는 리전이 들어가도 KeyError 없이
    그 채널만 건너뛴다 — 오타/선행 추가 한 줄이 15분 사이클 전체를 비우지 않도록 (v2.25.1 리뷰 Minor)."""
    import gptbench
    monkeypatch.setattr(gptbench, "_BENCH_SPECS",
                        [("GPT 6 Astra", "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", ("global", "eu-typo", "us-west-2"))])
    chans = gptbench.bench_channels()
    assert [c["region"] for c in chans] == ["global", "us-west-2"]


# ---------------------------------------------------------------------------
# 호출 wall-clock 상한 + 무재시도 (v2.28.0 하드닝)
#   2026-09-16~17 GPT 5.4 us-east-2 워밍업 1회 ~3,540s — CALL_TIMEOUT_S는 read timeout일 뿐이었고
#   SDK 기본 max_retries=2가 실패를 숨겼다.
# ---------------------------------------------------------------------------

def _ev(type_, usage=None):
    return types.SimpleNamespace(type=type_, response=types.SimpleNamespace(usage=usage))


def _usage():
    return types.SimpleNamespace(
        input_tokens=55839, output_tokens=90,
        input_tokens_details=types.SimpleNamespace(cached_tokens=55646),
        output_tokens_details=types.SimpleNamespace(reasoning_tokens=40),
    )


class _HangingStream:
    """첫 이벤트 후 close()될 때까지 블로킹 — 실제 SDK처럼 끊긴 스트림은 읽기 오류를 던진다."""

    def __init__(self):
        self.closed = threading.Event()

    def __iter__(self):
        yield _ev("response.created")
        # 테스트 안전판 10s — watchdog이 동작하지 않으면 이 대기가 끝까지 가서 테스트가 실패한다.
        self.closed.wait(10)
        raise OSError("[Errno 9] Bad file descriptor")

    def close(self):
        self.closed.set()


class _SlowStream:
    """이벤트를 천천히(간격 delay) 내보내지만 상한 안에 정상 종료하는 스트림.

    buffered=True면 close() 뒤에도 남은 이벤트를 끝까지 내보낸다(버퍼에 이미 받아 둔 응답 모사).
    기본은 실제 SDK처럼 close() 뒤 다음 읽기에서 오류.
    """

    def __init__(self, delay=0.0, buffered=False):
        self.delay = delay
        self.buffered = buffered
        self.closed = False

    def __iter__(self):
        events = [_ev(et) for et in ("response.created", "response.output_text.delta",
                                     "response.output_text.delta")]
        events.append(_ev("response.completed", usage=_usage()))
        for ev in events:
            time.sleep(self.delay)
            if self.closed and not self.buffered:
                raise OSError("[Errno 9] Bad file descriptor")
            yield ev

    def close(self):
        self.closed = True


class _CompletedThenHangingStream:
    """종료 이벤트(response.completed)까지 받은 뒤 스트림 꼬리([DONE]/연결 종료)를 기다리며 멈춘다.

    이 상태에서 watchdog이 만료되면 abort가 끊은 스트림이 실제 SDK처럼 읽기 오류를 던진다 —
    측정은 이미 상한 안에 끝났으므로 오류 행이 되면 안 된다(경합 회귀).
    """

    def __init__(self):
        self.closed = threading.Event()

    def __iter__(self):
        for et in ("response.created", "response.output_text.delta"):
            yield _ev(et)
        yield _ev("response.completed", usage=_usage())
        # 테스트 안전판 10s — watchdog이 끊지 않으면 이 대기가 끝까지 간다.
        self.closed.wait(10)
        raise OSError("[Errno 9] Bad file descriptor")

    def close(self):
        self.closed.set()


class _FakeClient:
    def __init__(self, stream, create_delay=0.0):
        self.stream = stream
        self.create_delay = create_delay
        self.responses = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        time.sleep(self.create_delay)
        return self.stream


def test_client_created_with_max_retries_zero(bench_env, monkeypatch):
    """(a) 측정 호출은 SDK 재시도 금지 — OpenAI(..., max_retries=0) + timeout=CALL_TIMEOUT_S."""
    import gptbench

    captured = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr(gptbench, "_client_cache", {})
    gptbench._client_for("us-east-1")
    gptbench._client_for("us-east-1")  # 캐시 — 재생성 없음
    gptbench._client_for("global")
    assert len(captured) == 2
    assert all(kw["max_retries"] == 0 for kw in captured)
    assert all(kw["timeout"] == gptbench.CALL_TIMEOUT_S for kw in captured)
    assert [kw["base_url"] for kw in captured] == ["http://e1", "http://gl"]


def test_watchdog_closes_hung_stream_within_cap(monkeypatch):
    """(b) 이벤트 후 멈춘 스트림은 상한 시점에 watchdog이 끊고 명확한 오류로 반환된다."""
    import gptbench

    stream = _HangingStream()
    monkeypatch.setattr(gptbench, "CALL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(gptbench, "_client_for", lambda region: _FakeClient(stream))

    t0 = time.perf_counter()
    r = gptbench.one_call("us-east-2", "openai.gpt-5.4")
    elapsed = time.perf_counter() - t0

    assert stream.closed.is_set()
    assert elapsed < 2.0  # 안전판(10s)이 아니라 상한(0.2s) 근처에서 풀려야 한다
    assert r["error"] == "WallClockTimeout: wall-clock timeout after 0.2s"
    assert r["ttfb_ms"] is not None and r["ttft_ms"] is None  # 부분 측정은 남지만 오류 행


def test_watchdog_fires_before_stream_opens(monkeypatch):
    """응답 헤더 대기 중(스트림 열기 전)에 만료되면 스트림이 열리는 즉시 끊고 오류로 기록한다."""
    import gptbench

    stream = _SlowStream()
    monkeypatch.setattr(gptbench, "CALL_TIMEOUT_S", 0.05)
    monkeypatch.setattr(gptbench, "_client_for", lambda region: _FakeClient(stream, create_delay=0.3))

    r = gptbench.one_call("us-east-1", "openai.gpt-6-sol")
    assert stream.closed
    assert r["error"] == "WallClockTimeout: wall-clock timeout after 0.05s"


def test_completion_after_expiry_is_still_timeout(monkeypatch):
    """만료 뒤에 버퍼에 남은 completed 이벤트가 와도 상한을 넘긴 호출은 오류 행이다."""
    import gptbench

    stream = _SlowStream(buffered=True)
    monkeypatch.setattr(gptbench, "CALL_TIMEOUT_S", 0.05)
    monkeypatch.setattr(gptbench, "_client_for", lambda region: _FakeClient(stream, create_delay=0.3))

    r = gptbench.one_call("us", "us.openai.gpt-6-luna")
    assert stream.closed
    assert r["error"] == "WallClockTimeout: wall-clock timeout after 0.05s"


def test_abort_stream_shuts_down_socket_before_close():
    """close()만으로는 다른 스레드의 블로킹 recv가 안 깨지므로(Linux) 소켓 shutdown이 먼저다."""
    import socket

    import gptbench

    calls = []

    class Sock:
        def shutdown(self, how):
            calls.append(("shutdown", how))

    class NS:
        def get_extra_info(self, name):
            return Sock() if name == "socket" else None

    class Stream:
        response = types.SimpleNamespace(extensions={"network_stream": NS()})

        def close(self):
            calls.append(("close", None))

    gptbench._abort_stream(Stream())
    assert calls == [("shutdown", socket.SHUT_RDWR), ("close", None)]

    # 소켓 미노출(fake/HTTP2 등)이어도 close는 수행
    calls.clear()
    plain = _SlowStream()
    gptbench._abort_stream(plain)
    assert plain.closed


def test_normal_call_unaffected_by_watchdog(monkeypatch):
    """(c) 상한 안에 끝나는 호출(느린 이벤트 포함)은 성공이며 watchdog이 스트림을 건드리지 않는다."""
    import gptbench

    stream = _SlowStream(delay=0.02)
    monkeypatch.setattr(gptbench, "CALL_TIMEOUT_S", 2.0)
    monkeypatch.setattr(gptbench, "_client_for", lambda region: _FakeClient(stream))
    watchdogs = []

    class RecordingWatchdog(gptbench._CallWatchdog):
        def __init__(self, limit_s):
            super().__init__(limit_s)
            watchdogs.append(self)

    monkeypatch.setattr(gptbench, "_CallWatchdog", RecordingWatchdog)

    r = gptbench.one_call("global", "global.openai.gpt-6-luna")
    assert r["error"] is None
    assert r["ttfb_ms"] is not None and r["ttft_ms"] is not None and r["ttft_ms"] >= r["ttfb_ms"]
    assert (r["input_tokens"], r["cached_tokens"], r["reasoning_tokens"], r["output_tokens"]) == (
        55839, 55646, 40, 90)
    assert not stream.closed
    # 타이머는 finally에서 취소되어 남지 않는다 — 고정 대기 대신 타이머 스레드를 직접 join(상한 1s)해
    # CI 부하에서도 흔들리지 않게 한다 (취소된 Timer는 즉시 깨어나 종료한다; 2.0s 상한보다 짧다).
    [wd] = watchdogs
    wd._timer.join(timeout=1.0)
    assert not wd._timer.is_alive()
    assert not wd.fired


def test_completed_then_abort_keeps_measurement(monkeypatch):
    """상한 안에 response.completed를 받은 뒤 watchdog이 만료되어 스트림을 끊어도(abort가 던진
    읽기 오류) 끝난 측정은 오류 행으로 뒤집히지 않는다 — 상한 안에 못 끝난 호출만 WallClockTimeout."""
    import gptbench

    stream = _CompletedThenHangingStream()
    monkeypatch.setattr(gptbench, "CALL_TIMEOUT_S", 0.1)
    monkeypatch.setattr(gptbench, "_client_for", lambda region: _FakeClient(stream))

    t0 = time.perf_counter()
    r = gptbench.one_call("us-west-2", "openai.gpt-6-sol")
    assert time.perf_counter() - t0 < 2.0  # 안전판(10s)이 아니라 상한 근처에서 풀린다
    assert stream.closed.is_set()  # watchdog이 실제로 만료되어 abort했다
    assert r["error"] is None
    assert r["ttfb_ms"] is not None and r["ttft_ms"] is not None
    assert (r["input_tokens"], r["cached_tokens"], r["reasoning_tokens"], r["output_tokens"]) == (
        55839, 55646, 40, 90)


def test_run_cycle_records_wall_clock_timeout_row(bench_env, session_factory, monkeypatch):
    """멈춘 호출은 기존 오류 행 경로로 저장되고 사이클은 다음 run으로 진행한다(순차 유지)."""
    import database
    import gptbench

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(gptbench, "CALL_TIMEOUT_S", 0.1)
    monkeypatch.setattr(gptbench, "RUNS_PER_CHANNEL", 2)
    monkeypatch.setattr(gptbench, "_BENCH_SPECS",
                        [("GPT 5.4", "BEDROCK_OPENAI_GPT_54_MODEL_ID", ("us-east-2",))])
    # 워밍업 정상 → run 1 멈춤 → run 2 정상
    streams = iter([_SlowStream(), _HangingStream(), _SlowStream()])
    monkeypatch.setattr(gptbench, "_client_for", lambda region: _FakeClient(next(streams)))

    t0 = time.perf_counter()
    res = gptbench.run_cycle()
    assert time.perf_counter() - t0 < 3.0
    assert res["rows"] == 2 and res["errors"] == 1

    s = session_factory()
    rows = s.query(models.GptBenchResult).order_by(models.GptBenchResult.run_no).all()
    assert [(r.run_no, r.status) for r in rows] == [(1, "error"), (2, "success")]
    assert rows[0].error_message == "WallClockTimeout: wall-clock timeout after 0.1s"
    assert rows[0].gap_ms is None
    s.close()
