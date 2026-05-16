"""인사이트 조회 라우터.

주기적으로 insights_runner가 만들어 둔 결과를 GET /api/insights 로 조회.
대시보드의 인사이트 패널이 사용.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import get_db
from models import Insight

router = APIRouter(prefix="/api/insights", tags=["insights"])


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
