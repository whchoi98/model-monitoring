"""챗봇 / 인사이트 잡이 호출하는 4개 도구 함수.

각 함수는 DB를 직접 질의하고 JSON-직렬화 가능한 dict를 반환한다.
LLM의 tool_use 응답에 매핑되어 다시 LLM에 tool_result로 돌아간다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import ProbeResult, ProbeRun
from visibility import visible_only


def get_latest_results(db: Session, model_id: Optional[str] = None) -> Dict[str, Any]:
    """모델별 최신 자동 프로브 결과 1건씩 반환.

    model_id 지정 시 해당 모델만, 미지정 시 가장 최근 완료된 auto run의 전 모델.
    """
    latest_run = (
        db.query(ProbeRun)
        .filter(ProbeRun.is_auto == 1, ProbeRun.status == "completed")
        .order_by(desc(ProbeRun.created_at))
        .first()
    )
    if not latest_run:
        return {"run_id": None, "results": []}

    q = visible_only(db.query(ProbeResult), ProbeResult.model_name).filter(ProbeResult.run_id == latest_run.id)
    if model_id:
        q = q.filter(ProbeResult.model_id == model_id)
    rows = q.order_by(ProbeResult.model_name).all()

    return {
        "run_id": latest_run.id,
        "run_created_at": latest_run.created_at.isoformat() if latest_run.created_at else None,
        "results": [
            {
                "model_id": r.model_id,
                "model_name": r.model_name,
                "status": r.status,
                "ttft_ms": r.ttft_ms,
                "total_latency_ms": r.total_latency_ms,
                "tps": r.tps,
                "output_tokens": r.output_tokens,
                "error_message": r.error_message,
            }
            for r in rows
        ],
    }


# get_trend 응답 포인트 상한 (2026-07-10 실사고 방지 — 아래 get_trend docstring 참고).
MAX_TREND_POINTS = 2500

_ALLOWED_METRICS = {"ttft_ms", "total_latency_ms", "tps"}


def _fetch_metric_rows(db: Session, hours: int, metric: str):
    """(timestamp, model_id, model_name, value) 슬림 튜플 목록 — 큰 TEXT 컬럼 미조회."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    metric_col = getattr(ProbeResult, metric)
    return (
        visible_only(db.query(ProbeResult.timestamp, ProbeResult.model_id,
                              ProbeResult.model_name, metric_col), ProbeResult.model_name)
        .join(ProbeRun, ProbeResult.run_id == ProbeRun.id)
        .filter(
            ProbeRun.is_auto == 1,
            ProbeRun.status == "completed",
            ProbeRun.created_at >= cutoff,
            metric_col.isnot(None),
        )
        .order_by(ProbeResult.timestamp)
        .all()
    )


def get_trend(db: Session, hours: int = 24, metric: str = "ttft_ms") -> Dict[str, Any]:
    """최근 N시간 자동 프로브 결과 시계열.

    metric: ttft_ms / total_latency_ms / tps 중 하나.

    토큰 폭발 방지 (2026-07-10 실사고): 원본 포인트를 무제한 반환하면 hours=168에서
    56k+ 포인트(≈1.6M 토큰)가 tool_result로 LLM 컨텍스트에 들어가 ConverseStream이
    'prompt is too long' (1M 상한)으로 죽는다. 6시간 초과는 (모델, 정시 버킷) 평균으로
    축약하고, 결과는 항상 MAX_TREND_POINTS 이하로 자른다.
    """
    if metric not in _ALLOWED_METRICS:
        return {"error": f"metric must be one of {sorted(_ALLOWED_METRICS)}"}

    hours = max(1, min(hours, 168))  # 1h ~ 7d 제한
    rows = _fetch_metric_rows(db, hours, metric)
    if not rows:
        return {"hours": hours, "metric": metric, "points": []}

    aggregation = "raw"
    if hours > 6:
        aggregation = "hourly_avg"
        buckets: Dict[tuple, List[float]] = {}
        ids: Dict[tuple, str] = {}
        for ts, model_id, model_name, value in rows:
            if ts is None:
                continue
            key = (model_name, ts.replace(minute=0, second=0, microsecond=0))
            buckets.setdefault(key, []).append(float(value))
            ids[key] = model_id
        points = [
            {
                "timestamp": bucket_ts.isoformat(),
                "model_id": ids[(name, bucket_ts)],
                "model_name": name,
                "value": round(sum(vals) / len(vals), 2),
                "sample_count": len(vals),
            }
            for (name, bucket_ts), vals in sorted(buckets.items(), key=lambda kv: kv[0][1])
        ]
    else:
        points = [
            {
                "timestamp": ts.isoformat() if ts else None,
                "model_id": model_id,
                "model_name": model_name,
                "value": value,
            }
            for ts, model_id, model_name, value in rows
        ]

    truncated = len(points) > MAX_TREND_POINTS
    if truncated:
        points = points[-MAX_TREND_POINTS:]  # 가장 최근 구간 우선

    out = {"hours": hours, "metric": metric, "aggregation": aggregation, "points": points}
    if truncated:
        out["note"] = f"points truncated to most recent {MAX_TREND_POINTS}"
    return out


