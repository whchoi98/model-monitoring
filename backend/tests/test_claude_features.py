"""Claude API Features 검증 엔진 — 카탈로그·판정·전송기 순수 로직 테스트 (v2.23.0)."""

import json

import pytest

from claude_features import catalog, engine, probes as P, transports as T, runner as R


def test_surfaces_and_models():
    assert catalog.SURFACES == ["cp", "mantle", "bedrock_messages", "bedrock_invoke", "bedrock_converse"]
    keys = [m["key"] for m in catalog.MODELS]
    assert keys == ["fable-5-1", "fable-5", "opus-5-5", "opus-5", "sonnet-5"]
    assert catalog.MODEL_KEYS == keys
    assert catalog.model_id_for("cp", "fable-5-1") == "claude-fable-5-1"
    assert catalog.model_id_for("mantle", "fable-5-1") is None  # US GovCloud only
    assert catalog.model_id_for("mantle", "opus-5") == "anthropic.claude-opus-5"
    assert catalog.model_id_for("bedrock_messages", "sonnet-5") == "global.anthropic.claude-sonnet-5"
    assert catalog.model_id_for("bedrock_invoke", "sonnet-5") == "global.anthropic.claude-sonnet-5"
    assert catalog.model_id_for("bedrock_converse", "sonnet-5") == "global.anthropic.claude-sonnet-5"
    # Opus 5.5 (2026-09-23) — Mantle /anthropic us-east-1이 서빙(200 실측) → mantle id 있음, Bedrock 3열은 같은 global CRIS 프로파일
    assert catalog.model_label("opus-5-5") == "Claude Opus 5.5"
    assert catalog.model_id_for("cp", "opus-5-5") == "claude-opus-5-5"
    assert catalog.model_id_for("mantle", "opus-5-5") == "anthropic.claude-opus-5-5"
    for s in ("bedrock_messages", "bedrock_invoke", "bedrock_converse"):
        assert catalog.model_id_for(s, "opus-5-5") == "global.anthropic.claude-opus-5-5"
    # 접두 충돌 가드: opus-5 행이 5.5 id로 바뀌지 않았는지
    assert catalog.model_id_for("cp", "opus-5") == "claude-opus-5"
    assert catalog.model_id_for("bedrock_converse", "opus-5") == "global.anthropic.claude-opus-5"


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


def test_tool_choice_auto_for_opus_55_all_id_forms():
    # Opus 5.5는 forced tool_choice(tool/any)를 400으로 거부 → 세 id 형태(cp/mantle/bedrock) 모두 auto + 프롬프트 지시
    for mid in ("claude-opus-5-5", "anthropic.claude-opus-5-5", "global.anthropic.claude-opus-5-5"):
        assert P._tool_choice(mid, "echo") == {"type": "auto"}, mid
    # opus-5는 여전히 강제 (substring 마커 "opus-5-5"가 opus-5 id에 걸리지 않음)
    for mid in ("claude-opus-5", "anthropic.claude-opus-5", "global.anthropic.claude-opus-5"):
        assert P._tool_choice(mid, "echo") == {"type": "tool", "name": "echo"}, mid


def test_converse_tool_choice_auto_for_opus_55():
    from claude_features.transports import NormalizedResponse
    seen = {}

    class _ConvT:
        surface = "bedrock_converse"
        routes = frozenset({"converse", "count_tokens"})

        def converse(self, model_id, stream=False, **kw):
            seen[model_id] = kw["toolConfig"]["toolChoice"]
            return NormalizedResponse(content=[{"type": "tool_use", "name": "echo", "input": {"text": P.CANARY}}], stop_reason="tool_use")

    for probe in (P.probe_tool_use, P.probe_strict_tool_use):
        seen.clear()
        assert probe(_ConvT(), "global.anthropic.claude-opus-5-5", "opus-5-5")[0] is True
        assert probe(_ConvT(), "global.anthropic.claude-opus-5", "opus-5")[0] is True
        assert seen == {"global.anthropic.claude-opus-5-5": {"auto": {}}, "global.anthropic.claude-opus-5": {"tool": {"name": "echo"}}}


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


@pytest.mark.parametrize("surface,expected", [
    ("cp", "fallback-credit-2026-07-01"),
    ("mantle", "fallback-credit-2026-06-01"),
    ("bedrock_messages", "fallback-credit-2026-06-01"),
    ("bedrock_invoke", "fallback-credit-2026-06-01"),
    ("bedrock_converse", "fallback-credit-2026-06-01"),
])
def test_fallback_credit_beta_name_per_surface(surface, expected):
    """fallback_credit beta 이름은 CP만 07-01, Bedrock 3경로와 Mantle은 06-01 (v2.28.0).

    Mantle에 CP 이름(07-01)을 보내면 400 "Unexpected value(s) ... for the anthropic-beta header"로
    모든 모델이 거짓 드리프트가 됐다 — 2026-09-23 라이브: Mantle us-east-1은 06-01에 200(end_turn).
    """
    from claude_features.transports import NormalizedResponse

    resp = NormalizedResponse(content=[{"type": "text", "text": "pong"}], stop_reason="end_turn")
    sent = []

    class _T:
        routes = frozenset({"messages"})

        def messages(self, model_id, body, betas=(), stream=False):
            sent.append(list(betas))
            return resp

        def converse(self, model_id, stream=False, **kw):
            sent.append(kw["additionalModelRequestFields"]["anthropic_beta"])
            return resp

    t = _T()
    t.surface = surface
    ok, ev = P.probe_fallback_credit(t, "anthropic.claude-opus-5", "opus-5")
    assert ok is True and ev["verification"] == "acceptance" and ev["stop_reason"] == "end_turn"
    assert sent == [[expected]]
    req = ev["request"]["additionalModelRequestFields"] if surface == "bedrock_converse" else ev["request"]
    assert req["anthropic_beta"] == [expected]  # 증거 모달의 요청 스냅샷도 실제로 보낸 이름을 보여 준다


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
    assert P._advisor_model("opus-5-5") == "claude-opus-5-5"  # 자기 페어링 (CP 실측 supported, 2026-09-23)


