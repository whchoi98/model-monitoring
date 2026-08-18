"""GPT on AWS 벤치 조회 API (v2.18.0) — /gpt-on-aws 페이지 데이터 소스.

gptbench.run_cycle()이 15분마다 저장한 gpt_bench_results를 집계해 제공:
  - /latest : 최신 사이클의 채널별 스코어 카드 (median TTFB/TTFT/GAP, 캐시 히트율, 성공률)
  - /trend  : 시간 범위 내 사이클×채널 median 시계열 (그래프용)
조회 전용·공개 (auto-probe 계열과 동일 정책).
"""

import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import GptBenchResult

router = APIRouter(prefix="/api/gptbench", tags=["gptbench"])


class ChannelCard(BaseModel):
    model_id: str
    model_name: str
    family: str
    region: str
    runs: int
    success: int
    median_ttfb_ms: Optional[float] = None
    median_ttft_ms: Optional[float] = None
    median_gap_ms: Optional[float] = None
    p95_ttft_ms: Optional[float] = None
    cache_hit_rate: Optional[float] = None       # cached>0 비율
    median_reasoning_tokens: Optional[float] = None
    last_error: Optional[str] = None


class LatestResponse(BaseModel):
    cycle_ts: Optional[datetime] = None
    channels: list[ChannelCard] = []


class TrendPoint(BaseModel):
    cycle_ts: datetime
    median_ttfb_ms: Optional[float] = None
    median_ttft_ms: Optional[float] = None
    median_gap_ms: Optional[float] = None
    errors: int = 0


class TrendSeries(BaseModel):
    model_id: str
    model_name: str
    points: list[TrendPoint]


class TrendResponse(BaseModel):
    hours: int
    series: list[TrendSeries] = []


# 사이클은 채널 단위로 커밋되므로 실행 중(~7분)에는 max(cycle_ts)가 부분 사이클이다.
# 데드라인(13분) + 여유 = 14분 이상 지난 사이클만 "완료"로 간주하고, 최신이 진행 중이면
# 직전 사이클로 폴백한다 (2026-07-22 "카드 4개만 보임" 실사고).
_CYCLE_COMPLETE_AFTER = timedelta(minutes=14)


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _latest_complete_cycle(db: Session) -> Optional[datetime]:
    cycles = [r[0] for r in (db.query(GptBenchResult.cycle_ts).distinct()
                             .order_by(GptBenchResult.cycle_ts.desc()).limit(2))]
    if not cycles:
        return None
    newest = cycles[0]
    if datetime.now(timezone.utc) - _as_aware(newest) >= _CYCLE_COMPLETE_AFTER:
        return newest
    return cycles[1] if len(cycles) > 1 else newest


def _median(vals: list) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def _p95(vals: list) -> Optional[float]:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, round(0.95 * (len(vals) - 1))))
    return round(vals[k], 1)


@router.get("/latest", response_model=LatestResponse)
def latest(db: Session = Depends(get_db)):
    """최신 **완료** 사이클의 채널별 집계 — 스코어 카드용 (진행 중 사이클은 직전으로 폴백)."""
    last_cycle = _latest_complete_cycle(db)
    if last_cycle is None:
        return LatestResponse()
    rows = (db.query(GptBenchResult)
            .filter(GptBenchResult.cycle_ts == last_cycle).all())
    by_channel: dict[str, list[GptBenchResult]] = {}
    for r in rows:
        by_channel.setdefault(r.model_id, []).append(r)

    cards = []
    for model_id, grp in by_channel.items():
        ok = [r for r in grp if r.status == "success"]
        errs = [r for r in grp if r.error_message]
        cached_known = [r for r in ok if r.cached_tokens is not None]
        cards.append(ChannelCard(
            model_id=model_id,
            model_name=grp[0].model_name,
            family=grp[0].family,
            region=grp[0].region,
            runs=len(grp),
            success=len(ok),
            median_ttfb_ms=_median([r.ttfb_ms for r in ok]),
            median_ttft_ms=_median([r.ttft_ms for r in ok]),
            median_gap_ms=_median([r.gap_ms for r in ok]),
            p95_ttft_ms=_p95([r.ttft_ms for r in ok]),
            cache_hit_rate=(round(sum(1 for r in cached_known if r.cached_tokens > 0)
                                  / len(cached_known), 3) if cached_known else None),
            median_reasoning_tokens=_median([r.reasoning_tokens for r in ok]),
            last_error=(errs[-1].error_message if errs else None),
        ))
    # 정렬: family(카탈로그 순) → region
    fam_rank = {"GPT 5.6 Terra": 0, "GPT 5.5": 1, "GPT 5.4": 2}
    cards.sort(key=lambda c: (fam_rank.get(c.family, 9), c.region))
    return LatestResponse(cycle_ts=last_cycle, channels=cards)


@router.get("/trend", response_model=TrendResponse)
def trend(
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """시간 범위 내 사이클별 median 시계열 — 그래프용. 96사이클/일 × 9채널 규모라 Python 집계로 충분."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (db.query(GptBenchResult)
             .filter(GptBenchResult.cycle_ts >= since))
    # 진행 중 사이클의 부분 median이 그래프 끝점을 왜곡하지 않도록 완료 사이클까지만 포함.
    cutoff = _latest_complete_cycle(db)
    if cutoff is not None:
        query = query.filter(GptBenchResult.cycle_ts <= cutoff)
    rows = query.order_by(GptBenchResult.cycle_ts.asc()).all()

    grouped: dict[str, dict[datetime, list[GptBenchResult]]] = {}
    names: dict[str, str] = {}
    for r in rows:
        grouped.setdefault(r.model_id, {}).setdefault(r.cycle_ts, []).append(r)
        names[r.model_id] = r.model_name

    series = []
    for model_id, cycles in grouped.items():
        points = []
        for cts in sorted(cycles.keys()):
            grp = cycles[cts]
            ok = [r for r in grp if r.status == "success"]
            points.append(TrendPoint(
                cycle_ts=cts,
                median_ttfb_ms=_median([r.ttfb_ms for r in ok]),
                median_ttft_ms=_median([r.ttft_ms for r in ok]),
                median_gap_ms=_median([r.gap_ms for r in ok]),
                errors=len(grp) - len(ok),
            ))
        series.append(TrendSeries(model_id=model_id, model_name=names[model_id], points=points))
    series.sort(key=lambda s: s.model_name)
    return TrendResponse(hours=hours, series=series)
