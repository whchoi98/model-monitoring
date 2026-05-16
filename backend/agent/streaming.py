"""SSE 스트리밍 헬퍼.

NFR-4 SSE 운영 원칙 준수:
  1. delta 이벤트 즉시 emit (버퍼링 금지) — generator 외부에서 보장.
  2. CloudFront 5s keep-alive — 청크 사이 간격 < 5s로 유지하면 자동 충족.
  3. ORIGIN_RESPONSE Lambda@Edge 사용 금지 — 인프라 레벨에서 보장.
  4. final 이벤트 try/finally — 본 모듈의 stream_with_final()로 강제.
  5. max_tokens 시나리오별 분리 — 호출자가 설정.
  6. AgentCore 응답은 simulate_streaming() — 본 모듈 제공.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import AsyncGenerator, AsyncIterator, Optional

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> str:
    """SSE 단일 이벤트 문자열을 만든다.

    Bedrock converse_stream의 contentBlockDelta 등에 직접 매핑되도록 짧게 유지.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def simulate_streaming(
    text: str,
    *,
    chunk_size: int = 50,
    delay_ms: int = 15,
) -> AsyncIterator[str]:
    """AgentCore처럼 한 번에 텍스트를 반환하는 응답을 50자/15ms 청크로 흘려보낸다.

    사용 예: AgentCore Runtime invoke가 최종 텍스트 한 번에 돌아올 때 chat SSE로 변환.
    """
    delay = max(0, delay_ms) / 1000.0
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield sse_event("delta", {"text": chunk})
        if delay > 0:
            await asyncio.sleep(delay)


async def stream_with_final(
    inner: AsyncGenerator[str, None],
    *,
    label: str = "chat",
    on_error_metadata: Optional[dict] = None,
) -> AsyncIterator[str]:
    """inner 생성기를 그대로 흘려보내되 끝/예외 모두에서 'final' 이벤트를 반드시 emit.

    클라이언트가 connection close만 보고 결과를 추정해야 하는 상황을 제거.
    예외 발생 시 CloudWatch에 스택트레이스 logged + 'final' 이벤트의 error 필드 채움.
    """
    error_payload: Optional[dict] = None
    try:
        async for chunk in inner:
            yield chunk
    except Exception as exc:  # noqa: BLE001 — SSE 끊김 방지를 위해 전부 catch
        tb = traceback.format_exc()
        logger.exception("[%s] streaming failed mid-flight: %s", label, exc)
        error_payload = {
            "ok": False,
            "error": str(exc),
            "type": exc.__class__.__name__,
        }
        # 스택트레이스는 클라이언트에 노출하지 않는다 (CloudWatch만).
        del tb
    finally:
        payload = {"ok": True, "label": label}
        if error_payload is not None:
            payload = error_payload
        if on_error_metadata and error_payload is not None:
            payload = {**payload, **on_error_metadata}
        yield sse_event("final", payload)
