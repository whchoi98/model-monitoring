"""Official price source parsers (v2.30.0, ADR-030; v2.31.0 cache and long-context fields, OpenAI doc) — offline,
sanitized fixtures regenerated from the 2026-09-27 sources (tests/fixtures/pricing/)."""

import dataclasses
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from pricing_parsers import (
    DIMENSION_RE, EXTRA_FIELDS, PRICE_FIELDS, PriceParseError, UnitPrice, parse_anthropic_pricing_md,
    parse_openai_pricing_md, parse_pricelist, select_offer_price, single_public_offer,
)
from pricing_sources import ANTHROPIC_DOC_NAMES, NOVA_USAGETYPES

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
# Nova 2.0 Lite prompt-cache usagetypes (read, write) as the 2026-09-27 Price List names them
NOVA_CACHE = ("USE1-Nova2.0Lite-cache-read-input-token-count", "USE1-Nova2.0Lite-cache-write-input-token-count")
# v2.30.0 allow-list (input/output only) — the v2.31.0 input/output selection must equal it on every fixture
V230_DIMENSION_RE = re.compile(
    r"^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?"
    r"(?:(?P<io>input|output)_tokens(?P<g>_global)?_standard"
    r"|(?P<IO>Input|Output)TokenCount(?P<G>_Global)?)$"
)


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _card(name):
    return single_public_offer(_load(name))[1]


def D(v):
    return Decimal(str(v))


def P(i, o):
    return UnitPrice(input=D(i), output=D(o))


def U(i, o, **extra):
    return UnitPrice(input=D(i), output=D(o), **{k: D(v) for k, v in extra.items()})


def E(dimension, price, unit="Units"):
    return {"dimension": dimension, "price": price, "description": dimension, "unit": unit}


def test_fixtures_are_sanitized():
    names = {f.name for f in FIXTURES.iterdir()}
    assert names >= {"offers_claude-opus-5-5.json", "offers_claude-sonnet-4-6.json", "offers_claude-haiku-4-5.json",
                     "offers_claude-fable-5-1.json", "offers_gpt-6-astra.json", "offers_gpt-5.4.json",
                     "offers_gpt-5.5.json", "offers_gpt-5.6-terra.json", "offers_gpt-5.6-luna.json",
                     "pricelist_nova-2-lite.json", "anthropic_pricing.md", "openai_pricing.md"}
    for f in FIXTURES.iterdir():
        text = f.read_text(encoding="utf-8")
        for forbidden in ("offerToken", "legalTerm", "X-Amz", "Security-Token", "awsmp-offer-legal"):
            assert forbidden not in text, f"{f.name} contains {forbidden}"


def test_price_fields_contract():
    assert EXTRA_FIELDS == ("cache_read", "cache_write", "cache_write_1h",
                            "long_input", "long_output", "long_cache_read", "long_cache_write")
    assert PRICE_FIELDS == ("input", "output", *EXTRA_FIELDS)
    assert tuple(f.name for f in dataclasses.fields(UnitPrice)) == PRICE_FIELDS
    price = P(4, 20)
    assert all(getattr(price, f) is None for f in EXTRA_FIELDS)
    with pytest.raises(dataclasses.FrozenInstanceError):
        price.cache_read = D("0.2")


# ---------------------------------------------------------------- agreement offers


def test_single_public_offer_returns_offer_id_and_rate_card():
    offer_id, card = single_public_offer(_load("offers_claude-opus-5-5.json"))
    assert offer_id == "offer-7sp77cpl4rveu" and any(e["dimension"] == "USE1_input_tokens_standard" for e in card)


def _offer(offer_id, card):
    return {"offerId": offer_id, "termDetails": {"usageBasedPricingTerm": {"rateCard": card}}}


@pytest.mark.parametrize("response", [
    {"offers": []},
    {"offers": [_offer("offer-a", [E("input_tokens_standard", "2.2")]), _offer("offer-b", [E("input_tokens_standard", "3")])]},
    {"modelId": "openai.gpt-6-sol"},
    {"offers": [{"offerId": "offer-a", "termDetails": {}}]},
], ids=["zero-offers", "two-offers", "no-offers-key", "no-rate-card"])
def test_single_public_offer_rejects_anything_but_exactly_one_offer(response):
    with pytest.raises(PriceParseError):
        single_public_offer(response)


ASTRA_STANDARD = U(11, 55, cache_read="1.1", cache_write="13.75", long_input=22, long_output="82.5",
                   long_cache_read="2.2", long_cache_write="27.5")
GPT54_STANDARD = U("2.75", "16.5", cache_read="0.275", long_input="5.5", long_output="24.75", long_cache_read="0.55")


