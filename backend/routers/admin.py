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


# ───────────────────────────────────────────────────────────────────────
# User management (admin only)
# ───────────────────────────────────────────────────────────────────────


class UserRow(BaseModel):
    id: int
    username: str
    approved: int


class UserListResponse(BaseModel):
    users: list[UserRow]


@router.get("/users", response_model=UserListResponse)
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """모든 사용자 목록 (admin 전용)."""
    _ensure_admin(user)
    rows = db.query(User).order_by(User.id).all()
    return UserListResponse(users=[
        UserRow(id=u.id, username=u.username, approved=u.approved or 0)
        for u in rows
    ])


class UserActionResponse(BaseModel):
    ok: bool
    message: str


@router.delete("/users/{username}", response_model=UserActionResponse)
def delete_user(
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """username으로 user 삭제 (admin 전용). 본인 admin 계정은 삭제 금지."""
    _ensure_admin(user)
    if username == user.username:
        raise HTTPException(status_code=400, detail="자기 자신은 삭제할 수 없습니다.")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail=f"user '{username}' not found")
    db.delete(target)
    db.commit()
    logger.warning("admin '%s' deleted user '%s'", user.username, username)
    return UserActionResponse(ok=True, message=f"user '{username}' deleted")


@router.post("/users/{username}/approve", response_model=UserActionResponse)
def approve_user(
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """username을 즉시 승인 (admin 전용). 이메일 발송 실패 등으로 승인 link 도달 안 한 경우 사용."""
    _ensure_admin(user)
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail=f"user '{username}' not found")
    if target.approved == 1:
        return UserActionResponse(ok=True, message=f"user '{username}' is already approved")
    target.approved = 1
    db.commit()
    logger.info("admin '%s' approved user '%s'", user.username, username)
    return UserActionResponse(ok=True, message=f"user '{username}' approved")
