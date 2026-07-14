"""Core streaming probe logic.

Calls Bedrock converse_stream for each model, collects latency metrics,
streams SSE events back to the client, and persists results to the DB.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Generator, Optional

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from models import ProbeResult, ProbeRun

logger = logging.getLogger(__name__)

# 모니터링 대상 - Global profile (Seoul 호출) + US profile (us-east-1 호출, Claude Platform on AWS).
AVAILABLE_MODELS: dict[str, str] = {
    # Bedrock - Global cross-region inference profile (ap-northeast-2)
    "global.anthropic.claude-fable-5": "Bedrock Claude Fable 5 (Global)",
    "global.anthropic.claude-opus-4-8": "Bedrock Claude Opus 4.8 (Global)",
    "global.anthropic.claude-opus-4-7": "Bedrock Claude Opus 4.7 (Global)",
    "global.anthropic.claude-opus-4-6-v1": "Bedrock Claude Opus 4.6 (Global)",
    "global.anthropic.claude-sonnet-5": "Bedrock Claude Sonnet 5 (Global)",
    "global.anthropic.claude-sonnet-4-6": "Bedrock Claude Sonnet 4.6 (Global)",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": "Bedrock Claude Haiku 4.5 (Global)",
    # Bedrock - US cross-region inference profile (us-east-1)
    # Fable 5 (Covered Model): provider_data_share data-retention 필요 — us. 는 us-east-1, global. 는 ap-northeast-2 리전 opt-in (2026-06-10). plain anthropic.* FM ID는 on-demand 미지원이라 inference profile(us./global.) 사용.
    "us.anthropic.claude-fable-5": "Bedrock Claude Fable 5 (US)",
    "us.anthropic.claude-opus-4-8": "Bedrock Claude Opus 4.8 (US)",
    "us.anthropic.claude-opus-4-7": "Bedrock Claude Opus 4.7 (US)",
    "us.anthropic.claude-opus-4-6-v1": "Bedrock Claude Opus 4.6 (US)",
    "us.anthropic.claude-sonnet-5": "Bedrock Claude Sonnet 5 (US)",
    "us.anthropic.claude-sonnet-4-6": "Bedrock Claude Sonnet 4.6 (US)",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Bedrock Claude Haiku 4.5 (US)",
    # Opus 4.5, Sonnet 4.5는 사용자 요청으로 모니터링 대상에서 제외 (2026-05-20).
    # Bedrock - Amazon Nova (1P). 사용자 요청으로 Nova 2.0 Lite (US)만 유지.
    "us.amazon.nova-2-lite-v1:0": "Bedrock Nova 2.0 Lite (US)",
}

# Claude Platform on AWS (CP on AWS) - Path 3 External 채널.
# vendor-hosted endpoint: aws-external-anthropic.<region>.api.aws
# Key prefix "anthropic:<actual-anthropic-model-id>" 형태로 저장.
# 시작 시 _discover_anthropic_models()가 /v1/models 응답에서 substring 매칭해 자동 등록.
_ANTHROPIC_TARGETS: list[tuple[str, str]] = [
    ("fable-5", "Anthropic Claude Fable 5 (US)"),
    ("opus-4-8", "Anthropic Claude Opus 4.8 (US)"),
    ("opus-4-7", "Anthropic Claude Opus 4.7 (US)"),
    ("sonnet-5", "Anthropic Claude Sonnet 5 (US)"),
    ("sonnet-4-6", "Anthropic Claude Sonnet 4.6 (US)"),
    ("haiku-4-5", "Anthropic Claude Haiku 4.5 (US)"),
]

# Claude Platform on AWS Path 3 External endpoint - vendor-hosted AWS API.
# region은 ANTHROPIC_AWS_REGION 환경변수로 오버라이드 가능 (기본 us-east-2).
_ANTHROPIC_AWS_BASE_URL_TEMPLATE = "https://aws-external-anthropic.{region}.api.aws"


def _anthropic_base_url() -> str:
    region = os.environ.get("ANTHROPIC_AWS_REGION", "us-east-2")
    return _ANTHROPIC_AWS_BASE_URL_TEMPLATE.format(region=region)


def _anthropic_default_headers() -> dict[str, str]:
    """CP on AWS 필수 헤더 - workspace-id."""
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    return {"anthropic-workspace-id": ws} if ws else {}


def _discover_anthropic_models() -> None:
    """Claude Platform on AWS의 /v1/models를 호출해 모델 ID 자동 발견 후 AVAILABLE_MODELS에 등록.

    호출 실패 / 키 또는 workspace-id 미설정 시 조용히 skip - Bedrock 12개는 정상 동작.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if not api_key or not workspace_id:
        logger.info(
            "ANTHROPIC_API_KEY or ANTHROPIC_WORKSPACE_ID not set - skipping CP on AWS models",
        )
        return
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=api_key,
            base_url=_anthropic_base_url(),
            default_headers=_anthropic_default_headers(),
        )
        models_page = client.models.list(limit=100)
        all_ids = [m.id for m in models_page.data]
        for substring, display_label in _ANTHROPIC_TARGETS:
            matched = next((mid for mid in all_ids if substring in mid), None)
            if matched:
                key = f"anthropic:{matched}"
                AVAILABLE_MODELS[key] = display_label
                logger.info("Registered CP on AWS model: %s -> %s", key, display_label)
            else:
                logger.warning("CP on AWS model substring '%s' not found in /v1/models", substring)
    except Exception:
        logger.exception("Failed to discover CP on AWS models")


