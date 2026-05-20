"""Multi-channel Reliability Dashboard - 동일 모델의 채널별 가용성·실패 모드 비교.

같은 family (예: Claude Sonnet 4.6)를 Bedrock Global / Bedrock US / Anthropic (CP on AWS)
3채널로 호출했을 때의 성공률/지연/실패 유형 분포를 표시 — failover 의사결정에 사용.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ProbeResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reliability", tags=["reliability"])


def _parse_window(spec: str) -> timedelta:
    s = spec.strip().lower()
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    return timedelta(hours=24)


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(s[int(k)], 2)
    return round(s[f] + (s[c] - s[f]) * (k - f), 2)


# 모델 라벨 → (family, channel) 추출.
#  "Bedrock Claude Sonnet 4.6 (Global)" → family="Claude Sonnet 4.6", channel="Bedrock Global"
#  "Bedrock Claude Sonnet 4.6 (US)"     → family="Claude Sonnet 4.6", channel="Bedrock US"
#  "Anthropic Claude Sonnet 4.6 (US)"   → family="Claude Sonnet 4.6", channel="Anthropic"
#  "Bedrock Nova 2.0 Lite (US)"         → family="Nova 2.0 Lite",     channel="Bedrock US"
_LABEL_RE = re.compile(r"^(Bedrock|Anthropic)\s+(.+?)\s+\(([^)]+)\)$")


def _parse_label(name: str) -> tuple[str, str]:
    m = _LABEL_RE.match(name)
    if not m:
        return name, "Other"
    namespace, family, region = m.group(1), m.group(2), m.group(3)
    if namespace == "Anthropic":
        channel = "Anthropic (CP on AWS)"
    else:
        # Bedrock — region에 따라 Global / US
        if "Global" in region:
            channel = "Bedrock Global"
        else:
            channel = "Bedrock US"
    return family, channel


def _classify_error(msg: Optional[str], status: str) -> str:
    """error_message → bucket: throttle / overloaded / server / model / network / other."""
    if status == "overloaded":
        return "overloaded"
    if not msg:
        return "other"
    m = msg.lower()
    if "throttling" in m or "throttle" in m or "toomanyrequests" in m:
        return "throttle"
    if "overload" in m:
        return "overloaded"
    if "serviceunavailable" in m or "500" in m or "internal" in m:
        return "server"
    if "modelstream" in m or "modelerror" in m or "model not found" in m:
        return "model"
    if "network" in m or "timeout" in m or "connection" in m:
        return "network"
    return "other"


class ChannelRow(BaseModel):
    channel: str
    samples: int
    success: int
    error: int
    overloaded: int
    success_rate: Optional[float]  # 0~1
    avg_ttft_ms: Optional[float]
    p95_ttft_ms: Optional[float]
    avg_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    avg_tps: Optional[float]
    error_buckets: dict[str, int]


class FamilyGroup(BaseModel):
    family: str
    channels: list[ChannelRow]


class ReliabilityResponse(BaseModel):
    window: str
    since: str
    families: list[FamilyGroup]


@router.get("/multi-channel", response_model=ReliabilityResponse)
def get_multi_channel(
    window: str = Query("24h"),
    db: Session = Depends(get_db),
):
    """동일 family를 채널별로 집계해 가용성/실패 모드 비교."""
    since = datetime.now(timezone.utc) - _parse_window(window)
    rows = (
        db.query(ProbeResult)
        .filter(ProbeResult.timestamp >= since)
        .all()
    )

    # family → channel → bucket
    agg: dict[str, dict[str, dict]] = {}
    for r in rows:
        family, channel = _parse_label(r.model_name)
        f = agg.setdefault(family, {})
        c = f.setdefault(
            channel,
            {
                "samples": 0,
                "success": 0,
                "error": 0,
                "overloaded": 0,
                "ttft": [],
                "latency": [],
                "tps": [],
                "buckets": {},
            },
        )
        c["samples"] += 1
        if r.status == "success":
            c["success"] += 1
            if r.ttft_ms is not None:
                c["ttft"].append(float(r.ttft_ms))
            if r.total_latency_ms is not None:
                c["latency"].append(float(r.total_latency_ms))
            if r.tps is not None:
                c["tps"].append(float(r.tps))
        elif r.status == "overloaded":
            c["overloaded"] += 1
        else:
            c["error"] += 1
        if r.status != "success":
            bucket = _classify_error(r.error_message, r.status)
            c["buckets"][bucket] = c["buckets"].get(bucket, 0) + 1

    # Format
    families: list[FamilyGroup] = []
    for family in sorted(agg.keys()):
        ch_rows: list[ChannelRow] = []
        for channel in ("Anthropic (CP on AWS)", "Bedrock Global", "Bedrock US"):
            c = agg[family].get(channel)
            if c is None:
                continue
            samples = c["samples"]
            success = c["success"]
            ch_rows.append(ChannelRow(
                channel=channel,
                samples=samples,
                success=success,
                error=c["error"],
                overloaded=c["overloaded"],
                success_rate=round(success / samples, 4) if samples else None,
                avg_ttft_ms=round(sum(c["ttft"]) / len(c["ttft"]), 2) if c["ttft"] else None,
                p95_ttft_ms=_percentile(c["ttft"], 95),
                avg_latency_ms=round(sum(c["latency"]) / len(c["latency"]), 2) if c["latency"] else None,
                p95_latency_ms=_percentile(c["latency"], 95),
                avg_tps=round(sum(c["tps"]) / len(c["tps"]), 2) if c["tps"] else None,
                error_buckets=c["buckets"],
            ))
        if ch_rows:
            families.append(FamilyGroup(family=family, channels=ch_rows))

    return ReliabilityResponse(window=window, since=since.isoformat(), families=families)
