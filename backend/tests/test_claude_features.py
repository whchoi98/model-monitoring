"""Claude API Features 검증 엔진 — 카탈로그·판정·전송기 순수 로직 테스트 (v2.23.0)."""

import pytest

from claude_features import catalog, engine, transports as T


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
