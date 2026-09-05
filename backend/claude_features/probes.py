"""피처별 프로브 (v2.23.0) — 전송기 무관. 본문은 Anthropic Messages 스키마로만 작성한다.

각 프로브: (transport, model_id, model_key) -> (passed|status, evidence)
  True → supported / False → broken(증거 실패) / "inconclusive" | "not_applicable" | "unsupported" | "supported"
run_probe()가 시간 측정·오류 분류·요청 스냅샷을 공통 처리한다.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from claude_features import engine
from claude_features.transports import NormalizedResponse, Transport, TransportError
from parity.catalog import supports_forced_tool_choice
from parity.engine import check_canary, check_json_object, check_tool_roundtrip

CANARY = "FEATURES_OK_7391"
_MAX = 256
_JSON_MAX = 512
_THINK_MAX = 3000
_TOOL_MAX = 1024
# 캐시 최소 토큰(Fable/Opus 5 = 512, Sonnet 5 = 1,024)을 넉넉히 넘기는 무해한 영문 패딩 (~2,100 토큰).
# 내용은 의도적으로 평범한 백과사전식 문장이다 — 구 패딩은 자신을 "probe"로 설명하며 "model"의
# 최소 길이를 언급해 CP Fable 5(refusal/cyber)·Opus 5(refusal/reasoning_extraction)·
# Converse Fable 5(content_filtered)에서 안전 거부를 유발했고, 거부된 완료는 캐시를 읽지 않아
# cache_read가 0으로 남아 broken 오탐 4건이 됐다 (2026-09-05 전체 스윕 실측).
CACHE_PAD = ("The Baltic Sea is a marginal sea of the Atlantic Ocean enclosed by Northern and Central Europe. "
             "It drains a basin of roughly 1.6 million square kilometres through the Danish straits. "
             "Its surface salinity stays low because many rivers empty into it and evaporation is modest. "
             "Sea ice forms along the northern coasts most winters and clears again by late spring. ") * 25
_JSON_SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
                "required": ["city", "country"], "additionalProperties": False}
_ECHO_SCHEMA = {"type": "object", "properties": {"text": {"type": "string", "description": "text to echo"}},
                "required": ["text"], "additionalProperties": False}
_TOOL_PROMPT = f"Call the `echo` tool exactly once with text set to '{CANARY}'. Do not answer in prose."
_SYSTEM_PROMPT = f"Begin every reply with the exact token {CANARY} followed by a space."
_BASIC_PROMPT = "Reply with the single word: pong"


@dataclass
class ProbeOutcome:
    status: str
    latency_ms: float | None = None
    evidence: dict = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------- helpers

def _msg(prompt: Any, **kw: Any) -> dict:
    content = prompt if isinstance(prompt, list) else prompt
    body = {"max_tokens": _MAX, "messages": [{"role": "user", "content": content}]}
    body.update(kw)
    return body


def _tool_choice(model_id: str, name: str) -> dict:
    return {"type": "tool", "name": name} if supports_forced_tool_choice(model_id) else {"type": "auto"}


def _echo_tool(strict: bool = False, eager: bool = False) -> dict:
    tool: dict = {"name": "echo", "description": "Returns the given text unchanged.", "input_schema": _ECHO_SCHEMA}
    if strict:
        tool["strict"] = True
    if eager:
        tool["eager_input_streaming"] = True
    return tool


def _trim(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    if isinstance(v, str) and len(v) > 200:
        return f"{v[:200]}… ({len(v)} chars)"
    if isinstance(v, dict):
        return {k: _trim(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_trim(x) for x in v]
    return v


def _req(model_id: str, body: dict | None = None, betas=(), **extra: Any) -> dict:
    snap: dict = {"model": model_id}
    if body:
        snap.update(_trim(body))
    if betas:
        snap["anthropic_beta"] = list(betas)
    snap.update(_trim(extra))
    return snap


def _snippet(n: NormalizedResponse, limit: int = 300) -> str:
    return engine.text_of(n.content)[:limit]


def _content_deltas(events: list[dict], delta_type: str) -> int:
    return sum(1 for e in events if e.get("type") == "content_block_delta"
               and (e.get("delta") or {}).get("type") == delta_type)


def _route_or_unsupported(t: Transport, route: str) -> tuple[str, dict] | None:
    """라우트가 없는 전송기(Bedrock 두 열)는 호출 없이 unsupported로 판정."""
    if route not in t.routes:
        return "unsupported", {"reason": f"no route: {t.surface} endpoint has no {route} API"}
    return None


def _tiny_pdf(text: str) -> bytes:
    """텍스트 한 줄이 든 최소 1페이지 PDF (Helvetica, ASCII만)."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def run_probe(fn: Callable, t: Transport, model_id: str, model_key: str) -> ProbeOutcome:
    start = time.time()
    try:
        result, evidence = fn(t, model_id, model_key)
        latency = (time.time() - start) * 1000
        evidence.setdefault("request", _req(model_id))
        if result is True:
            return ProbeOutcome("supported", latency, evidence)
        if result is False:
            evidence.setdefault("reason", "evidence check failed")
            return ProbeOutcome("broken", latency, evidence)
        if str(result) not in engine.STATUSES:
            return ProbeOutcome("broken", latency, {**evidence, "reason": f"probe returned unknown status {result!r}"})
        return ProbeOutcome(str(result), latency, evidence)
    except TransportError as exc:
        latency = (time.time() - start) * 1000
        msg = str(exc)
        return ProbeOutcome(engine.classify(msg), latency, {"request": _req(model_id)}, error=msg[:1500])
    except Exception as exc:  # noqa: BLE001 — 네트워크/파싱 오류 전체
        latency = (time.time() - start) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        return ProbeOutcome(engine.classify(msg), latency, {"request": _req(model_id)}, error=msg[:1500])


