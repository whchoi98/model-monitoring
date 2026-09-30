"""Cost Dashboard router - 토큰 단가 × 입출력 적산으로 비용 통계.

v2.30.0 (ADR-030): 단가는 price_history에서 각 프로브 시각에 유효했던 값을 행 단위로 조인한다
(price_history.with_row_cost). 단가 행이 없는 모델은 비용 NULL, 토큰 합계에는 포함.

Endpoints:
  GET /api/cost/summary?window=24h     - 모델별 비용 합계 + total
  GET /api/cost/channel-compare?window=24h - Bedrock vs Anthropic CP on AWS 채널 비교
  GET /api/cost/trend?window=24h        - 시간 단위 bucketing trend
  window는 세 엔드포인트 모두 최대 30d — 넘거나, 0 이하이거나, 읽을 수 없으면 422 (window_spec.parse_window).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import Depends

from database import get_db
from models import ProbeResult
from visibility import hidden_patterns
from price_history import as_utc, with_row_cost
from window_spec import parse_window

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cost", tags=["cost"])

# 세 엔드포인트의 창 상한 30d — 비용 화면(1h, 6h, 24h, 7d, 30d)의 가장 긴 창. 공개 엔드포인트라 상한이 곧 요청 하나의
# 스캔 상한이다 — 넘는 창은 422 (window_spec, 2026-09-30 /analysis OOM). summary, channel-compare는 DB에서 GROUP BY로
# 합친 모델별 행만 받아 메모리는 O(모델)이지만, 창만큼 probe_results와 price_history 조인을 훑으므로 같은 상한을 둔다.
# trend는 화면 호출자가 없다.
_MAX_WINDOW = timedelta(days=30)
_YIELD_PER = 2000  # trend가 한 번에 가져오는 행 수(PostgreSQL은 서버 측 커서)


def _channel(model_id: str) -> str:
    """Bedrock global / Bedrock us / Bedrock <aws-region>(in-region, bedrock:<region>:*) / Anthropic CP on AWS /
    Bedrock Nova / OpenAI."""
    if model_id.startswith("anthropic:"):
        return "Anthropic (CP on AWS)"
    if model_id.startswith("openai:"):
        return "OpenAI"
    if model_id.startswith("global.amazon.") or model_id.startswith("us.amazon."):
        return "Bedrock Nova"
    if model_id.startswith("global."):
        return "Bedrock Global"
    if model_id.startswith("us."):
        return "Bedrock US"
    if model_id.startswith("bedrock:"):  # in-region 온디맨드 bedrock:<region>:<FM id> (v2.32.0) — reliability와 같은 채널 이름
        parts = model_id.split(":", 2)
        return f"Bedrock {parts[1]}" if len(parts) == 3 and parts[1] and parts[2] else "Other"
    return "Other"


class ModelCostRow(BaseModel):
    model_id: str
    model_name: str
    channel: str
    samples: int
    input_tokens: int
    output_tokens: int
    cost_usd: Optional[float]
    avg_cost_per_call_usd: Optional[float]


class CostSummary(BaseModel):
    window: str
    since: str
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    rows: list[ModelCostRow]


@router.get("/summary", response_model=CostSummary)
def get_cost_summary(
    window: str = Query("24h"),
    db: Session = Depends(get_db),
):
    """모델별 비용 합계."""
    since = datetime.now(timezone.utc) - parse_window(window, max_window=_MAX_WINDOW)
    query, row_cost = with_row_cost(
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            func.count(ProbeResult.id).label("samples"),
            func.coalesce(func.sum(ProbeResult.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(ProbeResult.output_tokens), 0).label("out_tok"),
        )
    )
    rows = (
        query.add_columns(
            func.sum(row_cost).label("cost"),
            func.count(row_cost).label("priced"),
        )
        .filter(ProbeResult.timestamp >= since)
        .filter(ProbeResult.status == "success")
        .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
        .group_by(ProbeResult.model_id, ProbeResult.model_name)
        .all()
    )

    out_rows: list[ModelCostRow] = []
    total_cost = 0.0
    total_in = 0
    total_out = 0
    for r in rows:
        cost = float(r.cost) if r.priced else None
        avg = (cost / r.samples) if cost is not None and r.samples > 0 else None
        if cost is not None:
            total_cost += cost
        total_in += int(r.in_tok)
        total_out += int(r.out_tok)
        out_rows.append(ModelCostRow(
            model_id=r.model_id,
            model_name=r.model_name,
            channel=_channel(r.model_id),
            samples=int(r.samples),
            input_tokens=int(r.in_tok),
            output_tokens=int(r.out_tok),
            cost_usd=cost,
            avg_cost_per_call_usd=avg,
        ))
    out_rows.sort(key=lambda x: (x.cost_usd or 0), reverse=True)
    return CostSummary(
        window=window,
        since=since.isoformat(),
        total_cost_usd=round(total_cost, 6),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        rows=out_rows,
    )


class ChannelRow(BaseModel):
    channel: str
    samples: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ChannelCompare(BaseModel):
    window: str
    since: str
    channels: list[ChannelRow]


@router.get("/channel-compare", response_model=ChannelCompare)
def get_channel_compare(
    window: str = Query("24h"),
    db: Session = Depends(get_db),
):
    """채널별 (Bedrock Global / US / in-region(<aws-region>) / Nova / Anthropic CP / OpenAI) 합계."""
    since = datetime.now(timezone.utc) - parse_window(window, max_window=_MAX_WINDOW)
    query, row_cost = with_row_cost(
        db.query(
            ProbeResult.model_id,
            func.count(ProbeResult.id).label("samples"),
            func.coalesce(func.sum(ProbeResult.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(ProbeResult.output_tokens), 0).label("out_tok"),
        )
    )
    rows = (
        query.add_columns(
            func.sum(row_cost).label("cost"),
            func.count(row_cost).label("priced"),
        )
        .filter(ProbeResult.timestamp >= since)
        .filter(ProbeResult.status == "success")
        .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
        .group_by(ProbeResult.model_id)
        .all()
    )

    agg: dict[str, dict[str, float]] = {}
    for r in rows:
        ch = _channel(r.model_id)
        slot = agg.setdefault(ch, {"samples": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        slot["samples"] += int(r.samples)
        slot["input_tokens"] += int(r.in_tok)
        slot["output_tokens"] += int(r.out_tok)
        if r.priced:  # 단가 없는 모델은 0으로 더한다 (현행 유지)
            slot["cost_usd"] += float(r.cost)

    channels = [
        ChannelRow(
            channel=k,
            samples=int(v["samples"]),
            input_tokens=int(v["input_tokens"]),
            output_tokens=int(v["output_tokens"]),
            cost_usd=round(v["cost_usd"], 6),
        )
        for k, v in agg.items()
    ]
    channels.sort(key=lambda x: x.cost_usd, reverse=True)
    return ChannelCompare(window=window, since=since.isoformat(), channels=channels)


class TrendPoint(BaseModel):
    bucket: str  # ISO timestamp of bucket start
    model_name: str
    cost_usd: float


class CostTrend(BaseModel):
    window: str
    since: str
    bucket_minutes: int
    points: list[TrendPoint]


@router.get("/trend", response_model=CostTrend)
def get_cost_trend(
    window: str = Query("24h"),
    db: Session = Depends(get_db),
):
    """시간 단위 bucketing — window가 24h 이상이면 1시간 bucket, 작으면 5분 bucket."""
    delta = parse_window(window, max_window=_MAX_WINDOW)
    since = datetime.now(timezone.utc) - delta
    bucket_min = 60 if delta >= timedelta(hours=12) else 5

    # date_trunc를 사용하지 않고 Python으로 bucket 계산 (DB-portable). 비용은 행 단위 시점 단가.
    # 행을 모아 두지 않고 나눠 읽으면서 bucket에 바로 더한다 — 메모리는 bucket × 모델.
    query, row_cost = with_row_cost(
        db.query(
            ProbeResult.model_name,
            ProbeResult.timestamp,
        )
    )
    rows = (
        query.add_columns(row_cost.label("cost"))
        .filter(ProbeResult.timestamp >= since)
        .filter(ProbeResult.status == "success")
        .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
        .yield_per(_YIELD_PER)
    )

    bucket_seconds = bucket_min * 60
    points_map: dict[tuple[str, str], float] = {}
    for r in rows:
        if r.cost is None:
            continue
        cost = float(r.cost)
        # bucket start: floor timestamp to bucket_min (SQLite는 naive로 돌려주므로 UTC로 고정)
        ts = as_utc(r.timestamp).replace(microsecond=0)
        epoch = int(ts.timestamp())
        bucket_epoch = (epoch // bucket_seconds) * bucket_seconds
        bucket_iso = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat()
        key = (bucket_iso, r.model_name)
        points_map[key] = points_map.get(key, 0.0) + cost

    points = [
        TrendPoint(bucket=k[0], model_name=k[1], cost_usd=round(v, 6))
        for k, v in sorted(points_map.items())
    ]
    return CostTrend(window=window, since=since.isoformat(), bucket_minutes=bucket_min, points=points)
