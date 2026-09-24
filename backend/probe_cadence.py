"""AutoProber 채널별 수집 주기 (v2.29.0).

EventBridge 스케줄은 그대로 rate(5 minutes)이고, 사이클마다 어떤 모델을 프로빙할지를 auto_prober가
고른다. Claude Platform on AWS 채널(model_id 접두 "anthropic:", Anthropic 1P API, 라벨
"Anthropic Claude … (US)")만 10분 주기다. 2026-09-23 조직 월간 사용량 상한 429 이후 사용자 결정
("API 스로틀링 이슈 — 1P만 해당"): CP 호출량을 절반으로 줄인다. Bedrock Claude(global./us.), Nova,
OpenAI는 5분 그대로다.

DB·SDK 의존이 없어 라우터(/status, /latest)와 에이전트 도구가 가볍게 import한다. 주기는 5분 사이클
단위로 반올림된다(600 → 2사이클마다, 900 → 3사이클마다).
"""

import logging
import os

logger = logging.getLogger(__name__)

BASE_INTERVAL_SECONDS = 300

CP_MODEL_PREFIX = "anthropic:"
# /api/auto-probe/status channel_intervals 키 — model_id의 첫 ':' 앞 접두.
CP_CHANNEL = "anthropic"

_CP_INTERVAL_ENV = "ANTHROPIC_CP_PROBE_INTERVAL_S"
_CP_INTERVAL_DEFAULT = 600


def _cp_interval_from_env() -> int:
    """ANTHROPIC_CP_PROBE_INTERVAL_S (기본 600). 숫자가 아니면 기본값, 5분 미만이면 5분(매 사이클)."""
    raw = os.environ.get(_CP_INTERVAL_ENV, "").strip()
    if not raw:
        return _CP_INTERVAL_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer - using %ds", _CP_INTERVAL_ENV, raw, _CP_INTERVAL_DEFAULT)
        return _CP_INTERVAL_DEFAULT
    if value < BASE_INTERVAL_SECONDS:
        logger.warning("%s=%d is below the %ds cycle - probing every cycle", _CP_INTERVAL_ENV, value,
                       BASE_INTERVAL_SECONDS)
        return BASE_INTERVAL_SECONDS
    return value


ANTHROPIC_CP_PROBE_INTERVAL_S = _cp_interval_from_env()


def is_cp_model(model_id: str) -> bool:
    """Claude Platform on AWS 채널(anthropic:<id>)인지 — Bedrock Claude(global./us.anthropic.*)는 아니다."""
    return model_id.startswith(CP_MODEL_PREFIX)


def interval_for(model_id: str) -> int:
    """모델 한 채널의 수집 주기(초)."""
    return ANTHROPIC_CP_PROBE_INTERVAL_S if is_cp_model(model_id) else BASE_INTERVAL_SECONDS


def channel_intervals() -> dict[str, int]:
    """채널별 주기 — 키는 model_id의 첫 ':' 앞 접두. 여기 없는 채널은 BASE_INTERVAL_SECONDS."""
    return {CP_CHANNEL: ANTHROPIC_CP_PROBE_INTERVAL_S}
