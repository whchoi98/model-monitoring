"""패리티 피처 카탈로그 — 무엇을 어떤 surface에서 프로빙할지 정의 (v2.11.0).

surface (6): converse / invoke_model (Bedrock SigV4), messages (Anthropic CP bearer),
messages_mantle (Bedrock Mantle /anthropic bearer — v2.13.0, 리전 MANTLE_ANTHROPIC_REGION),
chat_completions / responses (OpenAI 호환 bearer — Mantle·1P 공용).

적용 규칙:
- Bedrock Claude → converse + invoke_model + messages_mantle. Nova → converse만.
- reasoning 피처는 확장 사고 지원 모델에만 적용 (그 외 skipped).
"""

from __future__ import annotations

SURFACES = ["converse", "invoke_model", "messages", "messages_mantle", "chat_completions", "responses"]

FEATURES: list[dict] = [
    {
        "id": "basic",
        "label_ko": "기본 응답",
        "desc_ko": "논스트리밍 단건 요청 — 비어 있지 않은 텍스트 응답을 검증",
    },
    {
        "id": "streaming",
        "label_ko": "스트리밍",
        "desc_ko": "스트림 요청 — 2개 이상의 콘텐츠 델타 이벤트 수신을 검증",
    },
    {
        "id": "system_instructions",
        "label_ko": "시스템 지시",
        "desc_ko": "system 필드로 카나리 단어 강제 — 응답에 카나리가 실제 반영되는지 검증",
    },
    {
        "id": "tool_use",
        "label_ko": "도구 호출",
        "desc_ko": "echo 도구 강제(tool_choice) — 카나리 인자가 도구 호출로 왕복하는지 검증",
    },
    {
        "id": "structured_output",
        "label_ko": "구조화 출력",
        "desc_ko": "JSON 출력 강제 — 필수 키를 가진 유효한 JSON인지 검증",
    },
    {
        "id": "reasoning",
        "label_ko": "확장 추론",
        "desc_ko": "thinking/reasoning 활성 — 추론 토큰 사용 또는 추론 블록 존재를 검증",
    },
    {
        "id": "caching",
        "label_ko": "프롬프트 캐싱",
        "desc_ko": "동일 프롬프트 반복 — 두 번째 응답의 cached tokens > 0 검증",
    },
    # --- v2.14.0 확장 5종 ---
    {
        "id": "adaptive_thinking",
        "label_ko": "적응형 추론",
        "desc_ko": "thinking type: adaptive — 모델이 추론 예산을 스스로 조절, thinking 블록 존재 검증 (Fable 5 전용)",
    },
    {
        "id": "count_tokens",
        "label_ko": "토큰 카운트",
        "desc_ko": "Count Tokens 엔드포인트 왕복 — input_tokens > 0 검증",
    },
    {
        "id": "batches",
        "label_ko": "배치",
        "desc_ko": "Message Batches submit→status 왕복 — 배치 생성·상태 조회 검증 (조회 후 취소)",
    },
    {
        "id": "web_search",
        "label_ko": "웹 검색 도구",
        "desc_ko": "서버측 web_search 도구 정의 수락 검증 — 도구 포함 요청이 정상 완료되는지",
    },
    {
        "id": "computer_use",
        "label_ko": "컴퓨터 사용 도구",
        "desc_ko": "computer use 도구 정의 수락 검증 (beta 헤더 포함)",
    },
    # --- v2.15.0 확장 7종 (참조 도구 수준) ---
    {
        "id": "reasoning_effort",
        "label_ko": "추론 강도 조절",
        "desc_ko": "effort 파라미터(low/high) 수락 검증 — Claude output_config, GPT reasoning effort",
    },
    {
        "id": "json_schema",
        "label_ko": "JSON 스키마 강제",
        "desc_ko": "strict JSON schema 출력 강제 — 필수 키를 가진 유효 JSON 검증",
    },
    {
        "id": "url_sources",
        "label_ko": "URL 문서 소스",
        "desc_ko": "document source type: url — 원격 PDF를 컨텍스트로 수락하고 응답하는지 검증",
    },
    {
        "id": "memory_tool",
        "label_ko": "메모리 도구",
        "desc_ko": "memory 도구 정의 수락 검증 (beta 헤더 포함)",
    },
    {
        "id": "code_execution",
        "label_ko": "코드 실행 도구",
        "desc_ko": "서버측 code_execution 도구 정의 수락 검증 (beta 헤더 포함)",
    },
    {
        "id": "files_api",
        "label_ko": "Files API",
        "desc_ko": "파일 목록 엔드포인트 왕복 — Files API 제공 여부 검증",
    },
    {
        "id": "models_api",
        "label_ko": "Models API",
        "desc_ko": "모델 조회 엔드포인트 왕복 — 해당 모델 id가 조회되는지 검증",
    },
]

