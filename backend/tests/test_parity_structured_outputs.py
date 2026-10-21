"""패리티 구조화 출력 프로브 (v2.34.0) — json_schema GA 형식, 판별 프롬프트, Converse, strict_tool_use.

AWS 블로그 "Structured outputs for Anthropic Claude models on Amazon Bedrock"(2026-10-19)와 Bedrock 사용자 가이드의
요청 형식을 고정하고, 서비스가 스키마나 strict를 조용히 무시한 응답을 supported로 판정하지 않는지 확인한다.
"""

import io
import json
from types import SimpleNamespace

import pytest

from parity import probes as P
from parity.catalog import FEATURE_IDS, is_applicable, supports_forced_tool_choice
from parity.engine import check_schema_keys, check_strict_tool_input, classify_error, json_object_keys


# ---------------------------------------------------------------------------
# 증거 검사
# ---------------------------------------------------------------------------

def test_json_object_keys():
    assert json_object_keys('{"name": "서울", "city": "서울"}') == ["city", "name"]
    assert json_object_keys('```json\n{"city": "서울"}\n```') == ["city"]
    assert json_object_keys('{"city":"서울특별시 충북') is None  # 512토큰 절단
    assert json_object_keys('["city"]') is None
    assert json_object_keys("") is None


@pytest.mark.parametrize("text, ok", [
    ('{"city": "서울"}', True),
    ('```json\n{"city":"서울"}\n```', True),
    ('{"name": "서울"}', False),                              # 스키마 무시 — 프롬프트의 키
    ('{"city": "서울", "country": "대한민국"}', False),        # 키 존재만 보던 check_json_object는 통과시켰다
    ('{"city":"서울특별시 충북혁신도시 진천', False),
    (None, False),
])
def test_check_schema_keys(text, ok):
    assert check_schema_keys(text, {"city"}) is ok


@pytest.mark.parametrize("args, ok", [
    ({"text": P.CANARY, "count": 3}, True),
    (json.dumps({"text": P.CANARY, "count": 3}), True),  # OpenAI는 arguments가 JSON 문자열
    ({"text": P.CANARY, "count": "three"}, False),       # strict 무시 — integer 자리에 문자열
    ({"text": P.CANARY, "count": True}, False),          # bool은 integer가 아니다
    ({"text": P.CANARY}, False),                         # 절단으로 required 누락
    ({"text": P.CANARY, "count": 3, "lang": "ko"}, False),
    ({"text": "other", "count": 3}, False),
    ("{not json", False),
])
def test_check_strict_tool_input(args, ok):
    assert check_strict_tool_input({"name": "echo", "arguments": args}, P.CANARY, P._STRICT_SCHEMA) is ok


def test_check_strict_tool_input_without_a_call():
    assert check_strict_tool_input(None, P.CANARY, P._STRICT_SCHEMA) is False


@pytest.mark.parametrize("msg", [
    # 서울 in-region 온디맨드 FM (2026-10-20 실측) — effort, adaptive는 받고 이 두 필드만 거부
    "ValidationException: An error occurred (ValidationException) when calling the InvokeModel operation: "
    "output_config.format: Extra inputs are not permitted",
    "ValidationException: An error occurred (ValidationException) when calling the Converse operation: "
    "The model returned the following errors: tools.0.custom.strict: Extra inputs are not permitted",
    # Nova 2.0 Lite
    "ValidationException: An error occurred (ValidationException) when calling the Converse operation: "
    "This model doesn't support the outputConfig field. Remove outputConfig and try again.",
    "ValidationException: An error occurred (ValidationException) when calling the Converse operation: "
    "This model doesn't support the strict field. Remove strict and try again.",
    # GPT 추론 모델의 Chat Completions function 도구 — tool_use와 같은 제약
    "BadRequestError: Error code: 400 - {'error': {'message': \"Function tools with reasoning_effort are not "
    "supported for gpt-6-sol in /v1/chat/completions.\"}}",
])
def test_structured_output_rejections_are_unsupported(msg):
    assert classify_error(msg) == "unsupported"


