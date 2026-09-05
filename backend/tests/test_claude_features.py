"""Claude API Features 검증 엔진 — 카탈로그·판정·전송기 순수 로직 테스트 (v2.23.0)."""

import json

import pytest

from claude_features import catalog, engine, probes as P, transports as T, runner as R


def test_surfaces_and_models():
    assert catalog.SURFACES == ["cp", "mantle", "bedrock_messages", "bedrock_invoke", "bedrock_converse"]
    keys = [m["key"] for m in catalog.MODELS]
    assert keys == ["fable-5-1", "fable-5", "opus-5", "sonnet-5"]
    assert catalog.model_id_for("cp", "fable-5-1") == "claude-fable-5-1"
    assert catalog.model_id_for("mantle", "fable-5-1") is None  # US GovCloud only
    assert catalog.model_id_for("mantle", "opus-5") == "anthropic.claude-opus-5"
    assert catalog.model_id_for("bedrock_messages", "sonnet-5") == "global.anthropic.claude-sonnet-5"
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
    assert catalog.is_applicable("context_window_1m", "bedrock_messages", "opus-5") == (False, "skipped")
    # extended thinking: adaptive-only models → probe still runs (negative check)
    assert catalog.is_applicable("extended_thinking", "cp", "fable-5") == (True, None)


def test_documented_defaults_from_overview():
    assert catalog.documented_for("web_search", "cp") == "ga"
    assert catalog.documented_for("web_search", "bedrock_invoke") == "no"
    assert catalog.documented_for("structured_outputs", "mantle") == "no"
    assert catalog.documented_for("compaction", "bedrock_converse") == "no"
    assert catalog.documented_for("server_side_fallback", "cp") == "unknown"
    # bedrock_messages는 InvokeModel 기대치를 상속하고 갈라지는 지점만 override
    assert catalog.documented_for("adaptive_thinking", "bedrock_messages") == "ga"
    assert catalog.documented_for("structured_outputs", "bedrock_messages") == "no"
    assert catalog.documented_for("token_counting", "bedrock_messages") == "no"
    assert catalog.documented_for("tool_search", "bedrock_messages") == "unknown"


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
    # bedrock-runtime /anthropic은 모르는 라우트도 명시적으로 답한다 → 전 라우트를 실측한다
    assert "batches" in T.BedrockMessagesTransport.routes
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
    monkeypatch.setattr("aws_bedrock_token_generator.provide_token", lambda region=None: "tok")
    assert isinstance(T.build_transport("bedrock_invoke"), T.BedrockInvokeTransport)
    assert isinstance(T.build_transport("bedrock_converse"), T.BedrockConverseTransport)
    assert isinstance(T.build_transport("bedrock_messages"), T.BedrockMessagesTransport)


def test_bedrock_messages_transport_headers_and_base(monkeypatch):
    """bedrock-runtime이 직접 호스팅하는 Anthropic Messages API — SigV4 대신 단기 bearer를 x-api-key로."""
    monkeypatch.setattr("aws_bedrock_token_generator.provide_token", lambda region=None: "tok")
    t = T.BedrockMessagesTransport(region="ap-northeast-2")
    assert t.surface == "bedrock_messages"
    assert t.base_url == "https://bedrock-runtime.ap-northeast-2.amazonaws.com/anthropic"
    h = t._headers(["beta-a"])
    assert h["x-api-key"] == "tok" and h["anthropic-version"] == "2023-06-01"
    assert h["anthropic-beta"] == "beta-a" and h["content-type"] == "application/json"