FEATURE_IDS = [f["id"] for f in FEATURES]

# 확장 추론 지원 패밀리 (prober._is_reasoning_model과 정합 — 여기서는 카탈로그 자체 규칙으로 유지)
_REASONING_MARKERS = ("fable-5", "opus-4-8", "opus-4-7", "sonnet-5", "gpt-5")

# 피처별 surface 제한 (v2.14.0) — 미기재 피처는 모든 surface 허용.
# 검사 방법을 구현한 surface만 나열: 그 외 조합은 skipped (프로브 없음 ≠ 미지원).
_FEATURE_SURFACES: dict[str, frozenset[str]] = {
    "adaptive_thinking": frozenset({"converse", "invoke_model", "messages", "messages_mantle"}),
    "count_tokens": frozenset({"converse", "invoke_model", "messages", "messages_mantle"}),
    "batches": frozenset({"messages", "messages_mantle"}),
    "web_search": frozenset({"invoke_model", "messages", "messages_mantle", "responses"}),
    "computer_use": frozenset({"invoke_model", "messages", "messages_mantle"}),
    # v2.15.0
    "reasoning_effort": frozenset({"converse", "invoke_model", "messages", "messages_mantle",
                                   "chat_completions", "responses"}),
    "json_schema": frozenset({"invoke_model", "messages", "messages_mantle",
                              "chat_completions", "responses"}),
    "url_sources": frozenset({"invoke_model", "messages", "messages_mantle"}),
    "memory_tool": frozenset({"invoke_model", "messages", "messages_mantle"}),
    "code_execution": frozenset({"invoke_model", "messages", "messages_mantle"}),
    "files_api": frozenset({"messages", "messages_mantle"}),
    "models_api": frozenset({"messages", "messages_mantle", "chat_completions"}),
}


def surfaces_for(model_id: str) -> list[str]:
    """모델 키 스킴(ADR-019/020)에 따라 프로빙할 surface 목록."""
    if model_id.startswith("anthropic:"):
        return ["messages"]
    if model_id.startswith("openai:"):
        return ["chat_completions", "responses"]
    # Bedrock inference profile
    if "anthropic" in model_id:
        return ["converse", "invoke_model", "messages_mantle"]
    return ["converse"]  # Nova 등 — invoke_model 네이티브 프로브 미구현


def mantle_fm_id(model_id: str) -> str:
    """Bedrock Mantle /anthropic용 FM id — 프로파일 접두사(global./us.) 제거.

    실측(2026-07-11): Mantle은 `anthropic.claude-…` FM id만 인식, 프로파일 id는 not_found.
    """
    for prefix in ("global.", "us."):
        if model_id.startswith(prefix):
            return model_id[len(prefix):]
    return model_id


def is_reasoning_capable(model_id: str) -> bool:
    return any(m in model_id for m in _REASONING_MARKERS)


def is_applicable(feature_id: str, surface: str, model_id: str) -> bool:
    """(feature, surface, model) 조합에 프로브를 실행할지. False면 skipped."""
    if surface not in surfaces_for(model_id):
        return False
    allowed = _FEATURE_SURFACES.get(feature_id)
    if allowed is not None and surface not in allowed:
        return False
    if feature_id in ("reasoning", "reasoning_effort") and not is_reasoning_capable(model_id):
        return False
    if feature_id == "adaptive_thinking" and "fable-5" not in model_id:
        return False
    return True
