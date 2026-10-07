"""단가 seed — 활성 채널(v2.33.0 66) 공식 단가 초기값과 model_id 단위 멱등 삽입 (v2.30.0, ADR-030).

출처(2026-09-26 스파이크, USD per 1M tokens, Standard 입력/출력): Bedrock agreement offer rate card(FM 18개,
offerId 리전 무관), AWS Price List(Nova 2.0 Lite USE1, 1K tokens × 1000), Anthropic pricing.md(CP 9).
v2.29.1 대비 교정 11채널(결정 8, 과거까지): Bedrock Claude US 10 = Global × 1.1, Nova 2.0 Lite 0.33 / 2.75.
나머지 44채널은 v2.29.1 값과 같다. 새 모델은 pricing_sources.py 매핑과 함께 여기 표를 고친다.
v2.31.0: 2026-09-27 공식 출처의 표시 전용 캐시, 긴 컨텍스트 단가 seed와 OpenAI 공식 가격 seed(openai-list 채널 8개,
합계 63채널)를 더했고, v2.30.0 seed 행은 NULL인 확장 열만 seed 값으로 채운다.
v2.32.0: 2026-09-30 오퍼와 문서로 7채널을 더했다 — Claude Sonnet 5.5(Global, CP), GPT 6.1 Sol(Global, US, us-east-1),
서울 in-region Claude Opus 5, Sonnet 5(bedrock:ap-northeast-2:<FM id>, APN2_*_standard). 활성 62채널, offer FM 20개,
openai-list 9개, 합계 71채널.
v2.33.0: 2026-10-07 오퍼와 문서로 4채널을 더했다 — Claude Haiku 5.5(Global, US, CP)와 Claude Sonnet 5.5 US(같은 날 us. 프로파일이
생겼다). Haiku 5.5는 100K 토큰 초과 프롬프트 단가를 긴 컨텍스트 4필드로 둔다(Claude 중 유일, pricing_sources.CLAUDE_LONG_CONTEXT_FAMILIES).
같은 날 Sonnet 5.5 Bedrock 캐시 읽기가 0.2 → 0.1(US 0.22 → 0.11)로 내렸다. CP는 Anthropic 문서 표가 아직 0.2라 그대로 둔다
(pricing_sources.PRICE_NOTES 문서 불일치 메모). 활성 66채널, offer FM 21개, openai-list 9개, 합계 75채널.
"""

import logging
from datetime import date, datetime, timezone
from typing import Mapping

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import func, insert, select, text

from models import PriceHistory
from pricing_parsers import EXTRA_FIELDS
from pricing_sources import (
    ANTHROPIC_SOURCE_ID, EPOCH, NOVA_USAGETYPES, OPENAI_SOURCE_ID, PriceIdentity, offer_source_id, pricelist_source_id,
)

logger = logging.getLogger(__name__)

SEED_SOURCE_DATE = date(2026, 9, 27)  # seed만 있는 참고 자료의 확인일(as_of) 기본값 — 2026-09-27 공식 출처로 다시 확인
# 출처별 seed 확인일 — 기본값과 다른 날 확인한 출처만 둔다. 첫 동기화가 관측하기 전에는 이 날짜가 참고 자료의 as_of다.
# v2.32.0 새 오퍼 두 개는 2026-09-30에 확인했다(2026-09-27에는 오퍼가 없었다).
SEED_SOURCE_DATES: dict[str, date] = {
    offer_source_id("offer-5fu2rhus3byrs"): date(2026, 9, 30),  # Claude Sonnet 5.5
    offer_source_id("offer-wbhj4kycntgkk"): date(2026, 9, 30),  # GPT 6.1 Sol
    offer_source_id("offer-u3aih6zr7uw5u"): date(2026, 10, 7),  # Claude Haiku 5.5 (v2.33.0)
}
# backend 태스크 기동과 PricingSync 러너가 겹쳐도 같은 model_id를 두 번 seed하지 않는다(트랜잭션 잠금).
# 잠금 전에 트랜잭션 한정 상한을 건다 — 잠금 대기나 느린 쿼리가 lifespan/러너를 붙잡지 않게.
_SEED_TIMEOUT_SQL = ("SET LOCAL statement_timeout = '30000'", "SET LOCAL lock_timeout = '5000'")
_SEED_LOCK_SQL = "SELECT pg_advisory_xact_lock(917350003)"
# v2.31.0 표시 전용 단가 필드 → price_history 열 이름(필드 f의 열은 f"{f}_per_mtok"), EXTRA_FIELDS 순서
_EXTRA_COLUMN: dict[str, str] = {f: f"{f}_per_mtok" for f in EXTRA_FIELDS}

