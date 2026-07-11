"""EventBridge Scheduler가 호출하는 패리티 런 Fargate one-shot 진입점 (v2.11.0).

ECS Task Definition CMD:
  python -m parity_runner --once
"""

from __future__ import annotations

import argparse
import logging
import sys

from database import create_tables


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Run one parity sweep and exit")
    parser.add_argument("--once", action="store_true", help="실행 1회 후 종료")
    args = parser.parse_args()
    if not args.once:
        parser.error("--once 필수")

    # parity_runs / parity_results 테이블 보장 (backend 재배포 전에 먼저 돌 수 있음)
    create_tables()

    # 모델 자동 등록 (autoprober_runner와 동일)
    try:
        from prober import _discover_anthropic_models, _register_openai_models
        _discover_anthropic_models()
        _register_openai_models()
    except Exception:
        logging.exception("Model discovery/registration failed (non-fatal)")

    try:
        from parity.runner import run_parity
        run_id = run_parity()
        logging.info("parity_runner done (run_id=%d)", run_id)
        return 0
    except Exception:
        logging.exception("parity_runner 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
