"""이상 징후 요약 (v2.12.0) — 최근 N시간 프로브 실패를 모델별로 집계.

대시보드 상단 라운드 박스용 순수 로직. 입력은 (model_name, status, error_message,
timestamp) 튜플 목록 — 라우터가 DB 조회 결과를 그대로 전달한다.
"""

from __future__ import annotations

from typing import Any, Iterable


def summarize_anomalies(rows: Iterable[tuple]) -> dict[str, Any]:
    """모델별 실패 집계. 실패가 있는 모델만, 실패 많은 순으로 반환."""
    per_model: dict[str, dict[str, Any]] = {}
    total_probes = 0
    total_failures = 0
    for model_name, status, error_message, ts in rows:
        total_probes += 1
        m = per_model.setdefault(model_name, {
            "model_name": model_name, "failures": 0, "total": 0,
            "last_error": None, "last_at": None,
        })
        m["total"] += 1
        if status != "success":
            total_failures += 1
            m["failures"] += 1
            if m["last_at"] is None or (ts is not None and ts > m["last_at"]):
                m["last_error"] = (error_message or "")[:200] or None
                m["last_at"] = ts
    models = sorted(
        (m for m in per_model.values() if m["failures"] > 0),
        key=lambda m: (-m["failures"], m["model_name"]),
    )
    for m in models:
        m["last_at"] = m["last_at"].isoformat() if m["last_at"] else None
    return {"total_probes": total_probes, "total_failures": total_failures, "models": models}
