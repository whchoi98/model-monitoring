"""agent.tools 단위 테스트 — DB 없이 optimize_prompt 검증 + mock으로 DB tools 호출."""

from __future__ import annotations

from agent.tools import TOOL_REGISTRY, optimize_prompt


def test_tool_registry_has_4_tools():
    assert set(TOOL_REGISTRY.keys()) == {
        "get_latest_results",
        "get_trend",
        "compare_models",
        "optimize_prompt",
    }


def test_optimize_prompt_returns_guidance():
    result = optimize_prompt("Explain quantum computing in great detail.", target="shorter_with_same_quality")
    assert result["input_prompt"].startswith("Explain quantum")
    assert result["target"] == "shorter_with_same_quality"
    assert "guidance" in result and isinstance(result["guidance"], str)
    # 가이드라인이 핵심 원칙을 포함하는지.
    for keyword in ["응답 형식", "max_tokens", "시스템 프롬프트"]:
        assert keyword in result["guidance"]


def test_optimize_prompt_normalizes_target():
    result = optimize_prompt("hi", target="  REDUCE_COST  ")
    assert result["target"] == "reduce_cost"
