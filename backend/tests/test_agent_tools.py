"""챗봇/인사이트 도구 회귀 테스트 — get_trend 토큰 폭발 방지 (2026-07-10 실사고).

챗봇이 get_trend(hours=168)을 호출하면 원본 포인트 56k+개(≈1.6M 토큰)가 tool_result로
LLM 컨텍스트에 들어가 ConverseStream이 'prompt is too long: 1599843 tokens > 1000000
maximum'으로 실패했다. 6시간 초과 조회는 (모델, 정시 버킷) 평균으로 축약하고,
어떤 경우에도 포인트 수 상한을 지키도록 고정한다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from agent import tools


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _seed_cycles(s, *, hours, per_hour=12, model_names=("Model A",)):
    """hours 시간 동안 per_hour 간격 cycle × 모델 수만큼 결과 시딩."""
    for h in range(hours):
        for i in range(per_hour):
            ts = NOW - timedelta(hours=h, minutes=i * (60 // per_hour))
            run = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=ts)
            s.add(run)
            s.flush()
            for name in model_names:
                s.add(models.ProbeResult(
                    run_id=run.id, model_id="m", model_name=name, timestamp=ts,
                    prompt="p", status="success", ttft_ms=100.0 + h,
                    total_latency_ms=200.0, tps=40.0, output_text="X" * 500,
                    category="chat-short",
                ))
    s.commit()


def test_get_trend_short_range_stays_raw(session):
    _seed_cycles(session, hours=2, per_hour=12)
    out = tools.get_trend(session, hours=2, metric="ttft_ms")
    # 6시간 이하는 5분 해상도 원본 유지
    assert len(out["points"]) == 24
    assert "aggregation" not in out or out.get("aggregation") == "raw"


def test_get_trend_long_range_aggregates_hourly(session):
    _seed_cycles(session, hours=30, per_hour=12, model_names=("Model A", "Model B"))
    out = tools.get_trend(session, hours=48, metric="ttft_ms")

    # (모델 2 × 시간 버킷 ~30) — 원본 720개가 아니라 시간 평균 ~60개
    assert len(out["points"]) <= 2 * 31
    assert out["aggregation"] == "hourly_avg"
    # 버킷 평균 값 검증: h=0 버킷은 ttft 100.0
    a_points = [p for p in out["points"] if p["model_name"] == "Model A"]
    assert any(abs(p["value"] - 100.0) < 0.01 for p in a_points)


def test_get_trend_never_exceeds_max_points(session):
    # 28모델 × 12/h × 24h = 8064 원본 — hours=24도 상한(2500) 이하로 축약되어야 한다.
    _seed_cycles(session, hours=24, per_hour=12,
                 model_names=tuple(f"Model {i:02d}" for i in range(28)))
    out = tools.get_trend(session, hours=24, metric="ttft_ms")
    assert len(out["points"]) <= tools.MAX_TREND_POINTS
    # 축약이 일어났음을 응답에 명시 (LLM이 해상도를 오해하지 않도록)
    assert out["aggregation"] in ("hourly_avg", "raw")


def test_compare_models_unaffected_by_aggregation(session):
    _seed_cycles(session, hours=30, per_hour=12, model_names=("Model A", "Model B"))
    out = tools.compare_models(session, metric="ttft_ms", hours=48)
    names = {s_["model_name"] for s_ in out["summary"]}
    assert names == {"Model A", "Model B"}
    for s_ in out["summary"]:
        assert s_["sample_count"] > 0
