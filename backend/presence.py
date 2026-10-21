"""Persistent, idempotent browser counting shared by every backend replica."""

from datetime import datetime, timedelta, timezone
import hashlib

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from models import SitePresenceTotal, SiteVisitor

INITIAL_TOTAL = 10_000
WINDOW_SECONDS = 90
MAX_SAFE_COUNT = 9_007_199_254_740_991


def _limits(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '3000'"))
        db.execute(text("SET LOCAL lock_timeout = '1000'"))


def snapshot(db: Session) -> dict:
    _limits(db)
    now = datetime.now(timezone.utc)
    active = db.scalar(select(func.count()).select_from(SiteVisitor).where(
        SiteVisitor.last_seen > now - timedelta(seconds=WINDOW_SECONDS),
        SiteVisitor.last_seen <= now,
    ))
    # Count activity before reading the monotonic total: a concurrent new visit
    # commits its marker and increment together, so active cannot exceed tracked.
    total = db.get(SitePresenceTotal, 1)
    initial = total.initial_total if total else INITIAL_TOTAL
    count = total.total_visitors if total else INITIAL_TOTAL
    since = total.counting_since if total else None
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if not (0 <= initial <= count <= MAX_SAFE_COUNT and 0 <= active <= count - initial):
        raise ValueError("Inconsistent presence totals")
    return {
        "active_visitors": active,
        "total_visitors": count,
        "initial_total": initial,
        "window_seconds": WINDOW_SECONDS,
        "as_of": now.isoformat(),
        "counting_since": since.isoformat() if since else None,
    }


def heartbeat(db: Session, visitor: str) -> dict:
    _limits(db)
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(f"llm-monitor:presence:v1\0{visitor}".encode()).hexdigest()
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(SitePresenceTotal).values(
        id=1, initial_total=INITIAL_TOTAL, total_visitors=INITIAL_TOTAL, counting_since=now,
    ).on_conflict_do_nothing(index_elements=["id"]))
    first_visit = db.execute(insert(SiteVisitor).values(
        visitor_hash=digest, first_seen=now, last_seen=now,
    ).on_conflict_do_nothing(index_elements=["visitor_hash"]).returning(SiteVisitor.visitor_hash)).scalar_one_or_none()
    if first_visit is not None:
        result = db.execute(update(SitePresenceTotal).where(
            SitePresenceTotal.id == 1, SitePresenceTotal.total_visitors < MAX_SAFE_COUNT,
        ).values(total_visitors=SitePresenceTotal.total_visitors + 1))
        if result.rowcount != 1:
            raise ValueError("Presence total limit reached")
    else:
        db.execute(update(SiteVisitor).where(SiteVisitor.visitor_hash == digest).values(
            last_seen=case((SiteVisitor.last_seen < now, now), else_=SiteVisitor.last_seen),
        ))
    # A duplicate cookie, retry or concurrent tab can never increment separately
    # from the permanent visitor marker. No network call holds this transaction.
    db.commit()
    return snapshot(db)