# 모델 prefix별 boto3 client 리전 - cross-region inference profile은 각 home region에서 호출해야 함.
_REGION_MAP: dict[str, str] = {
    "global": "ap-northeast-2",
    "us": "us-east-1",
}

_client_cache: dict[str, object] = {}
_anthropic_client_cache: object | None = None


def _get_anthropic_client():
    """Lazy-init Anthropic SDK client (singleton). CP on AWS base_url + workspace 헤더."""
    global _anthropic_client_cache
    if _anthropic_client_cache is None:
        from anthropic import Anthropic
        _anthropic_client_cache = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=_anthropic_base_url(),
            default_headers=_anthropic_default_headers(),
        )
    return _anthropic_client_cache


def _is_anthropic_direct(model_id: str) -> bool:
    return model_id.startswith("anthropic:")


def _anthropic_actual_id(model_id: str) -> str:
    """anthropic:<id> → <id>."""
    return model_id.split(":", 1)[1]


# Reasoning model은 inferenceConfig.temperature를 거부 - 패턴 기반 식별.
_REASONING_MODEL_PATTERNS = ("opus-4-7", "opus-4-8", "fable-5", "sonnet-5")


def _is_reasoning_model(model_id: str) -> bool:
    """temperature 파라미터를 거부하는 reasoning model 여부."""
    return any(p in model_id for p in _REASONING_MODEL_PATTERNS)


# =====================================================================
# OpenAI GPT via Bedrock Mantle (OpenAI-compatible /openai/v1) — Path 4.
# model_id 키 스킴: "openai:<region>:<actual_model_id>" (예: openai:us-east-1:openai.gpt-5.4).
# region이 채널 식별자 (같은 model_id를 두 리전에 호출). bearer 토큰 인증.
# =====================================================================
_OPENAI_REGION_ENV: dict[str, str] = {
    "us-east-1": "OPENAI_US_EAST_1_BASE_URL",
    "us-east-2": "OPENAI_US_EAST_2_BASE_URL",
    "us-west-2": "OPENAI_US_WEST_2_BASE_URL",
}

# 모델별 가용 리전 — 모델이 모든 리전에 있는 건 아님(예: gpt-5.5/5.6-sol은 us-west-2 미제공 → 404).
# (model-id env var, display family, 제공 리전 튜플)
_OPENAI_MODEL_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID", "GPT 5.6 Sol", ("us-east-1", "us-east-2")),
    ("BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", "GPT 5.6 Terra", ("us-east-1", "us-east-2", "us-west-2")),
    ("BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID", "GPT 5.6 Luna", ("us-east-1", "us-east-2", "us-west-2")),
    ("BEDROCK_OPENAI_GPT_54_MODEL_ID", "GPT 5.4", ("us-east-1", "us-east-2", "us-west-2")),
    ("BEDROCK_OPENAI_GPT_55_MODEL_ID", "GPT 5.5", ("us-east-1", "us-east-2")),
]

