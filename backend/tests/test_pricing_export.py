"""pricing_export — golden CSV, Markdown and JSON for the golden payload (v2.30.0, extra price fields v2.31.0).

The exports are pure functions of the /api/pricing payload: same order, same footnote numbers, disclaimer
first (and last in Markdown). tests/_pricing_dataset.EXPECTED_PAYLOAD is the input; its correctness against
the database is pinned by test_pricing_payload.py. Markdown tables are per provider (Anthropic Claude, OpenAI,
Amazon Nova) with that provider's columns; a cell's second line is prompt caching, the third long context.
"""

import copy
import csv
import io
import json
from datetime import date

import pytest

from pricing_export import (
    BOM, CSV_HEADER, PROVIDER_COLUMNS, TIER_KEYS, TIER_TITLES, export_filename, to_csv, to_json, to_markdown,
)
from tests._pricing_dataset import EXPECTED_PAYLOAD

GOLDEN_MD_KO = """> 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.

# 비용 단가

- 통화와 단위: USD, 1M 토큰당, 입력 / 출력. 둘째 줄은 프롬프트 캐싱, GPT 셋째 줄은 긴 컨텍스트 단가다
- 생성 시각: 2026-09-25T16:00:00Z
- 마지막 자동 확인: 2026-09-25T15:00:31Z (completed)
- 검토 대기: 1

## Anthropic Claude

| 모델 | Claude Platform on AWS | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20[^1]<br>캐시 읽기 0.2, 쓰기 5, 1시간 쓰기 8 | 4 / 20[^2]<br>캐시 읽기 0.2, 쓰기 5, 1시간 쓰기 8 | 4.4 / 22[^2]<br>캐시 읽기 0.22, 쓰기 5.5, 1시간 쓰기 8.8 | — |

## OpenAI

| 모델 | OpenAI 공식 가격 | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region |
|---|---|---|---|---|
| GPT 6 Luna | — | — | — | — |
| GPT 5.6 Sol | — | 4 / 20 (검토 대기 9 / 45, 캐시 읽기 0.9, 긴 컨텍스트 18 / 67.5)[^3]<br>캐시 읽기 0.4, 쓰기 5<br>긴 컨텍스트 8 / 30, 캐시 읽기 0.8, 쓰기 10 | — | 4.4 / 22 us-east-1 (자동 확인 안 됨)[^3]<br>캐시 읽기 0.44, 쓰기 5.5<br>긴 컨텍스트 8.8 / 33, 캐시 읽기 0.88, 쓰기 11 |
| GPT 5.6 Terra | — | 2 / 12[^5]<br>캐시 읽기 0.2, 쓰기 2.5<br>긴 컨텍스트 4 / 18, 캐시 읽기 0.4, 쓰기 5 | — | 2.2 / 13.2 us-east-1, us-east-2[^5]<br>캐시 읽기 0.22, 쓰기 2.75<br>긴 컨텍스트 4.4 / 19.8, 캐시 읽기 0.44, 쓰기 5.5<br><br>2.4 / 14.4 us-west-2[^5] |
| GPT 5.5 | — | — | — | 5.5 / 33 us-east-1 (자동 확인 안 됨)[^6]<br>캐시 읽기 0.55<br>긴 컨텍스트 11 / 49.5, 캐시 읽기 1.1 |
| GPT 5.4 | 2.5 / 15[^4]<br>캐시 읽기 0.25<br>긴 컨텍스트 5 / 22.5, 캐시 읽기 0.5 | — | — | 2.75 / 16.5 us-east-1, us-east-2, us-west-2[^7]<br>캐시 읽기 0.275<br>긴 컨텍스트 5.5 / 24.75, 캐시 읽기 0.55 |

## Amazon Nova

| 모델 | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region |
|---|---|---|---|
| Nova 2.0 Lite | — | 0.33 / 2.75 (자동 확인 안 됨)[^8]<br>캐시 읽기 0.0825, 쓰기 0 | — |

## 참고 사항

1. 단가는 USD, 1M 토큰당, Standard 등급 기준이다.
2. AWS Bedrock - Global CRIS 단가는 같은 모델의 US CRIS, In Region 단가와 다를 수 있다.
3. 캐시 쓰기는 Claude의 5분 캐시, OpenAI 공식 문서의 cache writes, Nova의 캐시 쓰기 단가이고, 1시간 쓰기는 Claude의 1시간 캐시 단가다.
4. GPT의 긴 컨텍스트 요금은 OpenAI가 정한 짧은 컨텍스트 한도(GPT 5.4, 5.5는 272K)를 넘는 요청에 적용된다.
5. OpenAI 공식 가격은 OpenAI 직접 API 단가이며 비용 계산에 쓰지 않는다.
6. 캐시와 긴 컨텍스트 단가는 표시만 하며, 비용 화면은 입력과 출력 단가로 계산한다.
7. batch, flex, priority(fast) 단가는 포함하지 않는다.
8. 비용 화면은 각 프로브 시각의 단가로 계산한다.
9. 최종 가격은 공식 요금 페이지에서 확인한다[^9][^10].
10. GPT 5.6 Sol: 프로모션 단가, 최소 2026-11-21까지[^4]

## 참고 자료

[^1]: Anthropic API 요금 (Claude Platform on AWS는 표준 요금), https://platform.claude.com/docs/en/about-claude/pricing#model-pricing, 확인일 2026-09-25
[^2]: Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^3]: Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^4]: OpenAI API 요금 (Standard), https://developers.openai.com/api/docs/pricing, 확인일 2026-09-25
[^5]: Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^6]: Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-27
[^7]: Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^8]: AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite), https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html, 확인일 2026-09-24
[^9]: Amazon Bedrock 요금, https://aws.amazon.com/bedrock/pricing/
[^10]: Amazon Bedrock 모델 카드, OpenAI GPT 5.4, https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html

> 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.
"""

