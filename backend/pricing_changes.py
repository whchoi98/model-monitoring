"""Unit price run-to-run changes (v2.40.0, ADR-035).

Every price sync run stores what /pricing showed when it finished (`price_sync_runs.summary["snapshot"]`, built by
`build_snapshot` inside the run's transaction). The page compares the latest run that has a snapshot with the run
before it:
  channel — a channel only one side has: before null -> after "present" (new) or the reverse (left)
  price   — a shown field differs (a sync change, an admin approval or a first-time value — before null)
  pending — a pending field differs (null -> value: review started; value -> null: approved or rejected)
  check   — the check category differs: "ok" or the `skipped:<reason>` result of the run
A new or left channel gives only its channel item. Admin approvals and rejections between the two runs land in the
later snapshot, so the page says "table values changed since sync #N" without telling which path changed them.
Stored values are price_number values (6 decimals), so they compare as they are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from models import PriceSyncRun
from price_history import current_rows, pending_rows
from pricing_parsers import PRICE_FIELDS
from pricing_payload import iso_z, price_number_or_none
from pricing_sources import FAMILY_ORDER, PROVIDER_ORDER, PriceIdentity, region_of, tier_of

SNAPSHOT_VERSION = 1
TIER_ORDER = ("cp", "openai_list", "global", "us", "in_region")
KIND_ORDER = ("channel", "price", "pending", "check")
_COMPARED_STATUSES = ("completed", "partial")
_RECENT_RUNS = 20  # runs read to find the two latest comparable ones (failed runs in between are skipped)


def _fields(row) -> Optional[dict]:
    if row is None:
        return None
    return {f: price_number_or_none(getattr(row, f"{f}_per_mtok")) for f in PRICE_FIELDS}


def _pending_diff(shown: Optional[dict], held: Optional[dict]) -> Optional[dict]:
    """The pending fields that differ from what is shown; every set field when nothing is shown (no_baseline)."""
    if held is None:
        return None
    if shown is None:
        diff = {f: v for f, v in held.items() if v is not None}
    else:
        diff = {f: v for f, v in held.items() if v != shown[f]}
    return diff or None


def build_snapshot(db: Session, active: Mapping[str, PriceIdentity], channels: Mapping[str, str],
                   at: datetime) -> dict:
    """What /pricing shows for every active channel at `at` (call after db.flush(), before the commit)."""
    ids = sorted(active)
    current = current_rows(db, ids, now=at)
    pending = pending_rows(db, ids)
    out: dict[str, dict] = {}
    for mid in ids:
        ident = active[mid]
        shown = _fields(current.get(mid))
        out[mid] = {
            "family_key": ident.family_key, "family": ident.family, "provider": ident.provider,
            "tier": tier_of(ident.channel), "region": region_of(ident.channel),
            "shown": shown, "pending": _pending_diff(shown, _fields(pending.get(mid))),
            "result": channels.get(mid),
        }
    return {"version": SNAPSHOT_VERSION, "channels": out}


def _check(result: Optional[str]) -> str:
    return result if isinstance(result, str) and result.startswith("skipped:") else "ok"


def _meta(model_id: str, ch: Mapping) -> dict:
    return {"model_id": model_id, "family_key": ch["family_key"], "family": ch["family"],
            "provider": ch["provider"], "tier": ch["tier"], "region": ch.get("region")}


def _rank(item: Mapping) -> tuple:
    provider = PROVIDER_ORDER.index(item["provider"]) if item["provider"] in PROVIDER_ORDER else len(PROVIDER_ORDER)
    family = FAMILY_ORDER.index(item["family"]) if item["family"] in FAMILY_ORDER else len(FAMILY_ORDER)
    tier = TIER_ORDER.index(item["tier"]) if item["tier"] in TIER_ORDER else len(TIER_ORDER)
    field = PRICE_FIELDS.index(item["field"]) if item.get("field") in PRICE_FIELDS else -1
    return (provider, family, item["family_key"], tier, item["region"] or "", item["model_id"],
            KIND_ORDER.index(item["kind"]), field)


def compare_snapshots(before: Mapping, after: Mapping) -> list[dict]:
    """Change items between two snapshots, in table order (provider, family, tier, kind, field)."""
    prev, cur = before["channels"], after["channels"]
    items: list[dict] = []
    for mid in set(prev) | set(cur):
        if mid not in prev or mid not in cur:
            ch = cur.get(mid) or prev[mid]
            items.append({**_meta(mid, ch), "kind": "channel", "field": None,
                          "before": None if mid not in prev else "present",
                          "after": None if mid not in cur else "present"})
            continue
        a, b = prev[mid], cur[mid]
        meta = _meta(mid, b)
        shown_a, shown_b = a["shown"] or {}, b["shown"] or {}
        pend_a, pend_b = a["pending"] or {}, b["pending"] or {}
        for field in PRICE_FIELDS:
            if shown_a.get(field) != shown_b.get(field):
                items.append({**meta, "kind": "price", "field": field,
                              "before": shown_a.get(field), "after": shown_b.get(field)})
        for field in PRICE_FIELDS:
            if pend_a.get(field) != pend_b.get(field):
                items.append({**meta, "kind": "pending", "field": field,
                              "before": pend_a.get(field), "after": pend_b.get(field)})
        if _check(a["result"]) != _check(b["result"]):
            items.append({**meta, "kind": "check", "field": None,
                          "before": _check(a["result"]), "after": _check(b["result"])})
    return sorted(items, key=_rank)


def _snapshot_of(run: PriceSyncRun) -> Optional[dict]:
    summary = run.summary if isinstance(run.summary, dict) else {}
    snapshot = summary.get("snapshot")
    return snapshot if isinstance(snapshot, dict) and isinstance(snapshot.get("channels"), dict) else None


def select_runs(runs: Iterable[PriceSyncRun]) -> tuple[Optional[PriceSyncRun], Optional[PriceSyncRun]]:
    """(R, P): R = the latest finished completed/partial run with a snapshot, P = the completed/partial run before it.

    `runs` are newest first. Failed runs are skipped on both sides.
    """
    comparable = [r for r in runs if r.finished_at is not None and r.status in _COMPARED_STATUSES]
    for i, run in enumerate(comparable):
        if _snapshot_of(run) is not None:
            return run, comparable[i + 1] if i + 1 < len(comparable) else None
    return None, None


def changes_block(latest: Optional[PriceSyncRun], previous: Optional[PriceSyncRun]) -> dict:
    """The /api/pricing `changes` block for the two selected runs."""
    if latest is None or previous is None or _snapshot_of(previous) is None:
        return {"available": False, "run_id": None if latest is None else latest.id}
    return {
        "available": True,
        "run_id": latest.id, "finished_at": iso_z(latest.finished_at),
        "previous_run_id": previous.id, "previous_finished_at": iso_z(previous.finished_at),
        "items": compare_snapshots(_snapshot_of(previous), _snapshot_of(latest)),
    }


def latest_changes(db: Session) -> dict:
    runs = (db.query(PriceSyncRun)
            .filter(PriceSyncRun.finished_at.isnot(None))
            .order_by(PriceSyncRun.finished_at.desc(), PriceSyncRun.id.desc())
            .limit(_RECENT_RUNS)
            .all())
    return changes_block(*select_runs(runs))