# ---------------------------------------------------------------------------
# 카탈로그와 프롬프트
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("surface, model_id", [
    ("converse", "global.anthropic.claude-sonnet-5-5"),
    ("converse", "bedrock:ap-northeast-2:anthropic.claude-opus-5"),
    ("converse", "us.amazon.nova-2-lite-v1:0"),
    ("invoke_model", "us.anthropic.claude-opus-5"),
    ("messages", "anthropic:claude-haiku-5-5"),
    ("messages_mantle", "global.anthropic.claude-opus-5"),
    ("chat_completions", "openai:global:global.openai.gpt-6-astra"),
    ("responses", "openai:us:us.openai.gpt-6-sol"),
])
def test_json_schema_and_strict_tool_use_cover_every_surface(surface, model_id):
    assert is_applicable("json_schema", surface, model_id) is True
    assert is_applicable("strict_tool_use", surface, model_id) is True


def test_strict_tool_use_follows_json_schema_in_the_catalog():
    assert FEATURE_IDS.index("strict_tool_use") == FEATURE_IDS.index("json_schema") + 1


def test_schema_prompt_asks_for_a_different_key_name():
    assert "name" in P._SCHEMA_PROMPT and "city" not in P._SCHEMA_PROMPT
    # 스키마 밖 정보(국가, 인구)를 요구하지 않는다 — GPT 6 Astra, GPT 6 Sol이 그 정보를 city 값에 몰아넣다 잘렸다
    assert "국가" not in P._SCHEMA_PROMPT and "인구" not in P._SCHEMA_PROMPT


def test_strict_prompt_conflicts_with_the_schema_only_for_forced_models():
    assert P._STRICT_SCHEMA["properties"]["count"] == {"type": "integer"}
    assert P._STRICT_SCHEMA["required"] == ["text", "count"] and P._STRICT_SCHEMA["additionalProperties"] is False
    assert '"three"' in P._strict_tool_prompt("global.anthropic.claude-opus-5")
    for fam in ("fable-5-1", "opus-5-5", "sonnet-5-5"):  # auto 모델 — 타입 충돌이면 thinking으로 고민하다 잘린다
        assert not supports_forced_tool_choice(f"us.anthropic.claude-{fam}")
        assert P._strict_tool_prompt(f"us.anthropic.claude-{fam}") == P._STRICT_TOOL_PROMPT_AUTO
    assert "three" not in P._STRICT_TOOL_PROMPT_AUTO


# ---------------------------------------------------------------------------
# 요청 형식과 판정 — 가짜 클라이언트
# ---------------------------------------------------------------------------

class _Bedrock:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list[dict] = []

    def invoke_model(self, modelId, body):
        self.calls.append(json.loads(body))
        return {"body": io.BytesIO(json.dumps(self.reply).encode())}

    def converse(self, **kw):
        self.calls.append(kw)
        return self.reply


def _invoke_text(text):
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


def _invoke_tool(inp):
    return {"content": [{"type": "tool_use", "id": "t1", "name": "echo", "input": inp}], "stop_reason": "tool_use"}


def _converse_text(text):
    return {"output": {"message": {"content": [{"text": text}]}}, "stopReason": "end_turn"}


def _converse_tool(inp):
    return {"output": {"message": {"content": [{"toolUse": {"toolUseId": "t1", "name": "echo", "input": inp}}]}},
            "stopReason": "tool_use"}


def test_invoke_json_schema_sends_the_ga_format_without_beta():
    c = _Bedrock(_invoke_text('{"city": "서울"}'))
    o = P.probe_invoke_model(c, "global.anthropic.claude-sonnet-5-5", "json_schema")
    assert o.status == "supported" and o.evidence["keys"] == ["city"]
    body = c.calls[0]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": P._JSON_SCHEMA}}
    assert "output_format" not in body and "anthropic_beta" not in body
    assert body["messages"][0]["content"] == P._SCHEMA_PROMPT
    assert o.evidence["request"]["output_config"]["format"]["type"] == "json_schema"


def test_invoke_json_schema_ignored_schema_is_broken():
    # 서비스가 스키마를 무시하면 프롬프트의 name 키가 나온다 — 키 존재 검사였다면 걸러지지 않던 경우
    o = P.probe_invoke_model(_Bedrock(_invoke_text('{"name": "서울"}')), "global.anthropic.claude-sonnet-5-5", "json_schema")
    assert o.status == "broken" and o.evidence["keys"] == ["name"]


