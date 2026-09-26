"""Cost and efficiency endpoints with time-effective prices (v2.30.0, ADR-030).

/api/cost/summary, /api/cost/channel-compare, /api/cost/trend and /api/efficiency/score read the price that
was effective at each probe's timestamp from price_history. The equivalence test pins the new calculation
to a frozen copy of the v2.29.1 table (tests/_legacy_pricing_v2291.py) on the 44 channels whose price did
not change, and pins the 11 corrected channels (Bedrock Claude US x1.1, Nova 2.0 Lite) to official values.
All data lives in in-memory SQLite; no network.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_seed
from database import get_db
from pricing_sources import EPOCH, price_identity
from routers import cost as cost_router
from routers import efficiency as efficiency_router
from tests import _legacy_pricing_v2291 as legacy

NOW = datetime.now(timezone.utc)
HOUR = NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
CHANGE_AT = HOUR + timedelta(hours=1)  # verified price change inside the 24h window
A = ("global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)")
UNKNOWN = ("mystery.model-v9", "Bedrock Mystery (Global)")
HIDDEN = ("openai:1p:gpt-5.4", "OpenAI GPT 5.4 (1P)")

# Production /api/models on 2026-09-26: the 55 active channels (CP ids come from discovery).
_CLAUDE = ("claude-fable-5-1", "claude-fable-5", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8",
           "claude-opus-4-7", "claude-opus-4-6-v1", "claude-sonnet-5", "claude-sonnet-4-6",
           "claude-haiku-4-5-20251001-v1:0")
BEDROCK_GLOBAL = [f"global.anthropic.{m}" for m in _CLAUDE]
BEDROCK_US = [f"us.anthropic.{m}" for m in _CLAUDE]
NOVA = "us.amazon.nova-2-lite-v1:0"
CP = [f"anthropic:claude-{m}" for m in ("fable-5-1", "fable-5", "opus-5-5", "opus-5", "opus-4-8", "opus-4-7",
                                        "sonnet-5", "sonnet-4-6", "haiku-4-5-20251001")]
OPENAI = (
    [f"openai:global:global.openai.gpt-6-{f}" for f in ("astra", "sol", "luna")]
    + [f"openai:us:us.openai.gpt-6-{f}" for f in ("astra", "sol", "luna")]
    + ["openai:us-west-2:openai.gpt-6-astra", "openai:us-east-1:openai.gpt-6-sol", "openai:us-east-1:openai.gpt-6-luna"]
    + [f"openai:global:global.openai.gpt-5.6-{f}" for f in ("sol", "terra", "luna")]
    + [f"openai:{r}:openai.gpt-5.6-{f}" for r in ("us-east-1", "us-east-2") for f in ("sol", "terra", "luna")]
    + [f"openai:us-west-2:openai.gpt-5.6-{f}" for f in ("terra", "luna")]
    + [f"openai:{r}:openai.gpt-5.5" for r in ("us-east-1", "us-east-2")]
    + [f"openai:{r}:openai.gpt-5.4" for r in ("us-east-1", "us-east-2", "us-west-2")]
)
ACTIVE_IDS = BEDROCK_GLOBAL + BEDROCK_US + [NOVA] + CP + OPENAI
UNCHANGED = BEDROCK_GLOBAL + CP + OPENAI
CORRECTED = {
    "us.anthropic.claude-fable-5-1": (11.0, 55.0),
    "us.anthropic.claude-fable-5": (11.0, 55.0),
    "us.anthropic.claude-opus-5-5": (4.4, 22.0),
    "us.anthropic.claude-opus-5": (5.5, 27.5),
    "us.anthropic.claude-opus-4-8": (5.5, 27.5),
    "us.anthropic.claude-opus-4-7": (5.5, 27.5),
    "us.anthropic.claude-opus-4-6-v1": (5.5, 27.5),
    "us.anthropic.claude-sonnet-5": (2.2, 11.0),
    "us.anthropic.claude-sonnet-4-6": (3.3, 16.5),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.1, 5.5),
    NOVA: (0.33, 2.75),
}


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    with factory() as db:
        db.add(models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=NOW))
        db.commit()

    app = FastAPI()
    app.include_router(cost_router.router)
    app.include_router(efficiency_router.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as client:
        yield engine, factory, client
    engine.dispose()


def _price(factory, model_id, inp, out, effective_from, *, status="verified"):
    ident = price_identity(model_id)
    with factory() as db:
        db.add(models.PriceHistory(
            model_id=model_id, family_key=ident.family_key if ident else "unknown",
            channel=ident.channel if ident else "global", input_per_mtok=inp, output_per_mtok=out,
            effective_from=effective_from, source_id="offer:offer-test", status=status,
            observed_at=None if status == "seed" else effective_from,
        ))
        db.commit()


def _probe(factory, model, ts, input_tokens, output_tokens, *, status="success", category="chat-short"):
    model_id, model_name = model
    with factory() as db:
        db.add(models.ProbeResult(
            run_id=1, model_id=model_id, model_name=model_name, timestamp=ts, prompt="p", status=status,
            input_tokens=input_tokens, output_tokens=output_tokens, total_latency_ms=1000.0, tps=50.0,
            category=category,
        ))
        db.commit()


def _price_change_dataset(factory):
    """A: $1/$5 seed, then $2/$10 from CHANGE_AT. One probe on each side, plus unpriced/error/hidden rows."""
    _price(factory, A[0], 1.0, 5.0, EPOCH, status="seed")
    _price(factory, A[0], 2.0, 10.0, CHANGE_AT)
    _price(factory, HIDDEN[0], 2.75, 16.5, EPOCH, status="seed")
    _probe(factory, A, HOUR + timedelta(minutes=10), 100_000, 100_000)       # old price: 0.6
    _probe(factory, A, CHANGE_AT + timedelta(hours=1, minutes=10), 100_000, 100_000)  # new price: 1.2
    _probe(factory, A, CHANGE_AT + timedelta(minutes=20), None, None, status="error")
    _probe(factory, UNKNOWN, HOUR + timedelta(minutes=15), 1_000, 2_000)
    _probe(factory, HIDDEN, HOUR + timedelta(minutes=15), 1_000_000, 1_000_000)


def test_summary_sums_each_probe_at_its_own_price(env):
    _, factory, client = env
    _price_change_dataset(factory)
    body = client.get("/api/cost/summary?window=24h").json()
    rows = {r["model_id"]: r for r in body["rows"]}
    assert set(rows) == {A[0], UNKNOWN[0]}  # error rows filtered, (1P) hidden
    assert rows[A[0]]["samples"] == 2
    assert rows[A[0]]["input_tokens"] == 200_000
    assert rows[A[0]]["cost_usd"] == pytest.approx(0.6 + 1.2)
    assert rows[A[0]]["avg_cost_per_call_usd"] == pytest.approx(0.9)
    assert rows[UNKNOWN[0]]["cost_usd"] is None  # no price row -> NULL, shown as "-"
    assert rows[UNKNOWN[0]]["avg_cost_per_call_usd"] is None
    assert body["total_cost_usd"] == pytest.approx(1.8)
    assert body["total_input_tokens"] == 201_000  # unpriced tokens still count
    assert body["total_output_tokens"] == 202_000
    assert [r["model_id"] for r in body["rows"]] == [A[0], UNKNOWN[0]]


def test_channel_compare_adds_unpriced_models_as_zero(env):
    _, factory, client = env
    _price_change_dataset(factory)
    channels = {c["channel"]: c for c in client.get("/api/cost/channel-compare?window=24h").json()["channels"]}
    assert set(channels) == {"Bedrock Global", "Other"}
    assert channels["Bedrock Global"]["cost_usd"] == pytest.approx(1.8)
    assert channels["Bedrock Global"]["samples"] == 2
    assert channels["Other"]["cost_usd"] == 0.0
    assert channels["Other"]["input_tokens"] == 1_000


def test_trend_buckets_per_row_cost(env):
    _, factory, client = env
    _price_change_dataset(factory)
    body = client.get("/api/cost/trend?window=24h").json()
    assert body["bucket_minutes"] == 60
    points = [(p["bucket"], p["model_name"], p["cost_usd"]) for p in body["points"]]
    assert points == [
        (HOUR.isoformat(), A[1], pytest.approx(0.6)),
        ((HOUR + timedelta(hours=2)).isoformat(), A[1], pytest.approx(1.2)),
    ]  # unpriced model has no points, error and hidden rows are filtered


def test_efficiency_averages_priced_success_rows_only(env):
    _, factory, client = env
    _price_change_dataset(factory)
    got = {m["model_id"]: m for m in client.get("/api/efficiency/score?window=24h").json()["models"]}
    assert set(got) == {A[0], UNKNOWN[0]}
    assert got[A[0]]["samples"] == 3  # the error row counts as a sample, not as a cost
    assert got[A[0]]["success_rate"] == pytest.approx(0.6667)
    assert got[A[0]]["avg_cost_usd"] == pytest.approx(0.9)
    assert got[UNKNOWN[0]]["avg_cost_usd"] is None
    assert got[UNKNOWN[0]]["components"]["cost"] is None


def test_efficiency_category_filter_still_applies(env):
    _, factory, client = env
    _price(factory, A[0], 1.0, 5.0, EPOCH, status="seed")
    _probe(factory, A, HOUR, 100_000, 100_000, category="reasoning")
    _probe(factory, A, HOUR, 200_000, 200_000, category="translate")
    got = client.get("/api/efficiency/score?window=24h&category=reasoning").json()["models"]
    assert [(m["model_id"], m["samples"], m["avg_cost_usd"]) for m in got] == [(A[0], 1, pytest.approx(0.6))]


def test_seeded_costs_match_v2291_on_unchanged_channels_and_fix_the_11_corrected_ones(env):
    engine, factory, client = env
    active = {mid: price_identity(mid) for mid in ACTIVE_IDS}
    assert len(active) == 55 and all(active.values()), [m for m, i in active.items() if i is None]
    assert len(UNCHANGED) == 44 and len(CORRECTED) == 11
    pricing_seed.ensure_seed(engine, active)
    in_tok, out_tok = 12_345, 6_789
    for mid in ACTIVE_IDS:
        _probe(factory, (mid, f"label {mid}"), NOW - timedelta(hours=1), in_tok, out_tok)

    rows = {r["model_id"]: r["cost_usd"] for r in client.get("/api/cost/summary?window=24h").json()["rows"]}
    assert set(rows) == set(ACTIVE_IDS)
    for mid in UNCHANGED:
        assert type(rows[mid]) is float, mid
        assert rows[mid] == pytest.approx(legacy.estimate_cost_usd(mid, in_tok, out_tok), rel=1e-12), mid
    for mid, (inp, out) in CORRECTED.items():
        assert rows[mid] == pytest.approx((in_tok * inp + out_tok * out) / 1_000_000.0, rel=1e-12), mid
        assert rows[mid] != pytest.approx(legacy.estimate_cost_usd(mid, in_tok, out_tok), rel=1e-6), mid
