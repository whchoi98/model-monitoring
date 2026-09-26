"""pricing_export — golden CSV, Markdown and JSON for the golden payload (v2.30.0).

The exports are pure functions of the /api/pricing payload: same order, same footnote numbers, disclaimer
first (and last in Markdown). tests/_pricing_dataset.EXPECTED_PAYLOAD is the input; its correctness against
the database is pinned by test_pricing_payload.py.
"""

import csv
import io
import json
from datetime import date

import pytest

from pricing_export import BOM, export_filename, to_csv, to_json, to_markdown
from tests._pricing_dataset import EXPECTED_PAYLOAD

GOLDEN_MD_KO = """> 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.

# 비용 단가

- 통화와 단위: USD, 1M 토큰당, 입력 / 출력
- 생성 시각: 2026-09-25T16:00:00Z
- 마지막 자동 확인: 2026-09-25T15:00:31Z (completed)
- 검토 대기: 1

## Anthropic Claude

| 모델 | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20[^1] | 4 / 20[^2] | 4.4 / 22[^2] | — |

## Amazon Nova

| 모델 | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Nova 2.0 Lite | — | — | 0.33 / 2.75 (자동 확인 안 됨)[^3] | — |

## OpenAI

| 모델 | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| GPT 6 Luna | — | — | — | — |
| GPT 5.6 Sol | — | 4 / 20 (검토 대기 9 / 45)[^4] | — | 4.4 / 22 us-east-1 (자동 확인 안 됨)[^4] |
| GPT 5.6 Terra | — | 2 / 12[^5] | — | 2.2 / 13.2 us-east-1, us-east-2[^5]<br>2.4 / 14.4 us-west-2[^5] |
| GPT 5.5 | — | — | — | 5.5 / 33 us-east-1 (자동 확인 안 됨)[^6] |
| GPT 5.4 | — | — | — | 2.75 / 16.5 us-east-1, us-east-2, us-west-2[^7] |

## 참고 사항

1. 단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다.
2. Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다.
3. OpenAI는 입력 272K 이하 기준이다.
4. 캐시, batch, long-context, priority 단가는 포함하지 않는다.
5. 비용 화면은 각 프로브 시각의 단가로 계산한다.
6. 최종 가격은 공식 요금 페이지에서 확인한다[^8][^9].
7. GPT 5.6 Sol: 프로모션 단가, 최소 2026-11-21까지[^10]

## 참고 자료

[^1]: Anthropic API 요금 (Claude Platform on AWS는 표준 요금), https://platform.claude.com/docs/en/about-claude/pricing#model-pricing, 확인일 2026-09-25
[^2]: Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^3]: AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite), https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html, 확인일 2026-09-24
[^4]: Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^5]: Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^6]: Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-26
[^7]: Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^8]: Amazon Bedrock 요금, https://aws.amazon.com/bedrock/pricing/
[^9]: Amazon Bedrock 모델 카드, OpenAI GPT 5.4, https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
[^10]: 수동 메모: 프로모션 단가, 최소 2026-11-21까지

> 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.
"""

GOLDEN_MD_EN = """> This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.

# Unit prices

- Currency and unit: USD per 1M tokens, input / output
- Generated: 2026-09-25T16:00:00Z
- Last automatic check: 2026-09-25T15:00:31Z (completed)
- Pending review: 1

## Anthropic Claude

| Model | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20[^1] | 4 / 20[^2] | 4.4 / 22[^2] | — |

## Amazon Nova

| Model | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Nova 2.0 Lite | — | — | 0.33 / 2.75 (not verified automatically)[^3] | — |

## OpenAI

| Model | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| GPT 6 Luna | — | — | — | — |
| GPT 5.6 Sol | — | 4 / 20 (Pending review 9 / 45)[^4] | — | 4.4 / 22 us-east-1 (not verified automatically)[^4] |
| GPT 5.6 Terra | — | 2 / 12[^5] | — | 2.2 / 13.2 us-east-1, us-east-2[^5]<br>2.4 / 14.4 us-west-2[^5] |
| GPT 5.5 | — | — | — | 5.5 / 33 us-east-1 (not verified automatically)[^6] |
| GPT 5.4 | — | — | — | 2.75 / 16.5 us-east-1, us-east-2, us-west-2[^7] |

## Notes

1. Prices are in USD per 1M tokens, Standard tier input and output.
2. Global channel prices can differ from the US and In-Region channels of the same model.
3. OpenAI prices apply to inputs of 272K tokens or fewer.
4. Cache, batch, long-context and priority prices are not included.
5. The cost pages use the price in effect at each probe's time.
6. Confirm final prices on the official pricing pages[^8][^9].
7. GPT 5.6 Sol: Promotional price, at least until 2026-11-21[^10]

## References

[^1]: Anthropic API pricing (Claude Platform on AWS uses standard pricing), https://platform.claude.com/docs/en/about-claude/pricing#model-pricing, checked 2026-09-25
[^2]: Amazon Bedrock agreement offer rate card, offer-7sp77cpl4rveu (Claude Opus 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^3]: AWS Price List API, AmazonBedrock usage type USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite), https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html, checked 2026-09-24
[^4]: Amazon Bedrock agreement offer rate card, offer-gnqokrqqvdbgw (GPT 5.6 Sol), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^5]: Amazon Bedrock agreement offer rate card, offer-terra0example (GPT 5.6 Terra), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^6]: Amazon Bedrock agreement offer rate card, offer-gpt55example (GPT 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-26
[^7]: Amazon Bedrock agreement offer rate card, offer-5l5a5izq5fbec (GPT 5.4), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^8]: Amazon Bedrock pricing, https://aws.amazon.com/bedrock/pricing/
[^9]: Amazon Bedrock model card, OpenAI GPT 5.4, https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
[^10]: Manual note: Promotional price, at least until 2026-11-21

> This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.
"""