GOLDEN_MD_EN = """> This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.

# Unit prices

- Currency and unit: USD per 1M tokens, input / output. The second line is prompt caching, and the third line on GPT rows is long context
- Generated: 2026-09-25T16:00:00Z
- Last automatic check: 2026-09-25T15:00:31Z (completed)
- Pending review: 1

## Anthropic Claude

| Model | Claude Platform on AWS | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20[^1]<br>cache read 0.2, write 5, 1h write 8 | 4 / 20[^2]<br>cache read 0.2, write 5, 1h write 8 | 4.4 / 22[^2]<br>cache read 0.22, write 5.5, 1h write 8.8 | — |

## OpenAI

| Model | OpenAI official price | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region |
|---|---|---|---|---|
| GPT 6 Luna | — | — | — | — |
| GPT 5.6 Sol | — | 4 / 20 (Pending review 9 / 45, cache read 0.9, long context 18 / 67.5)[^3]<br>cache read 0.4, write 5<br>long context 8 / 30, cache read 0.8, write 10 | — | 4.4 / 22 us-east-1 (not verified automatically)[^3]<br>cache read 0.44, write 5.5<br>long context 8.8 / 33, cache read 0.88, write 11 |
| GPT 5.6 Terra | — | 2 / 12[^5]<br>cache read 0.2, write 2.5<br>long context 4 / 18, cache read 0.4, write 5 | — | 2.2 / 13.2 us-east-1, us-east-2[^5]<br>cache read 0.22, write 2.75<br>long context 4.4 / 19.8, cache read 0.44, write 5.5<br><br>2.4 / 14.4 us-west-2[^5] |
| GPT 5.5 | — | — | — | 5.5 / 33 us-east-1 (not verified automatically)[^6]<br>cache read 0.55<br>long context 11 / 49.5, cache read 1.1 |
| GPT 5.4 | 2.5 / 15[^4]<br>cache read 0.25<br>long context 5 / 22.5, cache read 0.5 | — | — | 2.75 / 16.5 us-east-1, us-east-2, us-west-2[^7]<br>cache read 0.275<br>long context 5.5 / 24.75, cache read 0.55 |

## Amazon Nova

| Model | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region |
|---|---|---|---|
| Nova 2.0 Lite | — | 0.33 / 2.75 (not verified automatically)[^8]<br>cache read 0.0825, write 0 | — |

## Notes

1. Prices are in USD per 1M tokens, Standard tier.
2. AWS Bedrock - Global CRIS prices can differ from the same model's US CRIS and In Region prices.
3. Cache write is the Claude 5-minute cache price, OpenAI's cache writes price and the Nova cache write price, and 1h write is the Claude 1-hour cache price.
4. GPT long-context prices apply to requests above OpenAI's short-context limit (272K for GPT 5.4 and 5.5).
5. The OpenAI official price is OpenAI's direct API price and is not used for cost calculations.
6. Cache and long-context prices are shown for reference, and the cost pages use input and output prices.
7. Batch, flex and priority (fast) prices are not included.
8. The cost pages use the price in effect at each probe's time.
9. Confirm final prices on the official pricing pages[^9][^10].
10. GPT 5.6 Sol: Promotional price, at least until 2026-11-21[^4]

## References

[^1]: Anthropic API pricing (Claude Platform on AWS uses standard pricing), https://platform.claude.com/docs/en/about-claude/pricing#model-pricing, checked 2026-09-25
[^2]: Amazon Bedrock agreement offer rate card, offer-7sp77cpl4rveu (Claude Opus 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^3]: Amazon Bedrock agreement offer rate card, offer-gnqokrqqvdbgw (GPT 5.6 Sol), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^4]: OpenAI API pricing (Standard), https://developers.openai.com/api/docs/pricing, checked 2026-09-25
[^5]: Amazon Bedrock agreement offer rate card, offer-terra0example (GPT 5.6 Terra), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^6]: Amazon Bedrock agreement offer rate card, offer-gpt55example (GPT 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-27
[^7]: Amazon Bedrock agreement offer rate card, offer-5l5a5izq5fbec (GPT 5.4), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^8]: AWS Price List API, AmazonBedrock usage type USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite), https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html, checked 2026-09-24
[^9]: Amazon Bedrock pricing, https://aws.amazon.com/bedrock/pricing/
[^10]: Amazon Bedrock model card, OpenAI GPT 5.4, https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html

> This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.
"""

