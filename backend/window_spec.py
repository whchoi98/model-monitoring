"""공개 조회 라우터의 창(window) 문자열 파서 — 창 상한이 곧 요청 하나의 스캔 상한이다 (2026-09-30).

"45m", "24h", "7d"처럼 정수와 단위(m, h, d, 대소문자 무관)를 받는다. 단위가 없는 값은 예전처럼 24시간으로
읽는다. 숫자를 읽을 수 없는 값('xd', '1e3h'), 0 이하의 창('0d', '-5d'), 상한(max_window)을 넘는 창, now - 창이
datetime 범위(서기 1년)를 벗어나는 창은 422로 거부한다. 예전 라우터별 _parse_window는 앞의 것을 ValueError, 아주 큰
값을 OverflowError로 500을 냈고, 0과 음수 창은 now 이후를 하한으로 삼아 빈 응답(200)을 냈으며, 3650d 같은 큰 창은
보존 중인 probe_results(RETENTION_DAYS 60일)를 통째로 읽었다(2026-09-30 /analysis OOM, docs/runbooks/troubleshooting.md).

상한은 그 화면이 고를 수 있는 가장 긴 창이다. 넘는 요청을 상한으로 잘라 받지 않고 422로 거부하는 이유:
응답의 window 필드는 요청 문자열을 그대로 돌려주므로 잘라 읽으면 "3650d" 응답이 실제로는 30일치만 담는다.
프런트엔드는 상한 이하의 값만 보내므로 422는 기존 클라이언트를 깨지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

DEFAULT_WINDOW = timedelta(hours=24)  # 단위가 없는 값(예전과 같음)
_UNITS = {"d": "days", "h": "hours", "m": "minutes"}
_EXAMPLE = "(예: 24h, 7d)"


def parse_window(spec: str, *, max_window: Optional[timedelta] = None) -> timedelta:
    """창 문자열 → 0보다 긴 timedelta. 읽을 수 없거나, 0 이하이거나, max_window보다 길거나,
    now - 창이 datetime 범위를 벗어나면 HTTPException(422)."""
    s = spec.strip().lower()
    unit = _UNITS.get(s[-1:])
    if unit is None:
        return DEFAULT_WINDOW
    try:
        delta = timedelta(**{unit: int(s[:-1])})
    except (ValueError, OverflowError):
        raise HTTPException(status_code=422, detail=f"window 값을 읽을 수 없습니다: {spec!r} {_EXAMPLE}") from None
    if delta <= timedelta(0):
        raise HTTPException(status_code=422, detail=f"window는 0보다 길어야 합니다: {spec!r} {_EXAMPLE}")
    if max_window is not None and delta > max_window:
        raise HTTPException(
            status_code=422,
            detail=f"window는 최대 {max_window.days}d까지 지정할 수 있습니다: {spec!r}",
        )
    # 호출자는 datetime.now(timezone.utc) - 창으로 하한을 만든다. 여기서 한 번 계산해 범위를 넘는 창을 거른다
    # (호출자의 now는 이보다 늦으므로 호출자 쪽 계산은 넘지 않는다).
    try:
        datetime.now(timezone.utc) - delta
    except OverflowError:
        raise HTTPException(status_code=422, detail=f"window가 너무 깁니다: {spec!r} {_EXAMPLE}") from None
    return delta
