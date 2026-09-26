"""Claude Opus 5.5 + OpenAI GPT 6 Sol/Luna 카탈로그 편입 (v2.27.0).

실측 근거 (2026-09-23, 운영 자격증명):
- Opus 5.5: Bedrock global.(Seoul) / us.(us-east-1) converse_stream 200, temperature 400,
  forced toolChoice 400. CP /v1/models는 claude-opus-5-5를 claude-opus-5보다 먼저 돌려준다.
- GPT 6 Sol/Luna: Global CRIS(Seoul bedrock-runtime) / US CRIS(us-east-1 bedrock-runtime) 200,
  Mantle 인리전은 us-east-1만 200 (us-east-2, us-west-2는 404 not_found_error — 2026-09-23 사용자 결정으로
  미지원 제외, 정기 재확인 대상 아님).
- GPT 6 Sol/Luna 단가: AWS Bedrock ListFoundationModelAgreementOffers rate card (2026-09-23) —
  In-Region, US CRIS는 Sol $2.20/$11, Luna $0.11/$0.55, Global CRIS는 Sol $2/$10, Luna $0.10/$0.50.
"""

import pytest

import pricing_seed
import prober
from parity.catalog import is_reasoning_capable, supports_forced_tool_choice
from pricing_sources import price_identity
from routers.reliability import _LABEL_RE

# 2026-09-23 CP on AWS /v1/models 실측 순서 그대로 — 점 버전이 base 버전보다 먼저 온다.
_CP_MODEL_IDS_20260923 = [
    "claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
    "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929",
]

_GPT6_SOL_LUNA_KEYS = [
    f"openai:{region}:{prefix}openai.gpt-6-{fam}"
    for fam in ("sol", "luna")
    for region, prefix in (("global", "global."), ("us", "us."), ("us-east-1", ""))
]


# ---------------------------------------------------------------- Claude Opus 5.5

def test_bedrock_opus55_channels_registered():
    assert prober.AVAILABLE_MODELS["global.anthropic.claude-opus-5-5"] == "Bedrock Claude Opus 5.5 (Global)"
    assert prober.AVAILABLE_MODELS["us.anthropic.claude-opus-5-5"] == "Bedrock Claude Opus 5.5 (US)"
    # 기존 Opus 5 채널은 그대로
    assert prober.AVAILABLE_MODELS["global.anthropic.claude-opus-5"] == "Bedrock Claude Opus 5 (Global)"
    assert prober.AVAILABLE_MODELS["us.anthropic.claude-opus-5"] == "Bedrock Claude Opus 5 (US)"


def test_cp_target_opus55_listed_before_opus5():
    substrings = [s for s, _ in prober._ANTHROPIC_TARGETS]
    assert substrings.index("opus-5-5") < substrings.index("opus-5")
    assert dict(prober._ANTHROPIC_TARGETS)["opus-5-5"] == "Anthropic Claude Opus 5.5 (US)"


def test_cp_discovery_with_live_model_order_labels_every_id_correctly():
    """운영 실사고 재현 — 5.5가 먼저 와도 Opus 5 라벨은 claude-opus-5에 붙어야 한다."""
    matched = {s: prober._match_anthropic_model(s, _CP_MODEL_IDS_20260923) for s, _ in prober._ANTHROPIC_TARGETS}
    assert matched == {
        "fable-5-1": "claude-fable-5-1",
        "fable-5": "claude-fable-5",
        "opus-5-5": "claude-opus-5-5",
        "opus-5": "claude-opus-5",
        "opus-4-8": "claude-opus-4-8",
        "opus-4-7": "claude-opus-4-7",
        "sonnet-5": "claude-sonnet-5",
        "sonnet-4-6": "claude-sonnet-4-6",
        "haiku-4-5": "claude-haiku-4-5-20251001",
    }
    # 한 id가 두 라벨로 등록되는 일이 없어야 한다
    assert len(set(matched.values())) == len(matched)


def test_point_release_without_target_never_hijacks_base_label():
    # 타깃이 아직 없는 미래 점 버전(sonnet-5-5)이 먼저 와도 Sonnet 5 라벨은 claude-sonnet-5로.
    assert prober._match_anthropic_model("sonnet-5", ["claude-sonnet-5-5", "claude-sonnet-5"]) == "claude-sonnet-5"
    # 점 버전만 서빙되면 base 라벨은 등록하지 않는다 (None → warning 후 skip).
    assert prober._match_anthropic_model("sonnet-5", ["claude-sonnet-5-5"]) is None
    assert prober._match_anthropic_model("opus-5", ["claude-opus-5-5"]) is None


def test_date_suffix_is_not_a_point_release():
    assert prober._is_point_release_of("haiku-4-5", "claude-haiku-4-5-20251001") is False
    assert prober._is_point_release_of("opus-5", "claude-opus-5-5") is True
    assert prober._is_point_release_of("fable-5", "claude-fable-5-1") is True
    assert prober._is_point_release_of("opus-5", "claude-opus-5") is False


def test_opus55_pricing_all_three_channels_not_opus5_fallback():
    # v2.30.0: exact per-model_id seed rows, no prefix fallback (ADR-030). Bedrock US is Global x1.1.
    for mid in ("global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5", "anthropic:claude-opus-5-5"):
        assert price_identity(mid).family_key == "claude-opus-5-5", mid
    assert pricing_seed.SEED["global.anthropic.claude-opus-5-5"][:2] == pytest.approx((4.0, 20.0))
    assert pricing_seed.SEED["us.anthropic.claude-opus-5-5"][:2] == pytest.approx((4.4, 22.0))
    assert pricing_seed.CP_SEED["claude-opus-5-5"][:2] == pytest.approx((4.0, 20.0))
    # Opus 5는 불변 — CP id claude-opus-5는 Opus 5.5가 아니라 Opus 5로 분류된다
    assert price_identity("anthropic:claude-opus-5").family_key == "claude-opus-5"
    assert pricing_seed.CP_SEED["claude-opus-5"][:2] == pytest.approx((5.0, 25.0))


