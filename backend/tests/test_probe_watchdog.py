"""Probe wall-clock watchdog (v2.28.2 hotfix) — prober 세 경로 + Comparison Lab + OpenAI 클라이언트.

2026-09-23 장애 재현 형태: 200 뒤 스트림이 멈추거나(hang) 드문드문 흐르면(trickle) 청크 간 read
timeout이 발동하지 않는다. watchdog이 상한에 스트림을 끊고 그 모델만 오류 행이 되어야 한다.
No network: SDK clients and streams are fakes; results go to an in-memory SQLite DB.
"""

import json
import sys
import threading
import time
import types
from queue import Queue

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober

CAP = 0.2
TIMEOUT_MSG = "WallClockTimeout: probe exceeded 0.2s wall-clock"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    run = models.ProbeRun(prompt="p", status="running", is_auto=1)
    session.add(run)
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def short_cap(monkeypatch):
    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", CAP)
    # 출력 예산 하한(max_tokens / 20 tok/s)이 짧은 테스트 상한을 덮지 않게 한다 — 별도 테스트로 검증.
    monkeypatch.setattr(prober, "_WALL_CLOCK_MIN_TPS", 1e9)
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")


# --- fakes -------------------------------------------------------------------

class _Ev:
    def __init__(self, type_, delta=None, response=None):
        self.type = type_
        self.delta = delta
        self.response = response


def _completed(input_tokens=12, output_tokens=5):
    usage = types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return _Ev("response.completed",
               response=types.SimpleNamespace(usage=usage, status="completed", incomplete_details=None))


class _HangingStream:
    """이벤트 몇 개 뒤 멈춘다 — close()(watchdog abort)가 와야 풀리며 실제 SDK처럼 읽기 오류를 던진다."""

    def __init__(self, head=None):
        self.closed = threading.Event()
        self.head = head if head is not None else [
            _Ev("response.created"), _Ev("response.output_text.delta", delta="partial")]

    def __iter__(self):
        yield from self.head
        # 테스트 안전판 10s — watchdog이 동작하지 않으면 여기서 끝까지 기다려 시간 assert가 실패한다.
        self.closed.wait(10)
        raise OSError("[Errno 9] Bad file descriptor")

    def close(self):
        self.closed.set()


class _TricklingStream:
    """이벤트를 끝없이 드문드문 흘리고 close()를 무시한다 — 소켓을 끊을 수 없는 스트림에서도
    이벤트마다의 만료 검사가 상한 근처에서 끊어야 한다."""

    def __init__(self, interval=0.03):
        self.interval = interval
        self.events = 0

    def __iter__(self):
        yield _Ev("response.created")
        while self.events < 1000:  # 안전판 ~30s
            time.sleep(self.interval)
            self.events += 1
            yield _Ev("response.output_text.delta", delta=".")


class _BufferedStream:
    """close() 뒤에도 버퍼에 남은 이벤트(completed 포함)를 끝까지 내보낸다."""

    def __init__(self):
        self.closed = False

    def __iter__(self):
        yield _Ev("response.output_text.delta", delta="late")
        yield _completed()

    def close(self):
        self.closed = True


class _FakeOpenAI:
    def __init__(self, *streams, create_delay=0.0):
        self.streams = list(streams)
        self.calls = 0
        self.create_delay = create_delay
        self.responses = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        assert kwargs["stream"] is True and "input" in kwargs  # payload 형태는 그대로
        self.calls += 1
        time.sleep(self.create_delay)
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _probe(db, model_id="openai:us-east-1:openai.gpt-5.6-sol", model_name="OpenAI GPT 5.6 Sol (us-east-1)",
           client=None):
    q: Queue = Queue()
    t0 = time.perf_counter()
    prober._probe_single_model(client, model_id, model_name, "hi", 0.1, 64, 1, q, 1, db, "chat-short")
    elapsed = time.perf_counter() - t0
    rows = db.query(models.ProbeResult).filter(models.ProbeResult.model_id == model_id).all()
    events = []
    while not q.empty():
        ev = q.get_nowait()
        events.append((ev.split("event: ", 1)[1].split("\n", 1)[0], json.loads(ev.split("data: ", 1)[1])))
    return rows, events, elapsed


