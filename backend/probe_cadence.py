"""AutoProber 채널별 수집 주기 (v2.29.0 도입, v2.29.1 기본값 복귀).

EventBridge 스케줄은 그대로 rate(5 minutes)이고, 사이클마다 어떤 모델을 프로빙할지를 auto_prober가
고른다. 주기를 따로 둘 수 있는 채널은 Claude Platform on AWS(model_id 접두 "anthropic:", Anthropic 1P
API, 라벨 "Anthropic Claude … (US)")뿐이다. Bedrock Claude(global./us.), Nova, OpenAI는 항상 5분이다.

v2.29.1 기본값은 300 — CP도 매 사이클, 사이클 카테고리 그대로(v2.29.0 이전 동작). 2026-09-26 사용자 결정
("Anthropic API 호출 기간 텀을 늘렸었습니다. 원래대로 복귀해 주세요"). v2.29.0의 10분 주기(2026-09-23 조직
월간 사용량 상한 429 이후 사용자 결정, "API 스로틀링 이슈 — 1P만 해당")는 운영 노브로 남는다:
ANTHROPIC_CP_PROBE_INTERVAL_S=600이면 다시 두 사이클에 한 번 + CP 자체 카테고리 회전이다.

DB·SDK 의존이 없어 라우터(/status, /latest)와 에이전트 도구가 가볍게 import한다. 주기는 5분 사이클
단위로 반올림된다(300 → 매 사이클, 600 → 2사이클마다, 900 → 3사이클마다). 반올림은 env를 읽을 때 한 번
하므로 AutoProber, /status, /latest가 같은 값을 쓴다 — 예를 들어 400은 300(매 사이클, 사이클 카테고리)이다.
"""

import logging
import os

logger = logging.getLogger(__name__)

BASE_INTERVAL_SECONDS = 300

CP_MODEL_PREFIX = "anthropic:"
# /api/auto-probe/status channel_intervals 키 — model_id의 첫 ':' 앞 접두.
CP_CHANNEL = "anthropic"

_CP_INTERVAL_ENV = "ANTHROPIC_CP_PROBE_INTERVAL_S"
# v2.29.1: 매 사이클(v2.29.0 이전 동작). 600이면 v2.29.0의 10분 주기(두 사이클에 한 번).
_CP_INTERVAL_DEFAULT = BASE_INTERVAL_SECONDS


def _round_to_cycles(value: int) -> int:
    """5분 사이클의 배수로 반올림, 동률(n.5 사이클)은 내림 — 최소 한 사이클.

    auto_prober의 due 판정(직전 CP run 시작 후 주기 − 150초 이상 경과)을 명목 사이클 간격에 적용한
    결과와 같다: 301~450 → 300(매 사이클), 451~750 → 600, 751~1050 → 900. 반올림하지 않으면 예를 들어
    400은 매 사이클 프로빙되면서도 _plan_cycle의 early return(주기 ≤ 사이클)을 타지 않아 CP 자체 회전
    카테고리가 남고, /status·/latest는 실제와 다른 400을 쓴다.
    """
    cycles = max(1, (value + BASE_INTERVAL_SECONDS // 2 - 1) // BASE_INTERVAL_SECONDS)
    return cycles * BASE_INTERVAL_SECONDS


def _cp_interval_from_env() -> int:
    """ANTHROPIC_CP_PROBE_INTERVAL_S (v2.29.1 기본 300 = 매 사이클, 600 = 두 사이클에 한 번).

    숫자가 아니면 기본값, 5분 미만이면 5분(매 사이클), 그 밖에는 5분 사이클 단위로 반올림(_round_to_cycles).
    """
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
    rounded = _round_to_cycles(value)
    if rounded != value:
        logger.warning("%s=%d is not a whole number of %ds cycles - using %ds", _CP_INTERVAL_ENV, value,
                       BASE_INTERVAL_SECONDS, rounded)
    return rounded


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