@pytest.mark.parametrize(("fixture", "channel", "expected"), [
    # region-prefix scheme (Claude 5.x): 5-minute write, 1-hour write, cache read
    ("offers_claude-opus-5-5.json", "global", U(4, 20, cache_read="0.2", cache_write=5, cache_write_1h=8)),
    ("offers_claude-opus-5-5.json", "us", U("4.4", 22, cache_read="0.22", cache_write="5.5", cache_write_1h="8.8")),
    # legacy TokenCount scheme (the _LCtx dimensions equal the base price and are never read)
    ("offers_claude-sonnet-4-6.json", "global", U(3, 15, cache_read="0.3", cache_write="3.75", cache_write_1h=6)),
    ("offers_claude-sonnet-4-6.json", "us", U("3.3", "16.5", cache_read="0.33", cache_write="4.125", cache_write_1h="6.6")),
    # both schemes, same values
    ("offers_claude-haiku-4-5.json", "global", U(1, 5, cache_read="0.1", cache_write="1.25", cache_write_1h=2)),
    ("offers_claude-haiku-4-5.json", "us", U("1.1", "5.5", cache_read="0.11", cache_write="1.375", cache_write_1h="2.2")),
    ("offers_claude-fable-5-1.json", "us", U(11, 55, cache_read="0.275", cache_write="13.75", cache_write_1h=22)),
    # flat scheme; unit anchor = AWS model card; cache_write_tokens_30m is the OpenAI "cache writes" price
    ("offers_gpt-6-astra.json", "global", U(10, 50, cache_read=1, cache_write="12.5", long_input=20, long_output=75,
                                            long_cache_read=2, long_cache_write=25)),
    ("offers_gpt-6-astra.json", "us", ASTRA_STANDARD),
    ("offers_gpt-6-astra.json", "inregion:us-west-2", ASTRA_STANDARD),
    # region-prefix scheme with both cache_read_tokens and cached_input_tokens (same value), no cache write
    ("offers_gpt-5.4.json", "inregion:us-east-1", GPT54_STANDARD),
    ("offers_gpt-5.4.json", "inregion:us-east-2", GPT54_STANDARD),
    ("offers_gpt-5.4.json", "inregion:us-west-2", GPT54_STANDARD),
    # long-context cache read only as cached_input_tokens_long_ctx (priority 2)
    ("offers_gpt-5.5.json", "inregion:us-east-1", U("5.5", 33, cache_read="0.55", long_input=11, long_output="49.5",
                                                    long_cache_read="1.1")),
    # cache_read_tokens (current, 0.2) beats cached_input_tokens (pre-cut, 0.25); cache_writes_tokens never read
    ("offers_gpt-5.6-terra.json", "global", U(2, 12, cache_read="0.2", cache_write="2.5", long_input=4, long_output=18,
                                              long_cache_read="0.4", long_cache_write=5)),
    ("offers_gpt-5.6-luna.json", "inregion:us-east-2", U("0.22", "1.32", cache_read="0.022", cache_write="0.275",
                                                         long_input="0.44", long_output="1.98",
                                                         long_cache_read="0.044", long_cache_write="0.55")),
])
def test_select_offer_price_from_real_rate_cards(fixture, channel, expected):
    assert select_offer_price(_card(fixture), channel) == expected


OFFER_FIXTURES = sorted(f.name for f in FIXTURES.glob("offers_*.json"))
CHANNELS = ("global", "us", "inregion:us-east-1", "inregion:us-east-2", "inregion:us-west-2")


@pytest.mark.parametrize("fixture", OFFER_FIXTURES)
def test_cache_and_long_context_dimensions_never_change_input_and_output(fixture):
    """Every fixture and channel gives the v2.30.0 input/output (the extra names only fill their own fields)."""
    card = _card(fixture)
    base_card = [e for e in card if V230_DIMENSION_RE.fullmatch(str(e["dimension"]))]
    for channel in CHANNELS:
        full, base = select_offer_price(card, channel), select_offer_price(base_card, channel)
        assert (full is None) == (base is None), (fixture, channel)
        if base is not None:
            assert (full.input, full.output) == (base.input, base.output), (fixture, channel)
            assert all(getattr(base, f) is None for f in EXTRA_FIELDS)


@pytest.mark.parametrize("fixture", [f for f in OFFER_FIXTURES if "claude" in f])
def test_claude_offers_have_no_long_context_price(fixture):
    card = _card(fixture)
    for channel in ("global", "us"):
        price = select_offer_price(card, channel)
        assert price.cache_read is not None and price.cache_write is not None and price.cache_write_1h is not None
        assert (price.long_input, price.long_output, price.long_cache_read, price.long_cache_write) == (None,) * 4


@pytest.mark.parametrize("channel", ["cp", "inregion:eu-west-1", "inregion:", "bogus"])
def test_channels_without_an_offer_rule_get_none(channel):
    assert select_offer_price(_card("offers_gpt-6-astra.json"), channel) is None


@pytest.mark.parametrize("dimension", [
    "input_tokens_standard", "output_tokens_global_standard", "APN2_input_tokens_global_standard",
    "USE2_input_tokens_standard", "USW2_output_tokens_standard", "USE1_InputTokenCount", "APN2_OutputTokenCount_Global",
    # v2.31.0: cache and long-context names (their own fields; input/output selection is unchanged)
    "USE1_cache_read_tokens_standard", "USE1_input_tokens_long_ctx_standard", "cached_input_tokens_long_ctx_global_standard",
    "cache_write_tokens_30m_long_ctx_global_standard", "APN2_cache_write_tokens_1h_global_standard",
    "USE1_cache_write_tokens_standard", "USE1_CacheReadInputTokenCount", "APN2_CacheWrite1hInputTokenCount_Global",
    "USW2_CacheWriteInputTokenCount",
])
def test_dimension_allow_list_accepts(dimension):
    assert DIMENSION_RE.fullmatch(dimension)


@pytest.mark.parametrize("dimension", [
    "UGE1_input_tokens_standard", "UGW1_InputTokenCount", "EU_input_tokens_standard", "USE1_input_tokens_batch",
    "input_tokens_priority", "input_tokens_global_flex", "USE1_InputTokenCount_LCtx", "APN2_InputTokenCount_Global_Batch",
    "APN2_Reserved_1Month_InputTPM_Global", "use1_input_tokens_standard",
    # v2.31.0 extra names stay excluded outside the allow-list
    "cache_writes_tokens_standard", "cache_writes_tokens_global_standard", "cache_writes_tokens_long_ctx_standard",
    "USE1_CacheReadInputTokenCount_LCtx", "APN2_CacheWrite1hInputTokenCount_LCtx_Global", "EU_cache_read_tokens_standard",
    "UGE1_cache_write_tokens_1h_standard", "cache_read_tokens_global_long_ctx_standard", "cache_read_tokens_long_ctx_flex",
    "cache_write_tokens_30m_priority", "USE1_cached_input_tokens_batch", "cache_write_tokens_5m_standard",
])
def test_dimension_allow_list_rejects(dimension):
    assert DIMENSION_RE.fullmatch(dimension) is None