# --- cap --------------------------------------------------------------------

def test_scheduled_presets_use_the_configured_cap_and_long_outputs_get_more(monkeypatch):
    """자동 사이클 프리셋(max_tokens ≤ 512)은 전부 PROBE_WALL_CLOCK_S 그대로 — 오류 문구 "90s"와
    auto_prober 모델 상한(+30s 여유)의 전제. 긴 출력의 수동 프로브/Comparison Lab만 늘어난다."""
    import auto_prober

    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", 90.0)
    monkeypatch.setattr(prober, "_WALL_CLOCK_MIN_TPS", 20.0)
    for preset in auto_prober.WORKLOAD_PRESETS:
        assert prober._wall_clock_limit(preset["max_tokens"]) == 90.0
    assert prober._wall_clock_limit(4096) == pytest.approx(204.8)  # /api/probes/run 최대
    assert prober._wall_clock_limit(8192) == pytest.approx(409.6)  # Comparison Lab 최대
    assert str(prober.WallClockTimeout(90.0)) == "WallClockTimeout: probe exceeded 90s wall-clock"


# --- OpenAI client ------------------------------------------------------------

def test_openai_client_has_no_sdk_retries_and_bounded_timeout(monkeypatch):
    """SDK 기본값(timeout 600s, max_retries 2) 대신 max_retries=0 + connect 10s / read 60s."""
    captured = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    # openai.Timeout(SDK 자체 타입)을 쓰는지 본다 — 3.x는 httpx2 기반이라 httpx.Timeout과 다르다.
    class FakeTimeout:
        def __init__(self, timeout, *, connect=None):
            self.read, self.connect = timeout, connect

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI, Timeout=FakeTimeout))
    monkeypatch.setattr(prober, "_openai_client_cache", {})
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_1P_API_KEY", "sk-proj-fake")
    monkeypatch.delenv("OPENAI_1P_BASE_URL", raising=False)

    prober._get_openai_client("https://e1/openai/v1")
    prober._get_openai_client("https://e1/openai/v1")  # 캐시 — 재생성 없음
    prober._get_openai_client("https://api.openai.com/v1")
    assert len(captured) == 2
    for kw in captured:
        assert kw["max_retries"] == 0
        timeout = kw["timeout"]
        assert isinstance(timeout, FakeTimeout)  # SDK 자체 타입 (httpx.Timeout 직접 사용 금지)
        assert (timeout.connect, timeout.read) == (10.0, 60.0)
    # 자격증명 분기는 그대로 (Mantle bearer vs 1P platform 키).
    assert [kw["api_key"] for kw in captured] == ["ABSK-fake", "sk-proj-fake"]


# --- OpenAI Responses path ------------------------------------------------------

def test_hanging_openai_stream_is_aborted_and_recorded_as_error_row(monkeypatch, db):
    stream = _HangingStream()
    client = _FakeOpenAI(stream)
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: client)

    rows, events, elapsed = _probe(db)

    assert stream.closed.is_set()  # watchdog이 실제로 스트림을 끊었다
    assert elapsed < 2.0  # 안전판(10s)이 아니라 상한(0.2s) 근처에서 풀린다
    [row] = rows
    assert (row.status, row.error_message) == ("error", TIMEOUT_MSG)
    assert row.category == "chat-short"
    assert client.calls == 1  # wall-clock 초과는 재시도하지 않는다
    assert [b["error"] for t, b in events if t == "error"] == [TIMEOUT_MSG]


def test_trickling_stream_is_cut_at_the_cap_even_if_close_is_ignored(monkeypatch, db):
    stream = _TricklingStream()
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeOpenAI(stream))

    rows, _, elapsed = _probe(db)

    assert elapsed < 2.0
    assert stream.events < 100  # 끝없이 흐르는 스트림을 상한 근처에서 멈췄다
    [row] = rows
    assert (row.status, row.error_message) == ("error", TIMEOUT_MSG)


