"""Claude API Features 검증 엔진 — 카탈로그·판정·전송기 순수 로직 테스트 (v2.23.0)."""

import json

import pytest

from claude_features import catalog, engine, probes as P, transports as T


def test_surfaces_and_models():
    assert catalog.SURFACES == ["cp", "mantle", "bedrock_invoke", "bedrock_converse"]
    keys = [m["key"] for m in catalog.MODELS]
    assert keys == ["fable-5-1", "fable-5", "opus-5", "sonnet-5"]
    assert catalog.model_id_for("cp", "fable-5-1") == "claude-fable-5-1"
    assert catalog.model_id_for("mantle", "fable-5-1") is None  # US GovCloud only
    assert catalog.model_id_for("mantle", "opus-5") == "anthropic.claude-opus-5"
    assert catalog.model_id_for("bedrock_invoke", "sonnet-5") == "global.anthropic.claude-sonnet-5"
    assert catalog.model_id_for("bedrock_converse", "sonnet-5") == "global.anthropic.claude-sonnet-5"


def test_feature_catalog_shape():
    assert len(catalog.FEATURES) == 39
    ids = catalog.FEATURE_IDS
    assert ids[:4] == ["messages_basic", "streaming", "system_prompt", "tool_use"]
    assert ids[-1] == "models_api"
    groups = {g["id"] for g in catalog.GROUPS}
    for f in catalog.FEATURES:
        assert f["group"] in groups
        assert f["doc_url"].startswith("https://platform.claude.com/")
        assert set(f["documented"]) == set(catalog.SURFACES)
        assert set(f["documented"].values()) <= {"ga", "beta", "no", "unknown"}
        assert f["verification"] in {"evidence", "acceptance", "capability", "negative"}
        for k in ("label_ko", "label_en", "desc_ko", "desc_en"):
            assert f[k]


def test_is_applicable_rules():
    ok, reason = catalog.is_applicable("messages_basic", "mantle", "fable-5-1")
    assert (ok, reason) == (False, "not_applicable")  # GovCloud-only
    assert catalog.is_applicable("messages_basic", "mantle", "fable-5") == (True, None)
    # Converse cannot express Anthropic-defined tools / top-level cache_control
    assert catalog.is_applicable("bash_tool", "bedrock_converse", "opus-5") == (False, "not_applicable")
    assert catalog.is_applicable("automatic_prompt_caching", "bedrock_converse", "opus-5") == (False, "not_applicable")
    # 1M capability only checkable on CP
    assert catalog.is_applicable("context_window_1m", "cp", "opus-5") == (True, None)
    assert catalog.is_applicable("context_window_1m", "mantle", "opus-5") == (False, "skipped")
    # extended thinking: adaptive-only models → probe still runs (negative check)
    assert catalog.is_applicable("extended_thinking", "cp", "fable-5") == (True, None)


def test_documented_defaults_from_overview():
    assert catalog.documented_for("web_search", "cp") == "ga"
    assert catalog.documented_for("web_search", "bedrock_invoke") == "no"
    assert catalog.documented_for("structured_outputs", "mantle") == "no"
    assert catalog.documented_for("compaction", "bedrock_converse") == "no"
    assert catalog.documented_for("server_side_fallback", "cp") == "unknown"


@pytest.mark.parametrize("documented,observed,expected", [
    ("ga", "supported", "match"), ("beta", "supported", "match"),
    ("no", "unsupported", "match"), ("ga", "unsupported", "drift"),
    ("beta", "broken", "drift"), ("no", "supported", "undocumented"),
    ("ga", "inconclusive", "none"), ("unknown", "supported", "none"),
    ("ga", "not_applicable", "none"), ("no", "broken", "none"),
])
def test_verdict(documented, observed, expected):
    assert engine.verdict(documented, observed) == expected


def test_aggregate_cell():
    assert engine.aggregate_cell(["supported", "supported"])["status"] == "supported"
    assert engine.aggregate_cell(["supported", "unsupported"])["status"] == "partial"
    assert engine.aggregate_cell(["supported", "broken"])["status"] == "broken"
    assert engine.aggregate_cell(["not_applicable", "skipped"])["status"] == "not_applicable"
    assert engine.aggregate_cell([])["status"] == "empty"
    assert engine.aggregate_cell(["supported", "inconclusive"])["counts"]["inconclusive"] == 1


