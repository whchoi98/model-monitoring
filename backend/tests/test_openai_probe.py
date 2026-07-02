"""Unit tests for the OpenAI (Bedrock Mantle) provider path in prober.py.

gpt-5.x are served via the OpenAI **Responses API** (/responses), NOT chat/completions.
No live API calls — env is monkeypatched and the OpenAI client is faked.
"""
import json
from queue import Queue

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
    monkeypatch.setenv("OPENAI_US_WEST_2_BASE_URL", "https://w2/openai/v1")
    assert prober._openai_base_url("us-east-1") == "https://e1/openai/v1"
    assert prober._openai_base_url("us-east-2") == "https://e2/openai/v1"
    assert prober._openai_base_url("us-west-2") == "https://w2/openai/v1"


def test_openai_parts_1p():
    region, actual = prober._openai_parts("openai:1p:gpt-5.4")
    assert region == "1p"
    assert actual == "gpt-5.4"


def test_openai_1p_base_url_default(monkeypatch):
    monkeypatch.delenv("OPENAI_1P_BASE_URL", raising=False)
    assert prober._openai_base_url("1p") == "https://api.openai.com/v1"


def test_openai_1p_base_url_override(monkeypatch):
    monkeypatch.setenv("OPENAI_1P_BASE_URL", "https://proxy.example/v1")
    assert prober._openai_base_url("1p") == "https://proxy.example/v1"


def test_openai_stop_reason():
    assert prober._openai_stop_reason("completed", None) == "end_turn"
    assert prober._openai_stop_reason("incomplete", "max_output_tokens") == "max_tokens"
    assert prober._openai_stop_reason("incomplete", "content_filter") == "content_filtered"
    assert prober._openai_stop_reason("incomplete", "weird") == "weird"
    assert prober._openai_stop_reason("incomplete", None) == "incomplete"


def test_register_openai_models_per_region_availability(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)  # isolate Mantle tests from 1P path
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setenv("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1")
    monkeypatch.setenv("OPENAI_US_WEST_2_BASE_URL", "https://w2/openai/v1")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_54_MODEL_ID", "openai.gpt-5.4")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_55_MODEL_ID", "openai.gpt-5.5")
    prober._register_openai_models()
    openai_keys = sorted(k for k in prober.AVAILABLE_MODELS if k.startswith("openai:"))
    # gpt-5.4 in e1/e2/w2 (3) + gpt-5.5 in e1/e2 (2) = 5; gpt-5.5 NOT in us-west-2.
    assert openai_keys == [
        "openai:us-east-1:openai.gpt-5.4",
        "openai:us-east-1:openai.gpt-5.5",
        "openai:us-east-2:openai.gpt-5.4",
        "openai:us-east-2:openai.gpt-5.5",
        "openai:us-west-2:openai.gpt-5.4",
    ]
    assert prober.AVAILABLE_MODELS["openai:us-west-2:openai.gpt-5.4"] == "OpenAI GPT 5.4 (us-west-2)"
    assert "openai:us-west-2:openai.gpt-5.5" not in prober.AVAILABLE_MODELS


def test_register_openai_models_skips_without_key(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)  # isolate Mantle tests from 1P path
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = len(prober.AVAILABLE_MODELS)
    prober._register_openai_models()
    assert len(prober.AVAILABLE_MODELS) == before


def test_register_openai_models_partial_skip(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)  # isolate Mantle tests from 1P path
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.delenv("OPENAI_US_EAST_2_BASE_URL", raising=False)
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_54_MODEL_ID", "openai.gpt-5.4")
    monkeypatch.delenv("BEDROCK_OPENAI_GPT_55_MODEL_ID", raising=False)
    prober._register_openai_models()
    keys = sorted(k for k in prober.AVAILABLE_MODELS if k.startswith("openai:"))
    # gpt-5.5 model-id absent → skipped; us-east-2 base-url absent → skipped.
    assert keys == ["openai:us-east-1:openai.gpt-5.4"]


def test_register_openai_1p_models(monkeypatch):
    """1P는 Mantle 키(OPENAI_API_KEY) 없이도 OPENAI_1P_API_KEY만으로 독립 등록."""
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # Mantle off — 1P is independent
    monkeypatch.setenv("OPENAI_1P_API_KEY", "sk-proj-fake")
    monkeypatch.setenv("OPENAI_1P_GPT_54_MODEL_ID", "gpt-5.4")
    monkeypatch.setenv("OPENAI_1P_GPT_55_MODEL_ID", "gpt-5.5")
    prober._register_openai_models()
    keys = sorted(k for k in prober.AVAILABLE_MODELS if k.startswith("openai:1p:"))
    assert keys == ["openai:1p:gpt-5.4", "openai:1p:gpt-5.5"]
    assert prober.AVAILABLE_MODELS["openai:1p:gpt-5.4"] == "OpenAI GPT 5.4 (1P)"
    assert prober.AVAILABLE_MODELS["openai:1p:gpt-5.5"] == "OpenAI GPT 5.5 (1P)"


