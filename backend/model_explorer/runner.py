"""Model Explorer verification run (v2.40.0, ADR-035) — every visible model × its code examples, executed for real.

- Jobs = visible prober.AVAILABLE_MODELS (labels without a HIDDEN_MODEL_PATTERNS pattern) × examples.code_examples.
- A ThreadPoolExecutor runs execute.execute on the EN code, 4 at a time (2 from the backend trigger, which runs inside
  the 1 GiB service task); rows are gathered on the main thread and saved at once (no DB session in a worker,
  parity/runner.py pattern). The pool is never a `with` block: results are awaited for sweep_wait_s() and the pool is
  shut down with wait=False (2026-09-23 rule) — an example with no result by then is failed "시간 초과 N초" if it was
  running, skipped "런 시간 상한" if it had not started.
- The `running` row is committed before the sweep and no transaction stays open during it (v2.32.2 rule).
- A run deadline (EXPLORER_RUN_DEADLINE_S, 1200 s) records the jobs that had not started as skipped.
- Retention: the latest KEEP_RUNS runs; a prune failure is logged and never turns a completed run into a failed one.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Callable, Mapping

from model_explorer import execute as executor
from model_explorer.examples import code_examples

logger = logging.getLogger(__name__)

KEEP_RUNS = 60
MAX_WORKERS = 4
SWEEP_WAIT_GRACE_S = 30.0
DEFAULT_RUN_DEADLINE_S = 1200.0
RUN_DEADLINE_REASON = "런 시간 상한"
STATUSES = ("passed", "failed", "skipped")


def run_deadline_s() -> float:
    return float(os.getenv("EXPLORER_RUN_DEADLINE_S", str(DEFAULT_RUN_DEADLINE_S)))


def visible_models(models: Mapping[str, str] | None = None) -> dict[str, str]:
    """{model_id: label} of the catalog without the hidden labels (visibility.HIDDEN_MODEL_PATTERNS)."""
    import prober
    from visibility import hidden_patterns

    patterns = hidden_patterns()
    source = prober.AVAILABLE_MODELS if models is None else models
    return {mid: label for mid, label in source.items() if not any(p in label for p in patterns)}


def build_jobs(models: Mapping[str, str], model_ids: list[str] | None = None) -> list[dict]:
    """One job per (model, example) in catalog order; `model_ids` narrows the models (CLI --models)."""
    jobs: list[dict] = []
    for model_id, label in models.items():
        if model_ids is not None and model_id not in model_ids:
            continue
        for example in code_examples(model_id):
            jobs.append({"model_id": model_id, "model_name": label, "api_id": example["api_id"],
                         "api": example["api"], "code": example["code"]["en"], "code_sha": example["code_sha"]})
    return jobs


def sweep_wait_s(deadline_s: float) -> float:
    """How long _sweep waits for results: the run deadline, one example started just before it with its retry
    (2 × execute.call_timeout_s()), and a grace for child start-up — 1,410 s with the defaults."""
    return deadline_s + 2 * executor.call_timeout_s() + SWEEP_WAIT_GRACE_S


def _outcome_of(future: Future) -> executor.Outcome:
    try:
        return future.result()
    except Exception as exc:  # noqa: BLE001 — one broken job never stops the run
        return executor.Outcome("failed", None, 0, None, f"executor: {type(exc).__name__}: {exc}"[:1500])


def _sweep(jobs: list[dict], execute_fn: Callable[[str], executor.Outcome], deadline_s: float,
           clock: Callable[[], float] = time.monotonic, *, max_workers: int | None = None,
           wait_s: float | None = None) -> list[tuple[dict, executor.Outcome]]:
    started = clock()
    workers = MAX_WORKERS if max_workers is None else max_workers
    wait_s = sweep_wait_s(deadline_s) if wait_s is None else wait_s

    def work(job: dict) -> executor.Outcome:
        if clock() - started > deadline_s:
            return executor.Outcome("skipped", None, 0, None, RUN_DEADLINE_REASON)
        return execute_fn(job["code"])

    done: list[tuple[dict, executor.Outcome]] = []
    seen: set[Future] = set()
    # Not a `with` block: its exit joins every worker, so one stuck example would hold the run — and the backend
    # trigger thread — forever (2026-09-23 freeze rule). Results are awaited for wait_s, then shutdown(wait=False).
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="explorer")
    futures = {pool.submit(work, job): job for job in jobs}
    try:
        for future in as_completed(futures, timeout=wait_s):
            seen.add(future)
            done.append((futures[future], _outcome_of(future)))
            if len(done) % 20 == 0:
                logger.info("explorer: %d/%d done", len(done), len(jobs))
    except FuturesTimeoutError:
        pool.shutdown(wait=False, cancel_futures=True)
        running = not_started = 0
        for future, job in futures.items():
            if future in seen:
                continue
            if future.cancelled():
                not_started += 1
                outcome = executor.Outcome("skipped", None, 0, None, RUN_DEADLINE_REASON)
            elif future.done():
                outcome = _outcome_of(future)
            else:
                running += 1
                outcome = executor.Outcome("failed", None, 1, None, f"시간 초과 {wait_s:g}초")
            done.append((job, outcome))
        logger.warning("explorer: no result after %gs — %d still running (failed), %d not started (skipped)",
                       wait_s, running, not_started)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return done


def _totals(results: list[tuple[dict, executor.Outcome]]) -> dict[str, int]:
    totals = dict.fromkeys(STATUSES, 0)
    for _, outcome in results:
        totals[outcome.status] = totals.get(outcome.status, 0) + 1
    return totals


def run_explorer(model_ids: list[str] | None = None, *, session_factory=None,
                 execute_fn: Callable[[str], executor.Outcome] | None = None,
                 models: Mapping[str, str] | None = None, deadline_s: float | None = None,
                 now: Callable[[], datetime] | None = None, max_workers: int | None = None) -> int:
    """One DB-recorded run; returns explorer_runs.id. Re-raises after marking the run failed."""
    from models import ExplorerResult, ExplorerRun

    if session_factory is None:
        from database import SessionLocal as session_factory
    clock = now or (lambda: datetime.now(timezone.utc))
    execute_fn = execute_fn or executor.execute
    deadline_s = run_deadline_s() if deadline_s is None else deadline_s

    db = session_factory()
    try:
        run = ExplorerRun(status="running", started_at=clock())
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()  # no refresh: the sweep runs with no transaction open
    finally:
        db.close()

    try:
        jobs = build_jobs(visible_models(models), model_ids)
        logger.info("Explorer run %d: %d examples, %d at a time", run_id, len(jobs),
                    MAX_WORKERS if max_workers is None else max_workers)
        results = _sweep(jobs, execute_fn, deadline_s, max_workers=max_workers)
        totals = _totals(results)
        db = session_factory()
        try:
            db.add_all([
                ExplorerResult(run_id=run_id, model_id=job["model_id"], model_name=job["model_name"],
                               api_id=job["api_id"], status=o.status, latency_ms=o.latency_ms, attempts=o.attempts,
                               code_sha=job["code_sha"], output_excerpt=o.output_excerpt, error_message=o.error_message)
                for job, o in sorted(results, key=lambda r: (r[0]["model_id"], r[0]["api_id"]))
            ])
            run = db.get(ExplorerRun, run_id)
            run.status, run.finished_at, run.totals = "completed", clock(), totals
            db.commit()
        finally:
            db.close()
        logger.info("Explorer run %d completed: %s", run_id, totals)
    except Exception as exc:
        _mark_failed(session_factory, run_id, clock(), exc)
        raise
    try:
        _prune(session_factory)
    except Exception:  # noqa: BLE001 — retention never fails a completed run
        logger.exception("explorer run prune failed (non-fatal)")
    return run_id


def _mark_failed(session_factory, run_id: int, finished_at: datetime, exc: BaseException) -> None:
    from models import ExplorerRun

    db = session_factory()
    try:
        run = db.get(ExplorerRun, run_id)
        if run is not None:
            run.status, run.finished_at, run.error_message = "failed", finished_at, str(exc)[:1500]
            db.commit()
    except Exception:  # noqa: BLE001 — the original error is re-raised by the caller
        db.rollback()
        logger.exception("failed to mark explorer run %d as failed", run_id)
    finally:
        db.close()


def _prune(session_factory) -> None:
    from models import ExplorerResult, ExplorerRun

    db = session_factory()
    try:
        keep = [r.id for r in db.query(ExplorerRun.id).order_by(ExplorerRun.id.desc()).limit(KEEP_RUNS)]
        if not keep:
            return
        old = [r.id for r in db.query(ExplorerRun.id).filter(ExplorerRun.id < min(keep)).all()]
        if old:
            db.query(ExplorerResult).filter(ExplorerResult.run_id.in_(old)).delete(synchronize_session=False)
            db.query(ExplorerRun).filter(ExplorerRun.id.in_(old)).delete(synchronize_session=False)
            db.commit()
            logger.info("pruned %d old explorer runs", len(old))
    finally:
        db.close()


def smoke(model_ids: list[str] | None = None, *, execute_fn: Callable[[str], executor.Outcome] | None = None,
          models: Mapping[str, str] | None = None) -> list[dict]:
    """Run without the DB and return one row per example (local check before a deploy)."""
    jobs = build_jobs(visible_models(models), model_ids)
    results = _sweep(jobs, execute_fn or executor.execute, run_deadline_s())
    return [
        {"model_id": job["model_id"], "model_name": job["model_name"], "api_id": job["api_id"], "status": o.status,
         "latency_ms": o.latency_ms, "attempts": o.attempts, "output_excerpt": o.output_excerpt,
         "error_message": o.error_message}
        for job, o in sorted(results, key=lambda r: (r[0]["model_id"], r[0]["api_id"]))
    ]
