"""PricingSync Fargate one-shot 진입점 (v2.30.0, ADR-030) — EventBridge Scheduler `rate(12 hours)`.

ECS Task Definition CMD:
  python -m pricing_sync_runner --once

순서 (spec "12시간 동기화" 1~2단계):
  1. create_tables() — price_history / price_sync_runs 보장 (backend 재배포 전에 먼저 돌 수 있음)
  2. 모델 등록 — prober._discover_anthropic_models() (CP on AWS /v1/models), prober._register_openai_models()
  3. active_channels(AVAILABLE_MODELS, hidden_patterns()) — 숨김 라벨(기본 "(1P)") 제외
  4. ensure_seed(engine, active) — 실패하면 동기화하지 않는다: seed 없이 돌면 seed 대상 채널이 전부
     no_baseline pending 행이 되고, 그 행 때문에 이후 ensure_seed가 그 model_id를 건너뛴다
  5. run_sync — PostgreSQL에서는 pg_try_advisory_lock(917350004) 아래(수동 실행과 스케줄 실행이 겹치지
     않게, 못 잡으면 즉시 종료). SQLite(로컬/테스트)는 잠금 생략
  6. os._exit — auto_prober_runner와 같은 종료 경로 (v2.28.2)

exit code: 0 = 런 completed 또는 partial, 1 = 런 failed, 잠금 점유 중, seed/동기화 예외.
"""

import argparse
import logging
import os
import sys
from collections import Counter
from contextlib import contextmanager

from sqlalchemy import text

from database import SessionLocal, create_tables, engine
from models import PriceSyncRun
from prober import AVAILABLE_MODELS, _discover_anthropic_models, _register_openai_models
from pricing_seed import ensure_seed
from pricing_sources import active_channels
from pricing_sync import SYNC_LOCK_KEY, default_fetchers, run_sync
from visibility import hidden_patterns

logger = logging.getLogger("pricing_sync_runner")

EXIT_OK = 0
EXIT_FAILED = 1
_OK_STATUSES = ("completed", "partial")


def _register_models() -> None:
    """auto_prober_runner와 같은 등록 — 하나가 실패해도 나머지는 등록한다(누락 채널은 동기화 대상에서 빠짐)."""
    for register in (_discover_anthropic_models, _register_openai_models):
        try:
            register()
        except Exception:  # noqa: BLE001 — 등록 실패는 non-fatal (CP 채널 없음 → 런 partial)
            logger.exception("pricing_sync_runner: model registration failed (non-fatal)")


@contextmanager
def _sync_lock(bind):
    """PostgreSQL 세션 advisory lock(SYNC_LOCK_KEY)을 런 전체 동안 쥔다. yield 값 = 잡았는지 여부."""
    if bind.dialect.name != "postgresql":
        yield True
        return
    conn = bind.connect()
    acquired = False
    try:
        acquired = bool(
            conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK_KEY}).scalar()
        )
        conn.commit()  # 세션 잠금은 트랜잭션과 무관 — idle-in-transaction으로 5분 머물지 않게 닫는다
        yield acquired
    finally:
        try:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK_KEY})
                conn.commit()
        except Exception:  # noqa: BLE001 — 해제 실패 시 커넥션을 버려 세션 잠금도 함께 끝낸다
            logger.exception("pricing_sync_runner: advisory unlock failed — invalidating the connection")
            conn.invalidate()
        finally:
            conn.close()


def _report(run_id: int) -> int:
    db = SessionLocal()
    try:
        run = db.get(PriceSyncRun, run_id)
        status = run.status if run is not None else "missing"
        summary = (run.summary if run is not None else None) or {}
        changes = run.changes if run is not None else 0
        pending = run.pending if run is not None else 0
    finally:
        db.close()
    results = Counter((summary.get("channels") or {}).values())
    logger.info(
        "pricing_sync_runner: run_id=%d status=%s changes=%d pending=%d results=%s errors=%d",
        run_id, status, changes, pending, dict(sorted(results.items())), len(summary.get("errors") or []),
    )
    return EXIT_OK if status in _OK_STATUSES else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Sync official unit prices once and exit")
    parser.add_argument("--once", action="store_true", help="실행 1회 후 종료 (현재 유일한 모드)")
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("--once 필수")

    try:
        create_tables()
    except Exception:
        logger.exception("pricing_sync_runner: create_tables failed")
        return EXIT_FAILED

    _register_models()
    active = active_channels(AVAILABLE_MODELS, hidden_patterns())
    logger.info("pricing_sync_runner: %d active channels", len(active))

    try:
        inserted = ensure_seed(engine, active)
    except Exception:
        logger.exception("pricing_sync_runner: ensure_seed failed — sync skipped")
        return EXIT_FAILED
    logger.info("pricing_sync_runner: ensure_seed inserted %d rows", inserted)

    try:
        with _sync_lock(engine) as acquired:
            if not acquired:
                logger.warning("pricing_sync_runner: lock %d held by another sync — exiting", SYNC_LOCK_KEY)
                return EXIT_FAILED
            run_id = run_sync(SessionLocal, active, default_fetchers())
        return _report(run_id)
    except Exception:
        logger.exception("pricing_sync_runner: sync failed")
        return EXIT_FAILED


def _finish(exit_code: int, _exit=os._exit) -> None:
    """auto_prober_runner._finish와 같다: DB 엔진 정리 + 로그 flush 후 os._exit (남은 스레드를 기다리지 않음)."""
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001 — 종료 경로는 어떤 정리 실패에도 막히지 않는다
        logging.exception("pricing_sync_runner: engine dispose failed (ignored)")
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    _exit(exit_code)


if __name__ == "__main__":
    _finish(main())
