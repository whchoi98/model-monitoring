"""auto_prober_runner exit path (v2.28.2 hotfix).

sys.exit()는 인터프리터 종료 단계에서 ThreadPoolExecutor 워커를 join한다 — 사이클이 포기한 멈춘
스레드가 있으면 Fargate 태스크가 RUNNING으로 남아 다음 스케줄이 "skipping overlapping cycle"로 빠졌다.
러너는 이제 DB 엔진 정리 + 로그 flush 뒤 os._exit로 끝난다. exit code 의미는 그대로다.
"""

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import auto_prober_runner as runner

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def argv_once(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["auto_prober_runner", "--once"])
    monkeypatch.setattr(runner, "_discover_anthropic_models", lambda: None)
    monkeypatch.setattr(runner, "_register_openai_models", lambda: None)


def test_main_returns_zero_when_the_cycle_finishes(argv_once, monkeypatch):
    monkeypatch.setattr(runner, "run_cycle", lambda: 34049)
    assert runner.main() == 0


def test_main_returns_one_when_the_cycle_raises(argv_once, monkeypatch):
    def boom():
        raise RuntimeError("1 model probes did not finish normally")

    monkeypatch.setattr(runner, "run_cycle", boom)
    assert runner.main() == 1


def test_finish_disposes_engine_flushes_logs_and_hard_exits_without_joining(monkeypatch):
    import database

    calls = []
    monkeypatch.setattr(database, "engine", type("E", (), {"dispose": lambda self: calls.append("dispose")})())
    monkeypatch.setattr(runner.logging, "shutdown", lambda: calls.append("logging.shutdown"))

    stuck = threading.Event()
    stray = threading.Thread(target=stuck.wait, args=(10,), daemon=False)  # 포기된 프로브 스레드 모사
    stray.start()
    try:
        t0 = time.perf_counter()
        runner._finish(3, _exit=lambda code: calls.append(("exit", code)))
        assert time.perf_counter() - t0 < 1.0  # 살아 있는 스레드를 기다리지 않는다
        assert stray.is_alive()
        assert calls == ["dispose", "logging.shutdown", ("exit", 3)]
    finally:
        stuck.set()
        stray.join(5)


def test_finish_exits_even_if_engine_dispose_fails(monkeypatch):
    import database

    def broken_dispose(self):
        raise RuntimeError("pool already gone")

    monkeypatch.setattr(database, "engine", type("E", (), {"dispose": broken_dispose})())
    monkeypatch.setattr(runner.logging, "shutdown", lambda: None)
    exits = []
    runner._finish(0, _exit=exits.append)
    assert exits == [0]


def test_module_entrypoint_exits_promptly_despite_a_stuck_executor_thread():
    """`python -m auto_prober_runner --once` 경로 그대로: 사이클이 끝났는데 executor 워커 하나가
    영원히 멈춰 있어도 프로세스가 곧바로 exit 0으로 끝난다(이전: interpreter 종료가 join해 무한 대기)."""
    script = textwrap.dedent("""
        import runpy, sys, threading
        from concurrent.futures import ThreadPoolExecutor
        import auto_prober, prober

        prober._discover_anthropic_models = lambda: None
        prober._register_openai_models = lambda: None
        executor = ThreadPoolExecutor(max_workers=1)

        def fake_cycle():
            executor.submit(threading.Event().wait)  # 영원히 풀리지 않는 워커
            executor.shutdown(wait=False, cancel_futures=True)
            return 34049

        auto_prober.run_cycle = fake_cycle
        sys.argv = ["auto_prober_runner", "--once"]
        runpy.run_module("auto_prober_runner", run_name="__main__")
        print("UNREACHABLE: _finish must not return")
    """)
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND, env=dict(os.environ),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "UNREACHABLE" not in proc.stdout
    assert "auto_prober_runner: run_id=34049" in proc.stderr  # 로그가 os._exit 전에 flush됐다
    assert time.perf_counter() - t0 < 30
