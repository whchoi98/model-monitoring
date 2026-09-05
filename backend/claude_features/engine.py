"""Claude API Features 판정 순수 로직 (v2.23.0) — 외부 의존 없음, 단위 테스트 대상.

observed ∈ supported | unsupported | broken | inconclusive | skipped | not_applicable
verdict  ∈ match | drift | undocumented | none   (문서 기대치 vs 실측)
"""

from __future__ import annotations

from typing import Any

from parity.engine import classify_error as _parity_classify

STATUSES = ("supported", "unsupported", "broken", "inconclusive", "skipped", "not_applicable")

# parity._UNSUPPORTED_MARKERS 위에 본 기능에서 추가로 확인된 "깨끗한 거부" 시그니처
_EXTRA_UNSUPPORTED = (
    "unknown field",
    "not supported for this model",
    "does not support tool types",
    "for the `anthropic-beta` header",
    "unexpected value(s)",
    "is not available on this platform",
    "not available on",
    "no route",
    "http 404",
    "http 405",
    "not found",
)


def classify(error_message: str | None) -> str:
    if not error_message:
        return "broken"
    if _parity_classify(error_message) == "unsupported":
        return "unsupported"
    msg = error_message.lower()
    return "unsupported" if any(m in msg for m in _EXTRA_UNSUPPORTED) else "broken"


def verdict(documented: str, observed: str) -> str:
    if documented == "unknown" or observed in ("inconclusive", "skipped", "not_applicable"):
        return "none"
    if documented in ("ga", "beta"):
        if observed == "supported":
            return "match"
        return "drift"  # unsupported | broken
    # documented == "no"
    if observed == "unsupported":
        return "match"
    if observed == "supported":
        return "undocumented"
    return "none"


def aggregate_cell(statuses: list[str]) -> dict[str, Any]:
    counts = {s: 0 for s in STATUSES}
    for s in statuses:
        if s in counts:
            counts[s] += 1
    probed = counts["supported"] + counts["unsupported"] + counts["broken"] + counts["inconclusive"]
    if not statuses:
        status = "empty"
    elif probed == 0:
        status = "not_applicable" if counts["not_applicable"] else "skipped"
    elif counts["broken"]:
        status = "broken"
    elif counts["supported"] == probed:
        status = "supported"
    elif counts["unsupported"] == probed:
        status = "unsupported"
    elif counts["inconclusive"] == probed:
        status = "inconclusive"
    else:
        status = "partial"
    return {"status": status, "counts": counts, "probed": probed}


def diff_runs(prev: dict[tuple, str], cur: dict[tuple, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in sorted(cur):
        before, after = prev.get(key), cur[key]
        if before == after:
            continue
        feature, surface, model_key = key
        out.append({"feature": feature, "surface": surface, "model_key": model_key, "before": before, "after": after})
    return out


def has_thinking_evidence(blocks: list[dict] | None) -> bool:
    """adaptive thinking 증거: thinking 블록이 있고 요약 텍스트나 서명 중 하나가 실제로 채워졌는가.

    Bedrock의 Fable 5.1은 요약 텍스트를 비워 보내고 signature만 채운다(추론은 실제로 수행) →
    블록 존재만 보는 검사는 빈 블록도 통과시키고, 텍스트만 보는 검사는 false-broken을 만든다.
    """
    b = find_block(blocks, "thinking")
    if b is None:
        return False
    return bool((b.get("thinking") or "").strip() or (b.get("signature") or "").strip())


def citation_is_search_result(citation: Any) -> bool:
    """인용 1건이 search_result 출처를 가리키는가 (Anthropic·Converse 양쪽 표기).

    Anthropic: ``{"type": "search_result_location", …}``
    Converse:  ``{"location": {"searchResultLocation": {"searchResultIndex": 0, …}}}`` — type 필드가 없다.
    """
    if not isinstance(citation, dict):
        return False
    if citation.get("type") == "search_result_location":
        return True
    loc = citation.get("location")
    return isinstance(loc, dict) and "searchResultLocation" in loc


#: effort 전용 허용값 — 이 중 `xhigh`는 다른 파라미터에 등장하지 않아 열거 자체가 지목 증거가 된다.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def effort_rejection_names_param(error_message: str | None, bad_value: str) -> bool:
    """effort 부정 제어의 400이 effort 파라미터를 지목했는가 (파싱·검증됐다는 증거).

    CP/Mantle은 필드 경로를 돌려준다: `output_config.effort: Input should be 'low', …`.
    Bedrock(InvokeModel·Converse)은 경로를 지우고 허용 variant만 남긴다:
    ``unknown variant `ultra`, expected one of `low`, `medium`, `high`, `xhigh`, `max` …``
    → 잘못된 값 + effort 전용 값 열거도 동등한 지목 증거로 인정한다. 아무 400이나 통과시키지는 않는다.
    """
    msg = (error_message or "").lower()
    if not msg:
        return False
    if "effort" in msg:
        return True
    return bad_value.lower() in msg and "xhigh" in msg


def find_block(blocks: list[dict] | None, type_: str) -> dict | None:
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") == type_:
            return b
    return None


def has_block(blocks: list[dict] | None, type_: str) -> bool:
    return find_block(blocks, type_) is not None


def usage_int(usage: dict | None, *keys: str) -> int:
    if not usage:
        return 0
    for k in keys:
        v = usage.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def text_of(blocks: list[dict] | None) -> str:
    return "".join(b.get("text", "") for b in blocks or [] if isinstance(b, dict) and b.get("type") == "text")