# ---------------------------------------------------------------- core

def probe_messages_basic(t, model_id, model_key):
    body = _msg(_BASIC_PROMPT)
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX}}
        n = t.converse(model_id, **kw)
        return bool(engine.text_of(n.content).strip()), {"request": _req(model_id, kw), "response_snippet": _snippet(n), "stop_reason": n.stop_reason}
    n = t.messages(model_id, body)
    return bool(engine.text_of(n.content).strip()), {"request": _req(model_id, body), "response_snippet": _snippet(n), "stop_reason": n.stop_reason}


def probe_streaming(t, model_id, model_key):
    prompt = "Count from 1 to 30 separated by commas."
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": _MAX}}
        n = t.converse(model_id, stream=True, **kw)
        deltas = sum(1 for e in n.events if "contentBlockDelta" in e)
        return deltas >= 2, {"request": _req(model_id, kw, stream=True), "content_events": deltas}
    body = _msg(prompt)
    n = t.messages(model_id, body, stream=True)
    deltas = _content_deltas(n.events, "text_delta")
    return deltas >= 2, {"request": _req(model_id, body, stream=True), "content_events": deltas, "response_snippet": _snippet(n)}


def probe_system_prompt(t, model_id, model_key):
    prompt = "Say hello in one short sentence."
    if t.surface == "bedrock_converse":
        kw = {"system": [{"text": _SYSTEM_PROMPT}], "messages": [{"role": "user", "content": [{"text": prompt}]}],
              "inferenceConfig": {"maxTokens": _MAX}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(prompt, system=_SYSTEM_PROMPT)
        n = t.messages(model_id, kw)
    text = engine.text_of(n.content)
    return check_canary(text, CANARY), {"request": _req(model_id, kw), "response_snippet": text[:300]}


def _tool_call_evidence(n: NormalizedResponse, name: str) -> tuple[bool, dict]:
    tu = next((b for b in n.content if b.get("type") == "tool_use" and b.get("name") == name), None)
    call = {"name": name, "arguments": tu.get("input")} if tu else None
    return check_tool_roundtrip(call, CANARY), {"tool_call": _trim(call), "stop_reason": n.stop_reason}


def probe_tool_use(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        choice = {"tool": {"name": "echo"}} if supports_forced_tool_choice(model_id) else {"auto": {}}
        kw = {"messages": [{"role": "user", "content": [{"text": _TOOL_PROMPT}]}], "inferenceConfig": {"maxTokens": _TOOL_MAX},
              "toolConfig": {"tools": [{"toolSpec": {"name": "echo", "description": "Returns the given text unchanged.",
                                                     "inputSchema": {"json": _ECHO_SCHEMA}}}], "toolChoice": choice}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(_TOOL_PROMPT, max_tokens=_TOOL_MAX, tools=[_echo_tool()], tool_choice=_tool_choice(model_id, "echo"))
        n = t.messages(model_id, kw)
    ok, ev = _tool_call_evidence(n, "echo")
    return ok, {"request": _req(model_id, kw), **ev}


# ---------------------------------------------------------------- model capabilities

def probe_context_window_1m(t, model_id, model_key):
    gate = _route_or_unsupported(t, "models")
    if gate:
        return gate
    _, obj = t.request("GET", f"/v1/models/{model_id}")
    caps = {k: obj.get(k) for k in ("max_input_tokens", "max_tokens")}
    return obj.get("max_input_tokens") == 1_000_000, {"request": _req(model_id, path=f"/v1/models/{model_id}"), **caps}


def probe_adaptive_thinking(t, model_id, model_key):
    prompt = "What is the third prime number greater than 100? Think it through, then answer with just the number."
    thinking = {"type": "adaptive", "display": "summarized"}
    # effort medium에서는 adaptive 모델이 이 정도 문제에 사고를 생략한다(Fable 5.1 Bedrock 실측) →
    # 사고 여부는 프롬프트 난이도가 아니라 effort가 가른다. high로 고정해 블록을 요구한다.
    output_config = {"effort": "high"}
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": _THINK_MAX},
              "additionalModelRequestFields": {"thinking": thinking, "output_config": output_config}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(prompt, max_tokens=_THINK_MAX, thinking=thinking, output_config=output_config)
        n = t.messages(model_id, kw)
    th = engine.find_block(n.content, "thinking")
    return engine.has_thinking_evidence(n.content), {
        "request": _req(model_id, kw), "content_types": [b.get("type") for b in n.content],
        "thinking_chars": len((th or {}).get("thinking") or ""),
        "thinking_signed": bool((th or {}).get("signature")), "response_snippet": _snippet(n)}


def probe_extended_thinking(t, model_id, model_key):
    prompt = "What is 17 * 23? Answer with just the number."
    thinking = {"type": "enabled", "budget_tokens": 1024}
    try:
        if t.surface == "bedrock_converse":
            kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": 2048},
                  "additionalModelRequestFields": {"thinking": thinking}}
            n = t.converse(model_id, **kw)
        else:
            kw = _msg(prompt, max_tokens=2048, thinking=thinking)
            n = t.messages(model_id, kw)
    except TransportError as exc:
        low = str(exc).lower()
        if "thinking" in low and ("not supported" in low or "adaptive" in low or "validation" in low):
            return "not_applicable", {"request": _req(model_id, thinking=thinking),
                                      "reason": "adaptive-only model rejects budget_tokens as documented", "error": str(exc)[:500]}
        raise
    return engine.has_block(n.content, "thinking"), {"request": _req(model_id, kw), "content_types": [b.get("type") for b in n.content]}


def probe_batch_processing(t, model_id, model_key):
    gate = _route_or_unsupported(t, "batches")
    if gate:
        return gate
    req = {"requests": [{"custom_id": "features-probe-1",
                         "params": {"model": model_id, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]}}]}
    _, created = t.request("POST", "/v1/messages/batches", json=req)
    bid = created.get("id")
    _, got = t.request("GET", f"/v1/messages/batches/{bid}")
    try:
        t.request("POST", f"/v1/messages/batches/{bid}/cancel")
    except TransportError:
        pass
    ok = bool(bid) and got.get("processing_status") in ("in_progress", "canceling", "ended")
    return ok, {"request": _req(model_id, req), "batch_id": bid, "processing_status": got.get("processing_status")}


def _doc_question(t, model_id, doc_block: dict, converse_block: dict, question: str) -> tuple[NormalizedResponse, dict]:
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [converse_block, {"text": question}]}], "inferenceConfig": {"maxTokens": _JSON_MAX}}
        return t.converse(model_id, **kw), kw
    kw = _msg([doc_block, {"type": "text", "text": question}], max_tokens=_JSON_MAX)
    return t.messages(model_id, kw), kw


