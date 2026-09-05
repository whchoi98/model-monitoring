"""Claude API Features 검증 API (v2.23.0).

- GET  /api/features/catalog   — 그룹·surface·모델·피처(문서 기대치 포함)
- GET  /api/features/latest    — 최신 완료 런 매트릭스 + 직전 런 diff + 드리프트 목록 (s-maxage=60)
- GET  /api/features/evidence  — 셀(feature, surface, model_key) 전체 증거
- POST /api/features/trigger   — 수동 런 (JWT, backend 내 백그라운드 스레드)
"""

import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from claude_features import catalog
from claude_features.engine import diff_runs
from database import get_db
from models import FeatureResult, FeatureRun

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/features", tags=["features"])

_run_lock = threading.Lock()
_running = {"active": False}


@router.get("/catalog")
def get_catalog():
    return {
        "groups": catalog.GROUPS,
        "surfaces": [{"id": s, **catalog.SURFACE_META[s], "region": catalog.region_for(s)} for s in catalog.SURFACES],
        "models": catalog.MODELS,
        "features": catalog.FEATURES,
    }


def build_latest_payload(run, rows, prev_rows, prev_run_id, running: bool) -> dict[str, Any]:
    results = [
        {"feature": r.feature, "surface": r.surface, "model_key": r.model_key, "model_label": r.model_label,
         "model_id": r.model_id, "status": r.status, "documented": r.documented, "verdict": r.verdict,
         "latency_ms": r.latency_ms}
        for r in rows
    ]
    changes: list[dict] = []
    if prev_rows is not None:
        prev_map = {(p.feature, p.surface, p.model_key): p.status for p in prev_rows}
        cur_map = {(r.feature, r.surface, r.model_key): r.status for r in rows}
        labels = {r.model_key: r.model_label for r in rows}
        changes = [{**c, "model_label": labels.get(c["model_key"], c["model_key"])} for c in diff_runs(prev_map, cur_map)]
    drift = [r for r in results if r["verdict"] == "drift"]
    return {
        "run": {"id": run.id, "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "totals": run.totals, "catalog_version": run.catalog_version, "running": running},
        "previous_run_id": prev_run_id,
        "changes": changes,
        "drift": drift,
        "results": results,
    }


@router.get("/latest")
def get_latest(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    run = db.query(FeatureRun).filter(FeatureRun.status == "completed").order_by(desc(FeatureRun.id)).first()
    if not run:
        return {"run": None, "previous_run_id": None, "changes": [], "drift": [], "results": [], "running": _running["active"]}
    cols = (FeatureResult.feature, FeatureResult.surface, FeatureResult.model_key, FeatureResult.model_label,
            FeatureResult.model_id, FeatureResult.status, FeatureResult.documented, FeatureResult.verdict, FeatureResult.latency_ms)
    rows = db.query(*cols).filter(FeatureResult.run_id == run.id).all()
    prev_run = (db.query(FeatureRun).filter(FeatureRun.status == "completed", FeatureRun.id < run.id)
                .order_by(desc(FeatureRun.id)).first())
    prev_rows = None
    if prev_run:
        prev_rows = (db.query(FeatureResult.feature, FeatureResult.surface, FeatureResult.model_key, FeatureResult.status)
                     .filter(FeatureResult.run_id == prev_run.id).all())
    return build_latest_payload(run, rows, prev_rows, prev_run.id if prev_run else None, _running["active"])


@router.get("/evidence")
def get_evidence(run_id: int = Query(...), feature: str = Query(...), surface: str = Query(...),
                 model_key: str = Query(...), db: Session = Depends(get_db)):
    row = (db.query(FeatureResult)
           .filter(FeatureResult.run_id == run_id, FeatureResult.feature == feature,
                   FeatureResult.surface == surface, FeatureResult.model_key == model_key).first())
    if not row:
        raise HTTPException(status_code=404, detail="result not found")
    fdef = next((f for f in catalog.FEATURES if f["id"] == feature), {})
    return {"feature": row.feature, "surface": row.surface, "model_key": row.model_key, "model_label": row.model_label,
            "model_id": row.model_id, "status": row.status, "documented": row.documented, "verdict": row.verdict,
            "latency_ms": row.latency_ms, "evidence": row.evidence, "error_message": row.error_message,
            "doc_url": fdef.get("doc_url"), "verification": fdef.get("verification"), "notes": fdef.get("notes")}


@router.post("/trigger")
def trigger(user=Depends(get_current_user)):
    with _run_lock:
        if _running["active"]:
            return {"triggered": False, "message": "이미 실행 중입니다"}
        _running["active"] = True

    def _worker():
        try:
            from claude_features.runner import run_features
            run_features()
        except Exception:
            logger.exception("Features run failed")
        finally:
            _running["active"] = False

    threading.Thread(target=_worker, daemon=True, name="features-run").start()
    return {"triggered": True, "message": "Claude API Features 검증 런을 시작했습니다 (약 7분 소요)"}
