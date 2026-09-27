"""Shared golden dataset for the pricing payload and export tests (v2.30.0, extra price fields v2.31.0).

load() writes a small price_history/price_sync_runs set; EXPECTED_PAYLOAD is the exact build_pricing_payload
result for it with PRICE_NOTES pinned to the copy below. Offer ids other than the spec's examples are
fictional. Extra prices come from the 2026-09-27 official values (Contract C8) except the pending rows,
whose values are fictional. References list only cited sources (v2.31.1): no official pages.

Numbering on purpose: GPT 5.6 Sol has no openai_list channel here, so its OpenAI-doc note is what first cites
"openai-pricing" (number 4, right after the Sol cells); GPT 5.4's openai_list cell later reuses that number.
"""

from datetime import datetime, timedelta, timezone

import models
from pricing_parsers import EXTRA_FIELDS
from pricing_sources import EPOCH, price_identity

NOW = datetime(2026, 9, 25, 16, 0, tzinfo=timezone.utc)
RUN1 = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
RUN2 = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)

OPUS = "offer:offer-7sp77cpl4rveu"
NOVA = "pricelist:USE1-Nova2.0Lite-input-tokens"
SOL = "offer:offer-gnqokrqqvdbgw"
TERRA = "offer:offer-terra0example"
G55 = "offer:offer-gpt55example"
G54 = "offer:offer-5l5a5izq5fbec"
OPENAI_DOC = "openai-pricing"

ACTIVE_IDS = [
    "anthropic:claude-opus-5-5",
    "global.anthropic.claude-opus-5-5",
    "us.anthropic.claude-opus-5-5",
    "us.amazon.nova-2-lite-v1:0",
    "openai:global:global.openai.gpt-6-luna",
    "openai:global:global.openai.gpt-5.6-sol",
    "openai:us-east-1:openai.gpt-5.6-sol",
    "openai:global:global.openai.gpt-5.6-terra",
    "openai:us-east-1:openai.gpt-5.6-terra",
    "openai:us-east-2:openai.gpt-5.6-terra",
    "openai:us-west-2:openai.gpt-5.6-terra",
    "openai:us-east-1:openai.gpt-5.5",
    "openai-list:gpt-5.4",
    "openai:us-west-2:openai.gpt-5.4",
    "openai:us-east-1:openai.gpt-5.4",
    "openai:us-east-2:openai.gpt-5.4",
]

# The production note's shape (Contract C6): cites the OpenAI pricing doc, no basis fields.
SOL_NOTE = {
    "family_key": "gpt-5.6-sol", "kind": "promo", "min_until": "2026-11-21",
    "prior_price": {"openai_list": {"input": 5, "output": 30}, "global": {"input": 5, "output": 30},
                    "in_region": {"input": 5.5, "output": 33}},
    "text_ko": "프로모션 단가, 최소 2026-11-21까지",
    "text_en": "Promotional price, at least until 2026-11-21",
    "source": "openai_doc",
    "source_id": OPENAI_DOC,
}
SOL_NOTE_PAYLOAD = dict(SOL_NOTE)  # nothing to strip: an OpenAI-doc note has no basis fields

# A manual note (still supported): basis fields build its reference title, no source_id (the payload fills in
# note_source_id(family_key)).
MANUAL_NOTE = {
    "family_key": "gpt-5.6-sol", "kind": "promo", "min_until": "2026-11-21",
    "prior_price": {"in_region": {"input": 5.5, "output": 33}, "global": {"input": 5, "output": 30}},
    "text_ko": "프로모션 단가, 최소 2026-11-21까지",
    "text_en": "Promotional price, at least until 2026-11-21",
    "basis_ko": "2026-09-23 AWS 모델 카드 기준",
    "basis_en": "2026-09-23 AWS model card",
    "source": "manual_note",
}

# Extra prices by channel (keys = pricing_parsers.EXTRA_FIELDS)
OPUS_GLOBAL_EXTRA = {"cache_read": 0.2, "cache_write": 5.0, "cache_write_1h": 8.0}
OPUS_US_EXTRA = {"cache_read": 0.22, "cache_write": 5.5, "cache_write_1h": 8.8}
NOVA_EXTRA = {"cache_read": 0.0825, "cache_write": 0.0}
SOL_GLOBAL_EXTRA = {"cache_read": 0.4, "cache_write": 5.0, "long_input": 8.0, "long_output": 30.0,
                    "long_cache_read": 0.8, "long_cache_write": 10.0}