def test_diff_runs_keys():
    prev = {("a", "cp", "opus-5"): "supported"}
    cur = {("a", "cp", "opus-5"): "broken", ("b", "cp", "opus-5"): "supported"}
    changes = engine.diff_runs(prev, cur)
    assert changes == [
        {"feature": "a", "surface": "cp", "model_key": "opus-5", "before": "supported", "after": "broken"},
        {"feature": "b", "surface": "cp", "model_key": "opus-5", "before": None, "after": "supported"},
    ]


def test_classify_extends_parity_markers():
    assert engine.classify("400: output_config.format: Extra inputs are not permitted") == "unsupported"
    assert engine.classify("tool_choice: type \"tool\" and \"any\" are not supported for this model.") == "unsupported"
    assert engine.classify("'claude-opus-5' does not support tool types: computer_20241022") == "unsupported"
    assert engine.classify("Unexpected value(s) `foo` for the `anthropic-beta` header") == "unsupported"
    assert engine.classify("AccessDeniedException: not authorized") == "broken"
    assert engine.classify("ReadTimeout") == "broken"


def test_block_helpers():
    blocks = [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "hi"}]
    assert engine.has_block(blocks, "thinking")
    assert engine.find_block(blocks, "text")["text"] == "hi"
    assert engine.find_block(blocks, "tool_use") is None
    assert engine.usage_int({"cache_read_input_tokens": 12}, "cache_read_input_tokens", "cacheReadInputTokens") == 12
    assert engine.usage_int({"cacheReadInputTokens": 5}, "cache_read_input_tokens", "cacheReadInputTokens") == 5
    assert engine.usage_int(None, "x") == 0


def test_invoke_body_strips_model_and_injects_version_and_betas():
    body = {"model": "x", "stream": True, "max_tokens": 16, "messages": []}
    out = T.invoke_body(body, ["beta-a", "beta-b"])
    assert "model" not in out and "stream" not in out
    assert out["anthropic_version"] == "bedrock-2023-05-31"
    assert out["anthropic_beta"] == ["beta-a", "beta-b"]
    assert T.invoke_body({"messages": []}, []).get("anthropic_beta") is None


def test_beta_header_joins_with_comma():
    assert T.beta_header([]) == {}
    assert T.beta_header(["a", "b"]) == {"anthropic-beta": "a,b"}


def test_parse_sse_extracts_json_events():
    text = 'event: message_start\ndata: {"type":"message_start"}\n\nevent: ping\ndata: {"type":"ping"}\n\ndata: [DONE]\n\n'
    evs = T.parse_sse(text)
    assert [e["type"] for e in evs] == ["message_start", "ping"]


def test_normalize_converse_maps_blocks_and_usage():
    resp = {
        "output": {"message": {"content": [
            {"text": "hello"},
            {"toolUse": {"toolUseId": "t1", "name": "echo", "input": {"text": "X"}}},
            {"reasoningContent": {"reasoningText": {"text": "hmm"}}},
            {"citationsContent": {"content": [{"text": "cited"}], "citations": [{"title": "d"}]}},
        ]}},
        "usage": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 3, "cacheWriteInputTokens": 7},
        "stopReason": "end_turn",
    }
    n = T.normalize_converse(resp)
    types = [b["type"] for b in n.content]
    assert types == ["text", "tool_use", "thinking", "text"]
    assert n.content[1]["input"] == {"text": "X"} and n.content[1]["name"] == "echo"
    assert n.content[3]["citations"] == [{"title": "d"}]
    assert n.usage == {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 7}
    assert n.stop_reason == "end_turn"


def test_normalize_anthropic_separates_top_level():
    obj = {"id": "m", "content": [{"type": "text", "text": "a"}], "usage": {"input_tokens": 1},
           "stop_reason": "end_turn", "container": {"id": "c1"}}
    n = T.normalize_anthropic(obj)
    assert n.top["container"] == {"id": "c1"} and "content" not in n.top
    assert n.stop_reason == "end_turn" and n.events == []


