"""EventBridge Scheduler가 호출하는 Fargate one-shot 진입점.

ECS Task Definition CMD:
  python -m auto_prober_runner --once
"""

from __future__ import annotations

import argparse
import logging
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
        logging.exception("Anthropic model discovery failed (non-fatal)")

    try:
        run_id = run_cycle()
    except Exception:
        logging.exception("auto_prober_runner 실패")
        return 1
    logging.info("auto_prober_runner: run_id=%d 종료", run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
