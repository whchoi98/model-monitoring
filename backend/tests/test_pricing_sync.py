"""12-hour official price sync (v2.30.0, ADR-030) — fake Fetchers + in-memory SQLite, no network."""

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pricing_sync
from database import Base
from models import PriceHistory, PriceSyncRun
from pricing_parsers import EXTRA_FIELDS, PRICE_FIELDS, PriceParseError, UnitPrice, single_public_offer
from pricing_sources import ANTHROPIC_PRICING_URL, EPOCH, OPENAI_PRICING_URL, price_identity
from pricing_sync import (
    CHANGE_THRESHOLD, SOURCES, SYNC_DEADLINE_S, SYNC_LOCK_KEY, Fetchers, classify_change, default_fetchers, run_sync,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
T0 = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
T1, T2 = T0 + timedelta(hours=12), T0 + timedelta(hours=24)
OPUS_G, OPUS_US = "global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5"
SOL_G, SOL_E1 = "openai:global:global.openai.gpt-5.6-sol", "openai:us-east-1:openai.gpt-5.6-sol"
NOVA = "us.amazon.nova-2-lite-v1:0"
CP_HAIKU = "anthropic:claude-haiku-4-5-20251001"  # CP ids carry the /v1/models date suffix
OL_SOL = "openai-list:gpt-5.6-sol"  # OpenAI official price (display only), from the OpenAI pricing markdown
ALL = (OPUS_G, OPUS_US, SOL_G, SOL_E1, NOVA, CP_HAIKU, OL_SOL)
SOL_OFFER_ID = "offer-gnqokrqqvdbgw"
BASELINE = {  # current official values = seed rows: (input, output, source_id)
    OPUS_G: (4.0, 20.0, "offer:offer-7sp77cpl4rveu"), OPUS_US: (4.4, 22.0, "offer:offer-7sp77cpl4rveu"),
    SOL_G: (4.0, 20.0, f"offer:{SOL_OFFER_ID}"), SOL_E1: (4.4, 22.0, f"offer:{SOL_OFFER_ID}"),
    NOVA: (0.33, 2.75, "pricelist:USE1-Nova2.0Lite-input-tokens"), CP_HAIKU: (1.0, 5.0, "anthropic-pricing"),
    OL_SOL: (4.0, 20.0, "openai-pricing"),
}
# The cache and long-context values the committed fixtures carry for the same channels (the fake Sol offer has
# none), so a seeded channel whose source says the same thing again is "unchanged". extras={} seeds v2.30.0 rows.
BASELINE_EXTRAS = {
    OPUS_G: {"cache_read": 0.2, "cache_write": 5.0, "cache_write_1h": 8.0},
    OPUS_US: {"cache_read": 0.22, "cache_write": 5.5, "cache_write_1h": 8.8},
    NOVA: {"cache_read": 0.0825, "cache_write": 0.0},
    CP_HAIKU: {"cache_read": 0.1, "cache_write": 1.25, "cache_write_1h": 2.0},
    OL_SOL: {"cache_read": 0.4, "cache_write": 5.0, "long_input": 8.0, "long_output": 30.0, "long_cache_read": 0.8,
             "long_cache_write": 10.0},
}


def P(i, o, **extra):
    return UnitPrice(input=Decimal(str(i)), output=Decimal(str(o)), **{k: Decimal(str(v)) for k, v in extra.items()})


def _current(i, o, **extra):
    """A stored row as classify_change reads it: every PRICE_FIELDS key, None where the column is NULL."""
    return {**dict.fromkeys(PRICE_FIELDS), "input": i, "output": o, **extra}


def _utc(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _active(*model_ids):
    active = {m: price_identity(m) for m in model_ids}
    assert all(active.values()), active
    return active


def _sol_offer(inp, out, g_inp, g_out, offers=1, extra=()):
    card = [{"dimension": d, "price": p, "description": d, "unit": "Units"} for d, p in (
        ("input_tokens_standard", inp), ("output_tokens_standard", out), ("input_tokens_global_standard", g_inp),
        ("output_tokens_global_standard", g_out), ("input_tokens_priority", "8.8"), *extra)]
    return {"modelId": "openai.gpt-5.6-sol",
            "offers": [{"offerId": SOL_OFFER_ID, "termDetails": {"usageBasedPricingTerm": {"rateCard": card}}}] * offers}


def _nova_items():
    return json.loads((FIXTURES / "pricelist_nova-2-lite.json").read_text(encoding="utf-8"))["PriceList"]


def _fetchers(*, sol=("4.4", "22", "4", "20"), sol_offers=1, fail=(), on_call=None, calls=None, opus_extra=None,
              sol_response=None, pricelist_items=None, openai_md=None, pricelist_args=None, more_offers=None):
    calls = [] if calls is None else calls

    def track(name):
        calls.append(name)
        if on_call is not None:
            on_call(name)
        if name in fail or name.split(":", 1)[0] in fail:
            raise ConnectionError(f"{name} unreachable")

    def offers(fm_id):
        track(f"offers:{fm_id}")
        if fm_id == "anthropic.claude-opus-5-5":
            response = json.loads((FIXTURES / "offers_claude-opus-5-5.json").read_text(encoding="utf-8"))
            response["offers"][0].update(opus_extra or {})
            return response
        if more_offers and fm_id in more_offers:
            return json.loads((FIXTURES / more_offers[fm_id]).read_text(encoding="utf-8"))
        assert fm_id == "openai.gpt-5.6-sol", fm_id
        return sol_response if sol_response is not None else _sol_offer(*sol, offers=sol_offers)

    def pricelist(*usagetypes):
        track("pricelist")
        if pricelist_args is not None:
            pricelist_args.append(usagetypes)
        return pricelist_items if pricelist_items is not None else _nova_items()

    def anthropic_doc():
        track("anthropic_doc")
        return (FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8")

    def openai_doc():
        track("openai_doc")
        return openai_md if openai_md is not None else (FIXTURES / "openai_pricing.md").read_text(encoding="utf-8")

    return Fetchers(offers=offers, pricelist=pricelist, anthropic_doc=anthropic_doc, openai_doc=openai_doc)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)  # same flags as database.SessionLocal
    engine.dispose()


def _seed(Session, values=BASELINE, extras=BASELINE_EXTRAS):
    with Session() as db:
        for model_id, (i, o, source_id) in values.items():
            ident = price_identity(model_id)
            columns = {f"{field}_per_mtok": v for field, v in extras.get(model_id, {}).items()}
            db.add(PriceHistory(model_id=model_id, family_key=ident.family_key, channel=ident.channel,
                                input_per_mtok=i, output_per_mtok=o, effective_from=EPOCH, source_id=source_id,
                                status="seed", observed_at=None, run_id=None, **columns))
        db.commit()


def _extras(row):
    return {field: getattr(row, f"{field}_per_mtok") for field in EXTRA_FIELDS}


def _rows(Session, model_id):
    with Session() as db:
        rows = db.query(PriceHistory).filter(PriceHistory.model_id == model_id).order_by(PriceHistory.id).all()
        db.expunge_all()
        return rows


def _run(Session, run_id):
    with Session() as db:
        run = db.get(PriceSyncRun, run_id)
        db.expunge(run)
        return run


def _sync(Session, at=T0, active=None, **kw):
    return _run(Session, run_sync(Session, active or _active(*ALL), _fetchers(**kw), now=lambda: at))


def test_contract_constants():
    assert (CHANGE_THRESHOLD, SYNC_DEADLINE_S, SYNC_LOCK_KEY) == (Decimal("0.5"), 300.0, 917350004)
    assert SOURCES == ("offers", "pricelist", "anthropic_doc", "openai_doc")


@pytest.mark.parametrize(("current", "new", "expected"), [
    (None, P(1, 5), "no_baseline"),
    ((4.4, 22.0), P("4.4", "22"), "unchanged"),
    ((0.33, 2.75), P("0.3300000000", "2.7500000000"), "unchanged"),  # Price List x1000 vs stored float
    ((4.4, 22.0), P("5.5", "33"), "changed"),       # GPT-5.6 Sol promo end, in-region +25 % / +50 % (boundary)
    ((4.0, 20.0), P("5", "30"), "changed"),         # Global +25 % / +50 % (boundary)
    ((4.4, 22.0), P("5.5", "33.01"), "pending"),    # just over 50 %
    ((10.0, 50.0), P("5", "25"), "changed"),        # exactly -50 %
    ((10.0, 50.0), P("4.99", "50"), "pending"),
    ((0.22, 1.32), P("0.044", "0.264"), "pending"),  # a real -80 % cut waits for review
    ((0.0, 5.0), P("1", "5"), "pending"),           # no ratio against a zero baseline
])
def test_classify_change(current, new, expected):
    assert classify_change(None if current is None else _current(*current), new) == expected


@pytest.mark.parametrize(("current", "new", "expected"), [
    (_current(4.0, 20.0), P(4, 20, cache_read="0.2", cache_write="5"), "enriched"),       # first-time values
    (_current(4.0, 20.0, cache_read=0.2), P(4, 20, cache_read="0.2"), "unchanged"),
    (_current(4.0, 20.0, cache_read=0.2), P(4, 20), "unchanged"),                        # missing = keep, not a change
    (_current(4.0, 20.0, cache_read=0.2), P(4, 20, cache_read="0.3"), "changed"),         # +50 % (boundary)
    (_current(4.0, 20.0, cache_read=0.2), P(4, 20, cache_read="0.31"), "pending"),        # just over 50 %
    (_current(4.0, 20.0, cache_read=0.2), P(4, 20, cache_read="0.2", long_input="8"), "enriched"),
    (_current(4.0, 20.0), P(5, 20, cache_read="0.2"), "changed"),                         # a change beats a fill
    (_current(4.0, 20.0, cache_read=0.2), P(5, 20, cache_read="0.4"), "pending"),         # pending beats a change
    (_current(0.33, 2.75, cache_write=0.0), P("0.33", "2.75", cache_write="0"), "unchanged"),
    (_current(0.33, 2.75, cache_write=0.0), P("0.33", "2.75", cache_write="0.1"), "pending"),  # no ratio against 0
    (_current(10.0, 50.0, long_input=20.0, long_output=75.0), P(10, 50, long_input="20", long_output="75.01"),
     "changed"),
])
def test_classify_change_over_every_price_field(current, new, expected):
    assert classify_change(current, new) == expected


def test_extra_fields_are_quantized_and_zero_is_kept():
    got = pricing_sync._quantized(P("0.33", "2.75", cache_read="0.0825000000", cache_write="0E-10",
                                    long_input="0.00000051"))
    assert (got.cache_read, got.cache_write, got.long_input, got.long_output) == (
        Decimal("0.082500"), Decimal("0"), Decimal("0.000001"), None)
    for bad in ({"cache_read": "-0.1"}, {"cache_write": "0.0000004"}):
        with pytest.raises(PriceParseError, match="negative or rounds to 0"):
            pricing_sync._quantized(P(1, 5, **bad))


def test_same_values_only_refresh_observed_at_and_run_id(Session):
    _seed(Session)
    run = _sync(Session)
    assert (run.status, run.changes, run.pending) == ("completed", 0, 0)
    assert _utc(run.started_at) == T0 and _utc(run.finished_at) == T0
    assert run.summary["channels"] == {m: "unchanged" for m in sorted(ALL)}
    assert run.summary["sources"] == {"offers": {"calls": 2, "ok": 2, "failed": 0},
                                      "pricelist": {"calls": 1, "ok": 1, "failed": 0},
                                      "anthropic_doc": {"calls": 1, "ok": 1, "failed": 0},
                                      "openai_doc": {"calls": 1, "ok": 1, "failed": 0}}
    for model_id in ALL:
        (row,) = _rows(Session, model_id)
        assert row.status == "seed" and _utc(row.effective_from) == EPOCH
        assert _utc(row.observed_at) == T0 and row.run_id == run.id
        assert (row.input_per_mtok, row.output_per_mtok) == BASELINE[model_id][:2]
        assert _extras(row) == {**dict.fromkeys(EXTRA_FIELDS), **BASELINE_EXTRAS.get(model_id, {})}


def test_an_unchanged_value_from_a_new_offer_id_refreshes_the_source_id(Session):
    _seed(Session, {**BASELINE, SOL_E1: (4.4, 22.0, "offer:old")})
    run = _sync(Session)
    assert run.summary["channels"][SOL_E1] == "unchanged" and (run.changes, run.pending) == (0, 0)
    (row,) = _rows(Session, SOL_E1)                                   # no new row, the seed row is re-cited
    assert row.source_id == f"offer:{SOL_OFFER_ID}" and row.status == "seed" and row.run_id == run.id


def test_observed_prices_are_quantized_to_six_decimals_before_compare_and_store(Session):
    _seed(Session)
    run = _sync(Session, sol=("4.4000004", "22.0000001", "4.0000004", "20"))  # 7 decimals = stored value at 6
    assert run.summary["channels"][SOL_E1] == run.summary["channels"][SOL_G] == "unchanged"
    assert (run.changes, run.pending) == (0, 0) and len(_rows(Session, SOL_E1)) == 1
    changed = _sync(Session, at=T1, sol=("5.5000004", "33.0000001", "4", "20"))
    assert changed.summary["channels"][SOL_E1] == "changed"
    _, new = _rows(Session, SOL_E1)
    assert (new.input_per_mtok, new.output_per_mtok) == (5.5, 33.0)  # stored quantized, not 5.5000004


def test_changes_up_to_fifty_percent_apply_from_the_run_start(Session):
    _seed(Session)
    run = _sync(Session, sol=("5.5", "33", "5", "30"))
    assert (run.status, run.changes, run.pending) == ("completed", 2, 0)
    for model_id, values in ((SOL_E1, (5.5, 33.0)), (SOL_G, (5.0, 30.0))):
        assert run.summary["channels"][model_id] == "changed"
        seed, new = _rows(Session, model_id)
        assert seed.status == "seed" and seed.observed_at is None      # the old row stays as history
        assert new.status == "verified" and (new.input_per_mtok, new.output_per_mtok) == values
        assert _utc(new.effective_from) == T0 and _utc(new.observed_at) == T0 and new.run_id == run.id
        assert new.source_id == f"offer:{SOL_OFFER_ID}" and new.channel == price_identity(model_id).channel


def test_a_change_just_over_fifty_percent_waits_for_review(Session):
    _seed(Session)
    run = _sync(Session, sol=("5.5", "33.01", "4", "20"))
    assert run.summary["channels"][SOL_E1] == "pending" and run.summary["channels"][SOL_G] == "unchanged"
    assert (run.changes, run.pending) == (0, 1)
    seed, pending = _rows(Session, SOL_E1)
    assert seed.status == "seed" and seed.observed_at is None      # effective value not re-confirmed
    assert pending.status == "pending_review" and (pending.input_per_mtok, pending.output_per_mtok) == (5.5, 33.01)
    assert _utc(pending.effective_from) == T0 and _utc(pending.observed_at) == T0


def test_the_same_pending_value_is_not_inserted_twice(Session):
    _seed(Session)
    first = _sync(Session, at=T0, sol=("5.5", "33.01", "4", "20"))
    second = _sync(Session, at=T1, sol=("5.5", "33.01", "4", "20"))
    assert second.summary["channels"][SOL_E1] == "pending" and second.pending == 1
    _, pending = _rows(Session, SOL_E1)
    assert _utc(pending.effective_from) == T0                        # the first observing run's start is kept
    assert _utc(pending.observed_at) == T1 and pending.run_id == second.id != first.id


def test_a_rejected_value_does_not_come_back_until_it_changes(Session):
    _seed(Session)
    _sync(Session, at=T0, sol=("5.5", "33.01", "4", "20"))
    with Session() as db:
        db.query(PriceHistory).filter(PriceHistory.status == "pending_review").update({"status": "rejected"})
        db.commit()
    again = _sync(Session, at=T1, sol=("5.5", "33.01", "4", "20"))
    assert again.summary["channels"][SOL_E1] == "rejected" and (again.status, again.pending) == ("completed", 0)
    assert _utc(_rows(Session, SOL_E1)[1].observed_at) == T1
    different = _sync(Session, at=T2, sol=("5.5", "40", "4", "20"))
    assert different.summary["channels"][SOL_E1] == "pending"
    assert [r.status for r in _rows(Session, SOL_E1)] == ["seed", "rejected", "pending_review"]


def test_a_model_without_baseline_is_pending_from_epoch(Session):
    _seed(Session, {k: v for k, v in BASELINE.items() if k != SOL_E1})
    run = _sync(Session)
    assert run.summary["channels"][SOL_E1] == "no_baseline" and run.pending == 1
    (row,) = _rows(Session, SOL_E1)
    assert row.status == "pending_review" and _utc(row.effective_from) == EPOCH and _utc(row.observed_at) == T0
    assert _sync(Session, at=T1).summary["channels"][SOL_E1] == "no_baseline"
    (row,) = _rows(Session, SOL_E1)                                   # de-duplicated, observed again
    assert _utc(row.observed_at) == T1


def test_one_failing_source_changes_nothing_for_its_channels_and_is_partial(Session):
    _seed(Session)
    run = _sync(Session, fail={"anthropic_doc"})
    assert run.status == "partial" and run.summary["channels"][CP_HAIKU] == "skipped:fetch_failed"
    assert all(run.summary["channels"][m] == "unchanged" for m in ALL if m != CP_HAIKU)
    assert run.summary["sources"]["anthropic_doc"] == {"calls": 1, "ok": 0, "failed": 1}
    assert any(e.startswith("anthropic_doc pricing.md: ConnectionError") for e in run.summary["errors"])
    (row,) = _rows(Session, CP_HAIKU)
    assert row.observed_at is None and row.run_id is None


@pytest.mark.parametrize(("kw", "reason"), [({"fail": {"offers:openai.gpt-5.6-sol"}}, "skipped:fetch_failed"),
                                            ({"sol_offers": 2}, "skipped:offer_count")])
def test_one_offer_problem_skips_only_that_models_channels(Session, kw, reason):
    _seed(Session)
    run = _sync(Session, **kw)
    assert run.status == "partial" and run.summary["channels"][OPUS_US] == "unchanged"
    assert run.summary["channels"][SOL_G] == run.summary["channels"][SOL_E1] == reason


def _malformed_nova_items(kind):
    items = [json.loads(s) for s in _nova_items()]
    if kind == "product-not-an-object":
        items.append({"product": "USE1-Nova2.0Lite-input-tokens", "terms": {}})
    else:  # "on-demand-not-an-object"
        for item in items:
            if item["product"]["attributes"]["usagetype"] == "USE1-Nova2.0Lite-output-tokens":
                item["terms"]["OnDemand"] = ["not", "an", "object"]
    return items


@pytest.mark.parametrize("kind", ["product-not-an-object", "on-demand-not-an-object"])
def test_a_malformed_price_list_item_skips_only_nova(Session, kind):
    _seed(Session)
    run = _sync(Session, pricelist_items=_malformed_nova_items(kind))
    assert run.status == "partial" and run.summary["channels"][NOVA] == "skipped:parse_failed"
    assert all(run.summary["channels"][m] == "unchanged" for m in ALL if m != NOVA)  # other sources still apply
    assert run.summary["sources"]["pricelist"] == {"calls": 1, "ok": 1, "failed": 0}
    assert any(e.startswith("pricelist nova-2-lite: price list ") for e in run.summary["errors"])
    (row,) = _rows(Session, NOVA)
    assert row.observed_at is None and row.run_id is None


@pytest.mark.parametrize("response", [
    {"modelId": "openai.gpt-5.6-sol", "offers": "none"},
    _sol_offer("1e999999999", "22", "4", "20"),  # finite, but not representable at 6 decimals (InvalidOperation)
    _sol_offer("0.0000004", "22", "4", "20"),    # positive, but 0 at 6 decimals (never store a zero price)
], ids=["offers-not-a-list", "unquantizable-price", "rounds-to-zero"])
def test_a_malformed_offers_response_skips_only_that_models_channels(Session, response):
    _seed(Session)
    run = _sync(Session, sol_response=response)
    assert run.status == "partial"
    assert run.summary["channels"][SOL_G] == run.summary["channels"][SOL_E1] == "skipped:parse_failed"
    assert all(run.summary["channels"][m] == "unchanged" for m in ALL if m not in (SOL_G, SOL_E1))
    assert run.summary["sources"]["offers"] == {"calls": 2, "ok": 2, "failed": 0}
    assert any(e.startswith("offers openai.gpt-5.6-sol: ") for e in run.summary["errors"])
    assert all(r.observed_at is None for m in (SOL_G, SOL_E1) for r in _rows(Session, m))


@pytest.mark.parametrize(("parser", "skipped"), [
    ("parse_anthropic_pricing_md", {CP_HAIKU}),
    ("parse_pricelist", {NOVA}),
    ("select_offer_price", {OPUS_G, OPUS_US, SOL_G, SOL_E1}),
    ("parse_openai_pricing_md", {OL_SOL}),
])
def test_any_parser_exception_only_skips_that_sources_channels(Session, monkeypatch, parser, skipped):
    _seed(Session)

    def boom(*_args):
        raise KeyError("unexpected shape")

    monkeypatch.setattr(pricing_sync, parser, boom)
    run = _sync(Session)
    assert run.status == "partial" and run.finished_at is not None
    assert {m: r for m, r in run.summary["channels"].items() if r != "unchanged"} == {
        m: "skipped:parse_failed" for m in skipped}
    assert any("KeyError: 'unexpected shape'" in e for e in run.summary["errors"])


def test_no_claude_platform_on_aws_channels_makes_the_run_partial(Session):
    _seed(Session)
    calls = []
    run = _sync(Session, active=_active(*(m for m in ALL if m != CP_HAIKU)), calls=calls)
    assert run.status == "partial" and "anthropic_doc" not in calls
    assert "anthropic_doc: no active channels" in run.summary["errors"] and CP_HAIKU not in run.summary["channels"]


def test_the_deadline_skips_the_remaining_channels(Session, caplog):
    _seed(Session)
    caplog.set_level(logging.INFO, logger="pricing_sync")
    clock, calls = {"t": T0}, []

    def slow(_name):  # every fetch takes 200 s on the fake clock
        clock["t"] += timedelta(seconds=200)

    run = _run(Session, run_sync(Session, _active(*ALL), _fetchers(on_call=slow, calls=calls),
                                 now=lambda: clock["t"], deadline_s=300))
    assert calls == ["anthropic_doc", "openai_doc"]   # 400 s > 300 s before the Price List call
    assert run.status == "partial" and run.summary["channels"][CP_HAIKU] == run.summary["channels"][OL_SOL] == "unchanged"
    assert all(run.summary["channels"][m] == "skipped:deadline" for m in (NOVA, OPUS_G, OPUS_US, SOL_G, SOL_E1))
    assert run.summary["sources"]["offers"] == run.summary["sources"]["pricelist"] == {"calls": 0, "ok": 0, "failed": 0}
    assert any(e.startswith("deadline: 300s exceeded") for e in run.summary["errors"])
    assert "pricing sync: deadline: 300s exceeded before pricelist nova-2-lite" in caplog.messages
    assert _utc(run.finished_at) == T0 + timedelta(seconds=400) and _rows(Session, OPUS_US)[0].observed_at is None


def test_every_summary_error_is_also_a_warning_log_line(Session, caplog):
    _seed(Session)
    caplog.set_level(logging.INFO, logger="pricing_sync")
    fetchers = _fetchers(sol_offers=2, pricelist_items=_malformed_nova_items("product-not-an-object"))
    fetchers.anthropic_doc = lambda: "# Pricing\n\nNo tables here.\n"
    run = _run(Session, run_sync(Session, _active(*ALL), fetchers, now=lambda: T0))
    assert run.status == "partial" and len(run.summary["errors"]) == 3   # CP doc, Nova and Sol all failed to parse
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [f"pricing sync: {e}" for e in run.summary["errors"]]
    assert "pricing sync: anthropic_doc: '## Model pricing' heading not found" in warnings


def test_all_sources_failing_marks_the_run_failed(Session):
    _seed(Session)
    run = _sync(Session, fail={"offers", "pricelist", "anthropic_doc", "openai_doc"})
    assert (run.status, run.changes, run.pending) == ("failed", 0, 0) and _utc(run.finished_at) == T0
    assert set(run.summary["channels"].values()) == {"skipped:fetch_failed"}
    assert all(_rows(Session, m)[0].observed_at is None for m in ALL)


def test_the_run_row_is_committed_as_running_before_the_first_fetch(Session):
    _seed(Session)
    seen = []

    def inspect(_name):
        if not seen:
            with Session() as db:
                seen.append([(r.status, r.finished_at, _utc(r.started_at)) for r in db.query(PriceSyncRun).all()])

    run = _sync(Session, on_call=inspect)
    assert seen == [[("running", None, T0)]]
    assert run.status == "completed" and run.finished_at is not None
    assert set(run.summary) == {"sources", "channels", "errors"} and sorted(run.summary["channels"]) == sorted(ALL)


def test_an_internal_error_marks_the_run_failed_and_reraises(Session, monkeypatch):
    _seed(Session)

    def boom(*_args):
        raise RuntimeError("database went away")

    monkeypatch.setattr(pricing_sync, "_apply", boom)
    with pytest.raises(RuntimeError, match="database went away"):
        run_sync(Session, _active(*ALL), _fetchers(), now=lambda: T0)
    with Session() as db:
        (run,) = db.query(PriceSyncRun).all()
        assert run.status == "failed" and run.finished_at is not None
        assert run.summary["errors"] == ["internal: RuntimeError: database went away"]
        assert db.query(PriceHistory).filter(PriceHistory.observed_at.isnot(None)).count() == 0
    with pytest.raises(ValueError):                   # a naive clock is refused up front
        run_sync(Session, _active(*ALL), _fetchers(), now=lambda: datetime(2026, 9, 26, 15, 0))


def test_offer_token_and_presigned_url_never_reach_logs_summary_or_rows(Session, caplog):
    _seed(Session)
    caplog.set_level(logging.DEBUG)
    extra = {"offerToken": "FAKE-OFFER-TOKEN-123", "legalTerm": {"url": "https://legal.example.invalid/o?sig=FAKE-PRESIGNED-456"}}
    run = _sync(Session, opus_extra=extra, sol_offers=2, fail={"pricelist"})
    with Session() as db:
        blob = caplog.text + json.dumps(run.summary) + json.dumps([r.source_id for r in db.query(PriceHistory).all()])
    assert "FAKE-OFFER-TOKEN" not in blob and "FAKE-PRESIGNED" not in blob


# ---------------------------------------------------------------- default fetchers (fake clients)


class _FakeBedrock:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def list_foundation_model_agreement_offers(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakePricing:
    def __init__(self, pages_by_usagetype):
        self.pages, self.calls = pages_by_usagetype, []

    def get_paginator(self, name):
        assert name == "get_products"
        outer = self

        class _Paginator:
            def paginate(self, **kwargs):
                outer.calls.append(kwargs)
                return iter(outer.pages[kwargs["Filters"][0]["Value"]])

        return _Paginator()


def _client_error(code, status):
    return ClientError({"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": status}}, "Op")


def _raw_offer():
    response = json.loads((FIXTURES / "offers_gpt-6-astra.json").read_text(encoding="utf-8"))
    response["offers"][0]["offerToken"] = "FAKE-OFFER-TOKEN-123"
    response["offers"][0]["termDetails"]["legalTerm"] = {"url": "https://legal.example.invalid/o?sig=FAKE-PRESIGNED-456"}
    response["offers"][0]["termDetails"]["supportTerm"] = {"refundPolicyDescription": "No refunds"}
    return response


def _defaults(bedrock=None, pricing=None, http=None, sleeps=None):
    http = http or httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(599)))
    sleep = sleeps.append if sleeps is not None else (lambda s: None)
    return default_fetchers(bedrock=bedrock or _FakeBedrock([]), pricing=pricing or _FakePricing({}), http=http, sleep=sleep)