# Bedrock Claude FM id → (offerId, Global in, Global out, US와 in-region in, out, 채널).
# Global = APN2_*_global_standard, US = USE1_*_standard, 서울 in-region = APN2_*_standard(US와 같은 값, v2.32.0).
# 채널: "global" → global.<FM>, "us" → us.<FM>, AWS 리전 → bedrock:<region>:<FM>(in-region 온디맨드).
_CLAUDE: dict[str, tuple[str, float, float, float, float, tuple[str, ...]]] = {
    "anthropic.claude-fable-5-1": ("offer-icq4574v6gz3i", 10.0, 50.0, 11.0, 55.0, ("global", "us")),
    "anthropic.claude-fable-5": ("offer-vk3fuman5qwzy", 10.0, 50.0, 11.0, 55.0, ("global", "us")),
    "anthropic.claude-opus-5-5": ("offer-7sp77cpl4rveu", 4.0, 20.0, 4.4, 22.0, ("global", "us")),
    "anthropic.claude-opus-5": ("offer-f3u6lgbrem3zs", 5.0, 25.0, 5.5, 27.5, ("global", "us", "ap-northeast-2")),
    "anthropic.claude-opus-4-8": ("offer-wdkl4yk6s7uu4", 5.0, 25.0, 5.5, 27.5, ("global", "us")),
    "anthropic.claude-opus-4-7": ("offer-sltne4evyuyeu", 5.0, 25.0, 5.5, 27.5, ("global", "us")),
    "anthropic.claude-opus-4-6-v1": ("offer-ee7a27hh4hr62", 5.0, 25.0, 5.5, 27.5, ("global", "us")),
    # Sonnet 5.5: v2.32.0은 Global만(us. 프로파일 없음, 2026-09-30), v2.33.0에 US(USE1_*_standard 2.2 / 11, 2026-10-07)
    "anthropic.claude-sonnet-5-5": ("offer-5fu2rhus3byrs", 2.0, 10.0, 2.2, 11.0, ("global", "us")),
    "anthropic.claude-sonnet-5": ("offer-2ykemehpsyf7g", 2.0, 10.0, 2.2, 11.0, ("global", "us", "ap-northeast-2")),
    "anthropic.claude-sonnet-4-6": ("offer-ldnd26nhxx676", 3.0, 15.0, 3.3, 16.5, ("global", "us")),
    "anthropic.claude-haiku-5-5": ("offer-u3aih6zr7uw5u", 0.1, 0.5, 0.11, 0.55, ("global", "us")),  # v2.33.0
    "anthropic.claude-haiku-4-5-20251001-v1:0": ("offer-fudwqbphlos64", 1.0, 5.0, 1.1, 5.5, ("global", "us")),
}
# OpenAI FM id → (offerId, US CRIS와 in-region in, out, Global in, out, 채널 리전)
_OPENAI: dict[str, tuple[str, float, float, float | None, float | None, tuple[str, ...]]] = {
    "openai.gpt-6.1-sol": ("offer-wbhj4kycntgkk", 2.2, 11.0, 2.0, 10.0, ("global", "us", "us-east-1")),
    "openai.gpt-6-astra": ("offer-7epta7rbw5aws", 11.0, 55.0, 10.0, 50.0, ("global", "us", "us-west-2")),
    "openai.gpt-6-sol": ("offer-pycji3sz5gpcc", 2.2, 11.0, 2.0, 10.0, ("global", "us", "us-east-1")),
    "openai.gpt-6-luna": ("offer-gmo53nkzc5or6", 0.11, 0.55, 0.1, 0.5, ("global", "us", "us-east-1")),
    "openai.gpt-5.6-sol": ("offer-gnqokrqqvdbgw", 4.4, 22.0, 4.0, 20.0, ("global", "us-east-1", "us-east-2")),
    "openai.gpt-5.6-terra": ("offer-3dvyrx3okd4lq", 2.2, 13.2, 2.0, 12.0, ("global", "us-east-1", "us-east-2", "us-west-2")),
    "openai.gpt-5.6-luna": ("offer-bklbyf2ewuawu", 0.22, 1.32, 0.2, 1.2, ("global", "us-east-1", "us-east-2", "us-west-2")),
    "openai.gpt-5.5": ("offer-rtwlbb46hcxpw", 5.5, 33.0, None, None, ("us-east-1", "us-east-2")),
    "openai.gpt-5.4": ("offer-5l5a5izq5fbec", 2.75, 16.5, None, None, ("us-east-1", "us-east-2", "us-west-2")),
}


