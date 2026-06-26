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


def test_register_openai_models_partial_skip(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.delenv("OPENAI_US_EAST_2_BASE_URL", raising=False)
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_54_MODEL_ID", "openai.gpt-5.4")
    monkeypatch.delenv("BEDROCK_OPENAI_GPT_55_MODEL_ID", raising=False)
    prober._register_openai_models()
    keys = sorted(k for k in prober.AVAILABLE_MODELS if k.startswith("openai:"))
    # gpt-5.5 model-id absent → skipped; us-east-2 base-url absent → skipped.
    assert keys == ["openai:us-east-1:openai.gpt-5.4"]


import json
from queue import Queue


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content=None, finish_reason=None):
        self.delta = _Delta(content)
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Chunk:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


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


def _install_fake_openai(monkeypatch, chunks, calls=None):
    class _FakeCompletions:
        def create(self, **kwargs):
            if calls is not None:
                calls.append("mct" if "max_completion_tokens" in kwargs else "mt")
            assert kwargs["stream"] is True
            assert kwargs["stream_options"] == {"include_usage": True}
            return iter(chunks)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeClient())


def test_openai_probe_streams_and_persists(monkeypatch):
    chunks = [
        _Chunk([_Choice(content="Hello")]),
        _Chunk([_Choice(content=" world")]),
        _Chunk([_Choice(content=None, finish_reason="length")]),
        _Chunk([], usage=_Usage(prompt_tokens=12, completion_tokens=5)),
    ]
    _install_fake_openai(monkeypatch, chunks)
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
    events = [_parse(e) for e in _drain(q)]
    types = [t for t, _ in events]
    assert "ttft" in types
    assert types.count("token") == 2
    result = next(b for t, b in events if t == "result")
    assert result["status"] == "success"
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 5
    assert result["output_text"] == "Hello world"
    assert result["stop_reason"] == "max_tokens"
    assert result["ttft_ms"] is not None
    assert result["server_latency_ms"] is None


def test_openai_probe_falls_back_to_max_tokens(monkeypatch):
    chunks = [
        _Chunk([_Choice(content="x", finish_reason="stop")]),
        _Chunk([], usage=_Usage(1, 1)),
    ]
    calls = []

    class _FakeCompletions:
        def create(self, **kwargs):
            if "max_completion_tokens" in kwargs:
                calls.append("mct")
                raise Exception("Unsupported parameter: 'max_completion_tokens'")
            calls.append("mt")
            return iter(chunks)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeClient())
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
    assert calls == ["mct", "mt"]
    result = next(b for t, b in (_parse(e) for e in _drain(q)) if t == "result")
    assert result["status"] == "success"
    assert result["stop_reason"] == "end_turn"
