"""Claude API Features 검증 Fargate one-shot / 로컬 스모크 진입점 (v2.23.0).

ECS CMD:  python -m features_runner --once
로컬:     python -m features_runner --smoke --models sonnet-5 --surfaces cp,mantle [--features messages_basic,...]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def _csv(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run one Claude API Features verification sweep and exit")
    parser.add_argument("--once", action="store_true", help="DB에 기록하는 실행 1회")
    parser.add_argument("--smoke", action="store_true", help="DB 없이 실행 후 표 출력 (로컬 검증)")
    parser.add_argument("--surfaces", help="cp,mantle,bedrock_invoke,bedrock_converse")
    parser.add_argument("--features", help="feature id 목록(콤마)")
    parser.add_argument("--models", help="fable-5-1,fable-5,opus-5,sonnet-5")
    parser.add_argument("--json", action="store_true", help="--smoke 결과를 JSON으로 출력")
    args = parser.parse_args()
    if not (args.once or args.smoke):
        parser.error("--once 또는 --smoke 필수")

    from claude_features.runner import run_features, smoke

    if args.smoke:
        rows = smoke(_csv(args.surfaces), _csv(args.features), _csv(args.models))
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        else:
            for r in sorted(rows, key=lambda r: (r["feature"], r["surface"], r["model_key"])):
                err = (r.get("error") or "")[:110].replace("\n", " ")
                print(f"{r['feature']:28s} {r['surface']:16s} {r['model_key']:10s} {r['status']:15s} {r['verdict']:12s} "
                      f"{(r['latency_ms'] or 0):7.0f}ms  {err}")
        return 0

    from database import create_tables
    create_tables()  # feature_runs / feature_results 보장 (backend 재배포 전에 먼저 돌 수 있음)
    try:
        run_id = run_features(_csv(args.surfaces), _csv(args.features), _csv(args.models))
        logging.info("features_runner done (run_id=%d)", run_id)
        return 0
    except Exception:
        logging.exception("features_runner 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
