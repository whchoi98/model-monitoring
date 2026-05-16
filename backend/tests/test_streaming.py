"""SSE streaming 헬퍼 단위 테스트 (외부 의존성 없음)."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent.streaming import sse_event, simulate_streaming, stream_with_final


def test_sse_event_format():
    out = sse_event("delta", {"text": "안녕"})
    assert out.startswith("event: delta\ndata: ")
    assert out.endswith("\n\n")
    # JSON 파싱 가능
    body = out.split("data: ", 1)[1].rstrip("\n")
    assert json.loads(body) == {"text": "안녕"}


@pytest.mark.asyncio
async def test_simulate_streaming_chunks_text():
    text = "ABCDEFGHIJ" * 6  # 60자
    chunks = []
    async for chunk in simulate_streaming(text, chunk_size=20, delay_ms=0):
        chunks.append(chunk)
    assert len(chunks) == 3  # 20*3=60
    # 각 청크는 delta 이벤트
    for c in chunks:
        assert c.startswith("event: delta\ndata: ")
    # 텍스트 누적이 입력과 일치
    combined = "".join(json.loads(c.split("data: ", 1)[1].rstrip("\n"))["text"] for c in chunks)
    assert combined == text


@pytest.mark.asyncio
async def test_stream_with_final_emits_on_success():
    async def inner():
        yield sse_event("delta", {"text": "x"})
        yield sse_event("delta", {"text": "y"})

    chunks = []
    async for c in stream_with_final(inner(), label="t"):
        chunks.append(c)
    assert any("event: final" in c for c in chunks)
    final = next(c for c in chunks if "event: final" in c)
    payload = json.loads(final.split("data: ", 1)[1].rstrip("\n"))
    assert payload["ok"] is True


@pytest.mark.asyncio
async def test_stream_with_final_emits_on_exception():
    async def inner():
        yield sse_event("delta", {"text": "x"})
        raise RuntimeError("boom")

    chunks = []
    async for c in stream_with_final(inner(), label="t"):
        chunks.append(c)
    final = next(c for c in chunks if "event: final" in c)
    payload = json.loads(final.split("data: ", 1)[1].rstrip("\n"))
    assert payload["ok"] is False
    assert payload["error"] == "boom"
    assert payload["type"] == "RuntimeError"


# pytest-asyncio가 없으면 자동 skip되도록 fallback.
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: async test")


# fallback runner: pytest-asyncio 없으면 직접 asyncio.run.
def _maybe_run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
