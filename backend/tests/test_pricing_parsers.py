"""Official price source parsers (v2.30.0, ADR-030) — offline, sanitized spike fixtures (tests/fixtures/pricing/)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pricing_parsers import (
    DIMENSION_RE, PriceParseError, UnitPrice, parse_anthropic_pricing_md, parse_pricelist,
    select_offer_price, single_public_offer,
)
from pricing_sources import ANTHROPIC_DOC_NAMES, NOVA_USAGETYPES

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _card(name):
    return single_public_offer(_load(name))[1]


def P(i, o):
    return UnitPrice(input=Decimal(str(i)), output=Decimal(str(o)))


def E(dimension, price, unit="Units"):
    return {"dimension": dimension, "price": price, "description": dimension, "unit": unit}


def test_fixtures_are_sanitized():
    names = {f.name for f in FIXTURES.iterdir()}
    assert names >= {"offers_claude-opus-5-5.json", "offers_claude-sonnet-4-6.json", "offers_claude-haiku-4-5.json",
                     "offers_gpt-6-astra.json", "offers_gpt-5.4.json", "pricelist_nova-2-lite.json", "anthropic_pricing.md"}
    for f in FIXTURES.iterdir():
        text = f.read_text(encoding="utf-8")
        for forbidden in ("offerToken", "legalTerm", "X-Amz", "Security-Token", "awsmp-offer-legal"):
            assert forbidden not in text, f"{f.name} contains {forbidden}"


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


@pytest.mark.parametrize(("fixture", "channel", "expected"), [
    ("offers_claude-opus-5-5.json", "global", P(4, 20)),          # region-prefix scheme
    ("offers_claude-opus-5-5.json", "us", P("4.4", 22)),
    ("offers_claude-sonnet-4-6.json", "global", P(3, 15)),        # legacy TokenCount scheme
    ("offers_claude-sonnet-4-6.json", "us", P("3.3", "16.5")),
    ("offers_claude-haiku-4-5.json", "global", P(1, 5)),          # both schemes, same values
    ("offers_claude-haiku-4-5.json", "us", P("1.1", "5.5")),
    ("offers_gpt-6-astra.json", "us", P(11, 55)),                 # flat scheme; unit anchor = AWS model card
    ("offers_gpt-6-astra.json", "global", P(10, 50)),
    ("offers_gpt-6-astra.json", "inregion:us-west-2", P(11, 55)),
    ("offers_gpt-5.4.json", "inregion:us-east-1", P("2.75", "16.5")),
    ("offers_gpt-5.4.json", "inregion:us-east-2", P("2.75", "16.5")),
    ("offers_gpt-5.4.json", "inregion:us-west-2", P("2.75", "16.5")),
])
def test_select_offer_price_from_real_rate_cards(fixture, channel, expected):
    assert select_offer_price(_card(fixture), channel) == expected


@pytest.mark.parametrize("channel", ["cp", "inregion:eu-west-1", "inregion:", "bogus"])
def test_channels_without_an_offer_rule_get_none(channel):
    assert select_offer_price(_card("offers_gpt-6-astra.json"), channel) is None


@pytest.mark.parametrize("dimension", [
    "input_tokens_standard", "output_tokens_global_standard", "APN2_input_tokens_global_standard",
    "USE2_input_tokens_standard", "USW2_output_tokens_standard", "USE1_InputTokenCount", "APN2_OutputTokenCount_Global",
])
def test_dimension_allow_list_accepts(dimension):
    assert DIMENSION_RE.fullmatch(dimension)


@pytest.mark.parametrize("dimension", [
    "UGE1_input_tokens_standard", "UGW1_InputTokenCount", "EU_input_tokens_standard", "USE1_input_tokens_batch",
    "input_tokens_priority", "input_tokens_global_flex", "USE1_input_tokens_long_ctx_standard",
    "USE1_InputTokenCount_LCtx", "APN2_InputTokenCount_Global_Batch", "USE1_cache_read_tokens_standard",
    "APN2_Reserved_1Month_InputTPM_Global", "use1_input_tokens_standard",
])
def test_dimension_allow_list_rejects(dimension):
    assert DIMENSION_RE.fullmatch(dimension) is None


def test_govcloud_and_eu_entries_of_a_real_card_are_never_candidates():
    excluded = [e for e in _card("offers_claude-opus-5-5.json") if e["dimension"].startswith(("UGE1_", "EU_"))]
    assert {"UGE1_input_tokens_standard", "EU_input_tokens_standard"} <= {e["dimension"] for e in excluded}
    assert all(select_offer_price(excluded, ch) is None for ch in ("global", "us", "inregion:us-east-1"))


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
    assert parse_pricelist(items, in_ut, out_ut) == P("0.33", "2.75")
    assert parse_pricelist([json.loads(s) for s in items], in_ut, out_ut) == P("0.33", "2.75")


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


# ---------------------------------------------------------------- Anthropic pricing markdown

CP_EXPECTED = {
    "Claude Fable 5.1": P(10, 50), "Claude Fable 5": P(10, 50), "Claude Opus 5.5": P(4, 20),
    "Claude Opus 5": P(5, 25), "Claude Opus 4.8": P(5, 25), "Claude Opus 4.7": P(5, 25),
    "Claude Sonnet 5": P(2, 10), "Claude Sonnet 4.6": P(3, 15), "Claude Haiku 4.5": P(1, 5),
}


def _doc():
    return parse_anthropic_pricing_md((FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8"))


def test_real_doc_gives_all_nine_claude_platform_on_aws_families():
    prices = _doc()
    assert sorted(ANTHROPIC_DOC_NAMES.values()) == sorted(CP_EXPECTED)
    assert {name: prices[name] for name in CP_EXPECTED} == CP_EXPECTED
    # Sonnet 5 value cells are "$2 / MTok<sup>3</sup>" / "$10 / MTok<sup>3</sup>"; the batch table later
    # in the fixture (Opus 5 $2.50 / $12.50) is never read
    assert prices["Claude Sonnet 5"] == P(2, 10) and prices["Claude Opus 5"] == P(5, 25)


def test_trailing_parentheses_with_markdown_links_are_removed_from_names():
    prices = _doc()
    assert prices["Claude Mythos 5.1"] == P(10, 50) and prices["Claude Mythos 5"] == P(10, 50)
    assert prices["Claude Opus 4.1"] == P(15, 75)   # "([retired, except on Bedrock and Google Cloud](https://…))"
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
    assert parse_anthropic_pricing_md(reordered) == {"Claude Opus 5": P(5, 25)}
    assert parse_anthropic_pricing_md(_md(
        "| Claude Opus 5 | $5 per MTok | $25 / MTok |",
        "| Claude Sonnet 5 | $2/MTok | $10 / MTok |",
        "| Claude Opus 4.8 | $5 / MTok | $25 / MTok |",
        "| Claude Opus 4.8 (legacy) | $15 / MTok | $75 / MTok |",
        "| Claude Haiku 4.5 | $1 / MTok | $5 / MTok |",
    )) == {"Claude Haiku 4.5": P(1, 5)}


@pytest.mark.parametrize("doc", [
    _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |").replace("## Model pricing", "## Pricing"),
    _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |", header="| Model | Input | Output |"),
    "## Model pricing\n\nNo table here.\n\n## Cloud platform pricing\n\n" + _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |").split("\n\n", 1)[1],
    "",
], ids=["no-heading", "renamed-headers", "table-in-next-section", "empty"])
def test_structure_changes_raise(doc):
    with pytest.raises(PriceParseError):
        parse_anthropic_pricing_md(doc)
