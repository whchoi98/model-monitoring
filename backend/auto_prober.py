"""Auto-prober — Phase 8부터 데몬 스레드 제거.

v1: backend 프로세스 내부 데몬 스레드가 5분마다 자동 호출.
v2: EventBridge Scheduler가 별도 Fargate Task(`auto_prober_runner`)를 5분마다 실행.

본 모듈은 두 가지 경로에서 재사용되는 `_run_cycle()`만 노출:
  - Fargate one-shot runner (`backend.auto_prober_runner`)
  - 수동 trigger API (`/api/auto-probe/trigger`) — backend 프로세스에서 동기 실행
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from typing import Optional

from database import SessionLocal
from models import ProbeRun
from prober import AVAILABLE_MODELS, _get_bedrock_client, _get_region_for_model, _probe_single_model

logger = logging.getLogger(__name__)

PROBE_PROMPT = "Explain what cloud computing is in 2-3 sentences."


class AutoProber:
    """단순 컨테이너 — in-process status 추적 (트리거 endpoint 가독성용)."""

    def __init__(self) -> None:
        self.last_run_time: Optional[datetime] = None
        self.current_cycle_running = False
        # v1 호환 필드 — v2에서는 외부 Scheduler가 관리하므로 항상 False.
        self.is_running = False
        self.next_run_time: Optional[datetime] = None

    def trigger(self) -> None:
        """수동 트리거 — backend 프로세스 별도 스레드에서 1회 실행."""
        threading.Thread(target=self._run_once_safe, daemon=True).start()

    def _run_once_safe(self) -> None:
        try:
            run_cycle()
        except Exception:
            logger.exception("auto_prober manual trigger 실행 실패")


def run_cycle() -> int:
    """모든 모델을 한 번 프로빙하고 DB에 결과를 저장. run_id 반환."""
    auto_prober.current_cycle_running = True
    logger.info("AutoProber: starting probe cycle")

    db = SessionLocal()
    try:
        run = ProbeRun(
            prompt=PROBE_PROMPT,
            temperature=0.1,
            max_tokens=256,
            concurrency=3,
            repeat_count=1,
            status="running",
            is_auto=1,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    except Exception:
        logger.exception("AutoProber: failed to create probe run")
        db.close()
        auto_prober.current_cycle_running = False
        raise

    event_queue: Queue = Queue()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for model_id, model_name in AVAILABLE_MODELS.items():
            client = _get_bedrock_client(_get_region_for_model(model_id))
            thread_db = SessionLocal()
            future = executor.submit(
                _probe_single_model,
                client,
                model_id,
                model_name,
                PROBE_PROMPT,
                0.1,
                256,
                1,
                event_queue,
                run_id,
                thread_db,
            )
            futures.append((future, thread_db))

        for future, thread_db in futures:
            try:
                future.result(timeout=120)
            except Exception:
                logger.exception("AutoProber: model probe failed")
            finally:
                thread_db.close()

    try:
        run = db.query(ProbeRun).filter(ProbeRun.id == run_id).first()
        if run:
            run.status = "completed"
            db.commit()
    except Exception:
        logger.exception("AutoProber: failed to update run status")
    finally:
        db.close()

    auto_prober.last_run_time = datetime.now(timezone.utc)
    auto_prober.current_cycle_running = False
    logger.info("AutoProber: cycle completed (run_id=%d)", run_id)
    return run_id


# 싱글톤 — 트리거 endpoint가 in-process status를 읽는 용도.
auto_prober = AutoProber()
