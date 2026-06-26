"""모델 토큰 단가 (USD per 1M tokens) - frontend lib/pricing.ts와 동기화.

가격 출처: AWS Bedrock public pricing + Anthropic public pricing (2026 기준).
가격 변경 시 본 파일과 frontend/src/lib/pricing.ts를 함께 수정.
"""

from __future__ import annotations

from typing import Optional


PRICE_TABLE: dict[str, dict[str, float]] = {
    # Anthropic Claude (USD per 1M tokens: input / output)
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-opus-4-8": {"input": 15.0, "output": 75.0},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6-v1": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001-v1:0": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    # Amazon Nova
    "nova-2-lite-v1:0": {"input": 0.06, "output": 0.24},
    # OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
    "gpt-5.4": {"input": 2.75, "output": 16.50},
    "gpt-5.5": {"input": 5.50, "output": 33.00},
}


def _normalize_key(model_id: str) -> str:
    """inference profile prefix / namespace prefix를 strip해 base 키로."""
    key = model_id
    if key.startswith("anthropic:"):
        key = key[len("anthropic:"):]
    if key.startswith("openai:"):
        # openai:<region>:<actual_id> → <actual_id>
        key = key.split(":", 2)[-1]
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] in ("global", "us", "eu", "apac"):
        key = parts[1]
    if key.startswith("anthropic."):
        key = key[len("anthropic."):]
    if key.startswith("amazon."):
        key = key[len("amazon."):]
    if key.startswith("openai."):
        key = key[len("openai."):]
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