def test_advisor_pairing_covers_every_catalog_model():
    # 빠진 키는 _advisor_model KeyError → run_probe가 advisor_tool 셀을 broken으로 분류한다 (모델 추가 시 회귀 가드)
    assert set(P._ADVISOR_FOR) == set(catalog.MODEL_KEYS)


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
    assert total == 39 * 5 * 5  # feature × surface × model (975, v2.28.0~ — Opus 5.5 추가 전 780)
    # pre-decided 162 = Mantle Fable 5.1 (39) + Converse-inexpressible 17 features × 5 models (85)
    #                 + context_window_1m skipped on mantle/messages/invoke/converse (4 × 5 − 1 overlap = 19)
    #                 + data_residency not_applicable by doc on mantle/messages/invoke/converse (4 × 5 − 1 overlap = 19)
    assert (len(jobs), len(decided)) == (813, 162)
    # Opus 5.5 몫 = 39 × 5 = 195셀 (프로브 170 + 사전판정 25) — Mantle에서 서빙되므로 Mantle 열도 프로브 대상
    o_jobs = [j for j in jobs if j["model_key"] == "opus-5-5"]
    o_dec = [d for d in decided if d["model_key"] == "opus-5-5"]
    assert (len(o_jobs), len(o_dec)) == (170, 25)
    assert sum(1 for j in o_jobs if j["surface"] == "mantle") == 37  # 39 − context_window_1m − data_residency


def test_data_residency_is_not_applicable_on_bedrock_by_doc():
    # 공식 문서: Bedrock은 엔드포인트/추론 프로파일이 추론 리전을 결정 → inference_geo "비적용" (미지원이 아님)
    for s in ("mantle", "bedrock_messages", "bedrock_invoke", "bedrock_converse"):
        assert catalog.is_applicable("data_residency", s, "opus-5") == (False, "not_applicable")
        assert "inference_geo" in catalog.na_reason("data_residency", s, "opus-5")
    assert catalog.is_applicable("data_residency", "cp", "opus-5") == (True, None)
    assert catalog.na_reason("data_residency", "cp", "opus-5") == ""


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


def test_build_latest_payload_computes_changes_and_drift(monkeypatch):
    import importlib
    from types import SimpleNamespace as NS

    # routers.features → auth는 import 시점에 JWT_SECRET_KEY(32자 이상)를 요구한다.
    # 깨끗한 셀(예: `make verify`)에서 env가 비어 있으면 RuntimeError로 죽으므로,
    # 모듈 import 전에 monkeypatch로 값을 주입하고 importlib로 지연 import한다.
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    build_latest_payload = importlib.import_module("routers.features").build_latest_payload
    run = NS(id=2, started_at=None, finished_at=None, totals={"supported": 1}, catalog_version="2026-09-05")
    rows = [NS(feature="a", surface="cp", model_key="opus-5", model_label="Opus 5", model_id="claude-opus-5",
               status="broken", documented="ga", verdict="drift", latency_ms=10.0, error_message=None)]
    prev = [NS(feature="a", surface="cp", model_key="opus-5", status="supported", latency_ms=9.0, error_message=None)]
    p = build_latest_payload(run, rows, prev, 1, running=False)
    assert p["run"]["id"] == 2 and p["previous_run_id"] == 1
    assert p["changes"] == [{"feature": "a", "surface": "cp", "model_key": "opus-5", "before": "supported", "after": "broken",
                             "kind": "measured", "model_label": "Opus 5"}]
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


CACHE_PROBES = (P.probe_automatic_prompt_caching, P.probe_prompt_caching_5m, P.probe_prompt_caching_1h)


def _cache_transport(usage, stop_reason="end_turn", stop_details=None):
    """캐시 프로브용 가짜 전송기 — 두 호출이 같은 usage/stop_reason을 낸다."""
    class _T:
        surface = "cp"
        routes = frozenset({"messages"})

        def messages(self, model_id, body, **kw):
            return T.NormalizedResponse(content=[{"type": "text", "text": "pong"}],
                                        top={"stop_details": stop_details}, usage=usage,
                                        stop_reason=stop_reason)
    return _T()