def test_default_offers_fetcher_asks_for_public_offers_and_strips_tokens():
    bedrock = _FakeBedrock([_raw_offer()])
    response = _defaults(bedrock=bedrock).offers("openai.gpt-6-astra")
    assert bedrock.calls == [{"modelId": "openai.gpt-6-astra", "offerType": "PUBLIC"}]
    assert not any(s in json.dumps(response) for s in ("offerToken", "legalTerm", "FAKE"))
    offer_id, card = single_public_offer(response)
    assert offer_id == "offer-7epta7rbw5aws" and len(card) == 40


def test_default_pricelist_fetcher_filters_exact_usagetypes_and_follows_pages():
    in_ut, out_ut = "USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens"
    pricing = _FakePricing({in_ut: [{"PriceList": ["a"]}, {"PriceList": ["b"]}], out_ut: [{"PriceList": ["c"]}]})
    assert _defaults(pricing=pricing).pricelist(in_ut, out_ut) == ["a", "b", "c"]
    assert pricing.calls == [{"ServiceCode": "AmazonBedrock", "FormatVersion": "aws_v1",
                              "Filters": [{"Type": "TERM_MATCH", "Field": "usagetype", "Value": ut}]} for ut in (in_ut, out_ut)]


def test_default_anthropic_fetcher_sends_a_user_agent_and_retries_5xx_but_not_404():
    seen, sleeps = [], []

    def handler(request):
        seen.append((str(request.url), request.headers.get("user-agent")))
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, text="## Model pricing\n")

    fetchers = _defaults(http=httpx.Client(transport=httpx.MockTransport(handler)), sleeps=sleeps)
    assert fetchers.anthropic_doc() == "## Model pricing\n"
    assert seen == [(ANTHROPIC_PRICING_URL, pricing_sync.USER_AGENT)] * 2 and sleeps == [1.0]
    sleeps.clear()
    not_found = _defaults(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))), sleeps=sleeps)
    with pytest.raises(httpx.HTTPStatusError):
        not_found.anthropic_doc()
    assert sleeps == []