def test_converse_json_schema_uses_output_config_text_format():
    c = _Bedrock(_converse_text('{"city":"서울"}'))
    o = P.probe_converse(c, "us.anthropic.claude-opus-5", "json_schema")
    assert o.status == "supported"
    fmt = c.calls[0]["outputConfig"]["textFormat"]
    assert fmt["type"] == "json_schema"
    assert json.loads(fmt["structure"]["jsonSchema"]["schema"]) == P._JSON_SCHEMA  # Converse는 스키마를 JSON 문자열로 받는다


@pytest.mark.parametrize("model_id, forced", [("us.anthropic.claude-opus-5", True), ("us.anthropic.claude-opus-5-5", False)])
def test_converse_strict_tool(model_id, forced):
    c = _Bedrock(_converse_tool({"text": P.CANARY, "count": 3}))
    o = P.probe_converse(c, model_id, "strict_tool_use")
    assert o.status == "supported"
    tool_config = c.calls[0]["toolConfig"]
    assert tool_config["tools"][0]["toolSpec"]["strict"] is True
    assert tool_config["tools"][0]["toolSpec"]["inputSchema"] == {"json": P._STRICT_SCHEMA}
    assert ("tool" in tool_config["toolChoice"]) is forced
    assert ("three" in c.calls[0]["messages"][0]["content"][0]["text"]) is forced


def test_invoke_strict_tool_string_in_integer_is_broken():
    c = _Bedrock(_invoke_tool({"text": P.CANARY, "count": "three"}))
    o = P.probe_invoke_model(c, "global.anthropic.claude-haiku-5-5", "strict_tool_use")
    assert o.status == "broken"
    body = c.calls[0]
    assert body["tools"][0]["strict"] is True and body["tools"][0]["input_schema"] == P._STRICT_SCHEMA
    assert body["tool_choice"] == {"type": "tool", "name": "echo"}


class _Messages:
    """anthropic SDK messages.create 흉내 — CP(messages)와 Mantle(messages_mantle) 공용 실행기."""

    def __init__(self, content):
        self.content = content
        self.calls: list[dict] = []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=self.content, stop_reason="end_turn")


def test_messages_json_schema_sends_output_config_without_beta_header():
    m = _Messages([SimpleNamespace(type="text", text='{"city":"서울"}')])
    o = P.probe_messages(SimpleNamespace(messages=m), "claude-sonnet-5-5", "json_schema")
    assert o.status == "supported"
    assert m.calls[0]["extra_body"] == {"output_config": {"format": P._OUTPUT_FORMAT}}
    assert "extra_headers" not in m.calls[0]


def test_messages_strict_tool():
    m = _Messages([SimpleNamespace(type="tool_use", name="echo", input={"text": P.CANARY, "count": 3})])
    o = P.probe_messages(SimpleNamespace(messages=m), "claude-haiku-5-5", "strict_tool_use")
    assert o.status == "supported"
    assert m.calls[0]["tools"][0]["strict"] is True
    assert m.calls[0]["tool_choice"] == {"type": "tool", "name": "echo"}


def test_chat_completions_json_schema_and_strict_tool():
    calls: list[dict] = []

    def create(**kw):
        calls.append(kw)
        if "tools" in kw:
            fn = SimpleNamespace(name="echo", arguments=json.dumps({"text": P.CANARY, "count": 3}))
            msg = SimpleNamespace(tool_calls=[SimpleNamespace(function=fn)], content=None)
        else:
            msg = SimpleNamespace(tool_calls=None, content='{"city":"서울"}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert P.probe_chat_completions(client, "openai.gpt-6-sol", "json_schema").status == "supported"
    assert P.probe_chat_completions(client, "openai.gpt-6-sol", "strict_tool_use").status == "supported"
    assert calls[0]["messages"][0]["content"] == P._SCHEMA_PROMPT
    assert calls[1]["tools"][0]["function"]["strict"] is True


def test_responses_strict_tool():
    calls: list[dict] = []

    def create(**kw):
        calls.append(kw)
        args = json.dumps({"text": P.CANARY, "count": 3})
        return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="echo", arguments=args)])

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    assert P.probe_responses(client, "global.openai.gpt-6-astra", "strict_tool_use").status == "supported"
    assert calls[0]["tools"][0]["strict"] is True and calls[0]["tool_choice"] == "required"
