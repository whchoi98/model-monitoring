"""Claude API Features 카탈로그 (v2.23.0) — 무엇을 어느 엔드포인트에서 어떤 모델로 검증하는가.

행(FEATURES) = platform.claude.com/docs/en/build-with-claude/overview 의 33개 피처 + 코어 4 + Models API.
열(SURFACES) = cp(Claude Platform on AWS) / mantle(Bedrock Mantle /anthropic) / bedrock_invoke / bedrock_converse.
documented = 문서상 기대치 {ga|beta|no|unknown}. 1차 출처는 overview Availability 컬럼(Bedrock 단일 컬럼),
Converse/InvokeModel 차이·Mantle 특례는 AWS 공식 문서와 platform.claude.com Bedrock 두 페이지로 보정.
출처가 상충하면 notes에 남기고 실측으로 판정한다 (drift 감지가 이 메뉴의 목적).
"""

from __future__ import annotations

import os

SURFACES = ["cp", "mantle", "bedrock_invoke", "bedrock_converse"]

SURFACE_META: dict[str, dict] = {
    "cp": {"label": "Claude Platform on AWS", "short": "CP on AWS", "group": "cp",
           "region_env": "ANTHROPIC_AWS_REGION", "default_region": "us-east-2"},
    "mantle": {"label": "Bedrock Mantle /anthropic", "short": "Mantle", "group": "mantle",
               "region_env": "MANTLE_ANTHROPIC_REGION", "default_region": "ap-northeast-1"},
    "bedrock_invoke": {"label": "Bedrock runtime · InvokeModel", "short": "InvokeModel", "group": "bedrock",
                       "region_env": "BEDROCK_FEATURES_REGION", "default_region": "ap-northeast-2"},
    "bedrock_converse": {"label": "Bedrock runtime · Converse", "short": "Converse", "group": "bedrock",
                         "region_env": "BEDROCK_FEATURES_REGION", "default_region": "ap-northeast-2"},
}


def region_for(surface: str) -> str:
    meta = SURFACE_META[surface]
    return os.environ.get(meta["region_env"], meta["default_region"])


# 대표 모델 4종 (사용자 결정 2026-09-05). mantle=None → Mantle Fable 5.1은 US GovCloud 전용.
MODELS: list[dict] = [
    {"key": "fable-5-1", "label": "Claude Fable 5.1", "cp": "claude-fable-5-1", "mantle": None,
     "bedrock": "global.anthropic.claude-fable-5-1",
     "mantle_reason": "Mantle Fable 5.1 = US GovCloud(us-gov-west-1) 전용"},
    {"key": "fable-5", "label": "Claude Fable 5", "cp": "claude-fable-5", "mantle": "anthropic.claude-fable-5",
     "bedrock": "global.anthropic.claude-fable-5"},
    {"key": "opus-5", "label": "Claude Opus 5", "cp": "claude-opus-5", "mantle": "anthropic.claude-opus-5",
     "bedrock": "global.anthropic.claude-opus-5"},
    {"key": "sonnet-5", "label": "Claude Sonnet 5", "cp": "claude-sonnet-5", "mantle": "anthropic.claude-sonnet-5",
     "bedrock": "global.anthropic.claude-sonnet-5"},
]
MODEL_KEYS = [m["key"] for m in MODELS]
_MODEL_BY_KEY = {m["key"]: m for m in MODELS}


def model_id_for(surface: str, model_key: str) -> str | None:
    m = _MODEL_BY_KEY[model_key]
    if surface == "cp":
        return m["cp"]
    if surface == "mantle":
        return m["mantle"]
    return m["bedrock"]


def model_label(model_key: str) -> str:
    return _MODEL_BY_KEY[model_key]["label"]


GROUPS: list[dict] = [
    {"id": "core", "label_ko": "코어 Messages", "label_en": "Core Messages"},
    {"id": "model", "label_ko": "모델 기능", "label_en": "Model capabilities"},
    {"id": "server_tools", "label_ko": "서버측 도구", "label_en": "Server-side tools"},
    {"id": "client_tools", "label_ko": "클라이언트 도구", "label_en": "Client-side tools"},
    {"id": "tool_infra", "label_ko": "도구 인프라", "label_en": "Tool infrastructure"},
    {"id": "context", "label_ko": "컨텍스트 관리", "label_en": "Context management"},
    {"id": "files_endpoints", "label_ko": "파일 · 엔드포인트", "label_en": "Files & endpoints"},
]