def test_govcloud_and_eu_entries_of_a_real_card_are_never_candidates():
    excluded = [e for e in _card("offers_claude-opus-5-5.json") if e["dimension"].startswith(("UGE1_", "EU_"))]
    assert {"UGE1_input_tokens_standard", "EU_input_tokens_standard", "EU_cache_read_tokens_standard",
            "UGE1_cache_write_tokens_1h_standard"} <= {e["dimension"] for e in excluded}
    assert all(select_offer_price(excluded, ch) is None for ch in ("global", "us", "inregion:us-east-1"))
    with_prefixed_cache = [E("USE1_input_tokens_standard", "4.4"), E("USE1_output_tokens_standard", "22"),
                           E("EU_cache_read_tokens_standard", "0.9"), E("UGE1_cache_write_tokens_standard", "9"),
                           E("USE1_cache_read_tokens_batch", "0.1"), E("USE1_cache_read_tokens_priority", "0.5")]
    assert select_offer_price(with_prefixed_cache, "us") == P("4.4", 22)


def test_zero_price_other_unit_and_conflicting_duplicates_are_dropped():
    zero = [E("USE1_input_tokens_standard", "0"), E("USE1_output_tokens_standard", "16.5"),
            E("input_tokens_standard", "2.75"), E("output_tokens_standard", "16.5")]
    assert select_offer_price(zero, "inregion:us-east-1") == P("2.75", "16.5")
    assert select_offer_price([E("input_tokens_standard", "11", "1K tokens"), E("output_tokens_standard", "55", "1K tokens")], "us") is None
    dup = [E("USE1_input_tokens_standard", "4.4"), E("USE1_input_tokens_standard", "5.5"), E("USE1_output_tokens_standard", "22"),
           E("input_tokens_standard", "4"), E("output_tokens_standard", "20")]
    assert select_offer_price(dup, "us") == P(4, 20)
    half = [E("USE1_input_tokens_standard", "6"), E("input_tokens_standard", "7"), E("output_tokens_standard", "70")]
    assert select_offer_price(half, "us") == P(7, 70)          # a candidate needs both input and output


def test_zero_or_other_unit_extra_prices_are_not_candidates():
    card = [E("USE1_input_tokens_standard", "4.4"), E("USE1_output_tokens_standard", "22"),
            E("USE1_cache_write_tokens_standard", "0"), E("USE1_cache_read_tokens_standard", "0.22", "1K tokens"),
            E("USE1_cache_write_tokens_1h_standard", "NaN")]
    assert select_offer_price(card, "us") == P("4.4", 22)      # offers never report a real 0 extra price


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_rate_card_prices_are_never_candidates(bad):
    card = [E("USE1_input_tokens_standard", bad), E("USE1_output_tokens_standard", "22"),
            E("input_tokens_standard", "4"), E("output_tokens_standard", "20")]
    assert select_offer_price(card, "us") == P(4, 20)  # the USE1 pair has no input, the flat pair wins
    assert select_offer_price([E("input_tokens_standard", "4"), E("output_tokens_standard", bad)], "us") is None


def test_cache_read_tokens_win_over_cached_input_tokens_within_one_key():
    terra = select_offer_price(_card("offers_gpt-5.6-terra.json"), "global")
    assert (terra.cache_read, terra.long_cache_read) == (D("0.2"), D("0.4"))  # not the pre-cut 0.25 / 0.5
    only_cached = [E("input_tokens_standard", "2.2"), E("output_tokens_standard", "13.2"),
                   E("cached_input_tokens_standard", "0.275"), E("cached_input_tokens_long_ctx_standard", "0.55")]
    price = select_offer_price(only_cached, "us")
    assert (price.cache_read, price.long_cache_read) == (D("0.275"), D("0.55"))  # GPT 5.4/5.5 APN2_ style
    both = only_cached + [E("cache_read_tokens_standard", "0.22"), E("cache_read_tokens_long_ctx_standard", "0.44")]
    for card in (both, list(reversed(both))):                 # card order does not matter
        price = select_offer_price(card, "us")
        assert (price.cache_read, price.long_cache_read) == (D("0.22"), D("0.44"))


def test_cache_writes_tokens_are_never_read():
    terra = select_offer_price(_card("offers_gpt-5.6-terra.json"), "global")
    assert (terra.cache_write, terra.long_cache_write) == (D("2.5"), D(5))   # cache_write_tokens_30m, not 3.125 / 6.25
    card = [E("input_tokens_global_standard", "2"), E("output_tokens_global_standard", "12"),
            E("cache_writes_tokens_global_standard", "3.125"), E("cache_writes_tokens_long_ctx_global_standard", "6.25")]
    assert select_offer_price(card, "global") == P(2, 12)


def test_claude_legacy_long_context_and_1h_long_context_are_ignored():
    legacy = [E("USE1_InputTokenCount", "3.3"), E("USE1_OutputTokenCount", "16.5"),
              E("USE1_InputTokenCount_LCtx", "6.6"), E("USE1_OutputTokenCount_LCtx", "24.75")]
    assert select_offer_price(legacy, "us") == P("3.3", "16.5")
    one_hour_long = [E("input_tokens_standard", "11"), E("output_tokens_standard", "55"),
                     E("cache_write_tokens_1h_standard", "22"), E("cache_write_tokens_1h_long_ctx_standard", "44")]
    assert select_offer_price(one_hour_long, "us") == U(11, 55, cache_write_1h=22)