@pytest.mark.parametrize("probe", CACHE_PROBES, ids=lambda f: f.__name__)
def test_cache_probes_still_require_cache_read_evidence(probe):
    """캐시 3프로브 전부 2차 호출의 cache_read > 0을 요구한다 (컨트롤러 판정 R-b).

    캐시 *생성*만 있는 응답(cache_creation > 0 / ephemeral_1h > 0, read == 0)은 프롬프트가
    최소 길이를 넘겼다는 뜻일 뿐 재사용 증거가 아니다 — 종전에는 automatic/1h가 이걸로 통과해
    거부된 완료까지 초록으로 보였다.
    """
    creation_only = {"input_tokens": 14, "output_tokens": 4,
                     "cache_creation_input_tokens": 2203, "cache_read_input_tokens": 0,
                     "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 2203}}
    status, ev = probe(_cache_transport(creation_only), "claude-opus-5", "opus-5")
    assert status is False, f"{probe.__name__}: creation-only must not be supported"
    # 생성 수치는 보조 증거로 남아야 한다 (숨기지 않는다)
    assert ev["second_usage"]["cache_read_input_tokens"] == 0
    assert ev["stop_reason"] == ["end_turn", "end_turn"]


@pytest.mark.parametrize("probe", CACHE_PROBES, ids=lambda f: f.__name__)
def test_cache_probes_pass_on_real_second_call_read(probe):
    """2차 호출이 실제로 캐시를 읽으면 supported (양성 케이스)."""
    read = {"input_tokens": 14, "output_tokens": 4,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 2203,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    status, ev = probe(_cache_transport(read), "claude-opus-5", "opus-5")
    assert status is True, probe.__name__
    assert ev["second_usage"]["cache_read_input_tokens"] == 2203


@pytest.mark.parametrize("probe", CACHE_PROBES, ids=lambda f: f.__name__)
def test_cache_probes_persist_blocked_category_evidence(probe):
    """차단 시 inconclusive + stop_reason/stop_details를 증거로 남긴다 (컨트롤러 판정 R-a).

    트리아지를 가능하게 한 건 카테고리(refusal/cyber, refusal/reasoning_extraction)였다 —
    이유 문자열만으로는 복원되지 않으므로 두 호출의 stop_details를 보존해야 한다.
    """
    details = {"type": "refusal", "category": "reasoning_extraction", "explanation": "blocked"}
    creation_only = {"cache_creation_input_tokens": 2203, "cache_read_input_tokens": 0}
    status, ev = probe(_cache_transport(creation_only, "refusal", details), "claude-opus-5", "opus-5")
    assert status == "inconclusive", probe.__name__
    assert "refusal" in ev["reason"]
    assert ev["stop_reason"] == ["refusal", "refusal"]
    assert ev["stop_details"][0]["category"] == "reasoning_extraction"
    # 증거는 그대로 보존돼야 한다 (usage를 숨기지 않는다)
    assert ev["first_usage"]["cache_creation_input_tokens"] == 2203


# ==================================================================== v2.24.0 — Task 1: engine.classify 회귀 핀 (D8(b) 전제)
# 라이브 run #3(2026-09-06) 증거·parity-ref 샘플에서 뽑은 대표 오류 문자열. classify는 소문자 부분 문자열 매칭이므로
# D8(b)가 오류 문자열에 AWS operation 이름·빈 본문 표기를 덧붙일 때 새 문구에 마커("not found", "no route" 등)가
# 끼어들면 broken→unsupported로 뒤집힌다 — 이 핀이 그 회귀를 막는다.
_CLASSIFY_PINS = [
    # (id, 오류 문자열 그대로, 기대 판정)
    ("bedrock-count-tokens", "HTTP 400: ValidationException: The provided model doesn't support counting tokens.", "unsupported"),
    ("invoke-structured-extra-inputs", "HTTP 400: ValidationException: output_config.format: Extra inputs are not permitted", "unsupported"),
    ("mantle-data-retention", 'HTTP 400: {"type": "error", "request_id": "req_37kb", "error": {"type": "invalid_request_error", '
                              '"message": "data retention mode \'default\' is not available for this model"}}', "unsupported"),
    # mantle-beta-header: v2.28.0 전 프로브가 Mantle에 CP beta 이름(07-01)을 보냈을 때의 실제 오류. 프로브는 이제
    # Mantle에 06-01을 보낸다(2026-09-23 라이브 200) — 이 핀은 분류 규칙(beta 헤더 거부 = unsupported) 회귀용으로 남긴다.
    ("mantle-beta-header", 'HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
                           '"message": "Unexpected value(s) `fallback-credit-2026-07-01` for the `anthropic-beta` header"}}', "unsupported"),
    ("invoke-tool-type", "HTTP 400: ValidationException: tool type 'advisor_20260301' is not supported for this model", "unsupported"),
    ("cp-strict-extra-inputs", 'HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
                               '"message": "tools.0.custom.strict: Extra inputs are not permitted"}}', "unsupported"),
    ("cp-fallbacks-param", 'HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
                           '"message": "\'claude-sonnet-5\' does not support the `fallbacks` parameter."}, "request_id": "req_011Ce"}', "unsupported"),
    ("mantle-empty-404", "HTTP 404: ", "unsupported"),
    ("coral-unknown-operation", "HTTP 404: UnknownOperationException: route not available on this endpoint", "unsupported"),
    ("bedrock-messages-403-as-404", 'HTTP 404: route not served by the Anthropic-compatible handler (403 {"Message": "Authorization header is missing"})',
     "unsupported"),
    ("no-route-gate", "no route: bedrock_invoke has no HTTP endpoint for /v1/messages/batches", "unsupported"),
    ("thinking-enabled-rejected", 'HTTP 400: ValidationException: "thinking.type.enabled" is not supported for this model. '
                                  'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.', "unsupported"),
    ("mantle-model-does-not-exist", 'HTTP 404: {"type": "error", "error": {"type": "not_found_error", '
                                    '"message": "The model \'anthropic.claude-fable-5-1\' does not exist or you do not have access to it."}}', "unsupported"),
    ("with-fallback-tail", "HTTP 400: ValidationException: tools.0: Input tag 'computer_toolset_20260801' found using 'type' does not match "
                           "any of the expected tags: 'bash_20250124' | attempts=[{\"attempt\": \"computer_toolset_20260801\", \"result\": \"HTTP 400\"}]",
     "unsupported"),
    ("bedrock-request-not-valid", "HTTP 400: ValidationException: request is not valid", "unsupported"),
    ("bedrock-messages-403-auth", 'HTTP 403: {"Message": "Authorization header is missing"}', "broken"),
    ("empty-400", "HTTP 400: ", "broken"),
    ("rate-limit-429", 'HTTP 429: {"type": "error", "error": {"type": "rate_limit_error", "message": "Too many requests"}}', "broken"),
    ("api-error-500", 'HTTP 500: {"type":"error","error":{"type":"api_error","message":"Internal server error"}}', "broken"),
    ("access-denied", "HTTP 403: AccessDeniedException: User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock:InvokeModel",
     "broken"),
    ("effort-unknown-variant", "HTTP 400: ValidationException: unknown variant `ultra`, expected one of `low`, `medium`, `high`, `xhigh`, "
                               "`max`, `Unhandled` at line 1 column 125", "broken"),
    ("read-timeout", "ReadTimeout: HTTPSConnectionPool(host='aws-external-anthropic.us-east-2.api.aws', port=443): Read timed out.", "broken"),
    ("connect-error", "ConnectError: [Errno 111] Connection refused", "broken"),
    ("transport-init", "transport init: KeyError: 'ANTHROPIC_API_KEY'", "broken"),
]


@pytest.mark.parametrize("msg,expected", [(m, e) for _, m, e in _CLASSIFY_PINS], ids=[i for i, _, _ in _CLASSIFY_PINS])
def test_classify_pins_live_error_strings(msg, expected):
    assert engine.classify(msg) == expected


# D8(b) 이후 형식 ↔ 현재 형식 — 같은 판정이어야 한다 (operation 괄호 표기, "(empty body) METHOD path")
_CLASSIFY_FORMAT_PAIRS = [
    # (현재 형식, D8(b) 형식, 기대 판정)
    ("HTTP 400: ValidationException: The provided model doesn't support counting tokens.",
     "HTTP 400: ValidationException (CountTokens): The provided model doesn't support counting tokens.", "unsupported"),
    ("HTTP 400: ValidationException: output_config.format: Extra inputs are not permitted",
     "HTTP 400: ValidationException (InvokeModel): output_config.format: Extra inputs are not permitted", "unsupported"),
    ('HTTP 400: ValidationException: "thinking.type.enabled" is not supported for this model.',
     'HTTP 400: ValidationException (Converse): "thinking.type.enabled" is not supported for this model.', "unsupported"),
    ("HTTP 400: ValidationException: request is not valid",
     "HTTP 400: ValidationException (InvokeModelWithResponseStream): request is not valid", "unsupported"),
    ("HTTP 403: AccessDeniedException: User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock:InvokeModel",
     "HTTP 403: AccessDeniedException (InvokeModel): User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock:InvokeModel",
     "broken"),
    ("HTTP 429: ThrottlingException: Too many requests, please wait before trying again.",
     "HTTP 429: ThrottlingException (Converse): Too many requests, please wait before trying again.", "broken"),
    ("HTTP 404: ", "HTTP 404: (empty body) GET /v1/files", "unsupported"),
    ("HTTP 404: ", "HTTP 404: (empty body) POST /v1/messages/batches", "unsupported"),
    ("HTTP 404: ", "HTTP 404: (empty body) GET /v1/models/anthropic.claude-fable-5", "unsupported"),
    ("HTTP 405: ", "HTTP 405: (empty body) DELETE /v1/files/file_01", "unsupported"),
    ("HTTP 400: ", "HTTP 400: (empty body) POST /v1/messages", "broken"),
    ("HTTP 400: ", "HTTP 400: (empty body) POST /v1/messages (stream)", "broken"),
    ("HTTP 403: ", "HTTP 403: (empty body) GET /v1/models/anthropic.claude-fable-5", "broken"),
    ("HTTP 500: ", "HTTP 500: (empty body) POST /v1/messages", "broken"),
]


@pytest.mark.parametrize("before,after,expected", _CLASSIFY_FORMAT_PAIRS)
def test_classify_unchanged_by_d8b_error_context(before, after, expected):
    assert engine.classify(before) == expected
    assert engine.classify(after) == expected


# ==================================================================== v2.24.0 — Task 2: D8(b) 오류 문맥

def test_client_error_keeps_boto_operation_name():
    """boto ClientError는 operation 이름을 str(exc)와 .operation_name에만 담는다 — Error.Message만 쓰면 탈락 (R6).

    라이브 run #3: `bedrock_invoke/token_counting`과 `bedrock_converse/token_counting`이 같은 문구라 CountTokens에서
    난 것인지 문자열만으로 구분 불가였다 (parity 샘플은 "CountTokens operation" 명시).
    """
    class E(Exception):
        response = {"Error": {"Code": "ValidationException", "Message": "The provided model doesn't support counting tokens."},
                    "ResponseMetadata": {"HTTPStatusCode": 400}}
        operation_name = "CountTokens"
    err = T._client_error(E("x"))
    assert str(err) == "HTTP 400: ValidationException (CountTokens): The provided model doesn't support counting tokens."
    assert err.status_code == 400
    assert engine.classify(str(err)) == "unsupported"

    class NoOp(Exception):
        response = {"Error": {"Code": "ThrottlingException", "Message": "slow down"}, "ResponseMetadata": {"HTTPStatusCode": 429}}
        operation_name = None
    assert str(T._client_error(NoOp("x"))) == "HTTP 429: ThrottlingException: slow down"


def test_http_empty_error_body_names_method_and_path(monkeypatch):
    """본문 없는 4xx는 'HTTP 404: '로 끝나 어느 라우트였는지 알 수 없었다 (라이브 run #3 Mantle files/batches/models) (R6)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()

    class _R:
        status_code = 404
        content = b""
        def json(self):
            raise ValueError("no body")

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError) as exc:
        t.request("GET", "/v1/files")
    assert str(exc.value) == "HTTP 404: (empty body) GET /v1/files"
    assert engine.classify(str(exc.value)) == "unsupported"  # 'http 404' 마커 유지

    _R.status_code = 500
    with pytest.raises(T.TransportError) as exc5:
        t.request("POST", "/v1/messages", json={"model": "m"})
    assert str(exc5.value) == "HTTP 500: (empty body) POST /v1/messages"
    assert engine.classify(str(exc5.value)) == "broken"


def test_http_stream_empty_error_body_is_labelled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(404, b"")))
    with pytest.raises(T.TransportError) as ei:
        t.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert str(ei.value) == "HTTP 404: (empty body) POST /v1/messages (stream)"
    # 본문이 있으면 그대로 (회귀 방지)
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(400, b'{"type":"error","error":{"message":"nope"}}')))
    with pytest.raises(T.TransportError) as ei2:
        t.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert str(ei2.value) == 'HTTP 400: {"type":"error","error":{"message":"nope"}}'


# ==================================================================== v2.24.0 — Task 3: D8(a) 실패 경로 요청 스냅샷

class _RecordingT(_FakeT):
    """실제 전송기처럼 호출 직전에 record_request를 부른다 — 실패 경로 스냅샷 회수 검증용."""

    def messages(self, model_id, body, betas=(), stream=False):
        payload = {**body, "model": model_id}
        if stream:
            payload["stream"] = True
        T.record_request(T._http_snapshot("POST", "/v1/messages", payload, betas, None, None))
        return super().messages(model_id, body, betas, stream)


def test_run_probe_transport_error_keeps_full_request_snapshot():
    """실패 셀도 요청 본문을 남긴다 — 라이브 run #3 unsupported 206셀 중 182셀(드리프트 25건 전부)이 {"model"}만 남겼다 (R1)."""
    t = _RecordingT(exc=T.TransportError(400, "data retention mode 'default' is not available for this model"))
    out = P.run_probe(P.PROBES["tool_use"], t, "claude-opus-5", "opus-5")
    assert out.status == "unsupported" and out.error.startswith("HTTP 400")
    req = out.evidence["request"]
    assert req["model"] == "claude-opus-5" and req["api"] == "POST /v1/messages"
    assert req["max_tokens"] == P._TOOL_MAX and req["messages"][0]["role"] == "user"
    assert req["tools"][0]["name"] == "echo" and req["tool_choice"] == {"type": "tool", "name": "echo"}


def test_run_probe_generic_exception_keeps_request_snapshot():
    t = _RecordingT(exc=RuntimeError("socket closed"))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.status == "broken" and out.error.startswith("RuntimeError: socket closed")
    assert out.evidence["request"]["api"] == "POST /v1/messages" and out.evidence["request"]["max_tokens"] == P._MAX


def test_run_probe_with_fallback_failure_records_last_attempt():
    """_with_fallback 최종 실패는 마지막 시도 본문이 남는다 (라이브 computer_use/mantle/fable-5는 attempts 문자열만 있었다)."""
    t = _RecordingT(exc=T.TransportError(400, "tools.0: Input tag 'x' found using 'type' does not match any of the expected tags"))
    out = P.run_probe(P.PROBES["computer_use"], t, "claude-opus-5", "opus-5")
    assert out.status == "unsupported" and "attempts=" in out.error
    assert out.evidence["request"]["tools"][0]["type"] == "computer_20251124"
    assert out.evidence["request"]["anthropic_beta"] == ["computer-use-2025-11-24"]
    assert len(t.calls) == 2


def test_run_probe_without_recorder_falls_back_to_model_only():
    """회귀 가드 — 구현 전에도 통과해야 한다. record_request를 부르지 않는 전송기(구형/가짜)는 종전처럼 {"model"}만 남긴다 — 하위 호환."""
    t = _FakeT(exc=T.TransportError(400, "thinking.type.enabled is not supported for this model"))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.evidence["request"] == {"model": "claude-opus-5"}


def test_run_probe_clears_stale_snapshot_from_previous_probe():
    """같은 워커 스레드의 직전 프로브 스냅샷이 호출 없는 프로브(route gate)에 새지 않아야 한다."""
    T.record_request({"api": "POST /v1/messages", "model": "stale", "messages": ["stale"]})
    t = _FakeT()
    t.surface, t.routes = "bedrock_invoke", frozenset({"messages", "count_tokens"})
    out = P.run_probe(P.PROBES["batch_processing"], t, "global.anthropic.claude-opus-5", "opus-5")
    assert out.status == "unsupported"
    assert out.evidence["request"] == {"model": "global.anthropic.claude-opus-5"}


def test_run_probe_success_setdefault_uses_transport_snapshot():
    """프로브가 request를 빠뜨려도 전송기 스냅샷으로 채운다 (critic 4-B, parity `_run` :81-82 동형)."""
    t = _RecordingT(resp=T.NormalizedResponse(content=[{"type": "text", "text": "pong"}]))

    def forgetful(t_, m, k):
        return bool(t_.messages(m, {"max_tokens": 4, "messages": []}).content), {}

    out = P.run_probe(forgetful, t, "claude-opus-5", "opus-5")
    assert out.status == "supported"
    assert out.evidence["request"] == {"model": "claude-opus-5", "api": "POST /v1/messages", "max_tokens": 4, "messages": []}


def test_last_request_is_thread_local():
    from concurrent.futures import ThreadPoolExecutor
    import time as _time

    def work(i):
        T.record_request({"model": f"m{i}"})
        _time.sleep(0.01)
        return T.last_request()["model"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(work, range(8))) == [f"m{i}" for i in range(8)]
    T.clear_last_request()
    assert T.last_request() is None


def test_transports_record_request_before_calling(monkeypatch):
    """모든 전송 경로가 호출 직전 record_request를 부른다 — InvokeModel/CountTokens/Converse/HTTP/no-route."""
    class _Down:
        def invoke_model(self, modelId, body):
            raise RuntimeError("down")
        def count_tokens(self, modelId, input):
            raise RuntimeError("down")
        def converse(self, modelId, **kw):
            raise RuntimeError("down")

    monkeypatch.setattr(T, "_boto_client", lambda region: _Down())
    inv = T.BedrockInvokeTransport(region="ap-northeast-2")
    with pytest.raises(RuntimeError):
        inv.messages("global.anthropic.claude-opus-5", {"max_tokens": 8, "messages": []}, betas=["b1"])
    rec = T.last_request()
    assert rec["api"] == "InvokeModel" and rec["model"] == "global.anthropic.claude-opus-5"
    assert rec["anthropic_version"] == "bedrock-2023-05-31" and rec["anthropic_beta"] == ["b1"] and rec["max_tokens"] == 8
    with pytest.raises(RuntimeError):
        inv.count_tokens("global.anthropic.claude-opus-5", {"max_tokens": 8, "messages": []})
    assert T.last_request()["api"] == "CountTokens" and "max_tokens" not in T.last_request()

    conv = T.BedrockConverseTransport(region="ap-northeast-2")
    with pytest.raises(RuntimeError):
        conv.converse("global.anthropic.claude-opus-5", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    assert T.last_request() == {"api": "Converse", "model": "global.anthropic.claude-opus-5",
                                "messages": [{"role": "user", "content": [{"text": "hi"}]}]}
    with pytest.raises(RuntimeError):
        conv.count_tokens_converse("global.anthropic.claude-opus-5", messages=[])
    assert T.last_request() == {"api": "CountTokens", "model": "global.anthropic.claude-opus-5", "messages": []}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    cp = T.CpTransport()

    class _R:
        status_code = 404
        content = b"{}"
        def json(self):
            return {"type": "error"}

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError):
        cp.request("POST", "/v1/files", files={"file": ("a.txt", b"x", "text/plain")})
    assert T.last_request()["api"] == "POST /v1/files" and T.last_request()["files"]["file"][0] == "a.txt"
    with pytest.raises(T.TransportError):
        cp.count_tokens("claude-opus-5", {"max_tokens": 8, "messages": []}, betas=["b2"])
    assert T.last_request() == {"api": "POST /v1/messages/count_tokens", "messages": [], "model": "claude-opus-5", "anthropic_beta": ["b2"]}
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(400, b'{"type":"error"}')))
    with pytest.raises(T.TransportError):
        cp.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert T.last_request()["stream"] is True and T.last_request()["api"] == "POST /v1/messages"

    # 라우트 없는 전송기의 base request()도 기록한다
    with pytest.raises(T.TransportError):
        T.Transport().request("GET", "/v1/models/x")
    assert T.last_request() == {"api": "GET /v1/models/x"}