@pytest.mark.parametrize(("outcomes", "succeeds", "sleeps_expected"), [
    ([_client_error("ThrottlingException", 400), EndpointConnectionError(endpoint_url="https://bedrock"), "ok"], True, [1.0, 2.0]),
    ([_client_error("SomethingElse", 502), "ok"], True, [1.0]),
    ([_client_error("ThrottlingException", 400)] * 4, False, [1.0, 2.0, 4.0]),   # gives up after 3 retries
    ([_client_error("AccessDeniedException", 403), "ok"], False, []),
    ([_client_error("ValidationException", 400), "ok"], False, []),              # e.g. "Agreement not supported"
])
def test_retry_policy(outcomes, succeeds, sleeps_expected):
    bedrock, sleeps = _FakeBedrock([_raw_offer() if o == "ok" else o for o in outcomes]), []
    fetchers = _defaults(bedrock=bedrock, sleeps=sleeps)
    if succeeds:
        assert single_public_offer(fetchers.offers("openai.gpt-6-astra"))[0] == "offer-7epta7rbw5aws"
    else:
        with pytest.raises(ClientError):
            fetchers.offers("openai.gpt-6-astra")
    assert sleeps == sleeps_expected


def test_default_fetchers_build_us_east_1_clients_without_sdk_retries(monkeypatch):
    import types

    import boto3

    made = []
    monkeypatch.setattr(boto3, "client", lambda name, **kw: made.append((name, kw)) or types.SimpleNamespace())
    default_fetchers(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(599))))
    assert [(n, kw["region_name"], kw["config"].retries["max_attempts"]) for n, kw in made] == [
        ("bedrock", "us-east-1", 1), ("pricing", "us-east-1", 1)]


