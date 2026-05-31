"""인사이트 조회 라우터.

주기적으로 insights_runner가 만들어 둔 결과를 GET /api/insights 로 조회.
대시보드의 인사이트 패널이 사용.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db, SessionLocal
from models import Insight, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/insights", tags=["insights"])

# 동시 regenerate 요청 직렬화 (여러 클릭 → 중복 Bedrock 호출 방지).
_regenerate_lock = threading.Lock()
_is_regenerating = False


class InsightResponse(BaseModel):
    id: int
    window_start: str
    window_end: str
    summary_md: str
    summary_md_en: Optional[str] = None
    model_breakdown: Optional[dict] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize(row: Insight) -> InsightResponse:
    return InsightResponse(
        id=row.id,
        window_start=row.window_start.isoformat() if row.window_start else "",
        window_end=row.window_end.isoformat() if row.window_end else "",
        summary_md=row.summary_md,
        summary_md_en=getattr(row, "summary_md_en", None),
        model_breakdown=row.model_breakdown,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


@router.get("/latest", response_model=Optional[InsightResponse])
def get_latest(db: Session = Depends(get_db)):
    row = db.query(Insight).order_by(desc(Insight.created_at)).first()
    return _serialize(row) if row else None


@router.get("", response_model=List[InsightResponse])
def list_insights(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows = db.query(Insight).order_by(desc(Insight.created_at)).limit(limit).all()
    return [_serialize(r) for r in rows]


class RegenerateRequest(BaseModel):
    window: str = "6h"
    lang: Optional[str] = "ko"


class RegenerateResponse(BaseModel):
    triggered: bool
    message: str


def _run_regenerate(window: str):
    """별도 스레드에서 insights_runner.run_once() 호출 후 lock 해제."""
    global _is_regenerating
    try:
        from insights_runner import run_once

        logger.info("inline insight regeneration started (window=%s)", window)
        run_once(window)
    except Exception:
        logger.exception("inline insight regeneration failed")
    finally:
        with _regenerate_lock:
            _is_regenerating = False


@router.post("/regenerate", response_model=RegenerateResponse)
def regenerate(
    body: RegenerateRequest,
    user: User = Depends(get_current_user),
):
    """현재 시점 기준으로 새 인사이트를 backend 프로세스 내부 thread로 생성한다.

    - 인증된 사용자만 호출 가능 (Bedrock 비용 abuse + DB write 방지).
    - Backend는 이미 Bedrock InvokeModel + DB 접근 권한을 갖고 있어 추가 IAM 불필요.
    - Lock으로 동시 요청 직렬화 (Bedrock 중복 호출 회피).
    - 응답은 즉시 (triggered=True) 반환. 클라이언트는 잠시 후 /api/insights/latest 재조회.
    """
    logger.info("insight regenerate requested by user='%s' window='%s'", user.username, body.window)
    global _is_regenerating
    with _regenerate_lock:
        if _is_regenerating:
            return RegenerateResponse(
                triggered=False,
                message="이미 인사이트 생성이 진행 중입니다",
            )
        _is_regenerating = True

    threading.Thread(target=_run_regenerate, args=(body.window,), daemon=True).start()
    return RegenerateResponse(
        triggered=True,
        message=f"인사이트 생성 시작 (window={body.window})",
    )


# ---------------------------------------------------------------------
# SSE 스트리밍 regenerate - Bedrock converse_stream으로 token 단위 즉시 emit.
# 완료 시 DB 저장.
# ---------------------------------------------------------------------
from fastapi.responses import StreamingResponse
import asyncio
import json as _json


@router.post("/stream-regenerate")
async def stream_regenerate(
    body: RegenerateRequest,
    user: User = Depends(get_current_user),
):
    """SSE 스트리밍 인사이트 재생성.

    Bedrock Sonnet 4.6 converse_stream으로 토큰 단위 yield → SSE delta 이벤트.
    완료 시 DB에 Insight row 저장 + final 이벤트로 응답 종료.

    Note: db는 Depends(get_db)로 받지 않는다. StreamingResponse 반환 직후 FastAPI가
    의존성 cleanup으로 session을 close하지만 generator는 그 후에도 계속 실행되어
    closed session에 대한 silent data loss가 발생. 대신 generator 안에서 SessionLocal()로
    dedicated session을 생성하고 finally에서 close.
    """
    from agent.bedrock import converse_stream_text, INSIGHTS_MODEL_ID
    from insights_runner import collect_stats_for_window, _build_prompt
    from datetime import datetime, timezone

    window = body.window
    lang = body.lang or "ko"

    async def _generator():
        # Generator 전용 DB session — StreamingResponse 반환 후 의존성 cleanup의 영향을 받지 않음.
        db = SessionLocal()
        try:
            # 1) Stats 수집.
            try:
                stats = collect_stats_for_window(db, window)
            except Exception as exc:
                logger.exception("stats compute failed")
                yield f"event: error\ndata: {_json.dumps({'message': str(exc)})}\n\n"
                return

            # 2) Prompt 빌드.
            system_prompt, user_prompt = _build_prompt(window, stats, lang)

            # 3) Bedrock converse_stream을 per-chunk로 SSE에 흘려보냄.
            accumulated: list[str] = []
            _SENTINEL = object()

            def _next(gen):
                try:
                    return next(gen)
                except StopIteration:
                    return _SENTINEL

            try:
                gen = converse_stream_text(
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    model_id=INSIGHTS_MODEL_ID,
                    system=system_prompt,
                    max_tokens=8192,
                    temperature=0.3,
                )
                while True:
                    chunk = await asyncio.to_thread(_next, gen)
                    if chunk is _SENTINEL:
                        break
                    accumulated.append(chunk)
                    yield f"event: delta\ndata: {_json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)
            except Exception as exc:
                logger.exception("converse_stream insight failed")
                yield f"event: error\ndata: {_json.dumps({'message': str(exc)})}\n\n"
                return

            # 4) DB 저장.
            full_text = "".join(accumulated)
            try:
                from insights_runner import parse_window
                now = datetime.now(timezone.utc)
                window_delta = parse_window(window)
                insight = Insight(
                    window_start=now - window_delta,
                    window_end=now,
                    summary_md=full_text,
                    summary_md_en=full_text if lang == "en" else None,
                )
                db.add(insight)
                db.commit()
                db.refresh(insight)
                yield f"event: final\ndata: {_json.dumps({'ok': True, 'id': insight.id, 'window': window, 'lang': lang})}\n\n"
            except Exception as exc:
                logger.exception("insight save failed")
                yield f"event: final\ndata: {_json.dumps({'ok': False, 'error': str(exc)})}\n\n"
        finally:
            db.close()

    # chat.py와 동일한 패턴: 우리가 이미 SSE 형식("event: X\ndata: Y\n\n")으로 raw yield하므로
    # EventSourceResponse가 아닌 StreamingResponse를 써야 이중 wrap 안 됨.
    return StreamingResponse(_generator(), media_type="text/event-stream")