def probe_citations(t, model_id, model_key):
    text = f"The code word is {CANARY}. The sky is blue. Water boils at 100 degrees Celsius."
    doc = {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": text},
           "title": "Probe document", "citations": {"enabled": True}}
    cdoc = {"document": {"format": "txt", "name": "probe", "source": {"text": text}, "citations": {"enabled": True}}}
    n, kw = _doc_question(t, model_id, doc, cdoc, "What is the code word? Cite the document.")
    cited = [b for b in n.content if b.get("type") == "text" and b.get("citations")]
    return bool(cited), {"request": _req(model_id, kw), "citation_blocks": len(cited),
                         "first_citation": _trim((cited[0]["citations"][0] if cited else None)), "response_snippet": _snippet(n)}


def probe_search_results(t, model_id, model_key):
    text = f"The code word is {CANARY}."
    sr = {"type": "search_result", "source": "https://example.com/probe", "title": "Probe result",
          "content": [{"type": "text", "text": text}], "citations": {"enabled": True}}
    csr = {"searchResult": {"source": "https://example.com/probe", "title": "Probe result",
                            "content": [{"text": text}], "citations": {"enabled": True}}}
    n, kw = _doc_question(t, model_id, sr, csr, "What is the code word? Cite your source.")
    cites = [c for b in n.content if b.get("type") == "text" for c in (b.get("citations") or [])]
    ok = any(engine.citation_is_search_result(c) for c in cites)
    return ok, {"request": _req(model_id, kw), "citations": _trim(cites[:2]), "response_snippet": _snippet(n)}


def probe_pdf_support(t, model_id, model_key):
    pdf = _tiny_pdf(CANARY)
    b64 = base64.b64encode(pdf).decode()
    doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    cdoc = {"document": {"format": "pdf", "name": "probe", "source": {"bytes": pdf}}}
    n, kw = _doc_question(t, model_id, doc, cdoc, "What code word is written in the document? Reply with only the word.")
    text = engine.text_of(n.content)
    return check_canary(text, CANARY), {"request": _req(model_id, {"document": f"pdf {len(pdf)} bytes"}), "response_snippet": text[:300]}


def probe_data_residency(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
              "additionalModelRequestFields": {"inference_geo": "us"}}
        n = t.converse(model_id, **kw)
        return n.usage.get("inference_geo") == "us", {"request": _req(model_id, kw), "usage": n.usage}
    kw = _msg(_BASIC_PROMPT, inference_geo="us")
    n = t.messages(model_id, kw)
    ev = {"request": _req(model_id, kw), "usage_inference_geo": n.usage.get("inference_geo")}
    try:
        t.messages(model_id, _msg(_BASIC_PROMPT, inference_geo="mars"))
        ev["negative_control"] = "accepted (not validated)"
    except TransportError as exc:
        ev["negative_control"] = f"rejected: {str(exc)[:160]}"
    return n.usage.get("inference_geo") == "us", ev


_BAD_EFFORT = "ultra"


def probe_effort(t, model_id, model_key):
    def call(effort: str):
        if t.surface == "bedrock_converse":
            kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
                  "additionalModelRequestFields": {"output_config": {"effort": effort}}}
            return t.converse(model_id, **kw), kw
        kw = _msg(_BASIC_PROMPT, output_config={"effort": effort})
        return t.messages(model_id, kw), kw

    n, kw = call("low")
    ev = {"request": _req(model_id, kw), "output_tokens_low": n.usage.get("output_tokens"), "response_snippet": _snippet(n)}
    try:
        call(_BAD_EFFORT)
        ev["negative_control"] = "accepted (effort not validated)"
        return "inconclusive", ev
    except TransportError as exc:
        ev["negative_control"] = f"rejected: {str(exc)[:200]}"
        return engine.effort_rejection_names_param(str(exc), _BAD_EFFORT), ev


