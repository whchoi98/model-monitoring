"""Regression test for the auto-prober DB connection-pool exhaustion bug.

Root cause (2026-06-09 incident): run_cycle() eagerly created one `SessionLocal()`
per model in the submit loop and only closed each session in the *in-order* result
loop. A slow early probe (e.g. Opus 4.8 Global read-timeout) stalled the loop while
the other probes finished holding open connections (the post-commit `db.refresh()`
keeps a read transaction open until close). Once >pool (5+5=10) sessions accumulated,
the tail models failed with `QueuePool limit ... reached, connection timed out`.

This test asserts run_cycle never holds more concurrent DB sessions than the worker
pool allows, regardless of model count — guarding against the eager-session pattern.
"""

import threading
import time

import auto_prober


def test_run_cycle_bounds_concurrent_db_sessions(monkeypatch):
    open_count = 0
    peak = 0
    lock = threading.Lock()

    class FakeSession:
        def add(self, *a, **k):
            pass

        def commit(self, *a, **k):
            pass

        def refresh(self, obj, *a, **k):
            # mimic SQLAlchemy: populate PK/timestamp after flush
            if getattr(obj, "id", None) is None:
                obj.id = 1
            if getattr(obj, "timestamp", None) is None:
                from datetime import datetime, timezone

                obj.timestamp = datetime.now(timezone.utc)

        # query-chain stubs used by _next_preset() and run-status update
        def query(self, *a, **k):
            return self

        def join(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def first(self, *a, **k):
            return None

        def close(self):
            nonlocal open_count
            with lock:
                open_count -= 1

    def fake_session_local():
        nonlocal open_count, peak
        with lock:
            open_count += 1
            peak = max(peak, open_count)
        return FakeSession()

    # 30 fake models to stress concurrency well past the real pool (10).
    fake_models = {f"global.anthropic.m{i}": f"Bedrock M{i} (Global)" for i in range(30)}

    monkeypatch.setattr(auto_prober, "SessionLocal", fake_session_local)
    monkeypatch.setattr(auto_prober, "AVAILABLE_MODELS", fake_models)
    monkeypatch.setattr(auto_prober, "_get_bedrock_client", lambda region: object())
    monkeypatch.setattr(auto_prober, "_get_region_for_model", lambda mid: "us-east-1")

    def fake_probe(client, model_id, model_name, prompt, temperature,
                   max_tokens, iteration, event_queue, run_id, db, category=None):
        time.sleep(0.02)  # force worker overlap
        db.add(object())
        db.commit()
        db.refresh(type("R", (), {"id": None, "timestamp": None})())

    monkeypatch.setattr(auto_prober, "_probe_single_model", fake_probe)

    auto_prober.run_cycle()

    # Allowed: 1 long-lived run-level session + at most max_workers (3) probe sessions.
    assert peak <= 1 + 3, (
        f"run_cycle held {peak} concurrent DB sessions (>4) — eager per-model session "
        f"pattern would exhaust the 10-connection pool with 15 models."
    )