def test_extras_come_from_the_winning_key_only():
    card = [E("USE1_input_tokens_standard", "4.4"), E("USE1_output_tokens_standard", "22"),
            E("USE1_cache_write_tokens_1h_standard", "8.8"),
            E("cache_read_tokens_standard", "0.4"), E("cache_write_tokens_standard", "5")]  # flat key, never merged
    assert select_offer_price(card, "us") == U("4.4", 22, cache_write_1h="8.8")
    no_pair = [E("USE1_cache_read_tokens_standard", "0.22"), E("input_tokens_standard", "4"), E("output_tokens_standard", "20")]
    assert select_offer_price(no_pair, "us") == P(4, 20)   # USE1 has no input/output pair; its cache price is not borrowed


def test_extra_conflicts_are_dropped_per_field_and_priority():
    card = [E("USE1_input_tokens_standard", "4.4"), E("USE1_output_tokens_standard", "22"),
            E("USE1_cache_write_tokens_standard", "5.5"), E("USE1_cache_write_tokens_standard", "6"),   # ambiguous
            E("USE1_cache_read_tokens_standard", "0.22"), E("USE1_cache_read_tokens_standard", "0.22"),  # same twice: kept
            E("USE1_cache_write_tokens_1h_standard", "8.8")]
    assert select_offer_price(card, "us") == U("4.4", 22, cache_read="0.22", cache_write_1h="8.8")
    # cache_write_tokens and cache_write_tokens_30m share (cache_write, priority 1)
    mixed = [E("input_tokens_standard", "11"), E("output_tokens_standard", "55"),
             E("cache_write_tokens_standard", "13.75"), E("cache_write_tokens_30m_standard", "12")]
    assert select_offer_price(mixed, "us") == P(11, 55)
    # a dropped priority-1 name leaves the priority-2 name of the same key
    fallback = [E("input_tokens_standard", "2.2"), E("output_tokens_standard", "13.2"),
                E("cache_read_tokens_standard", "0.22"), E("cache_read_tokens_standard", "0.23"),
                E("cached_input_tokens_standard", "0.275")]
    assert select_offer_price(fallback, "us") == U("2.2", "13.2", cache_read="0.275")


def _drain(card, channel):
    seen, rc = [], list(card)
    while (price := select_offer_price(rc, channel)) is not None:
        seen.append(int(price.input))
        rc = [e for e in rc if Decimal(e["price"]) not in (price.input, price.output)]
    return seen


def test_selection_order_per_channel():
    card = [E(d, p) for d, p in [
        ("APN2_input_tokens_global_standard", "1"), ("APN2_output_tokens_global_standard", "10"),
        ("USE1_input_tokens_global_standard", "2"), ("USE1_output_tokens_global_standard", "20"),
        ("input_tokens_global_standard", "3"), ("output_tokens_global_standard", "30"),
        ("APN2_InputTokenCount_Global", "4"), ("APN2_OutputTokenCount_Global", "40"),
        ("USE1_InputTokenCount_Global", "5"), ("USE1_OutputTokenCount_Global", "50"),
        ("USE1_input_tokens_standard", "6"), ("USE1_output_tokens_standard", "60"),
        ("input_tokens_standard", "7"), ("output_tokens_standard", "70"),
        ("USE1_InputTokenCount", "8"), ("USE1_OutputTokenCount", "80"),
        ("USE2_input_tokens_standard", "9"), ("USE2_output_tokens_standard", "90"),
        ("USW2_input_tokens_standard", "11"), ("USW2_output_tokens_standard", "110"),
    ]]
    assert _drain(card, "global") == [1, 2, 3, 4, 5]
    assert _drain(card, "us") == [6, 7, 8]
    assert _drain(card, "inregion:us-east-1") == [6, 7]
    assert _drain(card, "inregion:us-east-2") == [9, 7]
    assert _drain(card, "inregion:us-west-2") == [11, 7]


# ---------------------------------------------------------------- AWS Price List


def test_nova_price_list_is_converted_from_per_1k_to_per_1m():
    items = _load("pricelist_nova-2-lite.json")["PriceList"]
    in_ut, out_ut = NOVA_USAGETYPES["nova-2-lite"]
    assert parse_pricelist(items, in_ut, out_ut) == P("0.33", "2.75")   # cache usagetypes not asked: None
    assert parse_pricelist([json.loads(s) for s in items], in_ut, out_ut) == P("0.33", "2.75")


def test_nova_cache_usagetypes_are_read_when_given():
    items = _load("pricelist_nova-2-lite.json")["PriceList"]
    price = parse_pricelist(items, *NOVA_USAGETYPES["nova-2-lite"], *NOVA_CACHE)
    assert price == U("0.33", "2.75", cache_read="0.0825", cache_write=0)
    assert price.cache_write is not None and price.cache_write == 0      # officially $0.00, a real price
    assert (price.cache_write_1h, price.long_input, price.long_output) == (None, None, None)


def _cache_read_item(decoded):
    (item,) = [it for it in decoded if it["product"]["attributes"]["usagetype"] == NOVA_CACHE[0]]
    return item


def _mutate_cache_read(kind):
    decoded = [json.loads(s) for s in _load("pricelist_nova-2-lite.json")["PriceList"]]
    item = _cache_read_item(decoded)
    (term,) = item["terms"]["OnDemand"].values()
    (dim,) = term["priceDimensions"].values()
    if kind == "missing":
        decoded.remove(item)
    elif kind == "duplicate":
        decoded.append(json.loads(json.dumps(item)))
    elif kind == "two-dimensions":
        term["priceDimensions"]["EXTRA.RATE"] = dict(dim, rateCode="EXTRA.RATE")
    elif kind == "other-unit":
        dim["unit"] = "1M tokens"
    elif kind == "negative":
        dim["pricePerUnit"] = {"USD": "-0.0000825"}
    elif kind == "no-usd":
        dim["pricePerUnit"] = {}
    elif kind == "nan":
        dim["pricePerUnit"] = {"USD": "NaN"}
    elif kind == "terms-not-an-object":
        item["terms"] = ["not", "an", "object"]
    return decoded