# ---------------------------------------------------------------- v2.31.0: display-only fields, OpenAI doc


def _nova_items_with(cache_write_usd):
    items = [json.loads(s) for s in _nova_items()]
    for item in items:
        if item["product"]["attributes"]["usagetype"] == "USE1-Nova2.0Lite-cache-write-input-token-count":
            (term,) = item["terms"]["OnDemand"].values()
            (dim,) = term["priceDimensions"].values()
            dim["pricePerUnit"]["USD"] = cache_write_usd
    return items


def test_seed_rows_without_extras_are_enriched_in_place(Session):
    _seed(Session, extras={})                                         # v2.30.0 rows: every extra column NULL
    run = _sync(Session)
    assert (run.status, run.changes, run.pending) == ("completed", 0, 0)
    assert run.summary["channels"] == {**{m: "enriched" for m in (OPUS_G, OPUS_US, NOVA, CP_HAIKU, OL_SOL)},
                                       SOL_G: "unchanged", SOL_E1: "unchanged"}   # the fake Sol offer has no extras
    for model_id in ALL:
        (row,) = _rows(Session, model_id)                             # filled in place, no new history row
        assert row.status == "seed" and _utc(row.effective_from) == EPOCH
        assert _utc(row.observed_at) == T0 and row.run_id == run.id
        assert (row.input_per_mtok, row.output_per_mtok) == BASELINE[model_id][:2]
        assert _extras(row) == {**dict.fromkeys(EXTRA_FIELDS), **BASELINE_EXTRAS.get(model_id, {})}, model_id
    (nova,) = _rows(Session, NOVA)
    assert nova.cache_write_per_mtok == 0.0                           # an official $0 is stored as 0, not NULL
    again = _sync(Session, at=T1)
    assert set(again.summary["channels"].values()) == {"unchanged"} and all(len(_rows(Session, m)) == 1 for m in ALL)