def _claude_channel_id(fm: str, channel: str) -> str:
    return f"{channel}.{fm}" if channel in ("global", "us") else f"bedrock:{channel}:{fm}"


def _openai_seed(fm: str, region: str, spec: tuple) -> tuple[str, tuple[float, float, str]]:
    offer, r_in, r_out, g_in, g_out, _ = spec
    src = offer_source_id(offer)
    if region == "global":
        return f"openai:global:global.{fm}", (g_in, g_out, src)
    mid = f"openai:us:us.{fm}" if region == "us" else f"openai:{region}:{fm}"
    return mid, (r_in, r_out, src)


# model_id → (input, output, source_id) — CP를 뺀 활성 55채널
SEED: dict[str, tuple[float, float, str]] = {
    **{_claude_channel_id(fm, ch): ((g_in, g_out) if ch == "global" else (r_in, r_out)) + (offer_source_id(o),)
       for fm, (o, g_in, g_out, r_in, r_out, channels) in _CLAUDE.items() for ch in channels},
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75, pricelist_source_id(NOVA_USAGETYPES["nova-2-lite"][0])),
    **dict(_openai_seed(fm, r, spec) for fm, spec in _OPENAI.items() for r in spec[5]),
}

# Claude Platform on AWS — model_id가 디스커버리로 정해지므로(날짜 접미사) family_key 단위
CP_SEED: dict[str, tuple[float, float, str]] = {
    fk: (i, o, ANTHROPIC_SOURCE_ID)
    for fk, i, o in (
        ("claude-fable-5-1", 10.0, 50.0), ("claude-fable-5", 10.0, 50.0), ("claude-opus-5-5", 4.0, 20.0),
        ("claude-opus-5", 5.0, 25.0), ("claude-opus-4-8", 5.0, 25.0), ("claude-opus-4-7", 5.0, 25.0),
        ("claude-sonnet-5-5", 2.0, 10.0), ("claude-sonnet-5", 2.0, 10.0), ("claude-sonnet-4-6", 3.0, 15.0),
        ("claude-haiku-5-5", 0.1, 0.5), ("claude-haiku-4-5", 1.0, 5.0),
    )
}

# OpenAI 공식 가격(openai_list, 표시 전용) — OpenAI pricing.md "### Standard pricing data"(2026-09-27), family_key 단위.
# 합성 model_id openai-list:<family_key>는 active_channels가 만든다(v2.31.0).
OPENAI_LIST_SEED: dict[str, tuple[float, float, str]] = {
    fk: (i, o, OPENAI_SOURCE_ID)
    for fk, i, o in (
        ("gpt-6.1-sol", 2.0, 10.0), ("gpt-6-astra", 10.0, 50.0), ("gpt-6-sol", 2.0, 10.0), ("gpt-6-luna", 0.1, 0.5),
        ("gpt-5.6-sol", 4.0, 20.0), ("gpt-5.6-terra", 2.0, 12.0), ("gpt-5.6-luna", 0.2, 1.2),
        ("gpt-5.5", 5.0, 30.0), ("gpt-5.4", 2.5, 15.0),
    )
}


# ---------------------------------------------------------------- v2.31.0 표시 전용 단가 (캐시, 긴 컨텍스트)
# 2026-09-27 공식 출처 값, USD per 1M tokens. None = 출처에 그 단가가 없다. 비용 계산에는 쓰지 않는다.
_CACHE_FIELDS = ("cache_read", "cache_write", "cache_write_1h")
_GPT_FIELDS = ("cache_read", "cache_write", "long_input", "long_output", "long_cache_read", "long_cache_write")

