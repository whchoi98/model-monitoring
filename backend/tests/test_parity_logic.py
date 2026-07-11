"""패리티 엔진 순수 로직 테스트 — 카탈로그 적용 규칙, 오류 분류, 증거 검사.

패리티 런의 판정 원칙 (v2.11.0):
  supported   — 실제 요청이 성공했고 응답 '내용'이 증거 검사를 통과 (HTTP 200만으로는 불충분)
  unsupported — provider가 기능 미지원을 '깨끗한 오류'로 응답 (파라미터 거부 등)
  broken      — 동작해야 하는데 오류 또는 증거 검사 실패
  skipped     — 해당 조합에 프로브 없음 (surface 미적용 등)
"""

import pytest

from parity.catalog import FEATURES, SURFACES, surfaces_for, is_applicable
from parity.engine import classify_error, check_canary, check_json_object, check_tool_roundtrip, check_cached_tokens


# ---------------------------------------------------------------------------
# 카탈로그 — 모델별 surface 적용
# ---------------------------------------------------------------------------

def test_surfaces_for_each_provider_path():
    assert surfaces_for("global.anthropic.claude-fable-5") == ["converse", "invoke_model"]
    assert surfaces_for("us.amazon.nova-2-lite-v1:0") == ["converse"]  # Nova는 네이티브 스키마 미제공 → InvokeModel skip
    assert surfaces_for("anthropic:claude-sonnet-5") == ["messages"]
    assert surfaces_for("openai:us-east-1:openai.gpt-5.5") == ["chat_completions", "responses"]
    assert surfaces_for("openai:1p:gpt-5.4") == ["chat_completions", "responses"]


def test_feature_catalog_has_seven_features():
    assert len(FEATURES) == 7
    ids = [f["id"] for f in FEATURES]
    assert ids == ["basic", "streaming", "system_instructions", "tool_use",
                   "structured_output", "reasoning", "caching"]


def test_reasoning_only_applicable_to_reasoning_capable():
    # reasoning 프로브는 확장 사고 지원 모델에만 — Nova/Haiku 등은 skipped
    assert is_applicable("reasoning", "converse", "global.anthropic.claude-sonnet-5") is True
    assert is_applicable("reasoning", "converse", "us.amazon.nova-2-lite-v1:0") is False
    assert is_applicable("basic", "converse", "us.amazon.nova-2-lite-v1:0") is True


# ---------------------------------------------------------------------------
# 오류 분류 — clean not-supported vs broken
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "ValidationException: This model doesn't support tool use.",
    "The model returned the following errors: unsupported_parameter: 'reasoning'",
    "This model does not support the specified feature",
    "Extra inputs are not permitted: response_format",
    "Invalid parameter: tools is not supported for this model",
    "unknown parameter: 'cache_control'",
])
def test_clean_unsupported_errors(msg):
    assert classify_error(msg) == "unsupported"


@pytest.mark.parametrize("msg", [
    "ThrottlingException: Too many requests",
    "Internal server error",
    "timed out",
    "AccessDeniedException: not authorized",
])
def test_other_errors_are_broken(msg):
    assert classify_error(msg) == "broken"


# ---------------------------------------------------------------------------
# 증거 검사 (execution evidence)
# ---------------------------------------------------------------------------

def test_check_canary():
    assert check_canary("PARITY_OK — 안녕하세요", "PARITY_OK") is True
    assert check_canary("안녕하세요", "PARITY_OK") is False
    assert check_canary(None, "PARITY_OK") is False


def test_check_json_object_requires_key():
    assert check_json_object('{"city": "Seoul", "ok": true}', "city") is True
    assert check_json_object('앞말 {"city": "Seoul"} 뒷말', "city") is True  # 코드펜스/설명 섞임 허용
    assert check_json_object('{"other": 1}', "city") is False
    assert check_json_object("not json", "city") is False


def test_check_tool_roundtrip_requires_canary_argument():
    # 도구 호출이 실행됐고 canary 인자가 그대로 왕복해야 supported
    assert check_tool_roundtrip({"name": "echo", "arguments": {"text": "canary-123"}}, "canary-123") is True
    assert check_tool_roundtrip({"name": "echo", "arguments": {"text": "다른값"}}, "canary-123") is False
    assert check_tool_roundtrip(None, "canary-123") is False


def test_check_cached_tokens():
    assert check_cached_tokens({"cached_tokens": 128}) is True
    assert check_cached_tokens({"cache_read_input_tokens": 512}) is True
    assert check_cached_tokens({"cached_tokens": 0}) is False
    assert check_cached_tokens({}) is False
    assert check_cached_tokens(None) is False


# ---------------------------------------------------------------------------
# 피처별 토큰 예산 — 첫 실런에서 64토큰 절단으로 structured_output 전량 false-Broken
# (모델은 정상 JSON을 반환했으나 닫는 }가 잘림). 회귀 방지.
# ---------------------------------------------------------------------------

def test_max_tokens_budget_prevents_truncation():
    from parity.probes import max_tokens_for

    # 코드펜스 + 들여쓰기 JSON + 한국어 값도 절단 없이 담을 수 있어야 한다
    assert max_tokens_for("structured_output") >= 512
    # 일반 텍스트 프로브도 canary 접두사 + 짧은 답변에 충분해야 한다 (64는 부족했음)
    assert max_tokens_for("basic") >= 256
    assert max_tokens_for("system_instructions") >= 256
    # reasoning은 thinking budget(1024)보다 커야 텍스트가 남는다
    assert max_tokens_for("reasoning") > 1024


def test_check_json_object_rejects_truncated_json():
    # max_tokens 절단 시나리오 — 닫는 }가 없으면 반드시 False (조용한 오탐 방지)
    truncated = '```json\n{\n  "city": "서울",\n  "country": "대한민국",\n  '
    assert check_json_object(truncated, "city") is False


# ---------------------------------------------------------------------------
# 런 간 변경 감지 (v2.12.0) — 이전 완료 런 대비 상태가 바뀐 셀만 반환
# ---------------------------------------------------------------------------

def test_diff_statuses_reports_changed_and_new_cells():
    from parity.engine import diff_statuses

    prev = {
        ("m1", "converse", "basic"): "supported",
        ("m1", "converse", "caching"): "broken",
        ("m9", "converse", "basic"): "supported",  # 현재 런에 없음 → 무시
    }
    cur = {
        ("m1", "converse", "basic"): "supported",   # 동일 → 제외
        ("m1", "converse", "caching"): "supported", # 변경 → 포함
        ("m2", "responses", "basic"): "broken",     # 신규 셀 → before None
    }
    changes = diff_statuses(prev, cur)
    assert {(c["model_id"], c["surface"], c["feature"], c["before"], c["after"]) for c in changes} == {
        ("m1", "converse", "caching", "broken", "supported"),
        ("m2", "responses", "basic", None, "broken"),
    }


def test_diff_statuses_empty_prev_marks_all_new():
    from parity.engine import diff_statuses

    cur = {("m1", "converse", "basic"): "supported"}
    changes = diff_statuses({}, cur)
    assert changes == [
        {"model_id": "m1", "surface": "converse", "feature": "basic", "before": None, "after": "supported"}
    ]
