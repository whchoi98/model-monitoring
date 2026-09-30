"""Router for querying stored probe results and aggregated statistics."""

from __future__ import annotations

import logging
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
# start_time 하한(run_id가 없을 때) — HistoryPanel의 가장 긴 범위 30d + 브라우저 시계 오차 여유 1일. start_time은
# 브라우저가 자기 시계로 계산해 보내므로 거부(422)하지 않고 하한으로 당겨 읽으며, 응답 start_time은 당긴 값이다
# (기본 24h 창처럼 실제로 쓴 하한을 돌려준다). start_time=1970-01-01이 보존 테이블 전체를 읽던 경로(2026-09-30 점검).
_MAX_STATS_LOOKBACK = timedelta(days=31)
_YIELD_PER = 2000  # 한 번에 가져오는 행 수(PostgreSQL은 서버 측 커서)
# run_id는 1 이상만 받는다(0, 음수 → 422). stats는 기본 창과 31일 하한을 run_id is None으로 고르고 run_id 필터는 값이
# 참일 때만 걸었으므로, run_id=0이 두 상한을 모두 건너뛰고 보존 중인 success 행 전체를 읽었다(2026-09-30 통합 리뷰).
# 목록(list_results)에도 같은 규칙을 둔다. 프런트엔드는 run_id를 참일 때만 보낸다(frontend/src/lib/api.ts).

logger = logging.getLogger(__name__)
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
    run_id: Optional[int] = Query(None, ge=1),
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
    if run_id is not None:
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
    run_id: Optional[int] = Query(None, ge=1),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get aggregated statistics (avg/p50/p95/p99) per model.

    Only successful probes are included in the statistics.
    category 지정 시 그 workload preset 카테고리의 결과만 집계.
    """
    # 통계에 쓰는 열만 나눠 읽는다 — ORM 엔티티는 prompt, output_text까지 담아 화면의 30d 선택 하나가 1 GB를 넘었다.
    query = visible_only(
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            ProbeResult.timestamp,
            ProbeResult.ttft_ms,
            ProbeResult.total_latency_ms,
            ProbeResult.tps,
            ProbeResult.server_latency_ms,
        ).filter(ProbeResult.status == "success"),
        ProbeResult.model_name,
    )

    now = datetime.now(timezone.utc)
    if start_time is None and run_id is None:
        start_time = now - _DEFAULT_STATS_WINDOW
    elif start_time is not None and run_id is None:
        floor = now - _MAX_STATS_LOOKBACK
        # 오프셋 없는 값은 UTC로 본다(저장 시각이 모두 UTC)
        if (start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)) < floor:
            logger.warning("results/stats: start_time %s is older than %d days; reading from %s",
                           start_time.isoformat(), _MAX_STATS_LOOKBACK.days, floor.isoformat())
            start_time = floor
    if start_time:
        query = query.filter(ProbeResult.timestamp >= start_time)
    if end_time:
        query = query.filter(ProbeResult.timestamp <= end_time)
    if run_id is not None:  # 창 분기(run_id is None)와 같은 판정 — ge=1이라 0은 여기까지 오지 않는다
        query = query.filter(ProbeResult.run_id == run_id)
    if category:
        query = query.filter(ProbeResult.category == category)

    # model_id별로 행 수, 지표 값 목록(행 순서 그대로), 가장 최근 행의 라벨만 누적한다.
    model_groups: dict[str, dict] = {}
    for model_id, row_name, ts, ttft, latency, tps, server_latency in query.yield_per(_YIELD_PER):
        g = model_groups.get(model_id)
        if g is None:
            g = model_groups[model_id] = {"count": 0, "latest": (ts, row_name),
                                          "ttft": [], "latency": [], "tps": [], "server_latency": []}
        elif ts is not None and (g["latest"][0] is None or ts > g["latest"][0]):
            g["latest"] = (ts, row_name)  # 같은 시각이면 먼저 본 행 — 예전 max(group, key=timestamp)와 같다
        g["count"] += 1
        for key, value in (("ttft", ttft), ("latency", latency), ("tps", tps), ("server_latency", server_latency)):
            if value is not None:
                g[key].append(value)

    model_stats: list[ModelStats] = []
    for model_id, g in model_groups.items():
        # 라벨은 현행 카탈로그가 source of truth. 과거 행의 model_name은 오등록 라벨일 수 있음
        # (예: CP Fable 5.1이 Fable 5 라벨로 기록된 2026-09-01 사례) — 카탈로그에 없으면 최신 행 라벨.
        model_name = AVAILABLE_MODELS.get(model_id) or g["latest"][1]

        ttft_values = g["ttft"]
        latency_values = g["latency"]
        tps_values = g["tps"]
        server_latency_values = g["server_latency"]

        stats = ModelStats(
            model_id=model_id,
            model_name=model_name,
            count=g["count"],
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
