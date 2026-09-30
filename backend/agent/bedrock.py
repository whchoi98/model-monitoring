"""Bedrock Converse(Stream) 클라이언트 — 챗봇·인사이트 잡 공통.

설계 원칙 (NFR-4):
  - 챗봇/사용자 응답은 converse_stream 사용 (토큰 단위 즉시 emit).
  - 인사이트 배치 잡도 converse_stream을 쓴다(converse_stream_collect, v2.32.2) — 아래 참고.
  - tool_use 응답을 받으면 호출자가 tool 실행 후 tool_result로 다시 호출.

인사이트 잡(v2.32.2, 2026-09-30): 비스트림 converse는 생성이 끝나야 첫 바이트가 온다. Sonnet 4.6이 요약 5.4k~6.3k토큰을
초당 90~110토큰으로 만드는 데 55~75초가 걸려 기본 read timeout 60초에 자주 걸렸고(EN 요약 24시간 109/279건 실패), 기본
legacy 재시도 5회가 실패 한 번을 약 5분(5 × 60초 + backoff)으로 늘렸다. 그래서 인사이트 잡은 전용 client(insights_client — connect 10초,
read 60초, standard 재시도 total_max_attempts 2)로 converse_stream을 받고, 호출 전체는 CallWatchdog wall-clock 상한으로
끊는다. 스트림에서 read timeout은 청크 사이 대기 상한이고, botocore 재시도는 응답 헤더를 받기 전에만 일어난다(생성을
다시 과금하지 않는다). 챗봇, follow-up(converse_blocking), stream-regenerate(converse_stream_text)는 _client() 그대로다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Iterable, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from stream_watchdog import CallWatchdog

logger = logging.getLogger(__name__)

# 챗봇 기본 모델 — Seoul deployment에서는 global inference profile 사용.
CHAT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
INSIGHTS_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


def _client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-runtime", region_name=region)


# 인사이트 잡 전용 client 설정(v2.32.2). 호출할 때 읽는다(테스트가 시간을 줄여 본다).
INSIGHTS_CONNECT_TIMEOUT_S = 10
INSIGHTS_READ_TIMEOUT_S = 60  # converse_stream에서는 청크 사이 대기 상한 — 호출 전체 상한은 wall_clock_s
INSIGHTS_TOTAL_MAX_ATTEMPTS = 2  # 첫 시도 포함. standard 모드는 헤더 대기 ReadTimeout, throttling, 5xx, 연결 오류를 다시 시도한다


def insights_client():
    """인사이트 잡 전용 bedrock-runtime client — 러너가 run마다 호출 스레드에서 한 번 만들어 KO, EN 워커가 함께 쓴다.

    boto3 client는 스레드 안전하지만 기본 session에서 여러 스레드가 동시에 client를 만드는 것은 안전하지 않다.
    """
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-runtime", region_name=region, config=Config(
        connect_timeout=INSIGHTS_CONNECT_TIMEOUT_S,
        read_timeout=INSIGHTS_READ_TIMEOUT_S,
        retries={"mode": "standard", "total_max_attempts": INSIGHTS_TOTAL_MAX_ATTEMPTS},
    ))


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


@dataclass(frozen=True)
class StreamedText:
    """converse_stream_collect 결과 — messageStop까지 받은 본문."""

    text: str
    stop_reason: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    elapsed_s: float


class StreamWallClockTimeout(Exception):
    """호출 전체가 wall_clock_s를 넘어 watchdog이 스트림을 끊었다. 받은 부분 텍스트는 버린다."""

    def __init__(self, limit_s: float, elapsed_s: float, chars: int):
        self.limit_s, self.elapsed_s, self.chars = limit_s, elapsed_s, chars
        super().__init__(f"converse_stream exceeded the {limit_s:g}s wall-clock limit "
                         f"({elapsed_s:.1f}s, {chars} chars received)")


class StreamInterrupted(Exception):
    """응답 헤더를 받은 뒤 messageStop 전에 스트림이 끊겼다 — 청크 사이 read timeout, 연결 끊김, 스트림 안의 오류 이벤트,
    messageStop 없는 종료. 요청은 받아들여졌으므로 일시적인 실패로 보고, 받은 부분 텍스트는 버린다."""

    def __init__(self, cause: str, elapsed_s: float, chars: int):
        self.cause, self.elapsed_s, self.chars = cause, elapsed_s, chars
        super().__init__(f"converse_stream interrupted after {elapsed_s:.1f}s ({chars} chars received): {cause}")


def converse_stream_collect(
    messages: List[Dict],
    *,
    model_id: str = INSIGHTS_MODEL_ID,
    system: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    wall_clock_s: float,
    client=None,
) -> StreamedText:
    """배치 잡용 — converse_stream을 끝까지 받아 텍스트 하나로 돌려준다(인사이트 잡, v2.32.2).

    - 헤더 대기: client의 connect/read timeout과 botocore 재시도가 상한이다. 여기서 난 예외(ClientError, ReadTimeoutError
      …)는 그대로 던진다 — 재시도는 이미 botocore가 했다.
    - 스트림: 청크 사이는 read timeout, 호출 전체는 wall_clock_s(CallWatchdog, 호출 시작부터)가 상한이다. 만료되면 소켓을
      끊고 StreamWallClockTimeout, 그 밖에 messageStop 전에 끊기면 StreamInterrupted다. messageStop 뒤(metadata 꼬리)에
      난 예외는 무시한다 — 본문은 끝났다.
    """
    params: Dict = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        params["system"] = [{"text": system}]

    client = client if client is not None else insights_client()
    chunks: List[str] = []
    stop_reason: Optional[str] = None
    usage: Dict = {}
    watchdog = CallWatchdog(wall_clock_s)
    started = time.monotonic()

    def _chars() -> int:
        return sum(len(c) for c in chunks)

    watchdog.start()
    try:
        response = client.converse_stream(**params)
        stream = response["stream"]
        watchdog.attach(stream)  # 헤더 대기 중에 이미 만료됐으면 여기서 곧바로 끊는다
        try:
            for event in stream:
                if watchdog.fired and stop_reason is None:
                    break  # 소켓을 못 끊는 스트림도 만료 뒤에는 더 읽지 않는다
                if "contentBlockDelta" in event:
                    text = event["contentBlockDelta"].get("delta", {}).get("text")
                    if text:
                        chunks.append(text)
                elif "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason")
                elif "metadata" in event:
                    usage = event["metadata"].get("usage", {}) or {}
        except Exception as exc:  # noqa: BLE001 — 스트림 중 예외는 아래 두 가지로 나눈다
            if stop_reason is None:
                elapsed = time.monotonic() - started
                if watchdog.fired:
                    raise StreamWallClockTimeout(wall_clock_s, elapsed, _chars()) from exc
                raise StreamInterrupted(f"{type(exc).__name__}: {exc}", elapsed, _chars()) from exc
        if stop_reason is None:
            elapsed = time.monotonic() - started
            if watchdog.fired:
                raise StreamWallClockTimeout(wall_clock_s, elapsed, _chars())
            raise StreamInterrupted("stream ended before messageStop", elapsed, _chars())
    finally:
        watchdog.cancel()
    return StreamedText(
        text="".join(chunks),
        stop_reason=stop_reason,
        input_tokens=usage.get("inputTokens"),
        output_tokens=usage.get("outputTokens"),
        elapsed_s=time.monotonic() - started,
    )
