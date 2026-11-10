"""v2.42.0 (2026-11-10) — Claude Fable 5 leaves monitoring (user decision, ADR-037).

The three channels (Bedrock Global, US and Claude Platform on AWS) leave the catalog, the pricing seeds and the Claude API
Features representative models; stored rows stay and the hide pattern "Claude Fable 5 (" keeps them out of every read.
The pattern carries the parenthesis because the match is a substring: "Claude Fable 5" alone would also hide the
"Claude Fable 5.1 (…)" and "Claude Fable 5.2 (…)" labels.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_seed
import pricing_sources
import prober
import visibility
from claude_features import catalog as fcat, probes as fprobes, runner as frunner
from pricing_sources import price_identity
from routers import features as features_router
from tests.pricing_catalog import CP_MODEL_IDS_20261109

RETIRED = {
    "global.anthropic.claude-fable-5": "Bedrock Claude Fable 5 (Global)",
    "us.anthropic.claude-fable-5": "Bedrock Claude Fable 5 (US)",
    "anthropic:claude-fable-5": "Anthropic Claude Fable 5 (US)",
}
KEPT = ["Bedrock Claude Fable 5.1 (Global)", "Bedrock Claude Fable 5.1 (US)", "Anthropic Claude Fable 5.1 (US)",
        "Bedrock Claude Fable 5.2 (Global)", "Bedrock Claude Fable 5.2 (US)", "Anthropic Claude Fable 5.2 (US)"]


def test_fable5_is_out_of_the_catalog_and_the_cp_targets():
    assert not set(RETIRED) & set(prober.AVAILABLE_MODELS)
    assert "fable-5" not in dict(prober._ANTHROPIC_TARGETS)
    assert [s for s, _ in prober._ANTHROPIC_TARGETS][:3] == ["fable-5-2", "fable-5-1", "opus-5-5"]
    assert tuple(s for s, _ in prober._ANTHROPIC_TARGETS) == pricing_sources._CP_TARGETS


def test_cp_discovery_leaves_claude_fable_5_unregistered_and_keeps_the_point_releases():
    """CP still serves claude-fable-5; no target takes it, and 5.1 and 5.2 keep their own ids."""
    assert "claude-fable-5" in CP_MODEL_IDS_20261109
    matched = {s: prober._match_anthropic_model(s, CP_MODEL_IDS_20261109) for s, _ in prober._ANTHROPIC_TARGETS}
    assert "claude-fable-5" not in matched.values()
    assert (matched["fable-5-2"], matched["fable-5-1"]) == ("claude-fable-5-2", "claude-fable-5-1")
    assert None not in matched.values()


def test_the_hide_pattern_hides_fable5_labels_only():
    patterns = visibility.hidden_patterns()
    assert "Claude Fable 5 (" in patterns
    for label in RETIRED.values():
        assert any(p in label for p in patterns), label
    for label in KEPT:
        assert not any(p in label for p in patterns), label


def test_the_hide_pattern_filters_stored_rows_in_sql():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        run = models.ProbeRun(prompt="p")
        db.add(run)
        db.flush()
        for name in [*RETIRED.values(), *KEPT]:
            db.add(models.ProbeResult(run_id=run.id, model_id="x", model_name=name, prompt="p", status="success"))
        db.commit()
        q = visibility.visible_only(db.query(models.ProbeResult.model_name), models.ProbeResult.model_name)
        assert sorted(n for (n,) in q.all()) == sorted(KEPT)
    engine.dispose()


def test_pricing_drops_fable5_and_keeps_its_offer_out_of_the_seed():
    assert "Claude Fable 5" not in pricing_sources.FAMILY_ORDER
    assert pricing_sources.FAMILY_ORDER[:3] == ("Claude Fable 5.2", "Claude Fable 5.1", "Claude Opus 5.5")
    for mid in RETIRED:
        assert price_identity(mid) is None, mid
    assert "claude-fable-5" not in pricing_seed.CP_SEED
    assert not [m for m in pricing_seed.SEED if m.endswith("anthropic.claude-fable-5")]
    assert "offer:offer-vk3fuman5qwzy" not in {src for *_, src in pricing_seed.SEED.values()}
    # the point releases are untouched
    assert price_identity("global.anthropic.claude-fable-5-1").family == "Claude Fable 5.1"
    assert price_identity("anthropic:claude-fable-5-2").family == "Claude Fable 5.2"


def test_features_drop_fable5_from_the_representative_models():
    assert fcat.MODEL_KEYS == ["fable-5-2", "fable-5-1", "opus-5-5", "opus-5", "sonnet-5-5", "sonnet-5", "haiku-5-5"]
    assert "fable-5" not in fprobes._ADVISOR_FOR
    jobs, decided = frunner.build_jobs(None, None, None)
    assert (len(jobs), len(decided)) == (1042, 323) and len(jobs) + len(decided) == 39 * 5 * 7
    assert frunner.CATALOG_VERSION == "2026-11-10"


@pytest.fixture()
def features_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _cell(run_id, model_key, status, verdict="match"):
    return models.FeatureResult(run_id=run_id, feature="messages_basic", surface="cp", model_key=model_key,
                                model_label=model_key, model_id=model_key, status=status, documented="ga",
                                verdict=verdict, latency_ms=100.0)


def test_latest_hides_cells_of_a_model_that_left_the_catalog_and_recounts_the_totals(features_db):
    """A run from before v2.42.0 still holds fable-5 cells; /latest shows only the catalog models until the next run."""
    now = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)
    with features_db() as db:
        run = models.FeatureRun(status="completed", started_at=now, finished_at=now, catalog_version="2026-11-09",
                                totals={"supported": 2, "unsupported": 1, "broken": 0, "inconclusive": 0, "skipped": 0,
                                        "not_applicable": 0, "drift": 1})
        db.add(run)
        db.flush()
        db.add_all([_cell(run.id, "fable-5", "supported"), _cell(run.id, "opus-5", "supported"),
                    _cell(run.id, "fable-5-2", "unsupported", verdict="drift")])
        db.commit()
        payload = features_router.get_latest(response=features_router.Response(), db=db)
    assert sorted(r["model_key"] for r in payload["results"]) == ["fable-5-2", "opus-5"]
    assert payload["run"]["totals"] == {"supported": 1, "unsupported": 1, "broken": 0, "inconclusive": 0, "skipped": 0,
                                        "not_applicable": 0, "drift": 1}
    assert [d["model_key"] for d in payload["drift"]] == ["fable-5-2"]


def test_latest_keeps_the_stored_totals_when_every_cell_is_a_catalog_model(features_db):
    now = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)
    stored = {"supported": 1, "unsupported": 0, "broken": 0, "inconclusive": 0, "skipped": 0, "not_applicable": 0, "drift": 0}
    with features_db() as db:
        run = models.FeatureRun(status="completed", started_at=now, finished_at=now, totals=stored)
        db.add(run)
        db.flush()
        db.add(_cell(run.id, "opus-5", "supported"))
        db.commit()
        payload = features_router.get_latest(response=features_router.Response(), db=db)
    assert payload["run"]["totals"] == stored
