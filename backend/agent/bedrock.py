"""Bedrock Converse(Stream) 클라이언트 — 챗봇·인사이트 잡 공통.

설계 원칙 (NFR-4):
  - 챗봇/사용자 응답은 converse_stream 사용 (토큰 단위 즉시 emit).
  - 인사이트 배치 잡은 converse 사용 가능 (스트리밍 불필요).
  - tool_use 응답을 받으면 호출자가 tool 실행 후 tool_result로 다시 호출.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator, Dict, Iterable, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# 챗봇 기본 모델 — Seoul deployment에서는 global inference profile 사용.
CHAT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
INSIGHTS_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


def _client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-runtime", region_name=region)


def tool_spec_for(name: str, description: str, input_schema: dict) -> dict:
    """Bedrock Converse API tool spec 형태로 변환."""
    return {
        "toolSpec": {
            "name": name,
            "description": description,
            "inputSchema": {"json": input_schema},
        }
    }


DEFAULT_CHAT_SYSTEM = (
    "당신은 AWS Bedrock LLM 모니터링 도구의 한국어 어시스턴트입니다.\n"
    "사용자의 질문에 답하기 위해 제공된 도구를 사용해 데이터를 조회하고, "
    "정확한 수치와 함께 간결한 한국어로 응답하세요. 모르는 정보는 추측하지 않습니다."
)


async def converse_stream_chat(
    messages: List[Dict],
    *,
    model_id: str = CHAT_MODEL_ID,
    system: str = DEFAULT_CHAT_SYSTEM,
    tools: Optional[List[dict]] = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> AsyncIterator[Dict]:
    """챗봇용 ConverseStream — 이벤트를 비동기 generator로 yield.

    yield되는 dict 형태:
      {"type": "text_delta", "text": ...}
      {"type": "tool_use", "tool_use": {name, input, toolUseId}}
      {"type": "stop", "stop_reason": "tool_use" | "end_turn" | ..., "usage": {...}}
    """
    params: Dict = {
        "modelId": model_id,
        "messages": messages,
        "system": [{"text": system}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if tools:
        params["toolConfig"] = {"tools": tools}

    try:
        response = _client().converse_stream(**params)
    except ClientError as exc:
        logger.exception("Bedrock converse_stream 호출 실패")
        yield {"type": "error", "error": str(exc)}
        return

    stream = response.get("stream")
    if stream is None:
        yield {"type": "error", "error": "Bedrock 응답에 stream 없음"}
        return

    current_tool_input = ""
    current_tool_name: Optional[str] = None
    current_tool_use_id: Optional[str] = None

    for event in stream:
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            tool_use = start.get("toolUse")
            if tool_use:
                current_tool_name = tool_use.get("name")
                current_tool_use_id = tool_use.get("toolUseId")
                current_tool_input = ""

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text")
            if text:
                yield {"type": "text_delta", "text": text}
                # async event loop tick - sync stream iter가 uvicorn send를 막지 않도록
                # 매 yield 후 강제로 cede 해서 uvicorn이 chunk를 즉시 client로 flush.
                await asyncio.sleep(0)
                continue
            tool_input = delta.get("toolUse", {}).get("input")
            if tool_input is not None:
                current_tool_input += tool_input

        elif "contentBlockStop" in event:
            if current_tool_name and current_tool_use_id:
                # tool_use 누적 JSON 텍스트를 파싱하여 emit.
                import json as _json

                try:
                    parsed_input = _json.loads(current_tool_input) if current_tool_input else {}
                except _json.JSONDecodeError:
                    parsed_input = {"_raw": current_tool_input}
                yield {
                    "type": "tool_use",
                    "tool_use": {
                        "name": current_tool_name,
                        "input": parsed_input,
                        "toolUseId": current_tool_use_id,
                    },
                }
                current_tool_name = None
                current_tool_use_id = None
                current_tool_input = ""

        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
            yield {"type": "stop", "stop_reason": stop_reason}

        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            yield {"type": "usage", "usage": usage}


def converse_blocking(
    messages: List[Dict],
    *,
    model_id: str = INSIGHTS_MODEL_ID,
    system: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> str:
    """배치 잡용 — converse() 동기 호출, 최종 텍스트 한 번에 반환."""
    params: Dict = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        params["system"] = [{"text": system}]

    response = _client().converse(**params)
    output = response.get("output", {}).get("message", {})
    parts: Iterable[Dict] = output.get("content", [])
    chunks: List[str] = []
    for p in parts:
        text = p.get("text")
        if text:
            chunks.append(text)
    return "".join(chunks)


def converse_stream_text(
    messages: List[Dict],
    *,
    model_id: str = INSIGHTS_MODEL_ID,
    system: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
):
    """동기 generator — Bedrock converse_stream의 text_delta를 즉시 yield.

    인사이트 SSE 스트리밍에 사용. async 환경에서 호출 시 ThreadPoolExecutor로 감쌀 것.
    """
    params: Dict = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        params["system"] = [{"text": system}]

    response = _client().converse_stream(**params)
    for event in response.get("stream", []):
        if "contentBlockDelta" in event:
            text = event["contentBlockDelta"].get("delta", {}).get("text")
            if text:
                yield text
