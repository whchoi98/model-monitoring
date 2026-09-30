"""Official unit-price sync (v2.30.0, ADR-030) — one run every 12 hours in the PricingSync task.

Order: running row first -> Anthropic pricing.md -> OpenAI pricing.md -> Price List (Nova) -> agreement offers
(one call per FM id; cheap sources first so a slow offers API cannot starve them) -> per-channel compare over
every price field (input, output and, from v2.31.0, the display-only cache and long-context fields) -> run closed
as completed / partial / failed. offerToken and presigned legalTerm URLs are stripped by `default_fetchers`
right after the call; no response body is ever logged.

A display-only field seen for the first time fills the effective row in place ("enriched", no new history row);
a value change follows the 50 % gate per field.

A parser exception of any type only skips that source's (or FM id's) channels as skipped:parse_failed; it
never fails the run. Observed prices are quantized to 6 decimals before they are compared or stored.

A long-context input or output below its short-context price is a source error (v2.32.0): the four long-context
fields of that observation are dropped with a WARNING log line (not a run error), so the stored values stay.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping

import httpx
from botocore.exceptions import ClientError, ConnectionError as BotoConnectionError, HTTPClientError

from models import PriceHistory, PriceSyncRun
from pricing_parsers import (
    EXTRA_FIELDS,
    PRICE_FIELDS,
    PriceParseError,
    UnitPrice,
    parse_anthropic_pricing_md,
    parse_openai_pricing_md,
    parse_pricelist,
    select_offer_price,
    single_public_offer,
)
from pricing_sources import (
    ANTHROPIC_PRICING_URL,
    ANTHROPIC_SOURCE_ID,
    EPOCH,
    NOVA_CACHE_USAGETYPES,
    NOVA_USAGETYPES,
    OPENAI_PRICING_URL,
    OPENAI_SOURCE_ID,
    PriceIdentity,
    offer_source_id,
    pricelist_source_id,
)

logger = logging.getLogger(__name__)

CHANGE_THRESHOLD = Decimal("0.5")
PRICE_QUANTUM = Decimal("0.000001")  # observed prices are compared and stored at 6 decimals (as price_number shows)
SYNC_DEADLINE_S = 300.0
SYNC_LOCK_KEY = 917350004

AWS_REGION = "us-east-1"  # agreement offers are region-independent; the Price List API lives in us-east-1
USER_AGENT = "bedrock-llm-monitor-pricing-sync (+https://github.com/whchoi98/model-monitoring)"
FETCH_RETRIES = 3            # retries after the first attempt (ThrottlingException, 5xx, connection errors)
FETCH_BACKOFF_BASE_S = 1.0   # 1 s, 2 s, 4 s

SOURCES = ("offers", "pricelist", "anthropic_doc", "openai_doc")
_SOURCE_OF_KIND = {"offer": "offers", "pricelist": "pricelist", "anthropic_doc": "anthropic_doc", "openai_doc": "openai_doc"}
_PRICE_COLUMN: dict[str, str] = {f: f"{f}_per_mtok" for f in PRICE_FIELDS}  # price_history column of each field
_EFFECTIVE_STATUSES = ("seed", "verified")
_HELD_STATUSES = ("pending_review", "rejected")
_RETRYABLE_AWS_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded",
    "ServiceUnavailableException", "ServiceUnavailable", "InternalServerException", "InternalFailure",
})
_MAX_ERRORS = 50


@dataclass
class Fetchers:
    offers: Callable[[str], dict]           # FM id -> list_foundation_model_agreement_offers response
    pricelist: Callable[..., list]          # (*usagetypes) -> PriceList items for all of them
    anthropic_doc: Callable[[], str]        # markdown text
    openai_doc: Callable[[], str]           # markdown text (OPENAI_PRICING_URL)


# ---------------------------------------------------------------- default fetchers (network)


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ClientError):
        code = (exc.response.get("Error") or {}).get("Code", "")
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0
        return code in _RETRYABLE_AWS_CODES or status >= 500
    if isinstance(exc, (BotoConnectionError, HTTPClientError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _with_retries(call: Callable[[], object], *, sleep: Callable[[float], None]):
    attempt = 0
    while True:
        try:
            return call()
        except Exception as exc:
            if attempt >= FETCH_RETRIES or not _is_retryable(exc):
                raise
            delay = FETCH_BACKOFF_BASE_S * (2 ** attempt)
            attempt += 1
            logger.warning("pricing sync: %s — retry %d/%d in %.0fs", _short(exc), attempt, FETCH_RETRIES, delay)
            sleep(delay)


def _sanitize_offers(raw: dict) -> dict:
    """Keep modelId, offerId and the rate card only — drops offerToken, legalTerm (presigned URL), supportTerm."""
    raw = raw if isinstance(raw, dict) else {}
    offers = []
    for offer in raw.get("offers") or []:
        offer = offer if isinstance(offer, dict) else {}
        rate_card = ((offer.get("termDetails") or {}).get("usageBasedPricingTerm") or {}).get("rateCard")
        offers.append({"offerId": offer.get("offerId"), "termDetails": {"usageBasedPricingTerm": {"rateCard": rate_card}}})
    return {"modelId": raw.get("modelId"), "offers": offers}


def _get_products(pricing, usagetype: str) -> list:
    items: list = []
    paginator = pricing.get_paginator("get_products")
    for page in paginator.paginate(
        ServiceCode="AmazonBedrock",
        Filters=[{"Type": "TERM_MATCH", "Field": "usagetype", "Value": usagetype}],
        FormatVersion="aws_v1",
    ):
        items.extend(page.get("PriceList") or [])
    return items


def default_fetchers(*, bedrock=None, pricing=None, http=None, sleep: Callable[[float], None] = time.sleep) -> Fetchers:
    """Real sources: boto3 bedrock + pricing (us-east-1) and httpx for the Anthropic and OpenAI docs.

    SDK-level retries are off (botocore max_attempts=1); `_with_retries` is the only retry loop.
    The keyword arguments exist for tests (fake clients, no sleeping).
    """
    if bedrock is None or pricing is None:
        import boto3
        from botocore.config import Config

        cfg = Config(retries={"max_attempts": 1, "mode": "standard"}, connect_timeout=10, read_timeout=30)
        if bedrock is None:
            bedrock = boto3.client("bedrock", region_name=AWS_REGION, config=cfg)
        if pricing is None:
            pricing = boto3.client("pricing", region_name=AWS_REGION, config=cfg)
    if http is None:
        http = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)

    def offers(fm_id: str) -> dict:
        raw = _with_retries(
            lambda: bedrock.list_foundation_model_agreement_offers(modelId=fm_id, offerType="PUBLIC"),
            sleep=sleep,
        )
        return _sanitize_offers(raw)

    def pricelist(*usagetypes: str) -> list:
        items: list = []
        for usagetype in usagetypes:  # one exact-usagetype query each, in order, pages concatenated
            items.extend(_with_retries(lambda ut=usagetype: _get_products(pricing, ut), sleep=sleep))
        return items

    def markdown(url: str) -> str:
        def get() -> str:
            resp = http.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.text

        return _with_retries(get, sleep=sleep)

    def anthropic_doc() -> str:
        return markdown(ANTHROPIC_PRICING_URL)

    def openai_doc() -> str:
        return markdown(OPENAI_PRICING_URL)

    return Fetchers(offers=offers, pricelist=pricelist, anthropic_doc=anthropic_doc, openai_doc=openai_doc)


# ---------------------------------------------------------------- comparison


def _dec(v: float) -> Decimal:
    return Decimal(str(round(v, 6)))


def _quantized(price: UnitPrice) -> UnitPrice:
    """Every set field at 6 decimals. A value that cannot be quantized raises decimal.InvalidOperation. Input or
    output at or below 0 after rounding, and an extra field that is negative or positive but 0 at 6 decimals, raise
    PriceParseError (parse failures: a zero input/output price is never stored). An extra field of exactly 0 stays 0
    (the Nova cache write is officially $0.00)."""
    values = {f: None if getattr(price, f) is None else getattr(price, f).quantize(PRICE_QUANTUM) for f in PRICE_FIELDS}
    if values["input"] <= 0 or values["output"] <= 0:
        raise PriceParseError(f"price rounds to 0 at 6 decimals: {price.input}/{price.output}")
    for field in EXTRA_FIELDS:
        raw = getattr(price, field)
        if raw is not None and (raw < 0 or (raw > 0 and values[field] == 0)):
            raise PriceParseError(f"{field} price is negative or rounds to 0 at 6 decimals: {raw}")
    return UnitPrice(**values)


_LONG_FIELDS = ("long_input", "long_output", "long_cache_read", "long_cache_write")


def _gpt_long_only(price: UnitPrice, ident: PriceIdentity) -> UnitPrice:
    """Long-context prices are GPT-only. The offer allow-list accepts `_long_ctx` names on any FM, so a non-OpenAI
    channel's long_* fields are dropped here, before _quantized, and never reach price_history, /api/pricing or the
    exports (the doc parsers and the Price List never produce long_* for Claude or Nova)."""
    if ident.provider == "openai":
        return price
    return replace(price, **dict.fromkeys(_LONG_FIELDS))


def _implausible_long(price: UnitPrice) -> bool:
    """A long-context input or output below its short-context price is a source data error, not a price (2026-09-30
    GPT-6.1 Sol agreement offer: long output 2.2 / 2 against output 11 / 10; the OpenAI pricing doc says 15)."""
    return ((price.long_input is not None and price.long_input < price.input)
            or (price.long_output is not None and price.long_output < price.output))


def _plausible_long(price: UnitPrice, where: str) -> UnitPrice:
    """`price` without its four long_* fields when they are implausible (a warning log line names `where`), else as is.
    The fields become None, which the compare ignores: a stored long value stays, a missing one stays missing."""
    if not _implausible_long(price):
        return price
    logger.warning("pricing sync: %s: long-context price below the short-context price, long prices dropped", where)
    return replace(price, **dict.fromkeys(_LONG_FIELDS))


def _parse_message(exc: Exception) -> str:
    """PriceParseError text as-is; any other parser exception (a shape the parser did not expect) with its type."""
    return str(exc) if isinstance(exc, PriceParseError) else _short(exc)


def classify_change(current: Mapping[str, float | None] | None, new: UnitPrice) -> str:
    """"no_baseline" | "unchanged" | "enriched" | "changed" | "pending" over PRICE_FIELDS.

    `current` maps each field to the stored float or None. Per field: observed None -> ignored (the stored value
    stays); stored None and observed set -> fill; both set and different -> differs, and pending when the stored
    value is <= 0 or |new - old| / old > 0.5 (boundary inclusive). Any pending -> "pending", else any differs ->
    "changed", else any fill -> "enriched", else "unchanged".
    """
    if current is None:
        return "no_baseline"
    fill = differs = False
    for field in PRICE_FIELDS:
        stored, value = current.get(field), getattr(new, field)
        if value is None:
            continue
        if stored is None:
            fill = True
            continue
        old = _dec(stored)
        if old == value:
            continue
        differs = True
        if old <= 0 or abs(value - old) / old > CHANGE_THRESHOLD:
            return "pending"
    if differs:
        return "changed"
    return "enriched" if fill else "unchanged"


# ---------------------------------------------------------------- run


@dataclass(frozen=True)
class _Observed:
    price: UnitPrice
    source_id: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _open_run(session_factory, started_at: datetime) -> int:
    db = session_factory()
    try:
        run = PriceSyncRun(started_at=started_at, status="running", changes=0, pending=0)
        db.add(run)
        db.commit()
        return run.id
    finally:
        db.close()


def _fetch_all(active: Mapping[str, PriceIdentity], fetchers: Fetchers, clock, started_at: datetime, deadline_s: float):
    observed: dict[str, _Observed] = {}
    channels: dict[str, str] = {}
    sources = {s: {"calls": 0, "ok": 0, "failed": 0} for s in SOURCES}
    errors: list[str] = []

    def error(message: str) -> None:  # every summary error is also a log line — the run summary is not in the logs
        logger.warning("pricing sync: %s", message)
        errors.append(message)

    groups: dict[str, dict[str, list[tuple[str, PriceIdentity]]]] = {s: defaultdict(list) for s in SOURCES}
    for model_id in sorted(active):
        ident = active[model_id]
        source = _SOURCE_OF_KIND.get(ident.source_kind)
        if source is None:
            channels[model_id] = "skipped:unmapped"
            error(f"{model_id}: unknown source kind {ident.source_kind!r}")
            continue
        groups[source][ident.source_ref].append((model_id, ident))
    for source in SOURCES:
        if not groups[source]:
            error(f"{source}: no active channels")

    deadline = {"hit": False}

    def fetch(source: str, what: str, call: Callable[[], object]):
        if (clock() - started_at).total_seconds() > deadline_s:
            if not deadline["hit"]:
                deadline["hit"] = True
                error(f"deadline: {deadline_s:g}s exceeded before {source} {what}")
            return None, "deadline"
        sources[source]["calls"] += 1
        try:
            value = call()
        except Exception as exc:  # noqa: BLE001 — a source failure only skips its channels
            sources[source]["failed"] += 1
            error(f"{source} {what}: {_short(exc)}")
            return None, "fetch_failed"
        sources[source]["ok"] += 1
        return value, None

    def settle(members, price: UnitPrice | None, reason: str | None, source_id: str | None) -> None:
        for model_id, _ in members:
            if price is None:
                channels[model_id] = f"skipped:{reason}"
            else:
                observed[model_id] = _Observed(price, source_id)

    def settle_doc(source: str, doc_groups, table: dict[str, UnitPrice], reason: str | None, source_id: str) -> None:
        """A doc table's prices are quantized per looked-up model only: an untracked row with an odd value (a $0.00
        input, an extra that rounds to 0) never skips the tracked channels, and a bad tracked row skips only its own."""
        for doc_name in sorted(doc_groups):
            price, why = table.get(doc_name), reason
            if why is None and price is None:
                error(f"{source}: model {doc_name!r} not in the table")
                why = "not_found"
            elif price is not None:
                try:
                    price = _quantized(_plausible_long(price, f"{source} {doc_name}"))
                except Exception as exc:  # noqa: BLE001 — a bad value only skips this model's channels
                    error(f"{source} {doc_name}: {_parse_message(exc)}")
                    price, why = None, "parse_failed"
            settle(doc_groups[doc_name], price, why, source_id)

    # 1) Anthropic pricing.md — Claude Platform on AWS
    doc_groups = groups["anthropic_doc"]
    if doc_groups:
        text, reason = fetch("anthropic_doc", "pricing.md", fetchers.anthropic_doc)
        table: dict[str, UnitPrice] = {}
        if reason is None:
            try:
                table = parse_anthropic_pricing_md(text)
            except Exception as exc:  # noqa: BLE001 — any parser error only skips the CP channels
                reason = "parse_failed"
                error(f"anthropic_doc: {_parse_message(exc)}")
        settle_doc("anthropic_doc", doc_groups, table, reason, ANTHROPIC_SOURCE_ID)

    # 2) OpenAI pricing.md — OpenAI official price (display only, openai-list:<family_key>)
    openai_groups = groups["openai_doc"]
    if openai_groups:
        text, reason = fetch("openai_doc", "pricing.md", fetchers.openai_doc)
        openai_table: dict[str, UnitPrice] = {}
        if reason is None:
            try:
                openai_table = parse_openai_pricing_md(text)
            except Exception as exc:  # noqa: BLE001 — any parser error only skips the OpenAI official price channels
                reason = "parse_failed"
                error(f"openai_doc: {_parse_message(exc)}")
        settle_doc("openai_doc", openai_groups, openai_table, reason, OPENAI_SOURCE_ID)

    # 3) AWS Price List — Nova (input, output, then the optional cache read and cache write usagetypes)
    for family_key in sorted(groups["pricelist"]):
        members = groups["pricelist"][family_key]
        usagetypes = NOVA_USAGETYPES.get(family_key)
        if usagetypes is None:
            error(f"pricelist: no usagetypes for {family_key}")
            settle(members, None, "unmapped", None)
            continue
        wanted = (*usagetypes, *NOVA_CACHE_USAGETYPES.get(family_key, ()))
        items, reason = fetch("pricelist", family_key, lambda ut=wanted: fetchers.pricelist(*ut))
        price = None
        if reason is None:
            try:
                price = _quantized(parse_pricelist(items, *wanted))
            except Exception as exc:  # noqa: BLE001 — any parser error only skips this family's channels
                reason = "parse_failed"
                error(f"pricelist {family_key}: {_parse_message(exc)}")
        settle(members, price, reason, pricelist_source_id(usagetypes[0]))

    # 4) Bedrock agreement offers — Bedrock Claude + OpenAI (one call per FM id)
    for fm_id in sorted(groups["offers"]):
        members = groups["offers"][fm_id]
        response, reason = fetch("offers", fm_id, lambda fm=fm_id: fetchers.offers(fm))
        prices: dict[str, UnitPrice | None] = {}
        if reason is None:
            try:
                offer_id, rate_card = single_public_offer(response)
                for model_id, ident in members:
                    price = select_offer_price(rate_card, ident.channel)
                    prices[model_id] = None if price is None else _quantized(
                        _plausible_long(_gpt_long_only(price, ident), f"offers {fm_id} {ident.channel}"))
            except Exception as exc:  # noqa: BLE001 — any parser error only skips this FM's channels
                offers_list = response.get("offers") if isinstance(response, dict) else None
                reason = "offer_count" if isinstance(offers_list, list) and len(offers_list) != 1 else "parse_failed"
                error(f"offers {fm_id}: {_parse_message(exc)}")
        if reason is not None:
            settle(members, None, reason, None)
            continue
        for model_id, ident in members:
            price = prices[model_id]
            if price is None:
                error(f"offers {fm_id}: no standard price for channel {ident.channel}")
                channels[model_id] = "skipped:not_found"
            else:
                observed[model_id] = _Observed(price, offer_source_id(offer_id))
    return observed, channels, sources, errors


def _effective_row(db, model_id: str, at: datetime) -> PriceHistory | None:
    return (
        db.query(PriceHistory)
        .filter(
            PriceHistory.model_id == model_id,
            PriceHistory.status.in_(_EFFECTIVE_STATUSES),
            PriceHistory.effective_from <= at,
        )
        .order_by(PriceHistory.effective_from.desc(), PriceHistory.id.desc())
        .first()
    )


def _stored(row: PriceHistory) -> dict[str, float | None]:
    return {field: getattr(row, column) for field, column in _PRICE_COLUMN.items()}


def _merged(price: UnitPrice, current: Mapping[str, float | None] | None) -> dict[str, Decimal | None]:
    """The observed value where it is set, else the current row's value (an observation that lacks a field keeps it)."""
    merged: dict[str, Decimal | None] = {}
    for field in PRICE_FIELDS:
        value = getattr(price, field)
        if value is None and current is not None and current.get(field) is not None:
            value = _dec(current[field])
        merged[field] = value
    return merged