SOL_E1_EXTRAS = {"cache_read": 0.44, "cache_write": 5.5, "long_input": 8.8, "long_output": 33.0,
                 "long_cache_read": 0.88, "long_cache_write": 11.0}


def test_a_missing_extra_keeps_the_stored_value_and_a_change_within_fifty_percent_adds_merged_values(Session):
    _seed(Session, extras={**BASELINE_EXTRAS, SOL_E1: SOL_E1_EXTRAS})
    first = _sync(Session)                                            # the fake offer carries no extras for Sol
    assert first.summary["channels"][SOL_E1] == "unchanged"
    (row,) = _rows(Session, SOL_E1)
    assert _extras(row) == {**dict.fromkeys(EXTRA_FIELDS), **SOL_E1_EXTRAS}
    offer = _sol_offer("4.4", "22", "4", "20", extra=(("cache_read_tokens_standard", "0.5"),))  # 0.44 -> 0.5, +13.6 %
    run = _sync(Session, at=T1, sol_response=offer)
    assert run.summary["channels"][SOL_E1] == "changed" and run.summary["channels"][SOL_G] == "unchanged"
    assert (run.changes, run.pending) == (1, 0)
    seed, new = _rows(Session, SOL_E1)
    assert seed.status == "seed" and seed.cache_read_per_mtok == 0.44
    assert new.status == "verified" and _utc(new.effective_from) == T1 and _utc(new.observed_at) == T1
    assert (new.input_per_mtok, new.output_per_mtok) == (4.4, 22.0)
    assert _extras(new) == {**dict.fromkeys(EXTRA_FIELDS), **SOL_E1_EXTRAS, "cache_read": 0.5}  # merged


