"""GET /api/pricing payload builder (v2.30.0, ADR-030) — pure function over price_history.

The backend decides every order and number; the frontend and the three export formats reuse them as-is:
- families: PROVIDER_ORDER (Anthropic Claude, Amazon Nova, OpenAI), then FAMILY_ORDER.
- tiers: always the four keys cp, global, us (object or null) and in_region (always a list). Channels of one
  tier with equal values (price, verification, pending value) form one element; in_region elements are
  ordered by region name.
- footnotes: walking the cells in display order, each source_id gets the next number the first time it is
  cited; the fixed official pages follow, and manual notes come last, titled "<family> <kind> (manual note,
  <basis>)" with the family's FAMILY_ORDER name.
"""

from datetime import datetime
from decimal import Decimal
from typing import Mapping, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import pricing_sources
from models import PriceHistory
from price_history import as_utc, current_rows, last_finished_run, pending_rows, verification_of
from pricing_seed import SEED_SOURCE_DATE
from pricing_sources import (
    ANTHROPIC_REFERENCE_URL, ANTHROPIC_SOURCE_ID, FAMILY_ORDER, OFFER_REFERENCE_URL, PRICELIST_REFERENCE_URL,
    PROVIDER_ORDER, PriceIdentity, note_source_id, official_source_id, region_of, tier_of,
)

ANTHROPIC_TITLE_EN = "Anthropic API pricing (Claude Platform on AWS uses standard pricing)"
ANTHROPIC_TITLE_KO = "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)"

SINGLE_TIERS = ("cp", "global", "us")
_VERIFICATION_RANK = {"verified": 0, "stale": 1, "seed_only": 2, "none": 3}

NOTE_KIND_TITLES = {"promo": {"en": "promotion", "ko": "프로모션"}}
# Note fields that only build the reference title; families[].notes carries the rest (frontend PricingNote).
_NOTE_TITLE_FIELDS = ("basis_en", "basis_ko")


def price_number(v: float):
    """At most 6 decimals, trailing zeros removed: 4.0 -> 4, 4.40 -> 4.4, 4.4000000000000004 -> 4.4."""
    d = Decimal(str(round(float(v), 6))).normalize()
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def price_text(v: float) -> str:
    """price_number as text for CSV/Markdown (never scientific notation): 4.4 -> "4.4", 1e-05 -> "0.00001"."""
    n = price_number(v)
    if isinstance(n, int):
        return str(n)
    return format(Decimal(str(n)), "f")


def iso_z(value: Optional[datetime]) -> Optional[str]:
    """UTC ISO-8601 with a Z suffix and whole seconds (2026-09-26T15:00:00Z)."""
    if value is None:
        return None
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _same_price(row: PriceHistory, prior: Mapping) -> bool:
    return (price_number(row.input_per_mtok), price_number(row.output_per_mtok)) == (
        price_number(prior["input"]), price_number(prior["output"]))


def _source_reference(source_id: str, families: list[str]) -> dict:
    names = ", ".join(families)
    if source_id.startswith("offer:"):
        offer_id = source_id[len("offer:"):]
        return {
            "kind": "agreement_offer",
            "title_en": f"Amazon Bedrock agreement offer rate card, {offer_id} ({names})",
            "title_ko": f"Amazon Bedrock 약정 오퍼 요금표, {offer_id} ({names})",
            "url": OFFER_REFERENCE_URL,
        }
    if source_id.startswith("pricelist:"):
        usagetype = source_id[len("pricelist:"):]
        return {
            "kind": "price_list",
            "title_en": f"AWS Price List API, AmazonBedrock usage type {usagetype} ({names})",
            "title_ko": f"AWS Price List API, AmazonBedrock 사용 유형 {usagetype} ({names})",
            "url": PRICELIST_REFERENCE_URL,
        }
    if source_id == ANTHROPIC_SOURCE_ID:
        return {"kind": "anthropic_doc", "title_en": ANTHROPIC_TITLE_EN, "title_ko": ANTHROPIC_TITLE_KO,
                "url": ANTHROPIC_REFERENCE_URL}
    # Unknown format: still listed so the footnote resolves, without a link.
    return {"kind": "official_page", "title_en": source_id, "title_ko": source_id, "url": None}


def _note_reference(note: Mapping, family: str) -> dict:
    """A manual note's reference titles. `family` is the note's family as priced (its PriceIdentity.family)."""
    kind = NOTE_KIND_TITLES.get(note["kind"], {"en": note["kind"], "ko": note["kind"]})
    return {
        "kind": "manual_note",
        "title_en": f"{family} {kind['en']} (manual note, {note['basis_en']})",
        "title_ko": f"{family} {kind['ko']} (수동 메모, {note['basis_ko']})",
        "url": None,
    }


