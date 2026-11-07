"""Model Explorer verification Fargate one-shot / local smoke entry point (v2.40.0, ADR-035).

ECS CMD:  python -m explorer_runner --once            (ExplorerVerify, daily cron(0 18 * * ? *) UTC = 03:00 KST)
Local:    python -m explorer_runner --smoke [--models id,id] [--json]

Both modes register the runtime channels first (Claude Platform on AWS /v1/models, OpenAI env), like
pricing_sync_runner, so the run covers what the dashboard monitors. --once ends with os._exit like
auto_prober_runner: a stray thread must not keep the task RUNNING.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def _csv(value: str | None) -> list[str] | None:
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


def _register_models() -> None:
    from prober import _discover_anthropic_models, _register_openai_models

    for register in (_discover_anthropic_models, _register_openai_models):
        try:
            register()
        except Exception:  # noqa: BLE001 — a failed registration only leaves those channels out of the run
            logging.exception("explorer_runner: model registration failed (non-fatal)")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run every Model Explorer code example once and exit")
    parser.add_argument("--once", action="store_true", help="DB에 기록하는 실행 1회")
    parser.add_argument("--smoke", action="store_true", help="DB 없이 실행 후 표 출력 (배포 전 로컬 확인)")
    parser.add_argument("--models", help="model id 목록(콤마)")
    parser.add_argument("--json", action="store_true", help="--smoke 결과를 JSON으로 출력")
    args = parser.parse_args(argv)
    if not (args.once or args.smoke):
        parser.error("--once 또는 --smoke 필수")

    _register_models()
    from model_explorer.runner import run_explorer, smoke

    if args.smoke:
        rows = smoke(_csv(args.models))
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                head = (r["error_message"] or r["output_excerpt"] or "").split("\n")[0][:100]
                print(f"{r['status']:8s} {r['attempts']} {(r['latency_ms'] or 0):8.0f}ms  "
                      f"{r['model_id']:52s} {r['api_id']:13s} {head}")
        return 0 if all(r["status"] != "failed" for r in rows) else 1

    from database import create_tables

    create_tables()  # explorer_runs / explorer_results — the task can run before the backend is redeployed
    try:
        run_id = run_explorer(_csv(args.models))
    except Exception:
        logging.exception("explorer_runner 실패")
        return 1
    logging.info("explorer_runner done (run_id=%d)", run_id)
    return 0


def _finish(exit_code: int, _exit=os._exit) -> None:
    """Dispose the DB engine, flush the logs and end with os._exit (auto_prober_runner._finish, v2.28.2)."""
    try:
        from database import engine

        engine.dispose()
    except Exception:  # noqa: BLE001
        logging.exception("explorer_runner: engine dispose failed (ignored)")
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    _exit(exit_code)


if __name__ == "__main__":
    _finish(main())
