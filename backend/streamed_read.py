"""나눠 읽는 조회(yield_per)의 전체 시간 상한 — statement_timeout은 FETCH 하나에만 걸린다 (2026-09-30 v2.32.1 통합 리뷰).

database.py가 커넥션마다 거는 statement_timeout(DB_STATEMENT_TIMEOUT_MS, 기본 30초)은 문장 하나의 상한이다. 한 번에 받는
조회(.all(), GROUP BY 집계)는 문장 하나라 그 상한에서 취소된다. yield_per로 나눠 읽는 조회는 PostgreSQL에서 psycopg2 이름 있는
커서(DECLARE 뒤 FETCH 반복)이고, FETCH마다 새 문장이라 FETCH 하나하나가 상한 안에 끝나면 전체는 얼마든지 길어진다. DB가
느려지면(t4g.micro CPU 크레딧 소진) 풀 커넥션 하나와 워커 스레드 하나가 30초를 넘겨 붙잡히고, 그동안 CloudFront는 이미 504를
돌려준다.

stream_rows(query, what=...)는 조회를 돌며 행마다 시작 이후 경과 시간을 재고, 상한을 넘으면 안쪽 반복자를 닫고(ORM Query의
생성기는 닫힐 때 결과와 서버 측 커서를 닫는다 — CLOSE, 커넥션과 트랜잭션은 그대로) WARNING을 남긴 뒤 StreamedReadTimeout을
던진다. 상한 안에서는 행을 그대로 넘기므로 응답과 나눠 읽는 메모리 동작은 같다. 경과 시간에는 첫 FETCH까지의 실행 시간과
호출자가 행을 처리하는 시간이 모두 든다(커넥션을 붙잡는 시간). 검사는 행 사이에서 하므로 전체 상한은 대략 상한 + FETCH
하나이고, 그 FETCH도 statement_timeout을 넘지 못한다.

상한은 database._STATEMENT_TIMEOUT_MS(같은 env, 같은 기본값)를 호출할 때 읽는다. 0 이하면 statement_timeout=0처럼 상한이 없다.
query는 아직 실행하지 않은 Query(.yield_per 적용)를 넘긴다 — 실행한 Result를 넘기면 실행 시간이 상한에서 빠진다.

쓰는 곳: 공개 조회 라우터(reliability multi-channel, efficiency score, cost trend, results stats)는 stream_rows_or_503으로 503을
돌려주고, insights_runner(collect_stats_for_window, run_once)는 stream_rows를 쓴다 — 예외는 호출자가 처리한다(run_once의
except → -1, stream-regenerate의 error 이벤트, regenerate 스레드는 run_once의 -1).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from typing import Optional, TypeVar

from fastapi import HTTPException

import database

logger = logging.getLogger(__name__)

_clock = time.monotonic  # 경과 시간의 시계 — 테스트가 바꿔 끼운다

T = TypeVar("T")


class StreamedReadTimeout(RuntimeError):
    """나눠 읽는 조회가 전체 상한을 넘어 중단됐다. rows는 호출자에게 넘긴 행 수다."""

    def __init__(self, what: str, *, elapsed_s: float, limit_s: float, rows: int) -> None:
        self.what = what
        self.elapsed_s = elapsed_s
        self.limit_s = limit_s
        self.rows = rows
        super().__init__(f"DB 조회가 {limit_s:g}초 상한을 넘어 중단했습니다: {what} ({elapsed_s:.1f}초, {rows}행)")


def default_timeout_ms() -> int:
    """database.py의 statement_timeout과 같은 값(DB_STATEMENT_TIMEOUT_MS, 기본 30000) — 호출할 때 읽는다."""
    return database._STATEMENT_TIMEOUT_MS


def _close(it: object) -> None:
    """안쪽 반복자를 닫는다. 닫다가 난 오류는 로그만 남긴다 — 상한 초과 예외를 가리지 않는다."""
    close = getattr(it, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        logger.warning("streamed read: closing the aborted read failed", exc_info=True)


def stream_rows(query: Iterable[T], *, what: str, timeout_ms: Optional[int] = None) -> Iterator[T]:
    """query의 행을 그대로 넘기되, 시작 이후 timeout_ms(기본 default_timeout_ms())를 넘으면 닫고 StreamedReadTimeout.

    what은 WARNING 로그와 예외 메시지에 들어가는 조회 이름이다(라우터는 "GET <경로> <파라미터>").
    """
    limit_s = (default_timeout_ms() if timeout_ms is None else timeout_ms) / 1000.0
    started = _clock()  # 실행(첫 next) 전에 잰다
    it = iter(query)
    rows = 0
    try:
        for row in it:
            if limit_s > 0:
                elapsed = _clock() - started
                if elapsed > limit_s:
                    _close(it)  # 서버 측 커서를 먼저 닫는다
                    logger.warning("streamed read over the %gs limit, aborted: %s (elapsed %.1fs, %d rows)",
                                   limit_s, what, elapsed, rows)
                    raise StreamedReadTimeout(what, elapsed_s=elapsed, limit_s=limit_s, rows=rows)
            rows += 1
            yield row
    finally:
        _close(it)  # 호출자가 중간에 멈추거나 예외가 나도 닫는다(끝까지 읽었으면 아무 일도 하지 않는다)


def stream_rows_or_503(query: Iterable[T], *, route: str, timeout_ms: Optional[int] = None) -> Iterator[T]:
    """공개 조회 라우터용 stream_rows — 상한을 넘으면 HTTPException(503, 짧은 detail). 로그에는 route와 경과 시간이 남는다."""
    try:
        yield from stream_rows(query, what=route, timeout_ms=timeout_ms)
    except StreamedReadTimeout as exc:
        raise HTTPException(
            status_code=503,
            detail=f"DB 조회가 {exc.limit_s:g}초 안에 끝나지 않아 중단했습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
