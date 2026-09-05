"""세 Claude-on-AWS 엔드포인트 전송기 (v2.23.0) — 하나의 Anthropic Messages JSON 본문을 그대로 흘린다.

SDK를 쓰지 않는 이유: requirements.txt의 anthropic>=0.40.0 미고정 → 빌드 시 1.x 메이저 업.
raw httpx(CP/Mantle) + boto3(Bedrock)로 본문/헤더를 직접 제어해 판정을 SDK 표면 변화에서 격리한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

#: `request(..., json=...)` 파라미터가 모듈명을 가리므로 오류 직렬화는 별칭으로 한다.
_json = json

ANTHROPIC_VERSION = "2023-06-01"
BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"
_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)


class TransportError(Exception):
    def __init__(self, status_code: int | None, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}" if status_code else message)


@dataclass
class NormalizedResponse:
    content: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None
    top: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    raw: Any = None


# ---------------------------------------------------------------- pure helpers

def beta_header(betas) -> dict[str, str]:
    betas = [b for b in (betas or []) if b]
    return {"anthropic-beta": ",".join(betas)} if betas else {}


def invoke_body(body: dict, betas) -> dict:
    """Anthropic Messages 본문 → Bedrock InvokeModel 본문 (model/stream 제거, version·anthropic_beta 주입)."""
    out = {k: v for k, v in body.items() if k not in ("model", "stream")}
    out["anthropic_version"] = BEDROCK_ANTHROPIC_VERSION
    betas = [b for b in (betas or []) if b]
    if betas:
        out["anthropic_beta"] = betas
    return out


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except ValueError:
            continue
    return events


def normalize_anthropic(obj: dict, events: list[dict] | None = None) -> NormalizedResponse:
    top = {k: v for k, v in obj.items() if k not in ("content", "usage")}
    return NormalizedResponse(content=list(obj.get("content") or []), usage=dict(obj.get("usage") or {}),
                              stop_reason=obj.get("stop_reason"), top=top, events=list(events or []), raw=obj)


def assemble_stream(events: list[dict]) -> dict:
    """SSE 이벤트 → 최종 message dict (content 블록·usage·stop_reason 재조립)."""
    msg: dict = {"content": [], "usage": {}}
    blocks: dict[int, dict] = {}
    for ev in events:
        t = ev.get("type")
        if t == "message_start":
            m = ev.get("message") or {}
            msg.update({k: v for k, v in m.items() if k not in ("content",)})
            msg["usage"] = dict(m.get("usage") or {})
        elif t == "content_block_start":
            blocks[ev["index"]] = dict(ev.get("content_block") or {})
            if blocks[ev["index"]].get("type") == "tool_use":
                blocks[ev["index"]].setdefault("_json", "")
        elif t == "content_block_delta":
            d = ev.get("delta") or {}
            b = blocks.setdefault(ev["index"], {"type": "text", "text": ""})
            if d.get("type") == "text_delta":
                b["text"] = b.get("text", "") + d.get("text", "")
            elif d.get("type") == "input_json_delta":
                b["_json"] = b.get("_json", "") + d.get("partial_json", "")
            elif d.get("type") == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + d.get("thinking", "")
            elif d.get("type") == "signature_delta":
                b["signature"] = d.get("signature")
            elif d.get("type") == "citations_delta":
                b.setdefault("citations", []).append(d.get("citation"))
        elif t == "message_delta":
            d = ev.get("delta") or {}
            if d.get("stop_reason"):
                msg["stop_reason"] = d["stop_reason"]
            for k, v in (ev.get("usage") or {}).items():
                msg["usage"][k] = v
            for k in ("context_management", "container", "stop_details"):
                if k in d:
                    msg[k] = d[k]
    for i in sorted(blocks):
        b = blocks[i]
        if "_json" in b:
            try:
                b["input"] = json.loads(b.pop("_json") or "{}")
            except ValueError:
                b["input"] = b.pop("_json")
        msg["content"].append(b)
    return msg


def normalize_converse(resp: dict) -> NormalizedResponse:
    blocks: list[dict] = []
    for b in ((resp.get("output") or {}).get("message") or {}).get("content", []):
        if "text" in b:
            blocks.append({"type": "text", "text": b["text"]})
        elif "toolUse" in b:
            tu = b["toolUse"]
            blocks.append({"type": "tool_use", "id": tu.get("toolUseId"), "name": tu.get("name"), "input": tu.get("input")})
        elif "reasoningContent" in b:
            rc = b["reasoningContent"]
            blocks.append({"type": "thinking", "thinking": (rc.get("reasoningText") or {}).get("text", ""),
                           "signature": (rc.get("reasoningText") or {}).get("signature")})
        elif "citationsContent" in b:
            cc = b["citationsContent"]
            blocks.append({"type": "text", "text": "".join(c.get("text", "") for c in cc.get("content", [])),
                           "citations": cc.get("citations", [])})
        else:
            blocks.append({"type": next(iter(b.keys()), "unknown"), "raw": b})
    u = resp.get("usage") or {}
    usage = {"input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0),
             "cache_read_input_tokens": u.get("cacheReadInputTokens", 0),
             "cache_creation_input_tokens": u.get("cacheWriteInputTokens", 0)}
    top = {k: v for k, v in resp.items() if k not in ("output", "usage", "ResponseMetadata")}
    return NormalizedResponse(content=blocks, usage=usage, stop_reason=resp.get("stopReason"), top=top, raw=resp)


def _snippet_bytes(b: bytes | str, n: int = 800) -> str:
    s = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
    return s[:n]


# ---------------------------------------------------------------- base

class Transport:
    surface: str = ""
    region: str = ""
    routes: frozenset[str] = frozenset()

    def messages(self, model_id: str, body: dict, betas=(), stream: bool = False) -> NormalizedResponse:
        raise NotImplementedError

    def count_tokens(self, model_id: str, body: dict, betas=()) -> dict:
        raise NotImplementedError

    def request(self, method: str, path: str, json: Any = None, betas=(), files=None, data=None) -> tuple[int, Any]:
        raise TransportError(None, f"no route: {self.surface} has no HTTP endpoint for {path}")


class _HttpTransport(Transport):
    base_url: str = ""
    routes = frozenset({"messages", "count_tokens", "batches", "files", "models", "skills"})

    def _headers(self, betas=()) -> dict[str, str]:
        raise NotImplementedError

    def request(self, method: str, path: str, json: Any = None, betas=(), files=None, data=None) -> tuple[int, Any]:
        headers = self._headers(betas)
        if files is not None or data is not None:
            headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.request(method, self.base_url + path, json=json, headers=headers, files=files, data=data)
        parsed: Any
        try:
            parsed = r.json()
        except ValueError:
            parsed = _snippet_bytes(r.content)
        if r.status_code >= 400:
            msg = parsed if isinstance(parsed, str) else _json.dumps(parsed, ensure_ascii=False)[:1500]
            raise TransportError(r.status_code, msg)
        return r.status_code, parsed

    def messages(self, model_id: str, body: dict, betas=(), stream: bool = False) -> NormalizedResponse:
        payload = {**body, "model": model_id}
        headers = self._headers(betas)
        if not stream:
            _, obj = self.request("POST", "/v1/messages", json=payload, betas=betas)
            return normalize_anthropic(obj)
        payload["stream"] = True
        with httpx.Client(timeout=_TIMEOUT) as c, c.stream("POST", self.base_url + "/v1/messages",
                                                            json=payload, headers=headers) as r:
            text = r.read().decode("utf-8", "replace")
            if r.status_code >= 400:
                raise TransportError(r.status_code, text[:1500])
        events = parse_sse(text)
        return normalize_anthropic(assemble_stream(events), events)

    def count_tokens(self, model_id: str, body: dict, betas=()) -> dict:
        payload = {k: v for k, v in body.items() if k not in ("max_tokens", "stream")}
        payload["model"] = model_id
        _, obj = self.request("POST", "/v1/messages/count_tokens", json=payload, betas=betas)
        return obj


class CpTransport(_HttpTransport):
    surface = "cp"

    def __init__(self, region: str | None = None):
        from claude_features.catalog import region_for
        from prober import _anthropic_default_headers
        self.region = region or region_for("cp")
        self.base_url = f"https://aws-external-anthropic.{self.region}.api.aws"
        self._api_key = os.environ["ANTHROPIC_API_KEY"]
        self._extra = _anthropic_default_headers()

    def _headers(self, betas=()) -> dict[str, str]:
        return {"x-api-key": self._api_key, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json", **self._extra, **beta_header(betas)}


class MantleTransport(_HttpTransport):
    surface = "mantle"

    def __init__(self, region: str | None = None):
        from aws_bedrock_token_generator import provide_token
        from claude_features.catalog import region_for
        self.region = region or region_for("mantle")
        self.base_url = f"https://bedrock-mantle.{self.region}.api.aws/anthropic"
        self._token = provide_token(region=self.region)  # 런 동안 재사용 (≤12h)

    def _headers(self, betas=()) -> dict[str, str]:
        return {"x-api-key": self._token, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json", **beta_header(betas)}


def _boto_client(region: str):
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=region,
                        config=Config(connect_timeout=10, read_timeout=90, retries={"max_attempts": 2, "mode": "standard"}))


def _client_error(exc: Exception) -> TransportError:
    resp = getattr(exc, "response", None) or {}
    err = resp.get("Error") or {}
    status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    code, msg = err.get("Code", type(exc).__name__), err.get("Message", str(exc))
    return TransportError(status, f"{code}: {msg}")


class BedrockInvokeTransport(Transport):
    surface = "bedrock_invoke"
    routes = frozenset({"messages", "count_tokens"})

    def __init__(self, region: str | None = None):
        from claude_features.catalog import region_for
        self.region = region or region_for("bedrock_invoke")
        self.client = _boto_client(self.region)

    def messages(self, model_id: str, body: dict, betas=(), stream: bool = False) -> NormalizedResponse:
        native = invoke_body(body, betas)
        try:
            if not stream:
                r = self.client.invoke_model(modelId=model_id, body=json.dumps(native))
                return normalize_anthropic(json.loads(r["body"].read()))
            r = self.client.invoke_model_with_response_stream(modelId=model_id, body=json.dumps(native))
            events = [json.loads(e["chunk"]["bytes"]) for e in r["body"] if "chunk" in e]
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        return normalize_anthropic(assemble_stream(events), events)

    def count_tokens(self, model_id: str, body: dict, betas=()) -> dict:
        native = invoke_body({k: v for k, v in body.items() if k != "max_tokens"}, betas)
        try:
            r = self.client.count_tokens(modelId=model_id, input={"invokeModel": {"body": json.dumps(native)}})
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        return {"input_tokens": r.get("inputTokens")}


class BedrockConverseTransport(Transport):
    surface = "bedrock_converse"
    routes = frozenset({"converse", "count_tokens"})

    def __init__(self, region: str | None = None):
        from claude_features.catalog import region_for
        self.region = region or region_for("bedrock_converse")
        self.client = _boto_client(self.region)

    def converse(self, model_id: str, stream: bool = False, **kw) -> NormalizedResponse:
        try:
            if not stream:
                return normalize_converse(self.client.converse(modelId=model_id, **kw))
            r = self.client.converse_stream(modelId=model_id, **kw)
            events = list(r["stream"])
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        blocks: dict[int, dict] = {}
        stop, usage = None, {}
        for ev in events:
            if "contentBlockStart" in ev:
                s = ev["contentBlockStart"]
                start = s.get("start") or {}
                idx = s.get("contentBlockIndex", len(blocks))
                if "toolUse" in start:
                    blocks[idx] = {"toolUse": {"toolUseId": start["toolUse"].get("toolUseId"),
                                               "name": start["toolUse"].get("name"), "_input": ""}}
            elif "contentBlockDelta" in ev:
                cbd = ev["contentBlockDelta"]
                idx = cbd.get("contentBlockIndex", 0)
                d = cbd.get("delta") or {}
                b = blocks.setdefault(idx, {})
                if "text" in d:
                    b["text"] = b.get("text", "") + d["text"]
                elif "toolUse" in d:
                    b.setdefault("toolUse", {"_input": ""})["_input"] += d["toolUse"].get("input", "")
                elif "reasoningContent" in d:
                    rc = d["reasoningContent"]
                    r = b.setdefault("reasoningContent", {"reasoningText": {"text": ""}})
                    if "text" in rc:
                        r["reasoningText"]["text"] += rc["text"]
                    if "signature" in rc:
                        r["reasoningText"]["signature"] = rc["signature"]
            elif "messageStop" in ev:
                stop = ev["messageStop"].get("stopReason")
            elif "metadata" in ev:
                usage = ev["metadata"].get("usage") or {}
        content: list[dict] = []
        for i in sorted(blocks):
            b = blocks[i]
            if "toolUse" in b:
                tu = b["toolUse"]
                raw = tu.pop("_input", "")
                try:
                    tu["input"] = json.loads(raw or "{}")
                except ValueError:
                    tu["input"] = raw
                content.append({"toolUse": tu})
            elif "reasoningContent" in b:
                content.append({"reasoningContent": b["reasoningContent"]})
            else:
                content.append({"text": b.get("text", "")})
        n = normalize_converse({"output": {"message": {"content": content}}, "usage": usage, "stopReason": stop})
        n.events = events
        return n

    def count_tokens_converse(self, model_id: str, **kw) -> dict:
        try:
            r = self.client.count_tokens(modelId=model_id, input={"converse": kw})
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        return {"input_tokens": r.get("inputTokens")}


def build_transport(surface: str) -> Transport:
    return {"cp": CpTransport, "mantle": MantleTransport,
            "bedrock_invoke": BedrockInvokeTransport, "bedrock_converse": BedrockConverseTransport}[surface]()