def test_register_openai_1p_skips_without_key(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_1P_GPT_54_MODEL_ID", "gpt-5.4")  # id present but no key → skip
    prober._register_openai_models()
    assert not [k for k in prober.AVAILABLE_MODELS if k.startswith("openai:1p:")]


# --- Responses API event mocks -------------------------------------------

class _Usage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Incomplete:
    def __init__(self, reason):
        self.reason = reason


class _Resp:
    def __init__(self, input_tokens, output_tokens, status="completed", reason=None):
        self.usage = _Usage(input_tokens, output_tokens)
        self.status = status
        self.incomplete_details = _Incomplete(reason) if reason is not None else None


class _Ev:
    def __init__(self, type_, delta=None, response=None):
        self.type = type_
        self.delta = delta
        self.response = response


class _FakeSession:
    def add(self, *a, **k):
        pass

    def commit(self, *a, **k):
        pass

    def refresh(self, obj, *a, **k):
        from datetime import datetime, timezone
        if getattr(obj, "id", None) is None:
            obj.id = 1
        if getattr(obj, "timestamp", None) is None:
            obj.timestamp = datetime.now(timezone.utc)


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _parse(ev):
    etype = ev.split("event: ", 1)[1].split("\n", 1)[0]
    body = json.loads(ev.split("data: ", 1)[1].rstrip("\n"))
    return etype, body


def _install_fake_openai(monkeypatch, events):
    """Fake an OpenAI client whose responses.create() yields the given Responses events.

    Asserts the call uses the Responses-API shape (input + max_output_tokens + stream),
    NOT the chat/completions shape (messages) — guards against regressing to chat.
    """
    class _FakeResponses:
        def create(self, **kwargs):
            assert kwargs.get("stream") is True
            assert "max_output_tokens" in kwargs
            assert "input" in kwargs
            assert "messages" not in kwargs
            assert "temperature" not in kwargs  # reasoning models reject it
            return iter(events)

    class _FakeClient:
        responses = _FakeResponses()

    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeClient())


def test_openai_probe_streams_and_persists(monkeypatch):
    events = [
        _Ev("response.created"),
        _Ev("response.output_text.delta", delta="Hello"),
        _Ev("response.output_text.delta", delta=" world"),
        _Ev("response.completed", response=_Resp(12, 5, "completed")),
    ]
    _install_fake_openai(monkeypatch, events)
    q: Queue = Queue()
    prober._probe_single_model(
        client=None,
        model_id="openai:us-east-1:openai.gpt-5.4",
        model_name="OpenAI GPT 5.4 (us-east-1)",
        prompt="hi",
        temperature=0.1,
        max_tokens=64,
        iteration=1,
        event_queue=q,
        run_id=1,
        db=_FakeSession(),
    )
    parsed = [_parse(e) for e in _drain(q)]
    types = [t for t, _ in parsed]
    assert "ttft" in types
    assert types.count("token") == 2
    result = next(b for t, b in parsed if t == "result")
    assert result["status"] == "success"
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 5
    assert result["output_text"] == "Hello world"
    assert result["stop_reason"] == "end_turn"
    assert result["ttft_ms"] is not None
    assert result["server_latency_ms"] is None


def test_openai_probe_incomplete_maps_max_tokens(monkeypatch):
    events = [
        _Ev("response.output_text.delta", delta="partial"),
        _Ev("response.incomplete", response=_Resp(10, 64, "incomplete", "max_output_tokens")),
    ]
    _install_fake_openai(monkeypatch, events)
    q: Queue = Queue()
    prober._probe_single_model(
        client=None,
        model_id="openai:us-east-1:openai.gpt-5.5",
        model_name="OpenAI GPT 5.5 (us-east-1)",
        prompt="hi",
        temperature=0.1,
        max_tokens=64,
        iteration=1,
        event_queue=q,
        run_id=1,
        db=_FakeSession(),
    )
    result = next(b for t, b in (_parse(e) for e in _drain(q)) if t == "result")
    assert result["status"] == "success"
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 64
    assert result["stop_reason"] == "max_tokens"


def test_openai_1p_probe_streams(monkeypatch):
    """1P key (openai:1p:*) — base_url이 api.openai.com으로 resolve되고 정상 프로브."""
    events = [
        _Ev("response.output_text.delta", delta="ok"),
        _Ev("response.completed", response=_Resp(3, 1, "completed")),
    ]
    _install_fake_openai(monkeypatch, events)
    q: Queue = Queue()
    prober._probe_single_model(
        client=None,
        model_id="openai:1p:gpt-5.5",
        model_name="OpenAI GPT 5.5 (1P)",
        prompt="hi",
        temperature=0.1,
        max_tokens=64,
        iteration=1,
        event_queue=q,
        run_id=1,
        db=_FakeSession(),
    )
    result = next(b for t, b in (_parse(e) for e in _drain(q)) if t == "result")
    assert result["status"] == "success"
    assert result["output_text"] == "ok"
    assert result["stop_reason"] == "end_turn"


def test_openai_compare_emits_result(monkeypatch):
    events = [
        _Ev("response.output_text.delta", delta="Hi"),
        _Ev("response.completed", response=_Resp(3, 2, "completed")),
    ]
    _install_fake_openai(monkeypatch, events)
    q: Queue = Queue()
    prober._compare_single_model(
        model_id="openai:us-east-1:openai.gpt-5.4",
        prompt="hi",
        max_tokens=64,
        temperature=0.1,
        event_queue=q,
    )
    parsed = [_parse(e) for e in _drain(q)]
    types = [t for t, _ in parsed]
    assert "ttft" in types
    assert types.count("token") == 1
    result = next(b for t, b in parsed if t == "result")
    assert result["status"] == "success"
    assert result["input_tokens"] == 3
    assert result["output_tokens"] == 2
    assert result["output_text"] == "Hi"
