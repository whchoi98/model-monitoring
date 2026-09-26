"""Pure, fail-closed parsers for the official price sources (v2.30.0, ADR-030): Bedrock agreement offer rate
cards, AWS Price List items (Nova) and the Anthropic pricing markdown. Prices are Decimal USD per 1M tokens.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class PriceParseError(ValueError):
    """The source payload does not have the shape the parser accepts."""


@dataclass(frozen=True)
class UnitPrice:
    input: Decimal
    output: Decimal


# ---------------------------------------------------------------- agreement offers

# Full-match allow-list (spec). Region prefixes are an allow-list, so batch/flex/priority/long_ctx/
# _LCtx/cache/Reserved and GovCloud (UGE1_, UGW1_) or other prefixes (EU_, …) never become candidates.
DIMENSION_RE = re.compile(
    r"^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?"
    r"(?:(?P<io>input|output)_tokens(?P<g>_global)?_standard"
    r"|(?P<IO>Input|Output)TokenCount(?P<G>_Global)?)$"
)

# Rate cards carry no scale; "Units" is read as USD per 1M tokens (pinned by the GPT-6 Astra fixture).
_OFFER_UNIT = "Units"
_REGION_CODES = {"us-east-1": "USE1", "us-east-2": "USE2", "us-west-2": "USW2"}

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


def _candidates(rate_card: list[dict]) -> dict[tuple[str, str, bool], dict[str, Decimal]]:
    """Allow-listed, positive entries grouped by (scheme, region code, global?) -> {"input", "output"}.

    A key that appears twice with different values is ambiguous and dropped (fail-closed).
    """
    found: dict[tuple[str, str, bool], dict[str, Decimal]] = {}
    conflicted: set[tuple[tuple[str, str, bool], str]] = set()
    for entry in rate_card:
        if not isinstance(entry, dict) or entry.get("unit") != _OFFER_UNIT:
            continue
        m = DIMENSION_RE.fullmatch(str(entry.get("dimension", "")))
        if not m:
            continue
        price = _decimal(entry.get("price"))
        if price is None or price <= 0:
            continue
        if m.group("io"):
            key = ("new", m.group("rc") or "", bool(m.group("g")))
            side = m.group("io")
        else:
            key = ("legacy", m.group("rc") or "", bool(m.group("G")))
            side = m.group("IO").lower()
        slot = found.setdefault(key, {})
        if side in slot and slot[side] != price:
            conflicted.add((key, side))
        slot[side] = price
    for key, side in conflicted:
        found[key].pop(side, None)
    return found


def _order_for(channel: str) -> tuple[tuple[str, str, bool], ...]:
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
    """Standard input/output price for a channel ("global", "us", "inregion:<region>"), or None.

    The first candidate in the spec's per-channel order that has BOTH input and output wins.
    """
    found = _candidates(rate_card)
    for key in _order_for(channel):
        slot = found.get(key, {})
        if "input" in slot and "output" in slot:
            return UnitPrice(input=slot["input"], output=slot["output"])
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


def _pricelist_usd_per_million(items: list[dict], usagetype: str) -> Decimal:
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
    if usd is None or usd <= 0:
        raise PriceParseError(f"no positive USD price for {usagetype}")
    return usd * _PER_MILLION_FROM_PER_THOUSAND


def parse_pricelist(price_list: list, input_usagetype: str, output_usagetype: str) -> UnitPrice:
    """USD per 1M tokens from `pricing.get_products` items (JSON strings or dicts), "1K tokens" x 1000."""
    if not isinstance(price_list, list):
        raise PriceParseError("price list is not a list")
    items = [_pricelist_item(it) for it in price_list]
    return UnitPrice(
        input=_pricelist_usd_per_million(items, input_usagetype),
        output=_pricelist_usd_per_million(items, output_usagetype),
    )


# ---------------------------------------------------------------- Anthropic pricing markdown

_MODEL_PRICING_HEADING_RE = re.compile(r"^##\s+Model pricing\s*$")
_SUP_RE = re.compile(r"<sup>.*?</sup>", re.IGNORECASE | re.DOTALL)
# trailing parenthesis group, one nesting level — covers "([limited availability](https://…))"
_TRAILING_PAREN_RE = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)\s*$")
_PRICE_CELL_RE = re.compile(r"^\$(\d+(?:\.\d+)?) / MTok$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_COL_MODEL = "model"
_COL_INPUT = "base input tokens"
_COL_OUTPUT = "output tokens"


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


def _model_pricing_table(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    start = next((i for i, ln in enumerate(lines) if _MODEL_PRICING_HEADING_RE.match(ln.strip())), None)
    if start is None:
        raise PriceParseError("'## Model pricing' heading not found")
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
        raise PriceParseError("no pricing table under '## Model pricing'")
    return table


def parse_anthropic_pricing_md(markdown: str) -> dict[str, UnitPrice]:
    """Cleaned doc model name -> standard price from the first table under '## Model pricing'.

    Columns are found by header name ("Model", "Base input tokens", "Output tokens"), `<sup>` is removed
    from name and value cells, and the trailing parenthesis group (incl. a markdown link) is removed from
    the name. Rows whose values are not exactly "$<n> / MTok" are skipped; a name that appears twice with
    different prices is dropped. Callers look names up by exact match only.
    """
    table = _model_pricing_table(markdown)
    header = [_norm_header(c) for c in _cells(table[0])]
    try:
        i_model, i_in, i_out = header.index(_COL_MODEL), header.index(_COL_INPUT), header.index(_COL_OUTPUT)
    except ValueError:
        raise PriceParseError(f"pricing table headers not recognised: {header}") from None
    prices: dict[str, UnitPrice] = {}
    ambiguous: set[str] = set()
    for line in table[1:]:
        cells = _cells(line)
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue
        if len(cells) != len(header):
            continue
        name = _clean_model_name(cells[i_model])
        p_in, p_out = _price_cell(cells[i_in]), _price_cell(cells[i_out])
        if not name or p_in is None or p_out is None:
            continue
        price = UnitPrice(input=p_in, output=p_out)
        if name in prices and prices[name] != price:
            ambiguous.add(name)
        prices[name] = price
    for name in ambiguous:
        prices.pop(name, None)
    if not prices:
        raise PriceParseError("pricing table has no parseable rows")
    return prices
