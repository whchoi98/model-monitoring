"""Claude API Features 런 오케스트레이터 (v2.23.0).

feature × surface × model 잡을 팬아웃해 4개 전송기로 실행하고 RDS에 저장한다.
- ThreadPoolExecutor(4), 스레드별 DB 세션 금지 → 메인 스레드 일괄 저장 (parity/runner.py 패턴)
- 전송기는 surface당 1개를 런 시작 시 생성 (Mantle bearer 재사용)
- 실패 시 FeatureRun.status = failed + error_message (패리티의 공백 보완)
- 보존: 최근 KEEP_RUNS 초과 런 삭제
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from claude_features import catalog, engine
from claude_features.probes import PROBES, ProbeOutcome, run_probe
from claude_features.transports import Transport, build_transport

logger = logging.getLogger(__name__)

CATALOG_VERSION = "2026-09-05"
KEEP_RUNS = 60
_MAX_WORKERS = 4


def build_jobs(surfaces, features, models) -> tuple[list[dict], list[dict]]:
    surfaces = surfaces or catalog.SURFACES
    features = features or catalog.FEATURE_IDS
    models = models or catalog.MODEL_KEYS
    jobs: list[dict] = []
    decided: list[dict] = []
    for feature in features:
        for surface in surfaces:
            for model_key in models:
                base = {"feature": feature, "surface": surface, "model_key": model_key,
                        "model_id": catalog.model_id_for(surface, model_key),
                        "model_label": catalog.model_label(model_key),
                        "documented": catalog.documented_for(feature, surface)}
                ok, reason = catalog.is_applicable(feature, surface, model_key)
                if ok:
                    jobs.append(base)
                else:
                    decided.append({**base, "status": reason, "reason": catalog.na_reason(feature, surface, model_key)})
    return jobs, decided


def _transports(surfaces: list[str]) -> dict[str, Transport | Exception]:
    out: dict[str, Transport | Exception] = {}
    for s in surfaces:
        try:
            out[s] = build_transport(s)
        except Exception as exc:  # noqa: BLE001 — 자격/env 누락은 surface 전체 broken으로 기록
            logger.exception("transport init failed for %s", s)
            out[s] = exc
    return out


def _execute(transports: dict, job: dict) -> ProbeOutcome:
    t = transports[job["surface"]]
    if isinstance(t, Exception):
        return ProbeOutcome("broken", error=f"transport init: {type(t).__name__}: {t}"[:1500])
    return run_probe(PROBES[job["feature"]], t, job["model_id"], job["model_key"])


def _run_jobs(jobs: list[dict], on_result) -> dict[str, int]:
    counts: dict[str, int] = {s: 0 for s in engine.STATUSES}
    surfaces = sorted({j["surface"] for j in jobs})
    transports = _transports(surfaces)
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_execute, transports, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                outcome = fut.result()
            except Exception as exc:  # noqa: BLE001
                outcome = ProbeOutcome("broken", error=f"executor: {exc}"[:1500])
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            on_result(job, outcome)
            done += 1
            if done % 25 == 0:
                logger.info("features: %d/%d done %s", done, len(jobs), counts)
    return counts


def run_features(surfaces=None, features=None, models=None) -> int:
    from database import SessionLocal
    from models import FeatureResult, FeatureRun

    db = SessionLocal()
    try:
        run = FeatureRun(status="running", started_at=datetime.now(timezone.utc), catalog_version=CATALOG_VERSION)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    except Exception:
        db.close()
        raise

    jobs, decided = build_jobs(surfaces, features, models)
    logger.info("Features run %d: %d probes (+%d pre-decided)", run_id, len(jobs), len(decided))
    rows: list[FeatureResult] = [
        FeatureResult(run_id=run_id, feature=d["feature"], surface=d["surface"], model_key=d["model_key"],
                      model_label=d["model_label"], model_id=d["model_id"], status=d["status"], documented=d["documented"],
                      verdict=engine.verdict(d["documented"], d["status"]), evidence={"reason": d["reason"]})
        for d in decided
    ]
    drift = 0

    def on_result(job: dict, outcome: ProbeOutcome) -> None:
        nonlocal drift
        v = engine.verdict(job["documented"], outcome.status)
        drift += v == "drift"
        rows.append(FeatureResult(run_id=run_id, feature=job["feature"], surface=job["surface"], model_key=job["model_key"],
                                  model_label=job["model_label"], model_id=job["model_id"], status=outcome.status,
                                  documented=job["documented"], verdict=v, latency_ms=outcome.latency_ms,
                                  evidence=outcome.evidence or {}, error_message=outcome.error))

    try:
        counts = _run_jobs(jobs, on_result)
        for d in decided:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        counts["drift"] = drift
        db.add_all(rows)
        run = db.query(FeatureRun).filter(FeatureRun.id == run_id).first()
        run.status, run.finished_at, run.totals = (
            "completed",
            datetime.now(timezone.utc),
            counts,
        )
        db.commit()
        logger.info("Features run %d completed: %s", run_id, counts)
    except Exception as exc:
        _mark_failed(db, FeatureRun, run_id, exc)
        raise
    else:
        # 보존 정리는 런 성공과 분리 — 정리 실패가 완료된 런을 failed로 덮어쓰지 않도록 (non-fatal)
        try:
            _prune(db, FeatureRun, FeatureResult)
        except Exception:  # noqa: BLE001
            logger.exception("feature run prune failed (non-fatal)")
    finally:
        db.close()
    return run_id


def _prune(db, FeatureRun, FeatureResult) -> None:
    keep = [
        r.id
        for r in db.query(FeatureRun.id)
        .order_by(FeatureRun.id.desc())
        .limit(KEEP_RUNS)
    ]
    if not keep:
        return
    old = [
        r.id
        for r in db.query(FeatureRun.id)
        .filter(FeatureRun.id < min(keep))
        .all()
    ]
    if old:
        db.query(FeatureResult).filter(
            FeatureResult.run_id.in_(old)
        ).delete(synchronize_session=False)
        db.query(FeatureRun).filter(FeatureRun.id.in_(old)).delete(
            synchronize_session=False
        )
        db.commit()
        logger.info("pruned %d old feature runs", len(old))


def _mark_failed(db, FeatureRun, run_id: int, exc: Exception) -> None:
    """실패 상태 기록 — 여기서 난 예외는 원 예외를 가리지 않도록 로그만 남긴다."""
    try:
        db.rollback()
        run = db.query(FeatureRun).filter(FeatureRun.id == run_id).first()
        if run:
            run.status, run.finished_at, run.error_message = (
                "failed",
                datetime.now(timezone.utc),
                str(exc)[:1500],
            )
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("failed to mark feature run %d as failed", run_id)


def smoke(surfaces=None, features=None, models=None) -> list[dict]:
    """DB 없이 실행해 표로 출력할 결과 목록을 반환 (로컬 라이브 스모크)."""
    jobs, decided = build_jobs(surfaces, features, models)
    out: list[dict] = [
        {
            **d,
            "verdict": engine.verdict(d["documented"], d["status"]),
            "latency_ms": None,
            "error": None,
            "evidence": {"reason": d["reason"]},
        }
        for d in decided
    ]

    def on_result(job: dict, outcome: ProbeOutcome) -> None:
        out.append({**job, "status": outcome.status, "verdict": engine.verdict(job["documented"], outcome.status),
                    "latency_ms": outcome.latency_ms, "error": outcome.error, "evidence": outcome.evidence})

    _run_jobs(jobs, on_result)
    return out