def test_http_request_maps_coral_unknown_operation_to_404(monkeypatch):
    """bedrock-runtime은 미지원 라우트에 HTTP 200 + coral UnknownOperationException 본문을 준다 (실측 2026-09-05).

    정규화하지 않으면 count_tokens 프로브가 200 본문을 성공으로 읽어 false-supported가 된다.
    """
    monkeypatch.setattr("aws_bedrock_token_generator.provide_token", lambda region=None: "tok")
    t = T.BedrockMessagesTransport(region="ap-northeast-2")

    class _R:
        status_code = 200
        content = b"{}"
        def json(self):
            return {"Output": {"__type": "com.amazon.coral.service#UnknownOperationException"}, "Version": "1.0"}

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError) as exc:
        t.count_tokens("global.anthropic.claude-sonnet-5", {"max_tokens": 8, "messages": []})
    assert exc.value.status_code == 404 and "UnknownOperation" in exc.value.message
    assert engine.classify(str(exc.value)) == "unsupported"


def test_bedrock_messages_403_on_non_messages_route_is_route_absence(monkeypatch):
    """`/v1/messages/batches`의 403 "Authorization header is missing"는 라우트 부재 (스모크 발견).

    x-api-key 인증이 없는 경로로 떨어졌다는 뜻 — 인증 사고가 아니다. 반대로 `/v1/messages`에서 같은 403이
    나면 그건 진짜 사고이므로 broken으로 남겨야 한다.
    """
    monkeypatch.setattr("aws_bedrock_token_generator.provide_token", lambda region=None: "tok")
    t = T.BedrockMessagesTransport(region="ap-northeast-2")

    class _R:
        status_code = 403
        content = b"{}"
        def json(self):
            return {"Message": "Authorization header is missing"}

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError) as batches:
        t.request("POST", "/v1/messages/batches", json={"requests": []})
    assert batches.value.status_code == 404
    assert engine.classify(str(batches.value)) == "unsupported"

    with pytest.raises(T.TransportError) as messages:
        t.request("POST", "/v1/messages", json={"model": "m"})
    assert messages.value.status_code == 403
    assert engine.classify(str(messages.value)) == "broken"

    # count_tokens의 라우트 부재는 coral UnknownOperationException이 이미 잡는다 →
    # 여기서 나는 403은 인증 문제이므로 403(broken)으로 남겨야 한다.
    with pytest.raises(T.TransportError) as count_tokens:
        t.request("POST", "/v1/messages/count_tokens", json={"model": "m"})
    assert count_tokens.value.status_code == 403
    assert engine.classify(str(count_tokens.value)) == "broken"


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


def test_probes_cover_every_catalog_feature():
    assert set(P.PROBES) == set(catalog.FEATURE_IDS)


def test_advisor_pairing():
    assert P._advisor_model("fable-5-1") == "claude-fable-5-1"
    assert P._advisor_model("sonnet-5") == "claude-opus-5"
    assert P._advisor_model("opus-5") == "claude-opus-5"