# Bedrock Claude FM id → (Global, US와 in-region), 각각 (캐시 읽기, 5분 캐시 쓰기, 1시간 캐시 쓰기).
# Global = APN2_*_global_standard(레거시 APN2_*_Global), US = USE1_*_standard(레거시 USE1_*),
# 서울 in-region = APN2_*_standard(US와 같은 값, v2.32.0). 채널은 _CLAUDE의 채널 튜플을 따른다.
_CLAUDE_CACHE: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "anthropic.claude-fable-5-1": ((0.25, 12.5, 20.0), (0.275, 13.75, 22.0)),
    "anthropic.claude-fable-5": ((1.0, 12.5, 20.0), (1.1, 13.75, 22.0)),
    "anthropic.claude-opus-5-5": ((0.2, 5.0, 8.0), (0.22, 5.5, 8.8)),
    "anthropic.claude-opus-5": ((0.5, 6.25, 10.0), (0.55, 6.875, 11.0)),
    "anthropic.claude-opus-4-8": ((0.5, 6.25, 10.0), (0.55, 6.875, 11.0)),
    "anthropic.claude-opus-4-7": ((0.5, 6.25, 10.0), (0.55, 6.875, 11.0)),
    "anthropic.claude-opus-4-6-v1": ((0.5, 6.25, 10.0), (0.55, 6.875, 11.0)),
    # Sonnet 5.5 캐시 읽기는 2026-10-07 인하(0.2 → 0.1, US 0.22 → 0.11 — offer-5fu2rhus3byrs, v2.33.0)
    "anthropic.claude-sonnet-5-5": ((0.1, 2.5, 4.0), (0.11, 2.75, 4.4)),
    "anthropic.claude-sonnet-5": ((0.2, 2.5, 4.0), (0.22, 2.75, 4.4)),
    "anthropic.claude-sonnet-4-6": ((0.3, 3.75, 6.0), (0.33, 4.125, 6.6)),
    "anthropic.claude-haiku-5-5": ((0.01, 0.125, 0.2), (0.011, 0.1375, 0.22)),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ((0.1, 1.25, 2.0), (0.11, 1.375, 2.2)),
}
# 프롬프트 길이로 단가가 갈리는 Claude(pricing_sources.CLAUDE_LONG_CONTEXT_FAMILIES)의 긴 컨텍스트 단가 — (Global, US),
# 각각 _LONG_FIELDS 순서. offer `_long_ctx` 차원(100K 토큰 초과, v2.33.0). 1시간 캐시 쓰기의 긴 컨텍스트 단가는 필드가 없다.
_LONG_FIELDS = ("long_input", "long_output", "long_cache_read", "long_cache_write")
_CLAUDE_LONG: dict[str, tuple[tuple[float, float, float, float], tuple[float, float, float, float]]] = {
    "anthropic.claude-haiku-5-5": ((0.5, 2.5, 0.05, 0.625), (0.55, 2.75, 0.055, 0.6875)),
}
# Claude Platform on AWS — Anthropic 문서 "Cache hits and refreshes", "5m cache writes", "1h cache writes" 열
_CP_CACHE: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (0.25, 12.5, 20.0), "claude-fable-5": (1.0, 12.5, 20.0), "claude-opus-5-5": (0.2, 5.0, 8.0),
    "claude-opus-5": (0.5, 6.25, 10.0), "claude-opus-4-8": (0.5, 6.25, 10.0), "claude-opus-4-7": (0.5, 6.25, 10.0),
    "claude-sonnet-5-5": (0.2, 2.5, 4.0), "claude-sonnet-5": (0.2, 2.5, 4.0), "claude-sonnet-4-6": (0.3, 3.75, 6.0),
    "claude-haiku-5-5": (0.01, 0.125, 0.2), "claude-haiku-4-5": (0.1, 1.25, 2.0),
}
# Claude Platform on AWS 긴 컨텍스트 — Anthropic 문서 "(for prompts over 100,000 tokens)" 행, _LONG_FIELDS 순서(v2.33.0)
_CP_LONG: dict[str, tuple[float, float, float, float]] = {"claude-haiku-5-5": (0.5, 2.5, 0.05, 0.625)}
# OpenAI FM id → (standard = US CRIS와 모든 in-region, global = Global CRIS), 각각 _GPT_FIELDS 순서.
# 캐시 쓰기 = offer cache_write_tokens_30m, 1시간 캐시 쓰기 없음. GPT 5.5, 5.4는 캐시 쓰기와 Global 채널이 없다.
_OPENAI_EXTRA: dict[str, tuple[tuple, tuple | None]] = {
    # GPT 6.1 Sol: 2026-09-30 오퍼의 긴 컨텍스트 출력(2.2 / 2)이 짧은 컨텍스트 출력보다 낮다 — 동기화가 긴 컨텍스트
    # 단가를 버리므로(pricing_sync._plausible_long) seed도 None으로 둔다(None은 동기화가 채울 수 있다)
    "openai.gpt-6.1-sol": ((0.11, 2.75, None, None, None, None), (0.1, 2.5, None, None, None, None)),
    "openai.gpt-6-astra": ((1.1, 13.75, 22.0, 82.5, 2.2, 27.5), (1.0, 12.5, 20.0, 75.0, 2.0, 25.0)),
    "openai.gpt-6-sol": ((0.22, 2.75, 4.4, 16.5, 0.44, 5.5), (0.2, 2.5, 4.0, 15.0, 0.4, 5.0)),
    "openai.gpt-6-luna": ((0.011, 0.1375, 0.22, 0.825, 0.022, 0.275), (0.01, 0.125, 0.2, 0.75, 0.02, 0.25)),
    "openai.gpt-5.6-sol": ((0.44, 5.5, 8.8, 33.0, 0.88, 11.0), (0.4, 5.0, 8.0, 30.0, 0.8, 10.0)),
    "openai.gpt-5.6-terra": ((0.22, 2.75, 4.4, 19.8, 0.44, 5.5), (0.2, 2.5, 4.0, 18.0, 0.4, 5.0)),
    "openai.gpt-5.6-luna": ((0.022, 0.275, 0.44, 1.98, 0.044, 0.55), (0.02, 0.25, 0.4, 1.8, 0.04, 0.5)),
    "openai.gpt-5.5": ((0.55, None, 11.0, 49.5, 1.1, None), None),
    "openai.gpt-5.4": ((0.275, None, 5.5, 24.75, 0.55, None), None),
}
# OpenAI 공식 가격(openai-list:<family_key>) — OpenAI 문서 "### Standard pricing data" 첫 표, _GPT_FIELDS 순서
_OPENAI_LIST_EXTRA: dict[str, tuple] = {
    "gpt-6.1-sol": (0.1, 2.5, 4.0, 15.0, 0.2, 5.0),
    "gpt-6-astra": (1.0, 12.5, 20.0, 75.0, 2.0, 25.0),
    "gpt-6-sol": (0.2, 2.5, 4.0, 15.0, 0.4, 5.0),
    "gpt-6-luna": (0.01, 0.125, 0.2, 0.75, 0.02, 0.25),
    "gpt-5.6-sol": (0.4, 5.0, 8.0, 30.0, 0.8, 10.0),
    "gpt-5.6-terra": (0.2, 2.5, 4.0, 18.0, 0.4, 5.0),
    "gpt-5.6-luna": (0.02, 0.25, 0.4, 1.8, 0.04, 0.5),
    "gpt-5.5": (0.5, None, 10.0, 45.0, 1.0, None),
    "gpt-5.4": (0.25, None, 5.0, 22.5, 0.5, None),
}
# Nova 2.0 Lite — Price List USE1 cache read / cache write usagetype(1K tokens × 1000), 공식 캐시 쓰기는 $0
_NOVA_CACHE: dict[str, tuple[float, float]] = {"us.amazon.nova-2-lite-v1:0": (0.0825, 0.0)}


