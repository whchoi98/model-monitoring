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
from sqlalchemy import case
from sqlalchemy.orm import Session

from database import get_db
from models import ProbeResult
from streamed_read import stream_rows_or_503
from visibility import visible_only
from window_spec import parse_window

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reliability", tags=["reliability"])


# 창 상한 = /reliability 화면의 가장 긴 창(1h, 6h, 24h, 7d 중 7d). 넘는 창은 422 (window_spec).
# 공개 엔드포인트라 상한이 곧 요청 하나의 스캔 상한이다 — 2026-09-30 /analysis OOM과 같은 경로.
_MAX_WINDOW = timedelta(days=7)
_YIELD_PER = 2000  # 한 번에 가져오는 행 수(PostgreSQL은 서버 측 커서 — 전체 시간 상한은 streamed_read, 넘으면 503)


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
#  "OpenAI GPT 5.4 (us-east-1)"         → family="GPT 5.4",           channel="OpenAI us-east-1"
#  "OpenAI GPT 5.5 (1P)"                → family="GPT 5.5",           channel="OpenAI 1P"
#  "Bedrock Claude Opus 5 (ap-northeast-2)" → family="Claude Opus 5", channel="Bedrock ap-northeast-2" (in-region 온디맨드)
#  "OpenAI GPT 6.1 Sol (Global)"        → family="GPT 6.1 Sol",       channel="OpenAI Global"
_LABEL_RE = re.compile(r"^(Bedrock|Anthropic|OpenAI)\s+(.+?)\s+\(([^)]+)\)$")
# Bedrock 라벨 괄호가 AWS 리전 코드면 in-region 채널(v2.32.0). "(Global)"과 리전 코드가 아닌 나머지는 지금처럼 US.
_AWS_REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d+$")

# 채널 표시 순서: Anthropic → Bedrock Global → Bedrock US → Bedrock in-region(<aws-region>) → OpenAI(Global/US CRIS + Mantle 리전 + 1P) → 기타.
_FIXED_CHANNEL_ORDER = {"Anthropic (CP on AWS)": 0, "Bedrock Global": 1, "Bedrock US": 2}


def _channel_sort_key(channel: str) -> tuple[int, str]:
    if channel in _FIXED_CHANNEL_ORDER:
        return (_FIXED_CHANNEL_ORDER[channel], channel)
    if channel.startswith("Bedrock "):
        return (3, channel)  # Bedrock in-region ("Bedrock ap-northeast-2", v2.32.0) — Global/US는 위 고정 표에서 먼저 걸린다
    if channel.startswith("OpenAI"):
        return (4, channel)  # OpenAI Global/US CRIS + Mantle 리전들 + 1P direct
    return (5, channel)      # 미분류 → 마지막


def _parse_label(name: str) -> tuple[str, str]:
    m = _LABEL_RE.match(name)
    if not m:
        return name, "Other"
    namespace, family, region = m.group(1), m.group(2), m.group(3)
    if namespace == "Anthropic":
        channel = "Anthropic (CP on AWS)"
    elif namespace == "OpenAI":
        # OpenAI — region(paren 내용)이 채널 식별자. Mantle: us-east-1/2/west-2, 1P direct: "1P".
        channel = f"OpenAI {region}"
    else:
        # Bedrock — region에 따라 Global / in-region(<aws-region>) / US
        if "Global" in region:
            channel = "Bedrock Global"
        elif _AWS_REGION_RE.match(region):
            channel = f"Bedrock {region}"  # "Bedrock ap-northeast-2" (v2.32.0) — US에 합치면 서울 성공률이 US에 섞인다
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
    since = datetime.now(timezone.utc) - parse_window(window, max_window=_MAX_WINDOW)
    # 집계에 쓰는 열만 나눠 읽는다. ORM 엔티티는 prompt, output_text까지 담아 7d에서 요청 하나가 0.3~0.6 GB였다.
    # error_message는 실패 행에서만 쓰므로 성공 행은 NULL로 받는다. 누적하는 것은 채널별 지표 값 목록뿐이다(p95).
    rows = (
        visible_only(
            db.query(
                ProbeResult.model_name,
                ProbeResult.status,
                ProbeResult.ttft_ms,
                ProbeResult.total_latency_ms,
                ProbeResult.tps,
                case((ProbeResult.status != "success", ProbeResult.error_message), else_=None),
            ),
            ProbeResult.model_name,
        )
        .filter(ProbeResult.timestamp >= since)
        .yield_per(_YIELD_PER)
    )
    rows = stream_rows_or_503(rows, route=f"GET /api/reliability/multi-channel window={window!r}")

    # family → channel → bucket
    agg: dict[str, dict[str, dict]] = {}
    for model_name, status, ttft_ms, total_latency_ms, tps, error_message in rows:
        family, channel = _parse_label(model_name)
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
        if status == "success":
            c["success"] += 1
            if ttft_ms is not None:
                c["ttft"].append(float(ttft_ms))
            if total_latency_ms is not None:
                c["latency"].append(float(total_latency_ms))
            if tps is not None:
                c["tps"].append(float(tps))
        elif status == "overloaded":
            c["overloaded"] += 1
        else:
            c["error"] += 1
        if status != "success":
            bucket = _classify_error(error_message, status)
            c["buckets"][bucket] = c["buckets"].get(bucket, 0) + 1

    # Format
    families: list[FamilyGroup] = []
    for family in sorted(agg.keys()):
        ch_rows: list[ChannelRow] = []
        for channel in sorted(agg[family].keys(), key=_channel_sort_key):
            if channel == "Other":
                continue
            c = agg[family][channel]
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
