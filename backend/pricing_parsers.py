"""Pure, fail-closed parsers for the official price sources (v2.30.0, ADR-030; v2.31.0 extra fields): Bedrock
agreement offer rate cards, AWS Price List items (Nova), the Anthropic pricing markdown and the OpenAI pricing
markdown. Prices are Decimal USD per 1M tokens.

v2.31.0: besides the Standard input/output price, every parser reads prompt-caching prices and (GPT) long-context
prices into the optional UnitPrice fields. They are display-only; cost calculations keep using input/output.
"""

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation


class PriceParseError(ValueError):
    """The source payload does not have the shape the parser accepts."""


EXTRA_FIELDS: tuple[str, ...] = (
    "cache_read", "cache_write", "cache_write_1h",
    "long_input", "long_output", "long_cache_read", "long_cache_write",
)
PRICE_FIELDS: tuple[str, ...] = ("input", "output", *EXTRA_FIELDS)


@dataclass(frozen=True)
class UnitPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None       # cache hit / cached input
    cache_write: Decimal | None = None      # Claude 5-minute write, OpenAI "cache writes", Nova cache write
    cache_write_1h: Decimal | None = None   # Claude 1-hour write
    long_input: Decimal | None = None       # long context: GPT above OpenAI's short-context limit, Claude Haiku 5.5 over 100K
    long_output: Decimal | None = None
    long_cache_read: Decimal | None = None
    long_cache_write: Decimal | None = None


# ---------------------------------------------------------------- agreement offers

# Full-match allow-list (spec). Region prefixes are an allow-list, so batch/flex/priority/fast/Reserved, GovCloud
# (UGE1_, UGW1_) or other prefixes (EU_, …), Claude's legacy long context (_LCtx, equal to the base price) and the
# pre-price-cut cache_writes_tokens* names never become candidates.
DIMENSION_RE = re.compile(
    r"^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?"
    r"(?:(?P<new>input_tokens|output_tokens|cache_read_tokens|cached_input_tokens"
    r"|cache_write_tokens|cache_write_tokens_1h|cache_write_tokens_30m)(?P<long>_long_ctx)?(?P<g>_global)?_standard"
    r"|(?P<legacy>InputTokenCount|OutputTokenCount|CacheReadInputTokenCount|CacheWriteInputTokenCount"
    r"|CacheWrite1hInputTokenCount)(?P<G>_Global)?)$"
)

# new-scheme name -> (field, field with _long_ctx or None = ignored, priority). Priority 1 wins over 2 within one
# candidate key: GPT 5.6 offers carry both cache_read_tokens (current price) and cached_input_tokens (pre-cut).
_NEW_FIELDS: dict[str, tuple[str, str | None, int]] = {
    "input_tokens": ("input", "long_input", 1),
    "output_tokens": ("output", "long_output", 1),
    "cache_read_tokens": ("cache_read", "long_cache_read", 1),
    "cached_input_tokens": ("cache_read", "long_cache_read", 2),
    "cache_write_tokens": ("cache_write", "long_cache_write", 1),
    "cache_write_tokens_30m": ("cache_write", "long_cache_write", 1),
    "cache_write_tokens_1h": ("cache_write_1h", None, 1),
}
_LEGACY_FIELDS: dict[str, str] = {
    "InputTokenCount": "input",
    "OutputTokenCount": "output",
    "CacheReadInputTokenCount": "cache_read",
    "CacheWriteInputTokenCount": "cache_write",
    "CacheWrite1hInputTokenCount": "cache_write_1h",
}

# Rate cards carry no scale; "Units" is read as USD per 1M tokens (pinned by the GPT-6 Astra fixture).
_OFFER_UNIT = "Units"
_REGION_CODES = {"ap-northeast-2": "APN2", "us-east-1": "USE1", "us-east-2": "USE2", "us-west-2": "USW2"}

# (scheme, region code or "" for the flat scheme, global?) in the spec's selection order.
_GLOBAL_ORDER = (
    ("new", "APN2", True),
    ("new", "USE1", True),
    ("new", "", True),
    ("legacy", "APN2", True),
    ("legacy", "USE1", True),
)
_US_ORDER = (
    ("new", "USE1", False),
    ("new", "", False),
    ("legacy", "USE1", False),
)


