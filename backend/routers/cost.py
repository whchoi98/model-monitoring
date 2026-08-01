"""Cost Dashboard router - 토큰 단가 × 입출력 적산으로 비용 통계.

Endpoints:
  GET /api/cost/summary?window=24h     - 모델별 비용 합계 + total
  GET /api/cost/channel-compare?window=24h - Bedrock vs Anthropic CP on AWS 채널 비교
  GET /api/cost/trend?window=24h        - 시간 단위 bucketing trend
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
from pricing import get_pricing, estimate_cost_usd

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cost", tags=["cost"])


def _parse_window(spec: str) -> timedelta:
    s = spec.strip().lower()
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    return timedelta(hours=24)


def _channel(model_id: str) -> str:
    """Bedrock global / Bedrock us / Anthropic CP on AWS / Bedrock Nova / OpenAI."""
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
    since = datetime.now(timezone.utc) - _parse_window(window)
    rows = (
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            func.count(ProbeResult.id).label("samples"),
            func.coalesce(func.sum(ProbeResult.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(ProbeResult.output_tokens), 0).label("out_tok"),
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
        cost = estimate_cost_usd(r.model_id, int(r.in_tok), int(r.out_tok))
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
    """채널별 (Bedrock Global / US / Nova / Anthropic CP) 합계."""
    since = datetime.now(timezone.utc) - _parse_window(window)
    rows = (
        db.query(
            ProbeResult.model_id,
            func.count(ProbeResult.id).label("samples"),
            func.coalesce(func.sum(ProbeResult.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(ProbeResult.output_tokens), 0).label("out_tok"),
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
        cost = estimate_cost_usd(r.model_id, int(r.in_tok), int(r.out_tok))
        if cost is not None:
            slot["cost_usd"] += cost

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
    delta = _parse_window(window)
    since = datetime.now(timezone.utc) - delta
    bucket_min = 60 if delta >= timedelta(hours=12) else 5

    # date_trunc를 사용하지 않고 Python으로 bucket 계산 (DB-portable).
    rows = (
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            ProbeResult.timestamp,
            ProbeResult.input_tokens,
            ProbeResult.output_tokens,
        )
        .filter(ProbeResult.timestamp >= since)
        .filter(ProbeResult.status == "success")
        .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
        .all()
    )

    bucket_seconds = bucket_min * 60
    points_map: dict[tuple[str, str], float] = {}
    for r in rows:
        cost = estimate_cost_usd(r.model_id, r.input_tokens or 0, r.output_tokens or 0)
        if cost is None:
            continue
        # bucket start: floor timestamp to bucket_min
        ts = r.timestamp.replace(microsecond=0)
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
