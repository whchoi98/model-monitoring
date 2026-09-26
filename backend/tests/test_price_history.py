"""price_history.py — time-effective price join, current/pending rows, verification state (v2.30.0, ADR-030).

All data lives in in-memory SQLite built by Base.metadata.create_all; no network. Every timestamp is a
timezone-aware datetime bound through the ORM.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from price_history import (
    as_utc,
    current_rows,
    last_finished_run,
    pending_rows,
    verification_of,
    with_row_cost,
)
from pricing_sources import EPOCH

T = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
M = "global.anthropic.claude-sonnet-5"
M_TOKENS = 1_000_000


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    run = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=T)
    session.add(run)
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _price(db, model_id, inp, out, effective_from, *, status="verified", observed_at=None,
           source_id="offer:offer-test", channel="global", family_key="claude-sonnet-5"):
    row = models.PriceHistory(
        model_id=model_id, family_key=family_key, channel=channel,
        input_per_mtok=inp, output_per_mtok=out, effective_from=effective_from,
        source_id=source_id, status=status, observed_at=observed_at,
    )
    db.add(row)
    db.commit()
    return row


def _probe(db, model_id, ts, input_tokens=M_TOKENS, output_tokens=M_TOKENS, *, status="success"):
    row = models.ProbeResult(
        run_id=1, model_id=model_id, model_name=f"label {model_id}", timestamp=ts, prompt="p",
        status=status, input_tokens=input_tokens, output_tokens=output_tokens,
    )
    db.add(row)
    db.commit()
    return row.id


def _costs(db):
    query, row_cost = with_row_cost(db.query(models.ProbeResult.id))
    return {pid: cost for pid, cost in query.add_columns(row_cost).order_by(models.ProbeResult.id).all()}


def test_row_exactly_at_effective_from_uses_the_new_price(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 2.0, 10.0, T, observed_at=T)
    before = _probe(db, M, T - timedelta(seconds=1))
    at = _probe(db, M, T)
    after = _probe(db, M, T + timedelta(seconds=1))
    costs = _costs(db)
    assert costs[before] == pytest.approx(6.0)
    assert costs[at] == pytest.approx(12.0)  # effective_from is inclusive
    assert costs[after] == pytest.approx(12.0)


def test_model_without_price_rows_keeps_its_row_with_null_cost(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    unknown = _probe(db, "mystery.model-v9", T)
    priced = _probe(db, M, T)
    costs = _costs(db)
    assert set(costs) == {unknown, priced}  # LEFT OUTER JOIN keeps the unpriced probe row
    assert costs[unknown] is None
    assert costs[priced] == pytest.approx(6.0)


def test_null_tokens_count_as_zero(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    only_output = _probe(db, M, T, input_tokens=None, output_tokens=1000)
    no_tokens = _probe(db, M, T, input_tokens=None, output_tokens=None)
    costs = _costs(db)
    assert costs[only_output] == pytest.approx(0.005)
    assert costs[no_tokens] == 0.0  # priced model with no tokens costs 0, not NULL


def test_pending_and_rejected_rows_never_price_a_probe(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 100.0, 500.0, T, status="pending_review", observed_at=T)
    _price(db, M, 50.0, 250.0, T, status="rejected", observed_at=T)
    pid = _probe(db, M, T + timedelta(hours=1))
    assert _costs(db)[pid] == pytest.approx(6.0)


def test_same_effective_from_higher_id_wins_without_duplicating_the_probe_row(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 2.0, 10.0, T, observed_at=T)
    _price(db, M, 3.0, 15.0, T, observed_at=T)
    pid = _probe(db, M, T + timedelta(minutes=5))
    query, row_cost = with_row_cost(db.query(models.ProbeResult.id))
    rows = query.add_columns(row_cost).all()
    assert len(rows) == 1  # [T, T) interval of the lower id joins nothing
    assert rows[0] == (pid, pytest.approx(18.0))


def test_row_cost_is_a_python_float(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    pid = _probe(db, M, T, input_tokens=3, output_tokens=7)
    cost = _costs(db)[pid]
    assert type(cost) is float
    assert cost == pytest.approx((3 * 1.0 + 7 * 5.0) / 1_000_000.0)


def test_row_cost_sql_is_portable_to_postgresql(db):
    query, row_cost = with_row_cost(db.query(models.ProbeResult.id))
    sql = str(query.add_columns(row_cost).statement.compile(dialect=postgresql.dialect()))
    assert "LEFT OUTER JOIN" in sql
    assert ("lead(price_history.effective_from) OVER (PARTITION BY price_history.model_id "
            "ORDER BY price_history.effective_from, price_history.id)") in sql
    assert "AS FLOAT)" in sql
    assert "coalesce(probe_results.input_tokens" in sql


def test_current_rows_returns_the_row_effective_at_now(db):
    seed = _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    verified = _price(db, M, 2.0, 10.0, T, observed_at=T)
    _price(db, M, 9.0, 9.0, T + timedelta(hours=1), status="pending_review", observed_at=T)
    assert current_rows(db, [M], now=T + timedelta(days=1))[M].id == verified.id
    assert current_rows(db, [M], now=T - timedelta(seconds=1))[M].id == seed.id
    assert current_rows(db, [M, "mystery.model-v9"], now=T)[M].id == verified.id
    assert "mystery.model-v9" not in current_rows(db, [M, "mystery.model-v9"], now=T)
    assert current_rows(db, []) == {}


def test_pending_rows_returns_the_most_recently_observed_pending_row(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 9.0, 45.0, T, status="pending_review", observed_at=T + timedelta(hours=12))
    _price(db, M, 8.0, 40.0, T + timedelta(hours=1), status="pending_review", observed_at=T + timedelta(hours=1))
    _price(db, M, 7.0, 35.0, T, status="rejected", observed_at=T + timedelta(days=1))
    got = pending_rows(db, [M])
    assert (got[M].input_per_mtok, got[M].output_per_mtok) == (9.0, 45.0)
    assert pending_rows(db, ["mystery.model-v9"]) == {}


def test_last_finished_run_ignores_running_rows_and_keeps_any_status(db):
    assert last_finished_run(db) is None
    db.add(models.PriceSyncRun(started_at=T, finished_at=T + timedelta(seconds=30), status="completed"))
    db.add(models.PriceSyncRun(started_at=T + timedelta(hours=12), finished_at=T + timedelta(hours=12, seconds=9),
                               status="failed"))
    db.add(models.PriceSyncRun(started_at=T + timedelta(hours=24), finished_at=None, status="running"))
    db.commit()
    run = last_finished_run(db)
    assert run.status == "failed"
    assert as_utc(run.started_at) == T + timedelta(hours=12)


def test_verification_states(db):
    run = models.PriceSyncRun(started_at=T, finished_at=T + timedelta(seconds=30), status="completed")
    seed = models.PriceHistory(status="seed", observed_at=None)
    seed_confirmed = models.PriceHistory(status="seed", observed_at=T)
    fresh = models.PriceHistory(status="verified", observed_at=T)
    old = models.PriceHistory(status="verified", observed_at=T - timedelta(seconds=1))
    assert verification_of(None, run) == "none"
    assert verification_of(seed, run) == "seed_only"
    assert verification_of(seed, None) == "seed_only"
    assert verification_of(seed_confirmed, run) == "verified"  # boundary: observed_at == run start
    assert verification_of(fresh, run) == "verified"
    assert verification_of(old, run) == "stale"
    assert verification_of(fresh, None) == "stale"  # no finished run yet


def test_cp_cells_go_stale_after_a_partial_run_where_only_the_anthropic_source_failed(db):
    t1, t2 = T, T + timedelta(hours=12)
    db.add(models.PriceSyncRun(started_at=t1, finished_at=t1 + timedelta(seconds=31), status="completed"))
    cp = _price(db, "anthropic:claude-sonnet-5", 2.0, 10.0, EPOCH, status="seed", observed_at=t1,
                source_id="anthropic-pricing", channel="cp")
    offer = _price(db, M, 2.0, 10.0, EPOCH, status="seed", observed_at=t1)
    # Run 2: offers answered (observed_at moves to t2), the Anthropic document failed (CP row untouched).
    db.add(models.PriceSyncRun(started_at=t2, finished_at=t2 + timedelta(seconds=25), status="partial"))
    offer.observed_at = t2
    db.commit()
    last = last_finished_run(db)
    assert verification_of(offer, last) == "verified"
    assert verification_of(cp, last) == "stale"


def test_as_utc_normalizes_naive_and_foreign_offsets():
    kst = timezone(timedelta(hours=9))
    assert as_utc(None) is None
    assert as_utc(datetime(2026, 9, 26, 3, 0)) == T
    assert as_utc(datetime(2026, 9, 26, 12, 0, tzinfo=kst)) == T
    assert as_utc(datetime(2026, 9, 26, 12, 0, tzinfo=kst)).tzinfo == timezone.utc