def test_an_extra_change_over_fifty_percent_waits_for_review_and_held_rows_match_every_value(Session):
    _seed(Session, extras={**BASELINE_EXTRAS, SOL_E1: {"cache_read": 0.2}})
    offer = _sol_offer("4.4", "22", "4", "20", extra=(("cache_read_tokens_standard", "0.44"),))  # +120 %
    run = _sync(Session, sol_response=offer)
    assert run.summary["channels"][SOL_E1] == "pending" and (run.changes, run.pending) == (0, 1)
    seed, pending = _rows(Session, SOL_E1)
    assert seed.observed_at is None and seed.cache_read_per_mtok == 0.2   # the effective row is not re-confirmed
    assert pending.status == "pending_review" and _utc(pending.effective_from) == T0
    assert _extras(pending) == {**dict.fromkeys(EXTRA_FIELDS), "cache_read": 0.44}
    again = _sync(Session, at=T1, sol_response=offer)
    assert again.summary["channels"][SOL_E1] == "pending" and len(_rows(Session, SOL_E1)) == 2
    assert _utc(_rows(Session, SOL_E1)[1].observed_at) == T1           # the same held row, observed again
    more = _sol_offer("4.4", "22", "4", "20", extra=(("cache_read_tokens_standard", "0.44"),
                                                     ("cache_write_tokens_30m_standard", "5.5")))
    third = _sync(Session, at=T2, sol_response=more)                    # one more value: no longer the held row
    assert third.summary["channels"][SOL_E1] == "pending"
    _, _, newest = _rows(Session, SOL_E1)
    assert newest.status == "pending_review" and (newest.cache_read_per_mtok, newest.cache_write_per_mtok) == (0.44, 5.5)


def test_a_zero_extra_price_that_turns_positive_waits_for_review(Session):
    _seed(Session)                                                      # Nova cache write stored as 0
    run = _sync(Session, pricelist_items=_nova_items_with("0.0001000000"))  # $0.0001 per 1K = $0.1 per 1M
    assert run.summary["channels"][NOVA] == "pending" and run.pending == 1
    seed, pending = _rows(Session, NOVA)
    assert seed.cache_write_per_mtok == 0.0 and pending.status == "pending_review"
    assert (pending.input_per_mtok, pending.output_per_mtok, pending.cache_read_per_mtok, pending.cache_write_per_mtok) == (
        0.33, 2.75, 0.0825, 0.1)


def test_the_price_list_call_passes_the_nova_cache_usagetypes(Session):
    _seed(Session, extras={})
    seen: list[tuple] = []
    run = _sync(Session, pricelist_args=seen)
    assert seen == [("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens",
                     "USE1-Nova2.0Lite-cache-read-input-token-count", "USE1-Nova2.0Lite-cache-write-input-token-count")]
    assert run.summary["channels"][NOVA] == "enriched"
    (row,) = _rows(Session, NOVA)
    assert (row.cache_read_per_mtok, row.cache_write_per_mtok) == (0.0825, 0.0)