def _same_values(row: PriceHistory, values: Mapping[str, Decimal | None]) -> bool:
    """All nine stored values equal `values` at 6 decimals, None == None.

    A held row whose seven extra columns are all NULL was held under v2.30.0, before the columns existed: it is
    compared on input and output only, so it is not duplicated and a value an admin rejected stays rejected instead
    of coming back as a new pending_review row with the extras filled in.
    """
    legacy = all(getattr(row, _PRICE_COLUMN[field]) is None for field in EXTRA_FIELDS)
    for field, want in values.items():
        if legacy and field in EXTRA_FIELDS:
            continue
        stored = getattr(row, _PRICE_COLUMN[field])
        if (stored is None) != (want is None) or (stored is not None and _dec(stored) != want):
            return False
    return True


def _held_row_with_value(db, model_id: str, values: Mapping[str, Decimal | None]) -> PriceHistory | None:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id == model_id, PriceHistory.status.in_(_HELD_STATUSES))
        .order_by(PriceHistory.id.desc())
        .all()
    )
    return next((r for r in rows if _same_values(r, values)), None)


def _apply(db, model_id: str, ident: PriceIdentity, got: _Observed, started_at: datetime, run_id: int) -> str:
    current = _effective_row(db, model_id, started_at)
    stored = None if current is None else _stored(current)
    result = classify_change(stored, got.price)
    if result in ("unchanged", "enriched"):
        current.observed_at = started_at
        current.run_id = run_id
        current.source_id = got.source_id
        if result == "enriched":  # a first-time display-only value fills the effective row, no new history row
            for field in EXTRA_FIELDS:
                value = getattr(got.price, field)
                if value is not None and stored[field] is None:
                    setattr(current, _PRICE_COLUMN[field], float(value))
        return result
    values = _merged(got.price, stored)
    if result == "changed":
        status, effective_from = "verified", started_at
    else:  # "pending" | "no_baseline"
        held = _held_row_with_value(db, model_id, values)
        if held is not None:
            held.observed_at = started_at
            held.run_id = run_id
            return "rejected" if held.status == "rejected" else result
        status = "pending_review"
        effective_from = EPOCH if result == "no_baseline" else started_at
    db.add(
        PriceHistory(
            model_id=model_id,
            family_key=ident.family_key,
            channel=ident.channel,
            effective_from=effective_from,
            source_id=got.source_id,
            status=status,
            observed_at=started_at,
            run_id=run_id,
            **{_PRICE_COLUMN[field]: None if value is None else float(value) for field, value in values.items()},
        )
    )
    return result