def build_pricing_payload(db: Session, active: Mapping[str, PriceIdentity], *, now: datetime) -> dict:
    """The exact /api/pricing body for the active channel set (model_id -> PriceIdentity)."""
    now = as_utc(now)
    ids = sorted(active)
    current = current_rows(db, ids, now=now)
    pending = pending_rows(db, ids)
    last_run = last_finished_run(db)
    pending_count = 0
    # Every active channel with any pending_review row (distinct model_ids, not rows). price_sync_runs.pending only
    # counts the channels one run classified as pending, so it can be lower.
    if ids:
        pending_count = (
            db.query(func.count(PriceHistory.model_id.distinct()))
            .filter(PriceHistory.model_id.in_(ids), PriceHistory.status == "pending_review")
            .scalar()
        ) or 0

    by_family: dict[str, list[str]] = {}
    for mid in ids:
        by_family.setdefault(active[mid].family_key, []).append(mid)

    def family_order(family_key: str):
        ident = active[by_family[family_key][0]]
        provider_rank = PROVIDER_ORDER.index(ident.provider) if ident.provider in PROVIDER_ORDER else len(PROVIDER_ORDER)
        family_rank = FAMILY_ORDER.index(ident.family) if ident.family in FAMILY_ORDER else len(FAMILY_ORDER)
        return provider_rank, family_rank, family_key

    numbers: dict[str, int] = {}
    cited_by: dict[str, list[str]] = {}

    def cite(source_ids: list[str], family: str) -> list[int]:
        out = []
        for sid in source_ids:
            if sid not in numbers:
                numbers[sid] = len(numbers) + 1
                cited_by[sid] = []
            if family not in cited_by[sid]:
                cited_by[sid].append(family)
            out.append(numbers[sid])
        return out

    def group_key(mid: str):
        row = current[mid]
        p = pending.get(mid)
        return (
            price_number(row.input_per_mtok), price_number(row.output_per_mtok), verification_of(row, last_run),
            None if p is None else (price_number(p.input_per_mtok), price_number(p.output_per_mtok)),
        )

    def groups(mids: list[str]) -> list[list[str]]:
        grouped: dict[tuple, list[str]] = {}
        for mid in mids:
            grouped.setdefault(group_key(mid), []).append(mid)
        return list(grouped.values())

    def cell(mids: list[str], family: str) -> dict:
        rows = [current[m] for m in mids]
        first = rows[0]
        source_ids: list[str] = []
        for r in rows:
            if r.source_id not in source_ids:
                source_ids.append(r.source_id)
        observed = [as_utc(r.observed_at) for r in rows if r.observed_at is not None]
        p = pending.get(mids[0])
        return {
            "input": price_number(first.input_per_mtok),
            "output": price_number(first.output_per_mtok),
            "model_ids": list(mids),
            "source_ids": source_ids,
            "footnotes": cite(source_ids, family),
            "verification": verification_of(first, last_run),
            "observed_at": iso_z(min(observed)) if observed else None,
            "pending": None if p is None else {
                "id": p.id,
                "input": price_number(p.input_per_mtok),
                "output": price_number(p.output_per_mtok),
                "observed_at": iso_z(p.observed_at),
            },
        }

    families = []
    shown_notes: list[tuple[Mapping, str]] = []  # (note, family) in display order, for the manual_note references
    for family_key in sorted(by_family, key=family_order):
        mids = by_family[family_key]
        ident = active[mids[0]]
        priced = [m for m in mids if m in current]
        tiers: dict = {}
        for tier in SINGLE_TIERS:
            options = groups(sorted(m for m in priced if tier_of(active[m].channel) == tier))
            if not options:
                tiers[tier] = None
                continue
            best = min(options, key=lambda g: (_VERIFICATION_RANK[verification_of(current[g[0]], last_run)], g[0]))
            tiers[tier] = cell(best, ident.family)
        regional = sorted(
            (m for m in priced if tier_of(active[m].channel) == "in_region"),
            key=lambda m: (region_of(active[m].channel), m),
        )
        tiers["in_region"] = [
            {"regions": [region_of(active[m].channel) for m in g], **cell(g, ident.family)}
            for g in groups(regional)
        ]
        notes = [note for note in pricing_sources.PRICE_NOTES
                 if note["family_key"] == family_key and not _note_resolved(note, mids, active, current)]
        shown_notes.extend((note, ident.family) for note in notes)
        families.append({
            "family_key": family_key,
            "family": ident.family,
            "provider": ident.provider,
            "tiers": tiers,
            "notes": [{k: v for k, v in note.items() if k not in _NOTE_TITLE_FIELDS} for note in notes],
        })

    references = []
    for sid, n in sorted(numbers.items(), key=lambda kv: kv[1]):
        observed = [as_utc(r.observed_at) for r in current.values() if r.source_id == sid and r.observed_at is not None]
        as_of = max(observed).date().isoformat() if observed else SEED_SOURCE_DATE.isoformat()
        references.append({"n": n, "id": sid, **_source_reference(sid, cited_by[sid]), "as_of": as_of})
    for page in pricing_sources.OFFICIAL_PAGES:
        references.append({
            "n": len(references) + 1, "id": official_source_id(page["slug"]), "kind": "official_page",
            "title_en": page["title_en"], "title_ko": page["title_ko"], "url": page["url"], "as_of": None,
        })
    for note, family in shown_notes:
        references.append({
            "n": len(references) + 1, "id": note_source_id(note["family_key"]), **_note_reference(note, family),
            "as_of": None,
        })

    return {
        "currency": "USD",
        "unit": "per_1m_tokens",
        "generated_at": iso_z(now),
        "last_sync": None if last_run is None else {
            "id": last_run.id,
            "started_at": iso_z(last_run.started_at),
            "finished_at": iso_z(last_run.finished_at),
            "status": last_run.status,
        },
        "pending_review": int(pending_count),
        "families": families,
        "models": {
            mid: {
                "input": price_number(current[mid].input_per_mtok),
                "output": price_number(current[mid].output_per_mtok),
                "verification": verification_of(current[mid], last_run),
            }
            for mid in ids if mid in current
        },
        "references": references,
        "disclaimer": {"en": pricing_sources.DISCLAIMER["en"], "ko": pricing_sources.DISCLAIMER["ko"]},
    }


def _note_resolved(note: Mapping, mids: list[str], active: Mapping[str, PriceIdentity],
                   current: Mapping[str, PriceHistory]) -> bool:
    """A promo note drops out once a sync has observed the pre-promotion price on one of its tiers."""
    for tier, prior in note["prior_price"].items():
        for mid in mids:
            row = current.get(mid)
            if (row is not None and row.observed_at is not None
                    and tier_of(active[mid].channel) == tier and _same_price(row, prior)):
                return True
    return False
