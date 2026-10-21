"""패리티 판정 순수 로직 — 오류 분류 + 실행 증거 검사 (v2.11.0).

원칙: HTTP 200은 증거가 아니다. supported 판정은 응답 '내용'이 증거 검사를 통과했을 때만.
provider가 기능 미지원을 명시적 미지원 오류(파라미터 거부 등)로 알려주면 unsupported,
그 외 오류·증거 실패는 broken.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# 기능 미지원을 나타내는 "명시적 미지원 오류" 시그니처 (소문자 비교).
_UNSUPPORTED_MARKERS = (
    "doesn't support",
    "does not support",
    "not supported",
    "unsupported_parameter",
    "unsupported parameter",
    "unknown parameter",
    "unexpected keyword",
    "extra inputs are not permitted",
    "invalid parameter",
    "unrecognized request argument",
    "no endpoints support",
    # Mantle /anthropic 등에서 모델이 해당 엔드포인트/리전에 서빙되지 않음 — 깨끗한 미제공 신호
    "does not exist",
    # Bedrock InvokeModel의 generic 검증 거부 — 프로브 형태는 고정이므로 도구/파라미터
    # 미지원 신호로 해석 (프로브 자체 결함이면 전 모델 동시 발생으로 드러남)
    "request is not valid",
    # 기능이 아직 미개방 (예: Mantle web_search live 모드, 신형 모델의 URL 소스)
    "not yet available",
    "not yet supported",
    # 고정 엔드포인트에 대한 본문 없는 404 (예: Mantle batches 미제공)
    "error code: 404",
    # bedrock-runtime의 coral 라우트 부재 — 본문이 XML이라 openai SDK 오류 문자열에 "error code: 404"가 없다.
    # 예: Global/US CRIS OpenAI 호환 엔드포인트의 GET /v1/models/{model} → "NotFoundError: <UnknownOperationException/>"
    # (claude_features/transports.py가 같은 신호를 404로 정규화한다)
    "unknownoperationexception",
    # 모델 단위 미제공 — Mantle /anthropic의 Fable 5(Covered Model)는 계정에 데이터 보존 옵트인이 없으면
    # "data retention mode 'default' is not available for this model"(400)로 거부한다. claude_features.engine과 같은
    # 판정 (사용자 결정 2026-10-19 — run #211까지 messages_mantle 16피처 × Global, US 32셀이 broken이었다)
    "is not available for this model",
    # 도구 스키마의 명시적 거부 — 허용 tool 태그 목록 반환 (Bedrock InvokeModel)
    "does not match any of the expected",
)


def classify_error(error_message: str | None) -> str:
    """오류 메시지 → 'unsupported'(명시적 미지원 응답) | 'broken'(그 외)."""
    if not error_message:
        return "broken"
    msg = error_message.lower()
    if any(m in msg for m in _UNSUPPORTED_MARKERS):
        return "unsupported"
    return "broken"


def check_canary(text: str | None, canary: str) -> bool:
    """system-instructions 증거: 응답 텍스트에 카나리 단어가 실제 반영됐는가."""
    return bool(text) and canary in text


def check_json_object(text: str | None, required_key: str) -> bool:
    """structured-output 증거: 필수 키를 가진 JSON 객체가 응답에 존재하는가.

    모델이 코드펜스·설명을 섞는 경우를 허용 — 첫 번째 { ... } 블록을 추출해 파싱.
    """
    if not text:
        return False
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return False
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return False
    return isinstance(obj, dict) and required_key in obj


def json_object_keys(text: str | None) -> list[str] | None:
    """응답의 첫 번째 { ... } JSON 객체 키 목록(정렬) — 객체가 없거나 파싱되지 않으면 None."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return sorted(obj) if isinstance(obj, dict) else None


def check_schema_keys(text: str | None, schema_keys: set[str]) -> bool:
    """json-schema 증거 (v2.34.0): 응답 JSON 객체의 키 집합이 스키마 키 집합과 정확히 같은가.

    프롬프트가 스키마와 다른 키 이름을 요구하므로, 서비스가 스키마를 조용히 무시하면 프롬프트의 키가 나와
    실패한다(스키마 없이는 name, 강제되면 city — 2026-10-20 실측). 키 존재만 보는 check_json_object로는
    무시를 잡지 못했다.
    """
    keys = json_object_keys(text)
    return keys is not None and set(keys) == schema_keys


def _matches_json_type(value: Any, json_type: str | None) -> bool:
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    return True  # 프로브 스키마는 string, integer만 쓴다


def check_strict_tool_input(tool_call: dict | None, canary: str, schema: dict) -> bool:
    """strict tool use 증거 (v2.34.0): 도구 입력 키가 스키마 properties와 정확히 같고, 값마다 타입이 맞고,
    카나리가 왕복했는가.

    프로브는 integer 인자에 문자열을 넣으라고 요구한다 — strict가 무시되면 모델이 문자열을 넣어 타입 검사에서
    걸린다(strict 없이 Haiku 5.5, Sonnet 4.6, GPT 5.6 Luna가 "three", strict면 전부 정수 — 2026-10-20 실측).
    """
    if not tool_call:
        return False
    args = tool_call.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            return False
    props = schema.get("properties", {})
    if not isinstance(args, dict) or set(args) != set(props):
        return False
    if not all(_matches_json_type(args[k], spec.get("type")) for k, spec in props.items()):
        return False
    return any(isinstance(v, str) and canary in v for v in args.values())


def check_tool_roundtrip(tool_call: dict | None, canary: str) -> bool:
    """tool-use 증거: 도구 호출이 실행됐고 카나리 인자가 그대로 왕복했는가."""
    if not tool_call:
        return False
    args = tool_call.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            return False
    if not isinstance(args, dict):
        return False
    return any(isinstance(v, str) and canary in v for v in args.values())


def check_cached_tokens(usage: Optional[dict[str, Any]]) -> bool:
    """caching 증거: 반복 요청의 usage에 캐시된 토큰 수가 0보다 큰가.

    provider별 필드: OpenAI cached_tokens / Anthropic cache_read_input_tokens
    / Bedrock cacheReadInputTokens.
    """
    if not usage:
        return False
    for key in ("cached_tokens", "cache_read_input_tokens", "cacheReadInputTokens", "cacheReadInputTokenCount"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return True
    return False


def check_stream_events(content_event_count: int) -> bool:
    """streaming 증거: 콘텐츠 델타 이벤트가 2개 이상 수신됐는가."""
    return content_event_count >= 2


def diff_statuses(
    prev: dict[tuple, str], cur: dict[tuple, str]
) -> list[dict[str, Any]]:
    """런 간 변경 감지 — (model_id, surface, feature) 키별 상태 비교.

    현재 런 기준: 상태가 바뀐 셀 + 신규 셀(before None)만 반환.
    이전 런에만 있던 셀(모델 제외 등)은 무시. 키 순 정렬로 결정적 출력.
    """
    changes: list[dict[str, Any]] = []
    for key in sorted(cur):
        before = prev.get(key)
        after = cur[key]
        if before == after:
            continue
        model_id, surface, feature = key
        changes.append({
            "model_id": model_id, "surface": surface, "feature": feature,
            "before": before, "after": after,
        })
    return changes