def _extra(names: tuple[str, ...], values) -> dict[str, float | None]:
    """EXTRA_FIELDS 7개 전부를 담은 dict — names에 없는 필드와 값이 None인 필드는 None."""
    out: dict[str, float | None] = dict.fromkeys(EXTRA_FIELDS)
    out.update({name: None if v is None else float(v) for name, v in zip(names, values or ())})
    return out


def _long_extra(values) -> dict[str, float | None]:
    """긴 컨텍스트 4필드만 담은 dict — values가 None이면 전부 None (Claude는 CLAUDE_LONG_CONTEXT_FAMILIES만 값이 있다)."""
    return {name: None if values is None else float(v) for name, v in zip(_LONG_FIELDS, values or (None,) * 4)}


def _openai_channel_id(fm: str, region: str) -> str:
    return f"openai:{region}:{region}.{fm}" if region in ("global", "us") else f"openai:{region}:{fm}"


# model_id → 확장 필드 — CP와 OpenAI 공식 가격을 뺀 활성 55채널(SEED와 같은 키)
_SEED_EXTRA: dict[str, dict[str, float | None]] = {
    **{_claude_channel_id(fm, ch): {**_extra(_CACHE_FIELDS, g if ch == "global" else r),
                                    **_long_extra(_CLAUDE_LONG.get(fm, (None, None))[0 if ch == "global" else 1])}
       for fm, (g, r) in _CLAUDE_CACHE.items() for ch in _CLAUDE[fm][5]},
    **{mid: _extra(("cache_read", "cache_write"), v) for mid, v in _NOVA_CACHE.items()},
    **{_openai_channel_id(fm, region): _extra(_GPT_FIELDS, global_ if region == "global" else standard)
       for fm, (standard, global_) in _OPENAI_EXTRA.items() for region in _OPENAI[fm][5]},
}