def test_http_request_drops_json_content_type_for_multipart(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    seen = {}

    class _R:
        status_code = 200
        content = b"{}"
        def json(self):
            return {"id": "file_1", "type": "file"}

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            seen.update(kw)
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    t.request("POST", "/v1/files", files={"file": ("a.txt", b"x", "text/plain")})
    assert "content-type" not in {k.lower() for k in seen["headers"]}


def test_has_thinking_evidence_accepts_signature_only_block():
    """Bedrock Fable 5.1은 요약 텍스트를 비우고 signature만 채운다 (스모크 발견)."""
    assert engine.has_thinking_evidence([{"type": "thinking", "thinking": "", "signature": "CAQS0gM"}])
    assert engine.has_thinking_evidence([{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "107"}])
    # 빈 블록·블록 없음은 증거가 아니다
    assert not engine.has_thinking_evidence([{"type": "thinking", "thinking": "", "signature": ""}])
    assert not engine.has_thinking_evidence([{"type": "text", "text": "107"}])
    assert not engine.has_thinking_evidence(None)


def test_citation_is_search_result_matches_both_notations():
    """Converse 인용에는 type이 없다 — '아무 인용이나 통과'하던 완화를 실측 shape로 대체 (스모크 발견)."""
    assert engine.citation_is_search_result({"type": "search_result_location", "search_result_index": 0})
    assert engine.citation_is_search_result({"location": {"searchResultLocation": {"searchResultIndex": 0}}})
    # 문서 출처 인용은 search_results 증거가 아니다
    assert not engine.citation_is_search_result({"type": "char_location", "document_index": 0})
    assert not engine.citation_is_search_result({"location": {"documentChar": {"start": 0}}})
    assert not engine.citation_is_search_result(None)


def test_effort_rejection_accepts_bedrock_variant_enumeration():
    """Bedrock은 필드 경로를 지우고 variant만 남긴다 — 'effort' 문자열만 찾으면 false-broken (스모크 발견)."""
    cp = "HTTP 400: output_config.effort: Input should be 'low', 'medium', 'high', 'xhigh' or 'max'"
    bedrock = ("HTTP 400: ValidationException: unknown variant `ultra`, expected one of "
               "`low`, `medium`, `high`, `xhigh`, `max`, `Unhandled` at line 1 column 125")
    assert engine.effort_rejection_names_param(cp, "ultra")
    assert engine.effort_rejection_names_param(bedrock, "ultra")
    # 파라미터를 지목하지 않는 400·빈 오류는 통과시키지 않는다
    assert not engine.effort_rejection_names_param("HTTP 400: ValidationException: request is not valid", "ultra")
    assert not engine.effort_rejection_names_param("HTTP 429: Too many requests", "ultra")
    assert not engine.effort_rejection_names_param(None, "ultra")


def test_agent_skills_without_container_is_inconclusive_not_broken():
    """컨테이너는 코드 실행의 부산물 — 모델이 도구를 안 부르면 inconclusive (스모크 발견)."""
    no_call = T.NormalizedResponse(content=[{"type": "text", "text": "pdf"}], top={})
    status, ev = P.probe_agent_skills(_FakeT(resp=no_call), "claude-sonnet-5", "sonnet-5")
    assert status == "inconclusive" and "did not" in ev["reason"]

    ran_no_container = T.NormalizedResponse(
        content=[{"type": "server_tool_use", "name": "bash_code_execution"}, {"type": "text", "text": "pdf"}], top={})
    status, _ = P.probe_agent_skills(_FakeT(resp=ran_no_container), "claude-sonnet-5", "sonnet-5")
    assert status is False  # 실행됐는데 컨테이너가 없다 → broken

    ok = T.NormalizedResponse(content=[{"type": "server_tool_use", "name": "bash_code_execution"}],
                              top={"container": {"id": "container_1", "skills": [{"skill_id": "pdf"}]}})
    status, ev = P.probe_agent_skills(_FakeT(resp=ok), "claude-sonnet-5", "sonnet-5")
    assert status is True and ev["container_skills"] == ["pdf"]


def test_http_request_serializes_dict_error_body(monkeypatch):
    """`json=` 파라미터가 json 모듈을 가려 4xx JSON 본문 직렬화가 터졌던 회귀 (스모크 발견)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    body = {"type": "error", "error": {"type": "not_found_error", "message": "model does not exist"}}

    class _R:
        status_code = 404
        content = b"{}"
        def json(self):
            return body

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError) as exc:
        t.request("POST", "/v1/messages", json={"model": "m"})
    assert "not_found_error" in exc.value.message
    assert engine.classify(str(exc.value)) == "unsupported"


def test_trim_replaces_bytes_and_truncates_long_strings():
    snap = P._req("m", {"blob": b"\x00" * 5000, "text": "x" * 500})
    assert snap["blob"] == "<5000 bytes>"
    assert snap["text"].startswith("x" * 200) and "(500 chars)" in snap["text"]


def test_run_probe_rejects_unknown_status_string():
    t = _FakeT()
    out = P.run_probe(lambda t_, m, k: ("not_aplicable", {}), t, "claude-opus-5", "opus-5")
    assert out.status == "broken" and "unknown status" in out.evidence["reason"]


def test_build_jobs_partitions_applicable_and_predecided():
    jobs, decided = R.build_jobs(["mantle", "bedrock_converse"], ["messages_basic", "bash_tool", "context_window_1m"], ["fable-5-1", "opus-5"])
    keys = {(j["feature"], j["surface"], j["model_key"]) for j in jobs}
    assert ("messages_basic", "mantle", "opus-5") in keys
    assert ("messages_basic", "mantle", "fable-5-1") not in keys  # GovCloud-only → decided
    na = {(d["feature"], d["surface"], d["model_key"]): d["status"] for d in decided}
    assert na[("messages_basic", "mantle", "fable-5-1")] == "not_applicable"
    assert na[("bash_tool", "bedrock_converse", "opus-5")] == "not_applicable"
    assert na[("context_window_1m", "mantle", "opus-5")] == "skipped"
    for j in jobs:
        assert j["documented"] in {"ga", "beta", "no", "unknown"} and j["model_id"]


def test_default_job_count_matches_spec_estimate():
    jobs, decided = R.build_jobs(None, None, None)
    total = len(jobs) + len(decided)
    assert total == 39 * 5 * 4  # feature × surface × model
    # pre-decided 122 = Mantle Fable 5.1 (39) + Converse-inexpressible 17 features × 4 models (68)
    #                 + context_window_1m skipped on mantle/messages/invoke/converse (4 × 4 − 1 overlap = 15)
    assert (len(jobs), len(decided)) == (658, 122)


def test_smoke_rows_always_carry_verdict_without_network():
    # mantle + fable-5-1 is pre-decided (not_applicable) → no transport is built, no network call
    rows = R.smoke(["mantle"], ["messages_basic"], ["fable-5-1"])
    assert len(rows) == 1
    assert rows[0]["status"] == "not_applicable" and rows[0]["verdict"] == "none"
    assert rows[0]["evidence"]["reason"]


def test_mark_failed_swallows_secondary_errors():
    class _DB:
        def rollback(self):
            raise RuntimeError("connection gone")

    R._mark_failed(_DB(), object, 1, RuntimeError("original"))  # must not raise


def test_build_latest_payload_computes_changes_and_drift():
    from types import SimpleNamespace as NS
    from routers.features import build_latest_payload
    run = NS(id=2, started_at=None, finished_at=None, totals={"supported": 1}, catalog_version="2026-09-05")
    rows = [NS(feature="a", surface="cp", model_key="opus-5", model_label="Opus 5", model_id="claude-opus-5",
               status="broken", documented="ga", verdict="drift", latency_ms=10.0)]
    prev = [NS(feature="a", surface="cp", model_key="opus-5", status="supported")]
    p = build_latest_payload(run, rows, prev, 1, running=False)
    assert p["run"]["id"] == 2 and p["previous_run_id"] == 1
    assert p["changes"] == [{"feature": "a", "surface": "cp", "model_key": "opus-5", "before": "supported", "after": "broken", "model_label": "Opus 5"}]
    assert p["drift"][0]["feature"] == "a" and p["results"][0]["verdict"] == "drift"


def test_classify_treats_model_level_unavailability_as_unsupported():
    """Mantle Fable 5는 Covered Model 데이터 보존 옵트인이 없으면 모델 자체를 거부한다 (전체 스윕 발견).

    "data retention mode 'default' is not available for this model"은 플랫폼이 모델 미제공을
    명시한 깨끗한 거부다 — broken(프로브/전송 결함)으로 기록하면 35행이 전부 오탐이 된다.
    """
    dr = ('HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
          '"message": "data retention mode \'default\' is not available for this model"}}')
    assert engine.classify(dr) == "unsupported"
    # 인증·타임아웃 등 진짜 장애는 여전히 broken이어야 한다 (마커가 넓어져 장애를 삼키면 안 된다)
    assert engine.classify("AccessDeniedException: not authorized") == "broken"
    assert engine.classify("ConnectError: connection refused") == "broken"


def test_blocked_stop_reason_flags_refusal_and_content_filter():
    """안전 거부·콘텐츠 필터로 차단된 완료는 usage 증거를 측정할 수 없다 (전체 스윕 발견).

    CP Fable 5(refusal/cyber)·Opus 5(refusal/reasoning_extraction)·Converse Fable 5(content_filtered)가
    캐시 패딩을 거부해 cache_read가 0으로 남았다 → broken 오탐. inconclusive로 분류해야 한다.
    """
    assert engine.blocked_stop_reason("refusal") == "refusal"
    assert engine.blocked_stop_reason("content_filtered") == "content_filtered"
    assert engine.blocked_stop_reason("guardrail_intervened") == "guardrail_intervened"
    # 두 응답 중 하나만 차단돼도 측정 불가
    assert engine.blocked_stop_reason("end_turn", "refusal") == "refusal"
    # 정상 완료·미지정은 차단이 아니다
    assert engine.blocked_stop_reason("end_turn", "max_tokens") is None
    assert engine.blocked_stop_reason(None) is None
    assert engine.blocked_stop_reason() is None


def test_cache_pad_is_benign_filler():
    """캐시 패딩은 안전 거부를 유발하는 표현을 담지 않아야 한다 (전체 스윕 발견).

    구 패딩이 자신을 'probe'로 설명하며 'model' 최소 길이를 언급해 Opus 5에서
    reasoning_extraction, Fable 5에서 cyber 거부를 유발했다.
    """
    low = P.CACHE_PAD.lower()
    for banned in ("probe", "model", "reverse", "extract", "jailbreak", "bypass"):
        assert banned not in low, f"CACHE_PAD must not mention {banned!r}"
    assert P.CACHE_PAD.isascii()


def test_cache_probes_report_blocked_completion_as_inconclusive(monkeypatch):
    """차단된 완료에서 캐시 프로브는 broken이 아니라 inconclusive를 반환한다 (전체 스윕 발견)."""
    blocked = T.NormalizedResponse(content=[], top={}, usage={"cache_creation_input_tokens": 2203,
                                                              "cache_read_input_tokens": 0},
                                   stop_reason="refusal")

    class _T:
        surface = "cp"
        routes = frozenset({"messages"})

        def messages(self, model_id, body, **kw):
            return blocked

    for probe in (P.probe_prompt_caching_5m, P.probe_prompt_caching_1h, P.probe_automatic_prompt_caching):
        status, ev = probe(_T(), "claude-opus-5", "opus-5")
        assert status == "inconclusive", probe.__name__
        assert "refusal" in ev["reason"]
        # 증거는 그대로 보존돼야 한다 (usage를 숨기지 않는다)
        assert ev["first_usage"]["cache_creation_input_tokens"] == 2203


def test_cache_probes_still_require_cache_read_evidence():
    """차단 가드가 증거 검사를 약화시키지 않는다 — 정상 완료인데 cache_read가 0이면 broken."""
    def _resp(usage):
        return T.NormalizedResponse(content=[{"type": "text", "text": "pong"}], top={}, usage=usage,
                                    stop_reason="end_turn")

    class _T:
        surface = "cp"
        routes = frozenset({"messages"})

        def __init__(self, usage):
            self._u = usage

        def messages(self, model_id, body, **kw):
            return _resp(self._u)

    no_read = {"cache_creation_input_tokens": 2203, "cache_read_input_tokens": 0}
    assert P.probe_prompt_caching_5m(_T(no_read), "claude-opus-5", "opus-5")[0] is False
    read = {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 2203}
    assert P.probe_prompt_caching_5m(_T(read), "claude-opus-5", "opus-5")[0] is True