def test_an_openai_doc_failure_skips_only_the_openai_list_channels(Session):
    _seed(Session)
    run = _sync(Session, fail={"openai_doc"})
    assert run.status == "partial" and run.summary["channels"][OL_SOL] == "skipped:fetch_failed"
    assert all(run.summary["channels"][m] == "unchanged" for m in ALL if m != OL_SOL)
    assert run.summary["sources"]["openai_doc"] == {"calls": 1, "ok": 0, "failed": 1}
    assert any(e.startswith("openai_doc pricing.md: ConnectionError") for e in run.summary["errors"])
    (row,) = _rows(Session, OL_SOL)
    assert row.observed_at is None and row.run_id is None


def test_an_openai_list_model_missing_from_the_doc_is_skipped_not_found(Session):
    _seed(Session)
    text = (FIXTURES / "openai_pricing.md").read_text(encoding="utf-8")
    without_sol = "\n".join(ln for ln in text.splitlines() if not ln.startswith("| gpt-5.6-sol |"))
    run = _sync(Session, openai_md=without_sol)
    assert run.status == "partial" and run.summary["channels"][OL_SOL] == "skipped:not_found"
    assert "openai_doc: model 'gpt-5.6-sol' not in the table" in run.summary["errors"]
    assert run.summary["sources"]["openai_doc"] == {"calls": 1, "ok": 1, "failed": 0}
    assert all(run.summary["channels"][m] == "unchanged" for m in ALL if m != OL_SOL)


def test_an_extra_price_that_rounds_to_zero_skips_that_models_channels(Session):
    _seed(Session)
    offer = _sol_offer("4.4", "22", "4", "20", extra=(("cache_read_tokens_standard", "0.0000004"),))
    run = _sync(Session, sol_response=offer)
    assert run.summary["channels"][SOL_G] == run.summary["channels"][SOL_E1] == "skipped:parse_failed"
    assert any(e.startswith("offers openai.gpt-5.6-sol: cache_read price is negative or rounds to 0")
               for e in run.summary["errors"])


@pytest.mark.parametrize(("status", "result"), [("pending_review", "pending"), ("rejected", "rejected")])
def test_a_v2_30_held_row_without_extras_is_matched_on_input_and_output(Session, status, result):
    _seed(Session)
    ident = price_identity(SOL_E1)
    held_at = T0 - timedelta(hours=12)
    with Session() as db:  # held under v2.30.0, before the extra columns existed: every extra column NULL
        db.add(PriceHistory(model_id=SOL_E1, family_key=ident.family_key, channel=ident.channel,
                            input_per_mtok=8.8, output_per_mtok=44.0, effective_from=held_at,
                            source_id=f"offer:{SOL_OFFER_ID}", status=status, observed_at=held_at, run_id=None))
        db.commit()
    # The same input and output again (+100 %), now with a cache price the v2.30.0 row never had.
    offer = _sol_offer("8.8", "44", "4", "20", extra=(("cache_read_tokens_standard", "0.88"),))
    run = _sync(Session, sol_response=offer)
    assert run.summary["channels"][SOL_E1] == result
    seed, held = _rows(Session, SOL_E1)                  # no second pending_review row, a rejection stays rejected
    assert seed.status == "seed" and held.status == status
    assert _utc(held.observed_at) == T0 and held.cache_read_per_mtok is None


def test_a_long_context_dimension_on_a_claude_offer_is_dropped(Session):
    _seed(Session)
    response = json.loads((FIXTURES / "offers_claude-opus-5-5.json").read_text(encoding="utf-8"))
    term = response["offers"][0]["termDetails"]
    term["usageBasedPricingTerm"]["rateCard"] += [
        {"dimension": d, "price": p, "description": d, "unit": "Units"}
        for d, p in (("APN2_input_tokens_long_ctx_global_standard", "8"),
                     ("APN2_output_tokens_long_ctx_global_standard", "40"))]
    run = _sync(Session, opus_extra={"termDetails": term})
    assert run.summary["channels"][OPUS_G] == "unchanged"   # long context is GPT-only: nothing to fill ("enriched")
    (row,) = _rows(Session, OPUS_G)
    assert (row.long_input_per_mtok, row.long_output_per_mtok) == (None, None)


def test_an_odd_untracked_openai_doc_row_never_skips_the_tracked_channels(Session):
    _seed(Session)
    text = (FIXTURES / "openai_pricing.md").read_text(encoding="utf-8")
    odd = ("| gpt-free-preview | $0.00 | - | - | $0.00 | - | - | - | - |\n"             # input and output $0.00
           "| gpt-tiny-preview | $0.10 | $0.0000001 | - | $0.40 | - | - | - | - |\n")  # cached input rounds to 0
    run = _sync(Session, openai_md=text.replace("| gpt-6-astra |", odd + "| gpt-6-astra |", 1))
    assert run.status == "completed" and run.summary["channels"][OL_SOL] == "unchanged"
    assert not any("preview" in e for e in run.summary["errors"])


def test_a_tracked_openai_doc_value_that_rounds_to_zero_skips_only_that_models_channel(Session):
    ol_6sol = "openai-list:gpt-6-sol"             # a second tracked OpenAI official price from the same doc table
    _seed(Session, values={**BASELINE, ol_6sol: (2.0, 10.0, "openai-pricing")},
          extras={**BASELINE_EXTRAS, ol_6sol: {"cache_read": 0.2, "cache_write": 2.5, "long_input": 4.0,
                                              "long_output": 15.0, "long_cache_read": 0.4, "long_cache_write": 5.0}})
    text = (FIXTURES / "openai_pricing.md").read_text(encoding="utf-8")
    row = "| gpt-5.6-sol | $4.00 | $0.40 |"
    assert row in text
    bad = text.replace(row, "| gpt-5.6-sol | $4.00 | $0.0000001 |", 1)   # short-context cached input rounds to 0
    run = _run(Session, run_sync(Session, _active(*ALL, ol_6sol), _fetchers(openai_md=bad), now=lambda: T0))
    assert run.status == "partial"
    assert run.summary["channels"][OL_SOL] == "skipped:parse_failed"
    assert all(run.summary["channels"][m] == "unchanged" for m in (*ALL, ol_6sol) if m != OL_SOL)
    assert run.summary["sources"]["openai_doc"] == {"calls": 1, "ok": 1, "failed": 0}
    (error,) = [e for e in run.summary["errors"] if e.startswith("openai_doc")]
    assert error.startswith("openai_doc gpt-5.6-sol: cache_read price is negative or rounds to 0 at 6 decimals"), error
    (stored,) = _rows(Session, OL_SOL)
    assert stored.observed_at is None and stored.cache_read_per_mtok == 0.4    # the stored row is left alone


