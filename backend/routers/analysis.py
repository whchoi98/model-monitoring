"""Output Analysis - Stop Reason 분포 + Output Token 길이 분포.

LLM 특유의 시그널을 시각화:
  - Stop Reason: end_turn(정상) / max_tokens(잘림) / tool_use / stop_sequence /
                 guardrail_intervened / content_filtered 비율
                 → max_tokens 비율이 높으면 prompt 설계 문제, content_filtered가 높으면 안전성 시그널
  - Output Length: 모델별 output_tokens 분포 (n, mean, median, p50, p95, std, histogram)
                  → 같은 prompt에 모델이 얼마나 장황한지 / 간결한지, 비용/지연 예측에 사용

메모리 (2026-09-30 OOM): 두 엔드포인트는 /analysis 화면이 동시에 부른다. 예전에는 창 안의 success 행을
prompt, output_text까지 담은 ORM 엔티티로 모두 읽어 7d 기본 창 두 요청이 backend 태스크(1024 MiB)를 OOM(exit 137)으로
죽였다. 지금은 DB에서 GROUP BY로 센 행 수만 읽고(모델 × 값 종류), 창은 최대 30일이다(window_spec.parse_window, 넘으면 422).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import mean, median, pstdev
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import ProbeResult
from visibility import visible_only
from window_spec import parse_window

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# 창 상한 = /analysis 화면의 가장 긴 창(24h, 7d, 30d 중 30d). 넘는 창은 422.
_MAX_WINDOW = timedelta(days=30)


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
    cutoff = datetime.now(timezone.utc) - parse_window(window, max_window=_MAX_WINDOW)

    # 원래 stop_reason 값별 행 수를 DB에서 센다(GROUP BY) — 엔티티를 읽지 않으니 메모리는 모델 × 값 종류.
    # 정규화는 그 뒤에 하고 같은 정규 키끼리 합친다. model_name 동률인 행과 counts 키는 창 안에서 처음 나온
    # 순서(min(id))로 둔다 — 예전 코드는 DB가 돌려준 행 순서를 따랐고, 행을 id 순으로 돌면 결과가 같다.
    q = visible_only(
        db.query(ProbeResult.model_id, ProbeResult.model_name, ProbeResult.stop_reason,
                 func.count(ProbeResult.id), func.min(ProbeResult.id)),
        ProbeResult.model_name,
    ).filter(
        ProbeResult.timestamp >= cutoff,
        ProbeResult.status == "success",
    )
    if category:
        q = q.filter(ProbeResult.category == category)
    q = q.group_by(ProbeResult.model_id, ProbeResult.model_name, ProbeResult.stop_reason)

    # (model_id, model_name) → {"first_id", "reasons": {정규 키: [행 수, 처음 나온 id]}}
    grouped: dict[tuple[str, str], dict] = {}
    for model_id, model_name, raw_reason, n, first_id in q:
        slot = grouped.setdefault((model_id, model_name), {"first_id": first_id, "reasons": {}})
        slot["first_id"] = min(slot["first_id"], first_id)
        reason = slot["reasons"].setdefault(_normalize_stop_reason(raw_reason), [0, first_id])
        reason[0] += n
        reason[1] = min(reason[1], first_id)

    rows: list[StopReasonRow] = []
    for (model_id, model_name), slot in sorted(grouped.items(), key=lambda kv: kv[1]["first_id"]):
        counts = {k: v[0] for k, v in sorted(slot["reasons"].items(), key=lambda kv: kv[1][1])}
        total = sum(counts.values())
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
    cutoff = datetime.now(timezone.utc) - parse_window(window, max_window=_MAX_WINDOW)

    # output_tokens 값별 행 수를 DB에서 센다(GROUP BY). 자동 프로브 max_tokens가 512 이하, 수동이 4096 이하라
    # 그룹 수는 모델 × 수백이다. 통계에는 값 목록이 필요하므로 [값] * 행 수로 펼친다 — 원소는 같은 int를 가리켜
    # 포인터 하나(8 B)씩이고, mean, median, pstdev, 백분위, 히스토그램 모두 값의 순서와 무관해 예전 결과와 같다.
    q = visible_only(
        db.query(ProbeResult.model_id, ProbeResult.model_name, ProbeResult.output_tokens,
                 func.count(ProbeResult.id), func.min(ProbeResult.id)),
        ProbeResult.model_name,
    ).filter(
        ProbeResult.timestamp >= cutoff,
        ProbeResult.status == "success",
        ProbeResult.output_tokens.isnot(None),
    )
    if category:
        q = q.filter(ProbeResult.category == category)
    q = q.group_by(ProbeResult.model_id, ProbeResult.model_name, ProbeResult.output_tokens)

    # (model_id, model_name) → {"first_id", "vals"} — 음수 값은 예전처럼 건너뛴다(그 그룹만으로는 행이 생기지 않는다).
    # 행 순서(model_name 동률)는 stop-reasons와 같이 창 안에서 처음 나온 순서다.
    grouped: dict[tuple[str, str], dict] = {}
    for model_id, model_name, tokens, n, first_id in q:
        if tokens is None or tokens < 0:
            continue
        slot = grouped.setdefault((model_id, model_name), {"first_id": first_id, "vals": []})
        slot["first_id"] = min(slot["first_id"], first_id)
        slot["vals"].extend([int(tokens)] * n)

    rows: list[OutputLengthRow] = []
    for (model_id, model_name), slot in sorted(grouped.items(), key=lambda kv: kv[1]["first_id"]):
        vals = slot["vals"]
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
