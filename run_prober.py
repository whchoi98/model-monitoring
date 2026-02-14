#!/usr/bin/env python3
"""Entry point for the Bedrock model prober."""

import argparse
import logging
import sys

from src.config import load_config
from src.db import Database
from src.prober import run_loop, run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Bedrock Model Monitoring Prober")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )
    parser.add_argument(
        "--once", action="store_true", help="Run a single probe round and exit"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config(args.config)
    db = Database(config.db_path)

    logging.info(
        "Loaded config: region=%s, models=%d, interval=%ds",
        config.aws_region,
        len(config.models),
        config.probing.interval_seconds,
    )

    try:
        if args.once:
            run_once(config, db)
        else:
            run_loop(config, db)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        db.close()


if __name__ == "__main__":
    main()