def compare_models(db: Session, metric: str = "ttft_ms", hours: int = 24) -> Dict[str, Any]:
    """최근 N시간 동안의 모델별 metric 평균/p50/p95 요약.

    통계는 원본 값으로 계산한다 — get_trend의 시간 평균 축약을 거치면 p95가 뭉개진다.
    (요약만 반환하므로 토큰 폭발 위험 없음.)
    """
    if metric not in _ALLOWED_METRICS:
        return {"error": f"metric must be one of {sorted(_ALLOWED_METRICS)}"}
    hours = max(1, min(hours, 168))

    by_model: Dict[str, List[float]] = {}
    for _ts, _mid, model_name, value in _fetch_metric_rows(db, hours, metric):
        by_model.setdefault(model_name, []).append(float(value))

    summary: List[Dict[str, Any]] = []
    for name, values in by_model.items():
        if not values:
            continue
        values_sorted = sorted(values)
        n = len(values_sorted)
        avg = sum(values_sorted) / n
        p50 = values_sorted[n // 2]
        p95 = values_sorted[min(n - 1, int(n * 0.95))]
        summary.append(
            {
                "model_name": name,
                "sample_count": n,
                "avg": round(avg, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "min": round(min(values_sorted), 2),
                "max": round(max(values_sorted), 2),
            }
        )

    # metric에 따라 정렬: 낮을수록 좋은 지표(ttft/latency)면 ASC, tps면 DESC.
    reverse = metric == "tps"
    summary.sort(key=lambda s: s["avg"], reverse=reverse)
    return {"hours": hours, "metric": metric, "summary": summary}


def optimize_prompt(
    prompt: str,
    target: str = "shorter_with_same_quality",
) -> Dict[str, Any]:
    """프롬프트 최적화 제안 — 결과는 LLM이 직접 생성하도록 'guidance' 형태로 반환.

    DB 질의는 없고 LLM의 후속 호출이 실제 최적화를 수행한다.
    target은 'shorter_with_same_quality' / 'more_specific' / 'reduce_cost' 등.
    """
    target_norm = target.strip().lower()
    return {
        "input_prompt": prompt,
        "target": target_norm,
        "guidance": (
            "다음 원칙에 따라 프롬프트를 개선하고, 변경 사유를 한 줄씩 설명하시오:\n"
            "1) 불필요한 형용사/완곡 표현 제거\n"
            "2) 응답 형식을 명시 (e.g. 'JSON only', 'one-line answer')\n"
            "3) 응답 길이 상한을 직접 지정 (max_tokens와 정렬)\n"
            "4) 시스템 프롬프트로 옮길 수 있는 영구 컨텍스트 분리\n"
            f"목표: {target_norm}"
        ),
    }


# Tool name → callable 매핑.
TOOL_REGISTRY = {
    "get_latest_results": get_latest_results,
    "get_trend": get_trend,
    "compare_models": compare_models,
    "optimize_prompt": optimize_prompt,
}
