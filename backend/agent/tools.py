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

    q = db.query(ProbeResult).filter(ProbeResult.run_id == latest_run.id)
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


def get_trend(db: Session, hours: int = 24, metric: str = "ttft_ms") -> Dict[str, Any]:
    """최근 N시간 자동 프로브 결과 시계열.

    metric: ttft_ms / total_latency_ms / tps 중 하나.
    """
    allowed = {"ttft_ms", "total_latency_ms", "tps"}
    if metric not in allowed:
        return {"error": f"metric must be one of {sorted(allowed)}"}

    hours = max(1, min(hours, 168))  # 1h ~ 7d 제한
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    runs = (
        db.query(ProbeRun)
        .filter(ProbeRun.is_auto == 1, ProbeRun.status == "completed", ProbeRun.created_at >= cutoff)
        .all()
    )
    if not runs:
        return {"hours": hours, "metric": metric, "points": []}

    run_ids = [r.id for r in runs]
    rows = (
        db.query(ProbeResult)
        .filter(ProbeResult.run_id.in_(run_ids))
        .order_by(ProbeResult.timestamp)
        .all()
    )

    points: List[Dict[str, Any]] = []
    for r in rows:
        value = getattr(r, metric)
        if value is None:
            continue
        points.append(
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "model_id": r.model_id,
                "model_name": r.model_name,
                "value": value,
            }
        )

    return {"hours": hours, "metric": metric, "points": points}


def compare_models(db: Session, metric: str = "ttft_ms", hours: int = 24) -> Dict[str, Any]:
    """최근 N시간 동안의 모델별 metric 평균/p50/p95 요약."""
    trend = get_trend(db, hours=hours, metric=metric)
    if "error" in trend:
        return trend

    # 모델별 값 묶기.
    by_model: Dict[str, List[float]] = {}
    for p in trend.get("points", []):
        by_model.setdefault(p["model_name"], []).append(float(p["value"]))

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
