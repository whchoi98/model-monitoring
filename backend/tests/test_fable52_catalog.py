"""v2.41.0 (2026-11-09) — Claude Fable 5.2 (Global, US, CP).

Live checks behind these pins (2026-11-09): `global.`/`us.anthropic.claude-fable-5-2` ACTIVE (Seoul, us-east-1) and
converse_stream 200, the plain id is INFERENCE_PROFILE only in both regions; temperature 400 ("deprecated"), forced
tool_choice (tool, any) 400 and auto 200 on Bedrock Converse and CP, thinking.type.enabled 400 and adaptive + effort 200,
CountTokens unsupported, Mantle us-east-1 /anthropic 404. CP /v1/models lists claude-fable-5-2 first; production kept
the Fable 5 and 5.1 CP labels because the point-release guard skipped it before the target existed. Offer
offer-agsprgw6z3dg6: Global 8 / 40, US 8.8 / 44, cache read 0.025x input like Fable 5.1 (0.2, US 0.22), 5m write 10
(11), 1h write 16 (17.6), no long-context dimension. The Anthropic pricing table has the same CP price. The Claude API
Features smoke of all 195 Fable 5.2 cells gave the same statuses as the production Fable 5.1 cells (run 70), and the
seven new model-explorer examples passed on the first attempt.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_seed
import pricing_sources
import pricing_sync
import prober
from claude_features import catalog as fcat, probes as fprobes, runner as frunner
from model_explorer import examples
from parity.catalog import is_reasoning_capable, supports_forced_tool_choice
from price_history import current_rows
from pricing_parsers import UnitPrice, parse_anthropic_pricing_md, select_offer_price, single_public_offer
from pricing_payload import build_pricing_payload
from pricing_sources import active_channels, price_identity
from routers.reliability import _LABEL_RE
from tests.pricing_catalog import CP_MODEL_IDS_20261109

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
F_G, F_US, F_CP = "global.anthropic.claude-fable-5-2", "us.anthropic.claude-fable-5-2", "anthropic:claude-fable-5-2"
NOW = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)


def U(inp, out, **extra):
    return UnitPrice(input=D(str(inp)), output=D(str(out)), **{k: D(str(v)) for k, v in extra.items()})


# ---------------------------------------------------------------- prober channels

def test_bedrock_fable52_channels_open_the_global_and_us_blocks():
    models_ = prober.AVAILABLE_MODELS
    assert models_[F_G] == "Bedrock Claude Fable 5.2 (Global)"
    assert models_[F_US] == "Bedrock Claude Fable 5.2 (US)"
    assert "bedrock:ap-northeast-2:anthropic.claude-fable-5-2" not in models_  # INFERENCE_PROFILE only
    keys = list(models_)
    assert keys[0] == F_G and keys.index(F_G) + 1 == keys.index("global.anthropic.claude-fable-5-1")
    assert keys.index(F_US) + 1 == keys.index("us.anthropic.claude-fable-5-1")
    # Fable 5 and 5.1 stay as they were
    assert models_["global.anthropic.claude-fable-5-1"] == "Bedrock Claude Fable 5.1 (Global)"
    assert models_["us.anthropic.claude-fable-5"] == "Bedrock Claude Fable 5 (US)"


def test_temperature_is_suppressed_for_every_fable52_channel():
    for mid in (F_G, F_US, F_CP):
        assert prober._is_reasoning_model(mid), mid  # "fable-5" covers it — temperature 400 (2026-11-09)


def test_cp_target_fable52_comes_first_and_is_mirrored_by_pricing():
    substrings = [s for s, _ in prober._ANTHROPIC_TARGETS]
    assert substrings[:3] == ["fable-5-2", "fable-5-1", "fable-5"]
    assert dict(prober._ANTHROPIC_TARGETS)["fable-5-2"] == "Anthropic Claude Fable 5.2 (US)"
    assert tuple(substrings) == pricing_sources._CP_TARGETS


def test_cp_discovery_with_20261109_model_order_labels_every_id_once():
    """claude-fable-5-2 comes first; Fable 5 and 5.1 still find their own ids and no id gets two labels."""
    matched = {s: prober._match_anthropic_model(s, CP_MODEL_IDS_20261109) for s, _ in prober._ANTHROPIC_TARGETS}
    assert (matched["fable-5-2"], matched["fable-5-1"], matched["fable-5"]) == (
        "claude-fable-5-2", "claude-fable-5-1", "claude-fable-5")
    assert None not in matched.values()
    assert len(set(matched.values())) == len(matched)
    # without its own target the 5.2 id never fell to Fable 5 or 5.1 (what production did before v2.41.0)
    assert prober._match_anthropic_model("fable-5", ["claude-fable-5-2"]) is None
    assert prober._match_anthropic_model("fable-5-1", ["claude-fable-5-2"]) is None
    # a dated 5.2 id matches its own target, and a later point release never hijacks it
    assert prober._match_anthropic_model("fable-5-2", ["claude-fable-5-2-20261201"]) == "claude-fable-5-2-20261201"
    assert prober._match_anthropic_model("fable-5-2", ["claude-fable-5-2-1"]) is None


def test_reliability_reads_the_fable52_labels():
    m = _LABEL_RE.match("Anthropic Claude Fable 5.2 (US)")
    assert m and m.group(2) == "Claude Fable 5.2" and m.group(3) == "US"
    m = _LABEL_RE.match("Bedrock Claude Fable 5.2 (Global)")
    assert m and m.group(1) == "Bedrock" and m.group(2) == "Claude Fable 5.2"


# ---------------------------------------------------------------- parity, Claude API Features, model explorer

def test_parity_fable52_uses_auto_tool_choice_and_is_reasoning_capable():
    for mid in (F_G, F_US, F_CP):
        assert not supports_forced_tool_choice(mid), mid  # forced tool/any 400 (2026-11-09)
        assert is_reasoning_capable(mid), mid             # adaptive-only like Fable 5.1
    # the marker is the point release only — Fable 5 keeps forced tool_choice
    assert supports_forced_tool_choice("global.anthropic.claude-fable-5")
    assert supports_forced_tool_choice("anthropic:claude-fable-5")


def test_features_fable52_is_the_first_model_without_mantle():
    (fable,) = [m for m in fcat.MODELS if m["key"] == "fable-5-2"]
    assert fcat.MODEL_KEYS[:2] == ["fable-5-2", "fable-5-1"]
    assert (fable["cp"], fable["bedrock"], fable["mantle"]) == ("claude-fable-5-2", F_G, None)
    assert "anthropic.claude-fable-5-2" in fable["mantle_reason_en"] and "404" in fable["mantle_reason"]
    assert fprobes._advisor_model("fable-5-2") == "claude-fable-5-2"  # self pairing, like Fable 5.1 (smoke supported)
    jobs, decided = frunner.build_jobs(None, None, None)
    f_jobs = [j for j in jobs if j["model_key"] == "fable-5-2"]
    f_dec = [d for d in decided if d["model_key"] == "fable-5-2"]
    assert (len(f_jobs), len(f_dec)) == (133, 62)  # same shape as Fable 5.1: the whole Mantle column is decided
    assert sum(1 for d in f_dec if d["surface"] == "mantle") == 39
    assert frunner.CATALOG_VERSION == "2026-11-09"


def test_explorer_builds_the_same_three_bedrock_examples_and_one_cp_example():
    by_api = {mid: [e["api_id"] for e in examples.code_examples(mid)] for mid in (F_G, F_US, F_CP)}
    assert by_api == {F_G: ["converse", "invoke_model", "messages"], F_US: ["converse", "invoke_model", "messages"],
                      F_CP: ["messages"]}
    (cp,) = examples.code_examples(F_CP)
    assert '"claude-fable-5-2"' in cp["code"]["en"]
    assert '"us.anthropic.claude-fable-5-2"' in examples.code_examples(F_US)[0]["code"]["en"]


# ---------------------------------------------------------------- pricing identity, seeds, parsers

def test_price_identity_of_the_new_channels():
    for mid, channel, source_kind in ((F_G, "global", "offer"), (F_US, "us", "offer"), (F_CP, "cp", "anthropic_doc")):
        ident = price_identity(mid)
        assert (ident.family_key, ident.family, ident.channel, ident.source_kind) == (
            "claude-fable-5-2", "Claude Fable 5.2", channel, source_kind), mid
    assert pricing_sources.FAMILY_ORDER[0] == "Claude Fable 5.2"
    assert not pricing_sources.keeps_long_context(price_identity(F_G))


def test_new_seed_values():
    rows = pricing_seed.seed_rows(active_channels({m: m for m in (F_G, F_US, F_CP)}, []))
    assert rows[F_G] == (8.0, 40.0, "offer:offer-agsprgw6z3dg6")
    assert rows[F_US] == (8.8, 44.0, "offer:offer-agsprgw6z3dg6")
    assert rows[F_CP] == (8.0, 40.0, pricing_sources.ANTHROPIC_SOURCE_ID)
    extra = {mid: pricing_seed.seed_extra(mid, price_identity(mid)) for mid in (F_G, F_US, F_CP)}
    assert [(e["cache_read"], e["cache_write"], e["cache_write_1h"]) for e in extra.values()] == [
        (0.2, 10.0, 16.0), (0.22, 11.0, 17.6), (0.2, 10.0, 16.0)]
    assert all(e[f] is None for e in extra.values() for f in ("long_input", "long_output"))


def test_offer_fixture_gives_the_seed_prices():
    offer_id, card = single_public_offer(json.loads((FIXTURES / "offers_claude-fable-5-2.json").read_text()))
    assert offer_id == "offer-agsprgw6z3dg6"
    assert select_offer_price(card, "global") == U(8, 40, cache_read="0.2", cache_write=10, cache_write_1h=16)
    assert select_offer_price(card, "us") == U("8.8", 44, cache_read="0.22", cache_write=11, cache_write_1h="17.6")


def test_20261109_doc_lists_every_cp_family_and_the_fable52_price():
    prices = parse_anthropic_pricing_md((FIXTURES / "anthropic_pricing_20261109.md").read_text(encoding="utf-8"))
    assert set(pricing_sources.ANTHROPIC_DOC_NAMES.values()) <= set(prices)
    # "$0.20 / MTok<sup>1</sup>" — the footnote says Fable 5.2 and 5.1 cache hits are 0.025x the base input price
    assert prices["Claude Fable 5.2"] == U(8, 40, cache_read="0.20", cache_write=10, cache_write_1h=16)
    assert prices["Claude Fable 5.1"] == U(10, 50, cache_read="0.25", cache_write="12.50", cache_write_1h=20)


# ---------------------------------------------------------------- one sync against the 2026-11-09 sources

def _fail(*_):
    raise AssertionError("no such source in this test")


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_sync_verifies_the_fable52_seed_without_review(engine):
    active = active_channels({m: m for m in (F_G, F_US, F_CP)}, [])
    assert pricing_seed.ensure_seed(engine, active) == 3
    Session = sessionmaker(bind=engine, autoflush=False)
    fetchers = pricing_sync.Fetchers(
        offers=lambda fm: json.loads((FIXTURES / "offers_claude-fable-5-2.json").read_text(encoding="utf-8")),
        pricelist=_fail, openai_doc=_fail,
        anthropic_doc=lambda: (FIXTURES / "anthropic_pricing_20261109.md").read_text(encoding="utf-8"))
    pricing_sync.run_sync(Session, active, fetchers, now=lambda: NOW)

    with Session() as db:
        current = current_rows(db, active, now=NOW)
        assert db.query(models.PriceHistory).filter(models.PriceHistory.status == "pending_review").count() == 0
        for mid, want in ((F_G, (8.0, 40.0, 0.2)), (F_US, (8.8, 44.0, 0.22)), (F_CP, (8.0, 40.0, 0.2))):
            row = current[mid]
            assert (row.input_per_mtok, row.output_per_mtok, row.cache_read_per_mtok) == want, mid
            assert row.observed_at is not None, mid  # the sync observed the seed value, so the seed row is confirmed
        payload = build_pricing_payload(db, active, now=NOW)
    (family,) = [f for f in payload["families"] if f["family_key"] == "claude-fable-5-2"]
    assert family["family"] == "Claude Fable 5.2"
    assert family["tiers"]["global"]["input"] == 8.0 and family["tiers"]["us"]["output"] == 44.0
    assert family["tiers"]["cp"]["cache_write_1h"] == 16.0