def test_routes_per_surface(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    assert "batches" in T.CpTransport().routes
    assert T.BedrockInvokeTransport.routes == frozenset({"messages", "count_tokens"})
    assert T.BedrockConverseTransport.routes == frozenset({"converse", "count_tokens"})


def test_assemble_stream_accumulates_tool_json_signature_and_usage():
    events = [
        {"type": "message_start", "message": {"id": "m1", "model": "x", "usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hm"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "echo", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"te'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": 'xt":"X"}'}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 7}},
    ]
    msg = T.assemble_stream(events)
    assert msg["content"][0] == {"type": "thinking", "thinking": "hm", "signature": "sig"}
    assert msg["content"][1]["input"] == {"text": "X"} and msg["content"][1]["name"] == "echo"
    assert msg["stop_reason"] == "tool_use" and msg["usage"] == {"input_tokens": 5, "output_tokens": 7}


def test_client_error_maps_botocore_shape():
    class E(Exception):
        response = {"Error": {"Code": "ValidationException", "Message": "bad"}, "ResponseMetadata": {"HTTPStatusCode": 400}}
    err = T._client_error(E("x"))
    assert err.status_code == 400 and str(err) == "HTTP 400: ValidationException: bad"

    class E2(Exception):
        response = {}
    err2 = T._client_error(E2("boom"))
    assert err2.status_code is None and "E2: boom" in str(err2)


class _FakeHttpStream:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _fake_httpx_client(resp):
    class _C:
        def __init__(self, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def stream(self, method, url, **kw):
            return resp
    return _C


def test_http_stream_raises_transport_error_on_400(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(400, b'{"type":"error","error":{"message":"nope"}}')))
    with pytest.raises(T.TransportError) as ei:
        t.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert ei.value.status_code == 400 and "nope" in str(ei.value)


def test_http_stream_assembles_events(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    sse = ('data: {"type":"message_start","message":{"usage":{"input_tokens":1}}}\n\n'
           'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
           'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"po"}}\n\n'
           'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ng"}}\n\n'
           'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n\n')
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(200, sse.encode())))
    n = t.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert n.content == [{"type": "text", "text": "pong"}] and n.stop_reason == "end_turn"
    assert len(n.events) == 5 and n.usage == {"input_tokens": 1, "output_tokens": 2}


def test_bedrock_invoke_messages_and_count_tokens_with_fake_client(monkeypatch):
    import io

    class _Fake:
        def __init__(self):
            self.calls = []
        def invoke_model(self, modelId, body):
            self.calls.append(("invoke", modelId, json.loads(body)))
            payload = {"content": [{"type": "text", "text": "pong"}], "usage": {"input_tokens": 3}, "stop_reason": "end_turn"}
            return {"body": io.BytesIO(json.dumps(payload).encode())}
        def invoke_model_with_response_stream(self, modelId, body):
            chunks = [{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                      {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}]
            return {"body": [{"chunk": {"bytes": json.dumps(c).encode()}} for c in chunks]}
        def count_tokens(self, modelId, input):
            self.calls.append(("count", modelId, input))
            return {"inputTokens": 9}

    monkeypatch.setattr(T, "_boto_client", lambda region: _Fake())
    t = T.BedrockInvokeTransport(region="ap-northeast-2")
    n = t.messages("global.anthropic.claude-opus-5", {"model": "ignored", "max_tokens": 8, "messages": []}, betas=["b1"])
    sent = t.client.calls[0][2]
    assert sent["anthropic_version"] == "bedrock-2023-05-31" and sent["anthropic_beta"] == ["b1"] and "model" not in sent
    assert n.content[0]["text"] == "pong"
    s = t.messages("global.anthropic.claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert s.content == [{"type": "text", "text": "hi"}] and len(s.events) == 2
    assert t.count_tokens("global.anthropic.claude-opus-5", {"max_tokens": 8, "messages": []}) == {"input_tokens": 9}
    assert "max_tokens" not in json.loads(t.client.calls[-1][2]["invokeModel"]["body"])


def test_bedrock_converse_stream_keeps_tool_use_and_reasoning(monkeypatch):
    class _Fake:
        def converse_stream(self, modelId, **kw):
            return {"stream": [
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"reasoningContent": {"text": "think"}}}},
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"reasoningContent": {"signature": "sig"}}}},
                {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": "po"}}},
                {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": "ng"}}},
                {"contentBlockStart": {"contentBlockIndex": 2, "start": {"toolUse": {"toolUseId": "t1", "name": "echo"}}}},
                {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"toolUse": {"input": '{"text":'}}}},
                {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"toolUse": {"input": '"X"}'}}}},
                {"messageStop": {"stopReason": "tool_use"}},
                {"metadata": {"usage": {"inputTokens": 4, "outputTokens": 6}}},
            ]}
        def count_tokens(self, modelId, input):
            return {"inputTokens": 11}

    monkeypatch.setattr(T, "_boto_client", lambda region: _Fake())
    t = T.BedrockConverseTransport(region="ap-northeast-2")
    n = t.converse("global.anthropic.claude-opus-5", stream=True, messages=[])
    assert [b["type"] for b in n.content] == ["thinking", "text", "tool_use"]
    assert n.content[0]["thinking"] == "think" and n.content[0]["signature"] == "sig"
    assert n.content[1]["text"] == "pong"
    assert n.content[2]["name"] == "echo" and n.content[2]["input"] == {"text": "X"}
    assert n.stop_reason == "tool_use" and n.usage["input_tokens"] == 4
    assert t.count_tokens_converse("global.anthropic.claude-opus-5", messages=[]) == {"input_tokens": 11}


