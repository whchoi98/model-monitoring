"""Claude Sonnet 5.5, OpenAI GPT 6.1 Sol, 서울 In-Region Opus 5 / Sonnet 5 카탈로그 편입 (v2.32.0).

실측 근거 (2026-09-30, 운영 자격증명):
- 서울 in-region: ap-northeast-2 list-foundation-models가 anthropic.claude-opus-5 / anthropic.claude-sonnet-5를
  ON_DEMAND로 표시. converse_stream, converse, invoke_model, invoke_model_with_response_stream 200,
  temperature 400. CountTokens는 두 FM id 모두 ValidationException "The provided model doesn't support
  counting tokens"(관찰만, 결정 D9).
- 키 스킴 "bedrock:<aws-region>:<Bedrock FM id>" — client 리전은 키의 리전, modelId는 접두를 벗긴 FM id.
  한쪽만 고치면 리전 오라우팅(us-east-1 폴백)이나 ValidationException이 조용히 생긴다(계획 위험 1).
No network: Bedrock/SDK clients are fakes; probe rows go to an in-memory SQLite DB.
"""

from queue import Queue

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober

_OPUS5_SEOUL = "bedrock:ap-northeast-2:anthropic.claude-opus-5"
_SONNET5_SEOUL = "bedrock:ap-northeast-2:anthropic.claude-sonnet-5"


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


class _RecordingBedrockClient:
    """converse_stream(**kwargs)를 기록하고 정상 종료 스트림을 돌려주는 가짜 bedrock-runtime client."""

    def __init__(self):
        self.calls: list[dict] = []

    def converse_stream(self, **kwargs):
        self.calls.append(kwargs)
        return {"stream": iter([
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"delta": {"text": "OK"}}},
            {"messageStop": {"stopReason": "end_turn"}},
            {"metadata": {"usage": {"inputTokens": 16, "outputTokens": 4}, "metrics": {"latencyMs": 500}}},
        ])}


# ---------------------------------------------------------------- _bedrock_target (키 → 리전, modelId)

@pytest.mark.parametrize("key, expected", [
    (_OPUS5_SEOUL, ("ap-northeast-2", "anthropic.claude-opus-5")),
    (_SONNET5_SEOUL, ("ap-northeast-2", "anthropic.claude-sonnet-5")),
    # split(":", 2) — FM id 안의 ':'(…-v1:0)는 보존
    ("bedrock:ap-northeast-2:anthropic.claude-haiku-4-5-20251001-v1:0",
     ("ap-northeast-2", "anthropic.claude-haiku-4-5-20251001-v1:0")),
    # CRIS 프로파일은 기존 동작 그대로 — 리전은 접두, modelId는 키 그대로
    ("global.anthropic.claude-sonnet-5-5", ("ap-northeast-2", "global.anthropic.claude-sonnet-5-5")),
    ("us.anthropic.claude-opus-5", ("us-east-1", "us.anthropic.claude-opus-5")),
    ("us.amazon.nova-2-lite-v1:0", ("us-east-1", "us.amazon.nova-2-lite-v1:0")),
])
def test_bedrock_target_resolves_region_and_model_id(key, expected):
    assert prober._bedrock_target(key) == expected
    assert prober._get_region_for_model(key) == expected[0]


@pytest.mark.parametrize("broken", ["bedrock:", "bedrock:ap-northeast-2", "bedrock::x", "bedrock:ap-northeast-2:"])
def test_broken_inregion_key_falls_back_without_raising(broken):
    # 제출 루프에서 예외가 나면 사이클 전체가 failed — 깨진 키는 폴백해 오류 행 하나로 끝나야 한다.
    assert prober._bedrock_target(broken) == ("us-east-1", broken)
    assert prober._get_region_for_model(broken) == "us-east-1"


def test_is_bedrock_inregion_only_matches_the_bedrock_prefix():
    assert prober.BEDROCK_INREGION_PREFIX == "bedrock:"
    assert prober._is_bedrock_inregion(_OPUS5_SEOUL) is True
    for key in ("global.anthropic.claude-opus-5", "us.anthropic.claude-opus-5",
                "anthropic:claude-opus-5", "openai:us-east-1:openai.gpt-6.1-sol"):
        assert prober._is_bedrock_inregion(key) is False, key


# ---------------------------------------------------------------- 서울 in-region 정적 등록

def test_seoul_inregion_channels_registered_with_region_code_labels():
    # 라벨은 DB model_name에 영구 기록 — 채널 표기는 OpenAI 인리전처럼 소문자 리전 코드.
    assert prober.AVAILABLE_MODELS[_OPUS5_SEOUL] == "Bedrock Claude Opus 5 (ap-northeast-2)"
    assert prober.AVAILABLE_MODELS[_SONNET5_SEOUL] == "Bedrock Claude Sonnet 5 (ap-northeast-2)"
    # 기존 Global/US 채널은 그대로
    assert prober.AVAILABLE_MODELS["global.anthropic.claude-opus-5"] == "Bedrock Claude Opus 5 (Global)"
    assert prober.AVAILABLE_MODELS["us.anthropic.claude-sonnet-5"] == "Bedrock Claude Sonnet 5 (US)"
    inregion = [k for k in prober.AVAILABLE_MODELS if k.startswith("bedrock:")]
    assert inregion == [_OPUS5_SEOUL, _SONNET5_SEOUL]