def test_completed_stream_keeps_success_when_late_abort_cuts_the_tail(monkeypatch, db):
    """상한 안에 response.completed를 받은 뒤 스트림 꼬리 대기 중 watchdog이 끊어도 성공 유지."""
    stream = _HangingStream(head=[
        _Ev("response.created"), _Ev("response.output_text.delta", delta="Hello"), _completed(12, 5)])
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeOpenAI(stream))

    rows, events, elapsed = _probe(db)

    assert stream.closed.is_set()  # watchdog이 만료되어 꼬리를 끊었다
    assert elapsed < 2.0
    [row] = rows
    assert row.status == "success" and row.error_message is None
    assert (row.input_tokens, row.output_tokens, row.output_text, row.stop_reason) == (12, 5, "Hello", "end_turn")
    assert any(t == "result" for t, _ in events)


def test_completion_arriving_after_expiry_is_still_a_timeout(monkeypatch, db):
    """응답 헤더 대기 중 만료 → 스트림이 열리는 즉시 끊고, 버퍼에 남은 completed가 와도 오류 행."""
    stream = _BufferedStream()
    monkeypatch.setattr(prober, "_get_openai_client",
                        lambda base_url: _FakeOpenAI(stream, create_delay=CAP + 0.2))

    rows, _, _ = _probe(db)

    assert stream.closed
    [row] = rows
    assert (row.status, row.error_message) == ("error", TIMEOUT_MSG)


def test_normal_stream_is_unaffected_and_timer_is_cancelled(monkeypatch, db):
    events = [_Ev("response.output_text.delta", delta="ok"), _completed(3, 1)]
    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", 5.0)
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeOpenAI(iter(events)))

    before = threading.active_count()
    rows, _, elapsed = _probe(db)

    [row] = rows
    assert row.status == "success" and row.output_text == "ok"
    assert (row.input_tokens, row.output_tokens, row.stop_reason) == (3, 1, "end_turn")
    assert elapsed < 1.0  # 5s 상한을 기다리지 않는다
    # 취소된 타이머 스레드는 곧 종료된다 — 프로브마다 스레드가 쌓이지 않는다.
    deadline = time.monotonic() + 2.0
    while threading.active_count() > before and time.monotonic() < deadline:
        time.sleep(0.01)
    assert threading.active_count() <= before


def test_rate_limit_error_is_retried_by_the_probe_loop(monkeypatch, db):
    """SDK 재시도를 껐으므로(max_retries=0) 429는 prober 루프가 재시도한다 — OpenAI SDK의 str()은
    "Error code: 429 - …"뿐이라 타입명 RateLimitError로 매칭된다."""
    class RateLimitError(Exception):
        pass

    client = _FakeOpenAI(RateLimitError("Error code: 429 - {}"),
                         iter([_Ev("response.output_text.delta", delta="ok"), _completed(3, 1)]))
    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", 5.0)
    monkeypatch.setattr(prober, "_RETRY_BACKOFFS", (0, 0, 0))
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: client)

    rows, _, _ = _probe(db)

    assert client.calls == 2
    [row] = rows
    assert row.status == "success"


def test_retry_is_skipped_when_backoff_would_exceed_the_wall_clock_budget(monkeypatch, db):
    class RateLimitError(Exception):
        pass

    client = _FakeOpenAI(RateLimitError("Error code: 429 - {}"), iter([_completed()]))
    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", 1.0)
    monkeypatch.setattr(prober, "_RETRY_BACKOFFS", (5, 5, 5))  # 첫 backoff만으로 예산 초과
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: client)

    rows, _, elapsed = _probe(db)

    assert client.calls == 1
    assert elapsed < 1.0  # 5s backoff를 자지 않았다
    [row] = rows
    assert row.status == "error"
    assert row.error_message == "Unexpected: Error code: 429 - {}"


