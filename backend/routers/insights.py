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

from database import get_db
from models import Insight

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
    model_breakdown: Optional[dict] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize(row: Insight) -> InsightResponse:
    return InsightResponse(
        id=row.id,
        window_start=row.window_start.isoformat() if row.window_start else "",
        window_end=row.window_end.isoformat() if row.window_end else "",
        summary_md=row.summary_md,
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
def regenerate(body: RegenerateRequest):
    """현재 시점 기준으로 새 인사이트를 backend 프로세스 내부 thread로 생성한다.

    - Backend는 이미 Bedrock InvokeModel + DB 접근 권한을 갖고 있어 추가 IAM 불필요.
    - Lock으로 동시 요청 직렬화 (Bedrock 중복 호출 회피).
    - 응답은 즉시 (triggered=True) 반환. 클라이언트는 잠시 후 /api/insights/latest 재조회.
    """
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
