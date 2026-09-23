"""스트리밍 호출 wall-clock watchdog — GPT on AWS 벤치와 prober 공용 (v2.28.2).

v2.28.0에서 gptbench.py에 넣었던 `_abort_stream`/`_CallWatchdog`를 동작 그대로 옮겼다.
2026-09-23 장애: Bedrock Mantle us-east-1 GPT-5.6 Sol Responses 스트림이 200을 준 뒤 멈추거나
드문드문 흘러 청크 간 read timeout이 끝내 발동하지 않았고, 프로브 스레드 하나가 AutoProber
태스크 전체를 30~46분 붙잡았다. 같은 계열의 멈춤을 벤치는 이미 v2.28.0에서 막았으므로 prober도
같은 메커니즘을 쓴다.

SDK timeout은 청크 사이 대기 상한일 뿐 호출 전체 상한이 아니다 — 무언가를 가끔씩이라도 보내는
스트림은 끝나지 않는다. `CallWatchdog`은 wall-clock 상한이 지나면 붙어 있는 스트림을 끊는
`threading.Timer`다.
"""

from __future__ import annotations

import socket
import threading


def _stream_socket(stream):
    """SDK 스트림 아래의 소켓. 노출되지 않으면 None.

    - httpx 기반 SDK 스트림(openai `Stream`, anthropic `MessageStream`): `stream.response`의
      httpcore `network_stream` — v2.28.0 gptbench 경로 그대로.
    - botocore `EventStream`(Bedrock `converse_stream`, v2.28.2 추가 폴백): `_raw_stream`이 urllib3
      `HTTPResponse`이고 스트리밍 본문은 `_connection`을 유지한다. httpx 경로에서 소켓을 못 찾을
      때만 시도하므로 httpx 스트림의 동작은 이전과 같다.
    """
    resp = getattr(stream, "response", None)
    ns = resp.extensions.get("network_stream") if resp is not None else None
    sock = ns.get_extra_info("socket") if ns is not None else None
    if sock is None:
        conn = getattr(getattr(stream, "_raw_stream", None), "_connection", None)
        sock = getattr(conn, "sock", None)
    return sock


def abort_stream(stream) -> None:
    """watchdog 만료 시 열린 스트림을 즉시 끊는다 (best effort).

    stream.close()만으로는 부족하다: 다른 스레드가 recv()에 블로킹돼 있으면 Linux에서 소켓
    close는 그 recv를 깨우지 않아 read timeout까지 더 기다린다 (2026-09-23 로컬 실험 — close만:
    10s read timeout까지 대기, shutdown 선행: 즉시 ReadError, 평문·TLS 동일. urllib3/botocore도
    같다 — close만: read timeout 뒤 ReadTimeoutError, shutdown 선행: 즉시 ProtocolError). 그래서
    소켓을 먼저 shutdown(SHUT_RDWR)해 블로킹 read를 깨운 뒤 close한다.
    """
    try:
        sock = _stream_socket(stream)
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001 — 이미 닫힘/소켓 미노출 등은 close로 폴백
        pass
    try:
        stream.close()
    except Exception:  # noqa: BLE001
        pass


class CallWatchdog:
    """호출 1회의 wall-clock 상한 — v2.28.0 gptbench 하드닝, v2.28.2부터 prober와 공용.

    OpenAI 클라이언트 timeout은 httpx read timeout(청크 간 대기 상한)일 뿐이라, 이벤트가 드문드문
    계속 오면 호출 전체는 끝없이 길어진다 — 2026-09-16~17 GPT 5.4 us-east-2 벤치 워밍업 1회가
    ~3,540s. 타이머는 호출 시작부터 돌고, 만료되면 열린 스트림을 끊는다. 스트림이 열리기 전(응답
    헤더 대기 중)에 만료되면 열리는 즉시 끊는다 — 헤더 대기 자체는 클라이언트 connect/read
    timeout이 상한이다. 호출을 대신 돌리는 별도 워커 스레드는 없다.

    `fired`는 abort 전에 lock 아래에서 켜지므로 abort가 던진 예외를 받은 쪽은 항상 fired=True를
    본다. 호출자는 만료 전에 종료 이벤트를 받은 결과를 유지한다("done and fired" = abort가 스트림
    꼬리만 끊음).
    """

    def __init__(self, limit_s: float):
        self.limit_s = limit_s
        self.fired = False
        self._stream = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(limit_s, self._fire)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.cancel()

    def attach(self, stream) -> None:
        with self._lock:
            self._stream = stream
            fired = self.fired
        if fired:
            abort_stream(stream)

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            stream = self._stream
        if stream is not None:
            abort_stream(stream)