# =====================================================================
# OpenAI GPT 1P direct (api.openai.com) — Path 5.
# Mantle와 별개 자격증명(OpenAI *platform* 키 sk-proj-…, OPENAI_1P_API_KEY)·리전 개념 없음.
# key 스킴: "openai:1p:<native_id>" (예: openai:1p:gpt-5.4). native id는 접두사 없음(gpt-5.4).
# base_url은 항상 api.openai.com (OPENAI_1P_BASE_URL로 override 가능).
# =====================================================================
_OPENAI_1P_DEFAULT_BASE_URL = "https://api.openai.com/v1"

# (model-id env var, display family) — 리전 없음 (글로벌 라우팅).
_OPENAI_1P_MODEL_SPECS: list[tuple[str, str]] = [
    ("OPENAI_1P_GPT_56_SOL_MODEL_ID", "GPT 5.6 Sol"),
    ("OPENAI_1P_GPT_56_TERRA_MODEL_ID", "GPT 5.6 Terra"),
    ("OPENAI_1P_GPT_56_LUNA_MODEL_ID", "GPT 5.6 Luna"),
    ("OPENAI_1P_GPT_54_MODEL_ID", "GPT 5.4"),
    ("OPENAI_1P_GPT_55_MODEL_ID", "GPT 5.5"),
]

# OpenAI Responses API의 incomplete reason → 기존 stop_reason enum(anthropic/bedrock와 정렬).
# gpt-5.x는 /chat/completions 미지원 → /responses 사용. finish_reason 대신 status/incomplete_details.
_OPENAI_INCOMPLETE_MAP: dict[str, str] = {
    "max_output_tokens": "max_tokens",
    "content_filter": "content_filtered",
}

_openai_client_cache: dict[str, object] = {}


def _is_openai_direct(model_id: str) -> bool:
    return model_id.startswith("openai:")


def _openai_parts(model_id: str) -> tuple[str, str]:
    """openai:<region>:<actual_id> → (region, actual_id)."""
    _, region, actual_id = model_id.split(":", 2)
    return region, actual_id


def _openai_1p_base_url() -> str:
    """1P direct 엔드포인트. OPENAI_1P_BASE_URL로 override 가능(기본 api.openai.com)."""
    return os.environ.get("OPENAI_1P_BASE_URL") or _OPENAI_1P_DEFAULT_BASE_URL


def _openai_base_url(region: str) -> str:
    if region == "1p":
        return _openai_1p_base_url()
    env_name = _OPENAI_REGION_ENV.get(region)
    if not env_name:
        raise ValueError(f"Unknown OpenAI region: {region}")
    url = os.environ.get(env_name)
    if not url:
        raise RuntimeError(f"{env_name} not set")
    return url


def _get_openai_client(base_url: str):
    """Lazy-init OpenAI SDK client per base_url.

    base_url이 1P(api.openai.com)면 OpenAI platform 키(OPENAI_1P_API_KEY)를,
    아니면 Bedrock Mantle bearer 키(OPENAI_API_KEY)를 사용한다. 두 자격증명은 호환되지 않음.
    """
    if base_url not in _openai_client_cache:
        from openai import OpenAI
        api_key = (
            os.environ["OPENAI_1P_API_KEY"]
            if base_url == _openai_1p_base_url()
            else os.environ["OPENAI_API_KEY"]
        )
        _openai_client_cache[base_url] = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    return _openai_client_cache[base_url]


def _openai_stop_reason(status: str | None, incomplete_reason: str | None) -> str | None:
    """Responses API: status 'completed' → end_turn; 'incomplete' → mapped incomplete reason."""
    if status == "completed":
        return "end_turn"
    if status == "incomplete":
        return _OPENAI_INCOMPLETE_MAP.get(incomplete_reason, incomplete_reason or "incomplete")
    return incomplete_reason


