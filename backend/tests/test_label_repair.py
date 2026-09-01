"""라벨 자가 복구 (v2.22.1) — 카탈로그 라벨과 다른 저장 행만 갱신, 카탈로그 외 model_id는 보존."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from label_repair import find_label_mismatches, repair_model_labels

NOW = datetime(2026, 9, 1, 22, 0, 0, tzinfo=timezone.utc)
CATALOG = {
    "anthropic:claude-fable-5-1": "Anthropic Claude Fable 5.1 (US)",
    "anthropic:claude-fable-5": "Anthropic Claude Fable 5 (US)",
}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    return eng


def _seed(eng, rows):
    s = sessionmaker(bind=eng)()
    run = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=NOW)
    s.add(run)
    s.flush()
    for model_id, model_name in rows:
        s.add(models.ProbeResult(run_id=run.id, model_id=model_id, model_name=model_name, prompt="p",
                                 timestamp=NOW, status="success", ttft_ms=1.0))
    s.add(models.ProbeResultHourly(bucket_ts=NOW, model_id="anthropic:claude-fable-5-1",
                                   model_name="Anthropic Claude Fable 5 (US)", cnt=1, success_cnt=1))
    s.commit()
    s.close()


def test_repairs_mislabeled_rows_only(engine):
    _seed(engine, [
        ("anthropic:claude-fable-5-1", "Anthropic Claude Fable 5 (US)"),   # 오등록 (구 substring 매칭)
        ("anthropic:claude-fable-5-1", "Anthropic Claude Fable 5 (US)"),
        ("anthropic:claude-fable-5-1", "Anthropic Claude Fable 5.1 (US)"),  # 정상
        ("anthropic:claude-fable-5", "Anthropic Claude Fable 5 (US)"),      # 정상
        ("us.amazon.nova-pro-v1:0", "Bedrock Nova Pro (US)"),               # 카탈로그 외 → 보존
    ])
    with engine.connect() as conn:
        mism = find_label_mismatches(conn, CATALOG, "probe_results")
    assert mism == [("anthropic:claude-fable-5-1", "Anthropic Claude Fable 5 (US)", "Anthropic Claude Fable 5.1 (US)")]

    assert repair_model_labels(engine, CATALOG) == 3  # probe_results 2 + hourly 1

    s = sessionmaker(bind=engine)()
    names = sorted(s.execute(select(models.ProbeResult.model_name)
                             .where(models.ProbeResult.model_id == "anthropic:claude-fable-5-1")).scalars())
    assert names == ["Anthropic Claude Fable 5.1 (US)"] * 3
    assert s.execute(select(models.ProbeResult.model_name)
                     .where(models.ProbeResult.model_id == "us.amazon.nova-pro-v1:0")).scalar() == "Bedrock Nova Pro (US)"
    assert s.execute(select(models.ProbeResultHourly.model_name)).scalar() == "Anthropic Claude Fable 5.1 (US)"
    # 두 번째 실행은 no-op
    assert repair_model_labels(engine, CATALOG) == 0


def test_empty_catalog_is_noop(engine):
    _seed(engine, [("anthropic:claude-fable-5-1", "Anthropic Claude Fable 5 (US)")])
    assert repair_model_labels(engine, {}) == 0
