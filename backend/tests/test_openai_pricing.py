"""OpenAI pricing normalization + cost estimation."""
import pricing
from routers.cost import _channel


def test_normalize_openai_key():
    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.4") == "gpt-5.4"
    assert pricing._normalize_key("openai:us-east-2:openai.gpt-5.5") == "gpt-5.5"


def test_get_pricing_openai():
    assert pricing.get_pricing("openai:us-east-1:openai.gpt-5.4") == {"input": 2.75, "output": 16.5}
    assert pricing.get_pricing("openai:us-east-2:openai.gpt-5.5") == {"input": 5.5, "output": 33.0}


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
    assert _channel("us.anthropic.claude-opus-4-8") == "Bedrock US"
    assert _channel("anthropic:claude-fable-5") == "Anthropic (CP on AWS)"
