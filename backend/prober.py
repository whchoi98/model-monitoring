"""Core streaming probe logic.

Calls Bedrock converse_stream for each model, collects latency metrics,
streams SSE events back to the client, and persists results to the DB.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
from stream_watchdog import CallWatchdog

logger = logging.getLogger(__name__)

# 프로브 1회(재시도·backoff 포함)의 wall-clock 상한 (v2.28.2 핫픽스).
# 2026-09-23 장애: Mantle us-east-1 GPT-5.6 Sol Responses 스트림이 200 뒤 멈추거나 드문드문 흘러
# 청크 간 read timeout이 끝내 발동하지 않았고(라이브 재현: read timeout 40s로도 150s 정지), 스레드
# 하나가 AutoProber 사이클을 멈춰 대시보드가 동결됐다. 만료되면 스트림 소켓을 끊고 해당 모델만
# 오류 행 "WallClockTimeout: probe exceeded 90s wall-clock"이 된다.
# 적용 범위: 세 경로 모두(OpenAI Responses, Anthropic CP messages.stream, Bedrock converse_stream).
# OpenAI/Anthropic SDK는 둘 다 httpx라 read timeout이 청크 간 상한일 뿐이고(같은 trickle 계열),
# botocore도 read_timeout(기본 60s)이 소켓 read 단위라 드문드문 오는 이벤트에는 발동하지 않는다.
# 그래서 모델 경로와 무관하게 _probe_single_model에서 공통으로 건다. 헤더 대기(스트림 객체가 생기기
# 전)는 watchdog이 끊을 수 없어 각 SDK의 connect/read timeout이 상한이다 — auto_prober의 모델별
# 사이클 타임아웃(PROBE_FUTURE_TIMEOUT_S)이 그 구간까지 포함한 최종 안전망이다.
PROBE_WALL_CLOCK_S = float(os.environ.get("PROBE_WALL_CLOCK_S", "90"))
# 긴 출력을 요청한 수동 프로브(/api/probes/run, max_tokens ≤ 4096)와 Comparison Lab(≤ 8192)이 정상
# 생성 도중 잘리지 않도록 상한의 하한을 출력 예산으로도 잡는다 — 20 tok/s 기준 4096 → 205s,
# 8192 → 410s. 자동 사이클 프리셋(max_tokens ≤ 512 → 26s)은 PROBE_WALL_CLOCK_S가 그대로 상한이다.
_WALL_CLOCK_MIN_TPS = 20.0


def _wall_clock_limit(max_tokens: int) -> float:
    """프로브 1회의 wall-clock 상한(초) — PROBE_WALL_CLOCK_S, 단 출력 예산이 크면 그만큼 늘린다."""
    return max(PROBE_WALL_CLOCK_S, max_tokens / _WALL_CLOCK_MIN_TPS)


class WallClockTimeout(Exception):
    """프로브 스트림이 wall-clock 상한(_wall_clock_limit)을 넘겨 watchdog이 끊었다 (v2.28.2)."""

    def __init__(self, limit_s: float):
        super().__init__(f"WallClockTimeout: probe exceeded {limit_s:g}s wall-clock")


class _ProbeDeadline:
    """스트리밍 시도 1회의 wall-clock 가드 — stream_watchdog.CallWatchdog + 판정 규칙.

    판정은 gptbench.one_call과 같다:
      - 종료 이벤트(mark_done) 전에 만료되면 WallClockTimeout (만료 뒤 버퍼에 남은 종료 이벤트도 초과).
      - 만료 전에 종료 이벤트를 받았으면 그 뒤 abort가 스트림 꼬리를 끊어 예외가 나도 성공 유지.
      - check()는 이벤트마다 + 스트림 종료 직후 호출한다 — 소켓을 못 끊는 스트림(가짜 스트림 등)이나
        abort 뒤 조용히 끝난 스트림이 부분 응답 성공으로 기록되지 않게 한다.
    budget_s는 이 시도에 남은 예산(재시도 시 줄어듦), limit_s는 오류 문구에 쓰는 설정 상한이다.
    """

    def __init__(self, budget_s: float, limit_s: float):
        self.limit_s = limit_s
        self.done = False
        self._watchdog = CallWatchdog(budget_s)

    def __enter__(self) -> "_ProbeDeadline":
        self._watchdog.start()
        return self

    def __exit__(self, *exc_info) -> bool:
        self._watchdog.cancel()
        return False

    def attach(self, stream) -> None:
        self._watchdog.attach(stream)

    def check(self) -> None:
        if self._watchdog.fired and not self.done:
            raise WallClockTimeout(self.limit_s)

    def mark_done(self) -> None:
        """종료 이벤트 수신 — 이미 만료됐다면 done이 아니다(상한 초과 호출)."""
        self.done = not self._watchdog.fired

    def outcome(self, exc: Exception) -> Exception | None:
        """시도 중 난 예외의 최종 판정. None = 만료 전에 끝난 스트림(성공 유지)."""
        if isinstance(exc, WallClockTimeout) or not self._watchdog.fired:
            return exc
        # fired는 abort 전에 lock 아래에서 켜지므로, 만료 뒤의 예외는 abort가 끊은 스트림의 부수 예외다.
        return None if self.done else WallClockTimeout(self.limit_s)


# 모니터링 대상 - Global profile (Seoul 호출) + US profile (us-east-1 호출, Claude Platform on AWS).
AVAILABLE_MODELS: dict[str, str] = {
    # Bedrock - Global cross-region inference profile (ap-northeast-2)
    # Fable 5.1 (v2.22.0, 2026-09-01): Fable 5와 동일한 Covered Model 제약(provider_data_share 리전 opt-in 기존 적용).
    # forced tool_choice(type tool/any)는 400 — 패리티 tool_use 프로브는 auto로 대체 (parity/catalog.py).
    "global.anthropic.claude-fable-5-1": "Bedrock Claude Fable 5.1 (Global)",
    "global.anthropic.claude-fable-5": "Bedrock Claude Fable 5 (Global)",
    # Opus 5.5 (v2.27.0, 2026-09-22 출시): Seoul은 Global CRIS만 제공(Geo 없음), us.는 us-east-1.
    # temperature 400(추론 전용) · forced tool_choice(type tool/any) 400 — 패리티는 auto로 대체 (parity/catalog.py).
    "global.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (Global)",
    "global.anthropic.claude-opus-5": "Bedrock Claude Opus 5 (Global)",
    "global.anthropic.claude-opus-4-8": "Bedrock Claude Opus 4.8 (Global)",
    "global.anthropic.claude-opus-4-7": "Bedrock Claude Opus 4.7 (Global)",
    "global.anthropic.claude-opus-4-6-v1": "Bedrock Claude Opus 4.6 (Global)",
    "global.anthropic.claude-sonnet-5": "Bedrock Claude Sonnet 5 (Global)",
    "global.anthropic.claude-sonnet-4-6": "Bedrock Claude Sonnet 4.6 (Global)",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": "Bedrock Claude Haiku 4.5 (Global)",
    # Bedrock - US cross-region inference profile (us-east-1)
    # Fable 5 (Covered Model): provider_data_share data-retention 필요 — us. 는 us-east-1, global. 는 ap-northeast-2 리전 opt-in (2026-06-10). plain anthropic.* FM ID는 on-demand 미지원이라 inference profile(us./global.) 사용.
    "us.anthropic.claude-fable-5-1": "Bedrock Claude Fable 5.1 (US)",
    "us.anthropic.claude-fable-5": "Bedrock Claude Fable 5 (US)",
    "us.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (US)",
    "us.anthropic.claude-opus-5": "Bedrock Claude Opus 5 (US)",
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
# ⚠️ substring이 다른 타깃의 접두(fable-5 ⊂ fable-5-1, opus-5 ⊂ opus-5-5)가 될 수 있음 —
#    _match_anthropic_model()이 더 긴 타깃을 포함하는 id와, 아직 타깃이 없는 점 버전 id
#    (예: sonnet-5에 대한 claude-sonnet-5-5)를 짧은 타깃 후보에서 제외해 오등록을 막는다 (v2.22.0, v2.27.0).
_ANTHROPIC_TARGETS: list[tuple[str, str]] = [
    ("fable-5-1", "Anthropic Claude Fable 5.1 (US)"),  # v2.22.0 — CP 서빙 시 자동 발견
    ("fable-5", "Anthropic Claude Fable 5 (US)"),
    ("opus-5-5", "Anthropic Claude Opus 5.5 (US)"),  # v2.27.0 — CP가 2026-09-22부터 서빙
    ("opus-5", "Anthropic Claude Opus 5 (US)"),  # v2.19.0 — 조직 복구 시 자동 발견
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


def _is_point_release_of(substring: str, model_id: str) -> bool:
    """model_id가 substring 모델의 점 버전(예: 'opus-5' 기준 'claude-opus-5-5')인지.

    substring 바로 뒤에 '-<1~2자리 숫자>'가 오고 그 뒤가 숫자가 아니면 점 버전으로 본다.
    날짜 서픽스('haiku-4-5' 기준 'claude-haiku-4-5-20251001')는 8자리라 해당하지 않는다.
    """
    return re.search(re.escape(substring) + r"-\d{1,2}(?!\d)", model_id) is not None


def _match_anthropic_model(substring: str, all_ids: list[str]) -> str | None:
    """/v1/models id 목록에서 타깃 substring에 해당하는 id 하나를 고른다.

    같은 접두를 공유하는 더 긴 타깃(예: 'fable-5' vs 'fable-5-1')이 있으면 그 긴 substring을
    포함하는 id는 후보에서 제외 — /v1/models가 claude-fable-5-1을 claude-fable-5보다 먼저 돌려주면
    Fable 5 라벨이 5.1 id에 붙는 오등록이 생기기 때문 (v2.22.0).
    타깃이 아직 없는 점 버전도 제외한다 — Opus 5.5 출시일(2026-09-22)에 /v1/models가
    claude-opus-5-5를 claude-opus-5보다 먼저 돌려줘 5.5 id가 Opus 5 라벨로 프로빙된 실사고 (v2.27.0).
    """
    longer = [s for s, _ in _ANTHROPIC_TARGETS if s != substring and substring in s]
    return next(
        (
            mid for mid in all_ids
            if substring in mid
            and not any(label in mid for label in longer)
            and not _is_point_release_of(substring, mid)
        ),
        None,
    )


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
            # 디스커버리는 best-effort — backend lifespan(기동)에서 호출되므로 시간 상한 필수.
            # CP 조직 비활성 기간에 느린 500 + SDK 재시도가 기동을 지연시켜 ELB 헬스체크
            # 실패 → 배포 롤백을 유발한 실사고 (2026-07-22, v2.18.1 배포).
            timeout=10.0,
            max_retries=1,
        )
        models_page = client.models.list(limit=100)
        all_ids = [m.id for m in models_page.data]
        for substring, display_label in _ANTHROPIC_TARGETS:
            matched = _match_anthropic_model(substring, all_ids)
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
_anthropic_probe_client_cache: object | None = None


def _get_anthropic_client():
    """Lazy-init Anthropic SDK client (singleton). CP on AWS base_url + workspace 헤더.

    SDK 기본값(max_retries=2) 그대로 — Comparison Lab과 패리티 런(`messages` surface)이 쓴다. 둘 다
    재시도 루프가 없어 일시 오류 재시도를 SDK에 맡긴다. 대시보드 프로브는 _get_anthropic_probe_client.
    """
    global _anthropic_client_cache
    if _anthropic_client_cache is None:
        from anthropic import Anthropic
        _anthropic_client_cache = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=_anthropic_base_url(),
            default_headers=_anthropic_default_headers(),
        )
    return _anthropic_client_cache


def _get_anthropic_probe_client():
    """프로브 전용 CP 클라이언트 (v2.29.0) — 엔드포인트·헤더는 같고 SDK 재시도만 끈다(max_retries=0).

    대시보드 사이클과 /api/probes/run(_probe_single_model)이 쓴다. SDK 기본 재시도 2회가 prober 루프
    재시도(최대 4회 시도)와 곱해져 프로브 하나가 최대 12요청이 됐다 — 2026-09-23 월간 사용량 상한 429
    동안 /ecs/autoprober에 시간당 1,600~1,700줄. 재시도는 루프 하나만 두고, SDK가 재시도하던 일시
    오류(408/409/429/5xx, 연결 오류, timeout)는 _should_retry_probe가 대신 맡는다. timeout은 SDK
    기본값 그대로다(스트림 전체 상한은 PROBE_WALL_CLOCK_S watchdog).
    """
    global _anthropic_probe_client_cache
    if _anthropic_probe_client_cache is None:
        from anthropic import Anthropic
        _anthropic_probe_client_cache = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=_anthropic_base_url(),
            default_headers=_anthropic_default_headers(),
            max_retries=0,
        )
    return _anthropic_probe_client_cache


def _is_anthropic_direct(model_id: str) -> bool:
    return model_id.startswith("anthropic:")


def _anthropic_actual_id(model_id: str) -> str:
    """anthropic:<id> → <id>."""
    return model_id.split(":", 1)[1]


# Reasoning model은 inferenceConfig.temperature를 거부 - 패턴 기반 식별.
# "fable-5"는 substring 매칭이라 fable-5-1(Fable 5.1)도, "opus-5"는 opus-5-5(Opus 5.5)도 포함한다
# (Opus 5.5 temperature 400은 2026-09-23 converse_stream 실측).
_REASONING_MODEL_PATTERNS = ("opus-4-7", "opus-4-8", "opus-5", "fable-5", "sonnet-5")


def _is_reasoning_model(model_id: str) -> bool:
    """temperature 파라미터를 거부하는 reasoning model 여부."""
    return any(p in model_id for p in _REASONING_MODEL_PATTERNS)


# =====================================================================
# OpenAI GPT via Bedrock Mantle (OpenAI-compatible /openai/v1) — Path 4.
# model_id 키 스킴: "openai:<region>:<actual_model_id>" (예: openai:us-east-1:openai.gpt-5.4).
# region이 채널 식별자 (같은 model_id를 두 리전에 호출). bearer 토큰 인증.
# pseudo-region "global" (v2.20.0): Bedrock global cross-region 프로파일 —
# "openai:global:global.openai.gpt-5.6-sol" 형태 (actual_id 자체에 global. 접두사 포함).
# pseudo-region "us" (v2.25.0): Bedrock US cross-region 프로파일 —
# "openai:us:us.openai.gpt-6-astra" 형태 (actual_id 자체에 us. 접두사 포함).
# =====================================================================
_OPENAI_REGION_ENV: dict[str, str] = {
    "us-east-1": "OPENAI_US_EAST_1_BASE_URL",
    "us-east-2": "OPENAI_US_EAST_2_BASE_URL",
    "us-west-2": "OPENAI_US_WEST_2_BASE_URL",
    # pseudo-region "global" (v2.20.0) — Bedrock global cross-region 프로파일(global.openai.*).
    # bedrock-runtime OpenAI-compat 엔드포인트를 통해서만 호출 가능(bedrock-mantle 호스트는 미지원).
    # 운영값: https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1 (Seoul 라우팅).
    "global": "OPENAI_GLOBAL_BASE_URL",
    # pseudo-region "us" (v2.25.0) — Bedrock US cross-region 프로파일(us.openai.*).
    # 운영값: https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1 (2026-09-09 라이브 200 확인).
    "us": "OPENAI_US_BASE_URL",
}

# pseudo-region → (CRIS 프로파일 접두사, 라벨 서픽스). in-region 채널은 이 표에 없음.
# 라벨 표기는 Claude 채널과 동일한 "(Global)", "(US)" — DB model_name에 영구 기록되므로
# frontend MODEL_COLORS/channelRank가 기대하는 표기와 정확히 일치해야 한다.
_OPENAI_PSEUDO_REGIONS: dict[str, tuple[str, str]] = {
    "global": ("global.", "Global"),
    "us": ("us.", "US"),
}

# 모델별 가용 리전 — 모델이 모든 리전에 있는 건 아님(예: gpt-5.5/5.6-sol은 us-west-2 미제공 → 404).
# (model-id env var, display family, 제공 리전 튜플)
# "global"은 GPT-5.6 세대 이상만 지원(2026-08-17 발표) — 5.4/5.5 스펙에 넣으면 매 프로브 404.
# "us"(US CRIS)는 GPT-6 세대만 확인(Astra 2026-09-09, Sol/Luna 2026-09-23 라이브 200) — 5.x는 미검증이라 미기재.
# pseudo-region 채널의 모델 id는 in-region id에 접두사를 파생(_OPENAI_PSEUDO_REGIONS, 등록 루프).
# GPT 6 Astra의 Mantle 인리전은 us-west-2만 서빙 — us-east-1/us-east-2는 현재 미지원
# (404 not_found_error, 2026-09-09·2026-09-23 실측) → 2026-09-23 사용자 결정으로 제외(스펙 미기재).
# 정기 재확인 대상 아님 — AWS가 지원을 발표하면 아래 스펙 튜플에 리전만 추가하면 된다.
# GPT 6 Sol/Luna(2026-09-22 출시)의 Mantle 인리전은 반대로 us-east-1만 서빙 — us-east-2/us-west-2는
# 현재 미지원(404 not_found_error, 2026-09-23 실측) → 2026-09-23 사용자 결정으로 제외(스펙 미기재),
# 정기 재확인 대상 아님. us-east-1 첫 호출은 401 "subscription is being set up"
# (Marketplace 구독 자동 개시)이었다가 수 분 뒤 200.
_OPENAI_MODEL_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", "GPT 6 Astra", ("global", "us", "us-west-2")),
    ("BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID", "GPT 6 Sol", ("global", "us", "us-east-1")),
    ("BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID", "GPT 6 Luna", ("global", "us", "us-east-1")),
    ("BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID", "GPT 5.6 Sol", ("global", "us-east-1", "us-east-2")),
    ("BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", "GPT 5.6 Terra", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID", "GPT 5.6 Luna", ("global", "us-east-1", "us-east-2", "us-west-2")),
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

# OpenAI SDK 클라이언트 timeout (v2.28.2) — SDK 기본값은 600s. httpx read timeout은 청크 간 대기
# 상한일 뿐이라 호출 전체 상한은 PROBE_WALL_CLOCK_S watchdog이 맡고, 이 값은 응답 헤더 대기와
# 완전 정지(아무것도 안 옴) 구간의 상한이다.
_OPENAI_CONNECT_TIMEOUT_S = 10.0
_OPENAI_READ_TIMEOUT_S = 60.0


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


def _openai_api_key(base_url: str) -> str:
    """base_url이 1P(api.openai.com)면 OpenAI platform 키(OPENAI_1P_API_KEY)를,
    아니면 Bedrock Mantle bearer 키(OPENAI_API_KEY)를 쓴다. 두 자격증명은 호환되지 않음.
    """
    if base_url == _openai_1p_base_url():
        return os.environ["OPENAI_1P_API_KEY"]
    return os.environ["OPENAI_API_KEY"]


def _get_openai_client(base_url: str):
    """Lazy-init OpenAI SDK client per base_url — 프로브 전용 설정.

    대시보드 사이클, /api/probes/run, Comparison Lab 프로브가 쓴다. 패리티 런은 이 클라이언트를
    쓰지 않고 SDK 기본값 클라이언트를 따로 만든다(parity/runner.py `_parity_openai_client`) —
    아래 max_retries=0 + 60s read는 프로브 스트림 hang 대책이지 패리티 판정용 설정이 아니다.
    """
    if base_url not in _openai_client_cache:
        # SDK 자체 Timeout 타입을 쓴다 — openai 1.x/2.x는 httpx.Timeout, 3.x(운영 이미지 3.19, httpx2 기반)는
        # 자체 타입이라 httpx.Timeout을 넘기면 호환 shim에만 기대게 된다(2026-09-23 리뷰, 운영 이미지로 확인).
        from openai import OpenAI, Timeout
        _openai_client_cache[base_url] = OpenAI(
            api_key=_openai_api_key(base_url),
            base_url=base_url,
            timeout=Timeout(_OPENAI_READ_TIMEOUT_S, connect=_OPENAI_CONNECT_TIMEOUT_S),
            # SDK 재시도 금지 (v2.28.2) — 재시도는 _probe_single_model의 _RETRYABLE_PATTERNS 루프
            # 하나만 둔다. SDK 기본 max_retries=2가 겹치면 한 프로브의 대기가 곱으로 늘어난다.
            max_retries=0,
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
                pseudo = _OPENAI_PSEUDO_REGIONS.get(region)
                if pseudo:
                    # CRIS 프로파일 id = 접두사("global."/"us.") + in-region id (AWS 규약).
                    # 라벨은 Claude 채널과 동일하게 "(Global)", "(US)" 대문자 — DB model_name에
                    # 영구 기록되므로 frontend MODEL_COLORS/channelRank 기대 표기와 일치해야 함.
                    prefix, label_suffix = pseudo
                    channel_id = f"{prefix}{actual_id}"
                    label = f"OpenAI {family} ({label_suffix})"
                else:
                    channel_id = actual_id
                    label = f"OpenAI {family} ({region})"
                key = f"openai:{region}:{channel_id}"
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


def _openai_stream_events(
    client, actual_id: str, prompt: str, max_tokens: int, guard: _ProbeDeadline | None = None,
):
    """Stream the OpenAI **Responses API** (gpt-5.x require /responses, NOT /chat/completions).

    Normalized tuples를 yield:
      ("delta", text)                                       - 출력 텍스트 조각
      ("final", input_tokens, output_tokens, stop_reason)   - 완료/미완료 시 usage + stop
    temperature는 보내지 않음 (reasoning model). 토큰 한도는 max_output_tokens.

    guard(v2.28.2): 스트림이 열리면 wall-clock watchdog에 붙이고, 이벤트마다 만료를 검사하며
    종료 이벤트에서 done을 표시한다 — 프로브와 Comparison Lab이 이 제너레이터를 공유하므로 두 경로
    모두 같은 상한을 받는다. 요청 형태(payload)는 guard 유무와 무관하게 같다.
    """
    stream = client.responses.create(
        model=actual_id,
        input=prompt,
        max_output_tokens=max_tokens,
        stream=True,
    )
    if guard is not None:
        guard.attach(stream)
    for ev in stream:
        if guard is not None:
            guard.check()
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
            if guard is not None:
                guard.mark_done()
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
# 2s, 4s, 8s exponential backoff. 최대 3회 재시도 (총 4 attempts), wall-clock 예산 안에서만.
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


# 월간 사용량 상한 429 (v2.29.0) — 재시도해도 풀리지 않는 조직 단위 상한이라 재시도하지 않는다.
# 2026-09-23 19:52 UTC부터 CP 호출이 전부 429 rate_limit_error로 거부됐다: "You have reached your API
# usage limits: your organization has crossed its monthly API usage threshold, set based on your
# organization's API tier. You will regain access on 2026-10-01 at 00:00 UTC." (details.error_code
# enforced_spend_limit_reached). 예외 타입(RateLimitError)과 오류 타입(rate_limit_error)이 일시 429와
# 같아 _RETRYABLE_PATTERNS가 재시도했다. 메시지로만 구분된다 — 일시 429("rate limit" 문구)는 그대로
# 재시도한다. 소문자로 비교한다.
_USAGE_CAP_MARKERS: tuple[str, ...] = (
    "usage limits",
    "usage threshold",
    "enforced_spend_limit_reached",
)


def _is_usage_cap_error(err_msg: str) -> bool:
    """조직·워크스페이스 사용량 상한 도달 429인지 (재시도 무의미)."""
    lowered = err_msg.lower()
    return any(marker in lowered for marker in _USAGE_CAP_MARKERS)


# CP 프로브 클라이언트는 SDK 재시도를 끈다(_get_anthropic_probe_client, v2.29.0). SDK 기본값이 재시도하던
# 일시 오류 — HTTP 408/409/429/5xx와 연결 오류·timeout — 는 이 루프가 같은 backoff로 대신 재시도한다.
# 상태 코드는 SDK APIStatusError.status_code, 연결 오류는 예외 클래스 이름으로 본다(SDK 버전과 무관).
_CP_RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 429})
_CP_RETRYABLE_EXCEPTIONS: frozenset[str] = frozenset({"APIConnectionError", "APITimeoutError"})


def _is_cp_transient_error(exc: BaseException) -> bool:
    """anthropic SDK가 기본 설정에서 재시도하던 일시 오류인지."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status in _CP_RETRYABLE_STATUS or status >= 500):
        return True
    return any(cls.__name__ in _CP_RETRYABLE_EXCEPTIONS for cls in type(exc).__mro__)


