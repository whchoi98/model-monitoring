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
    # Bedrock Claude는 Mantle /anthropic Messages 시험 포함 (v2.13.0, ap-northeast-1)
    assert surfaces_for("global.anthropic.claude-fable-5") == ["converse", "invoke_model", "messages_mantle"]
    assert surfaces_for("us.amazon.nova-2-lite-v1:0") == ["converse"]  # Nova는 네이티브 스키마 미제공 → InvokeModel skip
    assert surfaces_for("anthropic:claude-sonnet-5") == ["messages"]
    assert surfaces_for("openai:us-east-1:openai.gpt-5.5") == ["chat_completions", "responses"]
    assert surfaces_for("openai:1p:gpt-5.4") == ["chat_completions", "responses"]


def test_mantle_fm_id_strips_profile_prefix():
    from parity.catalog import mantle_fm_id

    # Mantle /anthropic은 Bedrock FM id를 요구 — 프로파일 접두사(global./us.) 제거
    assert mantle_fm_id("global.anthropic.claude-fable-5") == "anthropic.claude-fable-5"
    assert mantle_fm_id("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "anthropic.claude-haiku-4-5-20251001-v1:0"


def test_feature_catalog_order():
    ids = [f["id"] for f in FEATURES]
    assert ids == ["basic", "streaming", "system_instructions", "tool_use",
                   "structured_output", "reasoning", "caching",
                   "adaptive_thinking", "count_tokens", "batches", "web_search", "computer_use"]


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
    # Mantle /anthropic에서 모델이 그 리전에 서빙되지 않음 — 깨끗한 미제공 신호 (v2.13.0)
    "NotFoundError: Error code: 404 - {'error': {'type': 'not_found_error', 'message': \"The model 'anthropic.claude-fable-5' does not exist\"}}",
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


# ---------------------------------------------------------------------------
# 증거용 요청 스냅샷 (v2.13.0) — 셀 클릭 시 Request JSON 표시용, 장문은 절단
# ---------------------------------------------------------------------------

def test_req_snapshot_trims_long_strings_and_keeps_structure():
    from parity.probes import _req_snapshot

    pad = "x" * 5000
    snap = _req_snapshot("model-1", system=[{"text": pad}], max_tokens=64,
                         messages=[{"role": "user", "content": "hi"}])
    assert snap["model"] == "model-1"
    assert snap["max_tokens"] == 64
    assert snap["messages"][0]["content"] == "hi"
    trimmed = snap["system"][0]["text"]
    assert len(trimmed) < 300 and "5000 chars" in trimmed  # 절단 + 원 길이 표기


# ---------------------------------------------------------------------------
# 피처 확장 5종 (v2.14.0) — 피처별 surface 적용 맵
# ---------------------------------------------------------------------------

def test_feature_catalog_has_twelve_features():
    ids = [f["id"] for f in FEATURES]
    assert len(ids) == 12
    for new in ("adaptive_thinking", "count_tokens", "batches", "web_search", "computer_use"):
        assert new in ids


def test_adaptive_thinking_only_for_fable5():
    # adaptive thinking은 Fable 5 계열 전용 (참조 증거 화면과 동일 방식)
    assert is_applicable("adaptive_thinking", "converse", "global.anthropic.claude-fable-5") is True
    assert is_applicable("adaptive_thinking", "messages", "anthropic:claude-fable-5") is True
    assert is_applicable("adaptive_thinking", "converse", "global.anthropic.claude-opus-4-8") is False


def test_feature_surface_restrictions():
    # batches는 anthropic SDK 경로(messages/messages_mantle)만
    assert is_applicable("batches", "messages", "anthropic:claude-haiku-4-5-20251001") is True
    assert is_applicable("batches", "converse", "global.anthropic.claude-haiku-4-5-20251001-v1:0") is False
    # web_search는 responses(OpenAI 내장 도구)에는 적용, chat_completions에는 미적용
    assert is_applicable("web_search", "responses", "openai:1p:gpt-5.5") is True
    assert is_applicable("web_search", "chat_completions", "openai:1p:gpt-5.5") is False
    assert is_applicable("web_search", "invoke_model", "us.anthropic.claude-haiku-4-5-20251001-v1:0") is True
    # computer_use는 anthropic 네이티브 경로만
    assert is_applicable("computer_use", "invoke_model", "us.anthropic.claude-haiku-4-5-20251001-v1:0") is True
    assert is_applicable("computer_use", "responses", "openai:1p:gpt-5.5") is False
    # count_tokens는 OpenAI 경로 미적용 (엔드포인트 없음)
    assert is_applicable("count_tokens", "messages", "anthropic:claude-haiku-4-5-20251001") is True
    assert is_applicable("count_tokens", "responses", "openai:1p:gpt-5.5") is False