GOLDEN_CSV_KO = BOM + """"# 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요."
provider,family,channel,regions,model_ids,input_usd_per_1m,output_usd_per_1m,cache_read_usd_per_1m,cache_write_usd_per_1m,cache_write_1h_usd_per_1m,long_input_usd_per_1m,long_output_usd_per_1m,long_cache_read_usd_per_1m,long_cache_write_usd_per_1m,verification,observed_at,footnotes,source_ids
anthropic,Claude Opus 5.5,cp,,anthropic:claude-opus-5-5,4,20,0.2,5,8,,,,,verified,2026-09-25T15:00:00Z,1,anthropic-pricing
anthropic,Claude Opus 5.5,global,,global.anthropic.claude-opus-5-5,4,20,0.2,5,8,,,,,verified,2026-09-25T15:00:00Z,2,offer:offer-7sp77cpl4rveu
anthropic,Claude Opus 5.5,us,,us.anthropic.claude-opus-5-5,4.4,22,0.22,5.5,8.8,,,,,verified,2026-09-25T15:00:00Z,2,offer:offer-7sp77cpl4rveu
openai,GPT 5.6 Sol,global,,openai:global:global.openai.gpt-5.6-sol,4,20,0.4,5,,8,30,0.8,10,verified,2026-09-25T15:00:00Z,3,offer:offer-gnqokrqqvdbgw
openai,GPT 5.6 Sol,in_region,us-east-1,openai:us-east-1:openai.gpt-5.6-sol,4.4,22,0.44,5.5,,8.8,33,0.88,11,seed_only,,3,offer:offer-gnqokrqqvdbgw
openai,GPT 5.6 Terra,global,,openai:global:global.openai.gpt-5.6-terra,2,12,0.2,2.5,,4,18,0.4,5,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.6 Terra,in_region,us-east-1 us-east-2,openai:us-east-1:openai.gpt-5.6-terra openai:us-east-2:openai.gpt-5.6-terra,2.2,13.2,0.22,2.75,,4.4,19.8,0.44,5.5,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.6 Terra,in_region,us-west-2,openai:us-west-2:openai.gpt-5.6-terra,2.4,14.4,,,,,,,,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.5,in_region,us-east-1,openai:us-east-1:openai.gpt-5.5,5.5,33,0.55,,,11,49.5,1.1,,seed_only,,6,offer:offer-gpt55example
openai,GPT 5.4,openai_list,,openai-list:gpt-5.4,2.5,15,0.25,,,5,22.5,0.5,,verified,2026-09-25T15:00:00Z,4,openai-pricing
openai,GPT 5.4,in_region,us-east-1 us-east-2 us-west-2,openai:us-east-1:openai.gpt-5.4 openai:us-east-2:openai.gpt-5.4 openai:us-west-2:openai.gpt-5.4,2.75,16.5,0.275,,,5.5,24.75,0.55,,verified,2026-09-25T15:00:00Z,7,offer:offer-5l5a5izq5fbec
amazon,Nova 2.0 Lite,us,,us.amazon.nova-2-lite-v1:0,0.33,2.75,0.0825,0,,,,,,stale,2026-09-24T15:00:00Z,8,pricelist:USE1-Nova2.0Lite-input-tokens

reference_n,reference_id,kind,title,url,as_of
1,anthropic-pricing,anthropic_doc,Anthropic API 요금 (Claude Platform on AWS는 표준 요금),https://platform.claude.com/docs/en/about-claude/pricing#model-pricing,2026-09-25
2,offer:offer-7sp77cpl4rveu,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
3,offer:offer-gnqokrqqvdbgw,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
4,openai-pricing,openai_doc,OpenAI API 요금 (Standard),https://developers.openai.com/api/docs/pricing,2026-09-25
5,offer:offer-terra0example,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
6,offer:offer-gpt55example,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-27
7,offer:offer-5l5a5izq5fbec,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
8,pricelist:USE1-Nova2.0Lite-input-tokens,price_list,"AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html,2026-09-24
9,official:bedrock-pricing,official_page,Amazon Bedrock 요금,https://aws.amazon.com/bedrock/pricing/,
10,official:model-card-openai-gpt-54,official_page,"Amazon Bedrock 모델 카드, OpenAI GPT 5.4",https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html,
"""