def test_build_transport_dispatch(monkeypatch):
    monkeypatch.setattr(T, "_boto_client", lambda region: object())
    assert isinstance(T.build_transport("bedrock_invoke"), T.BedrockInvokeTransport)
    assert isinstance(T.build_transport("bedrock_converse"), T.BedrockConverseTransport)


def test_tiny_pdf_is_valid_pdf_containing_text():
    pdf = P._tiny_pdf("HELLO_7391")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"HELLO_7391" in pdf


def test_cache_pad_is_long_enough():
    # 최소 캐시 토큰(Sonnet 5 = 1,024)을 넉넉히 넘겨야 함 — 영문 4자≈1토큰 기준 1,500토큰 ≈ 6,000자
    assert len(P.CACHE_PAD) >= 6000


def test_tool_choice_respects_fable_51():
    assert P._tool_choice("claude-fable-5-1", "echo") == {"type": "auto"}
    assert P._tool_choice("anthropic.claude-opus-5", "echo") == {"type": "tool", "name": "echo"}


class _FakeT:
    surface = "cp"
    routes = frozenset({"messages", "count_tokens"})

    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def messages(self, model_id, body, betas=(), stream=False):
        self.calls.append(("messages", body, tuple(betas), stream))
        if self.exc:
            raise self.exc
        return self.resp

    def count_tokens(self, model_id, body, betas=()):
        return {"input_tokens": 42}


def test_run_probe_classifies_transport_error():
    from claude_features.transports import TransportError
    t = _FakeT(exc=TransportError(400, 'thinking.type.enabled is not supported for this model'))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.status == "unsupported" and out.error.startswith("HTTP 400")
    assert out.evidence["request"]["model"] == "claude-opus-5"


def test_run_probe_supported_and_evidence():
    from claude_features.transports import NormalizedResponse
    t = _FakeT(resp=NormalizedResponse(content=[{"type": "text", "text": "pong"}], usage={"input_tokens": 3}, stop_reason="end_turn"))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.status == "supported" and out.evidence["response_snippet"] == "pong"


def test_extended_thinking_rejection_is_not_applicable():
    from claude_features.transports import TransportError
    t = _FakeT(exc=TransportError(400, '"thinking.type.enabled" is not supported for this model. Use adaptive.'))
    out = P.run_probe(P.PROBES["extended_thinking"], t, "claude-fable-5", "fable-5")
    assert out.status == "not_applicable"


def test_route_less_endpoint_feature_is_unsupported_without_call():
    t = _FakeT()
    t.surface, t.routes = "bedrock_invoke", frozenset({"messages", "count_tokens"})
    out = P.run_probe(P.PROBES["batch_processing"], t, "global.anthropic.claude-opus-5", "opus-5")
    assert out.status == "unsupported"
    assert t.calls == [] and "no route" in out.evidence["reason"]
