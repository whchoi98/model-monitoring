"""Parity run OpenAI client scope (v2.28.2 review fix).

The prober's probe client drops SDK retries (max_retries=0, read 60 s) as a stream-hang fix for the
dashboard cycle. The parity run must not inherit that: parity.engine.classify_error turns 429/5xx,
connection errors and timeouts into 'broken', so without the SDK retries a transient error would
show up as a broken matrix cell and a change banner. Parity therefore builds its own client with the
SDK defaults (no timeout / max_retries arguments, same construction path as before v2.28.2) and only
shares the credential choice with the prober.
No network: the openai module is a fake that records constructor kwargs.
"""

import sys
import types

import pytest

import prober
from parity import runner

MANTLE_URL = "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
ONE_P_URL = "https://api.openai.com/v1"


@pytest.fixture()
def created_clients(monkeypatch):
    created = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    # 실제 SDK 표면과 맞춘다 — prober 프로브 클라이언트는 openai.Timeout을 import한다(v2.28.2).
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI, Timeout=lambda *a, **k: (a, k)))
    monkeypatch.setattr(prober, "_openai_client_cache", {})
    monkeypatch.setattr(runner, "_openai_client_cache", {})
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_1P_API_KEY", "sk-proj-fake")
    monkeypatch.delenv("OPENAI_1P_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", MANTLE_URL)
    return created


@pytest.mark.parametrize(
    "surface, probe_attr",
    [("responses", "probe_responses"), ("chat_completions", "probe_chat_completions")],
)
def test_parity_openai_surfaces_keep_sdk_default_retries_and_timeout(
    monkeypatch, created_clients, surface, probe_attr
):
    seen = []

    def fake_probe(client, actual_id, feature):
        seen.append((client, actual_id, feature))
        return "outcome"

    monkeypatch.setattr(runner, probe_attr, fake_probe)

    assert runner._execute("openai:us-east-1:openai.gpt-5.4", surface, "basic") == "outcome"

    [(client, actual_id, feature)] = seen
    assert (actual_id, feature) == ("openai.gpt-5.4", "basic")
    # SDK 기본값 — timeout/max_retries 인자를 넘기지 않는다(v2.28.2 이전과 같은 생성 경로).
    assert client.kwargs == {"api_key": "ABSK-fake", "base_url": MANTLE_URL}

    # prober 프로브 클라이언트는 여전히 hang 대책 설정이고, 패리티와 다른 객체다.
    probe_client = prober._get_openai_client(MANTLE_URL)
    assert probe_client is not client
    assert probe_client.kwargs["max_retries"] == 0
    assert "timeout" in probe_client.kwargs


def test_parity_openai_client_is_cached_per_base_url_with_matching_credentials(created_clients):
    mantle = runner._parity_openai_client(MANTLE_URL)
    assert runner._parity_openai_client(MANTLE_URL) is mantle  # 캐시 — 재생성 없음
    runner._parity_openai_client(ONE_P_URL)

    assert [c.kwargs for c in created_clients] == [
        {"api_key": "ABSK-fake", "base_url": MANTLE_URL},  # Mantle bearer
        {"api_key": "sk-proj-fake", "base_url": ONE_P_URL},  # 1P platform 키
    ]
