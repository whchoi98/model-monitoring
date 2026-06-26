"""Unit tests for the OpenAI (Bedrock Mantle) provider path in prober.py.

No live API calls — env is monkeypatched and the OpenAI client is faked in Task 2.
"""
import prober


def test_is_openai_direct():
    assert prober._is_openai_direct("openai:us-east-1:openai.gpt-5.4") is True
    assert prober._is_openai_direct("anthropic:claude-fable-5") is False
    assert prober._is_openai_direct("us.anthropic.claude-opus-4-8") is False


def test_openai_parts():
    region, actual = prober._openai_parts("openai:us-east-2:openai.gpt-5.5")
    assert region == "us-east-2"
    assert actual == "openai.gpt-5.5"


def test_openai_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setenv("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1")
    assert prober._openai_base_url("us-east-1") == "https://e1/openai/v1"
    assert prober._openai_base_url("us-east-2") == "https://e2/openai/v1"


def test_map_openai_finish_reason():
    assert prober._map_openai_finish_reason("stop") == "end_turn"
    assert prober._map_openai_finish_reason("length") == "max_tokens"
    assert prober._map_openai_finish_reason("tool_calls") == "tool_use"
    assert prober._map_openai_finish_reason("content_filter") == "content_filtered"
    assert prober._map_openai_finish_reason(None) is None
    assert prober._map_openai_finish_reason("weird") == "weird"


def test_register_openai_models_registers_four(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setenv("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_54_MODEL_ID", "openai.gpt-5.4")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_55_MODEL_ID", "openai.gpt-5.5")
    prober._register_openai_models()
    assert prober.AVAILABLE_MODELS["openai:us-east-1:openai.gpt-5.4"] == "OpenAI GPT 5.4 (us-east-1)"
    assert prober.AVAILABLE_MODELS["openai:us-east-2:openai.gpt-5.4"] == "OpenAI GPT 5.4 (us-east-2)"
    assert prober.AVAILABLE_MODELS["openai:us-east-1:openai.gpt-5.5"] == "OpenAI GPT 5.5 (us-east-1)"
    assert prober.AVAILABLE_MODELS["openai:us-east-2:openai.gpt-5.5"] == "OpenAI GPT 5.5 (us-east-2)"


def test_register_openai_models_skips_without_key(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = len(prober.AVAILABLE_MODELS)
    prober._register_openai_models()
    assert len(prober.AVAILABLE_MODELS) == before