SOL_STANDARD_EXTRA = {"cache_read": 0.44, "cache_write": 5.5, "long_input": 8.8, "long_output": 33.0,
                      "long_cache_read": 0.88, "long_cache_write": 11.0}
TERRA_GLOBAL_EXTRA = {"cache_read": 0.2, "cache_write": 2.5, "long_input": 4.0, "long_output": 18.0,
                      "long_cache_read": 0.4, "long_cache_write": 5.0}
TERRA_STANDARD_EXTRA = {"cache_read": 0.22, "cache_write": 2.75, "long_input": 4.4, "long_output": 19.8,
                        "long_cache_read": 0.44, "long_cache_write": 5.5}
G55_STANDARD_EXTRA = {"cache_read": 0.55, "long_input": 11.0, "long_output": 49.5, "long_cache_read": 1.1}
G54_STANDARD_EXTRA = {"cache_read": 0.275, "long_input": 5.5, "long_output": 24.75, "long_cache_read": 0.55}
G54_OPENAI_LIST_EXTRA = {"cache_read": 0.25, "long_input": 5.0, "long_output": 22.5, "long_cache_read": 0.5}
SOL_PENDING_EXTRA = {"cache_read": 0.9, "long_input": 18.0, "long_output": 67.5}  # fictional


def active():
    return {mid: price_identity(mid) for mid in ACTIVE_IDS}


def add_price(db, model_id, inp, out, *, effective_from=EPOCH, status="seed", observed_at=None, source_id,
              **extra):
    """One price_history row; `extra` takes EXTRA_FIELDS names (cache_read=0.2, long_input=4, …)."""
    unknown = set(extra) - set(EXTRA_FIELDS)
    if unknown:
        raise TypeError(f"unknown price fields: {sorted(unknown)}")
    ident = price_identity(model_id)
    row = models.PriceHistory(
        model_id=model_id, family_key=ident.family_key if ident else "unknown",
        channel=ident.channel if ident else "global", input_per_mtok=inp, output_per_mtok=out,
        effective_from=effective_from, source_id=source_id, status=status, observed_at=observed_at,
        **{f"{field}_per_mtok": value for field, value in extra.items()},
    )
    db.add(row)
    db.flush()
    return row