def _family(payload, family_key):
    return next(f for f in payload["families"] if f["family_key"] == family_key)


def test_markdown_golden_ko():
    assert to_markdown(EXPECTED_PAYLOAD, "ko") == GOLDEN_MD_KO


def test_markdown_golden_en():
    assert to_markdown(EXPECTED_PAYLOAD, "en") == GOLDEN_MD_EN


def test_csv_golden_ko():
    assert to_csv(EXPECTED_PAYLOAD, "ko") == GOLDEN_CSV_KO


def test_tier_titles_columns_and_csv_header():
    assert TIER_KEYS == ("cp", "openai_list", "global", "us", "in_region")
    assert TIER_TITLES["ko"] == {
        "cp": "Claude Platform on AWS", "openai_list": "OpenAI 공식 가격", "global": "AWS Bedrock - Global CRIS",
        "us": "AWS Bedrock - US CRIS", "in_region": "AWS Bedrock - In Region"}
    assert TIER_TITLES["en"] == {**TIER_TITLES["ko"], "openai_list": "OpenAI official price"}
    assert PROVIDER_COLUMNS == {
        "anthropic": ("cp", "global", "us", "in_region"),
        "openai": ("openai_list", "global", "us", "in_region"),
        "amazon": ("global", "us", "in_region"),
    }
    assert CSV_HEADER == [
        "provider", "family", "channel", "regions", "model_ids", "input_usd_per_1m", "output_usd_per_1m",
        "cache_read_usd_per_1m", "cache_write_usd_per_1m", "cache_write_1h_usd_per_1m", "long_input_usd_per_1m",
        "long_output_usd_per_1m", "long_cache_read_usd_per_1m", "long_cache_write_usd_per_1m", "verification",
        "observed_at", "footnotes", "source_ids"]


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_every_markdown_table_separator_matches_its_header(lang):
    lines = to_markdown(EXPECTED_PAYLOAD, lang).split("\n")
    headers = [i for i, line in enumerate(lines) if line.startswith("| 모델 |") or line.startswith("| Model |")]
    assert len(headers) == 3  # Anthropic Claude, OpenAI, Amazon Nova — each table stands alone
    for i in headers:
        cells = lines[i].strip("|").split(" | ")
        assert lines[i + 1] == "|" + "---|" * len(cells)
    assert [len(lines[i].strip("|").split(" | ")) for i in headers] == [5, 5, 4]  # Nova has no blank column