def _run_status(channels: Mapping[str, str], sources: Mapping[str, dict]) -> str:
    skipped = sum(1 for r in channels.values() if r.startswith("skipped:"))
    if len(channels) == skipped:
        return "failed"
    if skipped or any(s["failed"] or not s["calls"] for s in sources.values()):
        return "partial"
    return "completed"


def _close_failed(session_factory, run_id: int, finished_at: datetime, exc: BaseException) -> None:
    db = session_factory()
    try:
        run = db.get(PriceSyncRun, run_id)
        if run is not None:
            run.status = "failed"
            run.finished_at = finished_at
            run.summary = {"sources": {}, "channels": {}, "errors": [f"internal: {_short(exc)}"]}
            db.commit()
    except Exception:  # noqa: BLE001 — the original error is re-raised by the caller
        db.rollback()
        logger.exception("pricing sync: could not mark run %d failed", run_id)
    finally:
        db.close()


def run_sync(
    session_factory,
    active: Mapping[str, PriceIdentity],
    fetchers: Fetchers,
    *,
    now: Callable[[], datetime] | None = None,
    deadline_s: float = SYNC_DEADLINE_S,
) -> int:
    """One sync run; returns `price_sync_runs.id`. Re-raises only internal (DB) errors, after marking the run failed."""
    clock = now or _utcnow
    started_at = clock()
    if started_at.tzinfo is None:
        raise ValueError("run_sync: now() must return a timezone-aware datetime")
    run_id = _open_run(session_factory, started_at)
    try:
        observed, channels, sources, errors = _fetch_all(active, fetchers, clock, started_at, deadline_s)
        db = session_factory()
        try:
            changes = pending = 0
            for model_id in sorted(observed):
                result = _apply(db, model_id, active[model_id], observed[model_id], started_at, run_id)
                channels[model_id] = result
                if result == "changed":
                    changes += 1
                elif result in ("pending", "no_baseline"):
                    pending += 1
            status = _run_status(channels, sources)
            run = db.get(PriceSyncRun, run_id)
            run.finished_at = clock()
            run.status = status
            run.summary = {"sources": sources, "channels": dict(sorted(channels.items())), "errors": errors[:_MAX_ERRORS]}
            run.changes = changes
            run.pending = pending
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as exc:
        logger.exception("pricing sync run %d failed", run_id)
        _close_failed(session_factory, run_id, clock(), exc)
        raise
    results: dict[str, int] = defaultdict(int)
    for r in channels.values():
        results[r] += 1
    logger.info(
        "pricing sync run %d %s: changes=%d pending=%d results=%s",
        run_id, status, changes, pending, dict(sorted(results.items())),
    )
    return run_id
