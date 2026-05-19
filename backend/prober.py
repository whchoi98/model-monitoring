"""Core streaming probe logic.

Calls Bedrock converse_stream for each model, collects latency metrics,
streams SSE events back to the client, and persists results to the DB.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Generator

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from models import ProbeResult, ProbeRun

logger = logging.getLogger(__name__)

# 모니터링 대상 - Global profile (Seoul 호출) + US profile (us-east-1 호출, Claude Platform on AWS).
AVAILABLE_MODELS: dict[str, str] = {
    # Global cross-region inference profile (ap-northeast-2)
    "global.anthropic.claude-opus-4-7": "Claude Opus 4.7 (Global)",
    "global.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (Global)",
    "global.anthropic.claude-sonnet-4-6": "Claude Sonnet 4.6 (Global)",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5 (Global)",
    "global.amazon.nova-2-lite-v1:0": "Nova 2.0 Lite (Global)",
    # US cross-region inference profile (us-east-1) - Claude Platform on AWS
    # Anthropic 3P 모델
    "us.anthropic.claude-opus-4-7": "Claude Opus 4.7 (US)",
    "us.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (US)",
    "us.anthropic.claude-sonnet-4-6": "Claude Sonnet 4.6 (US)",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5 (US)",
    # Amazon 1P (Nova) 모델 - Claude Platform on AWS 채널의 1P 옵션.
    # Nova Premier는 provider에 의해 Legacy로 마킹되어 접근 불가 - 제외.
    "us.amazon.nova-2-lite-v1:0": "Nova 2.0 Lite (US, 1P)",
}

# 모델 prefix별 boto3 client 리전 - cross-region inference profile은 각 home region에서 호출해야 함.
_REGION_MAP: dict[str, str] = {
    "global": "ap-northeast-2",
    "us": "us-east-1",
}

_client_cache: dict[str, object] = {}


# Reasoning model은 inferenceConfig.temperature를 거부 - 패턴 기반 식별.
_REASONING_MODEL_PATTERNS = ("opus-4-7",)


def _is_reasoning_model(model_id: str) -> bool:
    """temperature 파라미터를 거부하는 reasoning model 여부."""
    return any(p in model_id for p in _REASONING_MODEL_PATTERNS)


def _get_region_for_model(model_id: str) -> str:
    """Derive the AWS region from a model ID prefix."""
    prefix = model_id.split(".")[0]
    return _REGION_MAP.get(prefix, "us-east-1")


def _get_bedrock_client(region_name: str = "us-east-1"):
    """Return a cached boto3 bedrock-runtime client for the given region."""
    if region_name not in _client_cache:
        _client_cache[region_name] = boto3.client("bedrock-runtime", region_name=region_name)
    return _client_cache[region_name]


def _probe_single_model(
    client,
    model_id: str,
    model_name: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    iteration: int,
    event_queue: Queue,
    run_id: int,
    db: Session,
) -> None:
    """Execute a single converse_stream call and push SSE events to the queue."""
    start_time = time.monotonic()
    first_token_time: float | None = None
    collected_text: list[str] = []
    input_tokens = 0
    output_tokens = 0
    server_latency_ms: float | None = None

    try:
        # Claude Opus 4.7 등 reasoning model은 temperature 파라미터를 거부한다.
        # 모델 ID 기반으로 inferenceConfig 동적 구성.
        inference_config: dict = {"maxTokens": max_tokens}
        if not _is_reasoning_model(model_id):
            inference_config["temperature"] = temperature

        response = client.converse_stream(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig=inference_config,
        )

        stream = response["stream"]
        for event in stream:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                text = delta.get("text", "")
                if text:
                    now = time.monotonic()
                    if first_token_time is None:
                        first_token_time = now
                        ttft_ms = (first_token_time - start_time) * 1000.0
                        event_queue.put(
                            _sse("ttft", {
                                "model_id": model_id,
                                "model_name": model_name,
                                "iteration": iteration,
                                "ttft_ms": round(ttft_ms, 2),
                            })
                        )
                    collected_text.append(text)
                    event_queue.put(
                        _sse("token", {
                            "model_id": model_id,
                            "model_name": model_name,
                            "iteration": iteration,
                            "token": text,
                        })
                    )

            elif "metadata" in event:
                metadata = event["metadata"]
                usage = metadata.get("usage", {})
                metrics = metadata.get("metrics", {})
                input_tokens = usage.get("inputTokens", 0)
                output_tokens = usage.get("outputTokens", 0)
                server_latency_ms = metrics.get("latencyMs")

        end_time = time.monotonic()
        total_latency_ms = (end_time - start_time) * 1000.0

        # Calculate TPS
        tps: float | None = None
        if first_token_time is not None and end_time > first_token_time and output_tokens > 0:
            generation_seconds = end_time - first_token_time
            if generation_seconds > 0:
                tps = output_tokens / generation_seconds

        ttft_ms_final: float | None = None
        if first_token_time is not None:
            ttft_ms_final = (first_token_time - start_time) * 1000.0

        output_text = "".join(collected_text)

        # Build result dict
        result_data = {
            "run_id": run_id,
            "model_id": model_id,
            "model_name": model_name,
            "prompt": prompt,
            "status": "success",
            "ttft_ms": round(ttft_ms_final, 2) if ttft_ms_final is not None else None,
            "total_latency_ms": round(total_latency_ms, 2),
            "server_latency_ms": round(server_latency_ms, 2) if server_latency_ms is not None else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tps": round(tps, 2) if tps is not None else None,
            "output_text": output_text,
            "error_message": None,
            "iteration": iteration,
        }

        # Persist to DB
        db_result = ProbeResult(
            run_id=run_id,
            model_id=model_id,
            model_name=model_name,
            timestamp=datetime.now(timezone.utc),
            prompt=prompt,
            status="success",
            ttft_ms=result_data["ttft_ms"],
            total_latency_ms=result_data["total_latency_ms"],
            server_latency_ms=result_data["server_latency_ms"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tps=result_data["tps"],
            output_text=output_text,
            error_message=None,
            iteration=iteration,
        )
        db.add(db_result)
        db.commit()
        db.refresh(db_result)

        result_data["id"] = db_result.id
        result_data["timestamp"] = db_result.timestamp.isoformat()

        event_queue.put(_sse("result", result_data))

    except ClientError as exc:
        end_time = time.monotonic()
        total_latency_ms = (end_time - start_time) * 1000.0
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        error_msg = exc.response.get("Error", {}).get("Message", str(exc))
        full_error = f"{error_code}: {error_msg}"

        logger.warning("Probe error for %s (iter %d): %s", model_id, iteration, full_error)

        # Persist error to DB
        db_result = ProbeResult(
            run_id=run_id,
            model_id=model_id,
            model_name=model_name,
            timestamp=datetime.now(timezone.utc),
            prompt=prompt,
            status="error",
            ttft_ms=None,
            total_latency_ms=round(total_latency_ms, 2),
            server_latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            tps=None,
            output_text=None,
            error_message=full_error,
            iteration=iteration,
        )
        db.add(db_result)
        db.commit()
        db.refresh(db_result)

        event_queue.put(
            _sse("error", {
                "model_id": model_id,
                "model_name": model_name,
                "iteration": iteration,
                "error": full_error,
                "total_latency_ms": round(total_latency_ms, 2),
            })
        )

    except Exception as exc:
        end_time = time.monotonic()
        total_latency_ms = (end_time - start_time) * 1000.0
        full_error = f"Unexpected: {str(exc)}"

        logger.exception("Unexpected probe error for %s (iter %d)", model_id, iteration)

        db_result = ProbeResult(
            run_id=run_id,
            model_id=model_id,
            model_name=model_name,
            timestamp=datetime.now(timezone.utc),
            prompt=prompt,
            status="error",
            ttft_ms=None,
            total_latency_ms=round(total_latency_ms, 2),
            server_latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            tps=None,
            output_text=None,
            error_message=full_error,
            iteration=iteration,
        )
        db.add(db_result)
        db.commit()
        db.refresh(db_result)

        event_queue.put(
            _sse("error", {
                "model_id": model_id,
                "model_name": model_name,
                "iteration": iteration,
                "error": full_error,
                "total_latency_ms": round(total_latency_ms, 2),
            })
        )


def _sse(event_type: str, data: dict) -> str:
    """Format a single SSE message string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def stream_probe_events(
    model_ids: list[str],
    prompt: str,
    temperature: float,
    max_tokens: int,
    concurrency: int,
    repeat_count: int,
    db: Session,
    run_id: int,
) -> Generator[str, None, None]:
    """Generator that yields SSE-formatted strings as probes execute.

    Each model x repeat_count combination is submitted to a ThreadPoolExecutor.
    Events are pulled from a shared queue and yielded to the caller.
    """
    event_queue: Queue[str | None] = Queue()

    # Total number of individual probe tasks
    total_tasks = len(model_ids) * repeat_count

    # Yield an initial event with run metadata
    yield _sse("start", {
        "run_id": run_id,
        "total_tasks": total_tasks,
        "model_ids": model_ids,
        "repeat_count": repeat_count,
    })

    def _run_all():
        """Submit all probe tasks and signal completion via a sentinel."""
        # Each thread needs its own DB session for thread safety
        from database import SessionLocal

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for model_id in model_ids:
                model_name = AVAILABLE_MODELS.get(model_id, model_id)
                client = _get_bedrock_client(_get_region_for_model(model_id))
                for iteration in range(1, repeat_count + 1):
                    thread_db = SessionLocal()
                    future = executor.submit(
                        _probe_single_model,
                        client,
                        model_id,
                        model_name,
                        prompt,
                        temperature,
                        max_tokens,
                        iteration,
                        event_queue,
                        run_id,
                        thread_db,
                    )
                    futures.append((future, thread_db))

            # Wait for all futures to complete
            for future, thread_db in futures:
                try:
                    future.result()
                except Exception:
                    logger.exception("Unexpected error in probe future")
                finally:
                    thread_db.close()

        # Signal that all tasks are done
        event_queue.put(None)

    # Run all probes in a background thread so we can yield events as they arrive
    import threading

    worker_thread = threading.Thread(target=_run_all, daemon=True)
    worker_thread.start()

    completed = 0
    while True:
        try:
            event = event_queue.get(timeout=300)  # 5-minute timeout
        except Empty:
            yield _sse("error", {"error": "Probe timed out after 5 minutes"})
            break

        if event is None:
            # All tasks done
            break

        yield event

        # Count completed results and errors
        if "event: result\n" in event or "event: error\n" in event:
            completed += 1

    # Mark run as completed
    try:
        run = db.query(ProbeRun).filter(ProbeRun.id == run_id).first()
        if run:
            run.status = "completed"
            db.commit()
    except Exception:
        logger.exception("Failed to update run status")

    yield _sse("complete", {"run_id": run_id, "total": completed})

    worker_thread.join(timeout=5)
