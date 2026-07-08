"""REST API endpoints for the auto-probe dashboard."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auto_prober import auto_prober
from database import get_db
from models import ProbeRun, ProbeResult
from schemas import ProbeResultResponse

router = APIRouter(prefix="/api/auto-probe", tags=["auto-probe"])


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    """Return current auto-prober status.

    v2: EventBridge Scheduler가 별도 Fargate Task로 실행하므로 backend in-process state는
    부정확하다. DB의 최근 ProbeRun(is_auto=1)을 기반으로 last/next run time을 계산한다.
    """
    interval = 300
    last_run = (
        db.query(ProbeRun)
        .filter(ProbeRun.is_auto == 1)
        .order_by(desc(ProbeRun.created_at))
        .first()
    )
    last_iso: str | None = None
    next_iso: str | None = None
    if last_run and last_run.created_at:
        last_iso = last_run.created_at.isoformat()
        next_iso = (last_run.created_at + timedelta(seconds=interval)).isoformat()
    return {
        # v2는 EventBridge가 항상 ENABLED이므로 True로 노출 — 단순화.
        "is_running": True,
        "last_run_time": last_iso,
        "next_run_time": next_iso,
        "interval_seconds": interval,
        "current_cycle_running": auto_prober.current_cycle_running,
    }


@router.get("/latest", response_model=list[ProbeResultResponse])
def get_latest(
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return the latest auto-probe results.

    category 지정 시: 그 카테고리의 가장 최근 cycle의 결과만 반환.
                     (각 모델별로 가장 최근 1개 row → 카테고리 라운드로빈 후에도 카드 표시 안정).
    category 미지정: 가장 최근 auto run의 모든 결과.
    """
    if category:
        # 카테고리별 가장 최근 cycle의 결과들
        latest_run = (
            db.query(ProbeRun)
            .join(ProbeResult, ProbeResult.run_id == ProbeRun.id)
            .filter(
                ProbeRun.is_auto == 1,
                ProbeRun.status == "completed",
                ProbeResult.category == category,
            )
            .order_by(desc(ProbeRun.created_at))
            .first()
        )
        if not latest_run:
            return []
        results = (
            db.query(ProbeResult)
            .filter(ProbeResult.run_id == latest_run.id)
            .order_by(ProbeResult.model_name)
            .all()
        )
        return results

    # category 미지정 — 가장 최근 auto run의 모든 결과
    latest_run = (
        db.query(ProbeRun)
        .filter(ProbeRun.is_auto == 1, ProbeRun.status == "completed")
        .order_by(desc(ProbeRun.created_at))
        .first()
    )
    if not latest_run:
        return []

    results = (
        db.query(ProbeResult)
        .filter(ProbeResult.run_id == latest_run.id)
        .order_by(ProbeResult.model_name)
        .all()
    )
    return results


@router.get("/trend")
def get_trend(
    hours: float = Query(default=24, gt=0, le=168),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return time-series data from auto-probe runs within the given time window.

    category 지정 시 그 카테고리의 결과만 반환.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # 성능 (2026-07-08): ORM 전체 컬럼 로드(output_text 응답 전문 포함) + run_id IN 리스트가
    # hours=24 기준 1.87MB DB I/O·수 초 지연을 유발 → 응답에 쓰는 컬럼만 SELECT + JOIN.
    q = (
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            ProbeResult.timestamp,
            ProbeResult.ttft_ms,
            ProbeResult.total_latency_ms,
            ProbeResult.tps,
            ProbeResult.status,
            ProbeResult.category,
        )
        .join(ProbeRun, ProbeResult.run_id == ProbeRun.id)
        .filter(
            ProbeRun.is_auto == 1,
            ProbeRun.status == "completed",
            ProbeRun.created_at >= cutoff,
        )
    )
    if category:
        q = q.filter(ProbeResult.category == category)
    rows = q.order_by(ProbeResult.timestamp).all()

    return [
        {
            "model_id": r.model_id,
            "model_name": r.model_name,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "ttft_ms": r.ttft_ms,
            "total_latency_ms": r.total_latency_ms,
            "tps": r.tps,
            "status": r.status,
            "category": r.category,
        }
        for r in rows
    ]


@router.get("/categories")
def get_categories():
    """Workload preset 카테고리 목록 (id + 라벨)."""
    from auto_prober import WORKLOAD_PRESETS
    return [
        {"id": p["id"], "label_ko": p["label_ko"], "label_en": p["label_en"]}
        for p in WORKLOAD_PRESETS
    ]


@router.post("/trigger")
def trigger_probe():
    """Manually trigger an immediate auto-probe cycle."""
    if auto_prober.current_cycle_running:
        return {"message": "A cycle is already running", "triggered": False}
    auto_prober.trigger()
    return {"message": "Probe cycle triggered", "triggered": True}