@pytest.mark.parametrize("kind", ["missing", "duplicate", "two-dimensions", "other-unit", "negative", "no-usd", "nan",
                                  "terms-not-an-object"])
def test_nova_cache_prices_are_fail_soft(kind):
    price = parse_pricelist(_mutate_cache_read(kind), *NOVA_USAGETYPES["nova-2-lite"], *NOVA_CACHE)
    assert price == U("0.33", "2.75", cache_write=0)                    # only the broken cache read is None


def test_nova_cache_usagetype_none_or_unknown_is_none():
    items = _load("pricelist_nova-2-lite.json")["PriceList"]
    in_ut, out_ut = NOVA_USAGETYPES["nova-2-lite"]
    assert parse_pricelist(items, in_ut, out_ut, None, NOVA_CACHE[1]) == U("0.33", "2.75", cache_write=0)
    assert parse_pricelist(items, in_ut, out_ut, "USE1-Nova2.0Lite-cache-read-input-token-count-priority-x", None) == P("0.33", "2.75")


def test_price_list_unit_mismatch_missing_or_duplicate_product_raises():
    items = _load("pricelist_nova-2-lite.json")["PriceList"]
    in_ut, out_ut = NOVA_USAGETYPES["nova-2-lite"]
    decoded = [json.loads(s) for s in items]
    for item in decoded:
        if item["product"]["attributes"]["usagetype"] == out_ut:
            for term in item["terms"]["OnDemand"].values():
                for dim in term["priceDimensions"].values():
                    dim["unit"] = "1M tokens"
    with pytest.raises(PriceParseError, match="unit"):
        parse_pricelist(decoded, in_ut, out_ut)
    for bad in ([s for s in items if out_ut + '"' not in s], items + items, ["not json"]):
        with pytest.raises(PriceParseError):
            parse_pricelist(bad, in_ut, out_ut)
        with pytest.raises(PriceParseError):
            parse_pricelist(bad, in_ut, out_ut, *NOVA_CACHE)            # input/output stay strict with cache asked


def _nova_decoded():
    """Decoded Nova Price List items and the input-usagetype item (one OnDemand term, one dimension)."""
    decoded = [json.loads(s) for s in _load("pricelist_nova-2-lite.json")["PriceList"]]
    (item,) = [it for it in decoded if it["product"]["attributes"]["usagetype"] == NOVA_USAGETYPES["nova-2-lite"][0]]
    return decoded, item


def _only_dimension(item):
    (term,) = item["terms"]["OnDemand"].values()
    (dim,) = term["priceDimensions"].values()
    return term["priceDimensions"], dim


def test_price_list_two_on_demand_dimensions_raise():
    decoded, item = _nova_decoded()
    dims, dim = _only_dimension(item)
    dims["EXTRA.RATE"] = dict(dim, rateCode="EXTRA.RATE")
    with pytest.raises(PriceParseError, match="expected 1 OnDemand price dimension"):
        parse_pricelist(decoded, *NOVA_USAGETYPES["nova-2-lite"])


@pytest.mark.parametrize("usd", ["0", "0.0000000000", "-0.00033", "NaN", None])
def test_price_list_zero_negative_or_missing_usd_raises(usd):
    decoded, item = _nova_decoded()
    _only_dimension(item)[1]["pricePerUnit"] = {} if usd is None else {"USD": usd}
    with pytest.raises(PriceParseError, match="no positive USD price"):
        parse_pricelist(decoded, *NOVA_USAGETYPES["nova-2-lite"])
    with pytest.raises(PriceParseError, match="no positive USD price"):   # 0 is allowed for cache prices only
        parse_pricelist(decoded, *NOVA_USAGETYPES["nova-2-lite"], *NOVA_CACHE)


@pytest.mark.parametrize("path", [
    ("product",), ("product", "attributes"), ("terms",), ("terms", "OnDemand"), ("terms", "OnDemand", "*"),
    ("terms", "OnDemand", "*", "priceDimensions"), ("terms", "OnDemand", "*", "priceDimensions", "*"),
    ("terms", "OnDemand", "*", "priceDimensions", "*", "pricePerUnit"),
], ids=".".join)
def test_price_list_fields_that_are_not_objects_raise_price_parse_error(path):
    """A nested field of the wrong type is a PriceParseError, never an AttributeError ("*" = the only key)."""
    decoded, parent = _nova_decoded()
    for key in path[:-1]:
        parent = parent[next(iter(parent)) if key == "*" else key]
    parent[next(iter(parent)) if path[-1] == "*" else path[-1]] = ["not", "an", "object"]
    with pytest.raises(PriceParseError, match="is not an object"):
        parse_pricelist(decoded, *NOVA_USAGETYPES["nova-2-lite"])


# ---------------------------------------------------------------- Anthropic pricing markdown

CP_EXPECTED = {  # the nine Claude Platform on AWS families: input, output, cache read, 5m write, 1h write
    "Claude Fable 5.1": U(10, 50, cache_read="0.25", cache_write="12.5", cache_write_1h=20),
    "Claude Fable 5": U(10, 50, cache_read=1, cache_write="12.5", cache_write_1h=20),
    "Claude Opus 5.5": U(4, 20, cache_read="0.2", cache_write=5, cache_write_1h=8),
    "Claude Opus 5": U(5, 25, cache_read="0.5", cache_write="6.25", cache_write_1h=10),
    "Claude Opus 4.8": U(5, 25, cache_read="0.5", cache_write="6.25", cache_write_1h=10),
    "Claude Opus 4.7": U(5, 25, cache_read="0.5", cache_write="6.25", cache_write_1h=10),
    "Claude Sonnet 5": U(2, 10, cache_read="0.2", cache_write="2.5", cache_write_1h=4),
    "Claude Sonnet 4.6": U(3, 15, cache_read="0.3", cache_write="3.75", cache_write_1h=6),
    "Claude Haiku 4.5": U(1, 5, cache_read="0.1", cache_write="1.25", cache_write_1h=2),
}