def test_cache_line_lists_only_the_prices_a_cell_has():
    payload = copy.deepcopy(EXPECTED_PAYLOAD)
    _family(payload, "claude-opus-5-5")["tiers"]["cp"]["cache_read"] = None
    md = to_markdown(payload, "ko")
    assert "| Claude Opus 5.5 | 4 / 20[^1]<br>쓰기 5, 1시간 쓰기 8 | " in md
    assert "캐시 읽기 0.0825, 쓰기 0 |" in md  # an official $0 cache write is a price, not a missing one


def test_pending_lists_only_the_changed_prices_like_the_screen():
    payload = copy.deepcopy(EXPECTED_PAYLOAD)
    cell = _family(payload, "claude-opus-5-5")["tiers"]["global"]
    # Only the cache read changes (the per-field 50% gate can hold a row for that alone).
    cell["pending"] = {"id": 99, "input": 4, "output": 20, "cache_read": 0.3, "cache_write": 5, "cache_write_1h": 8,
                       "long": None, "observed_at": "2026-09-25T15:00:00Z"}
    assert "| 4 / 20 (검토 대기 캐시 읽기 0.3)[^2]<br>캐시 읽기 0.2, 쓰기 5, 1시간 쓰기 8 |" in to_markdown(payload, "ko")
    assert "| 4 / 20 (Pending review cache read 0.3)[^2]<br>cache read 0.2, write 5, 1h write 8 |" in to_markdown(
        payload, "en")
    cell["pending"]["cache_read"] = 0.2  # nothing differs: the pair, as on the screen
    assert "| 4 / 20 (검토 대기 4 / 20)[^2]<br>" in to_markdown(payload, "ko")


def test_note_item_ends_with_the_footnote_of_its_source_id():
    payload = copy.deepcopy(EXPECTED_PAYLOAD)
    sol = _family(payload, "gpt-5.6-sol")
    sol["notes"][0].update(source="manual_note", source_id="note:gpt-5.6-sol")
    payload["references"].append({"n": 11, "id": "note:gpt-5.6-sol", "kind": "manual_note",
                                  "title_en": "GPT 5.6 Sol promotion (manual note, 2026-09-23 AWS model card)",
                                  "title_ko": "GPT 5.6 Sol 프로모션 (수동 메모, 2026-09-23 AWS 모델 카드 기준)",
                                  "url": None, "as_of": None})
    md = to_markdown(payload, "ko")
    assert "10. GPT 5.6 Sol: 프로모션 단가, 최소 2026-11-21까지[^11]\n" in md
    assert "[^11]: GPT 5.6 Sol 프로모션 (수동 메모, 2026-09-23 AWS 모델 카드 기준)\n" in md


