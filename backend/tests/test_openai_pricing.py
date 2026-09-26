"""OpenAI channel price identity + seed prices + cost channel split.

v2.30.0 (ADR-030): backend/pricing.py (PRICE_TABLE, _normalize_key prefix fallback, estimate_cost_usd) is gone.
Prices are stored per model_id in price_history, so every channel needs its own classification
(pricing_sources.price_identity) and its own seed row (pricing_seed.SEED). Per-row cost math is covered by
test_price_history.py and test_cost_time_effective.py.
"""
import pytest

import pricing_seed
from pricing_sources import active_channels, price_identity
from routers.cost import _channel


def _seed(model_id):
    return pytest.approx(pricing_seed.SEED[model_id][:2])


def test_openai_channels_classify_per_channel():
    assert price_identity("openai:us-east-1:openai.gpt-5.4").channel == "inregion:us-east-1"
    assert price_identity("openai:us-east-2:openai.gpt-5.5").channel == "inregion:us-east-2"
    assert price_identity("openai:global:global.openai.gpt-5.6-sol").channel == "global"
    assert price_identity("openai:us:us.openai.gpt-6-astra").channel == "us"
    assert price_identity("openai:us-west-2:openai.gpt-6-astra").channel == "inregion:us-west-2"
    # Global/US CRIS and in-region share one family (one table row), never a "-global" key.
    assert {price_identity(m).family_key for m in (
        "openai:global:global.openai.gpt-5.6-sol", "openai:us-east-1:openai.gpt-5.6-sol",
    )} == {"gpt-5.6-sol"}
    assert price_identity("openai:global:global.openai.gpt-5.6-sol").source_ref == "openai.gpt-5.6-sol"


def test_dormant_1p_channel_is_not_priced():
    # 1P direct is hidden and dormant (v2.19.1); it must not borrow the in-region price any more.
    assert "openai:1p:gpt-5.4" not in pricing_seed.SEED
    assert active_channels({"openai:1p:gpt-5.4": "OpenAI GPT 5.4 (1P)"}, ["(1P)"]) == {}


def test_gpt6_astra_official_pricing_per_channel():
    """In-Region, Geo CRIS(US) = OpenAI list +10% ($11/$55), Global CRIS = list ($10/$50)."""
    assert _seed("openai:us-west-2:openai.gpt-6-astra") == (11.0, 55.0)
    assert _seed("openai:us:us.openai.gpt-6-astra") == (11.0, 55.0)
    assert _seed("openai:global:global.openai.gpt-6-astra") == (10.0, 50.0)


def test_gpt6_sol_luna_seed_per_channel():
    for fam in ("sol", "luna"):
        for mid in (f"openai:us-east-1:openai.gpt-6-{fam}", f"openai:us:us.openai.gpt-6-{fam}",
                    f"openai:global:global.openai.gpt-6-{fam}"):
            assert price_identity(mid).family_key == f"gpt-6-{fam}", mid
            assert mid in pricing_seed.SEED, mid


def test_seed_openai_gpt54_gpt55():
    assert _seed("openai:us-east-1:openai.gpt-5.4") == (2.75, 16.5)
    assert _seed("openai:us-east-2:openai.gpt-5.5") == (5.5, 33.0)


def test_seed_gpt56_global_vs_in_region():
    # Global CRIS is cheaper than in-region; GPT-5.6 Sol carries the promotional price (v2.28.1).
    assert _seed("openai:global:global.openai.gpt-5.6-sol") == (4.0, 20.0)
    assert _seed("openai:us-east-1:openai.gpt-5.6-sol") == (4.4, 22.0)
    assert _seed("openai:global:global.openai.gpt-5.6-terra") == (2.0, 12.0)
    assert _seed("openai:us-east-2:openai.gpt-5.6-terra") == (2.2, 13.2)
    assert _seed("openai:global:global.openai.gpt-5.6-luna") == (0.2, 1.2)
    assert _seed("openai:us-west-2:openai.gpt-5.6-luna") == (0.22, 1.32)


def test_existing_claude_seed_unbroken():
    # Bedrock US is Global x1.1 since v2.30.0 (the old table collapsed us. onto global.).
    assert _seed("us.anthropic.claude-fable-5") == (11.0, 55.0)
    assert _seed("global.anthropic.claude-opus-5") == (5.0, 25.0)
    # Opus 4.8 is $5/$25 (2026-07-24 official check; $15/$75 was the Opus 4.1 price).
    assert pricing_seed.CP_SEED["claude-opus-4-8"][:2] == pytest.approx((5.0, 25.0))
    assert price_identity("anthropic:claude-opus-4-8").family_key == "claude-opus-4-8"


def test_channel_openai():
    assert _channel("openai:us-east-1:openai.gpt-5.4") == "OpenAI"
    assert _channel("openai:global:global.openai.gpt-5.6-sol") == "OpenAI"
    assert _channel("openai:us:us.openai.gpt-6-astra") == "OpenAI"
    assert _channel("us.anthropic.claude-opus-4-8") == "Bedrock US"
    assert _channel("anthropic:claude-fable-5") == "Anthropic (CP on AWS)"
