"""CP monthly usage-cap 429 is not retried; ordinary transient errors still are (v2.29.0).

2026-09-23 19:52 UTC: every Claude Platform on AWS call returned 429 rate_limit_error "You have reached
your API usage limits: your organization has crossed its monthly API usage threshold ...". The prober
loop retried it (RateLimitError / rate_limit patterns, 4 attempts) and the anthropic SDK retried each
attempt twice more — up to 12 requests per probe, ~1,600-1,700 log lines per hour. Now the usage cap
ends in one request and one error row, the CP probe client has no SDK retries, and the loop takes over
the transient retries the SDK used to do (408/409/429/5xx, connection errors).

No network: the real anthropic SDK talks to an httpx.MockTransport; results go to in-memory SQLite.
"""

import json
import logging
import sys
import types
from queue import Queue

import anthropic
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober
from parity import runner as parity_runner

CP_ID = "anthropic:claude-sonnet-5"
CP_NAME = "Anthropic Claude Sonnet 5 (US)"
CAP_MESSAGE = (
    "You have reached your API usage limits: your organization has crossed its monthly API usage "
    "threshold, set based on your organization's API tier. You will regain access on 2026-10-01 at 00:00 UTC."
)
CAP_BODY = {
    "type": "error",
    "error": {"type": "rate_limit_error", "message": CAP_MESSAGE,
              "details": {"error_code": "enforced_spend_limit_reached"}},
    "request_id": "req_test",
}
TRANSIENT_429_BODY = {
    "type": "error",
    "error": {"type": "rate_limit_error",
              "message": "Number of request tokens has exceeded your per-minute rate limit"},
}
OVERLOADED_BODY = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
SERVER_ERROR_BODY = {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}}
BAD_REQUEST_BODY = {"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: bad"}}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


SSE_OK = "".join([
    _sse("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 7, "output_tokens": 1}}}),
    _sse("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "Hi"}}),
    _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 2}}),
    _sse("message_stop", {"type": "message_stop"}),
])


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(models.ProbeRun(prompt="p", status="running", is_auto=1))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(prober, "PROBE_WALL_CLOCK_S", 30.0)
    monkeypatch.setattr(prober, "_RETRY_BACKOFFS", (0, 0, 0))