GOLDEN_CSV_KO = BOM + """# 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.
provider,family,channel,regions,model_ids,input_usd_per_1m,output_usd_per_1m,verification,observed_at,footnotes,source_ids
anthropic,Claude Opus 5.5,cp,,anthropic:claude-opus-5-5,4,20,verified,2026-09-25T15:00:00Z,1,anthropic-pricing
anthropic,Claude Opus 5.5,global,,global.anthropic.claude-opus-5-5,4,20,verified,2026-09-25T15:00:00Z,2,offer:offer-7sp77cpl4rveu
anthropic,Claude Opus 5.5,us,,us.anthropic.claude-opus-5-5,4.4,22,verified,2026-09-25T15:00:00Z,2,offer:offer-7sp77cpl4rveu
amazon,Nova 2.0 Lite,us,,us.amazon.nova-2-lite-v1:0,0.33,2.75,stale,2026-09-24T15:00:00Z,3,pricelist:USE1-Nova2.0Lite-input-tokens
openai,GPT 5.6 Sol,global,,openai:global:global.openai.gpt-5.6-sol,4,20,verified,2026-09-25T15:00:00Z,4,offer:offer-gnqokrqqvdbgw
openai,GPT 5.6 Sol,in_region,us-east-1,openai:us-east-1:openai.gpt-5.6-sol,4.4,22,seed_only,,4,offer:offer-gnqokrqqvdbgw
openai,GPT 5.6 Terra,global,,openai:global:global.openai.gpt-5.6-terra,2,12,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.6 Terra,in_region,us-east-1 us-east-2,openai:us-east-1:openai.gpt-5.6-terra openai:us-east-2:openai.gpt-5.6-terra,2.2,13.2,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.6 Terra,in_region,us-west-2,openai:us-west-2:openai.gpt-5.6-terra,2.4,14.4,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.5,in_region,us-east-1,openai:us-east-1:openai.gpt-5.5,5.5,33,seed_only,,6,offer:offer-gpt55example
openai,GPT 5.4,in_region,us-east-1 us-east-2 us-west-2,openai:us-east-1:openai.gpt-5.4 openai:us-east-2:openai.gpt-5.4 openai:us-west-2:openai.gpt-5.4,2.75,16.5,verified,2026-09-25T15:00:00Z,7,offer:offer-5l5a5izq5fbec

reference_n,reference_id,kind,title,url,as_of
1,anthropic-pricing,anthropic_doc,Anthropic API 요금 (Claude Platform on AWS는 표준 요금),https://platform.claude.com/docs/en/about-claude/pricing#model-pricing,2026-09-25
2,offer:offer-7sp77cpl4rveu,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
3,pricelist:USE1-Nova2.0Lite-input-tokens,price_list,"AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html,2026-09-24
4,offer:offer-gnqokrqqvdbgw,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
5,offer:offer-terra0example,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
6,offer:offer-gpt55example,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-26
7,offer:offer-5l5a5izq5fbec,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
8,official:bedrock-pricing,official_page,Amazon Bedrock 요금,https://aws.amazon.com/bedrock/pricing/,
9,official:model-card-openai-gpt-54,official_page,"Amazon Bedrock 모델 카드, OpenAI GPT 5.4",https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html,
10,note:gpt-5.6-sol,manual_note,"프로모션 단가, 최소 2026-11-21까지",,
"""


def test_markdown_golden_ko():
    assert to_markdown(EXPECTED_PAYLOAD, "ko") == GOLDEN_MD_KO


def test_markdown_golden_en():
    assert to_markdown(EXPECTED_PAYLOAD, "en") == GOLDEN_MD_EN


def test_csv_golden_ko():
    assert to_csv(EXPECTED_PAYLOAD, "ko") == GOLDEN_CSV_KO


def test_csv_en_changes_only_the_disclaimer_and_reference_titles():
    en = to_csv(EXPECTED_PAYLOAD, "en")
    first, rest = en.split("\n", 1)
    assert first == BOM + "# " + EXPECTED_PAYLOAD["disclaimer"]["en"]
    assert '2,offer:offer-7sp77cpl4rveu,agreement_offer,"Amazon Bedrock agreement offer rate card, ' in rest
    assert rest.split("\n\n")[0] == GOLDEN_CSV_KO.split("\n", 1)[1].split("\n\n")[0]  # price rows are language-neutral


def test_csv_parses_back_into_two_tables():
    text = to_csv(EXPECTED_PAYLOAD, "ko")
    lines = text.lstrip(BOM).split("\n")
    assert lines[0].startswith("# ")
    prices, references = "\n".join(lines[1:]).split("\n\n")
    rows = list(csv.DictReader(io.StringIO(prices)))
    assert len(rows) == 11  # one row per cell (tier element), empty cells have no row
    terra = [r for r in rows if r["family"] == "GPT 5.6 Terra" and r["channel"] == "in_region"]
    assert [(r["regions"], r["input_usd_per_1m"]) for r in terra] == [("us-east-1 us-east-2", "2.2"), ("us-west-2", "2.4")]
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
