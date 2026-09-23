"""EventBridge Scheduler가 호출하는 Fargate one-shot 진입점.

ECS Task Definition CMD:
  python -m auto_prober_runner --once
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from auto_prober import run_cycle
from prober import _discover_anthropic_models, _register_openai_models


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Run the auto-prober once and exit")
    parser.add_argument("--once", action="store_true", help="실행 1회 후 종료 (현재 유일한 모드)")
    args = parser.parse_args()
    if not args.once:
        parser.error("--once 필수")

    # Anthropic 직접 API 모델 자동 발견 (ANTHROPIC_API_KEY 설정 시에만 동작)
    try:
        _discover_anthropic_models()
        _register_openai_models()
    except Exception:
        logging.exception("Model discovery/registration failed (non-fatal)")

    try:
        run_id = run_cycle()
    except Exception:
        logging.exception("auto_prober_runner 실패")
        return 1
    logging.info("auto_prober_runner: run_id=%d 종료", run_id)
    return 0


def _finish(exit_code: int, _exit=os._exit) -> None:
    """사이클이 끝나면 남은 스레드를 기다리지 않고 프로세스를 끝낸다 (v2.28.2).

    sys.exit()는 인터프리터 종료 단계에서 ThreadPoolExecutor 워커 스레드를 join한다. 사이클이
    포기한(abandoned) 멈춘 프로브 스레드가 남아 있으면 Fargate 태스크가 RUNNING으로 남고, 그동안
    running 예약 때문에 다음 스케줄 태스크가 "skipping overlapping cycle"로 빠진다(2026-09-23 장애,
    30~46분). 그래서 DB 엔진 커넥션을 정리하고 로그를 flush한 뒤 os._exit로 끝낸다.
    exit code 의미는 그대로다: 0 = 사이클 완료 또는 겹침 skip, 1 = 사이클 실패.
    """
    try:
        from database import engine

        engine.dispose()
    except Exception:  # noqa: BLE001 — 종료 경로는 어떤 정리 실패에도 막히지 않는다
        logging.exception("auto_prober_runner: engine dispose failed (ignored)")
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    _exit(exit_code)


if __name__ == "__main__":
    _finish(main())
