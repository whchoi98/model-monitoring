"""Claude Fable 5.1 카탈로그 편입 (v2.22.0) — 3채널 등록·단가·substring 충돌·패리티 스위치 검증."""

import pricing
import prober
from parity.catalog import is_applicable, is_reasoning_capable, supports_forced_tool_choice
from routers.reliability import _LABEL_RE


def test_bedrock_channels_registered():
    assert prober.AVAILABLE_MODELS["global.anthropic.claude-fable-5-1"] == "Bedrock Claude Fable 5.1 (Global)"
    assert prober.AVAILABLE_MODELS["us.anthropic.claude-fable-5-1"] == "Bedrock Claude Fable 5.1 (US)"
    # 기존 Fable 5는 그대로 유지
    assert prober.AVAILABLE_MODELS["global.anthropic.claude-fable-5"] == "Bedrock Claude Fable 5 (Global)"


def test_cp_target_registered_before_fable5():
    substrings = [s for s, _ in prober._ANTHROPIC_TARGETS]
    assert "fable-5-1" in substrings and "fable-5" in substrings
    labels = dict(prober._ANTHROPIC_TARGETS)
    assert labels["fable-5-1"] == "Anthropic Claude Fable 5.1 (US)"


def test_discovery_substring_does_not_mislabel_fable51_as_fable5():
    # /v1/models가 5.1을 먼저 돌려줘도 "fable-5" 타깃은 claude-fable-5를 골라야 한다.
    ids = ["claude-fable-5-1", "claude-fable-5", "claude-opus-5"]
    assert prober._match_anthropic_model("fable-5", ids) == "claude-fable-5"
    assert prober._match_anthropic_model("fable-5-1", ids) == "claude-fable-5-1"
    # 5.1만 서빙되면 Fable 5 라벨은 등록되지 않아야 한다 (None → warning 후 skip).
    assert prober._match_anthropic_model("fable-5", ["claude-fable-5-1"]) is None
    # 접두 관계가 없는 타깃은 기존 동작 그대로
    assert prober._match_anthropic_model("opus-5", ids) == "claude-opus-5"


def test_pricing_all_three_channels():
    expected = {"input": 10.0, "output": 50.0}
    for mid in ("global.anthropic.claude-fable-5-1", "us.anthropic.claude-fable-5-1", "anthropic:claude-fable-5-1"):
        assert pricing.get_pricing(mid) == expected, mid


def test_reasoning_and_parity_flags():
    assert prober._is_reasoning_model("global.anthropic.claude-fable-5-1") is True
    assert is_reasoning_capable("us.anthropic.claude-fable-5-1") is True
    assert is_applicable("adaptive_thinking", "converse", "global.anthropic.claude-fable-5-1") is True
    # forced tool_choice는 Fable 5.1만 미지원 → tool_use 프로브가 auto로 전환
    assert supports_forced_tool_choice("global.anthropic.claude-fable-5-1") is False
    assert supports_forced_tool_choice("anthropic:claude-fable-5-1") is False
    assert supports_forced_tool_choice("global.anthropic.claude-fable-5") is True
    assert supports_forced_tool_choice("us.anthropic.claude-opus-5") is True


def test_reliability_label_regex_parses_dotted_family():
    m = _LABEL_RE.match("Anthropic Claude Fable 5.1 (US)")
    assert m and m.group(2) == "Claude Fable 5.1" and m.group(3) == "US"
    m = _LABEL_RE.match("Bedrock Claude Fable 5.1 (Global)")
    assert m and m.group(1) == "Bedrock" and m.group(2) == "Claude Fable 5.1"