def load(db):
    """Runs 1 and 2 finished; run 3 is still running and must be ignored. GPT 6 Luna has no price rows."""
    db.add(models.PriceSyncRun(id=1, started_at=RUN1, finished_at=RUN1 + timedelta(seconds=31), status="completed"))
    db.add(models.PriceSyncRun(id=2, started_at=RUN2, finished_at=RUN2 + timedelta(seconds=31), status="completed"))
    db.add(models.PriceSyncRun(id=3, started_at=NOW, finished_at=None, status="running"))
    add_price(db, "anthropic:claude-opus-5-5", 4.0, 20.0, observed_at=RUN2, source_id="anthropic-pricing",
              **OPUS_GLOBAL_EXTRA)
    add_price(db, "global.anthropic.claude-opus-5-5", 4.0, 20.0, observed_at=RUN2, source_id=OPUS,
              **OPUS_GLOBAL_EXTRA)
    add_price(db, "us.anthropic.claude-opus-5-5", 4.4, 22.0, observed_at=RUN2, source_id=OPUS, **OPUS_US_EXTRA)
    # Price List failed in run 2: Nova was last confirmed in run 1 -> stale. Its cache write is officially $0.
    add_price(db, "us.amazon.nova-2-lite-v1:0", 0.33, 2.75, observed_at=RUN1, source_id=NOVA, **NOVA_EXTRA)
    add_price(db, "openai:global:global.openai.gpt-5.6-sol", 4.0, 20.0, observed_at=RUN2, source_id=SOL,
              **SOL_GLOBAL_EXTRA)
    add_price(db, "openai:global:global.openai.gpt-5.6-sol", 9.0, 45.0, effective_from=RUN2,
              status="pending_review", observed_at=RUN2, source_id=SOL, **SOL_PENDING_EXTRA)
    add_price(db, "openai:us-east-1:openai.gpt-5.6-sol", 4.4, 22.0, source_id=SOL,
              **SOL_STANDARD_EXTRA)  # seed never confirmed
    add_price(db, "openai:global:global.openai.gpt-5.6-terra", 2.0, 12.0, observed_at=RUN2, source_id=TERRA,
              **TERRA_GLOBAL_EXTRA)
    add_price(db, "openai:us-east-1:openai.gpt-5.6-terra", 2.2, 13.2, observed_at=RUN2, source_id=TERRA,
              **TERRA_STANDARD_EXTRA)
    add_price(db, "openai:us-east-2:openai.gpt-5.6-terra", 2.2, 13.2, observed_at=RUN2, source_id=TERRA,
              **TERRA_STANDARD_EXTRA)
    add_price(db, "openai:us-west-2:openai.gpt-5.6-terra", 2.2, 13.2, observed_at=RUN1, source_id=TERRA,
              **TERRA_STANDARD_EXTRA)
    # A later verified row without extra prices: that cell shows cache_* and long as null.
    add_price(db, "openai:us-west-2:openai.gpt-5.6-terra", 2.4, 14.4, effective_from=RUN2, status="verified",
              observed_at=RUN2, source_id=TERRA)
    add_price(db, "openai:us-east-1:openai.gpt-5.5", 5.5, 33.0, source_id=G55, **G55_STANDARD_EXTRA)
    for region in ("us-west-2", "us-east-2", "us-east-1"):
        add_price(db, f"openai:{region}:openai.gpt-5.4", 2.75, 16.5, observed_at=RUN2, source_id=G54,
                  **G54_STANDARD_EXTRA)
    # OpenAI official price (display-only openai_list channel): in the table, never in the cost map.
    add_price(db, "openai-list:gpt-5.4", 2.5, 15.0, observed_at=RUN2, source_id=OPENAI_DOC, **G54_OPENAI_LIST_EXTRA)
    # Not in the active set: never shown.
    add_price(db, "us.anthropic.claude-opus-4-6-v1", 5.5, 27.5, observed_at=RUN2, source_id="offer:offer-hidden")
    add_price(db, "openai:us-east-2:openai.gpt-5.5", 5.5, 33.0, effective_from=RUN2, status="pending_review",
              observed_at=RUN2, source_id=G55)
    # An older pending value for the same Sol Global channel: the cell still shows the newer one (id 6), and
    # pending_review counts the channel once.
    add_price(db, "openai:global:global.openai.gpt-5.6-sol", 8.0, 40.0, effective_from=RUN1,
              status="pending_review", observed_at=RUN1, source_id=SOL)
    db.commit()


# ----------------------------------------------------------------- golden /api/pricing body for load()

OFFER_URL = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html"
PRICE_LIST_URL = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html"
ANTHROPIC_URL = "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing"
OPENAI_URL = "https://developers.openai.com/api/docs/pricing"
R1 = "2026-09-24T15:00:00Z"
R2 = "2026-09-25T15:00:00Z"


def _long(inp, out, cache_read=None, cache_write=None):
    return {"input": inp, "output": out, "cache_read": cache_read, "cache_write": cache_write}


def _prices(inp, out, cache_read=None, cache_write=None, cache_write_1h=None, long=None):
    return {"input": inp, "output": out, "cache_read": cache_read, "cache_write": cache_write,
            "cache_write_1h": cache_write_1h, "long": long}


def _cell(prices, model_ids, source_ids, footnotes, verification, observed_at, pending=None, regions=None):
    cell = {"regions": regions} if regions is not None else {}
    cell.update(prices)
    cell.update({
        "model_ids": model_ids, "source_ids": source_ids, "footnotes": footnotes,
        "verification": verification, "observed_at": observed_at, "pending": pending,
    })
    return cell


def _family(family_key, family, provider, cp=None, openai_list=None, global_=None, us=None, in_region=(), notes=()):
    return {"family_key": family_key, "family": family, "provider": provider,
            "tiers": {"cp": cp, "openai_list": openai_list, "global": global_, "us": us,
                      "in_region": list(in_region)},
            "notes": list(notes)}