def seed_extra(model_id: str, ident: PriceIdentity) -> dict[str, float | None]:
    """All seven EXTRA_FIELDS for one active channel (None where the source has no such price)."""
    if ident.channel == "cp":
        return {**_extra(_CACHE_FIELDS, _CP_CACHE.get(ident.family_key)), **_long_extra(_CP_LONG.get(ident.family_key))}
    if ident.channel == "openai_list":
        return _extra(_GPT_FIELDS, _OPENAI_LIST_EXTRA.get(ident.family_key))
    found = _SEED_EXTRA.get(model_id)
    return dict(found) if found is not None else _extra((), ())


def seed_rows(active: Mapping[str, PriceIdentity]) -> dict[str, tuple[float, float, str]]:
    """활성 채널 → {model_id: seed}. CP와 OpenAI 공식 가격은 family_key로 풀고, seed 없는 id는 경고 후 뺀다
    (동기화가 no_baseline)."""
    out: dict[str, tuple[float, float, str]] = {}
    for model_id, ident in active.items():
        if ident.channel == "cp":
            seed = CP_SEED.get(ident.family_key)
        elif ident.channel == "openai_list":
            seed = OPENAI_LIST_SEED.get(ident.family_key)
        else:
            seed = SEED.get(model_id)
        if seed is None:
            logger.warning("No seed price for %s (%s, %s)", model_id, ident.family_key, ident.channel)
            continue
        out[model_id] = seed
    return out


def _fill_seed_extras(conn, table, seeds: Mapping[str, tuple[float, float, str]],
                      extras: Mapping[str, dict[str, float | None]]) -> int:
    """seeds의 model_id에서 status='seed'이고 입력, 출력이 seed 값과 같은(소수 6자리) 행의 NULL 확장 열만 seed 값으로
    채운다. 이미 값이 있는 열은 덮어쓰지 않는다 — 각 열은 COALESCE(열, seed 값)로 써서 SELECT 뒤 UPDATE 전에 동시
    동기화가 커밋한 값도 그대로 둔다. 채운 행 수를 돌려준다."""
    found = conn.execute(
        select(table.c.id, table.c.model_id, table.c.input_per_mtok, table.c.output_per_mtok,
               *(table.c[col] for col in _EXTRA_COLUMN.values()))
        .where(table.c.model_id.in_(list(seeds)), table.c.status == "seed")
        .order_by(table.c.id)
    ).all()
    filled = 0
    for row in found:
        seed_in, seed_out, _ = seeds[row.model_id]
        if round(row.input_per_mtok, 6) != round(seed_in, 6) or round(row.output_per_mtok, 6) != round(seed_out, 6):
            continue
        values = {
            _EXTRA_COLUMN[field]: func.coalesce(table.c[_EXTRA_COLUMN[field]], value)
            for field, value in extras[row.model_id].items()
            if value is not None and getattr(row, _EXTRA_COLUMN[field]) is None
        }
        if values:
            conn.execute(table.update().where(table.c.id == row.id).values(**values))
            filled += 1
    return filled