_DOC = "https://platform.claude.com/docs/en/"
ALL = {"cp": "ga", "mantle": "ga", "bedrock_invoke": "ga", "bedrock_converse": "ga"}
ALL_BETA = {"cp": "beta", "mantle": "beta", "bedrock_invoke": "beta", "bedrock_converse": "beta"}
CP_ONLY = {"cp": "ga", "mantle": "no", "bedrock_invoke": "no", "bedrock_converse": "no"}
CP_BETA_ONLY = {"cp": "beta", "mantle": "no", "bedrock_invoke": "no", "bedrock_converse": "no"}
NONE = {"cp": "no", "mantle": "no", "bedrock_invoke": "no", "bedrock_converse": "no"}


def _f(id_: str, group: str, ko: str, en: str, desc_ko: str, desc_en: str, doc: str,
       documented: dict, verification: str, notes: str = "") -> dict:
    return {"id": id_, "group": group, "label_ko": ko, "label_en": en, "desc_ko": desc_ko, "desc_en": desc_en,
            "doc_url": doc, "documented": dict(documented), "verification": verification, "notes": notes}


FEATURES: list[dict] = [
    # --- core ---
    _f("messages_basic", "core", "기본 응답", "Basic response", "논스트리밍 1건 — 비어 있지 않은 텍스트",
       "Non-streaming single request — non-empty text", _DOC + "api/messages", ALL, "evidence"),
    _f("streaming", "core", "스트리밍", "Streaming", "SSE/EventStream — 콘텐츠 델타 2개 이상",
       "SSE/EventStream — 2+ content deltas", _DOC + "build-with-claude/streaming", ALL, "evidence"),
    _f("system_prompt", "core", "시스템 프롬프트", "System prompt", "system 카나리 강제 → 응답 반영",
       "Canary forced via system → appears in reply", _DOC + "build-with-claude/prompt-engineering/system-prompts", ALL, "evidence"),
    _f("tool_use", "core", "도구 호출", "Tool use", "echo 도구 카나리 왕복 (Fable 5.1은 auto + 지시)",
       "Echo tool canary round-trip (Fable 5.1: auto + instruction)", _DOC + "agents-and-tools/tool-use/overview", ALL, "evidence"),
    # --- model capabilities ---
    _f("context_window_1m", "model", "1M 컨텍스트", "Context window (1M)", "Models API max_input_tokens == 1,000,000 (CP만 검증 경로 있음)",
       "Models API max_input_tokens == 1,000,000 (only CP has a capability endpoint)",
       _DOC + "build-with-claude/context-windows", ALL, "capability", "mantle/bedrock: capability 엔드포인트 없음 → skipped"),
    _f("adaptive_thinking", "model", "적응형 추론", "Adaptive thinking", "thinking type adaptive + display summarized → thinking 블록",
       "thinking type adaptive + display summarized → thinking block", _DOC + "build-with-claude/thinking", ALL, "evidence"),
    _f("batch_processing", "model", "배치 처리", "Batch processing", "배치 1건 생성 → 조회 → 취소",
       "Create 1-request batch → retrieve → cancel", _DOC + "build-with-claude/batch-processing", CP_ONLY, "evidence"),
    _f("citations", "model", "인용", "Citations", "document + citations.enabled → text.citations[]",
       "document + citations.enabled → text.citations[]", _DOC + "build-with-claude/citations", ALL, "evidence"),
    _f("data_residency", "model", "데이터 레지던시", "Data residency (inference_geo)", "inference_geo us → usage.inference_geo 에코",
       "inference_geo us → echoed in usage.inference_geo", _DOC + "manage-claude/data-residency", CP_ONLY, "evidence"),
    _f("effort", "model", "Effort", "Effort", "output_config.effort low 수락 + 잘못된 값 400(파라미터 검증 증명)",
       "output_config.effort low accepted + invalid value → 400 (proves validation)", _DOC + "build-with-claude/effort", ALL, "negative"),
    _f("fallback_credit", "model", "Fallback 크레딧", "Fallback credit", "beta fallback-credit-2026-07-01 수락 (refusal 없이는 토큰 미발급)",
       "beta fallback-credit-2026-07-01 accepted (no token without a refusal)", _DOC + "build-with-claude/fallback-credit", ALL_BETA, "acceptance"),
    _f("pdf_support", "model", "PDF 입력", "PDF support", "base64 1페이지 PDF의 카나리 단어 질의",
       "Ask for the canary word inside a base64 1-page PDF", _DOC + "build-with-claude/pdf-support", ALL, "evidence"),
    _f("search_results", "model", "검색 결과 블록", "Search results", "search_result 블록 + citations → search_result_location",
       "search_result block + citations → search_result_location", _DOC + "build-with-claude/search-results", ALL, "evidence",
       "AWS Converse 문서는 구모델(Opus 4.1 등)만 나열 — 대표 모델에서 unsupported 가능"),
    _f("server_side_fallback", "model", "서버측 Fallback", "Server-side fallback", "fallbacks default + beta 수락",
       "fallbacks default + beta accepted", _DOC + "build-with-claude/refusals-and-fallback",
       {"cp": "unknown", "mantle": "no", "bedrock_invoke": "no", "bedrock_converse": "no"}, "acceptance",
       "overview는 Claude API only, fallback-credit 페이지는 P-AWS 인식 시사 → 실측"),
    _f("structured_outputs", "model", "구조화 출력", "Structured outputs", "output_config.format json_schema → 스키마 유효 JSON",
       "output_config.format json_schema → schema-valid JSON", _DOC + "build-with-claude/structured-outputs",
       {"cp": "ga", "mantle": "no", "bedrock_invoke": "ga", "bedrock_converse": "ga"}, "evidence",
       "Anthropic Bedrock(Opus 4.7+) 페이지는 미지원, AWS InvokeModel 문서는 지원 → 실측"),
    _f("strict_tool_use", "model", "Strict 도구", "Strict tool use", "strict:true 도구 → 입력 키 집합이 스키마와 일치",
       "strict:true tool → input keys exactly match schema", _DOC + "build-with-claude/structured-outputs",
       {"cp": "ga", "mantle": "unknown", "bedrock_invoke": "ga", "bedrock_converse": "ga"}, "evidence"),
    _f("extended_thinking", "model", "확장 추론(budget)", "Extended thinking (budget_tokens)",
       "대표 4모델은 adaptive-only → 문서상 400이 정상; 정확한 거부 문구면 not_applicable",
       "All 4 models are adaptive-only → documented 400; exact rejection → not_applicable",
       _DOC + "build-with-claude/thinking", ALL, "negative"),
    # --- server-side tools ---
    _f("advisor_tool", "server_tools", "Advisor 도구", "Advisor tool", "advisor_20260301 → server_tool_use + advisor result",
       "advisor_20260301 → server_tool_use + advisor result", _DOC + "agents-and-tools/tool-use/advisor-tool", CP_BETA_ONLY, "evidence"),
    _f("code_execution", "server_tools", "코드 실행", "Code execution", "code_execution_20260521 → stdout에 22173",
       "code_execution_20260521 → stdout contains 22173", _DOC + "agents-and-tools/tool-use/code-execution-tool", CP_ONLY, "evidence"),
    _f("web_fetch", "server_tools", "웹 페치", "Web fetch", "web_fetch_20260209 → web_fetch_result",
       "web_fetch_20260209 → web_fetch_result", _DOC + "agents-and-tools/tool-use/web-fetch-tool", CP_ONLY, "evidence"),
    _f("web_search", "server_tools", "웹 검색", "Web search", "web_search_20260209 max_uses 1 → web_search_tool_result",
       "web_search_20260209 max_uses 1 → web_search_tool_result", _DOC + "agents-and-tools/tool-use/web-search-tool", CP_ONLY, "evidence"),
    # --- client-side tools ---
    _f("bash_tool", "client_tools", "Bash 도구", "Bash tool", "bash_20250124 → tool_use{bash}",
       "bash_20250124 → tool_use{bash}", _DOC + "agents-and-tools/tool-use/bash-tool", ALL, "evidence"),
    _f("browser_use", "client_tools", "브라우저 사용", "Browser use", "browser_toolset_20260801 → tool_use{toolset browser}",
       "browser_toolset_20260801 → tool_use{toolset browser}", _DOC + "agents-and-tools/tool-use/browser-use-tool", NONE, "evidence"),
    _f("computer_use", "client_tools", "컴퓨터 사용", "Computer use", "toolset 20260801 시도 → 400이면 computer_20251124 + beta",
       "Try toolset 20260801 → on 400 fall back to computer_20251124 + beta", _DOC + "agents-and-tools/tool-use/computer-use-tool", ALL_BETA, "evidence",
       "P-AWS/Bedrock은 toolset 미제공, 대표 모델은 toolset 전용 모델군 → 미지원 가능(정상 발견)"),
    _f("memory_tool", "client_tools", "메모리 도구", "Memory tool", "memory_20250818 → tool_use{memory view}",
       "memory_20250818 → tool_use{memory view}", _DOC + "agents-and-tools/tool-use/memory-tool", ALL, "evidence"),
    _f("text_editor", "client_tools", "텍스트 에디터", "Text editor", "text_editor_20250728 → tool_use{str_replace_based_edit_tool}",
       "text_editor_20250728 → tool_use{str_replace_based_edit_tool}", _DOC + "agents-and-tools/tool-use/text-editor-tool", ALL, "evidence"),
    # --- tool infrastructure ---
    _f("agent_skills", "tool_infra", "Agent Skills", "Agent Skills", "container.skills[pdf] + code_execution → container.id",
       "container.skills[pdf] + code_execution → container.id", _DOC + "agents-and-tools/agent-skills/overview", CP_BETA_ONLY, "evidence"),
    _f("fine_grained_tool_streaming", "tool_infra", "세분화 도구 스트리밍", "Fine-grained tool streaming",
       "eager_input_streaming + stream → input_json_delta 2개 이상", "eager_input_streaming + stream → 2+ input_json_delta",
       _DOC + "agents-and-tools/tool-use/fine-grained-tool-streaming", ALL, "evidence"),
    _f("mcp_connector", "tool_infra", "MCP 커넥터", "MCP connector", "mcp_servers + mcp_toolset → mcp_tool_use (공개 MCP 서버)",
       "mcp_servers + mcp_toolset → mcp_tool_use (public MCP server)", _DOC + "agents-and-tools/mcp-connector", CP_BETA_ONLY, "evidence",
       "서버 도달 실패는 inconclusive"),
    _f("programmatic_tool_calling", "tool_infra", "프로그래매틱 도구 호출", "Programmatic tool calling",
       "code_execution_20260120 + allowed_callers → tool_use.caller", "code_execution_20260120 + allowed_callers → tool_use.caller",
       _DOC + "agents-and-tools/tool-use/programmatic-tool-calling", CP_ONLY, "evidence"),
    _f("tool_search", "tool_infra", "도구 검색", "Tool search", "tool_search_tool_regex + defer_loading → tool_search_tool_result",
       "tool_search_tool_regex + defer_loading → tool_search_tool_result", _DOC + "agents-and-tools/tool-use/tool-search-tool",
       {"cp": "ga", "mantle": "ga", "bedrock_invoke": "ga", "bedrock_converse": "no"}, "evidence", "AWS: InvokeModel only"),
    # --- context management ---
    _f("compaction", "context", "컴팩션", "Compaction", "beta compact-2026-01-12 + edits[compact_20260112] 수락",
       "beta compact-2026-01-12 + edits[compact_20260112] accepted", _DOC + "build-with-claude/compaction",
       {"cp": "beta", "mantle": "beta", "bedrock_invoke": "beta", "bedrock_converse": "no"}, "acceptance", "AWS: Converse 미지원"),
    _f("context_editing", "context", "컨텍스트 편집", "Context editing", "clear_thinking_20251015 → context_management.applied_edits",
       "clear_thinking_20251015 → context_management.applied_edits", _DOC + "build-with-claude/context-editing",
       {"cp": "beta", "mantle": "beta", "bedrock_invoke": "beta", "bedrock_converse": "unknown"}, "evidence"),
    _f("automatic_prompt_caching", "context", "자동 프롬프트 캐싱", "Automatic prompt caching",
       "최상위 cache_control + 안정 프리픽스 2회 → cache_creation/cache_read", "Top-level cache_control, 2 calls → cache_creation/cache_read",
       _DOC + "build-with-claude/prompt-caching#automatic-caching", ALL, "evidence"),
    _f("prompt_caching_5m", "context", "프롬프트 캐싱 5분", "Prompt caching (5m)", "블록 cache_control 2회 → cache_read > 0",
       "Block cache_control, 2 calls → cache_read > 0", _DOC + "build-with-claude/prompt-caching", ALL, "evidence"),
    _f("prompt_caching_1h", "context", "프롬프트 캐싱 1시간", "Prompt caching (1h)", "ttl 1h → ephemeral_1h_input_tokens 또는 2차 read",
       "ttl 1h → ephemeral_1h_input_tokens or read on 2nd call", _DOC + "build-with-claude/prompt-caching#1-hour-cache-duration", ALL, "evidence"),
    _f("token_counting", "context", "토큰 카운트", "Token counting", "count_tokens → input_tokens > 0",
       "count_tokens → input_tokens > 0", _DOC + "build-with-claude/token-counting", ALL, "evidence"),
    # --- files & endpoints ---
    _f("files_api", "files_endpoints", "Files API", "Files API", "업로드 → 조회 → 삭제",
       "Upload → get → delete", _DOC + "build-with-claude/files", CP_BETA_ONLY, "evidence"),
    _f("models_api", "files_endpoints", "Models API", "Models API", "GET /v1/models/{id} → id 일치 + capabilities",
       "GET /v1/models/{id} → id match + capabilities", _DOC + "api/models/list", CP_ONLY, "evidence"),
]
FEATURE_IDS = [f["id"] for f in FEATURES]
_FEATURE_BY_ID = {f["id"]: f for f in FEATURES}

