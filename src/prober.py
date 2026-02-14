from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from src.config import AppConfig
from src.db import Database, ProbeResult

logger = logging.getLogger(__name__)


def probe_model(
    client,
    model_id: str,
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> ProbeResult:
    """Send a single probe to a Bedrock model and return the result."""
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        start = time.monotonic()
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        wall_clock_ms = (time.monotonic() - start) * 1000

        usage = response.get("usage", {})
        metrics = response.get("metrics", {})

        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        total_tokens = input_tokens + output_tokens
        server_latency_ms = metrics.get("latencyMs")

        logger.info(
            "OK  %-25s  wall=%7.0fms  server=%7s ms  in=%4d  out=%4d",
            model_name,
            wall_clock_ms,
            f"{server_latency_ms:.0f}" if server_latency_ms else "N/A",
            input_tokens,
            output_tokens,
        )

        return ProbeResult(
            model_id=model_id,
            model_name=model_name,
            timestamp=timestamp,
            prompt=prompt,
            status="success",
            wall_clock_ms=wall_clock_ms,
            server_latency_ms=server_latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    except ClientError as exc:
        wall_clock_ms = (time.monotonic() - start) * 1000
        error_code = exc.response["Error"]["Code"]
        error_msg = exc.response["Error"]["Message"]
        logger.warning("ERR %-25s  %s: %s", model_name, error_code, error_msg)

        return ProbeResult(
            model_id=model_id,
            model_name=model_name,
            timestamp=timestamp,
            prompt=prompt,
            status="error",
            wall_clock_ms=wall_clock_ms,
            error_message=f"{error_code}: {error_msg}",
        )

    except Exception as exc:
        wall_clock_ms = (time.monotonic() - start) * 1000
        logger.warning("ERR %-25s  %s", model_name, exc)

        return ProbeResult(
            model_id=model_id,
            model_name=model_name,
            timestamp=timestamp,
            prompt=prompt,
            status="error",
            wall_clock_ms=wall_clock_ms,
            error_message=str(exc),
        )


def run_once(config: AppConfig, db: Database) -> list[ProbeResult]:
    """Run a single round of probes against all configured models."""
    client = boto3.client("bedrock-runtime", region_name=config.aws_region)
    results: list[ProbeResult] = []

    prompt = random.choice(config.probing.prompts)
    logger.info("--- Probe round start  prompt=%r ---", prompt[:60])

    for model in config.models:
        result = probe_model(
            client=client,
            model_id=model.id,
            model_name=model.name,
            prompt=prompt,
            max_tokens=config.probing.max_tokens,
            temperature=config.probing.temperature,
        )
        db.insert_result(result)
        results.append(result)

    logger.info("--- Probe round complete (%d models) ---", len(results))
    return results


def run_loop(config: AppConfig, db: Database) -> None:
    """Run probes in an infinite loop at the configured interval."""
    interval = config.probing.interval_seconds
    logger.info("Starting probe loop (interval=%ds)", interval)

    while True:
        try:
            run_once(config, db)
        except Exception:
            logger.exception("Unexpected error during probe round")

        logger.info("Sleeping %ds until next round...", interval)
        time.sleep(interval)
