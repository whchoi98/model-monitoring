"""Shared streaming watchdog (v2.28.2) — gptbench와 prober가 같은 모듈을 쓰는지, botocore 폴백.

No network: sockets and streams are fakes.
"""

import socket
import threading
import time
import types

import stream_watchdog


def test_gptbench_reexports_the_shared_watchdog():
    """gptbench는 공용 모듈을 재노출만 한다 — 두 구현이 따로 드리프트하지 않는다."""
    import gptbench

    assert gptbench._CallWatchdog is stream_watchdog.CallWatchdog
    assert gptbench._abort_stream is stream_watchdog.abort_stream


def test_abort_stream_shuts_down_botocore_eventstream_socket_before_close():
    """Bedrock converse_stream(EventStream)은 httpx response가 없어 urllib3 연결 소켓으로 폴백한다.

    close만으로는 다른 스레드의 블로킹 recv가 read timeout까지 깨지 않는다(urllib3도 동일, 로컬 실험).
    """
    calls = []

    class Sock:
        def shutdown(self, how):
            calls.append(("shutdown", how))

    raw = types.SimpleNamespace(_connection=types.SimpleNamespace(sock=Sock()))

    class EventStream:
        _raw_stream = raw

        def close(self):
            calls.append(("close", None))

    stream_watchdog.abort_stream(EventStream())
    assert calls == [("shutdown", socket.SHUT_RDWR), ("close", None)]


def test_abort_stream_prefers_httpx_socket_and_tolerates_missing_parts():
    calls = []

    class Sock:
        def __init__(self, name):
            self.name = name

        def shutdown(self, how):
            calls.append(self.name)

    class NS:
        def get_extra_info(self, name):
            return Sock("httpx") if name == "socket" else None

    class Both:
        response = types.SimpleNamespace(extensions={"network_stream": NS()})
        _raw_stream = types.SimpleNamespace(_connection=types.SimpleNamespace(sock=Sock("urllib3")))

        def close(self):
            calls.append("close")

    stream_watchdog.abort_stream(Both())
    assert calls == ["httpx", "close"]

    # 소켓도 close도 없는 객체(예: list iterator)도 예외 없이 지나간다.
    stream_watchdog.abort_stream(iter([]))


def test_watchdog_aborts_attached_stream_on_expiry():
    closed = threading.Event()

    class Stream:
        def close(self):
            closed.set()

    wd = stream_watchdog.CallWatchdog(0.05)
    wd.start()
    wd.attach(Stream())
    assert closed.wait(2.0)
    assert wd.fired


def test_watchdog_attach_after_expiry_aborts_immediately():
    closed = []

    class Stream:
        def close(self):
            closed.append(True)

    wd = stream_watchdog.CallWatchdog(0.01)
    wd.start()
    deadline = time.monotonic() + 2.0
    while not wd.fired and time.monotonic() < deadline:
        time.sleep(0.01)
    assert wd.fired
    wd.attach(Stream())
    assert closed == [True]
