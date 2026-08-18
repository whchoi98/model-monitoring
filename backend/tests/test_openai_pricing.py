"""OpenAI pricing normalization + cost estimation."""
import pricing
from routers.cost import _channel


def test_normalize_openai_key():
    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.4") == "gpt-5.4"
    assert pricing._normalize_key("openai:us-east-2:openai.gpt-5.5") == "gpt-5.5"


def test_normalize_openai_global_key():
    # Bedrock global CRIS는 in-region과 단가가 달라 "-global" suffix 키로 분리 (v2.20.0).
    assert pricing._normalize_key("openai:global:global.openai.gpt-5.6-sol") == "gpt-5.6-sol-global"
    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.6-sol") == "gpt-5.6-sol"
    # Claude의 global. 프로파일은 종전대로 base 키로 collapse (suffix 미부여).
    assert pricing._normalize_key("global.anthropic.claude-opus-5") == "claude-opus-5"


def test_get_pricing_openai():
    assert pricing.get_pricing("openai:us-east-1:openai.gpt-5.4") == {"input": 2.75, "output": 16.5}
    assert pricing.get_pricing("openai:us-east-2:openai.gpt-5.5") == {"input": 5.5, "output": 33.0}


def test_get_pricing_gpt56_global_vs_in_region():
    # 공식 모델 카드 (Standard tier, short context) — global CRIS가 in-region보다 저렴.
    # in-region은 2026-07-30 인하 반영 (Luna -80%, Terra -20%, Sol 불변).
    assert pricing.get_pricing("openai:global:global.openai.gpt-5.6-sol") == {"input": 5.0, "output": 30.0}
    assert pricing.get_pricing("openai:us-east-1:openai.gpt-5.6-sol") == {"input": 5.5, "output": 33.0}
    assert pricing.get_pricing("openai:global:global.openai.gpt-5.6-terra") == {"input": 2.0, "output": 12.0}
    assert pricing.get_pricing("openai:us-east-2:openai.gpt-5.6-terra") == {"input": 2.2, "output": 13.2}
    assert pricing.get_pricing("openai:global:global.openai.gpt-5.6-luna") == {"input": 0.2, "output": 1.2}
    assert pricing.get_pricing("openai:us-west-2:openai.gpt-5.6-luna") == {"input": 0.22, "output": 1.32}


def test_estimate_cost_openai():
    # 1M input @2.75 + 1M output @16.5 = 19.25
    assert pricing.estimate_cost_usd("openai:us-east-1:openai.gpt-5.4", 1_000_000, 1_000_000) == 19.25


def test_existing_pricing_unbroken():
    assert pricing.get_pricing("us.anthropic.claude-fable-5") == {"input": 10.0, "output": 50.0}
    # Opus 4.8은 $5/$25 — 2026-07-24 공식 가격 확인 (기존 $15/$75는 Opus 4.1 단가로 오기재였음)
    assert pricing.get_pricing("anthropic:claude-opus-4-8") == {"input": 5.0, "output": 25.0}
    assert pricing.get_pricing("global.anthropic.claude-opus-5") == {"input": 5.0, "output": 25.0}


def test_channel_openai():
    assert _channel("openai:us-east-1:openai.gpt-5.4") == "OpenAI"
    assert _channel("openai:global:global.openai.gpt-5.6-sol") == "OpenAI"
    assert _channel("us.anthropic.claude-opus-4-8") == "Bedrock US"
    assert _channel("anthropic:claude-fable-5") == "Anthropic (CP on AWS)"
