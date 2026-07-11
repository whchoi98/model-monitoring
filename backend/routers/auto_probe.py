"""REST API endpoints for the auto-probe dashboard."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auto_prober import auto_prober
from database import get_db
from models import ProbeRun, ProbeResult
from schemas import ProbeResultResponse

router = APIRouter(prefix="/api/auto-probe", tags=["auto-probe"])


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
    """(model_name, 시각 정시 버킷)별 metric 평균. null metric은 평균에서 제외.

    status는 버킷 내 성공이 하나라도 있으면 success (차트는 metric null 여부로 결측 표현).
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
        ttft_avg, ttft_min, ttft_max = stats(i.ttft_ms for i in items)
        lat_avg, lat_min, lat_max = stats(i.total_latency_ms for i in items)
        tps_avg, tps_min, tps_max = stats(i.tps for i in items)
        out.append(_Bucket(
            model_id=items[0].model_id,
            model_name=model_name,
            timestamp=bucket_ts,
            ttft_ms=ttft_avg, ttft_ms_min=ttft_min, ttft_ms_max=ttft_max,
            total_latency_ms=lat_avg, total_latency_ms_min=lat_min, total_latency_ms_max=lat_max,
            tps=tps_avg, tps_min=tps_min, tps_max=tps_max,
            status="success" if any(i.status == "success" for i in items) else "error",
            category=items[0].category,
        ))
    out.sort(key=lambda b: b.timestamp)
    return out


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


# CloudFront 전용 단기 캐시 (max-age=0 → 브라우저 캐시 없음). 데이터는 5분 주기 갱신이므로
# s-maxage=30으로 다중 사용자·30초 자동새로고침의 중복 DB 조회를 edge에서 흡수.
# CloudFront가 이 헤더를 존중하려면 edge-stack의 /api/auto-probe/* behavior 필요.
_CACHE_CONTROL = "public, max-age=0, s-maxage=30"


@router.get("/latest", response_model=list[ProbeResultResponse])
def get_latest(
    response: Response,
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return the latest auto-probe results.

    category 지정 시: 그 카테고리의 가장 최근 cycle의 결과만 반환.
                     (각 모델별로 가장 최근 1개 row → 카테고리 라운드로빈 후에도 카드 표시 안정).
    category 미지정: 가장 최근 auto run의 모든 결과.
    """
    response.headers["Cache-Control"] = _CACHE_CONTROL
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
            ProbeRun.created_at >= cutoff,
        )
    )
    if category:
        q = q.filter(ProbeResult.category == category)
    rows = q.order_by(ProbeResult.timestamp).all()

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
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
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
    db: Session = Depends(get_db),
):
    """최근 N시간 프로브 실패 요약 — 대시보드 상단 이상 징후 박스용 (v2.12.0)."""
    from anomalies import summarize_anomalies

    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(ProbeResult.model_name, ProbeResult.status,
                 ProbeResult.error_message, ProbeResult.timestamp)
        .filter(ProbeResult.timestamp >= since)
        .all()
    )
    return {"hours": hours, **summarize_anomalies(rows)}


@router.post("/trigger")
def trigger_probe():
    """Manually trigger an immediate auto-probe cycle."""
    if auto_prober.current_cycle_running:
        return {"message": "A cycle is already running", "triggered": False}
    auto_prober.trigger()
    return {"message": "Probe cycle triggered", "triggered": True}
