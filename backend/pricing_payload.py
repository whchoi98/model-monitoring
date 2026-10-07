"""GET /api/pricing payload builder (v2.30.0, extra price fields v2.31.0, ADR-030) — pure function over price_history.

The backend decides every order and number; the frontend and the three export formats reuse them as-is:
- families: PROVIDER_ORDER (Anthropic Claude, OpenAI, Amazon Nova), then FAMILY_ORDER.
- tiers: always the five keys cp, openai_list, global, us (object or null) and in_region (always a list), in
  that order. Channels of one tier with equal values (all nine prices, verification, the full pending value
  set) form one element; in_region elements are ordered by region name.
- every cell (and its pending object) carries input, output, cache_read, cache_write, cache_write_1h (null when
  the source has no such price) and long ({input, output, cache_read, cache_write} when both long_input and
  long_output are set, else null).
- footnotes: walking the cells in display order, each source_id gets the next number the first time it is
  cited, and a family's official-source note (source != "manual_note") cites its source_id right after that
  family's cells, so it always has a number; manual notes come right after the cited sources, titled
  "<family> <kind> (manual note, <basis>)" with the family's FAMILY_ORDER name.
- references list only what a cell footnote or a family note cites, numbered 1..N without gaps (v2.31.1: the
  fixed official pages are gone; the Markdown export links the official pricing pages in its header instead).
- models (model_id -> input/output, the cost map) leaves out the display-only openai_list channels.
"""

from datetime import datetime
from decimal import Decimal
from typing import Mapping, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import pricing_sources
from models import PriceHistory
from price_history import as_utc, current_rows, last_finished_run, pending_rows, verification_of
from pricing_parsers import PRICE_FIELDS
from pricing_seed import SEED_SOURCE_DATE, SEED_SOURCE_DATES
from pricing_sources import (
    ANTHROPIC_REFERENCE_URL, ANTHROPIC_SOURCE_ID, FAMILY_ORDER, OFFER_REFERENCE_URL, OPENAI_REFERENCE_URL,
    OPENAI_SOURCE_ID, PRICELIST_REFERENCE_URL, PROVIDER_ORDER, PriceIdentity, note_source_id, region_of, tier_of,
)

ANTHROPIC_TITLE_EN = "Anthropic API pricing (Claude Platform on AWS uses standard pricing)"
ANTHROPIC_TITLE_KO = "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)"
OPENAI_TITLE_EN = "OpenAI API pricing (Standard)"
OPENAI_TITLE_KO = "OpenAI API 요금 (Standard)"

SINGLE_TIERS = ("cp", "openai_list", "global", "us")
_VERIFICATION_RANK = {"verified": 0, "stale": 1, "seed_only": 2, "none": 3}

NOTE_KIND_TITLES = {"promo": {"en": "promotion", "ko": "프로모션"}, "doc_conflict": {"en": "source mismatch", "ko": "문서 불일치"}}
# Note fields that only build a manual note's reference title; families[].notes carries the rest (frontend PricingNote).
_NOTE_TITLE_FIELDS = ("basis_en", "basis_ko")


def price_number(v: float):
    """At most 6 decimals, trailing zeros removed: 4.0 -> 4, 4.40 -> 4.4, 4.4000000000000004 -> 4.4."""
    d = Decimal(str(round(float(v), 6))).normalize()
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def price_number_or_none(v: Optional[float]):
    """price_number for an optional price: None (the source has no such price) stays None, 0 stays 0."""
    return None if v is None else price_number(v)


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


def price_values(row: PriceHistory) -> tuple:
    """The row's nine prices in PRICE_FIELDS order as price_number values (None where the row has none)."""
    return tuple(price_number_or_none(getattr(row, f"{f}_per_mtok")) for f in PRICE_FIELDS)