# Converse가 표현할 수 없는 피처 → not_applicable (변환 오류로 판정을 오염시키지 않기 위해 호출하지 않음)
_CONVERSE_NOT_EXPRESSIBLE = frozenset({
    "bash_tool", "browser_use", "computer_use", "memory_tool", "text_editor",
    "fine_grained_tool_streaming", "automatic_prompt_caching", "context_editing",
    "tool_search", "compaction", "mcp_connector", "programmatic_tool_calling", "agent_skills",
    "advisor_tool", "code_execution", "web_fetch", "web_search",
})
# 검증 경로가 없는 조합 → skipped
_SKIPPED = frozenset({("context_window_1m", "mantle"), ("context_window_1m", "bedrock_invoke"),
                      ("context_window_1m", "bedrock_converse")})


def documented_for(feature_id: str, surface: str) -> str:
    return _FEATURE_BY_ID[feature_id]["documented"][surface]


def is_applicable(feature_id: str, surface: str, model_key: str) -> tuple[bool, str | None]:
    """(실행 여부, 미실행 사유 상태). 사유는 'not_applicable' | 'skipped'."""
    if model_id_for(surface, model_key) is None:
        return False, "not_applicable"
    if surface == "bedrock_converse" and feature_id in _CONVERSE_NOT_EXPRESSIBLE:
        return False, "not_applicable"
    if (feature_id, surface) in _SKIPPED:
        return False, "skipped"
    return True, None


def na_reason(feature_id: str, surface: str, model_key: str) -> str:
    if model_id_for(surface, model_key) is None:
        return _MODEL_BY_KEY[model_key].get("mantle_reason", "모델 미제공")
    if surface == "bedrock_converse" and feature_id in _CONVERSE_NOT_EXPRESSIBLE:
        return "Converse API에는 이 피처를 표현하는 필드가 없음"
    if (feature_id, surface) in _SKIPPED:
        return "capability 엔드포인트 없음 — 실전송 검증은 비용상 비활성"
    return ""
