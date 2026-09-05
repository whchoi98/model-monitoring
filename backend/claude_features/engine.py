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
