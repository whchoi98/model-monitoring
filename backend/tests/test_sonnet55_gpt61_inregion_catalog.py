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


# ---------------------------------------------------------------- Claude Sonnet 5.5

# 2026-09-30 CP on AWS /v1/models 실측 순서 그대로 — 점 버전(sonnet-5-5, opus-5-5, fable-5-1)이 먼저 온다.
_CP_MODEL_IDS_20260930 = [
    "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5",
    "claude-fable-5", "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
    "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929",
]


def test_bedrock_sonnet55_global_and_no_in_region():
    assert prober.AVAILABLE_MODELS["global.anthropic.claude-sonnet-5-5"] == "Bedrock Claude Sonnet 5.5 (Global)"
    # 2026-09-30에는 us. 프로파일이 없었고 v2.33.0(2026-10-07)에 생겨 US 채널을 더했다(test_haiku55_catalog.py).
    # Seoul in-region은 여전히 ON_DEMAND 미지원(INFERENCE_PROFILE 전용).
    assert "bedrock:ap-northeast-2:anthropic.claude-sonnet-5-5" not in prober.AVAILABLE_MODELS
    assert prober._is_reasoning_model("global.anthropic.claude-sonnet-5-5") is True  # temperature 400
    # 정적 순서: Sonnet 5.5는 Sonnet 5 바로 앞
    keys = list(prober.AVAILABLE_MODELS)
    assert keys.index("global.anthropic.claude-sonnet-5-5") + 1 == keys.index("global.anthropic.claude-sonnet-5")


def test_cp_target_sonnet55_listed_right_before_sonnet5():
    substrings = [s for s, _ in prober._ANTHROPIC_TARGETS]
    assert substrings.index("sonnet-5-5") + 1 == substrings.index("sonnet-5")
    assert dict(prober._ANTHROPIC_TARGETS)["sonnet-5-5"] == "Anthropic Claude Sonnet 5.5 (US)"


def test_cp_discovery_with_20260930_model_order_labels_every_id_correctly():
    """claude-sonnet-5-5가 맨 앞에 와도 Sonnet 5 라벨은 claude-sonnet-5에 붙어야 한다."""
    matched = {s: prober._match_anthropic_model(s, _CP_MODEL_IDS_20260930) for s, _ in prober._ANTHROPIC_TARGETS}
    assert matched["sonnet-5-5"] == "claude-sonnet-5-5"
    assert matched["sonnet-5"] == "claude-sonnet-5"
    assert matched["opus-5"] == "claude-opus-5"
    assert matched["opus-5-5"] == "claude-opus-5-5"
    assert matched["fable-5"] == "claude-fable-5"
    # haiku-5-5는 v2.33.0 타깃 — 2026-09-30 목록에는 아직 없어 None(등록 skip)이 맞다
    assert matched.pop("haiku-5-5") is None
    assert None not in matched.values()
    assert len(set(matched.values())) == len(matched)
    # 날짜 서픽스가 붙은 미래 id도 자기 타깃에 매칭된다
    assert prober._match_anthropic_model("sonnet-5-5", ["claude-sonnet-5-5-20261001"]) == "claude-sonnet-5-5-20261001"


# ---------------------------------------------------------------- OpenAI GPT 6.1 Sol

_GPT61_SOL_KEYS = [
    "openai:global:global.openai.gpt-6.1-sol",
    "openai:us:us.openai.gpt-6.1-sol",
    "openai:us-east-1:openai.gpt-6.1-sol",
]


def test_gpt61_sol_is_the_first_openai_spec():
    assert prober._OPENAI_MODEL_SPECS[0] == (
        "BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", "GPT 6.1 Sol", ("global", "us", "us-east-1"))


def test_gpt61_sol_registers_exactly_three_channels(monkeypatch):
    """Global CRIS + US CRIS + Mantle us-east-1 — us-east-2/us-west-2는 env가 있어도 미등록(404)."""
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in (
        ("OPENAI_GLOBAL_BASE_URL", "https://gl/openai/v1"),
        ("OPENAI_US_BASE_URL", "https://us/openai/v1"),
        ("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1"),
        ("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1"),
        ("OPENAI_US_WEST_2_BASE_URL", "https://w2/openai/v1"),
    ):
        monkeypatch.setenv(env, url)
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", "openai.gpt-6.1-sol")
    prober._register_openai_models()

    keys = sorted(k for k in prober.AVAILABLE_MODELS if "gpt-6.1-sol" in k)
    assert keys == sorted(_GPT61_SOL_KEYS)
    # 라벨은 DB model_name에 영구 기록 — frontend MODEL_COLORS 키와 바이트 단위로 일치해야 함.
    assert prober.AVAILABLE_MODELS["openai:global:global.openai.gpt-6.1-sol"] == "OpenAI GPT 6.1 Sol (Global)"
    assert prober.AVAILABLE_MODELS["openai:us:us.openai.gpt-6.1-sol"] == "OpenAI GPT 6.1 Sol (US)"
    assert prober.AVAILABLE_MODELS["openai:us-east-1:openai.gpt-6.1-sol"] == "OpenAI GPT 6.1 Sol (us-east-1)"
    for region in ("us-east-2", "us-west-2"):
        assert f"openai:{region}:openai.gpt-6.1-sol" not in prober.AVAILABLE_MODELS


def test_gpt61_sol_is_skipped_without_its_model_id_env(monkeypatch):
    # env 누락이면 3채널이 조용히 빠진다 — CDK가 두 스택 모두에 주입해야 하는 이유(계획 위험 2).
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_GLOBAL_BASE_URL", "https://gl/openai/v1")
    monkeypatch.delenv("BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", raising=False)
    prober._register_openai_models()
    assert not [k for k in prober.AVAILABLE_MODELS if "gpt-6.1-sol" in k]


def test_gpt61_sol_does_not_collide_with_gpt6_sol_or_gpt5_markers():
    from parity.catalog import is_reasoning_capable

    for key in _GPT61_SOL_KEYS:
        assert "gpt-6-sol" not in key and "gpt-5" not in key
        assert is_reasoning_capable(key) is False  # reasoning_tokens 0 (2026-09-30)