def test_seoul_inregion_keys_suppress_temperature():
    # temperature 400 실측 — _REASONING_MODEL_PATTERNS의 "opus-5"/"sonnet-5"가 키 전체에 substring으로 걸린다.
    assert prober._is_reasoning_model(_OPUS5_SEOUL) is True
    assert prober._is_reasoning_model(_SONNET5_SEOUL) is True


# ---------------------------------------------------------------- 호출 경로가 리전과 FM id를 함께 푼다

def test_dashboard_probe_sends_stripped_fm_id_and_records_the_key(db):
    client = _RecordingBedrockClient()
    q: Queue = Queue()
    prober._probe_single_model(client, _OPUS5_SEOUL, "Bedrock Claude Opus 5 (ap-northeast-2)",
                               "hi", 0.1, 64, 1, q, 1, db, "chat-short")

    [kwargs] = client.calls
    assert kwargs["modelId"] == "anthropic.claude-opus-5"
    assert "temperature" not in kwargs["inferenceConfig"]
    [row] = db.query(models.ProbeResult).all()
    assert (row.status, row.model_id, row.model_name) == (
        "success", _OPUS5_SEOUL, "Bedrock Claude Opus 5 (ap-northeast-2)")
    # SSE 이벤트도 채널 키 그대로
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert events and all(f'"model_id": "{_OPUS5_SEOUL}"' in ev for ev in events)


def test_cris_probe_model_id_is_unchanged(db):
    client = _RecordingBedrockClient()
    prober._probe_single_model(client, "global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)",
                               "hi", 0.1, 64, 1, Queue(), 1, db, "chat-short")
    assert client.calls[0]["modelId"] == "global.anthropic.claude-sonnet-5"


def test_comparison_lab_uses_key_region_and_stripped_fm_id(monkeypatch):
    client = _RecordingBedrockClient()
    regions: list[str] = []
    monkeypatch.setattr(prober, "_get_bedrock_client", lambda region: regions.append(region) or client)

    prober._compare_single_model(_SONNET5_SEOUL, "hi", 64, 0.1, Queue())

    assert regions == ["ap-northeast-2"]
    assert client.calls[0]["modelId"] == "anthropic.claude-sonnet-5"
    assert "temperature" not in client.calls[0]["inferenceConfig"]


@pytest.mark.parametrize("surface, probe_attr", [("converse", "probe_converse"), ("invoke_model", "probe_invoke_model")])
def test_parity_execute_uses_key_region_and_stripped_fm_id(monkeypatch, surface, probe_attr):
    from parity import runner
    from parity.probes import ProbeOutcome

    sentinel = object()
    regions: list[str] = []
    seen: list[tuple] = []
    monkeypatch.setattr(prober, "_get_bedrock_client", lambda region: regions.append(region) or sentinel)
    monkeypatch.setattr(runner, probe_attr,
                        lambda client, model_id, feature: seen.append((client, model_id, feature))
                        or ProbeOutcome("supported"))

    outcome = runner._execute(_SONNET5_SEOUL, surface, "basic")

    assert outcome.status == "supported"
    assert regions == ["ap-northeast-2"]
    assert seen == [(sentinel, "anthropic.claude-sonnet-5", "basic")]


def test_parity_seoul_rows_skip_mantle_surface():
    # 결정 D1 — messages_mantle은 us-east-1에 같은 FM id를 보내 Global 행과 중복이다.
    from parity.catalog import is_applicable, surfaces_for

    assert surfaces_for(_OPUS5_SEOUL) == ["converse", "invoke_model"]
    assert surfaces_for(_SONNET5_SEOUL) == ["converse", "invoke_model"]
    assert surfaces_for("bedrock:ap-northeast-2:amazon.nova-2-lite-v1:0") == ["converse"]
    assert is_applicable("basic", "messages_mantle", _OPUS5_SEOUL) is False


def test_optimize_prompt_target_normalizes_inregion_key():
    from routers.prompts import _normalize_target_model_id

    assert _normalize_target_model_id(_OPUS5_SEOUL) == "anthropic.claude-opus-5"
    assert _normalize_target_model_id("bedrock:ap-northeast-2:anthropic.claude-haiku-4-5-20251001-v1:0") == (
        "anthropic.claude-haiku-4-5-20251001-v1:0")
    # 기존 규칙 불변
    assert _normalize_target_model_id("global.anthropic.claude-opus-4-7") == "anthropic.claude-opus-4-7"
    assert _normalize_target_model_id("us.amazon.nova-2-lite-v1:0") == "amazon.nova-2-lite-v1:0"
    assert _normalize_target_model_id("anthropic.claude-sonnet-5") == "anthropic.claude-sonnet-5"