def _ref(n, rid, kind, title_en, title_ko, url, as_of):
    return {"n": n, "id": rid, "kind": kind, "title_en": title_en, "title_ko": title_ko, "url": url, "as_of": as_of}


OPUS_GLOBAL_PRICES = _prices(4, 20, 0.2, 5, 8)
TERRA_STANDARD_PRICES = _prices(2.2, 13.2, 0.22, 2.75, long=_long(4.4, 19.8, 0.44, 5.5))
G54_STANDARD_PRICES = _prices(2.75, 16.5, 0.275, long=_long(5.5, 24.75, 0.55))

EXPECTED_PAYLOAD = {
    "currency": "USD",
    "unit": "per_1m_tokens",
    "generated_at": "2026-09-25T16:00:00Z",
    "last_sync": {"id": 2, "started_at": R2, "finished_at": "2026-09-25T15:00:31Z", "status": "completed"},
    "pending_review": 1,  # distinct channels: Sol Global has two pending rows, gpt-5.5 us-east-2 is not active
    "families": [
        _family("claude-opus-5-5", "Claude Opus 5.5", "anthropic",
                cp=_cell(OPUS_GLOBAL_PRICES, ["anthropic:claude-opus-5-5"], ["anthropic-pricing"], [1],
                         "verified", R2),
                global_=_cell(OPUS_GLOBAL_PRICES, ["global.anthropic.claude-opus-5-5"], [OPUS], [2], "verified", R2),
                us=_cell(_prices(4.4, 22, 0.22, 5.5, 8.8), ["us.anthropic.claude-opus-5-5"], [OPUS], [2],
                         "verified", R2)),
        _family("gpt-6-luna", "GPT 6 Luna", "openai"),
        _family("gpt-5.6-sol", "GPT 5.6 Sol", "openai",
                global_=_cell(_prices(4, 20, 0.4, 5, long=_long(8, 30, 0.8, 10)),
                              ["openai:global:global.openai.gpt-5.6-sol"], [SOL], [3], "verified", R2,
                              pending={"id": 6, **_prices(9, 45, 0.9, long=_long(18, 67.5)), "observed_at": R2}),
                in_region=[_cell(_prices(4.4, 22, 0.44, 5.5, long=_long(8.8, 33, 0.88, 11)),
                                 ["openai:us-east-1:openai.gpt-5.6-sol"], [SOL], [3], "seed_only", None,
                                 regions=["us-east-1"])],
                notes=[SOL_NOTE_PAYLOAD]),
        _family("gpt-5.6-terra", "GPT 5.6 Terra", "openai",
                global_=_cell(_prices(2, 12, 0.2, 2.5, long=_long(4, 18, 0.4, 5)),
                              ["openai:global:global.openai.gpt-5.6-terra"], [TERRA], [5], "verified", R2),
                in_region=[
                    _cell(TERRA_STANDARD_PRICES,
                          ["openai:us-east-1:openai.gpt-5.6-terra", "openai:us-east-2:openai.gpt-5.6-terra"],
                          [TERRA], [5], "verified", R2, regions=["us-east-1", "us-east-2"]),
                    _cell(_prices(2.4, 14.4), ["openai:us-west-2:openai.gpt-5.6-terra"], [TERRA], [5], "verified",
                          R2, regions=["us-west-2"]),
                ]),
        _family("gpt-5.5", "GPT 5.5", "openai",
                in_region=[_cell(_prices(5.5, 33, 0.55, long=_long(11, 49.5, 1.1)),
                                 ["openai:us-east-1:openai.gpt-5.5"], [G55], [6], "seed_only", None,
                                 regions=["us-east-1"])]),
        _family("gpt-5.4", "GPT 5.4", "openai",
                openai_list=_cell(_prices(2.5, 15, 0.25, long=_long(5, 22.5, 0.5)), ["openai-list:gpt-5.4"],
                                  [OPENAI_DOC], [4], "verified", R2),
                in_region=[_cell(G54_STANDARD_PRICES,
                                 ["openai:us-east-1:openai.gpt-5.4", "openai:us-east-2:openai.gpt-5.4",
                                  "openai:us-west-2:openai.gpt-5.4"],
                                 [G54], [7], "verified", R2, regions=["us-east-1", "us-east-2", "us-west-2"])]),
        _family("nova-2-lite", "Nova 2.0 Lite", "amazon",
                us=_cell(_prices(0.33, 2.75, 0.0825, 0), ["us.amazon.nova-2-lite-v1:0"], [NOVA], [8], "stale", R1)),
    ],
    # openai-list:gpt-5.4 has a current row but is display-only: never in the cost map
    "models": {
        "anthropic:claude-opus-5-5": {"input": 4, "output": 20, "verification": "verified"},
        "global.anthropic.claude-opus-5-5": {"input": 4, "output": 20, "verification": "verified"},
        "openai:global:global.openai.gpt-5.6-sol": {"input": 4, "output": 20, "verification": "verified"},
        "openai:global:global.openai.gpt-5.6-terra": {"input": 2, "output": 12, "verification": "verified"},
        "openai:us-east-1:openai.gpt-5.4": {"input": 2.75, "output": 16.5, "verification": "verified"},
        "openai:us-east-1:openai.gpt-5.5": {"input": 5.5, "output": 33, "verification": "seed_only"},
        "openai:us-east-1:openai.gpt-5.6-sol": {"input": 4.4, "output": 22, "verification": "seed_only"},
        "openai:us-east-1:openai.gpt-5.6-terra": {"input": 2.2, "output": 13.2, "verification": "verified"},
        "openai:us-east-2:openai.gpt-5.4": {"input": 2.75, "output": 16.5, "verification": "verified"},
        "openai:us-east-2:openai.gpt-5.6-terra": {"input": 2.2, "output": 13.2, "verification": "verified"},
        "openai:us-west-2:openai.gpt-5.4": {"input": 2.75, "output": 16.5, "verification": "verified"},
        "openai:us-west-2:openai.gpt-5.6-terra": {"input": 2.4, "output": 14.4, "verification": "verified"},
        "us.amazon.nova-2-lite-v1:0": {"input": 0.33, "output": 2.75, "verification": "stale"},
        "us.anthropic.claude-opus-5-5": {"input": 4.4, "output": 22, "verification": "verified"},
    },
    "references": [
        _ref(1, "anthropic-pricing", "anthropic_doc",
             "Anthropic API pricing (Claude Platform on AWS uses standard pricing)",
             "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)", ANTHROPIC_URL, "2026-09-25"),
        _ref(2, OPUS, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-7sp77cpl4rveu (Claude Opus 5.5)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5)", OFFER_URL, "2026-09-25"),
        _ref(3, SOL, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-gnqokrqqvdbgw (GPT 5.6 Sol)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol)", OFFER_URL, "2026-09-25"),
        # first cited by the GPT 5.6 Sol note, right after the Sol cells; as_of from the openai-list:gpt-5.4 row
        _ref(4, OPENAI_DOC, "openai_doc", "OpenAI API pricing (Standard)", "OpenAI API 요금 (Standard)", OPENAI_URL,
             "2026-09-25"),
        _ref(5, TERRA, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-terra0example (GPT 5.6 Terra)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra)", OFFER_URL, "2026-09-25"),
        # only seed rows (observed_at NULL) cite it -> the seed check date (pricing_seed.SEED_SOURCE_DATE)
        _ref(6, G55, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-gpt55example (GPT 5.5)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5)", OFFER_URL, "2026-09-27"),
        _ref(7, G54, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-5l5a5izq5fbec (GPT 5.4)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4)", OFFER_URL, "2026-09-25"),
        _ref(8, NOVA, "price_list",
             "AWS Price List API, AmazonBedrock usage type USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",
             "AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",
             PRICE_LIST_URL, "2026-09-24"),
    ],
    "disclaimer": {
        "en": "This price list is compiled automatically from public sources for reference only and is not an "
              "official AWS statement. Always confirm final prices on the official pricing pages.",
        "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
              "최종 가격은 반드시 공식 사이트에서 확인하세요.",
    },
}