def _register_openai_models() -> None:
    """OpenAI 채널 등록 — Bedrock Mantle(Path 4) + 1P direct(Path 5)를 독립적으로 gate.

    Mantle: OPENAI_API_KEY(bearer) + _OPENAI_MODEL_SPECS(모델별 가용 리전, gpt-5.5는 us-west-2 미제공).
    1P: OPENAI_1P_API_KEY(platform 키) + _OPENAI_1P_MODEL_SPECS(리전 없음, key "openai:1p:<native_id>").
    한쪽 키만 있어도 그쪽만 등록. 누락 시 조용히 skip (해당 채널만 미등록 — 나머지 정상).
    """
    # --- Bedrock Mantle (Path 4) ---
    mantle_key = os.environ.get("OPENAI_API_KEY")
    if mantle_key:
        for env_var, family, regions in _OPENAI_MODEL_SPECS:
            actual_id = os.environ.get(env_var)
            if not actual_id:
                continue
            for region in regions:
                env_name = _OPENAI_REGION_ENV.get(region)
                if not env_name or not os.environ.get(env_name):
                    continue
                key = f"openai:{region}:{actual_id}"
                label = f"OpenAI {family} ({region})"
                AVAILABLE_MODELS[key] = label
                logger.info("Registered OpenAI model: %s -> %s", key, label)
    else:
        logger.info("OPENAI_API_KEY not set - skipping OpenAI (Bedrock Mantle) models")

    # --- 1P direct / api.openai.com (Path 5) ---
    oa_1p_key = os.environ.get("OPENAI_1P_API_KEY")
    if oa_1p_key:
        for env_var, family in _OPENAI_1P_MODEL_SPECS:
            actual_id = os.environ.get(env_var)
            if not actual_id:
                continue
            key = f"openai:1p:{actual_id}"
            label = f"OpenAI {family} (1P)"
            AVAILABLE_MODELS[key] = label
            logger.info("Registered OpenAI 1P model: %s -> %s", key, label)
    else:
        logger.info("OPENAI_1P_API_KEY not set - skipping OpenAI 1P (direct) models")


def _openai_stream_events(client, actual_id: str, prompt: str, max_tokens: int):
    """Stream the OpenAI **Responses API** (gpt-5.x require /responses, NOT /chat/completions).

    Normalized tuples를 yield:
      ("delta", text)                                       - 출력 텍스트 조각
      ("final", input_tokens, output_tokens, stop_reason)   - 완료/미완료 시 usage + stop
    temperature는 보내지 않음 (reasoning model). 토큰 한도는 max_output_tokens.
    """
    stream = client.responses.create(
        model=actual_id,
        input=prompt,
        max_output_tokens=max_tokens,
        stream=True,
    )
    for ev in stream:
        etype = getattr(ev, "type", "")
        if etype == "response.output_text.delta":
            text = getattr(ev, "delta", "") or ""
            if text:
                yield ("delta", text)
        elif etype in ("response.completed", "response.incomplete", "response.failed"):
            resp = getattr(ev, "response", None)
            in_tok = out_tok = 0
            stop = None
            if resp is not None:
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    in_tok = getattr(usage, "input_tokens", 0) or 0
                    out_tok = getattr(usage, "output_tokens", 0) or 0
                idet = getattr(resp, "incomplete_details", None)
                reason = getattr(idet, "reason", None) if idet is not None else None
                stop = _openai_stop_reason(getattr(resp, "status", None), reason)
            yield ("final", in_tok, out_tok, stop)


def _get_region_for_model(model_id: str) -> str:
    """Derive the AWS region from a model ID prefix."""
    prefix = model_id.split(".")[0]
    return _REGION_MAP.get(prefix, "us-east-1")


def _get_bedrock_client(region_name: str = "us-east-1"):
    """Return a cached boto3 bedrock-runtime client for the given region."""
    if region_name not in _client_cache:
        _client_cache[region_name] = boto3.client("bedrock-runtime", region_name=region_name)
    return _client_cache[region_name]