def _should_retry_probe(model_id: str, exc: BaseException, retry_key: str) -> bool:
    """prober 루프의 재시도 판정. 사용량 상한 429는 어떤 경로든 재시도하지 않는다 (v2.29.0)."""
    if _is_usage_cap_error(retry_key):
        return False
    if _is_retryable_error(retry_key):
        return True
    return _is_anthropic_direct(model_id) and _is_cp_transient_error(exc)


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

    세 경로 모두 wall-clock 상한(_wall_clock_limit — 자동 사이클은 PROBE_WALL_CLOCK_S) 안에서 돈다
    (v2.28.2) — 재시도·backoff를 포함한 프로브 전체 예산이며, 만료되면 스트림을 끊고 오류 행
    "WallClockTimeout: …"을 남긴다(재시도 없음).
    """
    start_time = time.monotonic()
    wall_limit = _wall_clock_limit(max_tokens)
    wall_deadline = start_time + wall_limit
    first_token_time: float | None = None
    collected_text: list[str] = []
    input_tokens = 0
    output_tokens = 0
    server_latency_ms: float | None = None
    stop_reason: str | None = None

    # Retry loop - vendor 일시 부하(529 overloaded / Throttle) 시 2/4/8s backoff 최대 3회.
    # 월간 사용량 상한 429는 재시도하지 않는다(_should_retry_probe, v2.29.0).
    last_exception: Exception | None = None
    for attempt in range(len(_RETRY_BACKOFFS) + 1):  # 4 attempts: 0, 1, 2, 3
        # 재시도 시 state 리셋 (partial token이 client에 이미 도착했다면 자연스러운 reset로 인식).
        if attempt > 0:
            start_time = time.monotonic()
            first_token_time = None
            collected_text = []
            input_tokens = 0
            output_tokens = 0
            server_latency_ms = None
            stop_reason = None
        # 이 시도의 watchdog 예산 = 프로브 전체 예산의 남은 몫 (재시도가 상한을 늘리지 않는다).
        guard = _ProbeDeadline(max(wall_deadline - time.monotonic(), 0.0), wall_limit)
        try:
            with guard:
                if _is_anthropic_direct(model_id):
                    actual_id = _anthropic_actual_id(model_id)
                    anthropic_client = _get_anthropic_probe_client()  # SDK 재시도 0 (v2.29.0)
                    with anthropic_client.messages.stream(
                        model=actual_id,
                        max_tokens=max_tokens,
                        messages=[{"role": "user", "content": prompt}],
                    ) as stream:
                        guard.attach(stream)
                        for text in stream.text_stream:
                            guard.check()
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
                        guard.check()
                        input_tokens = final_message.usage.input_tokens
                        output_tokens = final_message.usage.output_tokens
                        # stop_reason: end_turn | max_tokens | stop_sequence | tool_use
                        stop_reason = getattr(final_message, "stop_reason", None)
                        # Anthropic API는 server-side latency를 제공하지 않음 - None 유지.
                        guard.mark_done()
                elif _is_openai_direct(model_id):
                    region, actual_id = _openai_parts(model_id)
                    oa_client = _get_openai_client(_openai_base_url(region))
                    for kind, *rest in _openai_stream_events(oa_client, actual_id, prompt, max_tokens, guard):
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
                    guard.attach(stream)
                    for event in stream:
                        guard.check()
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
                            # converse_stream의 마지막 이벤트(messageStop 다음) — 여기서 응답 완결.
                            guard.mark_done()

                        elif "messageStop" in event:
                            # Bedrock converse_stream: stopReason in messageStop event.
                            # 값: end_turn | tool_use | max_tokens | stop_sequence | guardrail_intervened | content_filtered
                            stop_reason = event["messageStop"].get("stopReason")
                # abort 뒤 예외 없이 끝난 스트림(연결 종료 = 이벤트 끝)을 부분 응답 성공으로 두지 않는다.
                guard.check()
            # 성공 — retry loop 탈출
            last_exception = None
            break
        except Exception as exc:
            verdict = guard.outcome(exc)
            if verdict is None:
                # 상한 안에 응답이 완결된 뒤 만료된 watchdog이 스트림 꼬리를 끊었다 — 측정은 유효.
                last_exception = None
                break
            last_exception = verdict
            if isinstance(verdict, WallClockTimeout):
                # 예산을 다 썼다 — 재시도하지 않는다 (재시도는 상한을 넘기는 대기만 늘린다).
                break
            msg = str(exc)
            # 예외 타입명도 함께 본다 — OpenAI SDK의 429는 str()이 "Error code: 429 - …"뿐이라
            # _RETRYABLE_PATTERNS의 "RateLimitError"가 타입명으로만 매칭된다. v2.28.2부터 OpenAI,
            # v2.29.0부터 CP 프로브 클라이언트가 max_retries=0이므로 SDK가 대신 해 주던 재시도를 이
            # 루프가 맡는다. 월간 사용량 상한 429는 제외 — 오류 행 1개로 끝낸다.
            retry_key = f"{type(exc).__name__}: {msg}"
            if attempt < len(_RETRY_BACKOFFS) and _should_retry_probe(model_id, exc, retry_key):
                backoff = _RETRY_BACKOFFS[attempt]
                if time.monotonic() + backoff >= wall_deadline:
                    # backoff 후에는 wall-clock 예산이 남지 않는다 — 이 오류를 그대로 기록한다.
                    break
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
        if isinstance(exc, WallClockTimeout):
            # 원인이 분명한 오류 — "Unexpected:" 접두와 traceback 없이 그대로 남긴다 (v2.28.2).
            full_error = str(exc)
            status_value = "error"
            logger.warning("Probe error for %s (iter %d): %s", model_id, iteration, full_error)
        elif _is_usage_cap_error(f"{type(exc).__name__}: {exc}"):
            # 월간 사용량 상한 429 (v2.29.0) — 행 형식은 다른 SDK 오류와 같게 두고, 상한이 풀릴 때까지
            # 사이클마다 반복되므로 traceback 없이 한 줄만 남긴다.
            full_error = f"Unexpected: {str(exc)}"
            status_value = "error"
            logger.warning(
                "Probe error for %s (iter %d): usage cap reached, not retried: %s",
                model_id, iteration, str(exc)[:300],
            )
        else:
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

    # 프로브와 같은 wall-clock 상한 (v2.28.2) — 멈춘 스트림이 compare 워커 스레드를 붙잡지 않게 한다.
    wall_limit = _wall_clock_limit(max_tokens)
    guard = _ProbeDeadline(wall_limit, wall_limit)
    try:
        try:
            with guard:
                if _is_anthropic_direct(model_id):
                    actual_id = _anthropic_actual_id(model_id)
                    client = _get_anthropic_client()
                    with client.messages.stream(
                        model=actual_id,
                        max_tokens=max_tokens,
                        messages=[{"role": "user", "content": prompt}],
                    ) as stream:
                        guard.attach(stream)
                        for text in stream.text_stream:
                            guard.check()
                            if text:
                                now = time.monotonic()
                                if first_token_time is None:
                                    first_token_time = now
                                    emit("ttft", {"ttft_ms": round((now - start_time) * 1000, 2)})
                                collected_text.append(text)
                                emit("token", {"token": text})
                        final = stream.get_final_message()
                        guard.check()
                        input_tokens = final.usage.input_tokens
                        output_tokens = final.usage.output_tokens
                        guard.mark_done()
                elif _is_openai_direct(model_id):
                    region, actual_id = _openai_parts(model_id)
                    client = _get_openai_client(_openai_base_url(region))
                    for kind, *rest in _openai_stream_events(client, actual_id, prompt, max_tokens, guard):
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
                    stream = response["stream"]
                    guard.attach(stream)
                    for event in stream:
                        guard.check()
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
                            guard.mark_done()
                guard.check()
        except Exception as exc:
            verdict = guard.outcome(exc)
            if verdict is exc:
                raise
            if verdict is not None:
                raise verdict from exc
            # verdict None: 상한 안에 완결된 응답의 꼬리를 watchdog이 끊었을 뿐 — 결과는 유효.

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
        if isinstance(exc, WallClockTimeout):
            err_msg = str(exc)  # 이미 "WallClockTimeout: …" 형태 (v2.28.2)
            status_value = "error"
            logger.warning("Compare probe error for %s: %s", model_id, err_msg)
        else:
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
