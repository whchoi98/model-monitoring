"""REST API endpoints for the auto-probe dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

import auto_prober as prober_service
import probe_cadence
from auth import get_current_user
from auto_prober import auto_prober
from database import get_db
from latest_results import latest_auto_rows
from models import ProbeRun, ProbeResult
from visibility import hidden_patterns, visible_only
from schemas import ProbeResultResponse

router = APIRouter(prefix="/api/auto-probe", tags=["auto-probe"])
logger = logging.getLogger(__name__)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    # SQLite / legacy rows may be naive; stored monitoring timestamps are UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime | None) -> str | None:
    value = _utc(value)
    return value.isoformat() if value is not None else None


def _result_response(row: ProbeResult) -> ProbeResultResponse:
    return ProbeResultResponse.model_validate(row).model_copy(
        update={"timestamp": _utc(row.timestamp)}
    )


class _Bucket:
    """모델×시각버킷 하나의 집계 결과 (trend 응답 row와 동일 속성 + min/max 밴드)."""

    __slots__ = ("model_id", "model_name", "timestamp", "ttft_ms",
                 "total_latency_ms", "tps", "status", "category",
                 "ttft_ms_min", "ttft_ms_max",
                 "total_latency_ms_min", "total_latency_ms_max",
                 "tps_min", "tps_max")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _downsample_hourly(rows):
    """(model_name, 시각 정시 버킷)별 성공 행의 metric 평균. null metric은 제외.

    실패 소요 시간은 성공 응답 지연과 섞지 않는다. 실패만 있는 버킷은 null metric으로 보존.
    status는 버킷 내 성공이 하나라도 있으면 success.
    category는 버킷 내 첫 값 — 카테고리 필터 지정 시엔 모두 동일, 미지정 시 혼합 대표값.
    """
    groups: dict[tuple, list] = {}
    for r in rows:
        if r.timestamp is None:
            continue
        bucket_ts = r.timestamp.replace(minute=0, second=0, microsecond=0)
        groups.setdefault((r.model_name, bucket_ts), []).append(r)

    def stats(values):
        vals = [v for v in values if v is not None]
        if not vals:
            return None, None, None
        return sum(vals) / len(vals), min(vals), max(vals)

    out = []
    for (model_name, bucket_ts), items in groups.items():
        successful = [i for i in items if i.status == "success"]
        ttft_avg, ttft_min, ttft_max = stats(i.ttft_ms for i in successful)
        lat_avg, lat_min, lat_max = stats(i.total_latency_ms for i in successful)
        tps_avg, tps_min, tps_max = stats(i.tps for i in successful)
        out.append(_Bucket(
            model_id=items[0].model_id,
            model_name=model_name,
            timestamp=bucket_ts,
            ttft_ms=ttft_avg, ttft_ms_min=ttft_min, ttft_ms_max=ttft_max,
            total_latency_ms=lat_avg, total_latency_ms_min=lat_min, total_latency_ms_max=lat_max,
            tps=tps_avg, tps_min=tps_min, tps_max=tps_max,
            status="success" if successful else "error",
            category=items[0].category,
        ))
    out.sort(key=lambda b: b.timestamp)
    return out


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    """Observed activity, not Scheduler configuration; no provider calls."""
    now = datetime.now(timezone.utc)
    interval = prober_service.PROBE_INTERVAL_SECONDS
    # Select scalar fields to avoid ProbeRun.results' selectin relationship:
    # polling status must not load all output text from the latest cycle.
    runs = db.query(ProbeRun.id, ProbeRun.created_at, ProbeRun.status).filter(
        ProbeRun.is_auto == 1
    )
    last_run = (
        runs.order_by(desc(ProbeRun.created_at), desc(ProbeRun.id)).first()
    )
    completed = (
        runs.filter(ProbeRun.status == "completed")
        .order_by(desc(ProbeRun.created_at), desc(ProbeRun.id))
        .first()
    )
    completed_time = None
    if completed is not None:
        completed_time = (
            visible_only(db.query(func.max(ProbeResult.timestamp)), ProbeResult.model_name)
            .filter(ProbeResult.run_id == completed.id)
            .scalar()
        )
    active = prober_service.get_active_auto_run(db, now)
    started = _utc(last_run.created_at) if last_run else None
    if active is not None:
        state = "running"
    elif last_run is None:
        state = "never_run"
    elif started is None or (
        now - started
    ).total_seconds() >= prober_service.OVERDUE_AFTER_SECONDS:
        state = "overdue"
    else:
        state = "failed" if last_run.status == "failed" else "completed"

    hidden = hidden_patterns()
    expected_models = sum(
        not any(pattern in name for pattern in hidden)
        for name in prober_service.AVAILABLE_MODELS.values()
    )
    category_count = len(prober_service.WORKLOAD_PRESETS)
    # 채널별 주기 (v2.29.0) — 키는 model_id의 첫 ':' 앞 접두("anthropic" = Claude Platform on AWS).
    # 여기 없는 채널은 interval_seconds / category_interval_seconds를 따른다.
    channel_intervals = probe_cadence.channel_intervals()
    return {
        "cycle_state": state,
        "is_running": state in {"running", "completed"},
        "last_run_id": last_run.id if last_run else None,
        "last_run_status": last_run.status if last_run else None,
        "last_run_time": _utc_iso(started),
        "last_completed_run_id": completed.id if completed else None,
        "last_completed_time": _utc_iso(completed_time),
        "next_run_time": _utc_iso(started + timedelta(seconds=interval)) if started else None,
        "interval_seconds": interval,
        "current_cycle_running": active is not None,
        "expected_model_count": expected_models,
        "category_count": category_count,
        "category_interval_seconds": interval * category_count,
        "channel_intervals": channel_intervals,
        "channel_category_intervals": {
            channel: seconds * category_count for channel, seconds in channel_intervals.items()
        },
        "overdue_after_seconds": prober_service.OVERDUE_AFTER_SECONDS,
        "running_timeout_seconds": prober_service.RUNNING_TIMEOUT_SECONDS,
    }


# CloudFront 전용 단기 캐시 (max-age=0 → 브라우저 캐시 없음). 데이터는 5분 주기 갱신이므로(CP 채널 10분)
# s-maxage=30으로 다중 사용자·30초 자동새로고침의 중복 DB 조회를 edge에서 흡수.
# CloudFront가 이 헤더를 존중하려면 edge-stack의 /api/auto-probe/* behavior 필요.
_CACHE_CONTROL = "public, max-age=0, s-maxage=30"


@router.get("/latest", response_model=list[ProbeResultResponse])
def get_latest(
    response: Response,
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return each model's latest auto-probe result (v2.29.0: per model, not per run).

    category 미지정: 모델별로 자기 주기 3회 범위 안의 최신 행 — 기본 채널은 최신 완료 run의 행이고,
                     10분 주기 CP 채널은 CP를 건너뛴 사이클에도 직전 run의 행이 남는다.
    category 지정: 그 카테고리의 모델별 최신 행 — 카테고리 회전 2바퀴 범위(기본 60분, CP 120분).
    기준 시각은 최신 완료 자동 run의 시작 시각 (latest_results 모듈 docstring).
    """
    response.headers["Cache-Control"] = _CACHE_CONTROL
    _, rows = latest_auto_rows(
        db, category=category or None, category_count=len(prober_service.WORKLOAD_PRESETS),
    )
    return [_result_response(r) for r in rows]