def test_default_openai_fetcher_sends_a_user_agent_and_retries_5xx():
    seen, sleeps = [], []

    def handler(request):
        seen.append((str(request.url), request.headers.get("user-agent")))
        return httpx.Response(502) if len(seen) == 1 else httpx.Response(200, text="### Standard pricing data\n")

    fetchers = _defaults(http=httpx.Client(transport=httpx.MockTransport(handler)), sleeps=sleeps)
    assert fetchers.openai_doc() == "### Standard pricing data\n"
    assert seen == [(OPENAI_PRICING_URL, pricing_sync.USER_AGENT)] * 2 and sleeps == [1.0]


def test_default_pricelist_fetcher_queries_every_usagetype_in_order():
    uts = ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens",
           "USE1-Nova2.0Lite-cache-read-input-token-count", "USE1-Nova2.0Lite-cache-write-input-token-count")
    pricing = _FakePricing({uts[0]: [{"PriceList": ["a"]}], uts[1]: [{"PriceList": ["b"]}, {"PriceList": ["c"]}],
                            uts[2]: [{"PriceList": ["d"]}], uts[3]: [{"PriceList": []}]})
    assert _defaults(pricing=pricing).pricelist(*uts) == ["a", "b", "c", "d"]
    assert [c["Filters"][0]["Value"] for c in pricing.calls] == list(uts)


# ---------------------------------------------------------------- v2.32.0: implausible long context, Seoul in-region

G61 = ("openai:global:global.openai.gpt-6.1-sol", "openai:us:us.openai.gpt-6.1-sol", "openai:us-east-1:openai.gpt-6.1-sol")
G61_SEED = {G61[0]: (2.0, 10.0, "offer:offer-wbhj4kycntgkk"), G61[1]: (2.2, 11.0, "offer:offer-wbhj4kycntgkk"),
            G61[2]: (2.2, 11.0, "offer:offer-wbhj4kycntgkk")}
G61_EXTRAS = {G61[0]: {"cache_read": 0.1, "cache_write": 2.5}, G61[1]: {"cache_read": 0.11, "cache_write": 2.75},
              G61[2]: {"cache_read": 0.11, "cache_write": 2.75}}


@pytest.mark.parametrize(("price", "dropped"), [
    (P(2, 10, long_input=4, long_output=2, long_cache_read="0.2", long_cache_write=5), True),   # 2026-09-30 GPT 6.1 Sol
    (P(2, 10, long_input="1.9", long_output=15), True),                                       # long input below input
    (P(2, 10, long_input=4, long_output=15, long_cache_read="0.2", long_cache_write=5), False),
    (P(3, 15, long_input=3, long_output=15), False),                                          # equal is plausible
    (P(2, 10, cache_read="0.1"), False),                                                      # no long prices at all
])
def test_plausible_long_drops_all_four_long_prices_only_when_below_short_context(price, dropped):
    got = pricing_sync._plausible_long(price, "test")
    long = (got.long_input, got.long_output, got.long_cache_read, got.long_cache_write)
    assert (long == (None,) * 4) if dropped else (got == price)
    assert (got.input, got.output, got.cache_read) == (price.input, price.output, price.cache_read)


def test_an_implausible_long_context_offer_price_is_never_stored(Session, caplog):
    _seed(Session, values=G61_SEED, extras=G61_EXTRAS)
    caplog.set_level(logging.INFO, logger="pricing_sync")
    run = _sync(Session, active=_active(*G61), more_offers={"openai.gpt-6.1-sol": "offers_gpt-6.1-sol.json"})
    assert run.summary["channels"] == {m: "unchanged" for m in sorted(G61)}   # long None = ignored, not "enriched"
    for model_id in G61:
        (row,) = _rows(Session, model_id)
        assert (row.long_input_per_mtok, row.long_output_per_mtok, row.long_cache_read_per_mtok,
                row.long_cache_write_per_mtok) == (None,) * 4
    assert any("offers openai.gpt-6.1-sol global: long-context price below the short-context price" in m
               for m in caplog.messages)
    assert not any("gpt-6.1-sol" in e for e in run.summary["errors"])      # a warning line, not a run error


def test_the_openai_doc_long_context_price_of_gpt_61_sol_is_kept(Session):
    ol = "openai-list:gpt-6.1-sol"
    _seed(Session, values={ol: (2.0, 10.0, "openai-pricing")}, extras={})
    run = _sync(Session, active=_active(ol))
    assert run.summary["channels"][ol] == "enriched"
    (row,) = _rows(Session, ol)
    assert (row.long_input_per_mtok, row.long_output_per_mtok, row.long_cache_read_per_mtok,
            row.long_cache_write_per_mtok) == (4.0, 15.0, 0.2, 5.0)


def test_seoul_in_region_shares_one_offer_call_with_the_cris_channels(Session):
    opus = ("global.anthropic.claude-opus-5", "us.anthropic.claude-opus-5", "bedrock:ap-northeast-2:anthropic.claude-opus-5")
    src = "offer:offer-f3u6lgbrem3zs"
    _seed(Session, values={opus[0]: (5.0, 25.0, src), opus[1]: (5.5, 27.5, src), opus[2]: (5.5, 27.5, src)},
          extras={opus[0]: {"cache_read": 0.5, "cache_write": 6.25, "cache_write_1h": 10.0},
                  opus[1]: {"cache_read": 0.55, "cache_write": 6.875, "cache_write_1h": 11.0},
                  opus[2]: {"cache_read": 0.55, "cache_write": 6.875, "cache_write_1h": 11.0}})
    calls = []
    run = _sync(Session, active=_active(*opus), calls=calls,
                more_offers={"anthropic.claude-opus-5": "offers_claude-opus-5.json"})
    assert calls.count("offers:anthropic.claude-opus-5") == 1
    assert run.summary["channels"] == {m: "unchanged" for m in sorted(opus)}
    assert run.summary["sources"]["offers"] == {"calls": 1, "ok": 1, "failed": 0}