def single_public_offer(response: dict) -> tuple[str, list[dict]]:
    """(offerId, rateCard) of the only PUBLIC offer; PriceParseError unless there is exactly one."""
    offers = response.get("offers") if isinstance(response, dict) else None
    if not isinstance(offers, list):
        raise PriceParseError("offers response has no 'offers' list")
    if len(offers) != 1:
        raise PriceParseError(f"expected exactly 1 public offer, got {len(offers)}")
    offer = offers[0]
    offer_id = offer.get("offerId") if isinstance(offer, dict) else None
    try:
        rate_card = offer["termDetails"]["usageBasedPricingTerm"]["rateCard"]
    except (KeyError, TypeError):
        raise PriceParseError("offer has no usageBasedPricingTerm.rateCard") from None
    if not isinstance(offer_id, str) or not offer_id or not isinstance(rate_card, list):
        raise PriceParseError("offer has no offerId or rateCard is not a list")
    return offer_id, rate_card


def _decimal(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


_Key = tuple[str, str, bool]


def _field_of(m: re.Match) -> tuple[_Key, str, int] | None:
    """(candidate key, field, priority) of an allow-listed dimension, or None when its name is ignored."""
    if m.group("new"):
        field, long_field, priority = _NEW_FIELDS[m.group("new")]
        if m.group("long"):
            if long_field is None:
                return None  # cache_write_tokens_1h_long_ctx: no such price field
            field = long_field
        return ("new", m.group("rc") or "", bool(m.group("g"))), field, priority
    return ("legacy", m.group("rc") or "", bool(m.group("G"))), _LEGACY_FIELDS[m.group("legacy")], 1


def _candidates(rate_card: list[dict]) -> dict[_Key, dict[str, dict[int, Decimal]]]:
    """Allow-listed, positive entries grouped by (scheme, region code, global?) -> {field: {priority: price}}.

    The same (field, priority) seen twice in one key with different prices is ambiguous and dropped (fail-closed).
    """
    found: dict[_Key, dict[str, dict[int, Decimal]]] = {}
    conflicted: set[tuple[_Key, str, int]] = set()
    for entry in rate_card:
        if not isinstance(entry, dict) or entry.get("unit") != _OFFER_UNIT:
            continue
        m = DIMENSION_RE.fullmatch(str(entry.get("dimension", "")))
        if not m:
            continue
        price = _decimal(entry.get("price"))
        if price is None or price <= 0:
            continue
        slot = _field_of(m)
        if slot is None:
            continue
        key, field, priority = slot
        by_priority = found.setdefault(key, {}).setdefault(field, {})
        if priority in by_priority and by_priority[priority] != price:
            conflicted.add((key, field, priority))
        by_priority[priority] = price
    for key, field, priority in conflicted:
        found[key][field].pop(priority, None)
    return found


def _order_for(channel: str) -> tuple[_Key, ...]:
    if channel == "global":
        return _GLOBAL_ORDER
    if channel == "us":
        return _US_ORDER
    if channel.startswith("inregion:"):
        code = _REGION_CODES.get(channel.split(":", 1)[1])
        if code is None:
            return ()
        return (("new", code, False), ("new", "", False))
    return ()


def select_offer_price(rate_card: list[dict], channel: str) -> UnitPrice | None:
    """Standard price for a channel ("global", "us", "inregion:<region>"), or None.

    The first candidate key in the spec's per-channel order that has BOTH input and output wins; every extra
    field (cache, long context) comes from that same key, at its lowest priority number, else None.
    """
    found = _candidates(rate_card)
    for key in _order_for(channel):
        picked = {field: by_priority[min(by_priority)] for field, by_priority in found.get(key, {}).items() if by_priority}
        if "input" in picked and "output" in picked:
            return UnitPrice(**picked)
    return None


# ---------------------------------------------------------------- AWS Price List

_PRICELIST_UNIT = "1K tokens"
_PER_MILLION_FROM_PER_THOUSAND = Decimal(1000)


def _pricelist_item(item) -> dict:
    if isinstance(item, str):
        try:
            item = json.loads(item)
        except ValueError:
            raise PriceParseError("price list item is not valid JSON") from None
    if not isinstance(item, dict):
        raise PriceParseError("price list item is not an object")
    return item


def _object(value, what: str) -> dict:
    """A nested price list field as a dict: {} when missing, PriceParseError when present but not an object."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PriceParseError(f"price list {what} is not an object")
    return value


def _usagetype_of(item: dict):
    return _object(_object(item.get("product"), "product").get("attributes"), "product.attributes").get("usagetype")


def _pricelist_usd_per_million(items: list[dict], usagetype: str, *, allow_zero: bool = False) -> Decimal:
    matches = [it for it in items if _usagetype_of(it) == usagetype]
    if len(matches) != 1:
        raise PriceParseError(f"expected 1 product for usagetype {usagetype}, got {len(matches)}")
    on_demand = _object(_object(matches[0].get("terms"), "terms").get("OnDemand"), "terms.OnDemand")
    dims = [
        _object(dim, "price dimension")
        for term in on_demand.values()
        for dim in _object(_object(term, "OnDemand term").get("priceDimensions"), "priceDimensions").values()
    ]
    if len(dims) != 1:
        raise PriceParseError(f"expected 1 OnDemand price dimension for {usagetype}, got {len(dims)}")
    if dims[0].get("unit") != _PRICELIST_UNIT:
        raise PriceParseError(f"unexpected unit for {usagetype}: {dims[0].get('unit')!r}")
    usd = _decimal(_object(dims[0].get("pricePerUnit"), "pricePerUnit").get("USD"))
    if usd is None or usd < 0 or (usd == 0 and not allow_zero):
        raise PriceParseError(f"no positive USD price for {usagetype}")
    if usd == 0:
        return Decimal(0)
    return usd * _PER_MILLION_FROM_PER_THOUSAND


def _optional_pricelist_usd_per_million(items: list[dict], usagetype: str | None) -> Decimal | None:
    """A cache price is fail-soft: None for no usagetype, no or duplicate product or dimension, another unit, or a
    missing or negative USD. 0 is a real price (Nova cache write is officially $0.00)."""
    if usagetype is None:
        return None
    try:
        return _pricelist_usd_per_million(items, usagetype, allow_zero=True)
    except PriceParseError:
        return None


def parse_pricelist(price_list: list, input_usagetype: str, output_usagetype: str,
                    cache_read_usagetype: str | None = None, cache_write_usagetype: str | None = None) -> UnitPrice:
    """USD per 1M tokens from `pricing.get_products` items (JSON strings or dicts), "1K tokens" x 1000.

    Input and output are strict (PriceParseError); the optional cache usagetypes are fail-soft (None).
    """
    if not isinstance(price_list, list):
        raise PriceParseError("price list is not a list")
    items = [_pricelist_item(it) for it in price_list]
    return UnitPrice(
        input=_pricelist_usd_per_million(items, input_usagetype),
        output=_pricelist_usd_per_million(items, output_usagetype),
        cache_read=_optional_pricelist_usd_per_million(items, cache_read_usagetype),
        cache_write=_optional_pricelist_usd_per_million(items, cache_write_usagetype),
    )


# ---------------------------------------------------------------- pricing markdown (Anthropic, OpenAI)

_MODEL_PRICING_HEADING_RE = re.compile(r"^##\s+Model pricing\s*$")
_SUP_RE = re.compile(r"<sup>.*?</sup>", re.IGNORECASE | re.DOTALL)
# trailing parenthesis group, one nesting level — covers "([limited availability](https://…))"
_TRAILING_PAREN_RE = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)\s*$")
# Prompt-length tiers of one model (Claude Haiku 5.5, v2.33.0): "(for prompts up to 100,000 tokens)" is the standard
# price and "(for prompts over 100,000 tokens)" the long-context price of the same cleaned name.
_PROMPT_TIER_RE = re.compile(r"\(for prompts (?P<tier>up to|over) [\d,]+ tokens\)\s*$", re.IGNORECASE)
_PRICE_CELL_RE = re.compile(r"^\$(\d+(?:\.\d+)?) / MTok$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_COL_MODEL = "model"
_COL_INPUT = "base input tokens"
_COL_OUTPUT = "output tokens"
# optional Anthropic columns (normalized header -> UnitPrice field)
_ANTHROPIC_CACHE_COLUMNS: dict[str, str] = {
    "cache hits and refreshes": "cache_read",
    "5m cache writes": "cache_write",
    "1h cache writes": "cache_write_1h",
}

_OPENAI_STANDARD_HEADING = "### Standard pricing data"
_OPENAI_VALUE_RE = re.compile(r"^\$(\d+(?:\.\d+)?)$")
_OPENAI_COL_MODEL = "model"
_OPENAI_COL_INPUT = "short context input"
_OPENAI_COL_OUTPUT = "short context output"
# optional OpenAI columns (normalized header -> UnitPrice field)
_OPENAI_EXTRA_COLUMNS: dict[str, str] = {
    "short context cached input": "cache_read",
    "short context cache writes": "cache_write",
    "long context input": "long_input",
    "long context output": "long_output",
    "long context cached input": "long_cache_read",
    "long context cache writes": "long_cache_write",
}


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _norm_header(cell: str) -> str:
    return " ".join(cell.split()).lower()


def _clean_model_name(cell: str) -> str:
    name = _SUP_RE.sub("", cell).strip()
    name = _TRAILING_PAREN_RE.sub("", name).strip()
    return " ".join(name.split())


def _price_cell(cell: str) -> Decimal | None:
    m = _PRICE_CELL_RE.fullmatch(_SUP_RE.sub("", cell).strip())
    return Decimal(m.group(1)) if m else None


def _openai_value(cell: str) -> Decimal | None:
    m = _OPENAI_VALUE_RE.fullmatch(cell.strip())
    return Decimal(m.group(1)) if m else None


def _first_table_after(markdown: str, is_heading, title: str) -> list[str]:
    """Table lines of the first table after the first heading line that `is_heading` accepts (stripped line).

    A '#' heading before any table ends the search; fewer than 3 table lines (header, separator, one row) raise.
    """
    lines = markdown.splitlines()
    start = next((i for i, ln in enumerate(lines) if is_heading(ln.strip())), None)
    if start is None:
        raise PriceParseError(f"'{title}' heading not found")
    table: list[str] = []
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if stripped.startswith("#"):
            break  # next section before any table
        if stripped.startswith("|"):
            table.append(stripped)
        elif table:
            break  # first table ended
    if len(table) < 3:
        raise PriceParseError(f"no pricing table under '{title}'")
    return table


def _model_pricing_table(markdown: str) -> list[str]:
    return _first_table_after(markdown, lambda s: _MODEL_PRICING_HEADING_RE.match(s) is not None, "## Model pricing")


def _rows(table: list[str], header: list[str]):
    """Data rows of a table as cell lists: separator rows and rows with the wrong cell count are skipped."""
    for line in table[1:]:
        cells = _cells(line)
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue
        if len(cells) != len(header):
            continue
        yield cells


def _unambiguous(pairs) -> dict[str, UnitPrice]:
    """{name: price} from (name, price) pairs.

    A name seen twice with a different input or output is dropped. When input and output agree, the name is kept
    and every extra field whose values differ (one side None and the other set counts as different) becomes None.
    """
    prices: dict[str, UnitPrice] = {}
    ambiguous: set[str] = set()
    for name, price in pairs:
        seen = prices.get(name)
        if seen is None:
            prices[name] = price
        elif (seen.input, seen.output) != (price.input, price.output):
            ambiguous.add(name)
        else:
            prices[name] = replace(seen, **{f: None for f in EXTRA_FIELDS if getattr(seen, f) != getattr(price, f)})
    for name in ambiguous:
        prices.pop(name, None)
    return prices


def parse_anthropic_pricing_md(markdown: str) -> dict[str, UnitPrice]:
    """Cleaned doc model name -> standard price from the first table under '## Model pricing'.

    Columns are found by header name ("Model", "Base input tokens", "Output tokens", and the optional
    "Cache hits and refreshes", "5m cache writes", "1h cache writes"), `<sup>` is removed from name and value
    cells, and the trailing parenthesis group (incl. a markdown link) is removed from the name. A model priced by
    prompt length has two rows, "(for prompts up to N tokens)" and "(for prompts over N tokens)": the first is its
    standard price and the second fills long_input, long_output, long_cache_read and long_cache_write (5-minute
    write) of the same name; an "over" row without its "up to" row is ignored (v2.33.0). Rows whose
    input or output is not exactly "$<n> / MTok" are skipped; such an optional cell is None. A name that
    appears twice with a different input or output is dropped; with the same input and output it is kept and a
    cache price that differs between the rows is None. Callers look names up by exact match only.
    """
    table = _model_pricing_table(markdown)
    header = [_norm_header(c) for c in _cells(table[0])]
    try:
        i_model, i_in, i_out = header.index(_COL_MODEL), header.index(_COL_INPUT), header.index(_COL_OUTPUT)
    except ValueError:
        raise PriceParseError(f"pricing table headers not recognised: {header}") from None
    extra = {field: header.index(col) for col, field in _ANTHROPIC_CACHE_COLUMNS.items() if col in header}

    long_rows: list[tuple[str, UnitPrice]] = []

    def pairs():
        for cells in _rows(table, header):
            name = _clean_model_name(cells[i_model])
            p_in, p_out = _price_cell(cells[i_in]), _price_cell(cells[i_out])
            if not name or p_in is None or p_out is None:
                continue
            price = UnitPrice(input=p_in, output=p_out, **{f: _price_cell(cells[i]) for f, i in extra.items()})
            tier = _PROMPT_TIER_RE.search(_SUP_RE.sub("", cells[i_model]).strip())
            if tier and tier.group("tier").lower() == "over":
                long_rows.append((name, price))
                continue
            yield name, price

    prices = _unambiguous(pairs())
    if not prices:
        raise PriceParseError("pricing table has no parseable rows")
    longs = _unambiguous(iter(long_rows))
    for name, long in longs.items():
        if name in prices:
            prices[name] = replace(prices[name], long_input=long.input, long_output=long.output,
                                   long_cache_read=long.cache_read, long_cache_write=long.cache_write)
    return prices


def parse_openai_pricing_md(markdown: str) -> dict[str, UnitPrice]:
    """OpenAI doc model name -> Standard price from the first table under '### Standard pricing data'.

    The Batch, Flex and Fast tables further down are never read. Columns are found by header name; required
    "Model", "Short context input", "Short context output", optional cached input, cache writes and the four
    "Long context" columns. A value cell is exactly "$<n>" (e.g. "$0.125"); anything else ("-", blank) is None
    and a row without both short-context input and output is skipped. Names lose `<sup>` and the trailing
    parenthesis group ("gpt-5.5 (<272K context length)" -> "gpt-5.5"); lookups are exact ("gpt-5.4" is not
    "gpt-5.4-mini"). A name seen twice with a different short-context input or output is dropped; with the same
    input and output it is kept and an optional value that differs between the rows is None.
    """
    table = _first_table_after(markdown, lambda s: s == _OPENAI_STANDARD_HEADING, _OPENAI_STANDARD_HEADING)
    header = [_norm_header(c) for c in _cells(table[0])]
    try:
        i_model = header.index(_OPENAI_COL_MODEL)
        i_in = header.index(_OPENAI_COL_INPUT)
        i_out = header.index(_OPENAI_COL_OUTPUT)
    except ValueError:
        raise PriceParseError(f"OpenAI pricing table headers not recognised: {header}") from None
    extra = {field: header.index(col) for col, field in _OPENAI_EXTRA_COLUMNS.items() if col in header}

    def pairs():
        for cells in _rows(table, header):
            name = _clean_model_name(cells[i_model])
            p_in, p_out = _openai_value(cells[i_in]), _openai_value(cells[i_out])
            if not name or p_in is None or p_out is None:
                continue
            yield name, UnitPrice(input=p_in, output=p_out, **{f: _openai_value(cells[i]) for f, i in extra.items()})

    prices = _unambiguous(pairs())
    if not prices:
        raise PriceParseError("OpenAI pricing table has no parseable rows")
    return prices