def _doc():
    return parse_anthropic_pricing_md((FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8"))


def test_real_doc_gives_all_nine_claude_platform_on_aws_families():
    prices = _doc()
    assert sorted(ANTHROPIC_DOC_NAMES.values()) == sorted(CP_EXPECTED)
    assert {name: prices[name] for name in CP_EXPECTED} == CP_EXPECTED
    # Sonnet 5 value cells are "$2 / MTok<sup>3</sup>" / "$10 / MTok<sup>3</sup>", the Fable 5.1 and Opus 5.5 cache
    # hits cells carry <sup>1</sup> / <sup>2</sup>; the batch table later in the fixture (Opus 5 $2.50 / $12.50) is
    # never read
    assert prices["Claude Sonnet 5"].input == D(2) and prices["Claude Opus 5"].input == D(5)
    assert prices["Claude Fable 5.1"].cache_read == D("0.25") and prices["Claude Opus 5.5"].cache_read == D("0.2")
    assert all(p.long_input is None and p.long_output is None for p in prices.values())


def test_trailing_parentheses_with_markdown_links_are_removed_from_names():
    prices = _doc()
    assert prices["Claude Mythos 5.1"] == U(10, 50, cache_read="0.25", cache_write="12.5", cache_write_1h=20)
    assert prices["Claude Mythos 5"] == U(10, 50, cache_read=1, cache_write="12.5", cache_write_1h=20)
    # "([retired, except on Bedrock and Google Cloud](https://…))"
    assert prices["Claude Opus 4.1"] == U(15, 75, cache_read="1.5", cache_write="18.75", cache_write_1h=30)
    assert all("(" not in n and "[" not in n and "<" not in n for n in prices)


def _md(*rows, header="| Model | Base input tokens | Output tokens |"):
    sep = "| " + " | ".join("---" for _ in header.strip("|").split("|")) + " |"
    return "## Model pricing\n\n" + "\n".join((header, sep) + rows) + "\n"


def test_exact_names_keep_point_releases_apart():
    prices = parse_anthropic_pricing_md(_md(
        "| Claude Fable 5.1 | $12 / MTok | $60 / MTok |",
        "| Claude Mythos 5.1 ([limited availability](https://anthropic.com/glasswing)) | $99 / MTok | $99 / MTok |",
        "| Claude Fable 5 | $10 / MTok | $50 / MTok |",
        "| Claude Opus 5.5 | $4 / MTok | $20 / MTok |",
        "| Claude Opus 5 | $5 / MTok | $25 / MTok |",
    ))
    assert prices["Claude Opus 5"] == P(5, 25) and prices["Claude Opus 5.5"] == P(4, 20)
    assert prices["Claude Fable 5"] == P(10, 50) and prices["Claude Fable 5.1"] == P(12, 60)


def test_columns_by_header_name_bad_values_skipped_and_ambiguous_names_dropped():
    reordered = _md("| $25 / MTok | Claude Opus 5 | $6.25 / MTok | $5 / MTok |",
                    header="| Output tokens | Model | 5m cache writes | Base input tokens |")
    assert parse_anthropic_pricing_md(reordered) == {"Claude Opus 5": U(5, 25, cache_write="6.25")}
    assert parse_anthropic_pricing_md(_md(
        "| Claude Opus 5 | $5 per MTok | $25 / MTok |",
        "| Claude Sonnet 5 | $2/MTok | $10 / MTok |",
        "| Claude Opus 4.8 | $5 / MTok | $25 / MTok |",
        "| Claude Opus 4.8 (legacy) | $15 / MTok | $75 / MTok |",
        "| Claude Haiku 4.5 | $1 / MTok | $5 / MTok |",
    )) == {"Claude Haiku 4.5": P(1, 5)}


def test_cache_columns_are_found_by_header_name_and_bad_cache_cells_are_none():
    doc = _md("| Claude Opus 5 | $5 / MTok | $0.50 / MTok | TBD | $6.25 / MTok<sup>4</sup> | $25 / MTok |",
              header="| Model | Base input tokens | Cache Hits and Refreshes | 1h cache writes | 5m  cache writes | Output tokens |")
    assert parse_anthropic_pricing_md(doc) == {"Claude Opus 5": U(5, 25, cache_read="0.5", cache_write="6.25")}


def test_names_with_the_same_input_output_keep_them_and_lose_only_the_conflicting_cache_prices():
    doc = _md("| Claude Opus 5 | $5 / MTok | $0.50 / MTok | $6.25 / MTok | $25 / MTok |",
              "| Claude Opus 5 (legacy) | $5 / MTok | $1 / MTok | $6.25 / MTok | $25 / MTok |",
              "| Claude Sonnet 5 | $2 / MTok | $0.20 / MTok | $2.50 / MTok | $10 / MTok |",
              "| Claude Sonnet 5 (legacy) | $2 / MTok | $0.20 / MTok | TBD | $10 / MTok |",    # set vs None: None
              "| Claude Haiku 4.5 | $1 / MTok | $0.10 / MTok | $1.25 / MTok | $5 / MTok |",
              "| Claude Haiku 4.5 ([note](https://example.invalid)) | $1 / MTok | $0.10 / MTok | $1.25 / MTok | $5 / MTok |",
              header="| Model | Base input tokens | Cache hits and refreshes | 5m cache writes | Output tokens |")
    assert parse_anthropic_pricing_md(doc) == {
        "Claude Opus 5": U(5, 25, cache_write="6.25"),                      # cache hits differ: only that is None
        "Claude Sonnet 5": U(2, 10, cache_read="0.2"),                      # 5m write set once, missing once
        "Claude Haiku 4.5": U(1, 5, cache_read="0.1", cache_write="1.25"),  # equal twice: kept whole
    }


def test_names_with_a_different_input_or_output_are_still_dropped_whatever_the_cache_prices():
    doc = _md("| Claude Opus 5 | $5 / MTok | $0.50 / MTok | $25 / MTok |",
              "| Claude Opus 5 (legacy) | $15 / MTok | $0.50 / MTok | $25 / MTok |",   # input differs
              "| Claude Sonnet 5 | $2 / MTok | $0.20 / MTok | $10 / MTok |",
              "| Claude Sonnet 5 (legacy) | $2 / MTok | $0.20 / MTok | $12 / MTok |",   # output differs
              "| Claude Sonnet 5 (note) | $2 / MTok | $0.20 / MTok | $10 / MTok |",     # a third, matching row
              "| Claude Haiku 4.5 | $1 / MTok | $0.10 / MTok | $5 / MTok |",
              header="| Model | Base input tokens | Cache hits and refreshes | Output tokens |")
    assert parse_anthropic_pricing_md(doc) == {"Claude Haiku 4.5": U(1, 5, cache_read="0.1")}


def test_only_the_first_table_under_the_heading_is_read():
    second = _md("| Claude Opus 5 | $2.50 / MTok | $12.50 / MTok |", "| Claude Sonnet 5 | $1 / MTok | $5 / MTok |")
    doc = _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |") + "\n" + second.split("\n\n", 1)[1]  # no heading between
    assert parse_anthropic_pricing_md(doc) == {"Claude Opus 5": P(5, 25)}


def test_rows_with_the_wrong_cell_count_are_skipped():
    assert parse_anthropic_pricing_md(_md(
        "| Claude Opus 5 | $5 / MTok | $25 / MTok | $6.25 / MTok |",
        "| Claude Sonnet 5 | $2 / MTok |",
        "| Claude Haiku 4.5 | $1 / MTok | $5 / MTok |",
    )) == {"Claude Haiku 4.5": P(1, 5)}


def test_a_table_without_parseable_rows_raises():
    with pytest.raises(PriceParseError, match="no parseable rows"):
        parse_anthropic_pricing_md(_md("| Claude Opus 5 | $5 per MTok | $25 / MTok |", "| Claude Sonnet 5 | TBD | TBD |"))


@pytest.mark.parametrize("doc", [
    _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |").replace("## Model pricing", "## Pricing"),
    _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |", header="| Model | Input | Output |"),
    "## Model pricing\n\nNo table here.\n\n## Cloud platform pricing\n\n" + _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |").split("\n\n", 1)[1],
    "",
], ids=["no-heading", "renamed-headers", "table-in-next-section", "empty"])
def test_structure_changes_raise(doc):
    with pytest.raises(PriceParseError):
        parse_anthropic_pricing_md(doc)


def test_heading_error_messages_are_unchanged():
    with pytest.raises(PriceParseError, match=r"^'## Model pricing' heading not found$"):
        parse_anthropic_pricing_md("# Pricing\n")
    with pytest.raises(PriceParseError, match=r"^no pricing table under '## Model pricing'$"):
        parse_anthropic_pricing_md("## Model pricing\n\nNo table here.\n")


# ---------------------------------------------------------------- OpenAI pricing markdown

OPENAI_EXPECTED = {  # "### Standard pricing data" of the 2026-09-27 doc, the eight Bedrock GPT families + a mini model
    "gpt-6-astra": U(10, 50, cache_read=1, cache_write="12.5", long_input=20, long_output=75, long_cache_read=2,
                     long_cache_write=25),
    "gpt-6-sol": U(2, 10, cache_read="0.2", cache_write="2.5", long_input=4, long_output=15, long_cache_read="0.4",
                   long_cache_write=5),
    "gpt-6-luna": U("0.1", "0.5", cache_read="0.01", cache_write="0.125", long_input="0.2", long_output="0.75",
                    long_cache_read="0.02", long_cache_write="0.25"),
    "gpt-5.6-sol": U(4, 20, cache_read="0.4", cache_write=5, long_input=8, long_output=30, long_cache_read="0.8",
                     long_cache_write=10),
    "gpt-5.6-terra": U(2, 12, cache_read="0.2", cache_write="2.5", long_input=4, long_output=18, long_cache_read="0.4",
                       long_cache_write=5),
    "gpt-5.6-luna": U("0.2", "1.2", cache_read="0.02", cache_write="0.25", long_input="0.4", long_output="1.8",
                      long_cache_read="0.04", long_cache_write="0.5"),
    "gpt-5.5": U(5, 30, cache_read="0.5", long_input=10, long_output=45, long_cache_read=1),
    "gpt-5.4": U("2.5", 15, cache_read="0.25", long_input=5, long_output="22.5", long_cache_read="0.5"),
    "gpt-5.4-mini": U("0.75", "4.5", cache_read="0.075"),
}
OA_HEADER = ("| Model | Short context input | Short context cached input | Short context cache writes | "
             "Short context output | Long context input | Long context cached input | Long context cache writes | "
             "Long context output |")


def _openai_doc():
    return parse_openai_pricing_md((FIXTURES / "openai_pricing.md").read_text(encoding="utf-8"))


def _oa(*rows, header=OA_HEADER, heading="### Standard pricing data"):
    sep = "| " + " | ".join("---" for _ in header.strip("|").split("|")) + " |"
    return f"# Pricing\n\n{heading}\n\n" + "\n".join((header, sep) + rows) + "\n"


def test_real_openai_doc_gives_the_eight_bedrock_gpt_families():
    prices = _openai_doc()
    assert {name: prices[name] for name in OPENAI_EXPECTED} == OPENAI_EXPECTED
    assert prices["gpt-5.5"].cache_write is None and prices["gpt-5.5"].long_cache_write is None   # "-" cells
    mini = prices["gpt-5.4-mini"]
    assert (mini.cache_write, mini.long_input, mini.long_output, mini.long_cache_read, mini.long_cache_write) == (None,) * 5
    assert prices["gpt-6-luna"].cache_write == D("0.125")       # 3 decimals are kept


def test_openai_names_are_exact_and_lose_the_context_length_note():
    prices = _openai_doc()
    assert "gpt-5.5 (<272K context length)" not in prices and "gpt-5.5" in prices
    assert prices["gpt-5.4"] != prices["gpt-5.4-mini"] and prices["gpt-5.4"] != prices["gpt-5.4-pro"]
    assert prices["gpt-5.4-pro"] == U(30, 180, long_input=60, long_output=270)
    assert all("(" not in n and "<" not in n for n in prices)


def test_openai_batch_table_is_never_read():
    prices = _openai_doc()
    assert prices["gpt-6-astra"].input == D(10) and prices["gpt-6-astra"].output == D(50)   # Batch: $5.00 / $25.00
    assert prices["gpt-5.4"].cache_read == D("0.25")                                      # Batch: $0.13
    doc = (_oa("| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |")
           + "\nBedrock pricing in commercial regions matches OpenAI direct pricing.\n\n"
           + _oa("| gpt-6-sol | $1.00 | $0.10 | $1.25 | $5.00 | $2.00 | $0.20 | $2.50 | $7.50 |",
                 heading="### Batch pricing data").split("\n\n", 1)[1])
    assert parse_openai_pricing_md(doc) == {"gpt-6-sol": OPENAI_EXPECTED["gpt-6-sol"]}
    batch_only = _oa("| gpt-6-sol | $1.00 | $0.10 | $1.25 | $5.00 | $2.00 | $0.20 | $2.50 | $7.50 |",
                     heading="### Batch pricing data")
    with pytest.raises(PriceParseError, match=r"^'### Standard pricing data' heading not found$"):
        parse_openai_pricing_md(batch_only)


def test_openai_dash_blank_and_other_value_cells_are_none():
    prices = parse_openai_pricing_md(_oa(
        "| gpt-5.5 (<272K context length) | $5.00 | $0.50 | - | $30.00 | $10.00 |  | $1.00 / 1M | $45.00 |",
        "| gpt-5.4-nano | - | $0.02 | - | $1.25 | - | - | - | - |",          # no short-context input: skipped
        "| gpt-5.4 | $2.50 | 0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |",
    ))
    assert prices == {"gpt-5.5": U(5, 30, cache_read="0.5", long_input=10, long_output=45),
                      "gpt-5.4": U("2.5", 15, long_input=5, long_output="22.5", long_cache_read="0.5")}


def test_openai_columns_by_header_name_and_optional_columns():
    reordered = _oa("| $50.00 | gpt-6-astra | $10.00 | $1.00 |",
                    header="| Short context output | Model | Short context input | Short Context  Cached Input |")
    assert parse_openai_pricing_md(reordered) == {"gpt-6-astra": U(10, 50, cache_read=1)}
    with pytest.raises(PriceParseError, match="headers not recognised"):
        parse_openai_pricing_md(_oa("| gpt-6-astra | $10.00 | $50.00 |", header="| Model | Input | Output |"))


def test_openai_duplicate_names_with_a_different_input_or_output_are_dropped():
    prices = parse_openai_pricing_md(_oa(
        "| gpt-5.4 | $2.50 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |",
        "| gpt-5.4 (<272K context length) | $3.00 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |",
        "| gpt-5.5 | $5.00 | $0.50 | - | $30.00 | $10.00 | $1.00 | - | $45.00 |",
        "| gpt-5.5 (<272K context length) | $5.00 | $0.50 | - | $31.00 | $10.00 | $1.00 | - | $45.00 |",
        "| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |",
    ))
    assert prices == {"gpt-6-sol": OPENAI_EXPECTED["gpt-6-sol"]}


def test_openai_duplicate_names_with_the_same_input_output_lose_only_the_conflicting_values():
    prices = parse_openai_pricing_md(_oa(
        "| gpt-5.4 | $2.50 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |",
        "| gpt-5.4 (<272K context length) | $2.50 | $0.30 | - | $15.00 | $6.00 | $0.50 | $1.00 | $22.50 |",
        "| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |",
        "| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |",
    ))
    # cached input 0.25/0.30, long input 5/6 and long cache writes None/1.00 differ: None; the rest is kept
    assert prices == {"gpt-5.4": U("2.5", 15, long_output="22.5", long_cache_read="0.5"),
                      "gpt-6-sol": OPENAI_EXPECTED["gpt-6-sol"]}


@pytest.mark.parametrize("doc", [
    _oa("| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |", heading="## Standard pricing data"),
    _oa("| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |",
        heading="### Standard pricing data (Oct 2026)"),
    "### Standard pricing data\n\nPrices per 1M tokens.\n\n### Batch pricing data\n\n"
    + _oa("| gpt-6-sol | $1.00 | $0.10 | $1.25 | $5.00 | $2.00 | $0.20 | $2.50 | $7.50 |").split("\n\n", 2)[2],
    "### Standard pricing data\n\n| Model | Short context input | Short context output |\n| --- | --- | --- |\n",
    _oa("| gpt-6-sol | TBD | - | - | TBD | - | - | - | - |"),
    "",
], ids=["h2-heading", "renamed-heading", "table-in-next-section", "header-only", "no-parseable-rows", "empty"])
def test_openai_structure_changes_raise(doc):
    with pytest.raises(PriceParseError):
        parse_openai_pricing_md(doc)
