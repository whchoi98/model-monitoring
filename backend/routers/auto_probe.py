"""REST API endpoints for the auto-probe dashboard."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auto_prober import auto_prober
from database import get_db
from models import ProbeRun, ProbeResult
from schemas import ProbeResultResponse

router = APIRouter(prefix="/api/auto-probe", tags=["auto-probe"])


@router.get("/status")
def get_status():
    """Return current auto-prober status."""
    return {
        "is_running": auto_prober.is_running,
        "last_run_time": auto_prober.last_run_time.isoformat() if auto_prober.last_run_time else None,
        "next_run_time": auto_prober.next_run_time.isoformat() if auto_prober.next_run_time else None,
        "interval_seconds": 300,
        "current_cycle_running": auto_prober.current_cycle_running,
    }


@router.get("/latest", response_model=list[ProbeResultResponse])
def get_latest(db: Session = Depends(get_db)):
    """Return the latest auto-probe results (one per model from the most recent auto run)."""
    # Find the most recent completed auto run
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
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
):
    """Return time-series data from auto-probe runs within the given time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Get all auto runs since cutoff
    auto_runs = (
        db.query(ProbeRun)
        .filter(
            ProbeRun.is_auto == 1,
            ProbeRun.status == "completed",
            ProbeRun.created_at >= cutoff,
        )
        .all()
    )
    if not auto_runs:
        return []

    run_ids = [r.id for r in auto_runs]

    results = (
        db.query(ProbeResult)
        .filter(ProbeResult.run_id.in_(run_ids))
        .order_by(ProbeResult.timestamp)
        .all()
    )

    trend_points = []
    for r in results:
        trend_points.append({
            "model_id": r.model_id,
            "model_name": r.model_name,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "ttft_ms": r.ttft_ms,
            "total_latency_ms": r.total_latency_ms,
            "tps": r.tps,
            "status": r.status,
        })

    return trend_points


@router.post("/trigger")
def trigger_probe():
    """Manually trigger an immediate auto-probe cycle."""
    if auto_prober.current_cycle_running:
        return {"message": "A cycle is already running", "triggered": False}
    auto_prober.trigger()
    return {"message": "Probe cycle triggered", "triggered": True}
