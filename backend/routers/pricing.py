"""Unit price menu API (v2.30.0, ADR-030).

Public:
  GET /api/pricing                                   - price table payload (pricing_payload.build_pricing_payload)
  GET /api/pricing/export?format=csv|md|json&lang=ko|en - the same table as a download (attachment)
Admin (JWT, username == "admin"):
  GET  /api/admin/pricing/pending                    - pending_review rows with current value and change ratio
  POST /api/admin/pricing/pending/{row_id}/approve   - status -> verified (effective_from unchanged)
  POST /api/admin/pricing/pending/{row_id}/reject    - status -> rejected

CloudFront does not cache /api/*, so the payload is cached in-process for 60 s (no lang in the key: the
body carries both languages). Approve/reject clear this process's cache at once; other backend tasks catch
up within 60 s.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

import prober
from auth import get_current_user
from database import get_db
from models import PriceHistory, User
from price_history import as_utc, current_rows
from pricing_export import export_filename, to_csv, to_json, to_markdown
from pricing_payload import build_pricing_payload, iso_z, price_number
from pricing_sources import EPOCH, active_channels, price_identity
from routers.admin import _ensure_admin
from visibility import hidden_patterns

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pricing", tags=["pricing"])
admin_router = APIRouter(prefix="/api/admin/pricing", tags=["admin"])

CACHE_TTL_S = 60.0
CP_RECENT_DAYS = 30
_EXPORT_MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
}

_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "payload": None}
_monotonic = time.monotonic  # patched by tests


def invalidate_cache() -> None:
    with _cache_lock:
        _cache["payload"] = None
        _cache["at"] = 0.0


def _active(db: Session, now: datetime) -> dict:
    """Active channels = AVAILABLE_MODELS + CP ids observed in the last 30 days (CP discovery may have failed
    at this backend's startup), hidden labels removed, classified by price_identity."""
    models = dict(prober.AVAILABLE_MODELS)
    since = now - timedelta(days=CP_RECENT_DAYS)
    recent = (
        db.query(PriceHistory.model_id)
        .filter(PriceHistory.channel == "cp", PriceHistory.observed_at >= since)
        .distinct()
        .all()
    )
    for (model_id,) in recent:
        ident = price_identity(model_id)
        if model_id not in models and ident is not None and ident.channel == "cp":
            models[model_id] = f"Anthropic {ident.family} (US)"  # prober's CP label format
    return active_channels(models, hidden_patterns())


def _payload(db: Session) -> dict:
    with _cache_lock:
        cached = _cache["payload"]
        if cached is not None and _monotonic() - _cache["at"] < CACHE_TTL_S:
            return cached
    now = datetime.now(timezone.utc)
    payload = build_pricing_payload(db, _active(db, now), now=now)
    with _cache_lock:
        _cache["payload"] = payload
        _cache["at"] = _monotonic()
    return payload


@router.get("")
def get_pricing_table(db: Session = Depends(get_db)):
    """Unit price table: families in display order, per-cell footnotes, references, disclaimer (ko + en)."""
    return _payload(db)


@router.get("/export")
def export_pricing_table(
    fmt: str = Query(..., alias="format", pattern="^(csv|md|json)$"),
    lang: str = Query("ko", pattern="^(ko|en)$"),
    db: Session = Depends(get_db),
):
    """Download the price table as CSV (UTF-8 BOM), Markdown or JSON."""
    payload = _payload(db)
    if fmt == "csv":
        body = to_csv(payload, lang)
    elif fmt == "md":
        body = to_markdown(payload, lang)
    else:
        body = to_json(payload)
    filename = export_filename(fmt, datetime.now(timezone.utc).date())
    return Response(
        content=body.encode("utf-8"),
        media_type=_EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class PriceValue(BaseModel):
    input: float
    output: float


class PendingPrice(BaseModel):
    id: int
    model_id: str
    family_key: str
    channel: str
    reason: str  # changed | no_baseline
    current: Optional[PriceValue]
    new: PriceValue
    change: Optional[PriceValue]  # |new - old| / old per side; null without a baseline
    source_id: str
    effective_from: str
    observed_at: Optional[str]


class PendingList(BaseModel):
    pending: list[PendingPrice]


class PendingAction(BaseModel):
    ok: bool
    id: int
    status: str
    effective_from: str
    warnings: list[str]


def _ratio(new: float, old: float) -> Optional[float]:
    return round(abs(new - old) / old, 6) if old else None


@admin_router.get("/pending", response_model=PendingList)
def list_pending_prices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """All pending_review rows, oldest first, with the currently effective value and the change ratio."""
    _ensure_admin(user)
    rows = db.query(PriceHistory).filter(PriceHistory.status == "pending_review").order_by(PriceHistory.id).all()
    current = current_rows(db, [r.model_id for r in rows])
    out = []
    for r in rows:
        cur = current.get(r.model_id)
        change = None
        if cur is not None:
            ci, co = _ratio(r.input_per_mtok, cur.input_per_mtok), _ratio(r.output_per_mtok, cur.output_per_mtok)
            change = PriceValue(input=ci, output=co) if ci is not None and co is not None else None
        out.append(PendingPrice(
            id=r.id, model_id=r.model_id, family_key=r.family_key, channel=r.channel,
            reason="no_baseline" if as_utc(r.effective_from) == EPOCH else "changed",
            current=None if cur is None else PriceValue(
                input=price_number(cur.input_per_mtok), output=price_number(cur.output_per_mtok)),
            new=PriceValue(input=price_number(r.input_per_mtok), output=price_number(r.output_per_mtok)),
            change=change, source_id=r.source_id,
            effective_from=iso_z(r.effective_from), observed_at=iso_z(r.observed_at),
        ))
    return PendingList(pending=out)


def _pending_or_404(db: Session, row_id: int) -> PriceHistory:
    row = db.get(PriceHistory, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"price row {row_id} not found")
    if row.status != "pending_review":
        raise HTTPException(status_code=409, detail=f"price row {row_id}는 검토 대기 상태가 아닙니다 (현재: {row.status})")
    return row


@admin_router.post("/pending/{row_id}/approve", response_model=PendingAction)
def approve_pending_price(row_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """pending_review -> verified. effective_from stays the insert-time value (the observing run's start, or
    1970 for no_baseline). A verified row that already starts later keeps winning from its own start."""
    _ensure_admin(user)
    row = _pending_or_404(db, row_id)
    later = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id == row.model_id, PriceHistory.status == "verified",
                PriceHistory.effective_from > row.effective_from, PriceHistory.id != row.id)
        .order_by(PriceHistory.effective_from, PriceHistory.id)
        .all()
    )
    warnings = [
        f"id {v.id}의 단가 {price_number(v.input_per_mtok)} / {price_number(v.output_per_mtok)}가 "
        f"{iso_z(v.effective_from)}부터 적용되므로, 승인한 단가는 그 시각 전까지만 적용됩니다."
        for v in later
    ]
    row.status = "verified"
    db.commit()
    invalidate_cache()
    logger.info("admin '%s' approved price row %d (%s)", user.username, row.id, row.model_id)
    return PendingAction(ok=True, id=row.id, status=row.status, effective_from=iso_z(row.effective_from),
                         warnings=warnings)


@admin_router.post("/pending/{row_id}/reject", response_model=PendingAction)
def reject_pending_price(row_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """pending_review -> rejected. The sync keeps it rejected until the observed value changes."""
    _ensure_admin(user)
    row = _pending_or_404(db, row_id)
    row.status = "rejected"
    db.commit()
    invalidate_cache()
    logger.info("admin '%s' rejected price row %d (%s)", user.username, row.id, row.model_id)
    return PendingAction(ok=True, id=row.id, status=row.status, effective_from=iso_z(row.effective_from),
                         warnings=[])