def probe_fallback_credit(t, model_id, model_key):
    beta = "fallback-credit-2026-06-01" if t.surface.startswith("bedrock") else "fallback-credit-2026-07-01"
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
              "additionalModelRequestFields": {"anthropic_beta": [beta]}}
        n = t.converse(model_id, **kw)
        return True, {"request": _req(model_id, kw), "stop_reason": n.stop_reason, "verification": "acceptance"}
    kw = _msg(_BASIC_PROMPT)
    n = t.messages(model_id, kw, betas=[beta])
    return True, {"request": _req(model_id, kw, betas=[beta]), "stop_reason": n.stop_reason,
                  "stop_details": n.top.get("stop_details"), "verification": "acceptance"}


def probe_server_side_fallback(t, model_id, model_key):
    beta = "server-side-fallback-2026-07-01"
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
              "additionalModelRequestFields": {"fallbacks": "default", "anthropic_beta": [beta]}}
        n = t.converse(model_id, **kw)
        return True, {"request": _req(model_id, kw), "model": n.top.get("model"), "verification": "acceptance"}
    kw = _msg(_BASIC_PROMPT, fallbacks="default")
    n = t.messages(model_id, kw, betas=[beta])
    return True, {"request": _req(model_id, kw, betas=[beta]), "served_model": n.top.get("model"),
                  "content_types": [b.get("type") for b in n.content], "verification": "acceptance"}


def probe_structured_outputs(t, model_id, model_key):
    prompt = "Give the capital city of South Korea and its country as JSON."
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": _JSON_MAX},
              "outputConfig": {"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {"schema": json.dumps(_JSON_SCHEMA)}}}}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(prompt, max_tokens=_JSON_MAX, output_config={"format": {"type": "json_schema", "schema": _JSON_SCHEMA}})
        n = t.messages(model_id, kw)
    text = engine.text_of(n.content)
    return check_json_object(text, "city"), {"request": _req(model_id, kw), "response_snippet": text[:300]}


def probe_strict_tool_use(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        choice = {"tool": {"name": "echo"}} if supports_forced_tool_choice(model_id) else {"auto": {}}
        kw = {"messages": [{"role": "user", "content": [{"text": _TOOL_PROMPT}]}], "inferenceConfig": {"maxTokens": _TOOL_MAX},
              "toolConfig": {"tools": [{"toolSpec": {"name": "echo", "description": "Returns the given text unchanged.",
                                                     "inputSchema": {"json": _ECHO_SCHEMA}, "strict": True}}], "toolChoice": choice}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(_TOOL_PROMPT, max_tokens=_TOOL_MAX, tools=[_echo_tool(strict=True)], tool_choice=_tool_choice(model_id, "echo"))
        n = t.messages(model_id, kw)
    tu = next((b for b in n.content if b.get("type") == "tool_use" and b.get("name") == "echo"), None)
    inp = (tu or {}).get("input")
    ok = isinstance(inp, dict) and set(inp) == {"text"} and CANARY in str(inp.get("text"))
    return ok, {"request": _req(model_id, kw), "tool_input": _trim(inp), "stop_reason": n.stop_reason}


PROBES: dict[str, Callable] = {
    "messages_basic": probe_messages_basic, "streaming": probe_streaming, "system_prompt": probe_system_prompt,
    "tool_use": probe_tool_use, "context_window_1m": probe_context_window_1m, "adaptive_thinking": probe_adaptive_thinking,
    "batch_processing": probe_batch_processing, "citations": probe_citations, "data_residency": probe_data_residency,
    "effort": probe_effort, "fallback_credit": probe_fallback_credit, "pdf_support": probe_pdf_support,
    "search_results": probe_search_results, "server_side_fallback": probe_server_side_fallback,
    "structured_outputs": probe_structured_outputs, "strict_tool_use": probe_strict_tool_use,
    "extended_thinking": probe_extended_thinking,
}


# ---------------------------------------------------------------- shared: beta/tool fallbacks

def _with_fallback(t: Transport, model_id: str, attempts: list[tuple[str, dict, list[str]]]) -> tuple[NormalizedResponse, dict]:
    """attempts = [(label, body, betas), ...] — 앞 시도가 '명시적 미지원' 400이면 다음 시도. 마지막 실패는 raise."""
    log: list[dict] = []
    for i, (label, body, betas) in enumerate(attempts):
        try:
            n = t.messages(model_id, body, betas=betas)
            log.append({"attempt": label, "result": "ok"})
            return n, {"attempts": log, "request": _req(model_id, body, betas=betas)}
        except TransportError as exc:
            log.append({"attempt": label, "result": str(exc)[:200]})
            if i == len(attempts) - 1 or engine.classify(str(exc)) != "unsupported":
                raise TransportError(exc.status_code, f"{exc.message} | attempts={json.dumps(log, ensure_ascii=False)[:600]}") from exc
    raise RuntimeError("unreachable")


def _tool_use_named(n: NormalizedResponse, *names: str, toolset: str | None = None) -> dict | None:
    for b in n.content:
        if b.get("type") != "tool_use":
            continue
        if b.get("name") in names or (toolset and b.get("toolset_name") == toolset):
            return b
    return None


def _server_tool_evidence(n: NormalizedResponse, tool_name: str, result_type: str) -> tuple[bool | str, dict]:
    used = any(b.get("type") == "server_tool_use" and b.get("name") == tool_name for b in n.content)
    result = engine.find_block(n.content, result_type)
    content = (result or {}).get("content")
    ev = {"server_tool_used": used, "result_type": (result or {}).get("type"), "stop_reason": n.stop_reason,
          "response_snippet": _snippet(n), "content_types": [b.get("type") for b in n.content]}
    if not used:
        return "inconclusive", {**ev, "reason": "model did not invoke the server tool"}
    if isinstance(content, dict) and content.get("type", "").endswith("_error"):
        return "inconclusive", {**ev, "reason": f"server tool error: {content.get('error_code')}"}
    return result is not None, ev


# ---------------------------------------------------------------- server-side tools

_ADVISOR_FOR = {"fable-5-1": "claude-fable-5-1", "fable-5": "claude-fable-5", "opus-5": "claude-opus-5", "sonnet-5": "claude-opus-5"}


def _advisor_model(model_key: str) -> str:
    return _ADVISOR_FOR[model_key]


def probe_advisor_tool(t, model_id, model_key):
    tool = {"type": "advisor_20260301", "name": "advisor", "model": _advisor_model(model_key), "max_uses": 1}
    prompt = "Before answering, consult the advisor tool once. Question: which number is larger, 7391 or 3917? Answer briefly."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[tool], tool_choice=_tool_choice(model_id, "advisor"))
    n = t.messages(model_id, kw, betas=["advisor-tool-2026-03-01"])
    used = any(b.get("type") == "server_tool_use" and b.get("name") == "advisor" for b in n.content)
    res = engine.find_block(n.content, "advisor_tool_result")
    ev = {"request": _req(model_id, kw, betas=["advisor-tool-2026-03-01"]), "server_tool_used": used,
          "advisor_result_type": ((res or {}).get("content") or {}).get("type"), "stop_reason": n.stop_reason}
    if not used:
        return "inconclusive", {**ev, "reason": "model did not call advisor"}
    return res is not None, ev


def probe_code_execution(t, model_id, model_key):
    prompt = "Use the code execution tool to run this Python: print(7391*3). Then reply with only the printed number."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "code_execution_20260521", "name": "code_execution"}])
    n = t.messages(model_id, kw)
    res = engine.find_block(n.content, "bash_code_execution_tool_result")
    stdout = str(((res or {}).get("content") or {}).get("stdout", ""))
    status, ev = _server_tool_evidence(n, "bash_code_execution", "bash_code_execution_tool_result")
    ev.update({"request": _req(model_id, kw), "stdout": stdout[:200], "container": n.top.get("container")})
    if status is True:
        return "22173" in stdout or "22173" in engine.text_of(n.content), ev
    return status, ev