def test_opus55_reasoning_and_forced_tool_choice_flags():
    for mid in ("global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5", "anthropic:claude-opus-5-5"):
        assert prober._is_reasoning_model(mid) is True  # temperature 400
        assert supports_forced_tool_choice(mid) is False  # tool_choice tool/any 400
    # Opus 5는 forced tool_choice 유지 — 마커가 opus-5 전체로 번지면 안 된다
    assert supports_forced_tool_choice("us.anthropic.claude-opus-5") is True
    assert supports_forced_tool_choice("anthropic:claude-opus-5") is True
    # 패리티 reasoning 셀 규칙은 Opus 5와 동일(비적용)
    assert is_reasoning_capable("global.anthropic.claude-opus-5-5") == is_reasoning_capable("global.anthropic.claude-opus-5")


# ---------------------------------------------------------------- OpenAI GPT 6 Sol / Luna

def _register_with_all_envs(monkeypatch):
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
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID", "openai.gpt-6-sol")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID", "openai.gpt-6-luna")
    prober._register_openai_models()


def test_gpt6_sol_luna_register_exactly_three_channels_each(monkeypatch):
    """Global CRIS + US CRIS + Mantle us-east-1 — us-east-2/us-west-2는 env가 있어도 미등록(미지원 404, 사용자 결정으로 제외)."""
    _register_with_all_envs(monkeypatch)
    keys = sorted(k for k in prober.AVAILABLE_MODELS if "gpt-6-sol" in k or "gpt-6-luna" in k)
    assert keys == sorted(_GPT6_SOL_LUNA_KEYS)
    for fam, label in (("sol", "GPT 6 Sol"), ("luna", "GPT 6 Luna")):
        # 라벨은 DB model_name에 영구 기록 — frontend MODEL_COLORS 키와 바이트 단위로 일치해야 함.
        assert prober.AVAILABLE_MODELS[f"openai:global:global.openai.gpt-6-{fam}"] == f"OpenAI {label} (Global)"
        assert prober.AVAILABLE_MODELS[f"openai:us:us.openai.gpt-6-{fam}"] == f"OpenAI {label} (US)"
        assert prober.AVAILABLE_MODELS[f"openai:us-east-1:openai.gpt-6-{fam}"] == f"OpenAI {label} (us-east-1)"


def test_gpt6_sol_luna_pricing_per_channel_and_never_matches_astra():
    """AWS offer rate card 단가 (2026-09-23) — In-Region, US CRIS는 OpenAI 정가 +10%, Global CRIS는 정가.

    6채널 모두 자기 정확 키로 매칭돼야 하고, Astra 키(gpt-6-astra*)로 prefix fallback 되면 안 된다.
    """
    expected = {
        "openai:global:global.openai.gpt-6-sol": {"input": 2.00, "output": 10.00},
        "openai:us:us.openai.gpt-6-sol": {"input": 2.20, "output": 11.00},
        "openai:us-east-1:openai.gpt-6-sol": {"input": 2.20, "output": 11.00},
        "openai:global:global.openai.gpt-6-luna": {"input": 0.10, "output": 0.50},
        "openai:us:us.openai.gpt-6-luna": {"input": 0.11, "output": 0.55},
        "openai:us-east-1:openai.gpt-6-luna": {"input": 0.11, "output": 0.55},
    }
    assert sorted(expected) == sorted(_GPT6_SOL_LUNA_KEYS)
    astra_prices = [
        pricing_seed.SEED[mid][:2]
        for mid in (
            "openai:global:global.openai.gpt-6-astra",
            "openai:us:us.openai.gpt-6-astra",
            "openai:us-west-2:openai.gpt-6-astra",
        )
    ]
    for mid, price in expected.items():
        seeded = pricing_seed.SEED[mid][:2]
        assert seeded == pytest.approx((price["input"], price["output"])), mid
        assert seeded not in astra_prices, mid
        assert price_identity(mid).family_key != "gpt-6-astra", mid


def test_gpt6_openai_reasoning_markers_stay_excluded():
    # effort low 프로브에서 reasoning_tokens=0 (2026-09-23 실측) → 넣으면 "미지원" 오판.
    for mid in _GPT6_SOL_LUNA_KEYS:
        assert is_reasoning_capable(mid) is False, mid


def test_reliability_label_regex_parses_new_labels():
    m = _LABEL_RE.match("Anthropic Claude Opus 5.5 (US)")
    assert m and m.group(2) == "Claude Opus 5.5" and m.group(3) == "US"
    m = _LABEL_RE.match("Bedrock Claude Opus 5.5 (Global)")
    assert m and m.group(1) == "Bedrock" and m.group(2) == "Claude Opus 5.5"
    m = _LABEL_RE.match("OpenAI GPT 6 Sol (us-east-1)")
    assert m and m.group(1) == "OpenAI" and m.group(2) == "GPT 6 Sol" and m.group(3) == "us-east-1"
    m = _LABEL_RE.match("OpenAI GPT 6 Luna (US)")
    assert m and m.group(2) == "GPT 6 Luna" and m.group(3) == "US"