# --- Bedrock converse_stream path ------------------------------------------------

class _BedrockClient:
    def __init__(self, stream):
        self.stream = stream

    def converse_stream(self, **kwargs):
        return {"stream": self.stream}


def test_hanging_bedrock_stream_is_aborted_and_recorded_as_error_row(db):
    stream = _HangingStream(head=[{"messageStart": {"role": "assistant"}},
                                  {"contentBlockDelta": {"delta": {"text": "partial"}}}])
    rows, _, elapsed = _probe(db, "global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)",
                              client=_BedrockClient(stream))

    assert stream.closed.is_set() and elapsed < 2.0
    [row] = rows
    assert (row.status, row.error_message) == ("error", TIMEOUT_MSG)


def test_bedrock_stream_success_is_unchanged(monkeypatch, db):
    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", 5.0)
    events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": "Hi"}}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 7, "outputTokens": 2}, "metrics": {"latencyMs": 321}}},
    ]
    rows, _, _ = _probe(db, "global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)",
                        client=_BedrockClient(iter(events)))
    [row] = rows
    assert row.status == "success"
    assert (row.input_tokens, row.output_tokens, row.server_latency_ms, row.stop_reason, row.output_text) == (
        7, 2, 321, "end_turn", "Hi")


def test_bedrock_metadata_then_late_abort_keeps_success(db):
    """converse_stream의 마지막 이벤트(metadata)까지 받았으면 그 뒤 abort가 끊어도 성공."""
    stream = _HangingStream(head=[
        {"contentBlockDelta": {"delta": {"text": "Hi"}}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 7, "outputTokens": 2}, "metrics": {"latencyMs": 321}}},
    ])
    rows, _, _ = _probe(db, "global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)",
                        client=_BedrockClient(stream))
    assert stream.closed.is_set()
    [row] = rows
    assert row.status == "success" and row.output_tokens == 2


# --- Anthropic CP path ---------------------------------------------------------

class _AnthropicStream:
    def __init__(self):
        self.closed = threading.Event()
        self.text_stream = self._text()

    def _text(self):
        yield "partial"
        self.closed.wait(10)
        raise OSError("[Errno 9] Bad file descriptor")

    def get_final_message(self):  # pragma: no cover — 멈춘 스트림은 여기까지 오지 않는다
        raise AssertionError("must not be reached")

    def close(self):
        self.closed.set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_hanging_anthropic_stream_is_aborted_and_recorded_as_error_row(monkeypatch, db):
    stream = _AnthropicStream()
    fake = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: stream))
    # 대시보드 프로브는 SDK 재시도 0인 프로브 전용 CP 클라이언트를 쓴다 (v2.29.0).
    monkeypatch.setattr(prober, "_get_anthropic_probe_client", lambda: fake)

    rows, _, elapsed = _probe(db, "anthropic:claude-sonnet-5", "Anthropic Claude Sonnet 5 (US)")

    assert stream.closed.is_set() and elapsed < 2.0
    [row] = rows
    assert (row.status, row.error_message) == ("error", TIMEOUT_MSG)


# --- Comparison Lab -----------------------------------------------------------

def test_compare_path_reports_wall_clock_timeout(monkeypatch):
    stream = _HangingStream()
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeOpenAI(stream))
    q: Queue = Queue()

    t0 = time.perf_counter()
    prober._compare_single_model("openai:us-east-1:openai.gpt-5.6-sol", "hi", 64, 0.1, q)

    assert time.perf_counter() - t0 < 2.0
    assert stream.closed.is_set()
    parsed = []
    while not q.empty():
        ev = q.get_nowait()
        parsed.append((ev.split("event: ", 1)[1].split("\n", 1)[0], json.loads(ev.split("data: ", 1)[1])))
    [err] = [b for t, b in parsed if t == "error"]
    assert (err["status"], err["error"]) == ("error", TIMEOUT_MSG)
    assert not any(t == "result" for t, _ in parsed)
