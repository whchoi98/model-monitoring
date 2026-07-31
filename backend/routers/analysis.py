"""Output Analysis - Stop Reason 분포 + Output Token 길이 분포.

LLM 특유의 시그널을 시각화:
  - Stop Reason: end_turn(정상) / max_tokens(잘림) / tool_use / stop_sequence /
                 guardrail_intervened / content_filtered 비율
                 → max_tokens 비율이 높으면 prompt 설계 문제, content_filtered가 높으면 안전성 시그널
  - Output Length: 모델별 output_tokens 분포 (n, mean, median, p50, p95, std, histogram)
                  → 같은 prompt에 모델이 얼마나 장황한지 / 간결한지, 비용/지연 예측에 사용
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median, pstdev
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ProbeResult
from visibility import visible_only

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _parse_window(spec: str) -> timedelta:
    s = spec.strip().lower()
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    return timedelta(hours=24)


# stop_reason 정규화 — Bedrock과 Anthropic SDK가 다른 형태를 반환할 수 있음.
# 정규 키 집합 (UI에서 색상/라벨 매핑에 사용):
#   end_turn | max_tokens | stop_sequence | tool_use | guardrail_intervened | content_filtered | other | unknown
_STOP_REASON_ALIASES = {
    "end_turn": "end_turn",
    "endturn": "end_turn",
    "max_tokens": "max_tokens",
    "maxtokens": "max_tokens",
    "stop_sequence": "stop_sequence",
    "stopsequence": "stop_sequence",
    "tool_use": "tool_use",
    "tooluse": "tool_use",
    "guardrail_intervened": "guardrail_intervened",
    "guardrailintervened": "guardrail_intervened",
    "content_filtered": "content_filtered",
    "contentfiltered": "content_filtered",
}


def _normalize_stop_reason(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    key = raw.strip().lower().replace("-", "_")
    if key in _STOP_REASON_ALIASES:
        return _STOP_REASON_ALIASES[key]
    # fallback: snake/camelCase 변환
    no_underscore = key.replace("_", "")
    return _STOP_REASON_ALIASES.get(no_underscore, "other")


# ───────────────────────────────────────────────────────────────────────
# Stop Reason 분포
# ───────────────────────────────────────────────────────────────────────


class StopReasonRow(BaseModel):
    model_id: str
    model_name: str
    total: int
    counts: dict[str, int]       # {"end_turn": 12, "max_tokens": 3, ...}
    percentages: dict[str, float]  # {"end_turn": 80.0, "max_tokens": 20.0, ...}


class StopReasonResponse(BaseModel):
    window: str
    category: Optional[str]
    rows: list[StopReasonRow]


@router.get("/stop-reasons", response_model=StopReasonResponse)
def get_stop_reasons(
    window: str = Query("7d", description="시간 윈도우 (예: 24h, 7d, 30d)"),
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """모델별 stop_reason 분포 (success status만 집계)."""
    cutoff = datetime.now(timezone.utc) - _parse_window(window)

    q = visible_only(db.query(ProbeResult), ProbeResult.model_name).filter(
        ProbeResult.timestamp >= cutoff,
        ProbeResult.status == "success",
    )
    if category:
        q = q.filter(ProbeResult.category == category)

    grouped: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in q.all():
        key = (row.model_id, row.model_name)
        grouped[key][_normalize_stop_reason(row.stop_reason)] += 1

    rows: list[StopReasonRow] = []
    for (model_id, model_name), counter in grouped.items():
        total = sum(counter.values())
        if total == 0:
            continue
        counts = dict(counter)
        percentages = {k: round(v * 100.0 / total, 1) for k, v in counts.items()}
        rows.append(StopReasonRow(
            model_id=model_id,
            model_name=model_name,
            total=total,
            counts=counts,
            percentages=percentages,
        ))

    rows.sort(key=lambda r: r.model_name)
    return StopReasonResponse(window=window, category=category, rows=rows)


# ───────────────────────────────────────────────────────────────────────
# Output Length 분포
# ───────────────────────────────────────────────────────────────────────


class OutputLengthRow(BaseModel):
    model_id: str
    model_name: str
    n: int
    mean: float
    median: float
    p50: float
    p95: float
    std: float
    min: int
    max: int
    histogram: list[dict]   # [{"bin": "0-100", "count": 5}, ...]


class OutputLengthResponse(BaseModel):
    window: str
    category: Optional[str]
    rows: list[OutputLengthRow]


def _percentile(sorted_vals: list[int], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = q * (len(sorted_vals) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# 히스토그램 빈 (output_tokens 기준)
_HISTOGRAM_BINS = [
    (0, 100),
    (100, 250),
    (250, 500),
    (500, 1000),
    (1000, 2000),
    (2000, 4000),
    (4000, 1_000_000),  # 4000+
]


def _bin_label(lo: int, hi: int) -> str:
    if hi >= 1_000_000:
        return f"{lo}+"
    return f"{lo}-{hi}"


def _build_histogram(values: list[int]) -> list[dict]:
    counts = [0] * len(_HISTOGRAM_BINS)
    for v in values:
        for i, (lo, hi) in enumerate(_HISTOGRAM_BINS):
            if lo <= v < hi:
                counts[i] += 1
                break
    return [
        {"bin": _bin_label(lo, hi), "count": c}
        for (lo, hi), c in zip(_HISTOGRAM_BINS, counts)
    ]


@router.get("/output-length", response_model=OutputLengthResponse)
def get_output_length(
    window: str = Query("7d", description="시간 윈도우 (예: 24h, 7d, 30d)"),
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """모델별 output_tokens 분포 통계 + 히스토그램."""
    cutoff = datetime.now(timezone.utc) - _parse_window(window)

    q = visible_only(db.query(ProbeResult), ProbeResult.model_name).filter(
        ProbeResult.timestamp >= cutoff,
        ProbeResult.status == "success",
        ProbeResult.output_tokens.isnot(None),
    )
    if category:
        q = q.filter(ProbeResult.category == category)

    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in q.all():
        if row.output_tokens is None or row.output_tokens < 0:
            continue
        grouped[(row.model_id, row.model_name)].append(int(row.output_tokens))

    rows: list[OutputLengthRow] = []
    for (model_id, model_name), vals in grouped.items():
        if not vals:
            continue
        sorted_vals = sorted(vals)
        rows.append(OutputLengthRow(
            model_id=model_id,
            model_name=model_name,
            n=len(vals),
            mean=round(mean(vals), 1),
            median=float(median(vals)),
            p50=round(_percentile(sorted_vals, 0.5), 1),
            p95=round(_percentile(sorted_vals, 0.95), 1),
            std=round(pstdev(vals), 1) if len(vals) > 1 else 0.0,
            min=min(vals),
            max=max(vals),
            histogram=_build_histogram(vals),
        ))

    rows.sort(key=lambda r: r.model_name)
    return OutputLengthResponse(window=window, category=category, rows=rows)