# Retry — Anthropic 529 overloaded_error / Bedrock ThrottlingException 등 vendor 일시 부하.
# 2s, 4s, 8s exponential backoff. 최대 2회 재시도 (총 3 attempts).
_RETRYABLE_PATTERNS: tuple[str, ...] = (
    "Overloaded",
    "overloaded_error",
    "ThrottlingException",
    "Throttling",
    "ServiceUnavailableException",
    "TooManyRequestsException",
    "ModelStreamErrorException",
    # OpenAI (Bedrock Mantle) rate-limit / overload markers.
    "RateLimitError",
    "rate_limit",
    "ServiceUnavailable",
    "overloaded",
)
_RETRY_BACKOFFS: tuple[int, ...] = (2, 4, 8)


def _is_retryable_error(err_msg: str) -> bool:
    return any(p in err_msg for p in _RETRYABLE_PATTERNS)


def _is_overload_error(err_msg: str) -> bool:
    """overloaded는 별도 status로 표시해 운영자에게 'vendor 일시 부하' 신호."""
    return "Overloaded" in err_msg or "overloaded_error" in err_msg


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
    category: Optional[str] = None,
) -> None:
    """Execute a single streaming probe call and push SSE events to the queue.

    Bedrock 경로(`us.*`, `global.*`)는 boto3 converse_stream.
    Anthropic 직접 API 경로(`anthropic:*`)는 anthropic SDK messages.stream.
    """
    start_time = time.monotonic()
    first_token_time: float | None = None
    collected_text: list[str] = []
    input_tokens = 0
    output_tokens = 0
    server_latency_ms: float | None = None
    stop_reason: str | None = None

    # Retry loop - vendor 일시 부하(529 overloaded / Throttle) 시 2/4/8s backoff 최대 2회.
    # Streaming setup 실패만 retry — 중간 token 수신 도중 실패는 retry하지 않음(이미 partial yield).
    last_exception: Exception | None = None
    for attempt in range(len(_RETRY_BACKOFFS) + 1):  # 3 attempts: 0, 1, 2
        # 재시도 시 state 리셋 (partial token이 client에 이미 도착했다면 자연스러운 reset로 인식).
        if attempt > 0:
            start_time = time.monotonic()
            first_token_time = None
            collected_text = []
            input_tokens = 0
            output_tokens = 0
            server_latency_ms = None
            stop_reason = None
        try:
            if _is_anthropic_direct(model_id):
                actual_id = _anthropic_actual_id(model_id)
                anthropic_client = _get_anthropic_client()
                with anthropic_client.messages.stream(
                    model=actual_id,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        if text:
                            now = time.monotonic()
                            if first_token_time is None:
                                first_token_time = now
                                ttft_ms = (first_token_time - start_time) * 1000.0
                                event_queue.put(_sse("ttft", {
                                    "model_id": model_id,
                                    "model_name": model_name,
                                    "iteration": iteration,
                                    "ttft_ms": round(ttft_ms, 2),
                                }))
                            collected_text.append(text)
                            event_queue.put(_sse("token", {
                                "model_id": model_id,
                                "model_name": model_name,
                                "iteration": iteration,
                                "token": text,
                            }))
                    final_message = stream.get_final_message()
                    input_tokens = final_message.usage.input_tokens
                    output_tokens = final_message.usage.output_tokens
                    # stop_reason: end_turn | max_tokens | stop_sequence | tool_use
                    stop_reason = getattr(final_message, "stop_reason", None)
                    # Anthropic API는 server-side latency를 제공하지 않음 - None 유지.
            elif _is_openai_direct(model_id):
                region, actual_id = _openai_parts(model_id)
                oa_client = _get_openai_client(_openai_base_url(region))
                for kind, *rest in _openai_stream_events(oa_client, actual_id, prompt, max_tokens):
                    if kind == "delta":
                        text = rest[0]
                        now = time.monotonic()
                        if first_token_time is None:
                            first_token_time = now
                            ttft_ms = (first_token_time - start_time) * 1000.0
                            event_queue.put(_sse("ttft", {
                                "model_id": model_id,
                                "model_name": model_name,
                                "iteration": iteration,
                                "ttft_ms": round(ttft_ms, 2),
                            }))
                        collected_text.append(text)
                        event_queue.put(_sse("token", {
                            "model_id": model_id,
                            "model_name": model_name,
                            "iteration": iteration,
                            "token": text,
                        }))
                    else:  # ("final", input_tokens, output_tokens, stop_reason)
                        input_tokens, output_tokens, stop_reason = rest
                # OpenAI Responses 엔드포인트는 server-side latency 미제공 - None 유지.
            else:
                # Bedrock 경로 - 기존 동작.
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

                    elif "messageStop" in event:
                        # Bedrock converse_stream: stopReason in messageStop event.
                        # 값: end_turn | tool_use | max_tokens | stop_sequence | guardrail_intervened | content_filtered
                        stop_reason = event["messageStop"].get("stopReason")
            # 성공 — retry loop 탈출
            last_exception = None
            break
        except Exception as exc:
            last_exception = exc
            msg = str(exc)
            if attempt < len(_RETRY_BACKOFFS) and _is_retryable_error(msg):
                backoff = _RETRY_BACKOFFS[attempt]
                logger.warning(
                    "Retryable error for %s (attempt %d/%d, backoff %ds): %s",
                    model_id, attempt + 1, len(_RETRY_BACKOFFS) + 1, backoff, msg[:120],
                )
                time.sleep(backoff)
                continue
            # 비-retryable 또는 최종 시도 실패 — outer try 안에서 처리되도록 break.
            # raise하면 for 루프 밖으로 propagate되어 outer try-except 미도달 → DB row 미저장 버그.
            break

    try:
        # retry 다 소진했거나 non-retryable로 빠진 경우 outer except가 DB에 error row 저장.
        if last_exception is not None:
            raise last_exception

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
            "stop_reason": stop_reason,
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
            category=category,
            stop_reason=stop_reason,
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
        status_value = "overloaded" if _is_overload_error(full_error) else "error"

        logger.warning("Probe %s for %s (iter %d): %s", status_value, model_id, iteration, full_error)

        # Persist error to DB
        db_result = ProbeResult(
            run_id=run_id,
            model_id=model_id,
            model_name=model_name,
            timestamp=datetime.now(timezone.utc),
            prompt=prompt,
            status=status_value,
            ttft_ms=None,
            total_latency_ms=round(total_latency_ms, 2),
            server_latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            tps=None,
            output_text=None,
            error_message=full_error,
            iteration=iteration,
            category=category,
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
        status_value = "overloaded" if _is_overload_error(full_error) else "error"

        logger.exception("Probe %s for %s (iter %d)", status_value, model_id, iteration)

        db_result = ProbeResult(
            run_id=run_id,
            model_id=model_id,
            model_name=model_name,
            timestamp=datetime.now(timezone.utc),
            prompt=prompt,
            status=status_value,
            ttft_ms=None,
            total_latency_ms=round(total_latency_ms, 2),
            server_latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            tps=None,
            output_text=None,
            error_message=full_error,
            iteration=iteration,
            category=category,
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


# =====================================================================
# Comparison Lab - in-memory streaming probe (DB 저장 없음).
# Phase 1: 한 prompt를 N개 모델에 병렬 invoke + side-by-side 비교.
# =====================================================================


def _compare_single_model(
    model_id: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    event_queue: Queue,
) -> None:
    """compare용 - DB 저장 없이 SSE event_queue로만 결과 push.

    Bedrock(`us.*`/`global.*`) + Anthropic CP on AWS(`anthropic:*`) + OpenAI(`openai:*`) 채널 지원.
    실패는 error 이벤트로만 보고 (raise 없음 - 다른 모델 호출에 영향 X).
    """
    start_time = time.monotonic()
    first_token_time: float | None = None
    collected_text: list[str] = []
    input_tokens = 0
    output_tokens = 0
    server_latency_ms: float | None = None
    model_name = AVAILABLE_MODELS.get(model_id, model_id)

    def emit(event_type: str, data: dict) -> None:
        data.setdefault("model_id", model_id)
        data.setdefault("model_name", model_name)
        event_queue.put(_sse(event_type, data))

    try:
        if _is_anthropic_direct(model_id):
            actual_id = _anthropic_actual_id(model_id)
            client = _get_anthropic_client()
            with client.messages.stream(
                model=actual_id,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        now = time.monotonic()
                        if first_token_time is None:
                            first_token_time = now
                            emit("ttft", {"ttft_ms": round((now - start_time) * 1000, 2)})
                        collected_text.append(text)
                        emit("token", {"token": text})
                final = stream.get_final_message()
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens
        elif _is_openai_direct(model_id):
            region, actual_id = _openai_parts(model_id)
            client = _get_openai_client(_openai_base_url(region))
            for kind, *rest in _openai_stream_events(client, actual_id, prompt, max_tokens):
                if kind == "delta":
                    text = rest[0]
                    now = time.monotonic()
                    if first_token_time is None:
                        first_token_time = now
                        emit("ttft", {"ttft_ms": round((now - start_time) * 1000, 2)})
                    collected_text.append(text)
                    emit("token", {"token": text})
                else:  # ("final", input_tokens, output_tokens, _stop)
                    input_tokens, output_tokens, _stop = rest
        else:
            client = _get_bedrock_client(_get_region_for_model(model_id))
            cfg: dict = {"maxTokens": max_tokens}
            if not _is_reasoning_model(model_id):
                cfg["temperature"] = temperature
            response = client.converse_stream(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig=cfg,
            )
            for event in response["stream"]:
                if "contentBlockDelta" in event:
                    text = event["contentBlockDelta"]["delta"].get("text", "")
                    if text:
                        now = time.monotonic()
                        if first_token_time is None:
                            first_token_time = now
                            emit("ttft", {"ttft_ms": round((now - start_time) * 1000, 2)})
                        collected_text.append(text)
                        emit("token", {"token": text})
                elif "metadata" in event:
                    usage = event["metadata"].get("usage", {})
                    metrics = event["metadata"].get("metrics", {})
                    input_tokens = usage.get("inputTokens", 0)
                    output_tokens = usage.get("outputTokens", 0)
                    server_latency_ms = metrics.get("latencyMs")

        end_time = time.monotonic()
        total_latency_ms = (end_time - start_time) * 1000.0
        ttft_ms = (first_token_time - start_time) * 1000.0 if first_token_time else None
        tps: float | None = None
        if first_token_time is not None and output_tokens > 0:
            gen_seconds = end_time - first_token_time
            if gen_seconds > 0:
                tps = output_tokens / gen_seconds

        emit("result", {
            "status": "success",
            "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
            "total_latency_ms": round(total_latency_ms, 2),
            "server_latency_ms": round(server_latency_ms, 2) if server_latency_ms is not None else None,
            "tps": round(tps, 2) if tps is not None else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "output_text": "".join(collected_text),
        })
    except Exception as exc:
        end_time = time.monotonic()
        err_msg = f"{type(exc).__name__}: {exc}"
        status_value = "overloaded" if _is_overload_error(err_msg) else "error"
        logger.exception("Compare probe %s for %s", status_value, model_id)
        emit("error", {
            "status": status_value,
            "error": err_msg,
            "total_latency_ms": round((end_time - start_time) * 1000, 2),
        })


def stream_compare_events(
    model_ids: list[str],
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.1,
    concurrency: int = 5,
) -> Generator[str, None, None]:
    """Comparison Lab generator - N개 모델 병렬 invoke + SSE 스트림.

    DB 저장 안 함. 모든 결과는 in-memory event queue로만 흐름.
    각 모델에 1회씩만 호출 (반복 없음).
    """
    event_queue: Queue[str | None] = Queue()
    total = len(model_ids)
    yield _sse("start", {"total_tasks": total, "model_ids": model_ids})

    def _run_all() -> None:
        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, total))) as ex:
            futures = [
                ex.submit(_compare_single_model, mid, prompt, max_tokens, temperature, event_queue)
                for mid in model_ids
            ]
            for f in futures:
                try:
                    f.result()
                except Exception:
                    logger.exception("Compare future failed")
        event_queue.put(None)

    threading.Thread(target=_run_all, daemon=True).start()

    completed = 0
    while True:
        try:
            event = event_queue.get(timeout=300)
        except Empty:
            yield _sse("error", {"error": "Compare timed out after 5 minutes"})
            break
        if event is None:
            break
        yield event
        if "event: result\n" in event or "event: error\n" in event:
            completed += 1
    yield _sse("complete", {"total": completed})
