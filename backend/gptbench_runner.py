"""GPT on AWS 벤치 러너 — EventBridge Scheduler가 15분마다 호출하는 CLI (v2.18.0).

ECS Task Definition CMD:
  python -m gptbench_runner --once
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gptbench_runner")


def main() -> int:
    parser = argparse.ArgumentParser(description="GPT on AWS bench cycle (one-shot)")
    parser.add_argument("--once", action="store_true", help="run exactly one cycle and exit")
    args = parser.parse_args()

    if not args.once:
        parser.error("only --once mode is supported (scheduled one-shot task)")

    from gptbench import run_cycle

    result = run_cycle()
    logger.info("cycle result: %s", result)
    # 모든 호출이 error여도 exit 0 — row로 기록되어 대시보드에 드러남 (autoprober와 동일 정책).
    return 0


if __name__ == "__main__":
    sys.exit(main())
