"""v2.33.0 (2026-10-07) — Claude Haiku 5.5 (Global, US, CP), Claude Sonnet 5.5 US, Sonnet 5.5 cache read cut.

Live checks behind these pins (2026-10-07): `global.`/`us.anthropic.claude-haiku-5-5` ACTIVE and converse 200, the Seoul
plain id is INFERENCE_PROFILE only; temperature 400, forced tool_choice (any) 200 on Bedrock and CP, thinking.type.enabled
400 and adaptive + effort 200; CP /v1/models lists claude-haiku-5-5 first; Mantle us-east-1 /anthropic 404.
`us.anthropic.claude-sonnet-5-5` appeared the same day (converse 200, forced tool_choice still 400). Offers:
Haiku 5.5 offer-u3aih6zr7uw5u (0.1 / 0.5, long context over 100K tokens 5x), Sonnet 5.5 cache read 0.2 -> 0.1 (Global).
The Anthropic pricing table still shows Sonnet 5.5 cache hits $0.20 while its text says $0.10 (user decision: follow
the table and show a doc_conflict note).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober
import pricing_seed
import pricing_sources
import pricing_sync
from claude_features import catalog as fcat, probes as fprobes, runner as frunner
from parity.catalog import is_reasoning_capable, supports_forced_tool_choice
from price_history import current_rows
from pricing_parsers import UnitPrice, parse_anthropic_pricing_md
from pricing_payload import build_pricing_payload
from pricing_sources import active_channels, price_identity
from tests.pricing_catalog import CP_MODEL_IDS_20261007

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
H_G, H_US, H_CP = "global.anthropic.claude-haiku-5-5", "us.anthropic.claude-haiku-5-5", "anthropic:claude-haiku-5-5"
S_G, S_US, S_CP = "global.anthropic.claude-sonnet-5-5", "us.anthropic.claude-sonnet-5-5", "anthropic:claude-sonnet-5-5"
NOW = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- prober channels

def test_bedrock_haiku55_and_sonnet55_us_channels():
    models_ = prober.AVAILABLE_MODELS
    assert models_[H_G] == "Bedrock Claude Haiku 5.5 (Global)"
    assert models_[H_US] == "Bedrock Claude Haiku 5.5 (US)"
    assert models_[S_US] == "Bedrock Claude Sonnet 5.5 (US)"
    assert "bedrock:ap-northeast-2:anthropic.claude-haiku-5-5" not in models_  # INFERENCE_PROFILE only
    keys = list(models_)
    assert keys.index(H_G) + 1 == keys.index("global.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert keys.index(H_US) + 1 == keys.index("us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert keys.index(S_US) + 1 == keys.index("us.anthropic.claude-sonnet-5")


def test_temperature_is_suppressed_for_haiku55_only():
    assert prober._is_reasoning_model(H_G) and prober._is_reasoning_model(H_US) and prober._is_reasoning_model(H_CP)
    assert prober._is_reasoning_model(S_US)
    assert not prober._is_reasoning_model("global.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert not prober._is_reasoning_model("anthropic:claude-haiku-4-5-20251001")


def test_cp_target_haiku55_right_before_haiku45_and_mirrored_by_pricing():
    substrings = [s for s, _ in prober._ANTHROPIC_TARGETS]
    assert substrings.index("haiku-5-5") + 1 == substrings.index("haiku-4-5")
    assert dict(prober._ANTHROPIC_TARGETS)["haiku-5-5"] == "Anthropic Claude Haiku 5.5 (US)"
    assert tuple(substrings) == pricing_sources._CP_TARGETS


def test_cp_discovery_with_20261007_model_order_labels_every_id_once():
    """claude-haiku-5-5 comes first; every target still finds its own id and no id gets two labels."""
    matched = {s: prober._match_anthropic_model(s, CP_MODEL_IDS_20261007) for s, _ in prober._ANTHROPIC_TARGETS}
    assert matched["haiku-5-5"] == "claude-haiku-5-5"
    assert matched["haiku-4-5"] == "claude-haiku-4-5-20251001"
    assert None not in matched.values()
    assert len(set(matched.values())) == len(matched)
    # a dated Haiku 5.5 id still matches its own target, and a later point release never hijacks it
    assert prober._match_anthropic_model("haiku-5-5", ["claude-haiku-5-5-20261101"]) == "claude-haiku-5-5-20261101"
    assert prober._match_anthropic_model("haiku-5-5", ["claude-haiku-5-5-1"]) is None


# ---------------------------------------------------------------- parity and Claude API Features

def test_parity_haiku55_keeps_forced_tool_choice_and_is_reasoning_capable():
    for mid in (H_G, H_US, H_CP):
        assert supports_forced_tool_choice(mid), mid  # forced any/tool 200 (2026-10-07)
        assert is_reasoning_capable(mid), mid         # adaptive-only like Sonnet 5.5
    assert not supports_forced_tool_choice(S_US)      # Sonnet 5.5 US: 400 like Global
    assert not is_reasoning_capable("global.anthropic.claude-haiku-4-5-20251001-v1:0")


def test_features_haiku55_is_the_seventh_model_without_mantle():
    (haiku,) = [m for m in fcat.MODELS if m["key"] == "haiku-5-5"]
    assert fcat.MODEL_KEYS[-1] == "haiku-5-5"
    assert (haiku["cp"], haiku["bedrock"], haiku["mantle"]) == ("claude-haiku-5-5", H_G, None)
    assert fprobes._advisor_model("haiku-5-5") == "claude-opus-5-5"
    jobs, decided = frunner.build_jobs(None, None, None)
    h_jobs = [j for j in jobs if j["model_key"] == "haiku-5-5"]
    h_dec = [d for d in decided if d["model_key"] == "haiku-5-5"]
    assert (len(h_jobs), len(h_dec)) == (133, 62)  # same shape as Sonnet 5.5: the whole Mantle column is decided
    assert sum(1 for d in h_dec if d["surface"] == "mantle") == 39
    assert frunner.CATALOG_VERSION == "2026-10-07"


# ---------------------------------------------------------------- pricing identity, seeds, parsers

def test_price_identity_of_the_new_channels():
    for mid, channel, source_kind in ((H_G, "global", "offer"), (H_US, "us", "offer"), (H_CP, "cp", "anthropic_doc")):
        ident = price_identity(mid)
        assert (ident.family_key, ident.family, ident.channel, ident.source_kind) == (
            "claude-haiku-5-5", "Claude Haiku 5.5", channel, source_kind), mid
    assert price_identity(S_US).channel == "us" and price_identity(S_US).family_key == "claude-sonnet-5-5"
    assert pricing_sources.FAMILY_ORDER.index("Claude Haiku 5.5") + 1 == pricing_sources.FAMILY_ORDER.index(
        "Claude Haiku 4.5")
    assert pricing_sources.keeps_long_context(price_identity(H_CP))
    assert not pricing_sources.keeps_long_context(price_identity(S_G))
    assert not pricing_sources.keeps_long_context(price_identity("us.anthropic.claude-haiku-4-5-20251001-v1:0"))


def test_new_seed_values():
    rows = pricing_seed.seed_rows(active_channels({m: m for m in (H_G, H_US, H_CP, S_G, S_US, S_CP)}, []))
    assert rows[H_G] == (0.1, 0.5, "offer:offer-u3aih6zr7uw5u")
    assert rows[H_US] == (0.11, 0.55, "offer:offer-u3aih6zr7uw5u")
    assert rows[H_CP] == (0.1, 0.5, pricing_sources.ANTHROPIC_SOURCE_ID)
    assert rows[S_US] == (2.2, 11.0, "offer:offer-5fu2rhus3byrs")
    extra = {mid: pricing_seed.seed_extra(mid, price_identity(mid)) for mid in (H_US, S_G, S_US, S_CP)}
    assert (extra[H_US]["long_input"], extra[H_US]["long_output"]) == (0.55, 2.75)
    assert [extra[m]["cache_read"] for m in (S_G, S_US, S_CP)] == [0.1, 0.11, 0.2]  # CP follows the doc table


def test_doc_parser_ignores_an_over_row_without_its_standard_row():
    table = (
        "## Model pricing\n\n"
        "| Model | Base input tokens | Output tokens |\n|---|---|---|\n"
        "| Claude Foo 1 (for prompts over 100,000 tokens) | $5 / MTok | $25 / MTok |\n"
        "| Claude Bar 2 (for prompts up to 200,000 tokens) | $1 / MTok | $5 / MTok |\n"
        "| Claude Bar 2 (for prompts over 200,000 tokens) | $2 / MTok | $10 / MTok |\n"
    )
    prices = parse_anthropic_pricing_md(table)
    assert set(prices) == {"Claude Bar 2"}
    assert (prices["Claude Bar 2"].input, prices["Claude Bar 2"].long_input, prices["Claude Bar 2"].long_output) == (1, 2, 10)


def test_long_context_gate_keeps_haiku55_and_drops_other_claude():
    price = UnitPrice(input=1, output=5, long_input=2, long_output=10, long_cache_read=1, long_cache_write=3)
    kept = pricing_sync._long_context_gate(price, price_identity(H_G))
    dropped = pricing_sync._long_context_gate(price, price_identity(S_G))
    assert (kept.long_input, kept.long_output) == (2, 10)
    assert (dropped.long_input, dropped.long_output, dropped.long_cache_read, dropped.long_cache_write) == (None,) * 4


# ---------------------------------------------------------------- one sync against the 2026-10-07 sources

def _offers(fm_id: str) -> dict:
    name = {"anthropic.claude-haiku-5-5": "offers_claude-haiku-5-5.json",
            "anthropic.claude-sonnet-5-5": "offers_claude-sonnet-5-5_20261007.json"}[fm_id]
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fail(*_):
    raise AssertionError("no such source in this test")


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_sync_applies_the_sonnet55_cache_cut_keeps_cp_on_the_table_and_shows_the_note(engine):
    active = active_channels({m: m for m in (H_G, H_US, H_CP, S_G, S_US, S_CP)}, [])
    assert pricing_seed.ensure_seed(engine, active) == 6
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:  # production before 2026-10-07: Sonnet 5.5 Global cache read was 0.2
        db.query(models.PriceHistory).filter(models.PriceHistory.model_id == S_G).update({"cache_read_per_mtok": 0.2})
        db.commit()
    fetchers = pricing_sync.Fetchers(
        offers=_offers, pricelist=_fail, openai_doc=_fail,
        anthropic_doc=lambda: (FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8"))
    pricing_sync.run_sync(Session, active, fetchers, now=lambda: NOW)

    with Session() as db:
        current = current_rows(db, active, now=NOW)
        assert current[S_G].cache_read_per_mtok == 0.1 and current[S_G].status == "verified"  # -50% applies
        assert db.query(models.PriceHistory).filter(models.PriceHistory.status == "pending_review").count() == 0
        assert current[S_CP].cache_read_per_mtok == 0.2   # the doc table still says $0.20
        assert current[S_US].cache_read_per_mtok == 0.11
        for mid, want in ((H_G, (0.5, 2.5, 0.05, 0.625)), (H_US, (0.55, 2.75, 0.055, 0.6875)), (H_CP, (0.5, 2.5, 0.05, 0.625))):
            row = current[mid]
            assert (row.long_input_per_mtok, row.long_output_per_mtok, row.long_cache_read_per_mtok,
                    row.long_cache_write_per_mtok) == want, mid
            assert row.observed_at is not None, mid
        assert current[S_G].long_input_per_mtok is None
        payload = build_pricing_payload(db, active, now=NOW)

    families = {f["family_key"]: f for f in payload["families"]}
    (note,) = families["claude-sonnet-5-5"]["notes"]
    assert (note["kind"], note["expected"], note["source_id"]) == ("doc_conflict", {"cp": {"cache_read": 0.1}},
                                                                    pricing_sources.ANTHROPIC_SOURCE_ID)
    haiku = families["claude-haiku-5-5"]["tiers"]
    assert haiku["global"]["long"] == {"input": 0.5, "output": 2.5, "cache_read": 0.05, "cache_write": 0.625}
    assert haiku["us"]["input"] == 0.11 and haiku["cp"]["long"]["input"] == 0.5
    assert families["claude-sonnet-5-5"]["tiers"]["global"]["cache_read"] == 0.1

    # Anthropic fixes the table: once a sync observes CP cache read 0.1, the note drops out
    with Session() as db:
        db.query(models.PriceHistory).filter(models.PriceHistory.model_id == S_CP).update({"cache_read_per_mtok": 0.1})
        db.commit()
        payload = build_pricing_payload(db, active, now=NOW)
    assert {f["family_key"]: f for f in payload["families"]}["claude-sonnet-5-5"]["notes"] == []