def _cp_client(monkeypatch, responses, *, max_retries=0):
    """Real SDK client over a scripted transport; returns the list of requests it received."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = responses.pop(0) if len(responses) > 1 else responses[0]
        if isinstance(item, Exception):
            raise item
        status, body = item
        if status == 200:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        return httpx.Response(status, json=body)

    client = anthropic.Anthropic(
        api_key="sk-ant-test", base_url="https://cp.test", max_retries=max_retries,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(prober, "_get_anthropic_probe_client", lambda: client)
    return requests


def _probe(db, model_id=CP_ID, model_name=CP_NAME, client=None):
    q: Queue = Queue()
    prober._probe_single_model(client, model_id, model_name, "hi", 0.1, 64, 1, q, 1, db, "chat-short")
    return db.query(models.ProbeResult).filter(models.ProbeResult.model_id == model_id).all()


# --- detection -----------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    (f"RateLimitError: Error code: 429 - {CAP_BODY}", True),
    ("Error code: 429 - You have reached your specified workspace API usage limits.", True),
    ("details: {'error_code': 'enforced_spend_limit_reached'}", True),
    (f"RateLimitError: Error code: 429 - {TRANSIENT_429_BODY}", False),
    ("ThrottlingException: Too many requests, please wait before trying again.", False),
    ("RateLimitError: Error code: 429 - Rate limit reached for requests", False),
    ("InternalServerError: Error code: 529 - overloaded_error", False),
])
def test_usage_cap_detection_is_specific_to_the_quota_message(text, expected):
    assert prober._is_usage_cap_error(text) is expected


# --- CP path, real SDK over a mock transport ----------------------------------------

def test_cp_usage_cap_429_is_one_request_and_one_error_row(monkeypatch, db, caplog):
    requests = _cp_client(monkeypatch, [(429, CAP_BODY)])

    with caplog.at_level(logging.WARNING, logger="prober"):
        rows = _probe(db)

    assert len(requests) == 1  # no SDK retry, no prober-loop retry
    [row] = rows
    assert row.status == "error"
    assert row.error_message.startswith("Unexpected: Error code: 429 - ")
    assert "monthly API usage threshold" in row.error_message
    assert row.category == "chat-short"
    # one warning line, no traceback and no "Retryable error" lines
    assert not [r for r in caplog.records if "Retryable error" in r.getMessage()]
    [warning] = [r for r in caplog.records if "usage cap reached" in r.getMessage()]
    assert warning.levelno == logging.WARNING and warning.exc_info is None


@pytest.mark.parametrize("status, body", [
    (429, TRANSIENT_429_BODY),   # ordinary rate limit — retried as before
    (529, OVERLOADED_BODY),      # overloaded — retried as before
    (500, SERVER_ERROR_BODY),    # 5xx — the SDK used to retry it; now the loop does
    (408, SERVER_ERROR_BODY),
    (409, SERVER_ERROR_BODY),
])
def test_cp_transient_errors_are_still_retried_by_the_probe_loop(monkeypatch, db, status, body):
    requests = _cp_client(monkeypatch, [(status, body), (200, SSE_OK)])

    [row] = _probe(db)

    assert len(requests) == 2
    assert row.status == "success"
    assert (row.output_text, row.input_tokens, row.output_tokens, row.stop_reason) == ("Hi", 7, 2, "end_turn")


def test_cp_connection_error_is_retried_by_the_probe_loop(monkeypatch, db):
    requests = _cp_client(monkeypatch, [httpx.ConnectError("connection refused"), (200, SSE_OK)])

    [row] = _probe(db)

    assert len(requests) == 2
    assert row.status == "success"


def test_cp_persistent_transient_429_uses_every_loop_attempt(monkeypatch, db):
    requests = _cp_client(monkeypatch, [(429, TRANSIENT_429_BODY)])

    [row] = _probe(db)

    assert len(requests) == len(prober._RETRY_BACKOFFS) + 1  # 4 attempts x 1 request (no SDK multiplier)
    assert row.status == "error" and "per-minute rate limit" in row.error_message


def test_cp_client_error_is_not_retried(monkeypatch, db):
    requests = _cp_client(monkeypatch, [(400, BAD_REQUEST_BODY)])

    [row] = _probe(db)

    assert len(requests) == 1
    assert row.status == "error"


# --- other paths -----------------------------------------------------------------

class _FakeOpenAI:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0
        self.responses = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, Exception):
            raise item
        return item


class RateLimitError(Exception):
    pass


class InternalServerError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.status_code = 500


def test_usage_cap_message_is_not_retried_on_openai_path_either(monkeypatch, db):
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    client = _FakeOpenAI(RateLimitError(f"Error code: 429 - {CAP_MESSAGE}"))
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: client)

    [row] = _probe(db, "openai:us-east-1:openai.gpt-5.4", "OpenAI GPT 5.4 (us-east-1)")

    assert client.calls == 1
    assert row.status == "error"


def test_non_cp_5xx_retry_behaviour_is_unchanged(monkeypatch, db):
    """The CP status-code fallback applies only to anthropic:* — OpenAI 500 stays unretried (v2.28.2)."""
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    client = _FakeOpenAI(InternalServerError("Error code: 500 - {}"))
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: client)

    [row] = _probe(db, "openai:us-east-1:openai.gpt-5.4", "OpenAI GPT 5.4 (us-east-1)")

    assert client.calls == 1
    assert row.status == "error"


# --- client scoping --------------------------------------------------------------------

@pytest.fixture()
def recorded_anthropic(monkeypatch):
    created = []

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    monkeypatch.setattr(prober, "_anthropic_client_cache", None)
    monkeypatch.setattr(prober, "_anthropic_probe_client_cache", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_fake")
    monkeypatch.delenv("ANTHROPIC_AWS_REGION", raising=False)
    return created


def test_probe_client_has_no_sdk_retries_and_shared_client_keeps_sdk_defaults(recorded_anthropic):
    probe_client = prober._get_anthropic_probe_client()
    assert prober._get_anthropic_probe_client() is probe_client  # cached
    shared = prober._get_anthropic_client()

    assert probe_client is not shared
    assert probe_client.kwargs["max_retries"] == 0
    assert "max_retries" not in shared.kwargs  # Comparison Lab / parity keep the SDK default (2)
    for client in (probe_client, shared):
        assert client.kwargs["base_url"] == "https://aws-external-anthropic.us-east-2.api.aws"
        assert client.kwargs["default_headers"] == {"anthropic-workspace-id": "wrkspc_fake"}
        assert client.kwargs["api_key"] == "sk-ant-fake"


def test_parity_messages_surface_keeps_the_sdk_default_client(monkeypatch, recorded_anthropic):
    seen = []
    monkeypatch.setattr(parity_runner, "probe_messages", lambda client, actual_id, feature: seen.append(client))

    parity_runner._execute(CP_ID, "messages", "basic")

    [client] = seen
    assert client is prober._get_anthropic_client()
    assert "max_retries" not in client.kwargs
