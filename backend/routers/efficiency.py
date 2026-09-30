"""Token Efficiency Score - 같은 prompt(category)에 모델별 토큰·비용·속도 효율 종합 평가.

같은 workload preset(category)에서 측정된 결과만 비교 → 동일 task 기준 공정 비교.

Efficiency Score (0~100, 높을수록 좋음):
  - cost (inverse, 30%)        : 호출당 USD가 낮을수록 높은 점수
  - output tokens (inverse, 25%): 평균 출력 토큰이 적을수록 좋음 (간결한 응답)
  - latency (inverse, 20%)     : 평균 응답 시간이 짧을수록 좋음
  - tps (direct, 15%)          : 생성 속도가 빠를수록 좋음
  - success rate (direct, 10%) : 성공률
각 메트릭을 카테고리 내 min-max로 0~1 정규화 후 가중 합산.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ProbeResult
from visibility import visible_only
from price_history import with_row_cost
from streamed_read import stream_rows_or_503
from window_spec import parse_window

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/efficiency", tags=["efficiency"])


# 창 상한 = /efficiency 화면의 가장 긴 창(1h, 6h, 24h, 7d 중 7d). 넘는 창은 422 (window_spec).
# 공개 엔드포인트라 상한이 곧 요청 하나의 스캔 상한이다 — 2026-09-30 /analysis OOM과 같은 경로.
_MAX_WINDOW = timedelta(days=7)
_YIELD_PER = 2000  # 한 번에 가져오는 행 수(PostgreSQL은 서버 측 커서 — 전체 시간 상한은 streamed_read, 넘으면 503)


WEIGHTS = {
    "cost": 0.30,
    "output_tokens": 0.25,
    "latency": 0.20,
    "tps": 0.15,
    "success_rate": 0.10,
}


def _normalize_inverse(values: list[float], v: Optional[float]) -> Optional[float]:
    """낮을수록 좋은 metric → 0~1 (최고가 1, 최저가 0). 표본 1개면 1.0."""
    if v is None:
        return None
    valid = [x for x in values if x is not None]
    if not valid:
        return None
    lo, hi = min(valid), max(valid)
    if hi == lo:
        return 1.0
    return round(1.0 - (v - lo) / (hi - lo), 4)


def _normalize_direct(values: list[float], v: Optional[float]) -> Optional[float]:
    """높을수록 좋은 metric → 0~1 (최고가 1, 최저가 0). 표본 1개면 1.0."""
    if v is None:
        return None
    valid = [x for x in values if x is not None]
    if not valid:
        return None
    lo, hi = min(valid), max(valid)
    if hi == lo:
        return 1.0
    return round((v - lo) / (hi - lo), 4)


class ModelEfficiency(BaseModel):
    model_id: str
    model_name: str
    samples: int
    success_rate: Optional[float]
    avg_output_tokens: Optional[float]
    avg_input_tokens: Optional[float]
    avg_cost_usd: Optional[float]
    avg_total_latency_ms: Optional[float]
    avg_tps: Optional[float]
    score: Optional[float]  # 0~100
    # 구성 요소 점수 (디버깅용)
    components: dict[str, Optional[float]]


class EfficiencyResponse(BaseModel):
    window: str
    since: str
    category: Optional[str]
    models: list[ModelEfficiency]


@router.get("/score", response_model=EfficiencyResponse)
def get_efficiency_score(
    window: str = Query("24h"),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """모델별 token efficiency score (0~100).

    category 미지정 시 전체. 지정 시 그 카테고리만 (공정 비교 권장: 같은 prompt 기준).
    """
    since = datetime.now(timezone.utc) - parse_window(window, max_window=_MAX_WINDOW)
    # 집계에 쓰는 열만 나눠 읽는다. ORM 엔티티는 prompt, output_text까지 담아 7d에서 요청 하나가 0.4~0.6 GB였다.
    # 합산은 예전처럼 Python에서 행 순서대로 한다(SQL AVG로 바꾸면 합산 순서가 달라져 round 경계 값이 흔들리고,
    # model_name은 model_id별로 처음 본 행의 값이라 GROUP BY에 넣으면 라벨이 여러 개인 모델이 갈라진다).
    q, row_cost = with_row_cost(visible_only(
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            ProbeResult.status,
            ProbeResult.output_tokens,
            ProbeResult.input_tokens,
            ProbeResult.total_latency_ms,
            ProbeResult.tps,
        ),
        ProbeResult.model_name,
    ))
    q = q.add_columns(row_cost.label("row_cost")).filter(ProbeResult.timestamp >= since)
    if category:
        q = q.filter(ProbeResult.category == category)
    rows = stream_rows_or_503(q.yield_per(_YIELD_PER),
                              route=f"GET /api/efficiency/score window={window!r} category={category!r}")

    # Aggregate per model — 비용은 각 프로브 시각의 단가(row_cost, 단가 없으면 None)
    agg: dict[str, dict] = {}
    for model_id, model_name, status, output_tokens, input_tokens, total_latency_ms, tps, cost in rows:
        a = agg.setdefault(
            model_id,
            {
                "model_id": model_id,
                "model_name": model_name,
                "samples": 0,
                "success": 0,
                "out_tok": [],
                "in_tok": [],
                "latency": [],
                "tps": [],
                "costs": [],
            },
        )
        a["samples"] += 1
        if status == "success":
            a["success"] += 1
            if output_tokens is not None:
                a["out_tok"].append(float(output_tokens))
            if input_tokens is not None:
                a["in_tok"].append(float(input_tokens))
            if total_latency_ms is not None:
                a["latency"].append(float(total_latency_ms))
            if tps is not None:
                a["tps"].append(float(tps))
            if cost is not None:
                a["costs"].append(float(cost))

    # 모델별 평균 계산
    per_model: list[dict] = []
    for a in agg.values():
        def avg(lst):
            return round(sum(lst) / len(lst), 4) if lst else None

        success_rate = round(a["success"] / a["samples"], 4) if a["samples"] else None
        per_model.append({
            "model_id": a["model_id"],
            "model_name": a["model_name"],
            "samples": a["samples"],
            "success_rate": success_rate,
            "avg_output_tokens": avg(a["out_tok"]),
            "avg_input_tokens": avg(a["in_tok"]),
            "avg_cost_usd": avg(a["costs"]),
            "avg_total_latency_ms": avg(a["latency"]),
            "avg_tps": avg(a["tps"]),
        })

    # 카테고리 내 min-max 정규화 + 가중 합산
    all_costs = [m["avg_cost_usd"] for m in per_model]
    all_out = [m["avg_output_tokens"] for m in per_model]
    all_lat = [m["avg_total_latency_ms"] for m in per_model]
    all_tps = [m["avg_tps"] for m in per_model]
    all_succ = [m["success_rate"] for m in per_model]

    out: list[ModelEfficiency] = []
    for m in per_model:
        c_cost = _normalize_inverse(all_costs, m["avg_cost_usd"])
        c_out = _normalize_inverse(all_out, m["avg_output_tokens"])
        c_lat = _normalize_inverse(all_lat, m["avg_total_latency_ms"])
        c_tps = _normalize_direct(all_tps, m["avg_tps"])
        c_succ = _normalize_direct(all_succ, m["success_rate"])
        # 종합 점수 — 가중 합산. None 컴포넌트는 weight 0으로 처리.
        total_weight = 0.0
        total_score = 0.0
        for key, comp in (
            ("cost", c_cost),
            ("output_tokens", c_out),
            ("latency", c_lat),
            ("tps", c_tps),
            ("success_rate", c_succ),
        ):
            if comp is not None:
                w = WEIGHTS[key]
                total_score += comp * w
                total_weight += w
        score = round(100 * total_score / total_weight, 2) if total_weight > 0 else None
        out.append(ModelEfficiency(
            model_id=m["model_id"],
            model_name=m["model_name"],
            samples=m["samples"],
            success_rate=m["success_rate"],
            avg_output_tokens=m["avg_output_tokens"],
            avg_input_tokens=m["avg_input_tokens"],
            avg_cost_usd=m["avg_cost_usd"],
            avg_total_latency_ms=m["avg_total_latency_ms"],
            avg_tps=m["avg_tps"],
            score=score,
            components={
                "cost": c_cost,
                "output_tokens": c_out,
                "latency": c_lat,
                "tps": c_tps,
                "success_rate": c_succ,
            },
        ))
    out.sort(key=lambda x: (x.score or 0), reverse=True)
    return EfficiencyResponse(
        window=window,
        since=since.isoformat(),
        category=category,
        models=out,
    )