@router.get("/trend")
def get_trend(
    response: Response,
    hours: float = Query(default=24, gt=0, le=168),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return time-series data from auto-probe runs within the given time window.

    category 지정 시 그 카테고리의 결과만 반환.
    """
    response.headers["Cache-Control"] = _CACHE_CONTROL
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
            ProbeResult.timestamp >= cutoff,
        )
    )
    if category:
        q = q.filter(ProbeResult.category == category)
    rows = visible_only(q, ProbeResult.model_name).order_by(ProbeResult.timestamp).all()

    # 24h 초과 조회는 시간 버킷 평균으로 다운샘플링 — 168h 원본은 56k행/13MB JSON이라
    # 전송·Recharts 렌더링 모두 마비. 5분 해상도는 24h 이하에서만 유지한다.
    # (Python 집계: date_trunc 등 PG 전용 SQL을 피해 sqlite 테스트와 호환, 수만 행 수준에선 ms 단위.)
    if hours > 24:
        rows = _downsample_hourly(rows)

    # 원본(비집계) 행은 min/max가 없으므로 getattr 기본값 None — 밴드는 집계 구간에서만 그려짐.
    return [
        {
            "model_id": r.model_id,
            "model_name": r.model_name,
            "timestamp": _utc_iso(r.timestamp),
            "ttft_ms": r.ttft_ms,
            "total_latency_ms": r.total_latency_ms,
            "tps": r.tps,
            "status": r.status,
            "category": r.category,
            "ttft_ms_min": getattr(r, "ttft_ms_min", None),
            "ttft_ms_max": getattr(r, "ttft_ms_max", None),
            "total_latency_ms_min": getattr(r, "total_latency_ms_min", None),
            "total_latency_ms_max": getattr(r, "total_latency_ms_max", None),
            "tps_min": getattr(r, "tps_min", None),
            "tps_max": getattr(r, "tps_max", None),
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


@router.get("/anomalies")
def get_anomalies(
    response: Response,
    hours: int = Query(12, ge=1, le=168),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """최근 N시간 프로브 실패 요약 — 대시보드 상단 이상 징후 박스용 (v2.12.0)."""
    from anomalies import summarize_anomalies

    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (
        visible_only(db.query(ProbeResult.model_name, ProbeResult.status,
                              ProbeResult.error_message, ProbeResult.timestamp),
                     ProbeResult.model_name)
        .join(ProbeRun, ProbeRun.id == ProbeResult.run_id)
        .filter(ProbeRun.is_auto == 1, ProbeResult.timestamp >= since)
    )
    if category:
        query = query.filter(ProbeResult.category == category)
    rows = (
        (r.model_name, r.status, r.error_message, _utc(r.timestamp))
        for r in query.all()
    )
    return {"hours": hours, "category": category, **summarize_anomalies(rows)}


@router.post("/trigger", status_code=202)
def trigger_probe(user=Depends(get_current_user)):
    """Authenticate and reserve before accepting asynchronous probe work."""
    try:
        run_id = auto_prober.trigger()
    except prober_service.CycleAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail={
            "code": "cycle_running", "run_id": exc.run_id,
            "message": "자동 프로브가 이미 실행 중입니다.",
        }) from exc
    except Exception as exc:
        logger.exception("Failed to accept manual auto-probe")
        raise HTTPException(status_code=503, detail={
            "code": "trigger_failed",
            "message": "프로브를 시작하지 못했습니다. 잠시 후 다시 시도하세요.",
        }) from exc
    return {
        "triggered": True, "run_id": run_id,
        "message": "프로브 실행을 접수했습니다.",
    }
