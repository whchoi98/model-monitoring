"""관리자 전용 라우터 - 데이터 reset 등 운영 작업.

JWT 인증 + username=='admin' 체크로 보호. 일반 사용자는 호출 불가.
"""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Insight, ProbeResult, ProbeRun, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


class ResetResponse(BaseModel):
    deleted: Dict[str, int]
    message: str


def _ensure_admin(user: User) -> None:
    if user.username != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin only",
        )


@router.post("/reset-monitoring-data", response_model=ResetResponse)
def reset_monitoring_data(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """모든 probe_runs / probe_results / insights 데이터 삭제.

    사용 시점: 이전 IAM 오류로 누적된 에러 데이터를 정리하고 깨끗한 베이스라인으로
    모니터링을 재시작할 때.
    사용자 인증: admin 계정만 호출 가능.
    """
    _ensure_admin(user)

    insights_deleted = db.query(Insight).delete()
    results_deleted = db.query(ProbeResult).delete()
    runs_deleted = db.query(ProbeRun).delete()
    db.commit()

    logger.warning(
        "admin '%s' wiped monitoring data: %d runs, %d results, %d insights",
        user.username,
        runs_deleted,
        results_deleted,
        insights_deleted,
    )

    return ResetResponse(
        deleted={
            "probe_runs": runs_deleted,
            "probe_results": results_deleted,
            "insights": insights_deleted,
        },
        message="모니터링 데이터를 모두 삭제했습니다. 다음 auto-probe 사이클부터 새로 시작합니다.",
    )