def price_fields(row: PriceHistory) -> dict:
    """The price keys of a cell or pending object: input, output, cache_read, cache_write, cache_write_1h, long."""
    long = None
    if row.long_input_per_mtok is not None and row.long_output_per_mtok is not None:
        long = {
            "input": price_number(row.long_input_per_mtok),
            "output": price_number(row.long_output_per_mtok),
            "cache_read": price_number_or_none(row.long_cache_read_per_mtok),
            "cache_write": price_number_or_none(row.long_cache_write_per_mtok),
        }
    return {
        "input": price_number(row.input_per_mtok),
        "output": price_number(row.output_per_mtok),
        "cache_read": price_number_or_none(row.cache_read_per_mtok),
        "cache_write": price_number_or_none(row.cache_write_per_mtok),
        "cache_write_1h": price_number_or_none(row.cache_write_1h_per_mtok),
        "long": long,
    }


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
    if source_id == OPENAI_SOURCE_ID:
        return {"kind": "openai_doc", "title_en": OPENAI_TITLE_EN, "title_ko": OPENAI_TITLE_KO,
                "url": OPENAI_REFERENCE_URL}
    # Unknown format: a cell cites it, so it is still listed and the footnote resolves, without a link.
    return {"kind": "official_page", "title_en": source_id, "title_ko": source_id, "url": None}


def _note_payload(note: Mapping) -> dict:
    """families[].notes entry: the note without its title-only fields, always with source and source_id
    (a manual note without a source_id gets note_source_id(family_key))."""
    out = {k: v for k, v in note.items() if k not in _NOTE_TITLE_FIELDS}
    out["source"] = note.get("source", "manual_note")
    out["source_id"] = note.get("source_id") or note_source_id(note["family_key"])
    return out


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
        p = pending.get(mid)
        return (
            price_values(current[mid]), verification_of(current[mid], last_run),
            None if p is None else price_values(p),
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
            **price_fields(first),
            "model_ids": list(mids),
            "source_ids": source_ids,
            "footnotes": cite(source_ids, family),
            "verification": verification_of(first, last_run),
            "observed_at": iso_z(min(observed)) if observed else None,
            "pending": None if p is None else {"id": p.id, **price_fields(p), "observed_at": iso_z(p.observed_at)},
        }

    families = []
    manual_notes: list[tuple[Mapping, dict, str]] = []  # (note, payload note, family) in display order
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
        shown = [note for note in pricing_sources.PRICE_NOTES
                 if note["family_key"] == family_key and not _note_resolved(note, mids, active, current)]
        notes = [_note_payload(note) for note in shown]
        for note, payload_note in zip(shown, notes):
            if payload_note["source"] == "manual_note":
                manual_notes.append((note, payload_note, ident.family))
            else:
                cite([payload_note["source_id"]], ident.family)  # right after this family's cells
        families.append({
            "family_key": family_key,
            "family": ident.family,
            "provider": ident.provider,
            "tiers": tiers,
            "notes": notes,
        })

    references = []
    for sid, n in sorted(numbers.items(), key=lambda kv: kv[1]):
        observed = [as_utc(r.observed_at) for r in current.values() if r.source_id == sid and r.observed_at is not None]
        # A source only seed rows cite (no sync has observed it yet) shows its own seed check date, else the default.
        as_of = (max(observed).date() if observed else SEED_SOURCE_DATES.get(sid, SEED_SOURCE_DATE)).isoformat()
        references.append({"n": n, "id": sid, **_source_reference(sid, cited_by[sid]), "as_of": as_of})
    for note, payload_note, family in manual_notes:
        references.append({
            "n": len(references) + 1, "id": payload_note["source_id"], **_note_reference(note, family),
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
            for mid in ids if mid in current and active[mid].channel != "openai_list"
        },
        "references": references,
        "disclaimer": {"en": pricing_sources.DISCLAIMER["en"], "ko": pricing_sources.DISCLAIMER["ko"]},
    }


def _note_resolved(note: Mapping, mids: list[str], active: Mapping[str, PriceIdentity],
                   current: Mapping[str, PriceHistory]) -> bool:
    """A promo note drops out once a sync has observed the pre-promotion price on one of its tiers; a doc_conflict
    note (v2.33.0) once a sync has observed every expected value on one of its tiers."""
    if note["kind"] == "doc_conflict":
        for tier, expected in note["expected"].items():
            for mid in mids:
                row = current.get(mid)
                if (row is not None and row.observed_at is not None and tier_of(active[mid].channel) == tier
                        and all(getattr(row, f"{field}_per_mtok") is not None
                                and price_number(getattr(row, f"{field}_per_mtok")) == price_number(value)
                                for field, value in expected.items())):
                    return True
        return False
    for tier, prior in note["prior_price"].items():
        for mid in mids:
            row = current.get(mid)
            if (row is not None and row.observed_at is not None
                    and tier_of(active[mid].channel) == tier and _same_price(row, prior)):
                return True
    return False
