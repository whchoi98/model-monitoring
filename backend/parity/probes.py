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
from parity.catalog import supports_forced_tool_choice

CANARY = "PARITY_OK_7391"
_MAX_TOKENS = 256
_JSON_MAX_TOKENS = 512
_REASONING_MAX_TOKENS = 2048
_REASONING_BUDGET = 1024
_ADAPTIVE_MAX_TOKENS = 8000  # 참조 증거와 동일 — 2048에서는 adaptive가 thinking 생략 (run #8)


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
_SEARCH_PROMPT = "오늘 서울의 날씨를 웹에서 검색해 한 문장으로 알려주세요."
_COMPUTER_TOOL = {"type": "computer_20250124", "name": "computer",
                  "display_width_px": 1024, "display_height_px": 768}
_COMPUTER_BETA = "computer-use-2025-01-24"
_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
# v2.15.0 확장 — 참조 도구 수준 피처
_PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
_JSON_SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}},
                "required": ["city"], "additionalProperties": False}
_MEMORY_TOOL = {"type": "memory_20250818", "name": "memory"}
_MEMORY_BETA = "context-management-2025-06-27"
_CODE_EXEC_TOOL = {"type": "code_execution_20250522", "name": "code_execution"}
_CODE_EXEC_BETA = "code-execution-2025-05-22"
_STRUCTURED_BETA = "structured-outputs-2025-11-13"
_FILES_BETA = "files-api-2025-04-14"
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


def _run(fn: Callable[[], tuple[bool, dict]], request: dict | None = None) -> ProbeOutcome:
    """공통 실행 래퍼 — 시간 측정 + 오류 분류. request 스냅샷은 성공/실패 모두 증거에 포함."""
    start = time.time()
    try:
        passed, evidence = fn()
        latency = (time.time() - start) * 1000
        if request:
            evidence.setdefault("request", request)
        if passed:
            return ProbeOutcome("supported", latency, evidence)
        evidence.setdefault("reason", "evidence check failed")
        return ProbeOutcome("broken", latency, evidence)
    except Exception as exc:  # noqa: BLE001 — provider 오류 전체를 분류 대상으로
        latency = (time.time() - start) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        evidence = {"request": request} if request else {}
        return ProbeOutcome(classify_error(msg), latency, evidence, error=msg[:1500])


def _snippet(text: Any) -> str:
    return str(text)[:300] if text else ""


