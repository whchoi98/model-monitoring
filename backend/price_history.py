"""Time-effective unit prices from price_history (v2.30.0, ADR-030).

The effective row for a model_id at time t is the seed/verified row with the latest
(effective_from, id) among rows whose effective_from <= t. Costs are computed per probe row
with the price that was effective at that row's timestamp:

    effective_prices = price_history rows with status IN ('seed', 'verified') plus
                       effective_to = LEAD(effective_from) OVER (PARTITION BY model_id
                                                             ORDER BY effective_from, id)
    probe_results LEFT OUTER JOIN effective_prices
        ON model_id = model_id AND timestamp >= effective_from
           AND (effective_to IS NULL OR timestamp < effective_to)
    row_cost = CAST((COALESCE(input_tokens, 0) * input_per_mtok
                     + COALESCE(output_tokens, 0) * output_per_mtok) / 1000000.0 AS FLOAT)

A model with no price row joins nothing, so row_cost is NULL (cost "-" on screen). Two rows
with the same effective_from get an empty [t, t) interval for the lower id, so a probe row
never joins twice. Every timestamp comparison is column-to-column or a bound datetime
parameter; SQLite stores DateTime values as UTC strings of one fixed format, so the string
comparison it does matches the PostgreSQL timestamptz comparison.
"""

from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from models import PriceHistory, PriceSyncRun, ProbeResult

EFFECTIVE_STATUSES = ("seed", "verified")


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes for DateTime(timezone=True) columns; every stored value is UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def effective_prices_subquery():
    """seed/verified rows with effective_to = the next row's effective_from for the same model_id."""
    effective_to = func.lead(PriceHistory.effective_from).over(
        partition_by=PriceHistory.model_id,
        order_by=(PriceHistory.effective_from, PriceHistory.id),
    )
    return (
        select(
            PriceHistory.model_id.label("model_id"),
            PriceHistory.input_per_mtok.label("input_per_mtok"),
            PriceHistory.output_per_mtok.label("output_per_mtok"),
            PriceHistory.effective_from.label("effective_from"),
            effective_to.label("effective_to"),
        )
        .where(PriceHistory.status.in_(EFFECTIVE_STATUSES))
        .subquery("effective_prices")
    )


def with_row_cost(query):
    """Outer-join a ProbeResult query with the price effective at each row's timestamp.

    Returns (joined query, row_cost). row_cost is a Float SQL expression, NULL when the model has
    no effective price at that time; the caller adds it as a column or inside SUM()/COUNT().
    """
    ep = effective_prices_subquery()
    joined = query.outerjoin(
        ep,
        and_(
            ep.c.model_id == ProbeResult.model_id,
            ProbeResult.timestamp >= ep.c.effective_from,
            or_(ep.c.effective_to.is_(None), ProbeResult.timestamp < ep.c.effective_to),
        ),
    )
    row_cost = cast(
        (
            func.coalesce(ProbeResult.input_tokens, 0) * ep.c.input_per_mtok
            + func.coalesce(ProbeResult.output_tokens, 0) * ep.c.output_per_mtok
        )
        / 1000000.0,
        Float,
    )
    return joined, row_cost


def _latest(rows: Iterable[PriceHistory], key) -> dict[str, PriceHistory]:
    out: dict[str, PriceHistory] = {}
    for row in rows:
        best = out.get(row.model_id)
        if best is None or key(row) > key(best):
            out[row.model_id] = row
    return out


def current_rows(db: Session, model_ids: Iterable[str], *, now: Optional[datetime] = None) -> dict[str, PriceHistory]:
    """model_id -> the seed/verified row effective at `now` (default: current UTC time)."""
    ids = sorted(set(model_ids))
    if not ids:
        return {}
    at = as_utc(now) if now is not None else datetime.now(timezone.utc)
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id.in_(ids))
        .filter(PriceHistory.status.in_(EFFECTIVE_STATUSES))
        .filter(PriceHistory.effective_from <= at)
        .all()
    )
    return _latest(rows, key=lambda r: (as_utc(r.effective_from), r.id))


def pending_rows(db: Session, model_ids: Iterable[str]) -> dict[str, PriceHistory]:
    """model_id -> the most recently observed pending_review row (ties: the higher id)."""
    ids = sorted(set(model_ids))
    if not ids:
        return {}
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id.in_(ids))
        .filter(PriceHistory.status == "pending_review")
        .all()
    )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return _latest(rows, key=lambda r: (as_utc(r.observed_at) or floor, r.id))


def last_finished_run(db: Session) -> Optional[PriceSyncRun]:
    """The most recently finished sync run, whatever its status (completed, partial, failed)."""
    return (
        db.query(PriceSyncRun)
        .filter(PriceSyncRun.finished_at.isnot(None))
        .order_by(PriceSyncRun.finished_at.desc(), PriceSyncRun.id.desc())
        .first()
    )


def verification_of(row: Optional[PriceHistory], last_run: Optional[PriceSyncRun]) -> str:
    """Per-cell calculation state (not the row's status column).

    none      : no effective price row
    seed_only : a seed row never confirmed by an official source (status 'seed', observed_at NULL)
    verified  : observed_at at or after started_at of the latest finished run (whatever that run's status)
    stale     : everything else: observed_at before the latest finished run started (that run did not confirm the
                channel, e.g. its source failed or it was skipped), observed_at set but no run has finished yet, or
                a non-seed row with observed_at NULL
    """
    if row is None:
        return "none"
    observed = as_utc(row.observed_at)
    if observed is None:
        return "seed_only" if row.status == "seed" else "stale"
    if last_run is not None and observed >= as_utc(last_run.started_at):
        return "verified"
    return "stale"