def probe_web_fetch(t, model_id, model_key):
    url = "https://www.iana.org/help/example-domains"
    prompt = f"Fetch {url} with the web_fetch tool and tell me its first heading in one line."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 1}])
    n = t.messages(model_id, kw)
    status, ev = _server_tool_evidence(n, "web_fetch", "web_fetch_tool_result")
    return status, {"request": _req(model_id, kw), **ev}


def probe_web_search(t, model_id, model_key):
    prompt = "Use the web_search tool once to find the current list of Anthropic Claude models, then name one model in one line."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 1}])
    n = t.messages(model_id, kw)
    status, ev = _server_tool_evidence(n, "web_search", "web_search_tool_result")
    res = engine.find_block(n.content, "web_search_tool_result")
    ev["results"] = len((res or {}).get("content") or []) if isinstance((res or {}).get("content"), list) else 0
    return status, {"request": _req(model_id, kw), **ev}


# ---------------------------------------------------------------- client-side tools (definition acceptance + tool_use emission)

def _client_tool_probe(t, model_id, tool: dict, prompt: str, tool_name: str, betas: list[str] | None = None,
                       fallback_betas: list[str] | None = None):
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[tool], tool_choice=_tool_choice(model_id, tool_name))
    attempts = [("no-beta" if not betas else ",".join(betas), kw, betas or [])]
    if fallback_betas:
        attempts.append((",".join(fallback_betas), kw, fallback_betas))
    n, ev = _with_fallback(t, model_id, attempts)
    tu = _tool_use_named(n, tool_name)
    ev.update({"tool_call": _trim({"name": (tu or {}).get("name"), "input": (tu or {}).get("input")}), "stop_reason": n.stop_reason})
    if tu is None:
        return "inconclusive", {**ev, "reason": "tool definition accepted but the model did not call it"}
    return True, ev


def probe_bash_tool(t, model_id, model_key):
    return _client_tool_probe(t, model_id, {"type": "bash_20250124", "name": "bash"},
                              f"Use the bash tool to run: echo {CANARY}", "bash", fallback_betas=["computer-use-2025-01-24"])


