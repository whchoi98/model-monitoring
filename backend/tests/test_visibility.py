"""visibility.py — 조회 노출 필터 회귀 테스트 (1P 채널 v2.19.1, 모니터링에서 뺀 다섯 패밀리 v2.39.0).

DB에는 1P 행과 v2.39.0에 모니터링에서 뺀 Claude Opus 4.7, Opus 4.6, Sonnet 4.6, Haiku 4.5, GPT 5.4 행이 남아 있어도
읽기 API(결과, 인사이트 통계, GPT on AWS 벤치, 패리티)에서 걸러지는지, env HIDDEN_MODEL_PATTERNS 재정의로 재노출이
가능한지, 활성 라벨이 숨김 패턴에 걸리지 않는지 확인한다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import visibility
from pricing_sources import FAMILY_ORDER
from tests.pricing_catalog import ACTIVE_MODELS, RETIRED_V239_MODELS

VISIBLE = [
    ("OpenAI GPT 5.5 (us-east-1)", "openai:us-east-1:openai.gpt-5.5"),
    ("Bedrock Claude Haiku 5.5 (Global)", "global.anthropic.claude-haiku-5-5"),
]
HIDDEN_1P = [("OpenAI GPT 5.5 (1P)", "openai:1p:gpt-5.5")]
RETIRED = [  # v2.39.0 — 다섯 패밀리마다 한 채널 이상
    ("OpenAI GPT 5.4 (us-east-1)", "openai:us-east-1:openai.gpt-5.4"),
    ("OpenAI GPT 5.4 (1P)", "openai:1p:gpt-5.4"),
    ("Bedrock Claude Haiku 4.5 (Global)", "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("Anthropic Claude Sonnet 4.6 (US)", "anthropic:claude-sonnet-4-6"),
    ("Bedrock Claude Opus 4.7 (US)", "us.anthropic.claude-opus-4-7"),
    ("Bedrock Claude Opus 4.6 (Global)", "global.anthropic.claude-opus-4-6-v1"),
]


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
    for name, mid in [*VISIBLE, *HIDDEN_1P, *RETIRED]:
        s.add(models.ProbeResult(
            run_id=run.id, model_id=mid, model_name=name, timestamp=now, prompt="p", status="success",
            ttft_ms=500.0, total_latency_ms=1500.0, tps=40.0,
            input_tokens=100, output_tokens=50,
        ))
    s.commit()
    s.close()


def _client(session_factory, *routers):
    from database import get_db

    app = FastAPI()
    for router in routers:
        app.include_router(router)

    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


@pytest.fixture()
def client(session_factory):
    from routers import results as results_router

    return _client(session_factory, results_router.router)


def test_results_hides_1p_and_retired_rows(session_factory, client):
    _seed(session_factory)
    names = [r["model_name"] for r in client.get("/api/results/").json()]
    assert sorted(names) == sorted(n for n, _ in VISIBLE)  # DB에는 있어도 응답에서 제외


def test_env_override_reexposes(session_factory, client, monkeypatch):
    _seed(session_factory)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "")  # 빈 값 = 숨김 해제
    names = [r["model_name"] for r in client.get("/api/results/").json()]
    assert sorted(names) == sorted(n for n, _ in [*VISIBLE, *HIDDEN_1P, *RETIRED])


def test_hidden_patterns_parsing(monkeypatch):
    assert visibility.hidden_patterns() == [
        "(1P)", "Claude Opus 4.7", "Claude Opus 4.6", "Claude Sonnet 4.6", "Claude Haiku 4.5", "GPT 5.4"]
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", " (1P) , Opus 4.5 ")
    assert visibility.hidden_patterns() == ["(1P)", "Opus 4.5"]


def _hidden(label: str) -> bool:
    return any(p in label for p in visibility.hidden_patterns())


def test_no_active_label_or_family_matches_a_default_pattern():
    """숨김 패턴이 남은 채널을 가리지 않는다 — 예를 들어 "GPT 5.4"가 미래의 "GPT 5.45"를, "Claude Opus 4.6"이
    다른 Opus를 잡지 않는지. 운영 카탈로그 49채널(tests/pricing_catalog.py)과 FAMILY_ORDER 18개로 확인한다."""
    assert [label for label in ACTIVE_MODELS.values() if _hidden(label)] == []
    assert [family for family in FAMILY_ORDER if _hidden(family)] == []
    assert len(RETIRED_V239_MODELS) == 12 and all(_hidden(label) for label in RETIRED_V239_MODELS.values())


def test_insights_stats_exclude_1p_and_retired(session_factory):
    """AI 인사이트 잡의 통계 수집도 1P 채널(v2.19.2)과 v2.39.0에 뺀 패밀리를 제외한다."""
    from insights_runner import collect_stats_for_window

    _seed(session_factory)
    s = session_factory()
    try:
        stats = collect_stats_for_window(s, "6h")
    finally:
        s.close()
    text = str(stats)
    assert "(1P)" not in text and not any(name in text for name, _ in RETIRED)
    assert all(name in text for name, _ in VISIBLE)


def test_gptbench_latest_and_trend_hide_retired_rows(session_factory):
    """GPT on AWS 벤치의 지난 GPT 5.4 사이클(v2.38.x까지 수집)은 스코어 카드와 추세에 나오지 않는다(v2.39.0)."""
    from routers import gptbench as gptbench_router

    cycle = datetime.now(timezone.utc) - timedelta(minutes=20)  # 14분이 지나 완료된 사이클
    s = session_factory()
    for name, mid, family in (("OpenAI GPT 5.5 (us-east-1)", "openai:us-east-1:openai.gpt-5.5", "GPT 5.5"),
                              ("OpenAI GPT 5.4 (us-east-1)", "openai:us-east-1:openai.gpt-5.4", "GPT 5.4")):
        s.add(models.GptBenchResult(cycle_ts=cycle, timestamp=cycle, model_id=mid, model_name=name, family=family,
                                    region="us-east-1", run_no=1, status="success", ttfb_ms=500.0, ttft_ms=900.0,
                                    gap_ms=400.0, cached_tokens=100))
    s.commit()
    s.close()
    client = _client(session_factory, gptbench_router.router)
    latest = client.get("/api/gptbench/latest").json()
    assert [c["model_name"] for c in latest["channels"]] == ["OpenAI GPT 5.5 (us-east-1)"]
    trend = client.get("/api/gptbench/trend?hours=1").json()
    assert [series["model_name"] for series in trend["series"]] == ["OpenAI GPT 5.5 (us-east-1)"]


def test_parity_latest_hides_retired_rows_and_their_diff(session_factory):
    """배포 직후 패리티 /latest는 마지막 런(배포 전)의 빠진 모델 셀도, 그 셀의 직전 런 대비 변경도 보이지 않는다.
    다음 런에는 그 셀이 없고, 직전 런에만 있는 셀은 diff_statuses가 원래 무시한다."""
    from routers import parity as parity_router

    now = datetime.now(timezone.utc)
    s = session_factory()
    previous = models.ParityRun(started_at=now - timedelta(hours=12), finished_at=now - timedelta(hours=12),
                                status="completed", totals={})
    current = models.ParityRun(started_at=now, finished_at=now, status="completed", totals={})
    s.add_all([previous, current])
    s.flush()
    cells = {previous.id: [("Bedrock Claude Haiku 5.5 (Global)", "global.anthropic.claude-haiku-5-5", "supported"),
                           ("Bedrock Claude Haiku 4.5 (Global)", "global.anthropic.claude-haiku-4-5-20251001-v1:0",
                            "supported")],
             current.id: [("Bedrock Claude Haiku 5.5 (Global)", "global.anthropic.claude-haiku-5-5", "unsupported"),
                          ("Bedrock Claude Haiku 4.5 (Global)", "global.anthropic.claude-haiku-4-5-20251001-v1:0",
                           "broken")]}
    for run_id, rows in cells.items():
        for name, mid, status in rows:
            s.add(models.ParityResult(run_id=run_id, model_id=mid, model_name=name, surface="converse",
                                      feature="streaming", status=status))
    s.commit()
    s.close()
    body = _client(session_factory, parity_router.router).get("/api/parity/latest").json()
    assert [r["model_name"] for r in body["results"]] == ["Bedrock Claude Haiku 5.5 (Global)"]
    assert [c["model_id"] for c in body["changes"]] == ["global.anthropic.claude-haiku-5-5"]  # Haiku 4.5: no change
