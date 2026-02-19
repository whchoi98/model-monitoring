"""Background auto-probing thread.

Periodically probes all available models and stores results in the DB.
Reuses _probe_single_model from prober.py but discards SSE events.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from queue import Queue

from database import SessionLocal
from models import ProbeRun
from prober import AVAILABLE_MODELS, _get_bedrock_client, _get_region_for_model, _probe_single_model

logger = logging.getLogger(__name__)

PROBE_INTERVAL = 300  # 5 minutes
PROBE_PROMPT = "Explain what cloud computing is in 2-3 sentences."


class AutoProber:
    """Singleton background thread that probes all models on a fixed interval."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.last_run_time: datetime | None = None
        self.next_run_time: datetime | None = None
        self.is_running = False
        self.current_cycle_running = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("AutoProber started (interval=%ds)", PROBE_INTERVAL)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("AutoProber stopped")

    def trigger(self) -> None:
        """Trigger a one-off cycle immediately in a separate thread."""
        threading.Thread(target=self._run_cycle, daemon=True).start()

    def _loop(self) -> None:
        self.is_running = True
        while not self._stop_event.is_set():
            try:
                self._run_cycle()
            except Exception:
                logger.exception("AutoProber cycle failed unexpectedly")
            self.next_run_time = datetime.now(timezone.utc) + timedelta(seconds=PROBE_INTERVAL)
            self._stop_event.wait(timeout=PROBE_INTERVAL)
        self.is_running = False

    def _run_cycle(self) -> None:
        """Probe all models once with concurrency=3."""
        self.current_cycle_running = True
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
            self.current_cycle_running = False
            return

        # Event queue — events are discarded (no SSE needed)
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
                    0.1,   # temperature
                    256,   # max_tokens
                    1,     # iteration
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

        self.last_run_time = datetime.now(timezone.utc)
        self.current_cycle_running = False
        logger.info("AutoProber: cycle completed (run_id=%d)", run_id)


# Singleton instance
auto_prober = AutoProber()