# ==================================================================== v2.24.0 — Task 4: D8(c) api/note 통일 + D8(d) thinking usage

class _SeqT(_FakeT):
    """호출 순서대로 응답/예외를 내는 전송기 — 2회 호출 프로브(effort, data_residency, _with_fallback) 검증용."""

    def __init__(self, *steps):
        super().__init__()
        self.steps = list(steps)

    def messages(self, model_id, body, betas=(), stream=False):
        self.calls.append(("messages", body, tuple(betas), stream))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _text(text="pong", **kw):
    return T.NormalizedResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", **kw)


def test_request_snapshots_use_api_key_instead_of_path_endpoint_stream():
    """요청 스냅샷 메타는 `api`/`note` 두 키로 통일 — path/endpoint/stream 혼용 제거 (R7, parity `_req_snapshot` 관례).

    라이브 run #3 cp/fable-5-1: context_window_1m은 {"path": "/v1/models/…"}, models_api는 {"endpoint": "/v1/models/…"} —
    같은 GET을 두 키로 표기했다.
    """
    _, ev = P.probe_token_counting(_FakeT(), "claude-opus-5", "opus-5")
    assert ev["request"]["api"] == "count_tokens" and "endpoint" not in ev["request"]

    stream = T.NormalizedResponse(content=[{"type": "text", "text": "1,2"}], events=[
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "1,"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "2"}}])
    ok, ev = P.probe_streaming(_FakeT(resp=stream), "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "messages (stream)" and "stream" not in ev["request"]

    class _ModelsT(_FakeT):
        routes = frozenset({"messages", "models"})
        def request(self, method, path, json=None, betas=(), files=None, data=None):
            return 200, {"id": "claude-opus-5", "capabilities": {}, "max_input_tokens": 1_000_000}

    ok, ev = P.probe_context_window_1m(_ModelsT(), "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "GET /v1/models/claude-opus-5" and "path" not in ev["request"]
    ok, ev = P.probe_models_api(_ModelsT(), "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "GET /v1/models/claude-opus-5" and "endpoint" not in ev["request"]

    # 소스 수준 가드 — 옛 키가 되살아나지 않도록
    import inspect
    src = inspect.getsource(P)
    assert "endpoint=" not in src and "path=f" not in src


def test_multi_call_probes_explain_themselves_with_note():
    """2회 호출 프로브는 요청 스냅샷에 note로 방법론을 적는다 (parity `note=` 관례, R7)."""
    ev, _ = P._cache_evidence("m", {"max_tokens": 1}, _text(usage={"input_tokens": 1}), _text(usage={"cache_read_input_tokens": 9}))
    assert ev["request"]["note"] == "same request twice; cache judged on 2nd call usage"

    t = _SeqT(_text(usage={"output_tokens": 3}),
              T.TransportError(400, "output_config.effort: Input should be 'low', 'medium', 'high', 'xhigh' or 'max'"))
    ok, ev = P.probe_effort(t, "claude-opus-5", "opus-5")
    assert ok is True and ev["request"]["note"] == "2 calls: effort=low, then effort=ultra as negative control"
    assert ev["negative_control"].startswith("rejected:")

    t = _SeqT(_text(usage={"inference_geo": "us"}), T.TransportError(400, "inference_geo: Input should be 'us'"))
    ok, ev = P.probe_data_residency(t, "claude-opus-5", "opus-5")
    assert ok is True and ev["request"]["note"] == "2 calls: inference_geo=us, then inference_geo=mars as negative control"

    t = _SeqT(T.TransportError(400, "tools.0: Input tag 'computer_toolset_20260801' found using 'type' does not match any of the expected tags"),
              T.NormalizedResponse(content=[{"type": "tool_use", "name": "computer", "input": {"action": "screenshot"}}], stop_reason="tool_use"))
    ok, ev = P.probe_computer_use(t, "claude-opus-5", "opus-5")
    assert ok is True and ev["request"]["note"] == "fallback attempt: computer_20251124+beta"
    assert ev["attempts"][0]["result"].startswith("HTTP 400") and ev["attempts"][1]["result"] == "ok"


def test_batch_and_files_probes_name_their_route_sequence():
    class _RoutesT(_FakeT):
        routes = frozenset({"messages", "batches", "files"})
        def request(self, method, path, json=None, betas=(), files=None, data=None):
            self.calls.append((method, path))
            if path.startswith("/v1/messages/batches"):
                return 200, {"id": "msgbatch_1", "processing_status": "in_progress"}
            if path == "/v1/files":
                return 200, {"id": "file_1", "type": "file"}
            return 200, {"id": "file_1"}

    t = _RoutesT()
    ok, ev = P.probe_batch_processing(t, "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "POST /v1/messages/batches → GET → POST cancel"
    assert [m for m, _ in t.calls] == ["POST", "GET", "POST"]
    t = _RoutesT()
    ok, ev = P.probe_files_api(t, "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "POST /v1/files → GET → DELETE" and ev["deleted"] is True
    assert [m for m, _ in t.calls] == ["POST", "GET", "DELETE"]


def test_thinking_probes_store_usage():
    """thinking 증거에 usage 전체를 남긴다 — Bedrock Fable 5.1은 요약 텍스트가 비어 thinking_tokens가 유일한 수치 증거 (R10).

    필드명(`output_tokens_details.thinking_tokens`)은 공식 문서 미기재라 숫자만 뽑지 않고 usage 전체를 저장한다
    (캐싱 프로브 `first_usage`/`second_usage`와 같은 방식).
    """
    usage = {"input_tokens": 20, "output_tokens": 15, "output_tokens_details": {"thinking_tokens": 11}}
    resp = T.NormalizedResponse(content=[{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "107"}],
                                usage=usage)
    ok, ev = P.probe_adaptive_thinking(_FakeT(resp=resp), "global.anthropic.claude-fable-5-1", "fable-5-1")
    assert ok is True and ev["usage"] == usage and ev["thinking_signed"] is True and ev["thinking_chars"] == 0
    ok, ev = P.probe_extended_thinking(_FakeT(resp=resp), "claude-opus-5", "opus-5")
    assert ok is True and ev["usage"] == usage


# ==================================================================== v2.24.0 — Task 5: D3 backend changes[].kind

def test_change_kind_covers_all_four_predecided_combinations():
    assert engine.change_kind(False, False) == "measured"
    assert engine.change_kind(True, False) == "catalog"
    assert engine.change_kind(False, True) == "catalog"
    assert engine.change_kind(True, True) == "catalog"


def test_change_kind_new_cell_is_catalog_and_annotate_passes_before_missing():
    """직전 런에 없던 셀(before None)은 카탈로그 변경으로만 생길 수 있다 (RUL-11)."""
    assert engine.change_kind(False, False, before_missing=True) == "catalog"
    assert engine.change_kind(False, True, before_missing=True) == "catalog"
    assert engine.change_kind(True, False, before_missing=True) == "catalog"
    assert engine.change_kind(False, False, before_missing=False) == "measured"
    changes = engine.diff_runs(
        {("dr", "bedrock_converse", "opus-5"): "unsupported", ("x", "cp", "opus-5"): "supported"},
        {("dr", "bedrock_converse", "opus-5"): "not_applicable", ("new", "cp", "opus-5"): "supported", ("x", "cp", "opus-5"): "broken"})
    tagged = engine.annotate_change_kinds(changes, prev_predecided=set(), cur_predecided={("dr", "bedrock_converse", "opus-5")})
    # sorted(cur) 순서: dr → new → x
    assert [(c["feature"], c["kind"]) for c in tagged] == [("dr", "catalog"), ("new", "catalog"), ("x", "measured")]
    assert tagged[0]["before"] == "unsupported" and tagged[0]["after"] == "not_applicable"
    assert tagged[1]["before"] is None
    assert "kind" not in changes[0]  # diff_runs 자체는 그대로


def test_build_latest_payload_tags_catalog_rule_changes(monkeypatch):
    """run #2→#3 data_residency 15건: documented도 catalog_version도 그대로였고 latency만 1180ms→null (R5 교정안)."""
    import importlib
    from types import SimpleNamespace as NS

    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    build_latest_payload = importlib.import_module("routers.features").build_latest_payload
    run = NS(id=3, started_at=None, finished_at=None, totals={}, catalog_version="2026-09-05")
    rows = [
        NS(feature="data_residency", surface="bedrock_converse", model_key="opus-5", model_label="Claude Opus 5",
           model_id="global.anthropic.claude-opus-5", status="not_applicable", documented="no", verdict="none",
           latency_ms=None, error_message=None),
        NS(feature="token_counting", surface="bedrock_invoke", model_key="opus-5", model_label="Claude Opus 5",
           model_id="global.anthropic.claude-opus-5", status="unsupported", documented="no", verdict="match",
           latency_ms=310.0, error_message=None),
        NS(feature="models_api", surface="cp", model_key="opus-5", model_label="Claude Opus 5",
           model_id="claude-opus-5", status="supported", documented="ga", verdict="match", latency_ms=120.0,
           error_message=None),
    ]
    prev = [
        NS(feature="data_residency", surface="bedrock_converse", model_key="opus-5", status="unsupported",
           latency_ms=1179.99, error_message=None),
        NS(feature="token_counting", surface="bedrock_invoke", model_key="opus-5", status="supported", latency_ms=290.0,
           error_message=None),
    ]
    p = build_latest_payload(run, rows, prev, 2, running=False)
    kinds = {(c["feature"], c["surface"]): c["kind"] for c in p["changes"]}
    assert kinds == {("data_residency", "bedrock_converse"): "catalog",
                     ("token_counting", "bedrock_invoke"): "measured",
                     ("models_api", "cp"): "catalog"}  # 신규 셀(before None)은 카탈로그 변경 (RUL-11)
    assert all(c["model_label"] == "Claude Opus 5" for c in p["changes"])


def test_build_latest_payload_null_latency_with_error_is_measured(monkeypatch):
    """latency 없는 행이라도 error_message가 있으면 프로브 실패(실측)다 — 사전판정 행은 error_message가 비어 있다.

    러너는 surface 전체의 transport 초기화가 실패하면 그 surface의 모든 job을
    ProbeOutcome("broken", error="transport init: …")로 기록한다(runner.py `_execute`).
    이 행은 latency_ms가 NULL이라 latency만으로는 사전판정과 구분되지 않고,
    자격 만료 같은 실측 장애가 "카탈로그 규칙 변경"으로 오태깅된다(복구 런도 반대 방향으로 같은 오태깅).
    """
    import importlib
    from types import SimpleNamespace as NS

    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    build_latest_payload = importlib.import_module("routers.features").build_latest_payload
    run = NS(id=4, started_at=None, finished_at=None, totals={}, catalog_version="2026-09-05")
    rows = [
        # 자격 누락으로 surface 전체가 broken — latency 없음 + error 있음 → 실측 변경
        NS(feature="tool_use", surface="cp", model_key="opus-5", model_label="Claude Opus 5", model_id="claude-opus-5",
           status="broken", documented="ga", verdict="drift", latency_ms=None,
           error_message="transport init: boom"),
        # 복구 런 방향: 직전 런이 broken(latency 없음 + error 있음)이었고 이번 런은 정상 프로브 → 실측 변경
        NS(feature="mcp_connector", surface="cp", model_key="opus-5", model_label="Claude Opus 5", model_id="claude-opus-5",
           status="supported", documented="ga", verdict="match", latency_ms=210.0, error_message=None),
        # 러너 사전판정 행: latency 없음 + error 없음 → 카탈로그 규칙 변경
        NS(feature="data_residency", surface="bedrock_converse", model_key="opus-5", model_label="Claude Opus 5",
           model_id="global.anthropic.claude-opus-5", status="not_applicable", documented="no", verdict="none",
           latency_ms=None, error_message=None),
    ]
    prev = [
        NS(feature="tool_use", surface="cp", model_key="opus-5", status="supported", latency_ms=140.0, error_message=None),
        NS(feature="mcp_connector", surface="cp", model_key="opus-5", status="broken", latency_ms=None,
           error_message="executor: boom"),
        NS(feature="data_residency", surface="bedrock_converse", model_key="opus-5", status="unsupported",
           latency_ms=1179.99, error_message=None),
    ]
    p = build_latest_payload(run, rows, prev, 3, running=False)
    assert {c["feature"]: c["kind"] for c in p["changes"]} == {
        "tool_use": "measured", "mcp_connector": "measured", "data_residency": "catalog"}


# ==================================================================== v2.24.0 — Task 15: catalog desc — acceptance 사유 (critic 4-D)

def test_acceptance_only_rows_state_why_in_desc():
    """critic 4-D (v2.24.0): server_side_fallback/compaction은 acceptance 행인데 desc에 사유가 없었다."""
    by_id = {f["id"]: f for f in catalog.FEATURES}
    for fid in ("server_side_fallback", "compaction"):
        f = by_id[fid]
        assert f["verification"] == "acceptance", fid
        assert "수락만 검증" in f["desc_ko"], fid
        assert "acceptance only" in f["desc_en"], fid
        assert "·" not in f["desc_ko"], fid  # 한글 UI 문장부호 규칙: 가운데 점 대신 쉼표
