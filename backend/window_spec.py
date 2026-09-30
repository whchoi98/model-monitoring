"""공개 조회 라우터의 창(window) 문자열 파서 — 창 상한이 곧 요청 하나의 스캔 상한이다 (2026-09-30).

"45m", "24h", "7d"처럼 정수와 단위(m, h, d, 대소문자 무관)를 받는다. 단위가 없는 값은 예전처럼 24시간으로
읽는다. 숫자를 읽을 수 없는 값('xd', '1e3h')과 상한(max_window)을 넘는 창은 422로 거부한다. 예전 라우터별
_parse_window는 앞의 것을 ValueError, 아주 큰 값을 OverflowError로 500을 냈고, 3650d 같은 큰 창은 보존 중인
probe_results(RETENTION_DAYS 60일)를 통째로 읽었다(2026-09-30 /analysis OOM, docs/runbooks/troubleshooting.md).

상한은 그 화면이 고를 수 있는 가장 긴 창이다. 넘는 요청을 상한으로 잘라 받지 않고 422로 거부하는 이유:
응답의 window 필드는 요청 문자열을 그대로 돌려주므로 잘라 읽으면 "3650d" 응답이 실제로는 30일치만 담는다.
프런트엔드는 상한 이하의 값만 보내므로 422는 기존 클라이언트를 깨지 않는다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import HTTPException

DEFAULT_WINDOW = timedelta(hours=24)  # 단위가 없는 값(예전과 같음)
_UNITS = {"d": "days", "h": "hours", "m": "minutes"}


def parse_window(spec: str, *, max_window: Optional[timedelta] = None) -> timedelta:
    """창 문자열 → timedelta. 읽을 수 없거나 max_window보다 길면 HTTPException(422)."""
    s = spec.strip().lower()
    unit = _UNITS.get(s[-1:])
    if unit is None:
        return DEFAULT_WINDOW
    try:
        delta = timedelta(**{unit: int(s[:-1])})
    except (ValueError, OverflowError):
        raise HTTPException(status_code=422, detail=f"window 값을 읽을 수 없습니다: {spec!r} (예: 24h, 7d)") from None
    if max_window is not None and delta > max_window:
        raise HTTPException(
            status_code=422,
            detail=f"window는 최대 {max_window.days}d까지 지정할 수 있습니다: {spec!r}",
        )
    return delta