def probe_text_editor(t, model_id, model_key):
    return _client_tool_probe(t, model_id, {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
                              "Use the text editor tool to view the file /tmp/probe.txt", "str_replace_based_edit_tool",
                              fallback_betas=["computer-use-2025-01-24"])


def probe_memory_tool(t, model_id, model_key):
    return _client_tool_probe(t, model_id, {"type": "memory_20250818", "name": "memory"},
                              "Check your memory directory first, then say hello.", "memory",
                              fallback_betas=["context-management-2025-06-27"])


def probe_browser_use(t, model_id, model_key):
    kw = _msg("Take a screenshot of the current browser page using the browser tools.", max_tokens=_TOOL_MAX,
              tools=[{"type": "browser_toolset_20260801"}])
    n = t.messages(model_id, kw)
    tu = _tool_use_named(n, toolset="browser")
    ev = {"request": _req(model_id, kw), "tool_call": _trim(tu), "stop_reason": n.stop_reason}
    return (True, ev) if tu else ("inconclusive", {**ev, "reason": "toolset accepted but no browser tool_use"})


def probe_computer_use(t, model_id, model_key):
    prompt = "Take a screenshot of the screen using the computer tool."
    toolset = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "computer_toolset_20260801"}])
    legacy = _msg(prompt, max_tokens=_TOOL_MAX,
                  tools=[{"type": "computer_20251124", "name": "computer", "display_width_px": 1024, "display_height_px": 768}],
                  tool_choice=_tool_choice(model_id, "computer"))
    n, ev = _with_fallback(t, model_id, [("computer_toolset_20260801", toolset, []),
                                         ("computer_20251124+beta", legacy, ["computer-use-2025-11-24"])])
    tu = _tool_use_named(n, "computer", toolset="computer")
    ev.update({"tool_call": _trim(tu), "stop_reason": n.stop_reason})
    return (True, ev) if tu else ("inconclusive", {**ev, "reason": "tool accepted but no computer tool_use"})


# ---------------------------------------------------------------- tool infrastructure

def probe_agent_skills(t, model_id, model_key):
    # 컨테이너는 코드 실행의 부산물이므로 실제 실행을 지시해야 container.id가 생긴다
    # (질문만 하면 모델이 스킬 메타데이터로 답하고 컨테이너를 만들지 않아 false-broken).
    kw = _msg("Use the code execution tool to run this bash command: ls /mnt/skills. "
              "Then reply in one line with what you saw.", max_tokens=_TOOL_MAX,
              tools=[{"type": "code_execution_20260521", "name": "code_execution"}],
              container={"skills": [{"type": "anthropic", "skill_id": "pdf", "version": "latest"}]})
    n = t.messages(model_id, kw)
    container = n.top.get("container") or {}
    ev = {"request": _req(model_id, kw), "container": _trim(n.top.get("container")),
          "container_skills": [s.get("skill_id") for s in (container.get("skills") or []) if isinstance(s, dict)],
          "response_snippet": _snippet(n)}
    if "skills" in t.routes:
        try:
            _, skills = t.request("GET", "/v1/skills")
            ev["skills_listed"] = len(skills.get("data", [])) if isinstance(skills, dict) else None
        except TransportError as exc:
            ev["skills_listed"] = f"error: {str(exc)[:120]}"
    if not container.get("id") and not any(b.get("type") == "server_tool_use" for b in n.content):
        return "inconclusive", {**ev, "reason": "container.skills accepted but the model did not run code (no container created)"}
    return bool(container.get("id")), ev


def probe_fine_grained_tool_streaming(t, model_id, model_key):
    long_text = ("lorem ipsum dolor sit amet " * 12).strip()
    kw = _msg(f"Call the echo tool once with text set to exactly: {long_text}", max_tokens=_TOOL_MAX,
              tools=[_echo_tool(eager=True)], tool_choice=_tool_choice(model_id, "echo"))
    n = t.messages(model_id, kw, stream=True)
    deltas = _content_deltas(n.events, "input_json_delta")
    return deltas >= 2, {"request": _req(model_id, kw, stream=True), "input_json_deltas": deltas,
                         "tool_call": _trim(_tool_use_named(n, "echo"))}


def probe_mcp_connector(t, model_id, model_key):
    url = os.environ.get("FEATURES_MCP_SERVER_URL", "https://mcp.deepwiki.com/mcp")
    kw = _msg("List the tools offered by the probe-mcp server and call one of them with a trivial input, then summarize in one line.",
              max_tokens=_TOOL_MAX, mcp_servers=[{"type": "url", "url": url, "name": "probe-mcp"}],
              tools=[{"type": "mcp_toolset", "mcp_server_name": "probe-mcp"}])
    try:
        n = t.messages(model_id, kw, betas=["mcp-client-2025-11-20"])
    except TransportError as exc:
        low = str(exc).lower()
        if any(k in low for k in ("connect", "unreachable", "timed out", "mcp server", "failed to")) and engine.classify(str(exc)) != "unsupported":
            return "inconclusive", {"request": _req(model_id, kw), "reason": f"MCP server unreachable: {str(exc)[:200]}"}
        raise
    used = engine.has_block(n.content, "mcp_tool_use")
    ev = {"request": _req(model_id, kw, betas=["mcp-client-2025-11-20"]), "mcp_tool_use": used,
          "mcp_tool_result": engine.has_block(n.content, "mcp_tool_result"), "response_snippet": _snippet(n)}
    return (True, ev) if used else ("inconclusive", {**ev, "reason": "MCP toolset accepted but no mcp_tool_use"})


