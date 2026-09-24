"""모델별 최신 자동 프로브 행 (v2.29.0) — /api/auto-probe/latest와 챗봇 get_latest_results 공용.

v2.29.0부터 Claude Platform on AWS 채널은 10분마다(두 사이클에 한 번)만 프로빙하고 워크로드 카테고리도
따로 회전하므로, "최신 완료 run의 행"만 보면 CP 채널이 사이클 절반 동안 빠진다. 그래서 모델마다 자기
주기로 잡은 범위 안의 최신 행 하나를 돌려준다.

기준 시각(anchor)은 최신 완료 자동 run의 시작 시각이다 — 수집이 멈춰도 마지막 스냅샷이 사라지지 않고
(이전과 같다) 신선도는 프런트엔드가 timestamp로 판정한다. 모델별 범위:
  - 카테고리 없음: anchor − LATEST_LOOKBACK_INTERVALS × 모델 주기 (기본 채널 15분, CP 30분)
  - 카테고리 지정: anchor − CATEGORY_LOOKBACK_ROTATIONS × 카테고리 수 × 모델 주기 (기본 60분, CP 120분)

쿼리 2개, 둘 다 테이블 크기와 무관하게 bounded:
  1. 집계 — probe_results.timestamp 범위(ix_probe_results_timestamp)만 읽고 probe_runs PK로 조인,
     model_id별 max(id)·max(timestamp). 카테고리 없음 ≈ 30분 × 모델 수 행, 카테고리 ≈ 2시간 × 모델 수 행.
  2. 본문 — PK IN (모델 수 이하)로 전체 행.
run 상태는 completed만 — 이전 /latest와 같은 공개 기준이다(진행 중·실패 run의 행은 노출하지 않는다).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

import probe_cadence
from models import ProbeResult, ProbeRun
from visibility import visible_only

LATEST_LOOKBACK_INTERVALS = 3
CATEGORY_LOOKBACK_ROTATIONS = 2


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def latest_completed_auto_run(db: Session):
    """(id, created_at) of the newest completed automatic run, or None."""
    return (
        db.query(ProbeRun.id, ProbeRun.created_at)
        .filter(ProbeRun.is_auto == 1, ProbeRun.status == "completed")
        .order_by(desc(ProbeRun.created_at), desc(ProbeRun.id))
        .first()
    )


def lookback_seconds(model_id: str, category_count: Optional[int] = None) -> int:
    """모델 한 채널의 최신 행 탐색 범위(초). category_count가 있으면 카테고리 회전 기준."""
    interval = probe_cadence.interval_for(model_id)
    if category_count:
        return CATEGORY_LOOKBACK_ROTATIONS * category_count * interval
    return LATEST_LOOKBACK_INTERVALS * interval


def latest_auto_rows(
    db: Session,
    *,
    category: Optional[str] = None,
    model_id: Optional[str] = None,
    category_count: int = 6,
):
    """(anchor run 또는 None, 모델별 최신 ProbeResult 목록 — model_name 순)."""
    anchor = latest_completed_auto_run(db)
    if anchor is None:
        return None, []
    anchor_at = _utc(anchor.created_at) or datetime.now(timezone.utc)
    scope = category_count if category else None
    widest_interval = max(probe_cadence.BASE_INTERVAL_SECONDS, probe_cadence.ANTHROPIC_CP_PROBE_INTERVAL_S)
    widest = lookback_seconds(model_id, scope) if model_id else (
        (CATEGORY_LOOKBACK_ROTATIONS * category_count if scope else LATEST_LOOKBACK_INTERVALS) * widest_interval
    )

    query = (
        db.query(ProbeResult.model_id, func.max(ProbeResult.id), func.max(ProbeResult.timestamp))
        .join(ProbeRun, ProbeRun.id == ProbeResult.run_id)
        .filter(
            ProbeRun.is_auto == 1,
            ProbeRun.status == "completed",
            ProbeResult.timestamp >= anchor_at - timedelta(seconds=widest),
        )
    )
    query = visible_only(query, ProbeResult.model_name)
    if category:
        query = query.filter(ProbeResult.category == category)
    if model_id:
        query = query.filter(ProbeResult.model_id == model_id)

    ids = [
        row_id
        for mid, row_id, newest in query.group_by(ProbeResult.model_id).all()
        if newest is not None
        and _utc(newest) >= anchor_at - timedelta(seconds=lookback_seconds(mid, scope))
    ]
    if not ids:
        return anchor, []
    rows = db.query(ProbeResult).filter(ProbeResult.id.in_(ids)).order_by(ProbeResult.model_name).all()
    return anchor, rows
