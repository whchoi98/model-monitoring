"""모델 토큰 단가 (USD per 1M tokens) - frontend lib/pricing.ts와 동기화.

가격 출처: AWS Bedrock public pricing(모델 카드) + Anthropic public pricing (2026 기준).
모델 카드가 아직 없는 신규 출시 모델은 Bedrock ListFoundationModelAgreementOffers의
offer rate card를 출처로 쓰고, 카드가 게시되면 재대조한다 (예: GPT 6 Sol/Luna, ADR-028).
가격 변경 시 본 파일과 frontend/src/lib/pricing.ts를 함께 수정.
"""

from __future__ import annotations

from typing import Optional


PRICE_TABLE: dict[str, dict[str, float]] = {
    # Anthropic Claude (USD per 1M tokens: input / output)
    "claude-fable-5-1": {"input": 10.0, "output": 50.0},  # Fable 5.1 — Fable 5와 동일 티어/단가 (v2.22.0)
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    # Opus 5.5 (v2.27.0) — Anthropic 정가 $4/$20 (Opus 5보다 인하). 정확 키 필수:
    # 없으면 get_pricing prefix fallback이 "claude-opus-5"($5/$25)로 조용히 매칭된다.
    "claude-opus-5-5": {"input": 4.0, "output": 20.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6-v1": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001-v1:0": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    # Amazon Nova
    "nova-2-lite-v1:0": {"input": 0.06, "output": 0.24},
    # OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
    "gpt-5.4": {"input": 2.75, "output": 16.50},
    "gpt-5.5": {"input": 5.50, "output": 33.00},
    # GPT-5.6 세대 in-region/Geo 단가 — 2026-07-30 AWS 인하 반영 (Luna -80%, Terra -20%, Sol 불변).
    # 출처: AWS 공식 모델 카드 (Standard tier, short context ≤272K — 프로브는 항상 이 구간).
    "gpt-5.6-sol": {"input": 5.50, "output": 33.00},
    "gpt-5.6-terra": {"input": 2.20, "output": 13.20},
    "gpt-5.6-luna": {"input": 0.22, "output": 1.32},
    # Global CRIS(openai:global:global.openai.*)는 in-region보다 저렴한 별도 단가 — "-global" suffix 키.
    # ⚠️ 새 모델에 global 리전을 추가하면 여기 "-global" 키도 반드시 함께 추가할 것 —
    # 누락 시 get_pricing의 prefix fallback이 in-region 단가로 조용히 매칭돼 과대 산정됨.
    # ⚠️ 1P direct(openai:1p:*)는 여전히 base 키(in-region 단가) 공유 — 재노출 전 "-1p" 분리 필요.
    "gpt-5.6-sol-global": {"input": 5.00, "output": 30.00},
    "gpt-5.6-terra-global": {"input": 2.00, "output": 12.00},
    "gpt-5.6-luna-global": {"input": 0.20, "output": 1.20},
    # GPT 6 Astra — v2.25.0 미확정 → v2.27.0에서 AWS 공식 모델 카드 단가 반영 (Standard, ≤272K).
    # In-Region·Geo CRIS(US)는 OpenAI 정가 +10%, Global CRIS는 정가. 3키는 항상 함께 둔다 —
    # 하나만 있으면 prefix fallback이 나머지 채널을 그 단가로 오매칭한다.
    "gpt-6-astra": {"input": 11.00, "output": 55.00},
    "gpt-6-astra-us": {"input": 11.00, "output": 55.00},
    "gpt-6-astra-global": {"input": 10.00, "output": 50.00},
    # GPT 6 Sol / Luna (v2.27.0 출시) — 출처: AWS Bedrock ListFoundationModelAgreementOffers
    # rate card (2026-09-23 조회; Sol offer-pycji3sz5gpcc, Luna offer-gmo53nkzc5or6).
    # input/output_tokens_standard = In-Region, Geo CRIS(US) / *_global_standard = Global CRIS.
    # 교차 검증: 같은 방식으로 조회한 Astra offer(offer-7epta7rbw5aws, standard 11/55, global 10/50)가
    # Astra 공식 모델 카드와 정확히 일치하고, 값은 OpenAI 정가(Sol $2/$10, Luna $0.10/$0.50)에
    # 문서화된 In-Region, Geo +10%를 더한 값과 같다. 모델 카드 미게시 → 게시되면 카드와 재대조 (ADR-028).
    # 3키는 항상 함께 둔다 — 하나만 있으면 prefix fallback이 나머지 채널을 그 단가로 오매칭한다.
    "gpt-6-sol": {"input": 2.20, "output": 11.00},
    "gpt-6-sol-us": {"input": 2.20, "output": 11.00},
    "gpt-6-sol-global": {"input": 2.00, "output": 10.00},
    "gpt-6-luna": {"input": 0.11, "output": 0.55},
    "gpt-6-luna-us": {"input": 0.11, "output": 0.55},
    "gpt-6-luna-global": {"input": 0.10, "output": 0.50},
}

# OpenAI pseudo-region(Bedrock CRIS) — 채널 단가가 in-region과 달라 base 키에 "-<region>"
# suffix를 붙여 분리한다("-global"/"-us"). in-region, 1P 채널은 suffix 없음.
_OPENAI_CRIS_REGIONS: tuple[str, ...] = ("global", "us")


def _normalize_key(model_id: str) -> str:
    """inference profile prefix / namespace prefix를 strip해 base 키로."""
    key = model_id
    if key.startswith("anthropic:"):
        key = key[len("anthropic:"):]
    openai_cris_suffix = ""
    if key.startswith("openai:"):
        # openai:<region>:<actual_id> → <actual_id>. pseudo-region "global"/"us"(Bedrock
        # CRIS)은 in-region과 단가가 달라 base 키에 "-<region>" suffix를 붙여 구분한다.
        segs = key.split(":", 2)
        if len(segs) == 3 and segs[1] in _OPENAI_CRIS_REGIONS:
            openai_cris_suffix = f"-{segs[1]}"
        key = segs[-1]
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] in ("global", "us", "eu", "apac"):
        key = parts[1]
    if key.startswith("anthropic."):
        key = key[len("anthropic."):]
    if key.startswith("amazon."):
        key = key[len("amazon."):]
    if key.startswith("openai."):
        key = key[len("openai."):]
    if openai_cris_suffix:
        key = f"{key}{openai_cris_suffix}"
    return key


def get_pricing(model_id: str) -> Optional[dict[str, float]]:
    """model_id → {'input': USD_per_M, 'output': USD_per_M}. 미매칭 시 None."""
    key = _normalize_key(model_id)
    if key in PRICE_TABLE:
        return PRICE_TABLE[key]
    # prefix/suffix 매칭 fallback
    for k, v in PRICE_TABLE.items():
        if key.startswith(k) or k.startswith(key):
            return v
    return None


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """입·출력 토큰 → USD. 단가 없으면 None."""
    p = get_pricing(model_id)
    if p is None:
        return None
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000.0
