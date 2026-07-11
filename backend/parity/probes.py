"""surface별 패리티 프로브 실행기 (v2.11.0).

각 프로브는 실제 API 요청을 보내고 응답 '내용'을 검사해 supported/unsupported/broken을
판정한다. 클라이언트는 prober.py의 기존 헬퍼를 재사용한다 (5개 provider path 공용).

비용 통제: max_tokens 기본 256 (structured_output 512, reasoning 2048 — thinking budget 요구),
caching 프로브만 2회 호출. 64는 코드펜스 JSON·canary 응답이 절단돼 false-Broken을 유발했음 (run #1).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from parity.engine import (
    check_cached_tokens,
    check_canary,
    check_json_object,
    check_stream_events,
    check_tool_roundtrip,
    classify_error,
)

CANARY = "PARITY_OK_7391"
_MAX_TOKENS = 256
_JSON_MAX_TOKENS = 512
_REASONING_MAX_TOKENS = 2048
_REASONING_BUDGET = 1024


def max_tokens_for(feature: str) -> int:
    """피처별 max_tokens 예산 — 절단으로 인한 false-Broken 방지가 목적."""
    if feature == "reasoning":
        return _REASONING_MAX_TOKENS
    if feature == "structured_output":
        return _JSON_MAX_TOKENS
    return _MAX_TOKENS
# 캐싱 프로브용 장문 시스템 텍스트 — provider 최소 캐시 토큰(1024+)을 넘기기 위한 패딩.
_CACHE_PAD = ("모니터링 패리티 런의 캐싱 프로브를 위한 컨텍스트 패딩 문단입니다. " * 220).strip()

_ECHO_TOOL_DESC = "입력 text를 그대로 반환하는 echo 도구"
_TOOL_PROMPT = f"echo 도구를 text 인자 '{CANARY}' 값으로 호출하세요."
_JSON_PROMPT = '서울의 정보를 JSON 객체로만 답하세요. 반드시 "city" 키를 포함해야 합니다.'
_SYSTEM_PROMPT = f"모든 응답을 반드시 '{CANARY}' 로 시작하세요."
_BASIC_PROMPT = "안녕하세요라고 한 단어로 답하세요."


@dataclass
class ProbeOutcome:
    status: str  # supported | unsupported | broken
    latency_ms: float | None = None
    evidence: dict = field(default_factory=dict)
    error: str | None = None


def _run(fn: Callable[[], tuple[bool, dict]]) -> ProbeOutcome:
    """공통 실행 래퍼 — 시간 측정 + 오류 분류."""
    start = time.time()
    try:
        passed, evidence = fn()
        latency = (time.time() - start) * 1000
        if passed:
            return ProbeOutcome("supported", latency, evidence)
        evidence.setdefault("reason", "evidence check failed")
        return ProbeOutcome("broken", latency, evidence)
    except Exception as exc:  # noqa: BLE001 — provider 오류 전체를 분류 대상으로
        latency = (time.time() - start) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        return ProbeOutcome(classify_error(msg), latency, {}, error=msg[:1500])


def _snippet(text: Any) -> str:
    return str(text)[:300] if text else ""


# ---------------------------------------------------------------------------
# Converse (Bedrock SigV4)
# ---------------------------------------------------------------------------

def probe_converse(client, model_id: str, feature: str) -> ProbeOutcome:
    def converse(**kw):
        return client.converse(modelId=model_id, **kw)

    if feature == "basic":
        def fn():
            r = converse(messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
                         inferenceConfig={"maxTokens": _MAX_TOKENS})
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "streaming":
        def fn():
            r = client.converse_stream(modelId=model_id,
                                       messages=[{"role": "user", "content": [{"text": "1부터 30까지 세어보세요."}]}],
                                       inferenceConfig={"maxTokens": _MAX_TOKENS})
            events = sum(1 for e in r["stream"] if "contentBlockDelta" in e)
            return check_stream_events(events), {"content_events": events}
        return _run(fn)

    if feature == "system_instructions":
        def fn():
            r = converse(system=[{"text": _SYSTEM_PROMPT}],
                         messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
                         inferenceConfig={"maxTokens": _MAX_TOKENS})
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "tool_use":
        def fn():
            r = converse(
                messages=[{"role": "user", "content": [{"text": _TOOL_PROMPT}]}],
                toolConfig={
                    "tools": [{"toolSpec": {"name": "echo", "description": _ECHO_TOOL_DESC,
                                            "inputSchema": {"json": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}}],
                    "toolChoice": {"tool": {"name": "echo"}},
                },
                inferenceConfig={"maxTokens": _MAX_TOKENS},
            )
            tool_call = None
            for b in r["output"]["message"]["content"]:
                if "toolUse" in b:
                    tool_call = {"name": b["toolUse"]["name"], "arguments": b["toolUse"]["input"]}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn)

    if feature == "structured_output":
        def fn():
            r = converse(system=[{"text": "JSON 객체만 출력. 다른 텍스트 금지."}],
                         messages=[{"role": "user", "content": [{"text": _JSON_PROMPT}]}],
                         inferenceConfig={"maxTokens": _JSON_MAX_TOKENS})
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "reasoning":
        def fn():
            r = converse(
                messages=[{"role": "user", "content": [{"text": "17 x 23은? 단계적으로 생각하세요."}]}],
                inferenceConfig={"maxTokens": _REASONING_MAX_TOKENS},
                additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": _REASONING_BUDGET}},
            )
            has_reasoning = any("reasoningContent" in b for b in r["output"]["message"]["content"])
            return has_reasoning, {"content_types": [list(b.keys())[0] for b in r["output"]["message"]["content"]]}
        return _run(fn)

    if feature == "caching":
        def fn():
            kw = dict(
                system=[{"text": _CACHE_PAD}, {"cachePoint": {"type": "default"}}],
                messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
                inferenceConfig={"maxTokens": _MAX_TOKENS},
            )
            converse(**kw)
            r2 = converse(**kw)
            usage = r2.get("usage", {})
            return check_cached_tokens(usage), {"second_usage": usage}
        return _run(fn)

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# InvokeModel (Bedrock SigV4, Anthropic 네이티브 스키마)
# ---------------------------------------------------------------------------

def probe_invoke_model(client, model_id: str, feature: str) -> ProbeOutcome:
    def invoke(body: dict) -> dict:
        base = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": _MAX_TOKENS}
        base.update(body)
        r = client.invoke_model(modelId=model_id, body=json.dumps(base))
        return json.loads(r["body"].read())

    if feature == "basic":
        def fn():
            r = invoke({"messages": [{"role": "user", "content": _BASIC_PROMPT}]})
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "streaming":
        def fn():
            base = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": _MAX_TOKENS,
                    "messages": [{"role": "user", "content": "1부터 30까지 세어보세요."}]}
            r = client.invoke_model_with_response_stream(modelId=model_id, body=json.dumps(base))
            events = 0
            for e in r["body"]:
                chunk = json.loads(e["chunk"]["bytes"])
                if chunk.get("type") == "content_block_delta":
                    events += 1
            return check_stream_events(events), {"content_events": events}
        return _run(fn)

    if feature == "system_instructions":
        def fn():
            r = invoke({"system": _SYSTEM_PROMPT, "messages": [{"role": "user", "content": _BASIC_PROMPT}]})
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "tool_use":
        def fn():
            r = invoke({
                "messages": [{"role": "user", "content": _TOOL_PROMPT}],
                "tools": [{"name": "echo", "description": _ECHO_TOOL_DESC,
                           "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}],
                "tool_choice": {"type": "tool", "name": "echo"},
            })
            tool_call = None
            for b in r.get("content", []):
                if b.get("type") == "tool_use":
                    tool_call = {"name": b["name"], "arguments": b["input"]}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn)

    if feature == "structured_output":
        def fn():
            r = invoke({"system": "JSON 객체만 출력. 다른 텍스트 금지.",
                        "max_tokens": _JSON_MAX_TOKENS,
                        "messages": [{"role": "user", "content": _JSON_PROMPT}]})
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "reasoning":
        def fn():
            r = invoke({"max_tokens": _REASONING_MAX_TOKENS,
                        "thinking": {"type": "enabled", "budget_tokens": _REASONING_BUDGET},
                        "messages": [{"role": "user", "content": "17 x 23은? 단계적으로 생각하세요."}]})
            has_thinking = any(b.get("type") == "thinking" for b in r.get("content", []))
            return has_thinking, {"content_types": [b.get("type") for b in r.get("content", [])]}
        return _run(fn)

    if feature == "caching":
        def fn():
            body = {
                "system": [{"type": "text", "text": _CACHE_PAD, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": _BASIC_PROMPT}],
            }
            invoke(dict(body))
            r2 = invoke(dict(body))
            usage = r2.get("usage", {})
            return check_cached_tokens(usage), {"second_usage": usage}
        return _run(fn)

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# Messages (Anthropic CP on AWS, anthropic SDK)
# ---------------------------------------------------------------------------

def probe_messages(client, actual_id: str, feature: str) -> ProbeOutcome:
    if feature == "basic":
        def fn():
            r = client.messages.create(model=actual_id, max_tokens=_MAX_TOKENS,
                                       messages=[{"role": "user", "content": _BASIC_PROMPT}])
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "streaming":
        def fn():
            events = 0
            with client.messages.stream(model=actual_id, max_tokens=_MAX_TOKENS,
                                        messages=[{"role": "user", "content": "1부터 30까지 세어보세요."}]) as stream:
                for _text in stream.text_stream:
                    events += 1
            return check_stream_events(events), {"content_events": events}
        return _run(fn)

    if feature == "system_instructions":
        def fn():
            r = client.messages.create(model=actual_id, max_tokens=_MAX_TOKENS, system=_SYSTEM_PROMPT,
                                       messages=[{"role": "user", "content": _BASIC_PROMPT}])
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "tool_use":
        def fn():
            r = client.messages.create(
                model=actual_id, max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": _TOOL_PROMPT}],
                tools=[{"name": "echo", "description": _ECHO_TOOL_DESC,
                        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}],
                tool_choice={"type": "tool", "name": "echo"},
            )
            tool_call = None
            for b in r.content:
                if getattr(b, "type", "") == "tool_use":
                    tool_call = {"name": b.name, "arguments": b.input}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn)

    if feature == "structured_output":
        def fn():
            r = client.messages.create(model=actual_id, max_tokens=_JSON_MAX_TOKENS,
                                       system="JSON 객체만 출력. 다른 텍스트 금지.",
                                       messages=[{"role": "user", "content": _JSON_PROMPT}])
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "reasoning":
        def fn():
            r = client.messages.create(
                model=actual_id, max_tokens=_REASONING_MAX_TOKENS,
                thinking={"type": "enabled", "budget_tokens": _REASONING_BUDGET},
                messages=[{"role": "user", "content": "17 x 23은? 단계적으로 생각하세요."}],
            )
            has_thinking = any(getattr(b, "type", "") == "thinking" for b in r.content)
            return has_thinking, {"content_types": [getattr(b, "type", "?") for b in r.content]}
        return _run(fn)

    if feature == "caching":
        def fn():
            kw = dict(
                model=actual_id, max_tokens=_MAX_TOKENS,
                system=[{"type": "text", "text": _CACHE_PAD, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": _BASIC_PROMPT}],
            )
            client.messages.create(**kw)
            r2 = client.messages.create(**kw)
            usage = {"cache_read_input_tokens": getattr(r2.usage, "cache_read_input_tokens", 0) or 0}
            return check_cached_tokens(usage), {"second_usage": usage}
        return _run(fn)

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# Chat Completions (OpenAI 호환 — Mantle/1P)
# ---------------------------------------------------------------------------

def probe_chat_completions(client, actual_id: str, feature: str) -> ProbeOutcome:
    if feature == "basic":
        def fn():
            r = client.chat.completions.create(model=actual_id, max_completion_tokens=_MAX_TOKENS,
                                               messages=[{"role": "user", "content": _BASIC_PROMPT}])
            text = r.choices[0].message.content
            return bool(text and text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "streaming":
        def fn():
            stream = client.chat.completions.create(model=actual_id, max_completion_tokens=_MAX_TOKENS,
                                                    messages=[{"role": "user", "content": "1부터 30까지 세어보세요."}], stream=True)
            events = sum(1 for c in stream if c.choices and c.choices[0].delta and c.choices[0].delta.content)
            return check_stream_events(events), {"content_events": events}
        return _run(fn)

    if feature == "system_instructions":
        def fn():
            r = client.chat.completions.create(model=actual_id, max_completion_tokens=_MAX_TOKENS,
                                               messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                                                         {"role": "user", "content": _BASIC_PROMPT}])
            text = r.choices[0].message.content
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "tool_use":
        def fn():
            r = client.chat.completions.create(
                model=actual_id, max_completion_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": _TOOL_PROMPT}],
                tools=[{"type": "function", "function": {"name": "echo", "description": _ECHO_TOOL_DESC,
                        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}],
                tool_choice={"type": "function", "function": {"name": "echo"}},
            )
            tc = r.choices[0].message.tool_calls
            tool_call = {"name": tc[0].function.name, "arguments": tc[0].function.arguments} if tc else None
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn)

    if feature == "structured_output":
        def fn():
            r = client.chat.completions.create(model=actual_id, max_completion_tokens=_JSON_MAX_TOKENS,
                                               response_format={"type": "json_object"},
                                               messages=[{"role": "user", "content": _JSON_PROMPT}])
            text = r.choices[0].message.content
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "reasoning":
        def fn():
            r = client.chat.completions.create(model=actual_id, max_completion_tokens=_REASONING_MAX_TOKENS,
                                               reasoning_effort="low",
                                               messages=[{"role": "user", "content": "17 x 23은?"}])
            details = getattr(r.usage, "completion_tokens_details", None)
            rt = getattr(details, "reasoning_tokens", 0) if details else 0
            return bool(rt and rt > 0), {"reasoning_tokens": rt}
        return _run(fn)

    if feature == "caching":
        def fn():
            msgs = [{"role": "system", "content": _CACHE_PAD}, {"role": "user", "content": _BASIC_PROMPT}]
            client.chat.completions.create(model=actual_id, max_completion_tokens=_MAX_TOKENS, messages=msgs)
            r2 = client.chat.completions.create(model=actual_id, max_completion_tokens=_MAX_TOKENS, messages=msgs)
            details = getattr(r2.usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            return check_cached_tokens({"cached_tokens": cached or 0}), {"second_usage": {"cached_tokens": cached}}
        return _run(fn)

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# Responses (OpenAI 호환 — Mantle/1P)
# ---------------------------------------------------------------------------

def probe_responses(client, actual_id: str, feature: str) -> ProbeOutcome:
    if feature == "basic":
        def fn():
            r = client.responses.create(model=actual_id, max_output_tokens=_MAX_TOKENS, input=_BASIC_PROMPT)
            text = getattr(r, "output_text", "")
            return bool(text and text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "streaming":
        def fn():
            stream = client.responses.create(model=actual_id, max_output_tokens=_MAX_TOKENS,
                                             input="1부터 30까지 세어보세요.", stream=True)
            events = sum(1 for e in stream if getattr(e, "type", "") == "response.output_text.delta")
            return check_stream_events(events), {"content_events": events}
        return _run(fn)

    if feature == "system_instructions":
        def fn():
            r = client.responses.create(model=actual_id, max_output_tokens=_MAX_TOKENS,
                                        instructions=_SYSTEM_PROMPT, input=_BASIC_PROMPT)
            text = getattr(r, "output_text", "")
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "tool_use":
        def fn():
            r = client.responses.create(
                model=actual_id, max_output_tokens=_MAX_TOKENS, input=_TOOL_PROMPT,
                tools=[{"type": "function", "name": "echo", "description": _ECHO_TOOL_DESC,
                        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}],
                tool_choice="required",
            )
            tool_call = None
            for item in r.output:
                if getattr(item, "type", "") == "function_call":
                    tool_call = {"name": item.name, "arguments": item.arguments}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn)

    if feature == "structured_output":
        def fn():
            r = client.responses.create(model=actual_id, max_output_tokens=_JSON_MAX_TOKENS, input=_JSON_PROMPT,
                                        text={"format": {"type": "json_object"}})
            text = getattr(r, "output_text", "")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn)

    if feature == "reasoning":
        def fn():
            r = client.responses.create(model=actual_id, max_output_tokens=_REASONING_MAX_TOKENS,
                                        reasoning={"effort": "low"}, input="17 x 23은?")
            details = getattr(r.usage, "output_tokens_details", None)
            rt = getattr(details, "reasoning_tokens", 0) if details else 0
            return bool(rt and rt > 0), {"reasoning_tokens": rt}
        return _run(fn)

    if feature == "caching":
        def fn():
            kw = dict(model=actual_id, max_output_tokens=_MAX_TOKENS,
                      instructions=_CACHE_PAD, input=_BASIC_PROMPT)
            client.responses.create(**kw)
            r2 = client.responses.create(**kw)
            details = getattr(r2.usage, "input_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            return check_cached_tokens({"cached_tokens": cached or 0}), {"second_usage": {"cached_tokens": cached}}
        return _run(fn)

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")