def ensure_seed(engine, active: Mapping[str, PriceIdentity]) -> int:
    """price_history에 행이 하나도 없는 활성 model_id에만 seed 행을 넣고 넣은 수를 돌려준다.

    model_id 단위 멱등(테이블 전체 비었는지 보지 않음), 자체 트랜잭션, PostgreSQL은 SET LOCAL
    statement_timeout 30초와 lock_timeout 5초를 건 뒤 pg_advisory_xact_lock(917350003) 아래(SQLite 생략).
    effective_from=EPOCH, status='seed', observed_at=NULL, 확장 열은 seed_extra 값(v2.31.0).
    같은 트랜잭션과 잠금에서, 이미 행이 있는 활성 model_id의 status='seed' 행 중 입력, 출력이 seed 값과 같은(소수 6자리)
    행은 NULL인 확장 열만 seed 값으로 채운다(v2.30.0 seed 행 대비, 이미 값이 있는 열은 그대로).
    예외는 호출부(main.py lifespan, pricing_sync_runner)로 올린다.
    """
    rows = seed_rows(active)
    if not rows:
        return 0
    extras = {mid: seed_extra(mid, active[mid]) for mid in rows}
    table = PriceHistory.__table__
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            for sql in _SEED_TIMEOUT_SQL:
                conn.execute(text(sql))
            conn.execute(text(_SEED_LOCK_SQL))
        existing = set(conn.execute(
            select(table.c.model_id).where(table.c.model_id.in_(list(rows))).distinct()
        ).scalars())
        created_at = datetime.now(timezone.utc)
        values = [
            {"model_id": mid, "family_key": active[mid].family_key, "channel": active[mid].channel,
             "input_per_mtok": float(i), "output_per_mtok": float(o), "effective_from": EPOCH,
             "source_id": src, "status": "seed", "observed_at": None, "run_id": None, "created_at": created_at,
             **{_EXTRA_COLUMN[field]: value for field, value in extras[mid].items()}}
            for mid, (i, o, src) in rows.items() if mid not in existing
        ]
        if values:
            conn.execute(insert(table), values)
        filled = _fill_seed_extras(conn, table, {mid: rows[mid] for mid in existing}, extras) if existing else 0
    if values:
        logger.info("Price seed inserted %d rows (%d already had price history)", len(values), len(existing))
    if filled:
        logger.info("Price seed filled cache/long-context fields on %d rows", filled)
    return len(values)


def ensure_price_columns(engine) -> list[str]:
    """기존 price_history에 v2.31.0 표시 전용 단가 열 7개를 더하고, 더한 열 이름을 EXTRA_FIELDS 순서로 돌려준다.

    새 DB는 create_all이 ORM 선언으로 만든다. 운영 DB는 테이블이 이미 있어 create_all이 열을 더하지 않으므로 여기서 더한다.
    빠진 열이 없으면 DDL을 하나도 실행하지 않는다 — ADD COLUMN IF NOT EXISTS는 no-op이어도 ACCESS EXCLUSIVE 락을
    요청하므로 기동마다 락 대기열에 서지 않게 한다. 빠진 열이 있으면 한 트랜잭션에서, PostgreSQL은 SET LOCAL
    statement_timeout 30초와 lock_timeout 5초를 건 뒤 ADD COLUMN IF NOT EXISTS … DOUBLE PRECISION, 그 밖의 방언(SQLite)은
    ADD COLUMN … FLOAT. 예외는 호출부(main.py lifespan, pricing_sync_runner)로 올린다.
    """
    present = {col["name"] for col in sa_inspect(engine).get_columns(PriceHistory.__tablename__)}
    missing = [col for col in _EXTRA_COLUMN.values() if col not in present]
    if not missing:
        return []
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            for sql in _SEED_TIMEOUT_SQL:
                conn.execute(text(sql))
            for col in missing:
                conn.execute(text(f"ALTER TABLE price_history ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION"))
        else:
            for col in missing:
                conn.execute(text(f"ALTER TABLE price_history ADD COLUMN {col} FLOAT"))
    logger.info("Price columns added to price_history: %s", ", ".join(missing))
    return missing