def probe_programmatic_tool_calling(t, model_id, model_key):
    tool = {"name": "get_number", "description": "Returns a secret integer for the given index.",
            "input_schema": {"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"]},
            "allowed_callers": ["code_execution_20260120"]}
    kw = _msg("Write and run code that calls get_number for index 1, 2 and 3 and prints the sum.", max_tokens=2048,
              tools=[{"type": "code_execution_20260120", "name": "code_execution"}, tool])
    n = t.messages(model_id, kw)
    tu = next((b for b in n.content if b.get("type") == "tool_use" and (b.get("caller") or {}).get("type") == "code_execution_20260120"), None)
    ev = {"request": _req(model_id, kw), "container": n.top.get("container"), "caller": (tu or {}).get("caller"),
          "stop_reason": n.stop_reason, "content_types": [b.get("type") for b in n.content]}
    return (True, ev) if tu else ("inconclusive", {**ev, "reason": "no tool_use with code_execution caller"})


def probe_tool_search(t, model_id, model_key):
    deferred = [{"name": f"get_{k}", "description": d, "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                 "defer_loading": True}
                for k, d in (("weather", "Current weather for a city"), ("time", "Current time in a timezone"), ("stock", "Stock quote"))]
    kw = _msg("Find the tool that gives weather for Seoul and call it.", max_tokens=_TOOL_MAX,
              tools=[{"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"}, *deferred])
    betas = ["tool-search-tool-2025-10-19"] if t.surface in ("bedrock_invoke", "bedrock_messages") else []
    n = t.messages(model_id, kw, betas=betas)
    searched = any(b.get("type") == "server_tool_use" and b.get("name") == "tool_search_tool_regex" for b in n.content)
    ev = {"request": _req(model_id, kw, betas=betas), "tool_search_used": searched,
          "tool_search_result": engine.has_block(n.content, "tool_search_tool_result"),
          "called": (_tool_use_named(n, "get_weather") or {}).get("name"), "stop_reason": n.stop_reason}
    return (True, ev) if searched else ("inconclusive", {**ev, "reason": "tool search tool accepted but not used"})


# ---------------------------------------------------------------- context management

def probe_compaction(t, model_id, model_key):
    cm = {"edits": [{"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": 50000}}]}
    kw = _msg(_BASIC_PROMPT, context_management=cm)
    n = t.messages(model_id, kw, betas=["compact-2026-01-12"])
    ev = {"request": _req(model_id, kw, betas=["compact-2026-01-12"]), "verification": "acceptance", "stop_reason": n.stop_reason}
    if "models" in t.routes:
        try:
            _, m = t.request("GET", f"/v1/models/{model_id}")
            ev["capability_compact_20260112"] = (((m.get("capabilities") or {}).get("context_management") or {}).get("compact_20260112") or {}).get("supported")
        except TransportError as exc:
            ev["capability_compact_20260112"] = f"error: {str(exc)[:120]}"
    return True, ev