def test_csv_en_changes_only_the_disclaimer_and_reference_titles():
    en = to_csv(EXPECTED_PAYLOAD, "en")
    first, rest = en.split("\n", 1)
    assert first == BOM + '"# ' + EXPECTED_PAYLOAD["disclaimer"]["en"] + '"'
    assert '2,offer:offer-7sp77cpl4rveu,agreement_offer,"Amazon Bedrock agreement offer rate card, ' in rest
    assert "4,openai-pricing,openai_doc,OpenAI API pricing (Standard),https://developers.openai.com/api/docs/pricing," in rest
    assert rest.split("\n\n")[0] == GOLDEN_CSV_KO.split("\n", 1)[1].split("\n\n")[0]  # price rows are language-neutral


def test_csv_parses_back_into_two_tables():
    text = to_csv(EXPECTED_PAYLOAD, "ko")
    lines = text.lstrip(BOM).split("\n")
    # the disclaimer is one quoted field even though the Korean text contains a comma
    assert next(csv.reader([lines[0]])) == ["# " + EXPECTED_PAYLOAD["disclaimer"]["ko"]]
    assert "," in EXPECTED_PAYLOAD["disclaimer"]["ko"]
    prices, references = "\n".join(lines[1:]).split("\n\n")
    rows = list(csv.DictReader(io.StringIO(prices)))
    assert len(rows) == 12  # one row per cell (tier element), empty cells have no row
    terra = [r for r in rows if r["family"] == "GPT 5.6 Terra" and r["channel"] == "in_region"]
    assert [(r["regions"], r["input_usd_per_1m"], r["cache_read_usd_per_1m"]) for r in terra] == [
        ("us-east-1 us-east-2", "2.2", "0.22"), ("us-west-2", "2.4", "")]
    (listed,) = [r for r in rows if r["channel"] == "openai_list"]
    assert (listed["family"], listed["model_ids"], listed["long_input_usd_per_1m"], listed["long_cache_write_usd_per_1m"],
            listed["source_ids"]) == ("GPT 5.4", "openai-list:gpt-5.4", "5", "", "openai-pricing")
    (nova,) = [r for r in rows if r["provider"] == "amazon"]
    assert (nova["cache_read_usd_per_1m"], nova["cache_write_usd_per_1m"], nova["cache_write_1h_usd_per_1m"]) == (
        "0.0825", "0", "")
    assert [r["channel"] for r in rows if r["family"] == "GPT 5.4"] == ["openai_list", "in_region"]
    refs = list(csv.DictReader(io.StringIO(references)))
    assert [int(r["reference_n"]) for r in refs] == list(range(1, 11))


def test_json_is_the_payload():
    text = to_json(EXPECTED_PAYLOAD)
    assert json.loads(text) == EXPECTED_PAYLOAD
    assert "이 가격표는" in text  # ensure_ascii=False keeps Korean readable
    assert text.endswith("}\n")


def test_filenames():
    assert export_filename("csv", date(2026, 9, 26)) == "llm-monitor-unit-prices-2026-09-26.csv"
    assert export_filename("md", date(2026, 9, 26)) == "llm-monitor-unit-prices-2026-09-26.md"
    assert export_filename("json", date(2026, 9, 26)) == "llm-monitor-unit-prices-2026-09-26.json"
    with pytest.raises(ValueError):
        export_filename("xlsx", date(2026, 9, 26))


def test_unknown_lang_is_rejected():
    with pytest.raises(ValueError):
        to_markdown(EXPECTED_PAYLOAD, "ja")
    with pytest.raises(ValueError):
        to_csv(EXPECTED_PAYLOAD, "ja")


def test_no_last_sync_and_no_pending_lines():
    payload = dict(EXPECTED_PAYLOAD, last_sync=None, pending_review=0)
    md = to_markdown(payload, "ko")
    assert "- 마지막 자동 확인: 없음\n" in md
    assert "- 검토 대기:" not in md
