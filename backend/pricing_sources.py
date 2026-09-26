"""단가 식별과 공식 출처 메타데이터 — 순수 데이터와 분류, DB와 네트워크 없음 (v2.30.0, ADR-030).

price_identity는 전부 정확 일치다(v2.29.1 get_pricing의 prefix fallback이 Claude US를 Global 단가로, Nova 2.0
Lite를 1세대 Nova Lite 단가로 매칭한 오류). CP는 prober _ANTHROPIC_TARGETS와 같은 substring 규칙 + 점 버전 제외.
분류할 수 없으면 None(비용 "-"). 새 모델은 이 매핑과 pricing_seed.py를 함께 고친다(tests가 prober 등록으로 잡는다).
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)  # seed, no_baseline 행의 effective_from
PROVIDER_ORDER: tuple[str, ...] = ("anthropic", "amazon", "openai")
# frontend/src/lib/sortModels.ts FAMILY_ORDER와 바이트 단위로 같아야 한다(tests가 파일을 읽어 고정).
FAMILY_ORDER: tuple[str, ...] = (
    "Claude Fable 5.1", "Claude Fable 5", "Claude Opus 5.5", "Claude Opus 5", "Claude Opus 4.8",
    "Claude Opus 4.7", "Claude Opus 4.6", "Claude Sonnet 5", "Claude Sonnet 4.6", "Claude Haiku 4.5",
    "Nova 2.0 Lite", "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna", "GPT 5.6 Sol", "GPT 5.6 Terra",
    "GPT 5.6 Luna", "GPT 5.5", "GPT 5.4",
)


@dataclass(frozen=True)
class PriceIdentity:
    family_key: str   # claude-opus-4-6 | claude-haiku-4-5 | nova-2-lite | gpt-6-astra | gpt-5.6-sol | gpt-5.4 ...
    family: str       # FAMILY_ORDER 문자열
    provider: str     # anthropic | amazon | openai
    channel: str      # cp | global | us | inregion:<aws-region>
    source_kind: str  # offer | pricelist | anthropic_doc
    source_ref: str   # offer: FM id / pricelist: NOVA_USAGETYPES 키 / anthropic_doc: 문서 모델명


# Bedrock Claude offer FM id → (family_key, family). global./us. 접두를 뗀 값과 정확 일치.
_BEDROCK_CLAUDE_FM: dict[str, tuple[str, str]] = {
    "anthropic.claude-fable-5-1": ("claude-fable-5-1", "Claude Fable 5.1"),
    "anthropic.claude-fable-5": ("claude-fable-5", "Claude Fable 5"),
    "anthropic.claude-opus-5-5": ("claude-opus-5-5", "Claude Opus 5.5"),
    "anthropic.claude-opus-5": ("claude-opus-5", "Claude Opus 5"),
    "anthropic.claude-opus-4-8": ("claude-opus-4-8", "Claude Opus 4.8"),
    "anthropic.claude-opus-4-7": ("claude-opus-4-7", "Claude Opus 4.7"),
    "anthropic.claude-opus-4-6-v1": ("claude-opus-4-6", "Claude Opus 4.6"),
    "anthropic.claude-sonnet-5": ("claude-sonnet-5", "Claude Sonnet 5"),
    "anthropic.claude-sonnet-4-6": ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ("claude-haiku-4-5", "Claude Haiku 4.5"),
}
_CLAUDE_FAMILY_NAMES = {fk: fam for fk, fam in _BEDROCK_CLAUDE_FM.values()}
# CP — prober._ANTHROPIC_TARGETS와 같은 substring, 같은 순서(tests가 고정). family_key = "claude-" + substring.
_CP_TARGETS = ("fable-5-1", "fable-5", "opus-5-5", "opus-5", "opus-4-8", "opus-4-7", "sonnet-5", "sonnet-4-6", "haiku-4-5")
ANTHROPIC_DOC_NAMES: dict[str, str] = {f"claude-{s}": _CLAUDE_FAMILY_NAMES[f"claude-{s}"] for s in _CP_TARGETS}
ANTHROPIC_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
ANTHROPIC_SOURCE_ID = "anthropic-pricing"
# Nova — Price List usagetype(USE1 regional, 1K tokens). us.amazon.* 는 us-east-1 호출 US(Geo) 채널.
NOVA_USAGETYPES: dict[str, tuple[str, str]] = {
    "nova-2-lite": ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens"),
}
_PRICELIST_MODEL_IDS = {"us.amazon.nova-2-lite-v1:0": ("nova-2-lite", "Nova 2.0 Lite", "us")}
# OpenAI offer FM id(= Mantle in-region id) → (family_key, family)
_OPENAI_FM: dict[str, tuple[str, str]] = {
    "openai.gpt-6-astra": ("gpt-6-astra", "GPT 6 Astra"), "openai.gpt-6-sol": ("gpt-6-sol", "GPT 6 Sol"),
    "openai.gpt-6-luna": ("gpt-6-luna", "GPT 6 Luna"), "openai.gpt-5.6-sol": ("gpt-5.6-sol", "GPT 5.6 Sol"),
    "openai.gpt-5.6-terra": ("gpt-5.6-terra", "GPT 5.6 Terra"), "openai.gpt-5.6-luna": ("gpt-5.6-luna", "GPT 5.6 Luna"),
    "openai.gpt-5.5": ("gpt-5.5", "GPT 5.5"), "openai.gpt-5.4": ("gpt-5.4", "GPT 5.4"),
}
# in-region은 offer 차원 리전 접두(USE1_/USE2_/USW2_)가 있는 리전만 — 새 리전은 fail-closed(단가 없음).
_INREGION_REGIONS = ("us-east-1", "us-east-2", "us-west-2")


def _is_point_release_of(substring: str, model_id: str) -> bool:
    """prober._is_point_release_of 복제(prober는 boto3, DB를 끌어온다). tests가 prober와 동등성을 고정."""
    return re.search(re.escape(substring) + r"-\d{1,2}(?!\d)", model_id) is not None


def _cp_family_key(actual_id: str) -> str | None:
    for sub in _CP_TARGETS:
        longer = [s for s in _CP_TARGETS if s != sub and sub in s]
        if sub in actual_id and not any(s in actual_id for s in longer) and not _is_point_release_of(sub, actual_id):
            return f"claude-{sub}"
    return None


def price_identity(model_id: str) -> PriceIdentity | None:
    """활성 채널 model_id → 단가 식별자, 분류할 수 없으면 None(예외 아님)."""
    if model_id.startswith("anthropic:"):
        fk = _cp_family_key(model_id[len("anthropic:"):])
        if fk is None:
            return None
        return PriceIdentity(fk, _CLAUDE_FAMILY_NAMES[fk], "anthropic", "cp", "anthropic_doc", ANTHROPIC_DOC_NAMES[fk])
    if model_id.startswith("openai:"):
        parts = model_id.split(":", 2)
        if len(parts) != 3:
            return None
        _, region, actual = parts
        if region in ("global", "us"):
            if not actual.startswith(f"{region}."):
                return None
            fm, channel = actual[len(region) + 1:], region
        elif region in _INREGION_REGIONS:
            fm, channel = actual, f"inregion:{region}"
        else:
            return None  # openai:1p:*(휴면 1P) 또는 모르는 리전
        if fm not in _OPENAI_FM:
            return None
        return PriceIdentity(*_OPENAI_FM[fm], "openai", channel, "offer", fm)
    if model_id in _PRICELIST_MODEL_IDS:
        fk, fam, channel = _PRICELIST_MODEL_IDS[model_id]
        return PriceIdentity(fk, fam, "amazon", channel, "pricelist", fk)
    prefix, _, fm = model_id.partition(".")
    if prefix in ("global", "us") and fm in _BEDROCK_CLAUDE_FM:
        return PriceIdentity(*_BEDROCK_CLAUDE_FM[fm], "anthropic", prefix, "offer", fm)
    return None


def tier_of(channel: str) -> str:
    """채널 → /api/pricing tiers 키(cp | global | us | in_region)."""
    if channel in ("cp", "global", "us"):
        return channel
    if channel.startswith("inregion:"):
        return "in_region"
    raise ValueError(f"unknown price channel: {channel!r}")


def region_of(channel: str) -> str | None:
    return channel[len("inregion:"):] if channel.startswith("inregion:") else None


def active_channels(models: Mapping[str, str], hidden: Sequence[str]) -> dict[str, PriceIdentity]:
    """{model_id: label} → 숨김 라벨은 조용히, 분류 불가 id는 경고 후 뺀 {model_id: PriceIdentity}(순서 유지)."""
    out: dict[str, PriceIdentity] = {}
    for model_id, label in models.items():
        if any(p and p in label for p in hidden):
            continue
        ident = price_identity(model_id)
        if ident is None:
            logger.warning("No price identity for active model %s (%s) - cost shows '-'", model_id, label)
            continue
        out[model_id] = ident
    return out


def offer_source_id(offer_id: str) -> str:
    return f"offer:{offer_id}"


def pricelist_source_id(usagetype: str) -> str:
    return f"pricelist:{usagetype}"


def official_source_id(slug: str) -> str:
    return f"official:{slug}"


def note_source_id(family_key: str) -> str:
    return f"note:{family_key}"


# references 고정 URL(셀 인용 출처, pricing_payload.py가 쓴다). CP 표준 요금 근거(#claude-platform-on-aws-pricing)는
# Anthropic 참고 자료 제목("Claude Platform on AWS는 표준 요금")으로만 싣는다 — PricingReference의 url은 하나다.
OFFER_REFERENCE_URL = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html"
PRICELIST_REFERENCE_URL = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html"
ANTHROPIC_REFERENCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing"

# 화면과 다운로드 3형식 공용 — KO, EN은 여기 한 곳에만 둔다.
DISCLAIMER: dict[str, str] = {
    "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
          "최종 가격은 반드시 공식 사이트에서 확인하세요.",
    "en": "This price list is compiled automatically from public sources for reference only and is not "
          "an official AWS statement. Always confirm final prices on the official pricing pages.",
}

# 고정 안내 항목(official_page, source_id official:<slug>) — 하드코딩, 런타임 존재 확인 없음
OFFICIAL_PAGES: list[dict] = [
    {"slug": "bedrock-pricing", "title_en": "Amazon Bedrock pricing", "title_ko": "Amazon Bedrock 요금",
     "url": "https://aws.amazon.com/bedrock/pricing/"},
    *(
        {"slug": f"model-card-openai-{slug}", "title_en": f"Amazon Bedrock model card: OpenAI {name}",
         "title_ko": f"Amazon Bedrock 모델 카드: OpenAI {name}",
         "url": f"https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{slug}.html"}
        for slug, name in (
            ("gpt-54", "GPT-5.4"), ("gpt-55", "GPT-5.5"), ("gpt-56-sol", "GPT-5.6 Sol"),
            ("gpt-56-terra", "GPT-5.6 Terra"), ("gpt-56-luna", "GPT-5.6 Luna"), ("gpt-6-astra", "GPT-6 Astra"),
            ("gpt-6-sol", "GPT-6 Sol"), ("gpt-6-luna", "GPT-6 Luna"),
        )
    ),
]

# 수동 메모(manual_note, 공식 출처 아님) — 근거: 2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1
# basis_en/basis_ko는 참고 자료 제목에만 쓴다(pricing_payload가 제목 앞에 패밀리 이름을 붙이고 families[].notes에서는 뺀다).
PRICE_NOTES: list[dict] = [{
    "family_key": "gpt-5.6-sol",
    "kind": "promo",
    "min_until": "2026-11-21",
    "prior_price": {"in_region": {"input": 5.5, "output": 33}, "global": {"input": 5, "output": 30}},
    "text_ko": "프로모션 단가다. 2026-09-23 AWS 모델 카드에 최소 2026-11-21까지 적용한다고 기재됐고, "
               "지금은 공식 출처에 표시가 없어 수동 메모로 관리한다(CHANGELOG v2.28.1).",
    "text_en": "Promotional price. The AWS model card stated on 2026-09-23 that it applies at least through "
               "2026-11-21; no official source shows it now, so it is kept as a manual note (CHANGELOG v2.28.1).",
    "basis_ko": "2026-09-23 AWS 모델 카드 기준",
    "basis_en": "2026-09-23 AWS model card",
    "source": "manual_note",
}]
