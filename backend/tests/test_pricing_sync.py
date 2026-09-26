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
from pricing_parsers import UnitPrice, single_public_offer
from pricing_sources import ANTHROPIC_PRICING_URL, EPOCH, price_identity
from pricing_sync import CHANGE_THRESHOLD, SYNC_DEADLINE_S, SYNC_LOCK_KEY, Fetchers, classify_change, default_fetchers, run_sync

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
T0 = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
T1, T2 = T0 + timedelta(hours=12), T0 + timedelta(hours=24)
OPUS_G, OPUS_US = "global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5"
SOL_G, SOL_E1 = "openai:global:global.openai.gpt-5.6-sol", "openai:us-east-1:openai.gpt-5.6-sol"
NOVA = "us.amazon.nova-2-lite-v1:0"
CP_HAIKU = "anthropic:claude-haiku-4-5-20251001"  # CP ids carry the /v1/models date suffix
ALL = (OPUS_G, OPUS_US, SOL_G, SOL_E1, NOVA, CP_HAIKU)
SOL_OFFER_ID = "offer-gnqokrqqvdbgw"
BASELINE = {  # current official values = seed rows: (input, output, source_id)
    OPUS_G: (4.0, 20.0, "offer:offer-7sp77cpl4rveu"), OPUS_US: (4.4, 22.0, "offer:offer-7sp77cpl4rveu"),
    SOL_G: (4.0, 20.0, f"offer:{SOL_OFFER_ID}"), SOL_E1: (4.4, 22.0, f"offer:{SOL_OFFER_ID}"),
    NOVA: (0.33, 2.75, "pricelist:USE1-Nova2.0Lite-input-tokens"), CP_HAIKU: (1.0, 5.0, "anthropic-pricing"),
}


def P(i, o):
    return UnitPrice(input=Decimal(str(i)), output=Decimal(str(o)))


def _utc(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _active(*model_ids):
    active = {m: price_identity(m) for m in model_ids}
    assert all(active.values()), active
    return active


def _sol_offer(inp, out, g_inp, g_out, offers=1):
    card = [{"dimension": d, "price": p, "description": d, "unit": "Units"} for d, p in (
        ("input_tokens_standard", inp), ("output_tokens_standard", out), ("input_tokens_global_standard", g_inp),
        ("output_tokens_global_standard", g_out), ("input_tokens_priority", "8.8"))]
    return {"modelId": "openai.gpt-5.6-sol",
            "offers": [{"offerId": SOL_OFFER_ID, "termDetails": {"usageBasedPricingTerm": {"rateCard": card}}}] * offers}


def _fetchers(*, sol=("4.4", "22", "4", "20"), sol_offers=1, fail=(), on_call=None, calls=None, opus_extra=None):
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
        assert fm_id == "openai.gpt-5.6-sol", fm_id
        return _sol_offer(*sol, offers=sol_offers)

    def pricelist(input_usagetype, output_usagetype):
        track("pricelist")
        return json.loads((FIXTURES / "pricelist_nova-2-lite.json").read_text(encoding="utf-8"))["PriceList"]

    def anthropic_doc():
        track("anthropic_doc")
        return (FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8")

    return Fetchers(offers=offers, pricelist=pricelist, anthropic_doc=anthropic_doc)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)  # same flags as database.SessionLocal
    engine.dispose()


def _seed(Session, values=BASELINE):
    with Session() as db:
        for model_id, (i, o, source_id) in values.items():
            ident = price_identity(model_id)
            db.add(PriceHistory(model_id=model_id, family_key=ident.family_key, channel=ident.channel,
                                input_per_mtok=i, output_per_mtok=o, effective_from=EPOCH, source_id=source_id,
                                status="seed", observed_at=None, run_id=None))
        db.commit()


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
    assert classify_change(current, new) == expected


def test_same_values_only_refresh_observed_at_and_run_id(Session):
    _seed(Session)
    run = _sync(Session)
    assert (run.status, run.changes, run.pending) == ("completed", 0, 0)
    assert _utc(run.started_at) == T0 and _utc(run.finished_at) == T0
    assert run.summary["channels"] == {m: "unchanged" for m in sorted(ALL)}
    assert run.summary["sources"] == {"offers": {"calls": 2, "ok": 2, "failed": 0},
                                      "pricelist": {"calls": 1, "ok": 1, "failed": 0},
                                      "anthropic_doc": {"calls": 1, "ok": 1, "failed": 0}}
    for model_id in ALL:
        (row,) = _rows(Session, model_id)
        assert row.status == "seed" and _utc(row.effective_from) == EPOCH
        assert _utc(row.observed_at) == T0 and row.run_id == run.id
        assert (row.input_per_mtok, row.output_per_mtok) == BASELINE[model_id][:2]


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


def test_no_claude_platform_on_aws_channels_makes_the_run_partial(Session):
    _seed(Session)
    calls = []
    run = _sync(Session, active=_active(*(m for m in ALL if m != CP_HAIKU)), calls=calls)
    assert run.status == "partial" and "anthropic_doc" not in calls
    assert "anthropic_doc: no active channels" in run.summary["errors"] and CP_HAIKU not in run.summary["channels"]


def test_the_deadline_skips_the_remaining_channels(Session):
    _seed(Session)
    clock, calls = {"t": T0}, []

    def slow(_name):  # every fetch takes 200 s on the fake clock
        clock["t"] += timedelta(seconds=200)

    run = _run(Session, run_sync(Session, _active(*ALL), _fetchers(on_call=slow, calls=calls),
                                 now=lambda: clock["t"], deadline_s=300))
    assert calls == ["anthropic_doc", "pricelist"]   # 400 s > 300 s before the first offer call
    assert run.status == "partial" and run.summary["channels"][CP_HAIKU] == run.summary["channels"][NOVA] == "unchanged"
    assert all(run.summary["channels"][m] == "skipped:deadline" for m in (OPUS_G, OPUS_US, SOL_G, SOL_E1))
    assert run.summary["sources"]["offers"] == {"calls": 0, "ok": 0, "failed": 0}
    assert any(e.startswith("deadline: 300s exceeded") for e in run.summary["errors"])
    assert _utc(run.finished_at) == T0 + timedelta(seconds=400) and _rows(Session, OPUS_US)[0].observed_at is None


def test_all_sources_failing_marks_the_run_failed(Session):
    _seed(Session)
    run = _sync(Session, fail={"offers", "pricelist", "anthropic_doc"})
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
    assert offer_id == "offer-7epta7rbw5aws" and len(card) == 18


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