def probe_context_editing(t, model_id, model_key):
    cm = {"edits": [{"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 100000}}]}
    kw = _msg(_BASIC_PROMPT, context_management=cm)
    n = t.messages(model_id, kw, betas=["context-management-2025-06-27"])
    applied = (n.top.get("context_management") or {}).get("applied_edits")
    return applied is not None, {"request": _req(model_id, kw, betas=["context-management-2025-06-27"]),
                                 "applied_edits": applied, "stop_reason": n.stop_reason}


def _cache_pair(t, model_id, kw_builder) -> tuple[dict, NormalizedResponse, NormalizedResponse]:
    """같은 프롬프트를 두 번 호출한다 — 1번째가 캐시를 쓰고 2번째가 읽어야 증거가 성립한다."""
    kw = kw_builder()
    if t.surface == "bedrock_converse":
        return kw, t.converse(model_id, **kw), t.converse(model_id, **kw)
    return kw, t.messages(model_id, kw), t.messages(model_id, kw)


def _cache_evidence(model_id: str, kw: dict, n1: NormalizedResponse, n2: NormalizedResponse) -> tuple[dict, str | None]:
    """캐시 프로브 공통 증거 + 차단 사유. 차단된 완료는 캐시를 읽지 않으므로 측정 자체가 불가하다.

    `stop_reason`·`stop_details`를 두 호출 모두 남긴다 — 차단 카테고리(예: refusal/cyber,
    refusal/reasoning_extraction)가 트리아지의 결정적 단서였는데 이유 문자열만으로는 복원되지 않는다.
    Converse에는 stop_details가 없어 None이 들어간다.
    """
    ev = {"request": _req(model_id, kw), "first_usage": n1.usage, "second_usage": n2.usage,
          "stop_reason": [n1.stop_reason, n2.stop_reason],
          "stop_details": [_trim(n1.top.get("stop_details")), _trim(n2.top.get("stop_details"))]}
    return ev, engine.blocked_stop_reason(n1.stop_reason, n2.stop_reason)


def _cache_read_verdict(ev: dict, blocked: str | None, n2: NormalizedResponse, label: str):
    """캐시 3프로브 공통 판정 — 2차 호출의 `cache_read_input_tokens > 0`만 supported로 인정한다.

    캐시 *생성*(cache_creation / ephemeral_1h)은 프롬프트가 최소 길이를 넘겼다는 뜻일 뿐
    캐시가 실제로 재사용됐다는 증거가 아니다. 생성만으로 통과시키면 거부된 완료도 초록으로
    보인다(2026-09-05 전체 스윕에서 실제로 그랬다) → 보조 필드로만 남긴다.
    """
    if blocked:
        return "inconclusive", {**ev, "reason": f"completion blocked ({blocked}) — {label} not measurable"}
    return engine.usage_int(n2.usage, "cache_read_input_tokens") > 0, ev


def probe_automatic_prompt_caching(t, model_id, model_key):
    kw, n1, n2 = _cache_pair(t, model_id, lambda: _msg(_BASIC_PROMPT, system=CACHE_PAD, cache_control={"type": "ephemeral"}))
    ev, blocked = _cache_evidence(model_id, kw, n1, n2)
    ev["first_call_cache_creation"] = engine.usage_int(n1.usage, "cache_creation_input_tokens")
    return _cache_read_verdict(ev, blocked, n2, "cache usage")


def probe_prompt_caching_5m(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        builder = lambda: {"system": [{"text": CACHE_PAD}, {"cachePoint": {"type": "default"}}],  # noqa: E731
                           "messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX}}
    else:
        builder = lambda: _msg(_BASIC_PROMPT, system=[{"type": "text", "text": CACHE_PAD, "cache_control": {"type": "ephemeral"}}])  # noqa: E731
    kw, n1, n2 = _cache_pair(t, model_id, builder)
    ev, blocked = _cache_evidence(model_id, kw, n1, n2)
    return _cache_read_verdict(ev, blocked, n2, "cache read")


def probe_prompt_caching_1h(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        builder = lambda: {"system": [{"text": CACHE_PAD}, {"cachePoint": {"type": "default", "ttl": "1h"}}],  # noqa: E731
                           "messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX}}
    else:
        builder = lambda: _msg(_BASIC_PROMPT, system=[{"type": "text", "text": CACHE_PAD, "cache_control": {"type": "ephemeral", "ttl": "1h"}}])  # noqa: E731
    kw, n1, n2 = _cache_pair(t, model_id, builder)
    u1 = n1.usage
    ev, blocked = _cache_evidence(model_id, kw, n1, n2)
    ev["ephemeral_1h_input_tokens"] = engine.usage_int(
        (u1.get("cache_creation") or {}) if isinstance(u1.get("cache_creation"), dict) else {}, "ephemeral_1h_input_tokens")
    return _cache_read_verdict(ev, blocked, n2, "1h cache read")


def probe_token_counting(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}]}
        r = t.count_tokens_converse(model_id, **kw)
    else:
        kw = _msg(_BASIC_PROMPT)
        r = t.count_tokens(model_id, kw)
    n = r.get("input_tokens")
    return isinstance(n, int) and n > 0, {"request": _req(model_id, kw, endpoint="count_tokens"), "input_tokens": n}


# ---------------------------------------------------------------- files & endpoints

def probe_files_api(t, model_id, model_key):
    gate = _route_or_unsupported(t, "files")
    if gate:
        return gate
    _, up = t.request("POST", "/v1/files", files={"file": ("features-probe.txt", b"Claude API Features probe file.\n", "text/plain")})
    fid = up.get("id")
    ev = {"request": _req(model_id, endpoint="/v1/files"), "file_id": fid, "type": up.get("type")}
    try:
        _, got = t.request("GET", f"/v1/files/{fid}")
        ev["get_ok"] = got.get("id") == fid
    finally:
        try:
            t.request("DELETE", f"/v1/files/{fid}")
            ev["deleted"] = True
        except TransportError as exc:
            ev["deleted"] = f"error: {str(exc)[:120]}"
    return up.get("type") == "file" and bool(fid), ev


def probe_models_api(t, model_id, model_key):
    gate = _route_or_unsupported(t, "models")
    if gate:
        return gate
    _, m = t.request("GET", f"/v1/models/{model_id}")
    return m.get("id") == model_id and "capabilities" in m, {"request": _req(model_id, endpoint=f"/v1/models/{model_id}"),
                                                              "retrieved_id": m.get("id"), "capabilities": _trim(m.get("capabilities"))}


PROBES.update({
    "advisor_tool": probe_advisor_tool, "code_execution": probe_code_execution, "web_fetch": probe_web_fetch, "web_search": probe_web_search,
    "bash_tool": probe_bash_tool, "browser_use": probe_browser_use, "computer_use": probe_computer_use,
    "memory_tool": probe_memory_tool, "text_editor": probe_text_editor,
    "agent_skills": probe_agent_skills, "fine_grained_tool_streaming": probe_fine_grained_tool_streaming,
    "mcp_connector": probe_mcp_connector, "programmatic_tool_calling": probe_programmatic_tool_calling, "tool_search": probe_tool_search,
    "compaction": probe_compaction, "context_editing": probe_context_editing,
    "automatic_prompt_caching": probe_automatic_prompt_caching, "prompt_caching_5m": probe_prompt_caching_5m,
    "prompt_caching_1h": probe_prompt_caching_1h, "token_counting": probe_token_counting,
    "files_api": probe_files_api, "models_api": probe_models_api,
})
