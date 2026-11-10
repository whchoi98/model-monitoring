"""Model Explorer verification API (v2.40.0, ADR-035).

- GET  /api/explorer/latest  — every visible model's code examples (KO and EN) with the latest completed run's result
                               per example, the run-to-run changes and whether a run is in progress (s-maxage=60)
- POST /api/explorer/trigger — manual run in a backend daemon thread (JWT)

The examples come from model_explorer.examples at request time, so a release that changes an example shows the new
code at once; `stale_code` marks a result that was measured on an older version of that code. "Running" is read from
the DB (a `running` row started less than 30 minutes ago): the scheduled run is a separate Fargate task the backend
process cannot see, like /api/auto-probe/status.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Mapping

from fastapi import APIRouter, Depends, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from model_explorer.diff import diff_cells
from model_explorer.examples import API_NAMES, code_examples
from model_explorer.runner import visible_models
from models import ExplorerResult, ExplorerRun, User
from visibility import visible_only

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/explorer", tags=["explorer"])

RUNNING_WINDOW = timedelta(minutes=30)
_run_lock = threading.Lock()
_running = {"active": False}
# The manual run executes inside the backend service task (0.5 vCPU, 1 GiB — v2.32.1 OOM) and every example is a
# child Python of about 65 MB with the SDKs loaded, so it runs two at a time; the scheduled task keeps four.
TRIGGER_MAX_WORKERS = 2

_RESULT_COLUMNS = (ExplorerResult.model_id, ExplorerResult.model_name, ExplorerResult.api_id, ExplorerResult.status,
                   ExplorerResult.latency_ms, ExplorerResult.attempts, ExplorerResult.code_sha,
                   ExplorerResult.output_excerpt, ExplorerResult.error_message)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def db_running(db: Session, now: datetime) -> bool:
    return (db.query(ExplorerRun.id)
            .filter(ExplorerRun.status == "running", ExplorerRun.started_at >= now - RUNNING_WINDOW)
            .first()) is not None


def _cells(rows) -> dict[tuple[str, str], dict]:
    return {(r.model_id, r.api_id): {"status": r.status, "code_sha": r.code_sha, "model_name": r.model_name,
                                    "api": API_NAMES.get(r.api_id, r.api_id)} for r in rows}


def build_latest_payload(db: Session, models: Mapping[str, str], *, now: datetime, in_process: bool = False) -> dict:
    running = in_process or db_running(db, now)
    run = (db.query(ExplorerRun).filter(ExplorerRun.status == "completed")
           .order_by(desc(ExplorerRun.id)).first())
    rows = []
    prev_run = None
    changes: list[dict] = []
    if run is not None:
        rows = visible_only(db.query(*_RESULT_COLUMNS).filter(ExplorerResult.run_id == run.id),
                            ExplorerResult.model_name).all()
        prev_run = (db.query(ExplorerRun).filter(ExplorerRun.status == "completed", ExplorerRun.id < run.id)
                    .order_by(desc(ExplorerRun.id)).first())
        if prev_run is not None:
            prev_rows = visible_only(db.query(*_RESULT_COLUMNS).filter(ExplorerResult.run_id == prev_run.id),
                                     ExplorerResult.model_name).all()
            changes = diff_cells(_cells(prev_rows), _cells(rows))
    by_cell = {(r.model_id, r.api_id): r for r in rows}

    def result(model_id: str, example: dict) -> dict | None:
        r = by_cell.get((model_id, example["api_id"]))
        if r is None:
            return None
        return {"status": r.status, "latency_ms": r.latency_ms, "attempts": r.attempts,
                "error_message": r.error_message, "output_excerpt": r.output_excerpt, "run_id": run.id,
                "verified_at": _iso(run.finished_at), "stale_code": r.code_sha != example["code_sha"]}

    return {
        "run": None if run is None else {"id": run.id, "started_at": _iso(run.started_at),
                                         "finished_at": _iso(run.finished_at), "totals": run.totals},
        "running": running,
        "previous_run_id": None if prev_run is None else prev_run.id,
        "changes": changes,
        "models": {mid: {"examples": [{**ex, "result": result(mid, ex)} for ex in code_examples(mid)]}
                   for mid in models},
    }


@router.get("/latest")
def get_latest(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    return build_latest_payload(db, visible_models(), now=datetime.now(timezone.utc), in_process=_running["active"])


@router.post("/trigger")
def trigger(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    with _run_lock:
        if _running["active"] or db_running(db, datetime.now(timezone.utc)):
            return {"triggered": False, "message": "이미 실행 중입니다"}
        _running["active"] = True
    db.close()  # the run opens its own sessions; nothing here holds a transaction while it runs

    def _worker():
        try:
            from model_explorer.runner import run_explorer
            run_explorer(max_workers=TRIGGER_MAX_WORKERS)
        except Exception:
            logger.exception("Explorer run failed")
        finally:
            _running["active"] = False

    try:
        threading.Thread(target=_worker, daemon=True, name="explorer-run").start()
    except RuntimeError:  # "can't start new thread" — release the flag, or every later trigger says busy until restart
        _running["active"] = False
        logger.exception("Explorer run thread did not start")
        return {"triggered": False, "message": "검증 런을 시작하지 못했습니다"}
    return {"triggered": True, "message": "모델 탐색 검증 런을 시작했습니다 (약 2분 소요)"}
