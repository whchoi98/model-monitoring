"""Router for querying stored probe results and aggregated statistics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import ProbeResult
from prober import AVAILABLE_MODELS
from visibility import visible_only
from schemas import ModelStats, ProbeResultResponse, StatsResponse

# start_time/run_id 없이 호출되면 전체 probe_results(수십만 행)를 ORM으로 적재해 backend 컨테이너가
# OOM(1024MB, exit 137)으로 죽는다 — 2026-09-01 실사고. 기간 미지정 시 최근 24h로 한정.
_DEFAULT_STATS_WINDOW = timedelta(hours=24)

router = APIRouter(prefix="/api/results", tags=["results"])


def _percentile(values: list[float], pct: float) -> float | None:
    """Compute a percentile from a list of floats."""
    if not values:
        return None
    arr = sorted(values)
    k = (len(arr) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(arr):
        return round(arr[f], 2)
    d0 = arr[f] * (c - k)
    d1 = arr[c] * (k - f)
    return round(d0 + d1, 2)


@router.get("", response_model=list[ProbeResultResponse])
def list_results(
    model_id: Optional[str] = Query(None),
    run_id: Optional[int] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List probe results with optional filters."""
    query = visible_only(db.query(ProbeResult), ProbeResult.model_name)

    if model_id:
        query = query.filter(ProbeResult.model_id == model_id)
    if run_id:
        query = query.filter(ProbeResult.run_id == run_id)
    if start_time:
        query = query.filter(ProbeResult.timestamp >= start_time)
    if end_time:
        query = query.filter(ProbeResult.timestamp <= end_time)

    query = query.order_by(ProbeResult.timestamp.desc())
    results = query.offset(offset).limit(limit).all()
    return results


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    run_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get aggregated statistics (avg/p50/p95/p99) per model.

    Only successful probes are included in the statistics.
    category 지정 시 그 workload preset 카테고리의 결과만 집계.
    """
    query = visible_only(db.query(ProbeResult).filter(ProbeResult.status == "success"),
                         ProbeResult.model_name)

    if start_time is None and run_id is None:
        start_time = datetime.now(timezone.utc) - _DEFAULT_STATS_WINDOW
    if start_time:
        query = query.filter(ProbeResult.timestamp >= start_time)
    if end_time:
        query = query.filter(ProbeResult.timestamp <= end_time)
    if run_id:
        query = query.filter(ProbeResult.run_id == run_id)
    if category:
        query = query.filter(ProbeResult.category == category)

    results = query.all()

    # Group by model_id
    model_groups: dict[str, list[ProbeResult]] = {}
    for r in results:
        model_groups.setdefault(r.model_id, []).append(r)

    model_stats: list[ModelStats] = []
    for model_id, group in model_groups.items():
        # 라벨은 현행 카탈로그가 source of truth. 과거 행의 model_name은 오등록 라벨일 수 있음
        # (예: CP Fable 5.1이 Fable 5 라벨로 기록된 2026-09-01 사례) — 카탈로그에 없으면 최신 행 라벨.
        model_name = AVAILABLE_MODELS.get(model_id) or max(group, key=lambda r: r.timestamp).model_name

        ttft_values = [r.ttft_ms for r in group if r.ttft_ms is not None]
        latency_values = [r.total_latency_ms for r in group if r.total_latency_ms is not None]
        tps_values = [r.tps for r in group if r.tps is not None]
        server_latency_values = [r.server_latency_ms for r in group if r.server_latency_ms is not None]

        stats = ModelStats(
            model_id=model_id,
            model_name=model_name,
            count=len(group),
            avg_ttft_ms=round(sum(ttft_values) / len(ttft_values), 2) if ttft_values else None,
            p50_ttft_ms=_percentile(ttft_values, 50),
            p95_ttft_ms=_percentile(ttft_values, 95),
            p99_ttft_ms=_percentile(ttft_values, 99),
            avg_latency_ms=round(sum(latency_values) / len(latency_values), 2) if latency_values else None,
            p50_latency_ms=_percentile(latency_values, 50),
            p95_latency_ms=_percentile(latency_values, 95),
            p99_latency_ms=_percentile(latency_values, 99),
            avg_tps=round(sum(tps_values) / len(tps_values), 2) if tps_values else None,
            p50_tps=_percentile(tps_values, 50),
            p95_tps=_percentile(tps_values, 95),
            p99_tps=_percentile(tps_values, 99),
            avg_server_latency_ms=round(sum(server_latency_values) / len(server_latency_values), 2) if server_latency_values else None,
            p50_server_latency_ms=_percentile(server_latency_values, 50),
            p95_server_latency_ms=_percentile(server_latency_values, 95),
            p99_server_latency_ms=_percentile(server_latency_values, 99),
        )
        model_stats.append(stats)

    return StatsResponse(
        start_time=start_time,
        end_time=end_time,
        models=model_stats,
    )


@router.get("/latest", response_model=list[ProbeResultResponse])
def get_latest_results(
    db: Session = Depends(get_db),
):
    """Get the most recent result for each model.

    Returns one result per model_id, ordered by timestamp descending.
    """
    # Subquery to find the max id per model (most recent result)
    subq = (
        db.query(
            ProbeResult.model_id,
            func.max(ProbeResult.id).label("max_id"),
        )
        .group_by(ProbeResult.model_id)
        .subquery()
    )

    results = (
        visible_only(db.query(ProbeResult), ProbeResult.model_name)
        .join(subq, ProbeResult.id == subq.c.max_id)
        .order_by(ProbeResult.timestamp.desc())
        .all()
    )

    return results