def _req_snapshot(model: str, **kw: Any) -> dict:
    """증거용 요청 스냅샷 (v2.13.0) — 셀 클릭 시 Request JSON으로 표시.

    캐시 패딩 같은 장문 문자열은 잘라서 저장 (DB 비대 방지, 원 길이 표기).
    """
    def trim(v: Any) -> Any:
        if isinstance(v, str) and len(v) > 200:
            return f"{v[:200]}… ({len(v)} chars)"
        if isinstance(v, dict):
            return {k: trim(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [trim(x) for x in v]
        return v

    return {"model": model, **{k: trim(v) for k, v in kw.items()}}


# ---------------------------------------------------------------------------
# Converse (Bedrock SigV4)
# ---------------------------------------------------------------------------

def probe_converse(client, model_id: str, feature: str) -> ProbeOutcome:
    def converse(**kw):
        return client.converse(modelId=model_id, **kw)

    if feature == "basic":
        kw = dict(messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
                  inferenceConfig={"maxTokens": _MAX_TOKENS})
        def fn():
            r = converse(**kw)
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, **kw))

    if feature == "streaming":
        kw = dict(messages=[{"role": "user", "content": [{"text": "1부터 30까지 세어보세요."}]}],
                  inferenceConfig={"maxTokens": _MAX_TOKENS})
        def fn():
            r = client.converse_stream(modelId=model_id, **kw)
            events = sum(1 for e in r["stream"] if "contentBlockDelta" in e)
            return check_stream_events(events), {"content_events": events}
        return _run(fn, _req_snapshot(model_id, api="converse_stream", **kw))

    if feature == "system_instructions":
        kw = dict(system=[{"text": _SYSTEM_PROMPT}],
                  messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
                  inferenceConfig={"maxTokens": _MAX_TOKENS})
        def fn():
            r = converse(**kw)
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, **kw))

    if feature == "tool_use":
        kw = dict(
            messages=[{"role": "user", "content": [{"text": _TOOL_PROMPT}]}],
            toolConfig={
                "tools": [{"toolSpec": {"name": "echo", "description": _ECHO_TOOL_DESC,
                                        "inputSchema": {"json": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}}],
                # Fable 5.1은 forced tool_choice를 400으로 거부 → auto + 프롬프트 지시 (catalog.supports_forced_tool_choice)
                "toolChoice": {"tool": {"name": "echo"}} if supports_forced_tool_choice(model_id) else {"auto": {}},
            },
            inferenceConfig={"maxTokens": _MAX_TOKENS},
        )
        def fn():
            r = converse(**kw)
            tool_call = None
            for b in r["output"]["message"]["content"]:
                if "toolUse" in b:
                    tool_call = {"name": b["toolUse"]["name"], "arguments": b["toolUse"]["input"]}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn, _req_snapshot(model_id, **kw))

    if feature == "structured_output":
        kw = dict(system=[{"text": "JSON 객체만 출력. 다른 텍스트 금지."}],
                  messages=[{"role": "user", "content": [{"text": _JSON_PROMPT}]}],
                  inferenceConfig={"maxTokens": _JSON_MAX_TOKENS})
        def fn():
            r = converse(**kw)
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, **kw))

    if feature == "reasoning":
        kw = dict(
            messages=[{"role": "user", "content": [{"text": "17 x 23은? 단계적으로 생각하세요."}]}],
            inferenceConfig={"maxTokens": _REASONING_MAX_TOKENS},
            additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": _REASONING_BUDGET}},
        )
        def fn():
            r = converse(**kw)
            has_reasoning = any("reasoningContent" in b for b in r["output"]["message"]["content"])
            return has_reasoning, {"content_types": [list(b.keys())[0] for b in r["output"]["message"]["content"]]}
        return _run(fn, _req_snapshot(model_id, **kw))

    if feature == "caching":
        kw = dict(
            system=[{"text": _CACHE_PAD}, {"cachePoint": {"type": "default"}}],
            messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
            inferenceConfig={"maxTokens": _MAX_TOKENS},
        )
        def fn():
            converse(**kw)
            r2 = converse(**kw)
            usage = r2.get("usage", {})
            return check_cached_tokens(usage), {"second_usage": usage}
        return _run(fn, _req_snapshot(model_id, note="동일 요청 2회 — 2번째 usage로 캐시 판정", **kw))

    if feature == "adaptive_thinking":
        # 참조 증거와 동일 형태: thinking adaptive + output_config effort high.
        # adaptive는 모델이 추론 여부를 스스로 결정하므로 추론을 요구하는 문제 + effort high로 유도.
        kw = dict(
            messages=[{"role": "user", "content": [{"text": "처음 20개 소수의 합을 구하세요. 신중하게 단계적으로 생각하세요."}]}],
            inferenceConfig={"maxTokens": _ADAPTIVE_MAX_TOKENS},
            additionalModelRequestFields={"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        )
        def fn():
            r = converse(**kw)
            has_thinking = any("reasoningContent" in b for b in r["output"]["message"]["content"])
            return has_thinking, {"content_types": [list(b.keys())[0] for b in r["output"]["message"]["content"]]}
        return _run(fn, _req_snapshot(model_id, **kw))

    if feature == "count_tokens":
        payload = {"converse": {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}]}}
        def fn():
            r = client.count_tokens(modelId=model_id, input=payload)
            tokens = r.get("inputTokens", 0)
            return bool(tokens and tokens > 0), {"input_tokens": tokens}
        return _run(fn, _req_snapshot(model_id, api="count_tokens", input=payload))


    if feature == "reasoning_effort":
        kw = dict(
            messages=[{"role": "user", "content": [{"text": _BASIC_PROMPT}]}],
            inferenceConfig={"maxTokens": _MAX_TOKENS},
            additionalModelRequestFields={"output_config": {"effort": "low"}},
        )
        def fn():
            r = converse(**kw)
            text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
            return bool(text.strip()), {"response_snippet": _snippet(text), "stop_reason": r.get("stopReason")}
        return _run(fn, _req_snapshot(model_id, **kw))

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
        body = {"messages": [{"role": "user", "content": _BASIC_PROMPT}]}
        def fn():
            r = invoke(body)
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, max_tokens=_MAX_TOKENS, **body))

    if feature == "streaming":
        base = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": _MAX_TOKENS,
                "messages": [{"role": "user", "content": "1부터 30까지 세어보세요."}]}
        def fn():
            r = client.invoke_model_with_response_stream(modelId=model_id, body=json.dumps(base))
            events = 0
            for e in r["body"]:
                chunk = json.loads(e["chunk"]["bytes"])
                if chunk.get("type") == "content_block_delta":
                    events += 1
            return check_stream_events(events), {"content_events": events}
        return _run(fn, _req_snapshot(model_id, api="invoke_model_with_response_stream", **base))

    if feature == "system_instructions":
        body = {"system": _SYSTEM_PROMPT, "messages": [{"role": "user", "content": _BASIC_PROMPT}]}
        def fn():
            r = invoke(body)
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, max_tokens=_MAX_TOKENS, **body))

    if feature == "tool_use":
        body = {
            "messages": [{"role": "user", "content": _TOOL_PROMPT}],
            "tools": [{"name": "echo", "description": _ECHO_TOOL_DESC,
                       "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}],
            "tool_choice": {"type": "tool", "name": "echo"} if supports_forced_tool_choice(model_id) else {"type": "auto"},
        }
        def fn():
            r = invoke(body)
            tool_call = None
            for b in r.get("content", []):
                if b.get("type") == "tool_use":
                    tool_call = {"name": b["name"], "arguments": b["input"]}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn, _req_snapshot(model_id, max_tokens=_MAX_TOKENS, **body))

    if feature == "structured_output":
        body = {"system": "JSON 객체만 출력. 다른 텍스트 금지.",
                "max_tokens": _JSON_MAX_TOKENS,
                "messages": [{"role": "user", "content": _JSON_PROMPT}]}
        def fn():
            r = invoke(body)
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "reasoning":
        body = {"max_tokens": _REASONING_MAX_TOKENS,
                "thinking": {"type": "enabled", "budget_tokens": _REASONING_BUDGET},
                "messages": [{"role": "user", "content": "17 x 23은? 단계적으로 생각하세요."}]}
        def fn():
            r = invoke(body)
            has_thinking = any(b.get("type") == "thinking" for b in r.get("content", []))
            return has_thinking, {"content_types": [b.get("type") for b in r.get("content", [])]}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "caching":
        body = {
            "system": [{"type": "text", "text": _CACHE_PAD, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": _BASIC_PROMPT}],
        }
        def fn():
            invoke(dict(body))
            r2 = invoke(dict(body))
            usage = r2.get("usage", {})
            return check_cached_tokens(usage), {"second_usage": usage}
        return _run(fn, _req_snapshot(model_id, note="동일 요청 2회 — 2번째 usage로 캐시 판정", max_tokens=_MAX_TOKENS, **body))

    if feature == "adaptive_thinking":
        body = {"max_tokens": _ADAPTIVE_MAX_TOKENS, "thinking": {"type": "adaptive"},
                "output_config": {"effort": "high"},
                "messages": [{"role": "user", "content": "처음 20개 소수의 합을 구하세요. 신중하게 단계적으로 생각하세요."}]}
        def fn():
            r = invoke(body)
            has_thinking = any(b.get("type") == "thinking" for b in r.get("content", []))
            return has_thinking, {"content_types": [b.get("type") for b in r.get("content", [])]}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "count_tokens":
        native = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": _MAX_TOKENS,
                  "messages": [{"role": "user", "content": _BASIC_PROMPT}]}
        def fn():
            r = client.count_tokens(modelId=model_id, input={"invokeModel": {"body": json.dumps(native)}})
            tokens = r.get("inputTokens", 0)
            return bool(tokens and tokens > 0), {"input_tokens": tokens}
        return _run(fn, _req_snapshot(model_id, api="count_tokens", **native))

    if feature == "web_search":
        body = {"max_tokens": _MAX_TOKENS, "tools": [dict(_WEB_SEARCH_TOOL)],
                "messages": [{"role": "user", "content": _SEARCH_PROMPT}]}
        def fn():
            r = invoke(body)
            types = [b.get("type") for b in r.get("content", [])]
            accepted = r.get("stop_reason") is not None
            return accepted, {"content_types": types, "stop_reason": r.get("stop_reason"),
                              "server_tool_used": any(t in ("server_tool_use", "web_search_tool_result") for t in types)}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "computer_use":
        body = {"max_tokens": _MAX_TOKENS, "anthropic_beta": [_COMPUTER_BETA],
                "tools": [dict(_COMPUTER_TOOL)],
                "messages": [{"role": "user", "content": "화면을 스크린샷으로 캡처하세요."}]}
        def fn():
            r = invoke(body)
            types = [b.get("type") for b in r.get("content", [])]
            return r.get("stop_reason") is not None, {"content_types": types, "stop_reason": r.get("stop_reason")}
        return _run(fn, _req_snapshot(model_id, **body))


    if feature == "reasoning_effort":
        body = {"max_tokens": _MAX_TOKENS, "output_config": {"effort": "low"},
                "messages": [{"role": "user", "content": _BASIC_PROMPT}]}
        def fn():
            r = invoke(body)
            return r.get("stop_reason") is not None, {"stop_reason": r.get("stop_reason")}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "json_schema":
        body = {"max_tokens": _JSON_MAX_TOKENS, "anthropic_beta": [_STRUCTURED_BETA],
                "output_format": {"type": "json_schema", "schema": _JSON_SCHEMA},
                "messages": [{"role": "user", "content": _JSON_PROMPT}]}
        def fn():
            r = invoke(body)
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "url_sources":
        body = {"max_tokens": _MAX_TOKENS,
                "messages": [{"role": "user", "content": [
                    {"type": "document", "source": {"type": "url", "url": _PDF_URL}},
                    {"type": "text", "text": "이 문서의 내용을 한 문장으로 요약하세요."},
                ]}]}
        def fn():
            r = invoke(body)
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "memory_tool":
        body = {"max_tokens": _MAX_TOKENS, "anthropic_beta": [_MEMORY_BETA],
                "tools": [dict(_MEMORY_TOOL)],
                "messages": [{"role": "user", "content": "지금까지의 기억을 확인해 주세요."}]}
        def fn():
            r = invoke(body)
            types = [b.get("type") for b in r.get("content", [])]
            return r.get("stop_reason") is not None, {"content_types": types, "stop_reason": r.get("stop_reason")}
        return _run(fn, _req_snapshot(model_id, **body))

    if feature == "code_execution":
        body = {"max_tokens": _MAX_TOKENS, "anthropic_beta": [_CODE_EXEC_BETA],
                "tools": [dict(_CODE_EXEC_TOOL)],
                "messages": [{"role": "user", "content": "파이썬으로 2+2를 계산하세요."}]}
        def fn():
            r = invoke(body)
            types = [b.get("type") for b in r.get("content", [])]
            return r.get("stop_reason") is not None, {"content_types": types, "stop_reason": r.get("stop_reason")}
        return _run(fn, _req_snapshot(model_id, **body))

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# Messages (Anthropic CP on AWS, anthropic SDK)
# ---------------------------------------------------------------------------

def probe_messages(client, actual_id: str, feature: str) -> ProbeOutcome:
    if feature == "basic":
        kw = dict(max_tokens=_MAX_TOKENS, messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "streaming":
        kw = dict(max_tokens=_MAX_TOKENS, messages=[{"role": "user", "content": "1부터 30까지 세어보세요."}])
        def fn():
            events = 0
            with client.messages.stream(model=actual_id, **kw) as stream:
                for _text in stream.text_stream:
                    events += 1
            return check_stream_events(events), {"content_events": events}
        return _run(fn, _req_snapshot(actual_id, stream=True, **kw))

    if feature == "system_instructions":
        kw = dict(max_tokens=_MAX_TOKENS, system=_SYSTEM_PROMPT,
                  messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "tool_use":
        kw = dict(
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": _TOOL_PROMPT}],
            tools=[{"name": "echo", "description": _ECHO_TOOL_DESC,
                    "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}],
            tool_choice={"type": "tool", "name": "echo"} if supports_forced_tool_choice(actual_id) else {"type": "auto"},
        )
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            tool_call = None
            for b in r.content:
                if getattr(b, "type", "") == "tool_use":
                    tool_call = {"name": b.name, "arguments": b.input}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "structured_output":
        kw = dict(max_tokens=_JSON_MAX_TOKENS, system="JSON 객체만 출력. 다른 텍스트 금지.",
                  messages=[{"role": "user", "content": _JSON_PROMPT}])
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "reasoning":
        kw = dict(
            max_tokens=_REASONING_MAX_TOKENS,
            thinking={"type": "enabled", "budget_tokens": _REASONING_BUDGET},
            messages=[{"role": "user", "content": "17 x 23은? 단계적으로 생각하세요."}],
        )
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            has_thinking = any(getattr(b, "type", "") == "thinking" for b in r.content)
            return has_thinking, {"content_types": [getattr(b, "type", "?") for b in r.content]}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "caching":
        kw = dict(
            max_tokens=_MAX_TOKENS,
            system=[{"type": "text", "text": _CACHE_PAD, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _BASIC_PROMPT}],
        )
        def fn():
            client.messages.create(model=actual_id, **kw)
            r2 = client.messages.create(model=actual_id, **kw)
            usage = {"cache_read_input_tokens": getattr(r2.usage, "cache_read_input_tokens", 0) or 0}
            return check_cached_tokens(usage), {"second_usage": usage}
        return _run(fn, _req_snapshot(actual_id, note="동일 요청 2회 — 2번째 usage로 캐시 판정", **kw))

    if feature == "adaptive_thinking":
        kw = dict(max_tokens=_ADAPTIVE_MAX_TOKENS, thinking={"type": "adaptive"},
                  messages=[{"role": "user", "content": "처음 20개 소수의 합을 구하세요. 신중하게 단계적으로 생각하세요."}])
        def fn():
            r = client.messages.create(model=actual_id, extra_body={"output_config": {"effort": "high"}}, **kw)
            has_thinking = any(getattr(b, "type", "") == "thinking" for b in r.content)
            return has_thinking, {"content_types": [getattr(b, "type", "?") for b in r.content]}
        return _run(fn, _req_snapshot(actual_id, output_config={"effort": "high"}, **kw))

    if feature == "count_tokens":
        kw = dict(messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.messages.count_tokens(model=actual_id, **kw)
            tokens = getattr(r, "input_tokens", 0) or 0
            return tokens > 0, {"input_tokens": tokens}
        return _run(fn, _req_snapshot(actual_id, api="messages.count_tokens", **kw))

    if feature == "batches":
        params = dict(max_tokens=16, messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            batch = client.messages.batches.create(
                requests=[{"custom_id": "parity-probe-1", "params": {"model": actual_id, **params}}])
            status = client.messages.batches.retrieve(batch.id)
            try:  # 비용·잔여 작업 방지 — 상태 확인 후 즉시 취소 (실패해도 판정 무관)
                client.messages.batches.cancel(batch.id)
            except Exception:  # noqa: BLE001
                pass
            processing = getattr(status, "processing_status", None)
            return bool(batch.id and processing), {"batch_id": batch.id, "processing_status": processing}
        return _run(fn, _req_snapshot(actual_id, api="messages.batches submit→retrieve→cancel", **params))

    if feature == "web_search":
        kw = dict(max_tokens=_MAX_TOKENS, tools=[dict(_WEB_SEARCH_TOOL)],
                  messages=[{"role": "user", "content": _SEARCH_PROMPT}])
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            types = [getattr(b, "type", "?") for b in r.content]
            return r.stop_reason is not None, {"content_types": types, "stop_reason": r.stop_reason,
                                               "server_tool_used": any(t in ("server_tool_use", "web_search_tool_result") for t in types)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "computer_use":
        kw = dict(max_tokens=_MAX_TOKENS, tools=[dict(_COMPUTER_TOOL)],
                  messages=[{"role": "user", "content": "화면을 스크린샷으로 캡처하세요."}])
        def fn():
            r = client.beta.messages.create(model=actual_id, betas=[_COMPUTER_BETA], **kw)
            types = [getattr(b, "type", "?") for b in r.content]
            return r.stop_reason is not None, {"content_types": types, "stop_reason": r.stop_reason}
        return _run(fn, _req_snapshot(actual_id, betas=[_COMPUTER_BETA], **kw))


    if feature == "reasoning_effort":
        kw = dict(max_tokens=_MAX_TOKENS, messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.messages.create(model=actual_id, extra_body={"output_config": {"effort": "low"}}, **kw)
            return r.stop_reason is not None, {"stop_reason": r.stop_reason}
        return _run(fn, _req_snapshot(actual_id, output_config={"effort": "low"}, **kw))

    if feature == "json_schema":
        kw = dict(max_tokens=_JSON_MAX_TOKENS, messages=[{"role": "user", "content": _JSON_PROMPT}])
        def fn():
            r = client.messages.create(
                model=actual_id,
                extra_body={"output_format": {"type": "json_schema", "schema": _JSON_SCHEMA}},
                extra_headers={"anthropic-beta": _STRUCTURED_BETA}, **kw)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, output_format={"type": "json_schema", "schema": _JSON_SCHEMA}, **kw))

    if feature == "url_sources":
        kw = dict(max_tokens=_MAX_TOKENS, messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "url", "url": _PDF_URL}},
            {"type": "text", "text": "이 문서의 내용을 한 문장으로 요약하세요."},
        ]}])
        def fn():
            r = client.messages.create(model=actual_id, **kw)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return bool(text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "memory_tool":
        kw = dict(max_tokens=_MAX_TOKENS, tools=[dict(_MEMORY_TOOL)],
                  messages=[{"role": "user", "content": "지금까지의 기억을 확인해 주세요."}])
        def fn():
            r = client.beta.messages.create(model=actual_id, betas=[_MEMORY_BETA], **kw)
            types = [getattr(b, "type", "?") for b in r.content]
            return r.stop_reason is not None, {"content_types": types, "stop_reason": r.stop_reason}
        return _run(fn, _req_snapshot(actual_id, betas=[_MEMORY_BETA], **kw))

    if feature == "code_execution":
        kw = dict(max_tokens=_MAX_TOKENS, tools=[dict(_CODE_EXEC_TOOL)],
                  messages=[{"role": "user", "content": "파이썬으로 2+2를 계산하세요."}])
        def fn():
            r = client.beta.messages.create(model=actual_id, betas=[_CODE_EXEC_BETA], **kw)
            types = [getattr(b, "type", "?") for b in r.content]
            return r.stop_reason is not None, {"content_types": types, "stop_reason": r.stop_reason}
        return _run(fn, _req_snapshot(actual_id, betas=[_CODE_EXEC_BETA], **kw))

    if feature == "files_api":
        def fn():
            page = client.beta.files.list(extra_headers={"anthropic-beta": _FILES_BETA})
            files = list(getattr(page, "data", []) or [])
            return True, {"files_listed": len(files)}
        return _run(fn, _req_snapshot(actual_id, api="GET /v1/files (beta)"))

    if feature == "models_api":
        def fn():
            r = client.models.retrieve(actual_id)
            rid = getattr(r, "id", None)
            return rid == actual_id, {"retrieved_id": rid}
        return _run(fn, _req_snapshot(actual_id, api="GET /v1/models/{model}"))

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# Chat Completions (OpenAI 호환 — Mantle/1P)
# ---------------------------------------------------------------------------

def probe_chat_completions(client, actual_id: str, feature: str) -> ProbeOutcome:
    if feature == "basic":
        kw = dict(max_completion_tokens=_MAX_TOKENS, messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            text = r.choices[0].message.content
            return bool(text and text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "streaming":
        kw = dict(max_completion_tokens=_MAX_TOKENS,
                  messages=[{"role": "user", "content": "1부터 30까지 세어보세요."}], stream=True)
        def fn():
            stream = client.chat.completions.create(model=actual_id, **kw)
            events = sum(1 for c in stream if c.choices and c.choices[0].delta and c.choices[0].delta.content)
            return check_stream_events(events), {"content_events": events}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "system_instructions":
        kw = dict(max_completion_tokens=_MAX_TOKENS,
                  messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            text = r.choices[0].message.content
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "tool_use":
        kw = dict(
            max_completion_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": _TOOL_PROMPT}],
            tools=[{"type": "function", "function": {"name": "echo", "description": _ECHO_TOOL_DESC,
                    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}],
            tool_choice={"type": "function", "function": {"name": "echo"}},
        )
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            tc = r.choices[0].message.tool_calls
            tool_call = {"name": tc[0].function.name, "arguments": tc[0].function.arguments} if tc else None
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "structured_output":
        kw = dict(max_completion_tokens=_JSON_MAX_TOKENS, response_format={"type": "json_object"},
                  messages=[{"role": "user", "content": _JSON_PROMPT}])
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            text = r.choices[0].message.content
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "reasoning":
        kw = dict(max_completion_tokens=_REASONING_MAX_TOKENS, reasoning_effort="low",
                  messages=[{"role": "user", "content": "17 x 23은?"}])
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            details = getattr(r.usage, "completion_tokens_details", None)
            rt = getattr(details, "reasoning_tokens", 0) if details else 0
            return bool(rt and rt > 0), {"reasoning_tokens": rt}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "caching":
        kw = dict(max_completion_tokens=_MAX_TOKENS,
                  messages=[{"role": "system", "content": _CACHE_PAD}, {"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            client.chat.completions.create(model=actual_id, **kw)
            r2 = client.chat.completions.create(model=actual_id, **kw)
            details = getattr(r2.usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            return check_cached_tokens({"cached_tokens": cached or 0}), {"second_usage": {"cached_tokens": cached}}
        return _run(fn, _req_snapshot(actual_id, note="동일 요청 2회 — 2번째 usage로 캐시 판정", **kw))


    if feature == "reasoning_effort":
        kw = dict(max_completion_tokens=_REASONING_MAX_TOKENS, reasoning_effort="high",
                  messages=[{"role": "user", "content": _BASIC_PROMPT}])
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            ok = bool(r.choices)
            return ok, {"finish_reason": r.choices[0].finish_reason if ok else None}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "json_schema":
        kw = dict(max_completion_tokens=_JSON_MAX_TOKENS,
                  response_format={"type": "json_schema",
                                   "json_schema": {"name": "city_info", "strict": True, "schema": _JSON_SCHEMA}},
                  messages=[{"role": "user", "content": _JSON_PROMPT}])
        def fn():
            r = client.chat.completions.create(model=actual_id, **kw)
            text = r.choices[0].message.content
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "models_api":
        def fn():
            r = client.models.retrieve(actual_id)
            rid = getattr(r, "id", None)
            return rid == actual_id, {"retrieved_id": rid}
        return _run(fn, _req_snapshot(actual_id, api="GET /v1/models/{model}"))

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")


# ---------------------------------------------------------------------------
# Responses (OpenAI 호환 — Mantle/1P)
# ---------------------------------------------------------------------------

def probe_responses(client, actual_id: str, feature: str) -> ProbeOutcome:
    if feature == "basic":
        kw = dict(max_output_tokens=_MAX_TOKENS, input=_BASIC_PROMPT)
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            text = getattr(r, "output_text", "")
            return bool(text and text.strip()), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "streaming":
        kw = dict(max_output_tokens=_MAX_TOKENS, input="1부터 30까지 세어보세요.", stream=True)
        def fn():
            stream = client.responses.create(model=actual_id, **kw)
            events = sum(1 for e in stream if getattr(e, "type", "") == "response.output_text.delta")
            return check_stream_events(events), {"content_events": events}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "system_instructions":
        kw = dict(max_output_tokens=_MAX_TOKENS, instructions=_SYSTEM_PROMPT, input=_BASIC_PROMPT)
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            text = getattr(r, "output_text", "")
            return check_canary(text, CANARY), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "tool_use":
        kw = dict(
            max_output_tokens=_MAX_TOKENS, input=_TOOL_PROMPT,
            tools=[{"type": "function", "name": "echo", "description": _ECHO_TOOL_DESC,
                    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}],
            tool_choice="required",
        )
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            tool_call = None
            for item in r.output:
                if getattr(item, "type", "") == "function_call":
                    tool_call = {"name": item.name, "arguments": item.arguments}
            return check_tool_roundtrip(tool_call, CANARY), {"tool_call": tool_call}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "structured_output":
        kw = dict(max_output_tokens=_JSON_MAX_TOKENS, input=_JSON_PROMPT,
                  text={"format": {"type": "json_object"}})
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            text = getattr(r, "output_text", "")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "reasoning":
        kw = dict(max_output_tokens=_REASONING_MAX_TOKENS, reasoning={"effort": "low"}, input="17 x 23은?")
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            details = getattr(r.usage, "output_tokens_details", None)
            rt = getattr(details, "reasoning_tokens", 0) if details else 0
            return bool(rt and rt > 0), {"reasoning_tokens": rt}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "caching":
        kw = dict(max_output_tokens=_MAX_TOKENS, instructions=_CACHE_PAD, input=_BASIC_PROMPT)
        def fn():
            client.responses.create(model=actual_id, **kw)
            r2 = client.responses.create(model=actual_id, **kw)
            details = getattr(r2.usage, "input_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            return check_cached_tokens({"cached_tokens": cached or 0}), {"second_usage": {"cached_tokens": cached}}
        return _run(fn, _req_snapshot(actual_id, note="동일 요청 2회 — 2번째 usage로 캐시 판정", **kw))

    if feature == "web_search":
        kw = dict(max_output_tokens=_JSON_MAX_TOKENS, tools=[{"type": "web_search"}], input=_SEARCH_PROMPT)
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            types = [getattr(item, "type", "?") for item in getattr(r, "output", []) or []]
            completed = getattr(r, "status", "") == "completed" or bool(getattr(r, "output_text", ""))
            return completed, {"output_types": types, "status": getattr(r, "status", None),
                               "search_used": any("web_search" in t for t in types)}
        return _run(fn, _req_snapshot(actual_id, **kw))


    if feature == "reasoning_effort":
        kw = dict(max_output_tokens=_REASONING_MAX_TOKENS, reasoning={"effort": "high"}, input=_BASIC_PROMPT)
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            return getattr(r, "status", "") == "completed", {"status": getattr(r, "status", None)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    if feature == "json_schema":
        kw = dict(max_output_tokens=_JSON_MAX_TOKENS, input=_JSON_PROMPT,
                  text={"format": {"type": "json_schema", "name": "city_info",
                                   "schema": _JSON_SCHEMA, "strict": True}})
        def fn():
            r = client.responses.create(model=actual_id, **kw)
            text = getattr(r, "output_text", "")
            return check_json_object(text, "city"), {"response_snippet": _snippet(text)}
        return _run(fn, _req_snapshot(actual_id, **kw))

    return ProbeOutcome("broken", error=f"no probe for feature {feature}")
