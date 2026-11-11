"""v2.43.0 (2026-11-10) — Claude Opus 4.8, GPT 5.5 and GPT 5.6 Sol, Terra, Luna leave monitoring (user decision, ADR-038).

"fable 5.0, opus 4.8, gpt 5.5, gpt 5.6 을 deprecate 합니다." — Fable 5 already left in v2.42.0 (ADR-037). Ten channels leave
the catalog (Opus 4.8 Bedrock Global, US and CP; GPT 5.6 Sol, Terra, Luna Global and Mantle us-east-1; GPT 5.5 Mantle
us-east-1), with their pricing identity, seeds, OpenAI official-price channels, the GPT-5.6 Sol promo note, the GPT on
AWS bench channels (GPT 5.5, GPT 5.6 Terra) and the dormant 1P specs. Stored rows stay; the default hide patterns
"Claude Opus 4.8", "GPT 5.6" and "GPT 5.5" keep them out of every read. Active channels 49 → 39.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import gptbench
import models
import pricing_seed
import pricing_sources
import prober
import visibility
from pricing_sources import price_identity
from tests.pricing_catalog import ACTIVE_MODELS, CP_MODEL_IDS_20261109, RETIRED_1P_MODELS, RETIRED_V243_MODELS

NEW_PATTERNS = ("Claude Opus 4.8", "GPT 5.6", "GPT 5.5")
RETIRED_OFFERS = {  # offers no seed row cites any more
    "offer:offer-wdkl4yk6s7uu4",  # Claude Opus 4.8
    "offer:offer-gnqokrqqvdbgw", "offer:offer-3dvyrx3okd4lq", "offer:offer-bklbyf2ewuawu",  # GPT 5.6 Sol, Terra, Luna
    "offer:offer-rtwlbb46hcxpw",  # GPT 5.5
}


def test_the_ten_channels_are_out_of_the_catalog_and_the_cp_targets():
    assert len(RETIRED_V243_MODELS) == 10
    assert not set(RETIRED_V243_MODELS) & set(prober.AVAILABLE_MODELS)
    assert "opus-4-8" not in dict(prober._ANTHROPIC_TARGETS)
    assert tuple(s for s, _ in prober._ANTHROPIC_TARGETS) == pricing_sources._CP_TARGETS == (
        "fable-5-2", "fable-5-1", "opus-5-5", "opus-5", "sonnet-5-5", "sonnet-5", "haiku-5-5")
    families = [family for _, family, _ in prober._OPENAI_MODEL_SPECS]
    assert families == ["GPT 6.1 Sol", "GPT 6.1 Terra", "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna"]
    assert prober._OPENAI_1P_MODEL_SPECS == []  # the dormant 1P specs were GPT 5.5 and 5.6 only
    assert len(ACTIVE_MODELS) == 39


def test_cp_discovery_leaves_claude_opus_4_8_unregistered():
    """CP still lists claude-opus-4-8; no target takes it, and Opus 5 and 5.5 keep their own ids."""
    assert "claude-opus-4-8" in CP_MODEL_IDS_20261109
    matched = {s: prober._match_anthropic_model(s, CP_MODEL_IDS_20261109) for s, _ in prober._ANTHROPIC_TARGETS}
    assert "claude-opus-4-8" not in matched.values()
    assert (matched["opus-5-5"], matched["opus-5"]) == ("claude-opus-5-5", "claude-opus-5")
    assert None not in matched.values()


def test_injected_retired_model_envs_register_nothing(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_1P_API_KEY", "sk-proj-fake")
    for env, url in (("OPENAI_US_EAST_1_BASE_URL", "https://e1"), ("OPENAI_GLOBAL_BASE_URL", "https://gl"),
                     ("OPENAI_US_BASE_URL", "https://us")):
        monkeypatch.setenv(env, url)
    for env, value in (("BEDROCK_OPENAI_GPT_55_MODEL_ID", "openai.gpt-5.5"),
                       ("BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID", "openai.gpt-5.6-sol"),
                       ("BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", "openai.gpt-5.6-terra"),
                       ("BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID", "openai.gpt-5.6-luna"),
                       ("OPENAI_1P_GPT_55_MODEL_ID", "gpt-5.5"), ("OPENAI_1P_GPT_56_SOL_MODEL_ID", "gpt-5.6-sol")):
        monkeypatch.setenv(env, value)
    prober._register_openai_models()
    assert not [k for k in prober.AVAILABLE_MODELS if "gpt-5." in k or k.startswith("openai:1p:")]


def test_the_new_hide_patterns_hide_their_labels_and_no_active_label():
    patterns = visibility.hidden_patterns()
    assert patterns[-3:] == list(NEW_PATTERNS)
    for label in [*RETIRED_V243_MODELS.values(), *RETIRED_1P_MODELS.values()]:
        assert any(p in label for p in patterns), label
    for label in ACTIVE_MODELS.values():
        assert not any(p in label for p in patterns), label
    for family in pricing_sources.FAMILY_ORDER:
        assert not any(p in family for p in patterns), family


def test_the_new_hide_patterns_filter_stored_rows_in_sql():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    kept = ["Bedrock Claude Opus 5 (US)", "Anthropic Claude Opus 5.5 (US)", "OpenAI GPT 6 Sol (us-east-1)",
            "OpenAI GPT 6.1 Terra (Global)"]
    with sessionmaker(bind=engine)() as db:
        run = models.ProbeRun(prompt="p")
        db.add(run)
        db.flush()
        for name in [*RETIRED_V243_MODELS.values(), *kept]:
            db.add(models.ProbeResult(run_id=run.id, model_id="x", model_name=name, prompt="p", status="success"))
        db.commit()
        q = visibility.visible_only(db.query(models.ProbeResult.model_name), models.ProbeResult.model_name)
        assert sorted(n for (n,) in q.all()) == sorted(kept)
    engine.dispose()


@pytest.mark.parametrize("model_id", sorted(RETIRED_V243_MODELS))
def test_every_retired_channel_has_no_price_identity_or_seed(model_id):
    assert price_identity(model_id) is None
    assert model_id not in pricing_seed.SEED


def test_no_seed_offer_or_official_price_is_left_for_them():
    assert "claude-opus-4-8" not in pricing_seed.CP_SEED
    assert not [fk for fk in pricing_seed.OPENAI_LIST_SEED if fk.startswith("gpt-5.")]
    for list_id in ("openai-list:gpt-5.6-sol", "openai-list:gpt-5.6-terra", "openai-list:gpt-5.6-luna",
                    "openai-list:gpt-5.5"):
        assert price_identity(list_id) is None, list_id
    cited = {src for *_, src in pricing_seed.SEED.values()}
    assert not RETIRED_OFFERS & cited
    assert not RETIRED_OFFERS & set(pricing_seed.SEED_SOURCE_DATES)
    for name in ("Claude Opus 4.8", "GPT 5.6 Sol", "GPT 5.6 Terra", "GPT 5.6 Luna", "GPT 5.5"):
        assert name not in pricing_sources.FAMILY_ORDER, name


def test_the_gpt_5_6_sol_promo_note_is_gone():
    assert [n["kind"] for n in pricing_sources.PRICE_NOTES] == ["doc_conflict"]
    assert not [n for n in pricing_sources.PRICE_NOTES if n["family_key"].startswith("gpt-5.")]


def test_the_bench_keeps_fifteen_gpt_6_channels_in_two_lanes(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in (("OPENAI_US_EAST_1_BASE_URL", "https://e1"), ("OPENAI_GLOBAL_BASE_URL", "https://gl"),
                     ("OPENAI_US_BASE_URL", "https://us")):
        monkeypatch.setenv(env, url)
    for env, _, _ in prober._OPENAI_MODEL_SPECS:
        monkeypatch.setenv(env, "openai.x")
    assert [family for family, _, _ in gptbench._BENCH_SPECS] == [
        "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna", "GPT 6.1 Sol", "GPT 6.1 Terra"]
    chans = gptbench.bench_channels()
    assert len(chans) == 15 and not [c for c in chans if c["family"].startswith("GPT 5.")]
    lanes = gptbench.bench_lanes(chans)
    assert {lane: len(items) for lane, items in lanes.items()} == {"cris": 10, "mantle-us-east-1": 5}
