"""패리티 런 API (v2.11.0).

- GET  /api/parity/latest    — 최신 완료 런의 매트릭스 데이터 (증거 제외 슬림)
- GET  /api/parity/evidence  — 특정 셀의 전체 증거
- GET  /api/parity/catalog   — 피처 카탈로그 (라벨·설명)
- POST /api/parity/trigger   — 수동 런 시작 (인증 필요, 백그라운드 스레드)
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import ParityResult, ParityRun
from parity.catalog import FEATURES, SURFACES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/parity", tags=["parity"])

_run_lock = threading.Lock()
_running = {"active": False}


@router.get("/catalog")
def get_catalog():
    return {"features": FEATURES, "surfaces": SURFACES}


@router.get("/latest")
def get_latest(response: Response, db: Session = Depends(get_db)):
    """최신 완료 런의 결과 매트릭스 (셀당 슬림 필드)."""
    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    run = (
        db.query(ParityRun)
        .filter(ParityRun.status == "completed")
        .order_by(desc(ParityRun.id))
        .first()
    )
    if not run:
        return {"run": None, "results": []}
    rows = (
        db.query(ParityResult.model_id, ParityResult.model_name, ParityResult.surface,
                 ParityResult.feature, ParityResult.status, ParityResult.latency_ms)
        .filter(ParityResult.run_id == run.id)
        .all()
    )
    return {
        "run": {
            "id": run.id,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "totals": run.totals,
            "running": _running["active"],
        },
        "results": [
            {"model_id": r.model_id, "model_name": r.model_name, "surface": r.surface,
             "feature": r.feature, "status": r.status, "latency_ms": r.latency_ms}
            for r in rows
        ],
    }


@router.get("/evidence")
def get_evidence(
    run_id: int = Query(...),
    model_id: str = Query(...),
    surface: str = Query(...),
    feature: str = Query(...),
    db: Session = Depends(get_db),
):
    """매트릭스 셀 클릭 시 — 해당 프로브의 전체 증거."""
    row = (
        db.query(ParityResult)
        .filter(ParityResult.run_id == run_id, ParityResult.model_id == model_id,
                ParityResult.surface == surface, ParityResult.feature == feature)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="result not found")
    return {
        "model_id": row.model_id, "model_name": row.model_name,
        "surface": row.surface, "feature": row.feature, "status": row.status,
        "latency_ms": row.latency_ms, "evidence": row.evidence,
        "error_message": row.error_message,
    }


@router.post("/trigger")
def trigger(user=Depends(get_current_user)):
    """수동 패리티 런 시작 — 실행 중이면 거부. 백그라운드 스레드에서 수행 (~5-10분)."""
    with _run_lock:
        if _running["active"]:
            return {"triggered": False, "message": "이미 실행 중입니다"}
        _running["active"] = True

    def _worker():
        try:
            from parity.runner import run_parity
            run_parity()
        except Exception:
            logger.exception("Parity run failed")
        finally:
            _running["active"] = False

    threading.Thread(target=_worker, daemon=True, name="parity-run").start()
    return {"triggered": True, "message": "패리티 런을 시작했습니다 (약 5-10분 소요)"}
