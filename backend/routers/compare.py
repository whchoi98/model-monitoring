"""Comparison Lab router - 한 prompt를 N개 모델에 동시 invoke + SSE 스트림.

DB 저장 없음 (Phase 1). 결과는 in-memory queue로만 흐름.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from auth import get_current_user
from models import User
from prober import AVAILABLE_MODELS, stream_compare_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compare", tags=["compare"])


class CompareRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=20000)
    model_ids: list[str] = Field(..., min_length=1, max_length=20)
    max_tokens: int = Field(default=512, ge=1, le=8192)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)


@router.post("/run")
async def compare_run(payload: CompareRequest, user: User = Depends(get_current_user)):
    """N개 모델 병렬 invoke - SSE event stream으로 응답.

    Events:
      - start: {total_tasks, model_ids}
      - ttft: {model_id, model_name, ttft_ms}
      - token: {model_id, model_name, token}
      - result: {model_id, model_name, status, ttft_ms, total_latency_ms, tps,
                 input_tokens, output_tokens, output_text}
      - error: {model_id, error, total_latency_ms}
      - complete: {total}
    """
    # 모델 ID 검증 - AVAILABLE_MODELS에 등록된 것만 허용 (오타·악의적 ID 차단).
    unknown = [m for m in payload.model_ids if m not in AVAILABLE_MODELS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model_ids: {unknown}",
        )

    generator = stream_compare_events(
        model_ids=payload.model_ids,
        prompt=payload.prompt,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
    )
    # stream_compare_events는 이미 SSE 형식("event: X\ndata: Y\n\n")으로 raw yield하므로
    # EventSourceResponse(이중 wrap)가 아닌 StreamingResponse를 사용 (probes.py / insights.py 동일 패턴).
    # NFR-4: SSE no-buffering — X-Accel-Buffering: no 헤더를 명시적으로 설정.
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
