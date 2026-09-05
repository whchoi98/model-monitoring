# Claude API Features Verification Menu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/claude-features` menu that runs the 33 documented "Build with Claude" features (+4 core +Models API) against Claude Platform on AWS, Bedrock Mantle `/anthropic`, Bedrock InvokeModel and Bedrock Converse for Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5, storing execution evidence and flagging documented-vs-observed drift.

**Architecture:** New sibling package `backend/claude_features/` (catalog → transports → probes → engine → runner) that sends one canonical Anthropic Messages JSON body through four transports (raw httpx for CP/Mantle, boto3 for Bedrock), stores results in new `feature_runs`/`feature_results` tables, exposes `/api/features/*`, and is rendered by `ClaudeFeaturesPanel` (copy-adapted from `ParityPanel`). A daily EventBridge Fargate task (`features_runner --once`) plus a JWT manual trigger run it.

**Tech Stack:** Python 3.11 (FastAPI, SQLAlchemy 2, httpx, boto3, aws-bedrock-token-generator), Next.js 14 / React 18 / Tailwind, CDK v2 TypeScript, pytest (python3.12 locally), vitest.

**Spec:** `docs/superpowers/specs/2026-09-05-claude-features-verify-design.md`

## Global Constraints

- Backend files that FastAPI imports for `Depends` typing (`routers/features.py`) must NOT use `from __future__ import annotations`; pure modules (`claude_features/*.py`, `features_runner.py`) may.
- Never send `temperature`/`top_p`/`top_k` — Fable 5.1/5, Opus 5, Sonnet 5 return 400 on non-default sampling.
- Fable 5.1 rejects forced `tool_choice` (`type: tool`/`any`) → use `parity.catalog.supports_forced_tool_choice(model_id)`; on False use `{"type":"auto"}` + explicit prompt instruction.
- Mantle column: region `ap-northeast-1` (env `MANTLE_ANTHROPIC_REGION`, default fixed), FM ids `anthropic.claude-*`; Fable 5.1 is `not_applicable` (US GovCloud only).
- Bedrock runtime: region `ap-northeast-2`, profile ids `global.anthropic.claude-*`; InvokeModel body gets `anthropic_version: "bedrock-2023-05-31"` and betas in body `anthropic_beta: [...]`.
- CP on AWS: `https://aws-external-anthropic.{ANTHROPIC_AWS_REGION|us-east-2}.api.aws`, headers `x-api-key: $ANTHROPIC_API_KEY`, `anthropic-workspace-id: $ANTHROPIC_WORKSPACE_ID`, `anthropic-version: 2023-06-01`, betas via `anthropic-beta` (comma-joined).
- Status vocabulary: `supported | unsupported | broken | inconclusive | skipped | not_applicable`. Verdict: `match | drift | undocumented | none`.
- Prompt-caching pad must exceed 1,024 tokens (Sonnet 5 minimum); use ≥1,500-token pad.
- Version bump target: `v2.23.0` in `frontend/src/lib/version.ts`, `frontend/package.json`, `backend/main.py`, `README.md` badge, `CLAUDE.md` overview, `CHANGELOG.md`.
- Tests: backend `cd backend && python3.12 -m pytest tests/test_claude_features.py -q`; frontend `cd frontend && npx vitest run src/lib/claudeFeatures.test.ts`; CDK `cd cdk && npx jest test/scheduler-stack.test.ts`.
- Commit after every task on branch `feat/claude-features-verify` (already created; spec committed as `9aed77c`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/claude_features/__init__.py` | package marker |
| `backend/claude_features/catalog.py` | SURFACES, MODELS, GROUPS, FEATURES (39 rows with `documented` + `verification`), `is_applicable()`, `model_id_for()`, `documented_for()` |
| `backend/claude_features/engine.py` | pure: `verdict()`, `aggregate_cell()`, `diff_runs()`, extra unsupported markers `classify()` wrapping `parity.engine.classify_error`, evidence checks (`has_block`, `find_block`, `cache_read`, `cache_created`) |
| `backend/claude_features/transports.py` | `NormalizedResponse`, `Transport` protocol, `CpTransport`, `MantleTransport`, `BedrockInvokeTransport`, `BedrockConverseTransport`, `build_transport(surface)`; pure helpers `invoke_body()`, `beta_header()` |
| `backend/claude_features/probes.py` | `ProbeOutcome`, `run_probe()`, `PROBES: dict[feature_id, fn]`; one function per feature |
| `backend/claude_features/runner.py` | `run_features(...) -> run_id`, `smoke(...)` (no DB) |
| `backend/features_runner.py` | CLI `--once | --smoke` |
| `backend/routers/features.py` | `/api/features/{catalog,latest,evidence,trigger}` |
| `backend/models.py` | `FeatureRun`, `FeatureResult` |
| `backend/database.py` | import new models in `create_tables()` |
| `backend/main.py` | include router; version 2.23.0 |
| `backend/tests/test_claude_features.py` | catalog/engine/transport-pure/probe-evidence tests |
| `frontend/src/lib/claudeFeatures.ts` + `.test.ts` | types, status/verdict styles, `aggregateCell`, `buildGroups` |
| `frontend/src/lib/api.ts` | `fetchFeaturesCatalog/Latest/Evidence`, `triggerFeaturesRun` |
| `frontend/src/components/ClaudeFeaturesPanel.tsx` | page panel |
| `frontend/src/app/claude-features/page.tsx` | page shell |
| `frontend/src/components/AppHeader.tsx` | nav item |
| `cdk/lib/stacks/scheduler-stack.ts`, `cdk/lib/stacks/app-services-stack.ts`, `cdk/test/scheduler-stack.test.ts` | task def + schedule + env + tests |
| `docs/decisions/ADR-026-claude-api-feature-verification-matrix.md`, `CHANGELOG.md`, `README.md`, `CLAUDE.md`, `docs/architecture.md`, `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `frontend/CLAUDE.md`, `frontend/src/components/CLAUDE.md` | docs |

---

### Task 1: Catalog + pure engine

**Files:**
- Create: `backend/claude_features/__init__.py` (empty)
- Create: `backend/claude_features/catalog.py`
- Create: `backend/claude_features/engine.py`
- Test: `backend/tests/test_claude_features.py`

**Interfaces:**
- Produces: `SURFACES = ["cp","mantle","bedrock_invoke","bedrock_converse"]`; `SURFACE_META[surface] -> {label, region_env, default_region, kind}`; `MODELS: list[dict]` with keys `key`(`fable-5-1|fable-5|opus-5|sonnet-5`), `label`, `cp`, `mantle`(None for fable-5-1), `bedrock`; `GROUPS: list[dict]`; `FEATURES: list[dict]` (39) with keys `id, group, label_ko, label_en, desc_ko, desc_en, doc_url, documented: dict[surface,str], verification, notes`; `FEATURE_IDS`; `is_applicable(feature_id, surface, model_key) -> tuple[bool, str|None]` (False + reason → record `not_applicable`/`skipped`); `model_id_for(surface, model_key) -> str|None`; `documented_for(feature_id, surface) -> str`.
- Engine: `verdict(documented: str, observed: str) -> str`; `aggregate_cell(statuses: list[str]) -> dict{status, counts}`; `diff_runs(prev: dict[tuple,str], cur: dict[tuple,str]) -> list[dict]` (key `(feature, surface, model_key)`); `classify(error_message) -> str`; `find_block(blocks, type_) -> dict|None`; `has_block(blocks, type_) -> bool`; `usage_int(usage, *keys) -> int`.

- [ ] **Step 1: Write failing tests** — create `backend/tests/test_claude_features.py`:

```python
"""Claude API Features 검증 엔진 — 카탈로그·판정·전송기 순수 로직 테스트 (v2.23.0)."""

import pytest

from claude_features import catalog, engine


def test_surfaces_and_models():
    assert catalog.SURFACES == ["cp", "mantle", "bedrock_invoke", "bedrock_converse"]
    keys = [m["key"] for m in catalog.MODELS]
    assert keys == ["fable-5-1", "fable-5", "opus-5", "sonnet-5"]
    assert catalog.model_id_for("cp", "fable-5-1") == "claude-fable-5-1"
    assert catalog.model_id_for("mantle", "fable-5-1") is None  # US GovCloud only
    assert catalog.model_id_for("mantle", "opus-5") == "anthropic.claude-opus-5"
    assert catalog.model_id_for("bedrock_invoke", "sonnet-5") == "global.anthropic.claude-sonnet-5"
    assert catalog.model_id_for("bedrock_converse", "sonnet-5") == "global.anthropic.claude-sonnet-5"


def test_feature_catalog_shape():
    assert len(catalog.FEATURES) == 39
    ids = catalog.FEATURE_IDS
    assert ids[:4] == ["messages_basic", "streaming", "system_prompt", "tool_use"]
    assert ids[-1] == "models_api"
    groups = {g["id"] for g in catalog.GROUPS}
    for f in catalog.FEATURES:
        assert f["group"] in groups
        assert f["doc_url"].startswith("https://platform.claude.com/")
        assert set(f["documented"]) == set(catalog.SURFACES)
        assert set(f["documented"].values()) <= {"ga", "beta", "no", "unknown"}
        assert f["verification"] in {"evidence", "acceptance", "capability", "negative"}
        for k in ("label_ko", "label_en", "desc_ko", "desc_en"):
            assert f[k]


def test_is_applicable_rules():
    ok, reason = catalog.is_applicable("messages_basic", "mantle", "fable-5-1")
    assert (ok, reason) == (False, "not_applicable")  # GovCloud-only
    assert catalog.is_applicable("messages_basic", "mantle", "fable-5") == (True, None)
    # Converse cannot express Anthropic-defined tools / top-level cache_control
    assert catalog.is_applicable("bash_tool", "bedrock_converse", "opus-5") == (False, "not_applicable")
    assert catalog.is_applicable("automatic_prompt_caching", "bedrock_converse", "opus-5") == (False, "not_applicable")
    # 1M capability only checkable on CP
    assert catalog.is_applicable("context_window_1m", "cp", "opus-5") == (True, None)
    assert catalog.is_applicable("context_window_1m", "mantle", "opus-5") == (False, "skipped")
    # extended thinking: adaptive-only models → probe still runs (negative check)
    assert catalog.is_applicable("extended_thinking", "cp", "fable-5") == (True, None)


def test_documented_defaults_from_overview():
    assert catalog.documented_for("web_search", "cp") == "ga"
    assert catalog.documented_for("web_search", "bedrock_invoke") == "no"
    assert catalog.documented_for("structured_outputs", "mantle") == "no"
    assert catalog.documented_for("compaction", "bedrock_converse") == "no"
    assert catalog.documented_for("server_side_fallback", "cp") == "unknown"


@pytest.mark.parametrize("documented,observed,expected", [
    ("ga", "supported", "match"), ("beta", "supported", "match"),
    ("no", "unsupported", "match"), ("ga", "unsupported", "drift"),
    ("beta", "broken", "drift"), ("no", "supported", "undocumented"),
    ("ga", "inconclusive", "none"), ("unknown", "supported", "none"),
    ("ga", "not_applicable", "none"), ("no", "broken", "none"),
])
def test_verdict(documented, observed, expected):
    assert engine.verdict(documented, observed) == expected


def test_aggregate_cell():
    assert engine.aggregate_cell(["supported", "supported"])["status"] == "supported"
    assert engine.aggregate_cell(["supported", "unsupported"])["status"] == "partial"
    assert engine.aggregate_cell(["supported", "broken"])["status"] == "broken"
    assert engine.aggregate_cell(["not_applicable", "skipped"])["status"] == "not_applicable"
    assert engine.aggregate_cell([])["status"] == "empty"
    assert engine.aggregate_cell(["supported", "inconclusive"])["counts"]["inconclusive"] == 1


def test_diff_runs_keys():
    prev = {("a", "cp", "opus-5"): "supported"}
    cur = {("a", "cp", "opus-5"): "broken", ("b", "cp", "opus-5"): "supported"}
    changes = engine.diff_runs(prev, cur)
    assert changes == [
        {"feature": "a", "surface": "cp", "model_key": "opus-5", "before": "supported", "after": "broken"},
        {"feature": "b", "surface": "cp", "model_key": "opus-5", "before": None, "after": "supported"},
    ]


def test_classify_extends_parity_markers():
    assert engine.classify("400: output_config.format: Extra inputs are not permitted") == "unsupported"
    assert engine.classify("tool_choice: type \"tool\" and \"any\" are not supported for this model.") == "unsupported"
    assert engine.classify("'claude-opus-5' does not support tool types: computer_20241022") == "unsupported"
    assert engine.classify("Unexpected value(s) `foo` for the `anthropic-beta` header") == "unsupported"
    assert engine.classify("AccessDeniedException: not authorized") == "broken"
    assert engine.classify("ReadTimeout") == "broken"


def test_block_helpers():
    blocks = [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "hi"}]
    assert engine.has_block(blocks, "thinking")
    assert engine.find_block(blocks, "text")["text"] == "hi"
    assert engine.find_block(blocks, "tool_use") is None
    assert engine.usage_int({"cache_read_input_tokens": 12}, "cache_read_input_tokens", "cacheReadInputTokens") == 12
    assert engine.usage_int({"cacheReadInputTokens": 5}, "cache_read_input_tokens", "cacheReadInputTokens") == 5
    assert engine.usage_int(None, "x") == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3.12 -m pytest tests/test_claude_features.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'claude_features'`

- [ ] **Step 3: Write `backend/claude_features/__init__.py`** (empty file) and `backend/claude_features/catalog.py`:

```python
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
```

- [ ] **Step 4: Write `backend/claude_features/engine.py`**:

```python
"""Claude API Features 판정 순수 로직 (v2.23.0) — 외부 의존 없음, 단위 테스트 대상.

observed ∈ supported | unsupported | broken | inconclusive | skipped | not_applicable
verdict  ∈ match | drift | undocumented | none   (문서 기대치 vs 실측)
"""

from __future__ import annotations

from typing import Any

from parity.engine import classify_error as _parity_classify

STATUSES = ("supported", "unsupported", "broken", "inconclusive", "skipped", "not_applicable")

# parity._UNSUPPORTED_MARKERS 위에 본 기능에서 추가로 확인된 "깨끗한 거부" 시그니처
_EXTRA_UNSUPPORTED = (
    "unknown field",
    "not supported for this model",
    "does not support tool types",
    "for the `anthropic-beta` header",
    "unexpected value(s)",
    "is not available on this platform",
    "not available on",
    "no route",
)


def classify(error_message: str | None) -> str:
    if not error_message:
        return "broken"
    if _parity_classify(error_message) == "unsupported":
        return "unsupported"
    msg = error_message.lower()
    return "unsupported" if any(m in msg for m in _EXTRA_UNSUPPORTED) else "broken"


def verdict(documented: str, observed: str) -> str:
    if documented == "unknown" or observed in ("inconclusive", "skipped", "not_applicable"):
        return "none"
    if documented in ("ga", "beta"):
        if observed == "supported":
            return "match"
        return "drift"  # unsupported | broken
    # documented == "no"
    if observed == "unsupported":
        return "match"
    if observed == "supported":
        return "undocumented"
    return "none"


def aggregate_cell(statuses: list[str]) -> dict[str, Any]:
    counts = {s: 0 for s in STATUSES}
    for s in statuses:
        if s in counts:
            counts[s] += 1
    probed = counts["supported"] + counts["unsupported"] + counts["broken"] + counts["inconclusive"]
    if not statuses:
        status = "empty"
    elif probed == 0:
        status = "not_applicable" if counts["not_applicable"] else "skipped"
    elif counts["broken"]:
        status = "broken"
    elif counts["supported"] == probed:
        status = "supported"
    elif counts["unsupported"] == probed:
        status = "unsupported"
    elif counts["inconclusive"] == probed:
        status = "inconclusive"
    else:
        status = "partial"
    return {"status": status, "counts": counts, "probed": probed}


def diff_runs(prev: dict[tuple, str], cur: dict[tuple, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in sorted(cur):
        before, after = prev.get(key), cur[key]
        if before == after:
            continue
        feature, surface, model_key = key
        out.append({"feature": feature, "surface": surface, "model_key": model_key, "before": before, "after": after})
    return out


def find_block(blocks: list[dict] | None, type_: str) -> dict | None:
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") == type_:
            return b
    return None


def has_block(blocks: list[dict] | None, type_: str) -> bool:
    return find_block(blocks, type_) is not None


def usage_int(usage: dict | None, *keys: str) -> int:
    if not usage:
        return 0
    for k in keys:
        v = usage.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def text_of(blocks: list[dict] | None) -> str:
    return "".join(b.get("text", "") for b in blocks or [] if isinstance(b, dict) and b.get("type") == "text")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_claude_features.py -q`
Expected: all PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/claude_features/__init__.py backend/claude_features/catalog.py backend/claude_features/engine.py backend/tests/test_claude_features.py
git commit -m "feat(features): Claude API Features 카탈로그(39행×4 surface) + 판정 순수 로직 — v2.23.0"
```

---

### Task 2: Transports (one Messages body → four endpoints)

**Files:**
- Create: `backend/claude_features/transports.py`
- Test: `backend/tests/test_claude_features.py` (append)

**Interfaces:**
- Consumes: `catalog.region_for(surface)`, `prober._anthropic_base_url()`, `prober._anthropic_default_headers()`.
- Produces:
  - `class TransportError(Exception)`: attrs `status_code: int|None`, `message: str`; `str()` → `"HTTP {status}: {message}"`.
  - `@dataclass NormalizedResponse`: `content: list[dict]`, `usage: dict`, `stop_reason: str|None`, `top: dict` (top-level fields minus content/usage), `events: list[dict]` (stream events; `[]` for non-stream), `raw: Any`.
  - `class Transport` (base): attrs `surface: str`, `region: str`, `routes: frozenset[str]`; methods `messages(model_id, body, betas=(), stream=False) -> NormalizedResponse`, `count_tokens(model_id, body, betas=()) -> dict`, `request(method, path, json=None, betas=(), files=None) -> tuple[int, Any]` (only http transports), `converse(model_id, stream=False, **kw) -> NormalizedResponse` (converse only), `count_tokens_converse(model_id, **kw) -> dict`.
  - `build_transport(surface) -> Transport`; pure helpers `invoke_body(body, betas) -> dict`, `beta_header(betas) -> dict`, `parse_sse(text) -> list[dict]`, `normalize_anthropic(obj, events=None) -> NormalizedResponse`, `normalize_converse(resp) -> NormalizedResponse`.

- [ ] **Step 1: Append failing tests**

```python
from claude_features import transports as T


def test_invoke_body_strips_model_and_injects_version_and_betas():
    body = {"model": "x", "stream": True, "max_tokens": 16, "messages": []}
    out = T.invoke_body(body, ["beta-a", "beta-b"])
    assert "model" not in out and "stream" not in out
    assert out["anthropic_version"] == "bedrock-2023-05-31"
    assert out["anthropic_beta"] == ["beta-a", "beta-b"]
    assert T.invoke_body({"messages": []}, []).get("anthropic_beta") is None


def test_beta_header_joins_with_comma():
    assert T.beta_header([]) == {}
    assert T.beta_header(["a", "b"]) == {"anthropic-beta": "a,b"}


def test_parse_sse_extracts_json_events():
    text = 'event: message_start\ndata: {"type":"message_start"}\n\nevent: ping\ndata: {"type":"ping"}\n\ndata: [DONE]\n\n'
    evs = T.parse_sse(text)
    assert [e["type"] for e in evs] == ["message_start", "ping"]


def test_normalize_converse_maps_blocks_and_usage():
    resp = {
        "output": {"message": {"content": [
            {"text": "hello"},
            {"toolUse": {"toolUseId": "t1", "name": "echo", "input": {"text": "X"}}},
            {"reasoningContent": {"reasoningText": {"text": "hmm"}}},
            {"citationsContent": {"content": [{"text": "cited"}], "citations": [{"title": "d"}]}},
        ]}},
        "usage": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 3, "cacheWriteInputTokens": 7},
        "stopReason": "end_turn",
    }
    n = T.normalize_converse(resp)
    types = [b["type"] for b in n.content]
    assert types == ["text", "tool_use", "thinking", "text"]
    assert n.content[1]["input"] == {"text": "X"} and n.content[1]["name"] == "echo"
    assert n.content[3]["citations"] == [{"title": "d"}]
    assert n.usage == {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 7}
    assert n.stop_reason == "end_turn"


def test_normalize_anthropic_separates_top_level():
    obj = {"id": "m", "content": [{"type": "text", "text": "a"}], "usage": {"input_tokens": 1},
           "stop_reason": "end_turn", "container": {"id": "c1"}}
    n = T.normalize_anthropic(obj)
    assert n.top["container"] == {"id": "c1"} and "content" not in n.top
    assert n.stop_reason == "end_turn" and n.events == []


def test_routes_per_surface(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    assert "batches" in T.CpTransport().routes
    assert T.BedrockInvokeTransport.routes == frozenset({"messages", "count_tokens"})
    assert T.BedrockConverseTransport.routes == frozenset({"converse", "count_tokens"})
```

- [ ] **Step 2: Run to verify failure** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q` → FAIL `cannot import name 'transports'`.

- [ ] **Step 3: Write `backend/claude_features/transports.py`**

```python
"""세 Claude-on-AWS 엔드포인트 전송기 (v2.23.0) — 하나의 Anthropic Messages JSON 본문을 그대로 흘린다.

SDK를 쓰지 않는 이유: requirements.txt의 anthropic>=0.40.0 미고정 → 빌드 시 1.x 메이저 업.
raw httpx(CP/Mantle) + boto3(Bedrock)로 본문/헤더를 직접 제어해 판정을 SDK 표면 변화에서 격리한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

ANTHROPIC_VERSION = "2023-06-01"
BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"
_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)


class TransportError(Exception):
    def __init__(self, status_code: int | None, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}" if status_code else message)


@dataclass
class NormalizedResponse:
    content: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None
    top: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    raw: Any = None


# ---------------------------------------------------------------- pure helpers

def beta_header(betas) -> dict[str, str]:
    betas = [b for b in (betas or []) if b]
    return {"anthropic-beta": ",".join(betas)} if betas else {}


def invoke_body(body: dict, betas) -> dict:
    """Anthropic Messages 본문 → Bedrock InvokeModel 본문 (model/stream 제거, version·anthropic_beta 주입)."""
    out = {k: v for k, v in body.items() if k not in ("model", "stream")}
    out["anthropic_version"] = BEDROCK_ANTHROPIC_VERSION
    betas = [b for b in (betas or []) if b]
    if betas:
        out["anthropic_beta"] = betas
    return out


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except ValueError:
            continue
    return events


def normalize_anthropic(obj: dict, events: list[dict] | None = None) -> NormalizedResponse:
    top = {k: v for k, v in obj.items() if k not in ("content", "usage")}
    return NormalizedResponse(content=list(obj.get("content") or []), usage=dict(obj.get("usage") or {}),
                              stop_reason=obj.get("stop_reason"), top=top, events=list(events or []), raw=obj)


def assemble_stream(events: list[dict]) -> dict:
    """SSE 이벤트 → 최종 message dict (content 블록·usage·stop_reason 재조립)."""
    msg: dict = {"content": [], "usage": {}}
    blocks: dict[int, dict] = {}
    for ev in events:
        t = ev.get("type")
        if t == "message_start":
            m = ev.get("message") or {}
            msg.update({k: v for k, v in m.items() if k not in ("content",)})
            msg["usage"] = dict(m.get("usage") or {})
        elif t == "content_block_start":
            blocks[ev["index"]] = dict(ev.get("content_block") or {})
            if blocks[ev["index"]].get("type") == "tool_use":
                blocks[ev["index"]].setdefault("_json", "")
        elif t == "content_block_delta":
            d = ev.get("delta") or {}
            b = blocks.setdefault(ev["index"], {"type": "text", "text": ""})
            if d.get("type") == "text_delta":
                b["text"] = b.get("text", "") + d.get("text", "")
            elif d.get("type") == "input_json_delta":
                b["_json"] = b.get("_json", "") + d.get("partial_json", "")
            elif d.get("type") == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + d.get("thinking", "")
            elif d.get("type") == "citations_delta":
                b.setdefault("citations", []).append(d.get("citation"))
        elif t == "message_delta":
            d = ev.get("delta") or {}
            if d.get("stop_reason"):
                msg["stop_reason"] = d["stop_reason"]
            for k, v in (ev.get("usage") or {}).items():
                msg["usage"][k] = v
            for k in ("context_management", "container", "stop_details"):
                if k in d:
                    msg[k] = d[k]
    for i in sorted(blocks):
        b = blocks[i]
        if "_json" in b:
            try:
                b["input"] = json.loads(b.pop("_json") or "{}")
            except ValueError:
                b["input"] = b.pop("_json")
        msg["content"].append(b)
    return msg


def normalize_converse(resp: dict) -> NormalizedResponse:
    blocks: list[dict] = []
    for b in ((resp.get("output") or {}).get("message") or {}).get("content", []):
        if "text" in b:
            blocks.append({"type": "text", "text": b["text"]})
        elif "toolUse" in b:
            tu = b["toolUse"]
            blocks.append({"type": "tool_use", "id": tu.get("toolUseId"), "name": tu.get("name"), "input": tu.get("input")})
        elif "reasoningContent" in b:
            rc = b["reasoningContent"]
            blocks.append({"type": "thinking", "thinking": (rc.get("reasoningText") or {}).get("text", ""),
                           "signature": (rc.get("reasoningText") or {}).get("signature")})
        elif "citationsContent" in b:
            cc = b["citationsContent"]
            blocks.append({"type": "text", "text": "".join(c.get("text", "") for c in cc.get("content", [])),
                           "citations": cc.get("citations", [])})
        else:
            blocks.append({"type": next(iter(b.keys()), "unknown"), "raw": b})
    u = resp.get("usage") or {}
    usage = {"input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0),
             "cache_read_input_tokens": u.get("cacheReadInputTokens", 0),
             "cache_creation_input_tokens": u.get("cacheWriteInputTokens", 0)}
    top = {k: v for k, v in resp.items() if k not in ("output", "usage", "ResponseMetadata")}
    return NormalizedResponse(content=blocks, usage=usage, stop_reason=resp.get("stopReason"), top=top, raw=resp)


def _snippet_bytes(b: bytes | str, n: int = 800) -> str:
    s = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
    return s[:n]


# ---------------------------------------------------------------- base

class Transport:
    surface: str = ""
    region: str = ""
    routes: frozenset[str] = frozenset()

    def messages(self, model_id: str, body: dict, betas=(), stream: bool = False) -> NormalizedResponse:
        raise NotImplementedError

    def count_tokens(self, model_id: str, body: dict, betas=()) -> dict:
        raise NotImplementedError

    def request(self, method: str, path: str, json: Any = None, betas=(), files=None, data=None) -> tuple[int, Any]:
        raise TransportError(None, f"no route: {self.surface} has no HTTP endpoint for {path}")


class _HttpTransport(Transport):
    base_url: str = ""
    routes = frozenset({"messages", "count_tokens", "batches", "files", "models", "skills"})

    def _headers(self, betas=()) -> dict[str, str]:
        raise NotImplementedError

    def request(self, method: str, path: str, json: Any = None, betas=(), files=None, data=None) -> tuple[int, Any]:
        headers = self._headers(betas)
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.request(method, self.base_url + path, json=json, headers=headers, files=files, data=data)
        parsed: Any
        try:
            parsed = r.json()
        except ValueError:
            parsed = _snippet_bytes(r.content)
        if r.status_code >= 400:
            msg = parsed if isinstance(parsed, str) else json.dumps(parsed, ensure_ascii=False)[:1500]
            raise TransportError(r.status_code, msg)
        return r.status_code, parsed

    def messages(self, model_id: str, body: dict, betas=(), stream: bool = False) -> NormalizedResponse:
        payload = {**body, "model": model_id}
        headers = self._headers(betas)
        if not stream:
            _, obj = self.request("POST", "/v1/messages", json=payload, betas=betas)
            return normalize_anthropic(obj)
        payload["stream"] = True
        with httpx.Client(timeout=_TIMEOUT) as c, c.stream("POST", self.base_url + "/v1/messages",
                                                            json=payload, headers=headers) as r:
            text = r.read().decode("utf-8", "replace")
            if r.status_code >= 400:
                raise TransportError(r.status_code, text[:1500])
        events = parse_sse(text)
        return normalize_anthropic(assemble_stream(events), events)

    def count_tokens(self, model_id: str, body: dict, betas=()) -> dict:
        payload = {k: v for k, v in body.items() if k not in ("max_tokens", "stream")}
        payload["model"] = model_id
        _, obj = self.request("POST", "/v1/messages/count_tokens", json=payload, betas=betas)
        return obj


class CpTransport(_HttpTransport):
    surface = "cp"

    def __init__(self, region: str | None = None):
        from claude_features.catalog import region_for
        from prober import _anthropic_default_headers
        self.region = region or region_for("cp")
        self.base_url = f"https://aws-external-anthropic.{self.region}.api.aws"
        self._api_key = os.environ["ANTHROPIC_API_KEY"]
        self._extra = _anthropic_default_headers()

    def _headers(self, betas=()) -> dict[str, str]:
        return {"x-api-key": self._api_key, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json", **self._extra, **beta_header(betas)}


class MantleTransport(_HttpTransport):
    surface = "mantle"

    def __init__(self, region: str | None = None):
        from aws_bedrock_token_generator import provide_token
        from claude_features.catalog import region_for
        self.region = region or region_for("mantle")
        self.base_url = f"https://bedrock-mantle.{self.region}.api.aws/anthropic"
        self._token = provide_token(region=self.region)  # 런 동안 재사용 (≤12h)

    def _headers(self, betas=()) -> dict[str, str]:
        return {"x-api-key": self._token, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json", **beta_header(betas)}


def _boto_client(region: str):
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=region,
                        config=Config(connect_timeout=10, read_timeout=90, retries={"max_attempts": 2, "mode": "standard"}))


def _client_error(exc: Exception) -> TransportError:
    resp = getattr(exc, "response", None) or {}
    err = resp.get("Error") or {}
    status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    code, msg = err.get("Code", type(exc).__name__), err.get("Message", str(exc))
    return TransportError(status, f"{code}: {msg}")


class BedrockInvokeTransport(Transport):
    surface = "bedrock_invoke"
    routes = frozenset({"messages", "count_tokens"})

    def __init__(self, region: str | None = None):
        from claude_features.catalog import region_for
        self.region = region or region_for("bedrock_invoke")
        self.client = _boto_client(self.region)

    def messages(self, model_id: str, body: dict, betas=(), stream: bool = False) -> NormalizedResponse:
        native = invoke_body(body, betas)
        try:
            if not stream:
                r = self.client.invoke_model(modelId=model_id, body=json.dumps(native))
                return normalize_anthropic(json.loads(r["body"].read()))
            r = self.client.invoke_model_with_response_stream(modelId=model_id, body=json.dumps(native))
            events = [json.loads(e["chunk"]["bytes"]) for e in r["body"] if "chunk" in e]
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        return normalize_anthropic(assemble_stream(events), events)

    def count_tokens(self, model_id: str, body: dict, betas=()) -> dict:
        native = invoke_body({k: v for k, v in body.items() if k != "max_tokens"}, betas)
        try:
            r = self.client.count_tokens(modelId=model_id, input={"invokeModel": {"body": json.dumps(native)}})
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        return {"input_tokens": r.get("inputTokens")}


class BedrockConverseTransport(Transport):
    surface = "bedrock_converse"
    routes = frozenset({"converse", "count_tokens"})

    def __init__(self, region: str | None = None):
        from claude_features.catalog import region_for
        self.region = region or region_for("bedrock_converse")
        self.client = _boto_client(self.region)

    def converse(self, model_id: str, stream: bool = False, **kw) -> NormalizedResponse:
        try:
            if not stream:
                return normalize_converse(self.client.converse(modelId=model_id, **kw))
            r = self.client.converse_stream(modelId=model_id, **kw)
            events = list(r["stream"])
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        text, stop, usage = "", None, {}
        for ev in events:
            if "contentBlockDelta" in ev:
                text += (ev["contentBlockDelta"].get("delta") or {}).get("text", "")
            elif "messageStop" in ev:
                stop = ev["messageStop"].get("stopReason")
            elif "metadata" in ev:
                usage = ev["metadata"].get("usage") or {}
        n = normalize_converse({"output": {"message": {"content": [{"text": text}]}}, "usage": usage, "stopReason": stop})
        n.events = events
        return n

    def count_tokens_converse(self, model_id: str, **kw) -> dict:
        try:
            r = self.client.count_tokens(modelId=model_id, input={"converse": kw})
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _client_error(exc) from exc
            raise
        return {"input_tokens": r.get("inputTokens")}


def build_transport(surface: str) -> Transport:
    return {"cp": CpTransport, "mantle": MantleTransport,
            "bedrock_invoke": BedrockInvokeTransport, "bedrock_converse": BedrockConverseTransport}[surface]()
```

- [ ] **Step 4: Run tests** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add backend/claude_features/transports.py backend/tests/test_claude_features.py && git commit -m "feat(features): CP/Mantle/InvokeModel/Converse 전송기 — 단일 Messages 본문 4경로 라우팅"`

---

### Task 3: Probes part A — helpers, core, model capabilities

**Files:**
- Create: `backend/claude_features/probes.py`
- Modify: `backend/claude_features/engine.py` (add markers `"http 404"`, `"http 405"`, `"not found"` to `_EXTRA_UNSUPPORTED`)
- Test: `backend/tests/test_claude_features.py` (append)

**Interfaces:**
- Consumes: `transports.Transport` API (`messages`, `count_tokens`, `request`, `converse`, `count_tokens_converse`, `.surface`, `.routes`), `engine.*`, `parity.catalog.supports_forced_tool_choice`, `parity.engine.check_tool_roundtrip / check_json_object / check_canary`.
- Produces: `CANARY`, `CACHE_PAD`, `@dataclass ProbeOutcome(status, latency_ms, evidence, error)`, `run_probe(fn, transport, model_id, model_key) -> ProbeOutcome`, `PROBES: dict[str, Callable[[Transport, str, str], tuple[bool | str, dict]]]` — each probe returns `(passed_or_status, evidence)` where `True → supported`, `False → broken`, or an explicit status string (`"inconclusive" | "not_applicable" | "unsupported" | "supported"`). Helpers reused by Task 4: `_msg(prompt, **kw)`, `_tool_choice(model_id, name)`, `_echo_tool(strict=False, eager=False)`, `_req(model_id, body, betas=(), **extra)`, `_route_or_unsupported(t, route)`, `_tiny_pdf(text) -> bytes`, `_content_deltas(events, delta_type)`.

- [ ] **Step 1: Append failing tests**

```python
from claude_features import probes as P


def test_tiny_pdf_is_valid_pdf_containing_text():
    pdf = P._tiny_pdf("HELLO_7391")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"HELLO_7391" in pdf


def test_cache_pad_is_long_enough():
    # 최소 캐시 토큰(Sonnet 5 = 1,024)을 넉넉히 넘겨야 함 — 영문 4자≈1토큰 기준 1,500토큰 ≈ 6,000자
    assert len(P.CACHE_PAD) >= 6000


def test_tool_choice_respects_fable_51():
    assert P._tool_choice("claude-fable-5-1", "echo") == {"type": "auto"}
    assert P._tool_choice("anthropic.claude-opus-5", "echo") == {"type": "tool", "name": "echo"}


class _FakeT:
    surface = "cp"
    routes = frozenset({"messages", "count_tokens"})

    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def messages(self, model_id, body, betas=(), stream=False):
        self.calls.append(("messages", body, tuple(betas), stream))
        if self.exc:
            raise self.exc
        return self.resp

    def count_tokens(self, model_id, body, betas=()):
        return {"input_tokens": 42}


def test_run_probe_classifies_transport_error():
    from claude_features.transports import TransportError
    t = _FakeT(exc=TransportError(400, 'thinking.type.enabled is not supported for this model'))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.status == "unsupported" and out.error.startswith("HTTP 400")
    assert out.evidence["request"]["model"] == "claude-opus-5"


def test_run_probe_supported_and_evidence():
    from claude_features.transports import NormalizedResponse
    t = _FakeT(resp=NormalizedResponse(content=[{"type": "text", "text": "pong"}], usage={"input_tokens": 3}, stop_reason="end_turn"))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.status == "supported" and out.evidence["response_snippet"] == "pong"


def test_extended_thinking_rejection_is_not_applicable():
    from claude_features.transports import TransportError
    t = _FakeT(exc=TransportError(400, '"thinking.type.enabled" is not supported for this model. Use adaptive.'))
    out = P.run_probe(P.PROBES["extended_thinking"], t, "claude-fable-5", "fable-5")
    assert out.status == "not_applicable"


def test_route_less_endpoint_feature_is_unsupported_without_call():
    t = _FakeT()
    t.surface, t.routes = "bedrock_invoke", frozenset({"messages", "count_tokens"})
    out = P.run_probe(P.PROBES["batch_processing"], t, "global.anthropic.claude-opus-5", "opus-5")
    assert out.status == "unsupported" and out.calls == [] if hasattr(out, "calls") else True
    assert t.calls == [] and "no route" in out.evidence["reason"]
```

- [ ] **Step 2: Run to verify failure** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q` → FAIL `cannot import name 'probes'`.

- [ ] **Step 3: Extend `engine._EXTRA_UNSUPPORTED`** — add three markers so `TransportError("HTTP 404: …")` from Mantle route probes classifies as unsupported:

```python
_EXTRA_UNSUPPORTED = (
    "unknown field",
    "not supported for this model",
    "does not support tool types",
    "for the `anthropic-beta` header",
    "unexpected value(s)",
    "is not available on this platform",
    "not available on",
    "no route",
    "http 404",
    "http 405",
    "not found",
)
```

- [ ] **Step 4: Write `backend/claude_features/probes.py` (part A)**

```python
"""피처별 프로브 (v2.23.0) — 전송기 무관. 본문은 Anthropic Messages 스키마로만 작성한다.

각 프로브: (transport, model_id, model_key) -> (passed|status, evidence)
  True → supported / False → broken(증거 실패) / "inconclusive" | "not_applicable" | "unsupported" | "supported"
run_probe()가 시간 측정·오류 분류·요청 스냅샷을 공통 처리한다.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from claude_features import engine
from claude_features.transports import NormalizedResponse, Transport, TransportError
from parity.catalog import supports_forced_tool_choice
from parity.engine import check_canary, check_json_object, check_tool_roundtrip

CANARY = "FEATURES_OK_7391"
_MAX = 256
_JSON_MAX = 512
_THINK_MAX = 3000
_TOOL_MAX = 1024
# 캐시 최소 토큰(Fable/Opus 5 = 512, Sonnet 5 = 1,024)을 넉넉히 넘기는 영문 패딩 (~1,800 토큰)
CACHE_PAD = ("This paragraph is stable context padding for the Claude API Features prompt-caching probe. "
             "It exists only to exceed the minimum cacheable prefix length of every monitored model. ") * 40
_JSON_SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
                "required": ["city", "country"], "additionalProperties": False}
_ECHO_SCHEMA = {"type": "object", "properties": {"text": {"type": "string", "description": "text to echo"}},
                "required": ["text"], "additionalProperties": False}
_TOOL_PROMPT = f"Call the `echo` tool exactly once with text set to '{CANARY}'. Do not answer in prose."
_SYSTEM_PROMPT = f"Begin every reply with the exact token {CANARY} followed by a space."
_BASIC_PROMPT = "Reply with the single word: pong"


@dataclass
class ProbeOutcome:
    status: str
    latency_ms: float | None = None
    evidence: dict = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------- helpers

def _msg(prompt: Any, **kw: Any) -> dict:
    content = prompt if isinstance(prompt, list) else prompt
    body = {"max_tokens": _MAX, "messages": [{"role": "user", "content": content}]}
    body.update(kw)
    return body


def _tool_choice(model_id: str, name: str) -> dict:
    return {"type": "tool", "name": name} if supports_forced_tool_choice(model_id) else {"type": "auto"}


def _echo_tool(strict: bool = False, eager: bool = False) -> dict:
    tool: dict = {"name": "echo", "description": "Returns the given text unchanged.", "input_schema": _ECHO_SCHEMA}
    if strict:
        tool["strict"] = True
    if eager:
        tool["eager_input_streaming"] = True
    return tool


def _trim(v: Any) -> Any:
    if isinstance(v, str) and len(v) > 200:
        return f"{v[:200]}… ({len(v)} chars)"
    if isinstance(v, dict):
        return {k: _trim(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_trim(x) for x in v]
    return v


def _req(model_id: str, body: dict | None = None, betas=(), **extra: Any) -> dict:
    snap: dict = {"model": model_id}
    if body:
        snap.update(_trim(body))
    if betas:
        snap["anthropic_beta"] = list(betas)
    snap.update(_trim(extra))
    return snap


def _snippet(n: NormalizedResponse, limit: int = 300) -> str:
    return engine.text_of(n.content)[:limit]


def _content_deltas(events: list[dict], delta_type: str) -> int:
    return sum(1 for e in events if e.get("type") == "content_block_delta"
               and (e.get("delta") or {}).get("type") == delta_type)


def _route_or_unsupported(t: Transport, route: str) -> tuple[str, dict] | None:
    """라우트가 없는 전송기(Bedrock 두 열)는 호출 없이 unsupported로 판정."""
    if route not in t.routes:
        return "unsupported", {"reason": f"no route: {t.surface} endpoint has no {route} API"}
    return None


def _tiny_pdf(text: str) -> bytes:
    """텍스트 한 줄이 든 최소 1페이지 PDF (Helvetica, ASCII만)."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def run_probe(fn: Callable, t: Transport, model_id: str, model_key: str) -> ProbeOutcome:
    start = time.time()
    try:
        result, evidence = fn(t, model_id, model_key)
        latency = (time.time() - start) * 1000
        evidence.setdefault("request", _req(model_id))
        if result is True:
            return ProbeOutcome("supported", latency, evidence)
        if result is False:
            evidence.setdefault("reason", "evidence check failed")
            return ProbeOutcome("broken", latency, evidence)
        return ProbeOutcome(str(result), latency, evidence)
    except TransportError as exc:
        latency = (time.time() - start) * 1000
        msg = str(exc)
        return ProbeOutcome(engine.classify(msg), latency, {"request": _req(model_id)}, error=msg[:1500])
    except Exception as exc:  # noqa: BLE001 — 네트워크/파싱 오류 전체
        latency = (time.time() - start) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        return ProbeOutcome(engine.classify(msg), latency, {"request": _req(model_id)}, error=msg[:1500])


# ---------------------------------------------------------------- core

def probe_messages_basic(t, model_id, model_key):
    body = _msg(_BASIC_PROMPT)
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX}}
        n = t.converse(model_id, **kw)
        return bool(engine.text_of(n.content).strip()), {"request": _req(model_id, kw), "response_snippet": _snippet(n), "stop_reason": n.stop_reason}
    n = t.messages(model_id, body)
    return bool(engine.text_of(n.content).strip()), {"request": _req(model_id, body), "response_snippet": _snippet(n), "stop_reason": n.stop_reason}


def probe_streaming(t, model_id, model_key):
    prompt = "Count from 1 to 30 separated by commas."
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": _MAX}}
        n = t.converse(model_id, stream=True, **kw)
        deltas = sum(1 for e in n.events if "contentBlockDelta" in e)
        return deltas >= 2, {"request": _req(model_id, kw, stream=True), "content_events": deltas}
    body = _msg(prompt)
    n = t.messages(model_id, body, stream=True)
    deltas = _content_deltas(n.events, "text_delta")
    return deltas >= 2, {"request": _req(model_id, body, stream=True), "content_events": deltas, "response_snippet": _snippet(n)}


def probe_system_prompt(t, model_id, model_key):
    prompt = "Say hello in one short sentence."
    if t.surface == "bedrock_converse":
        kw = {"system": [{"text": _SYSTEM_PROMPT}], "messages": [{"role": "user", "content": [{"text": prompt}]}],
              "inferenceConfig": {"maxTokens": _MAX}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(prompt, system=_SYSTEM_PROMPT)
        n = t.messages(model_id, kw)
    text = engine.text_of(n.content)
    return check_canary(text, CANARY), {"request": _req(model_id, kw), "response_snippet": text[:300]}


def _tool_call_evidence(n: NormalizedResponse, name: str) -> tuple[bool, dict]:
    tu = next((b for b in n.content if b.get("type") == "tool_use" and b.get("name") == name), None)
    call = {"name": name, "arguments": tu.get("input")} if tu else None
    return check_tool_roundtrip(call, CANARY), {"tool_call": _trim(call), "stop_reason": n.stop_reason}


def probe_tool_use(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        choice = {"tool": {"name": "echo"}} if supports_forced_tool_choice(model_id) else {"auto": {}}
        kw = {"messages": [{"role": "user", "content": [{"text": _TOOL_PROMPT}]}], "inferenceConfig": {"maxTokens": _TOOL_MAX},
              "toolConfig": {"tools": [{"toolSpec": {"name": "echo", "description": "Returns the given text unchanged.",
                                                     "inputSchema": {"json": _ECHO_SCHEMA}}}], "toolChoice": choice}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(_TOOL_PROMPT, max_tokens=_TOOL_MAX, tools=[_echo_tool()], tool_choice=_tool_choice(model_id, "echo"))
        n = t.messages(model_id, kw)
    ok, ev = _tool_call_evidence(n, "echo")
    return ok, {"request": _req(model_id, kw), **ev}


# ---------------------------------------------------------------- model capabilities

def probe_context_window_1m(t, model_id, model_key):
    gate = _route_or_unsupported(t, "models")
    if gate:
        return gate
    _, obj = t.request("GET", f"/v1/models/{model_id}")
    caps = {k: obj.get(k) for k in ("max_input_tokens", "max_tokens")}
    return obj.get("max_input_tokens") == 1_000_000, {"request": _req(model_id, path=f"/v1/models/{model_id}"), **caps}


def probe_adaptive_thinking(t, model_id, model_key):
    prompt = "What is the third prime number greater than 100? Think it through, then answer with just the number."
    thinking = {"type": "adaptive", "display": "summarized"}
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": _THINK_MAX},
              "additionalModelRequestFields": {"thinking": thinking, "output_config": {"effort": "medium"}}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(prompt, max_tokens=_THINK_MAX, thinking=thinking, output_config={"effort": "medium"})
        n = t.messages(model_id, kw)
    th = engine.find_block(n.content, "thinking")
    return th is not None, {"request": _req(model_id, kw), "content_types": [b.get("type") for b in n.content],
                            "thinking_chars": len((th or {}).get("thinking") or ""), "response_snippet": _snippet(n)}


def probe_extended_thinking(t, model_id, model_key):
    prompt = "What is 17 * 23? Answer with just the number."
    thinking = {"type": "enabled", "budget_tokens": 1024}
    try:
        if t.surface == "bedrock_converse":
            kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": 2048},
                  "additionalModelRequestFields": {"thinking": thinking}}
            n = t.converse(model_id, **kw)
        else:
            kw = _msg(prompt, max_tokens=2048, thinking=thinking)
            n = t.messages(model_id, kw)
    except TransportError as exc:
        low = str(exc).lower()
        if "thinking" in low and ("not supported" in low or "adaptive" in low or "validation" in low):
            return "not_applicable", {"request": _req(model_id, thinking=thinking),
                                      "reason": "adaptive-only model rejects budget_tokens as documented", "error": str(exc)[:500]}
        raise
    return engine.has_block(n.content, "thinking"), {"request": _req(model_id, kw), "content_types": [b.get("type") for b in n.content]}


def probe_batch_processing(t, model_id, model_key):
    gate = _route_or_unsupported(t, "batches")
    if gate:
        return gate
    req = {"requests": [{"custom_id": "features-probe-1",
                         "params": {"model": model_id, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]}}]}
    _, created = t.request("POST", "/v1/messages/batches", json=req)
    bid = created.get("id")
    _, got = t.request("GET", f"/v1/messages/batches/{bid}")
    try:
        t.request("POST", f"/v1/messages/batches/{bid}/cancel")
    except TransportError:
        pass
    ok = bool(bid) and got.get("processing_status") in ("in_progress", "canceling", "ended")
    return ok, {"request": _req(model_id, req), "batch_id": bid, "processing_status": got.get("processing_status")}


def _doc_question(t, model_id, doc_block: dict, converse_block: dict, question: str) -> tuple[NormalizedResponse, dict]:
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [converse_block, {"text": question}]}], "inferenceConfig": {"maxTokens": _JSON_MAX}}
        return t.converse(model_id, **kw), kw
    kw = _msg([doc_block, {"type": "text", "text": question}], max_tokens=_JSON_MAX)
    return t.messages(model_id, kw), kw


def probe_citations(t, model_id, model_key):
    text = f"The code word is {CANARY}. The sky is blue. Water boils at 100 degrees Celsius."
    doc = {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": text},
           "title": "Probe document", "citations": {"enabled": True}}
    cdoc = {"document": {"format": "txt", "name": "probe", "source": {"text": text}, "citations": {"enabled": True}}}
    n, kw = _doc_question(t, model_id, doc, cdoc, "What is the code word? Cite the document.")
    cited = [b for b in n.content if b.get("type") == "text" and b.get("citations")]
    return bool(cited), {"request": _req(model_id, kw), "citation_blocks": len(cited),
                         "first_citation": _trim((cited[0]["citations"][0] if cited else None)), "response_snippet": _snippet(n)}


def probe_search_results(t, model_id, model_key):
    text = f"The code word is {CANARY}."
    sr = {"type": "search_result", "source": "https://example.com/probe", "title": "Probe result",
          "content": [{"type": "text", "text": text}], "citations": {"enabled": True}}
    csr = {"searchResult": {"source": "https://example.com/probe", "title": "Probe result",
                            "content": [{"text": text}], "citations": {"enabled": True}}}
    n, kw = _doc_question(t, model_id, sr, csr, "What is the code word? Cite your source.")
    cites = [c for b in n.content if b.get("type") == "text" for c in (b.get("citations") or [])]
    ok = any((c or {}).get("type") == "search_result_location" for c in cites) or (t.surface == "bedrock_converse" and bool(cites))
    return ok, {"request": _req(model_id, kw), "citations": _trim(cites[:2]), "response_snippet": _snippet(n)}


def probe_pdf_support(t, model_id, model_key):
    pdf = _tiny_pdf(CANARY)
    b64 = base64.b64encode(pdf).decode()
    doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    cdoc = {"document": {"format": "pdf", "name": "probe", "source": {"bytes": pdf}}}
    n, kw = _doc_question(t, model_id, doc, cdoc, "What code word is written in the document? Reply with only the word.")
    text = engine.text_of(n.content)
    return check_canary(text, CANARY), {"request": _req(model_id, {"document": f"pdf {len(pdf)} bytes"}), "response_snippet": text[:300]}


def probe_data_residency(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
              "additionalModelRequestFields": {"inference_geo": "us"}}
        n = t.converse(model_id, **kw)
        return n.usage.get("inference_geo") == "us", {"request": _req(model_id, kw), "usage": n.usage}
    kw = _msg(_BASIC_PROMPT, inference_geo="us")
    n = t.messages(model_id, kw)
    ev = {"request": _req(model_id, kw), "usage_inference_geo": n.usage.get("inference_geo")}
    try:
        t.messages(model_id, _msg(_BASIC_PROMPT, inference_geo="mars"))
        ev["negative_control"] = "accepted (not validated)"
    except TransportError as exc:
        ev["negative_control"] = f"rejected: {str(exc)[:160]}"
    return n.usage.get("inference_geo") == "us", ev


def probe_effort(t, model_id, model_key):
    def call(effort: str):
        if t.surface == "bedrock_converse":
            kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
                  "additionalModelRequestFields": {"output_config": {"effort": effort}}}
            return t.converse(model_id, **kw), kw
        kw = _msg(_BASIC_PROMPT, output_config={"effort": effort})
        return t.messages(model_id, kw), kw

    n, kw = call("low")
    ev = {"request": _req(model_id, kw), "output_tokens_low": n.usage.get("output_tokens"), "response_snippet": _snippet(n)}
    try:
        call("ultra")
        ev["negative_control"] = "accepted (effort not validated)"
        return "inconclusive", ev
    except TransportError as exc:
        ev["negative_control"] = f"rejected: {str(exc)[:200]}"
        return "effort" in str(exc).lower(), ev


def probe_fallback_credit(t, model_id, model_key):
    beta = "fallback-credit-2026-06-01" if t.surface.startswith("bedrock") else "fallback-credit-2026-07-01"
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
              "additionalModelRequestFields": {"anthropic_beta": [beta]}}
        n = t.converse(model_id, **kw)
        return True, {"request": _req(model_id, kw), "stop_reason": n.stop_reason, "verification": "acceptance"}
    kw = _msg(_BASIC_PROMPT)
    n = t.messages(model_id, kw, betas=[beta])
    return True, {"request": _req(model_id, kw, betas=[beta]), "stop_reason": n.stop_reason,
                  "stop_details": n.top.get("stop_details"), "verification": "acceptance"}


def probe_server_side_fallback(t, model_id, model_key):
    beta = "server-side-fallback-2026-07-01"
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX},
              "additionalModelRequestFields": {"fallbacks": "default", "anthropic_beta": [beta]}}
        n = t.converse(model_id, **kw)
        return True, {"request": _req(model_id, kw), "model": n.top.get("model"), "verification": "acceptance"}
    kw = _msg(_BASIC_PROMPT, fallbacks="default")
    n = t.messages(model_id, kw, betas=[beta])
    return True, {"request": _req(model_id, kw, betas=[beta]), "served_model": n.top.get("model"),
                  "content_types": [b.get("type") for b in n.content], "verification": "acceptance"}


def probe_structured_outputs(t, model_id, model_key):
    prompt = "Give the capital city of South Korea and its country as JSON."
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": {"maxTokens": _JSON_MAX},
              "outputConfig": {"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {"schema": json.dumps(_JSON_SCHEMA)}}}}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(prompt, max_tokens=_JSON_MAX, output_config={"format": {"type": "json_schema", "schema": _JSON_SCHEMA}})
        n = t.messages(model_id, kw)
    text = engine.text_of(n.content)
    return check_json_object(text, "city"), {"request": _req(model_id, kw), "response_snippet": text[:300]}


def probe_strict_tool_use(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        choice = {"tool": {"name": "echo"}} if supports_forced_tool_choice(model_id) else {"auto": {}}
        kw = {"messages": [{"role": "user", "content": [{"text": _TOOL_PROMPT}]}], "inferenceConfig": {"maxTokens": _TOOL_MAX},
              "toolConfig": {"tools": [{"toolSpec": {"name": "echo", "description": "Returns the given text unchanged.",
                                                     "inputSchema": {"json": _ECHO_SCHEMA}, "strict": True}}], "toolChoice": choice}}
        n = t.converse(model_id, **kw)
    else:
        kw = _msg(_TOOL_PROMPT, max_tokens=_TOOL_MAX, tools=[_echo_tool(strict=True)], tool_choice=_tool_choice(model_id, "echo"))
        n = t.messages(model_id, kw)
    tu = next((b for b in n.content if b.get("type") == "tool_use" and b.get("name") == "echo"), None)
    inp = (tu or {}).get("input")
    ok = isinstance(inp, dict) and set(inp) == {"text"} and CANARY in str(inp.get("text"))
    return ok, {"request": _req(model_id, kw), "tool_input": _trim(inp), "stop_reason": n.stop_reason}


PROBES: dict[str, Callable] = {
    "messages_basic": probe_messages_basic, "streaming": probe_streaming, "system_prompt": probe_system_prompt,
    "tool_use": probe_tool_use, "context_window_1m": probe_context_window_1m, "adaptive_thinking": probe_adaptive_thinking,
    "batch_processing": probe_batch_processing, "citations": probe_citations, "data_residency": probe_data_residency,
    "effort": probe_effort, "fallback_credit": probe_fallback_credit, "pdf_support": probe_pdf_support,
    "search_results": probe_search_results, "server_side_fallback": probe_server_side_fallback,
    "structured_outputs": probe_structured_outputs, "strict_tool_use": probe_strict_tool_use,
    "extended_thinking": probe_extended_thinking,
}
```

- [ ] **Step 5: Run tests** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add backend/claude_features && git add backend/tests/test_claude_features.py && git commit -m "feat(features): 프로브 A — 코어 4 + 모델 기능 13 (전송기 무관 Messages 본문)"`

---

### Task 4: Probes part B — server/client tools, tool infrastructure, context management, files & endpoints

**Files:**
- Modify: `backend/claude_features/probes.py` (append probes + extend `PROBES`)
- Modify: `backend/claude_features/transports.py` (`_HttpTransport.request`: drop `content-type` when `files`/`data` given)
- Test: `backend/tests/test_claude_features.py` (append)

**Interfaces:**
- Consumes: Task 3 helpers (`_msg`, `_tool_choice`, `_echo_tool`, `_req`, `_route_or_unsupported`, `_snippet`, `_content_deltas`, `CACHE_PAD`, `CANARY`).
- Produces: complete `PROBES` covering all 39 `catalog.FEATURE_IDS`; helper `_with_fallback(t, model_id, attempts) -> tuple[NormalizedResponse, dict]` (tries request variants in order, records `attempts[]`).

- [ ] **Step 1: Append failing tests**

```python
def test_probes_cover_every_catalog_feature():
    assert set(P.PROBES) == set(catalog.FEATURE_IDS)


def test_advisor_pairing():
    assert P._advisor_model("fable-5-1") == "claude-fable-5-1"
    assert P._advisor_model("sonnet-5") == "claude-opus-5"
    assert P._advisor_model("opus-5") == "claude-opus-5"


def test_http_request_drops_json_content_type_for_multipart(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    seen = {}

    class _R:
        status_code = 200
        content = b"{}"
        def json(self):
            return {"id": "file_1", "type": "file"}

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            seen.update(kw)
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    t.request("POST", "/v1/files", files={"file": ("a.txt", b"x", "text/plain")})
    assert "content-type" not in {k.lower() for k in seen["headers"]}
```

- [ ] **Step 2: Run to verify failure** — FAIL on `test_probes_cover_every_catalog_feature` (missing 22 ids) and `_advisor_model`.

- [ ] **Step 3: Patch `transports._HttpTransport.request`** — replace the `headers = self._headers(betas)` line with:

```python
        headers = self._headers(betas)
        if files is not None or data is not None:
            headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
```

- [ ] **Step 4: Append part B to `probes.py`**

```python
# ---------------------------------------------------------------- shared: beta/tool fallbacks

def _with_fallback(t: Transport, model_id: str, attempts: list[tuple[str, dict, list[str]]]) -> tuple[NormalizedResponse, dict]:
    """attempts = [(label, body, betas), ...] — 앞 시도가 '명시적 미지원' 400이면 다음 시도. 마지막 실패는 raise."""
    log: list[dict] = []
    for i, (label, body, betas) in enumerate(attempts):
        try:
            n = t.messages(model_id, body, betas=betas)
            log.append({"attempt": label, "result": "ok"})
            return n, {"attempts": log, "request": _req(model_id, body, betas=betas)}
        except TransportError as exc:
            log.append({"attempt": label, "result": str(exc)[:200]})
            if i == len(attempts) - 1 or engine.classify(str(exc)) != "unsupported":
                raise TransportError(exc.status_code, f"{exc.message} | attempts={json.dumps(log, ensure_ascii=False)[:600]}") from exc
    raise RuntimeError("unreachable")


def _tool_use_named(n: NormalizedResponse, *names: str, toolset: str | None = None) -> dict | None:
    for b in n.content:
        if b.get("type") != "tool_use":
            continue
        if b.get("name") in names or (toolset and b.get("toolset_name") == toolset):
            return b
    return None


def _server_tool_evidence(n: NormalizedResponse, tool_name: str, result_type: str) -> tuple[bool | str, dict]:
    used = any(b.get("type") == "server_tool_use" and b.get("name") == tool_name for b in n.content)
    result = engine.find_block(n.content, result_type)
    content = (result or {}).get("content")
    ev = {"server_tool_used": used, "result_type": (result or {}).get("type"), "stop_reason": n.stop_reason,
          "response_snippet": _snippet(n), "content_types": [b.get("type") for b in n.content]}
    if not used:
        return "inconclusive", {**ev, "reason": "model did not invoke the server tool"}
    if isinstance(content, dict) and content.get("type", "").endswith("_error"):
        return "inconclusive", {**ev, "reason": f"server tool error: {content.get('error_code')}"}
    return result is not None, ev


# ---------------------------------------------------------------- server-side tools

_ADVISOR_FOR = {"fable-5-1": "claude-fable-5-1", "fable-5": "claude-fable-5", "opus-5": "claude-opus-5", "sonnet-5": "claude-opus-5"}


def _advisor_model(model_key: str) -> str:
    return _ADVISOR_FOR[model_key]


def probe_advisor_tool(t, model_id, model_key):
    tool = {"type": "advisor_20260301", "name": "advisor", "model": _advisor_model(model_key), "max_uses": 1}
    prompt = "Before answering, consult the advisor tool once. Question: which number is larger, 7391 or 3917? Answer briefly."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[tool], tool_choice=_tool_choice(model_id, "advisor"))
    n = t.messages(model_id, kw, betas=["advisor-tool-2026-03-01"])
    used = any(b.get("type") == "server_tool_use" and b.get("name") == "advisor" for b in n.content)
    res = engine.find_block(n.content, "advisor_tool_result")
    ev = {"request": _req(model_id, kw, betas=["advisor-tool-2026-03-01"]), "server_tool_used": used,
          "advisor_result_type": ((res or {}).get("content") or {}).get("type"), "stop_reason": n.stop_reason}
    if not used:
        return "inconclusive", {**ev, "reason": "model did not call advisor"}
    return res is not None, ev


def probe_code_execution(t, model_id, model_key):
    prompt = "Use the code execution tool to run this Python: print(7391*3). Then reply with only the printed number."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "code_execution_20260521", "name": "code_execution"}])
    n = t.messages(model_id, kw)
    res = engine.find_block(n.content, "bash_code_execution_tool_result")
    stdout = str(((res or {}).get("content") or {}).get("stdout", ""))
    status, ev = _server_tool_evidence(n, "bash_code_execution", "bash_code_execution_tool_result")
    ev.update({"request": _req(model_id, kw), "stdout": stdout[:200], "container": n.top.get("container")})
    if status is True:
        return "22173" in stdout or "22173" in engine.text_of(n.content), ev
    return status, ev


def probe_web_fetch(t, model_id, model_key):
    url = "https://www.iana.org/help/example-domains"
    prompt = f"Fetch {url} with the web_fetch tool and tell me its first heading in one line."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 1}])
    n = t.messages(model_id, kw)
    status, ev = _server_tool_evidence(n, "web_fetch", "web_fetch_tool_result")
    return status, {"request": _req(model_id, kw), **ev}


def probe_web_search(t, model_id, model_key):
    prompt = "Use the web_search tool once to find the current list of Anthropic Claude models, then name one model in one line."
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 1}])
    n = t.messages(model_id, kw)
    status, ev = _server_tool_evidence(n, "web_search", "web_search_tool_result")
    res = engine.find_block(n.content, "web_search_tool_result")
    ev["results"] = len((res or {}).get("content") or []) if isinstance((res or {}).get("content"), list) else 0
    return status, {"request": _req(model_id, kw), **ev}


# ---------------------------------------------------------------- client-side tools (definition acceptance + tool_use emission)

def _client_tool_probe(t, model_id, tool: dict, prompt: str, tool_name: str, betas: list[str] | None = None,
                       fallback_betas: list[str] | None = None):
    kw = _msg(prompt, max_tokens=_TOOL_MAX, tools=[tool], tool_choice=_tool_choice(model_id, tool_name))
    attempts = [("no-beta" if not betas else ",".join(betas), kw, betas or [])]
    if fallback_betas:
        attempts.append((",".join(fallback_betas), kw, fallback_betas))
    n, ev = _with_fallback(t, model_id, attempts)
    tu = _tool_use_named(n, tool_name)
    ev.update({"tool_call": _trim({"name": (tu or {}).get("name"), "input": (tu or {}).get("input")}), "stop_reason": n.stop_reason})
    if tu is None:
        return "inconclusive", {**ev, "reason": "tool definition accepted but the model did not call it"}
    return True, ev


def probe_bash_tool(t, model_id, model_key):
    return _client_tool_probe(t, model_id, {"type": "bash_20250124", "name": "bash"},
                              f"Use the bash tool to run: echo {CANARY}", "bash", fallback_betas=["computer-use-2025-01-24"])


def probe_text_editor(t, model_id, model_key):
    return _client_tool_probe(t, model_id, {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
                              "Use the text editor tool to view the file /tmp/probe.txt", "str_replace_based_edit_tool",
                              fallback_betas=["computer-use-2025-01-24"])


def probe_memory_tool(t, model_id, model_key):
    return _client_tool_probe(t, model_id, {"type": "memory_20250818", "name": "memory"},
                              "Check your memory directory first, then say hello.", "memory",
                              fallback_betas=["context-management-2025-06-27"])


def probe_browser_use(t, model_id, model_key):
    kw = _msg("Take a screenshot of the current browser page using the browser tools.", max_tokens=_TOOL_MAX,
              tools=[{"type": "browser_toolset_20260801"}])
    n = t.messages(model_id, kw)
    tu = _tool_use_named(n, toolset="browser")
    ev = {"request": _req(model_id, kw), "tool_call": _trim(tu), "stop_reason": n.stop_reason}
    return (True, ev) if tu else ("inconclusive", {**ev, "reason": "toolset accepted but no browser tool_use"})


def probe_computer_use(t, model_id, model_key):
    prompt = "Take a screenshot of the screen using the computer tool."
    toolset = _msg(prompt, max_tokens=_TOOL_MAX, tools=[{"type": "computer_toolset_20260801"}])
    legacy = _msg(prompt, max_tokens=_TOOL_MAX,
                  tools=[{"type": "computer_20251124", "name": "computer", "display_width_px": 1024, "display_height_px": 768}],
                  tool_choice=_tool_choice(model_id, "computer"))
    n, ev = _with_fallback(t, model_id, [("computer_toolset_20260801", toolset, []),
                                         ("computer_20251124+beta", legacy, ["computer-use-2025-11-24"])])
    tu = _tool_use_named(n, "computer", toolset="computer")
    ev.update({"tool_call": _trim(tu), "stop_reason": n.stop_reason})
    return (True, ev) if tu else ("inconclusive", {**ev, "reason": "tool accepted but no computer tool_use"})


# ---------------------------------------------------------------- tool infrastructure

def probe_agent_skills(t, model_id, model_key):
    kw = _msg("In one line, list the names of the skills available to you.", max_tokens=_TOOL_MAX,
              tools=[{"type": "code_execution_20260521", "name": "code_execution"}],
              container={"skills": [{"type": "anthropic", "skill_id": "pdf", "version": "latest"}]})
    n = t.messages(model_id, kw)
    ev = {"request": _req(model_id, kw), "container": n.top.get("container"), "response_snippet": _snippet(n)}
    if "skills" in t.routes:
        try:
            _, skills = t.request("GET", "/v1/skills")
            ev["skills_listed"] = len(skills.get("data", [])) if isinstance(skills, dict) else None
        except TransportError as exc:
            ev["skills_listed"] = f"error: {str(exc)[:120]}"
    return bool((n.top.get("container") or {}).get("id")), ev


def probe_fine_grained_tool_streaming(t, model_id, model_key):
    long_text = ("lorem ipsum dolor sit amet " * 12).strip()
    kw = _msg(f"Call the echo tool once with text set to exactly: {long_text}", max_tokens=_TOOL_MAX,
              tools=[_echo_tool(eager=True)], tool_choice=_tool_choice(model_id, "echo"))
    n = t.messages(model_id, kw, stream=True)
    deltas = _content_deltas(n.events, "input_json_delta")
    return deltas >= 2, {"request": _req(model_id, kw, stream=True), "input_json_deltas": deltas,
                         "tool_call": _trim(_tool_use_named(n, "echo"))}


def probe_mcp_connector(t, model_id, model_key):
    url = os.environ.get("FEATURES_MCP_SERVER_URL", "https://mcp.deepwiki.com/mcp")
    kw = _msg("List the tools offered by the probe-mcp server and call one of them with a trivial input, then summarize in one line.",
              max_tokens=_TOOL_MAX, mcp_servers=[{"type": "url", "url": url, "name": "probe-mcp"}],
              tools=[{"type": "mcp_toolset", "mcp_server_name": "probe-mcp"}])
    try:
        n = t.messages(model_id, kw, betas=["mcp-client-2025-11-20"])
    except TransportError as exc:
        low = str(exc).lower()
        if any(k in low for k in ("connect", "unreachable", "timed out", "mcp server", "failed to")) and engine.classify(str(exc)) != "unsupported":
            return "inconclusive", {"request": _req(model_id, kw), "reason": f"MCP server unreachable: {str(exc)[:200]}"}
        raise
    used = engine.has_block(n.content, "mcp_tool_use")
    ev = {"request": _req(model_id, kw, betas=["mcp-client-2025-11-20"]), "mcp_tool_use": used,
          "mcp_tool_result": engine.has_block(n.content, "mcp_tool_result"), "response_snippet": _snippet(n)}
    return (True, ev) if used else ("inconclusive", {**ev, "reason": "MCP toolset accepted but no mcp_tool_use"})


def probe_programmatic_tool_calling(t, model_id, model_key):
    tool = {"name": "get_number", "description": "Returns a secret integer for the given index.",
            "input_schema": {"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"]},
            "allowed_callers": ["code_execution_20260120"]}
    kw = _msg("Write and run code that calls get_number for index 1, 2 and 3 and prints the sum.", max_tokens=2048,
              tools=[{"type": "code_execution_20260120", "name": "code_execution"}, tool])
    n = t.messages(model_id, kw)
    tu = next((b for b in n.content if b.get("type") == "tool_use" and (b.get("caller") or {}).get("type") == "code_execution_20260120"), None)
    ev = {"request": _req(model_id, kw), "container": n.top.get("container"), "caller": (tu or {}).get("caller"),
          "stop_reason": n.stop_reason, "content_types": [b.get("type") for b in n.content]}
    return (True, ev) if tu else ("inconclusive", {**ev, "reason": "no tool_use with code_execution caller"})


def probe_tool_search(t, model_id, model_key):
    deferred = [{"name": f"get_{k}", "description": d, "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                 "defer_loading": True}
                for k, d in (("weather", "Current weather for a city"), ("time", "Current time in a timezone"), ("stock", "Stock quote"))]
    kw = _msg("Find the tool that gives weather for Seoul and call it.", max_tokens=_TOOL_MAX,
              tools=[{"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"}, *deferred])
    betas = ["tool-search-tool-2025-10-19"] if t.surface == "bedrock_invoke" else []
    n = t.messages(model_id, kw, betas=betas)
    searched = any(b.get("type") == "server_tool_use" and b.get("name") == "tool_search_tool_regex" for b in n.content)
    ev = {"request": _req(model_id, kw, betas=betas), "tool_search_used": searched,
          "tool_search_result": engine.has_block(n.content, "tool_search_tool_result"),
          "called": (_tool_use_named(n, "get_weather") or {}).get("name"), "stop_reason": n.stop_reason}
    return (True, ev) if searched else ("inconclusive", {**ev, "reason": "tool search tool accepted but not used"})


# ---------------------------------------------------------------- context management

def probe_compaction(t, model_id, model_key):
    cm = {"edits": [{"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": 50000}}]}
    kw = _msg(_BASIC_PROMPT, context_management=cm)
    n = t.messages(model_id, kw, betas=["compact-2026-01-12"])
    ev = {"request": _req(model_id, kw, betas=["compact-2026-01-12"]), "verification": "acceptance", "stop_reason": n.stop_reason}
    if "models" in t.routes:
        try:
            _, m = t.request("GET", f"/v1/models/{model_id}")
            ev["capability_compact_20260112"] = (((m.get("capabilities") or {}).get("context_management") or {}).get("compact_20260112") or {}).get("supported")
        except TransportError as exc:
            ev["capability_compact_20260112"] = f"error: {str(exc)[:120]}"
    return True, ev


def probe_context_editing(t, model_id, model_key):
    cm = {"edits": [{"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 100000}}]}
    kw = _msg(_BASIC_PROMPT, context_management=cm)
    n = t.messages(model_id, kw, betas=["context-management-2025-06-27"])
    applied = (n.top.get("context_management") or {}).get("applied_edits")
    return applied is not None, {"request": _req(model_id, kw, betas=["context-management-2025-06-27"]),
                                 "applied_edits": applied, "stop_reason": n.stop_reason}


def _cache_pair(t, model_id, kw_builder) -> tuple[dict, dict, dict]:
    if t.surface == "bedrock_converse":
        kw = kw_builder()
        n1 = t.converse(model_id, **kw)
        n2 = t.converse(model_id, **kw)
    else:
        kw = kw_builder()
        n1 = t.messages(model_id, kw)
        n2 = t.messages(model_id, kw)
    return kw, n1.usage, n2.usage


def probe_automatic_prompt_caching(t, model_id, model_key):
    kw, u1, u2 = _cache_pair(t, model_id, lambda: _msg(_BASIC_PROMPT, system=CACHE_PAD, cache_control={"type": "ephemeral"}))
    created = engine.usage_int(u1, "cache_creation_input_tokens")
    read = engine.usage_int(u2, "cache_read_input_tokens")
    return (created > 0 or read > 0), {"request": _req(model_id, kw), "first_usage": u1, "second_usage": u2}


def probe_prompt_caching_5m(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        builder = lambda: {"system": [{"text": CACHE_PAD}, {"cachePoint": {"type": "default"}}],  # noqa: E731
                           "messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX}}
    else:
        builder = lambda: _msg(_BASIC_PROMPT, system=[{"type": "text", "text": CACHE_PAD, "cache_control": {"type": "ephemeral"}}])  # noqa: E731
    kw, u1, u2 = _cache_pair(t, model_id, builder)
    return engine.usage_int(u2, "cache_read_input_tokens") > 0, {"request": _req(model_id, kw), "first_usage": u1, "second_usage": u2}


def probe_prompt_caching_1h(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        builder = lambda: {"system": [{"text": CACHE_PAD}, {"cachePoint": {"type": "default", "ttl": "1h"}}],  # noqa: E731
                           "messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}], "inferenceConfig": {"maxTokens": _MAX}}
    else:
        builder = lambda: _msg(_BASIC_PROMPT, system=[{"type": "text", "text": CACHE_PAD, "cache_control": {"type": "ephemeral", "ttl": "1h"}}])  # noqa: E731
    kw, u1, u2 = _cache_pair(t, model_id, builder)
    one_h = engine.usage_int((u1.get("cache_creation") or {}) if isinstance(u1.get("cache_creation"), dict) else {}, "ephemeral_1h_input_tokens")
    read = engine.usage_int(u2, "cache_read_input_tokens")
    return (one_h > 0 or read > 0), {"request": _req(model_id, kw), "first_usage": u1, "second_usage": u2, "ephemeral_1h_input_tokens": one_h}


def probe_token_counting(t, model_id, model_key):
    if t.surface == "bedrock_converse":
        kw = {"messages": [{"role": "user", "content": [{"text": _BASIC_PROMPT}]}]}
        r = t.count_tokens_converse(model_id, **kw)
    else:
        kw = _msg(_BASIC_PROMPT)
        r = t.count_tokens(model_id, kw)
    n = r.get("input_tokens")
    return isinstance(n, int) and n > 0, {"request": _req(model_id, kw, endpoint="count_tokens"), "input_tokens": n}


# ---------------------------------------------------------------- files & endpoints

def probe_files_api(t, model_id, model_key):
    gate = _route_or_unsupported(t, "files")
    if gate:
        return gate
    _, up = t.request("POST", "/v1/files", files={"file": ("features-probe.txt", b"Claude API Features probe file.\n", "text/plain")})
    fid = up.get("id")
    ev = {"request": _req(model_id, endpoint="/v1/files"), "file_id": fid, "type": up.get("type")}
    try:
        _, got = t.request("GET", f"/v1/files/{fid}")
        ev["get_ok"] = got.get("id") == fid
    finally:
        try:
            t.request("DELETE", f"/v1/files/{fid}")
            ev["deleted"] = True
        except TransportError as exc:
            ev["deleted"] = f"error: {str(exc)[:120]}"
    return up.get("type") == "file" and bool(fid), ev


def probe_models_api(t, model_id, model_key):
    gate = _route_or_unsupported(t, "models")
    if gate:
        return gate
    _, m = t.request("GET", f"/v1/models/{model_id}")
    return m.get("id") == model_id and "capabilities" in m, {"request": _req(model_id, endpoint=f"/v1/models/{model_id}"),
                                                              "retrieved_id": m.get("id"), "capabilities": _trim(m.get("capabilities"))}


PROBES.update({
    "advisor_tool": probe_advisor_tool, "code_execution": probe_code_execution, "web_fetch": probe_web_fetch, "web_search": probe_web_search,
    "bash_tool": probe_bash_tool, "browser_use": probe_browser_use, "computer_use": probe_computer_use,
    "memory_tool": probe_memory_tool, "text_editor": probe_text_editor,
    "agent_skills": probe_agent_skills, "fine_grained_tool_streaming": probe_fine_grained_tool_streaming,
    "mcp_connector": probe_mcp_connector, "programmatic_tool_calling": probe_programmatic_tool_calling, "tool_search": probe_tool_search,
    "compaction": probe_compaction, "context_editing": probe_context_editing,
    "automatic_prompt_caching": probe_automatic_prompt_caching, "prompt_caching_5m": probe_prompt_caching_5m,
    "prompt_caching_1h": probe_prompt_caching_1h, "token_counting": probe_token_counting,
    "files_api": probe_files_api, "models_api": probe_models_api,
})
```

- [ ] **Step 5: Run tests** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q` → PASS; also `ruff check backend/claude_features` → clean.

- [ ] **Step 6: Commit** — `git add backend/claude_features backend/tests/test_claude_features.py && git commit -m "feat(features): 프로브 B — 서버/클라이언트 도구·도구 인프라·컨텍스트·Files/Models (39/39)"`

---

### Task 5: DB models, runner, CLI

**Files:**
- Modify: `backend/models.py` (append after `ParityResult`, before `GptBenchResult`)
- Modify: `backend/database.py:85-89` (`create_tables` import list)
- Create: `backend/claude_features/runner.py`
- Create: `backend/features_runner.py`
- Test: `backend/tests/test_claude_features.py` (append)

**Interfaces:**
- Produces: ORM `FeatureRun(id, started_at, finished_at, status, totals JSON, catalog_version TEXT, error_message TEXT)`, `FeatureResult(id, run_id FK, feature, surface, model_key, model_label, model_id, status, documented, verdict, latency_ms, evidence JSON, error_message)`; `runner.build_jobs(surfaces, features, models) -> tuple[list[Job], list[Job]]` (Job = dict `{feature, surface, model_key, model_id, model_label, documented}`; second list = pre-decided rows with `status`+`reason`), `runner.run_features(surfaces=None, features=None, models=None) -> int`, `runner.smoke(surfaces, features, models) -> list[dict]` (no DB), constants `CATALOG_VERSION = "2026-09-05"`, `KEEP_RUNS = 60`.

- [ ] **Step 1: Append failing tests**

```python
from claude_features import runner as R


def test_build_jobs_partitions_applicable_and_predecided():
    jobs, decided = R.build_jobs(["mantle", "bedrock_converse"], ["messages_basic", "bash_tool", "context_window_1m"], ["fable-5-1", "opus-5"])
    keys = {(j["feature"], j["surface"], j["model_key"]) for j in jobs}
    assert ("messages_basic", "mantle", "opus-5") in keys
    assert ("messages_basic", "mantle", "fable-5-1") not in keys  # GovCloud-only → decided
    na = {(d["feature"], d["surface"], d["model_key"]): d["status"] for d in decided}
    assert na[("messages_basic", "mantle", "fable-5-1")] == "not_applicable"
    assert na[("bash_tool", "bedrock_converse", "opus-5")] == "not_applicable"
    assert na[("context_window_1m", "mantle", "opus-5")] == "skipped"
    for j in jobs:
        assert j["documented"] in {"ga", "beta", "no", "unknown"} and j["model_id"]


def test_default_job_count_matches_spec_estimate():
    jobs, decided = R.build_jobs(None, None, None)
    total = len(jobs) + len(decided)
    assert total == 39 * 4 * 4  # feature × surface × model
    assert 380 <= len(jobs) <= 470
```

- [ ] **Step 2: Run to verify failure** — FAIL `cannot import name 'runner'`.

- [ ] **Step 3: Append ORM models to `backend/models.py`** (right after `ParityResult`):

```python
class FeatureRun(Base):
    """Claude API Features 검증 런 1회 (v2.23.0) — feature × surface × model 실행-증거 스윕."""

    __tablename__ = "feature_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, default="running")  # running | completed | failed
    totals = Column(JSON, nullable=True)  # {supported, unsupported, broken, inconclusive, skipped, not_applicable, drift}
    catalog_version = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)


class FeatureResult(Base):
    """Claude API Features 프로브 1건 — 판정 + 문서 기대치 + 증거 (v2.23.0)."""

    __tablename__ = "feature_results"
    __table_args__ = (
        Index("ix_feature_results_run_id", "run_id"),
        Index("ix_feature_results_run_feature", "run_id", "feature"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("feature_runs.id"), nullable=False)
    feature = Column(Text, nullable=False)      # claude_features.catalog.FEATURE_IDS
    surface = Column(Text, nullable=False)      # cp | mantle | bedrock_invoke | bedrock_converse
    model_key = Column(Text, nullable=False)    # fable-5-1 | fable-5 | opus-5 | sonnet-5
    model_label = Column(Text, nullable=False)
    model_id = Column(Text, nullable=True)      # surface별 실제 id (not_applicable이면 None)
    status = Column(Text, nullable=False)       # supported | unsupported | broken | inconclusive | skipped | not_applicable
    documented = Column(Text, nullable=False)   # ga | beta | no | unknown
    verdict = Column(Text, nullable=False)      # match | drift | undocumented | none
    latency_ms = Column(Float, nullable=True)
    evidence = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
```

- [ ] **Step 4: `backend/database.py` `create_tables`** — extend import: `from models import ProbeRun, ProbeResult, PromptSet, User, Insight, FeatureRun, FeatureResult  # noqa: F401`.

- [ ] **Step 5: Write `backend/claude_features/runner.py`**

```python
"""Claude API Features 런 오케스트레이터 (v2.23.0).

feature × surface × model 잡을 팬아웃해 4개 전송기로 실행하고 RDS에 저장한다.
- ThreadPoolExecutor(4), 스레드별 DB 세션 금지 → 메인 스레드 일괄 저장 (parity/runner.py 패턴)
- 전송기는 surface당 1개를 런 시작 시 생성 (Mantle bearer 재사용)
- 실패 시 FeatureRun.status = failed + error_message (패리티의 공백 보완)
- 보존: 최근 KEEP_RUNS 초과 런 삭제
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from claude_features import catalog, engine
from claude_features.probes import PROBES, ProbeOutcome, run_probe
from claude_features.transports import Transport, build_transport

logger = logging.getLogger(__name__)

CATALOG_VERSION = "2026-09-05"
KEEP_RUNS = 60
_MAX_WORKERS = 4


def build_jobs(surfaces, features, models) -> tuple[list[dict], list[dict]]:
    surfaces = surfaces or catalog.SURFACES
    features = features or catalog.FEATURE_IDS
    models = models or catalog.MODEL_KEYS
    jobs: list[dict] = []
    decided: list[dict] = []
    for feature in features:
        for surface in surfaces:
            for model_key in models:
                base = {"feature": feature, "surface": surface, "model_key": model_key,
                        "model_id": catalog.model_id_for(surface, model_key),
                        "model_label": catalog.model_label(model_key),
                        "documented": catalog.documented_for(feature, surface)}
                ok, reason = catalog.is_applicable(feature, surface, model_key)
                if ok:
                    jobs.append(base)
                else:
                    decided.append({**base, "status": reason, "reason": catalog.na_reason(feature, surface, model_key)})
    return jobs, decided


def _transports(surfaces: list[str]) -> dict[str, Transport | Exception]:
    out: dict[str, Transport | Exception] = {}
    for s in surfaces:
        try:
            out[s] = build_transport(s)
        except Exception as exc:  # noqa: BLE001 — 자격/env 누락은 surface 전체 broken으로 기록
            logger.exception("transport init failed for %s", s)
            out[s] = exc
    return out


def _execute(transports: dict, job: dict) -> ProbeOutcome:
    t = transports[job["surface"]]
    if isinstance(t, Exception):
        return ProbeOutcome("broken", error=f"transport init: {type(t).__name__}: {t}"[:1500])
    return run_probe(PROBES[job["feature"]], t, job["model_id"], job["model_key"])


def _run_jobs(jobs: list[dict], on_result) -> dict[str, int]:
    counts: dict[str, int] = {s: 0 for s in engine.STATUSES}
    surfaces = sorted({j["surface"] for j in jobs})
    transports = _transports(surfaces)
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_execute, transports, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                outcome = fut.result()
            except Exception as exc:  # noqa: BLE001
                outcome = ProbeOutcome("broken", error=f"executor: {exc}"[:1500])
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            on_result(job, outcome)
            done += 1
            if done % 25 == 0:
                logger.info("features: %d/%d done %s", done, len(jobs), counts)
    return counts


def run_features(surfaces=None, features=None, models=None) -> int:
    from database import SessionLocal
    from models import FeatureResult, FeatureRun

    db = SessionLocal()
    try:
        run = FeatureRun(status="running", started_at=datetime.now(timezone.utc), catalog_version=CATALOG_VERSION)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    except Exception:
        db.close()
        raise

    jobs, decided = build_jobs(surfaces, features, models)
    logger.info("Features run %d: %d probes (+%d pre-decided)", run_id, len(jobs), len(decided))
    rows: list[FeatureResult] = [
        FeatureResult(run_id=run_id, feature=d["feature"], surface=d["surface"], model_key=d["model_key"],
                      model_label=d["model_label"], model_id=d["model_id"], status=d["status"], documented=d["documented"],
                      verdict=engine.verdict(d["documented"], d["status"]), evidence={"reason": d["reason"]})
        for d in decided
    ]
    drift = 0

    def on_result(job: dict, outcome: ProbeOutcome) -> None:
        nonlocal drift
        v = engine.verdict(job["documented"], outcome.status)
        drift += v == "drift"
        rows.append(FeatureResult(run_id=run_id, feature=job["feature"], surface=job["surface"], model_key=job["model_key"],
                                  model_label=job["model_label"], model_id=job["model_id"], status=outcome.status,
                                  documented=job["documented"], verdict=v, latency_ms=outcome.latency_ms,
                                  evidence=outcome.evidence or {}, error_message=outcome.error))

    try:
        counts = _run_jobs(jobs, on_result)
        for d in decided:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        counts["drift"] = drift
        db.add_all(rows)
        run = db.query(FeatureRun).filter(FeatureRun.id == run_id).first()
        run.status, run.finished_at, run.totals = "completed", datetime.now(timezone.utc), counts
        db.commit()
        logger.info("Features run %d completed: %s", run_id, counts)
        _prune(db, FeatureRun, FeatureResult)
    except Exception as exc:
        db.rollback()
        run = db.query(FeatureRun).filter(FeatureRun.id == run_id).first()
        if run:
            run.status, run.finished_at, run.error_message = "failed", datetime.now(timezone.utc), str(exc)[:1500]
            db.commit()
        raise
    finally:
        db.close()
    return run_id


def _prune(db, FeatureRun, FeatureResult) -> None:
    keep = [r.id for r in db.query(FeatureRun.id).order_by(FeatureRun.id.desc()).limit(KEEP_RUNS)]
    if not keep:
        return
    old = [r.id for r in db.query(FeatureRun.id).filter(FeatureRun.id < min(keep)).all()]
    if old:
        db.query(FeatureResult).filter(FeatureResult.run_id.in_(old)).delete(synchronize_session=False)
        db.query(FeatureRun).filter(FeatureRun.id.in_(old)).delete(synchronize_session=False)
        db.commit()
        logger.info("pruned %d old feature runs", len(old))


def smoke(surfaces=None, features=None, models=None) -> list[dict]:
    """DB 없이 실행해 표로 출력할 결과 목록을 반환 (로컬 라이브 스모크)."""
    jobs, decided = build_jobs(surfaces, features, models)
    out: list[dict] = [{**d, "latency_ms": None, "error": None, "evidence": {"reason": d["reason"]}} for d in decided]

    def on_result(job: dict, outcome: ProbeOutcome) -> None:
        out.append({**job, "status": outcome.status, "verdict": engine.verdict(job["documented"], outcome.status),
                    "latency_ms": outcome.latency_ms, "error": outcome.error, "evidence": outcome.evidence})

    _run_jobs(jobs, on_result)
    return out
```

- [ ] **Step 6: Write `backend/features_runner.py`**

```python
"""Claude API Features 검증 Fargate one-shot / 로컬 스모크 진입점 (v2.23.0).

ECS CMD:  python -m features_runner --once
로컬:     python -m features_runner --smoke --models sonnet-5 --surfaces cp,mantle [--features messages_basic,...]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def _csv(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run one Claude API Features verification sweep and exit")
    parser.add_argument("--once", action="store_true", help="DB에 기록하는 실행 1회")
    parser.add_argument("--smoke", action="store_true", help="DB 없이 실행 후 표 출력 (로컬 검증)")
    parser.add_argument("--surfaces", help="cp,mantle,bedrock_invoke,bedrock_converse")
    parser.add_argument("--features", help="feature id 목록(콤마)")
    parser.add_argument("--models", help="fable-5-1,fable-5,opus-5,sonnet-5")
    parser.add_argument("--json", action="store_true", help="--smoke 결과를 JSON으로 출력")
    args = parser.parse_args()
    if not (args.once or args.smoke):
        parser.error("--once 또는 --smoke 필수")

    from claude_features.runner import run_features, smoke

    if args.smoke:
        rows = smoke(_csv(args.surfaces), _csv(args.features), _csv(args.models))
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        else:
            for r in sorted(rows, key=lambda r: (r["feature"], r["surface"], r["model_key"])):
                err = (r.get("error") or "")[:110].replace("\n", " ")
                print(f"{r['feature']:28s} {r['surface']:16s} {r['model_key']:10s} {r['status']:15s} {r['verdict']:12s} "
                      f"{(r['latency_ms'] or 0):7.0f}ms  {err}")
        return 0

    from database import create_tables
    create_tables()  # feature_runs / feature_results 보장 (backend 재배포 전에 먼저 돌 수 있음)
    try:
        run_id = run_features(_csv(args.surfaces), _csv(args.features), _csv(args.models))
        logging.info("features_runner done (run_id=%d)", run_id)
        return 0
    except Exception:
        logging.exception("features_runner 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run tests** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q` → PASS; `ruff check backend/` clean.

- [ ] **Step 8: Commit** — `git add backend/models.py backend/database.py backend/claude_features/runner.py backend/features_runner.py backend/tests/test_claude_features.py && git commit -m "feat(features): feature_runs/feature_results 테이블 + 러너(ThreadPool 4, failed 기록, 60런 보존) + CLI --once/--smoke"`

---

### Task 6: Router `/api/features/*` + registration

**Files:**
- Create: `backend/routers/features.py`
- Modify: `backend/main.py:24-25` (import), `backend/main.py:229-230` (include), `backend/main.py:201` (`version="2.23.0"`)
- Test: `backend/tests/test_claude_features.py` (append)

**Interfaces:**
- Produces: `GET /api/features/catalog` → `{groups, surfaces:[{id,label,short,group,region}], models:[{key,label,cp,mantle,bedrock,mantle_reason?}], features:[...]}`; `GET /api/features/latest` → `{run:{id,started_at,finished_at,totals,catalog_version,running}|null, previous_run_id, changes[], drift[], results[{feature,surface,model_key,model_label,model_id,status,documented,verdict,latency_ms}]}`; `GET /api/features/evidence?run_id&feature&surface&model_key`; `POST /api/features/trigger` (JWT). Pure helper `build_latest_payload(run, rows, prev_rows, running) -> dict` for unit test.

- [ ] **Step 1: Append failing test**

```python
def test_build_latest_payload_computes_changes_and_drift():
    from types import SimpleNamespace as NS
    from routers.features import build_latest_payload
    run = NS(id=2, started_at=None, finished_at=None, totals={"supported": 1}, catalog_version="2026-09-05")
    rows = [NS(feature="a", surface="cp", model_key="opus-5", model_label="Opus 5", model_id="claude-opus-5",
               status="broken", documented="ga", verdict="drift", latency_ms=10.0)]
    prev = [NS(feature="a", surface="cp", model_key="opus-5", status="supported")]
    p = build_latest_payload(run, rows, prev, 1, running=False)
    assert p["run"]["id"] == 2 and p["previous_run_id"] == 1
    assert p["changes"] == [{"feature": "a", "surface": "cp", "model_key": "opus-5", "before": "supported", "after": "broken", "model_label": "Opus 5"}]
    assert p["drift"][0]["feature"] == "a" and p["results"][0]["verdict"] == "drift"
```

- [ ] **Step 2: Run to verify failure** — FAIL `No module named 'routers.features'`.

- [ ] **Step 3: Write `backend/routers/features.py`** (no `from __future__ import annotations`):

```python
"""Claude API Features 검증 API (v2.23.0).

- GET  /api/features/catalog   — 그룹·surface·모델·피처(문서 기대치 포함)
- GET  /api/features/latest    — 최신 완료 런 매트릭스 + 직전 런 diff + 드리프트 목록 (s-maxage=60)
- GET  /api/features/evidence  — 셀(feature, surface, model_key) 전체 증거
- POST /api/features/trigger   — 수동 런 (JWT, backend 내 백그라운드 스레드)
"""

import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from claude_features import catalog
from claude_features.engine import diff_runs
from database import get_db
from models import FeatureResult, FeatureRun

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/features", tags=["features"])

_run_lock = threading.Lock()
_running = {"active": False}


@router.get("/catalog")
def get_catalog():
    return {
        "groups": catalog.GROUPS,
        "surfaces": [{"id": s, **catalog.SURFACE_META[s], "region": catalog.region_for(s)} for s in catalog.SURFACES],
        "models": catalog.MODELS,
        "features": catalog.FEATURES,
    }


def build_latest_payload(run, rows, prev_rows, prev_run_id, running: bool) -> dict[str, Any]:
    results = [
        {"feature": r.feature, "surface": r.surface, "model_key": r.model_key, "model_label": r.model_label,
         "model_id": r.model_id, "status": r.status, "documented": r.documented, "verdict": r.verdict,
         "latency_ms": r.latency_ms}
        for r in rows
    ]
    changes: list[dict] = []
    if prev_rows is not None:
        prev_map = {(p.feature, p.surface, p.model_key): p.status for p in prev_rows}
        cur_map = {(r.feature, r.surface, r.model_key): r.status for r in rows}
        labels = {r.model_key: r.model_label for r in rows}
        changes = [{**c, "model_label": labels.get(c["model_key"], c["model_key"])} for c in diff_runs(prev_map, cur_map)]
    drift = [r for r in results if r["verdict"] == "drift"]
    return {
        "run": {"id": run.id, "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "totals": run.totals, "catalog_version": run.catalog_version, "running": running},
        "previous_run_id": prev_run_id,
        "changes": changes,
        "drift": drift,
        "results": results,
    }


@router.get("/latest")
def get_latest(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    run = db.query(FeatureRun).filter(FeatureRun.status == "completed").order_by(desc(FeatureRun.id)).first()
    if not run:
        return {"run": None, "previous_run_id": None, "changes": [], "drift": [], "results": [], "running": _running["active"]}
    cols = (FeatureResult.feature, FeatureResult.surface, FeatureResult.model_key, FeatureResult.model_label,
            FeatureResult.model_id, FeatureResult.status, FeatureResult.documented, FeatureResult.verdict, FeatureResult.latency_ms)
    rows = db.query(*cols).filter(FeatureResult.run_id == run.id).all()
    prev_run = (db.query(FeatureRun).filter(FeatureRun.status == "completed", FeatureRun.id < run.id)
                .order_by(desc(FeatureRun.id)).first())
    prev_rows = None
    if prev_run:
        prev_rows = (db.query(FeatureResult.feature, FeatureResult.surface, FeatureResult.model_key, FeatureResult.status)
                     .filter(FeatureResult.run_id == prev_run.id).all())
    return build_latest_payload(run, rows, prev_rows, prev_run.id if prev_run else None, _running["active"])


@router.get("/evidence")
def get_evidence(run_id: int = Query(...), feature: str = Query(...), surface: str = Query(...),
                 model_key: str = Query(...), db: Session = Depends(get_db)):
    row = (db.query(FeatureResult)
           .filter(FeatureResult.run_id == run_id, FeatureResult.feature == feature,
                   FeatureResult.surface == surface, FeatureResult.model_key == model_key).first())
    if not row:
        raise HTTPException(status_code=404, detail="result not found")
    fdef = next((f for f in catalog.FEATURES if f["id"] == feature), {})
    return {"feature": row.feature, "surface": row.surface, "model_key": row.model_key, "model_label": row.model_label,
            "model_id": row.model_id, "status": row.status, "documented": row.documented, "verdict": row.verdict,
            "latency_ms": row.latency_ms, "evidence": row.evidence, "error_message": row.error_message,
            "doc_url": fdef.get("doc_url"), "verification": fdef.get("verification"), "notes": fdef.get("notes")}


@router.post("/trigger")
def trigger(user=Depends(get_current_user)):
    with _run_lock:
        if _running["active"]:
            return {"triggered": False, "message": "이미 실행 중입니다"}
        _running["active"] = True

    def _worker():
        try:
            from claude_features.runner import run_features
            run_features()
        except Exception:
            logger.exception("Features run failed")
        finally:
            _running["active"] = False

    threading.Thread(target=_worker, daemon=True, name="features-run").start()
    return {"triggered": True, "message": "Claude API Features 검증 런을 시작했습니다 (약 10-15분 소요)"}
```

- [ ] **Step 4: Register in `backend/main.py`** — add `from routers import features as features_router` after the gptbench import (line 25) and `app.include_router(features_router.router)` after line 230; set `version="2.23.0"`.

- [ ] **Step 5: Run** — `cd backend && python3.12 -m pytest tests/ -q` (whole suite still green) → PASS.

- [ ] **Step 6: Commit** — `git add backend/routers/features.py backend/main.py backend/tests/test_claude_features.py && git commit -m "feat(features): /api/features catalog·latest(diff+drift)·evidence·trigger 라우터 — FastAPI 2.23.0"`

---

### Task 7: Local live smoke — validate probes against the real endpoints before any deploy

**Files:**
- No new source files expected; fix defects found in `probes.py`/`transports.py`/`engine.py` (each fix gets its own commit + regression test where the defect is a pure-logic bug).

**Interfaces:**
- Consumes: `features_runner --smoke`.

- [ ] **Step 1: Export credentials for the local shell** (python3.12, current IAM role `VscodeServerStack-VSCode-Role`, SSM SecureStrings). Do not print secret values.

```bash
cd /home/ec2-user/my-project/model-monitoring/backend
export ANTHROPIC_API_KEY="$(aws ssm get-parameter --with-decryption --region ap-northeast-2 --name /bedrock-monitor/anthropic-api-key --query Parameter.Value --output text)"
export ANTHROPIC_WORKSPACE_ID="$(aws ssm get-parameter --with-decryption --region ap-northeast-2 --name /bedrock-monitor/anthropic-workspace-id --query Parameter.Value --output text)"
export AWS_REGION=ap-northeast-2 MANTLE_ANTHROPIC_REGION=ap-northeast-1
test -n "$ANTHROPIC_API_KEY" && test -n "$ANTHROPIC_WORKSPACE_ID" && echo creds-ok
```

Expected: `creds-ok`. If SSM decrypt is denied, stop and report — the local role lacks `ssm:GetParameter`/`kms:Decrypt`; ask the user for the key material or run the smoke as an ECS one-off task instead (`aws ecs run-task` with `features_runner --smoke --json`, read the log).

- [ ] **Step 2: Cheapest first — one model, core features, all four surfaces**

```bash
python3.12 -m features_runner --smoke --models sonnet-5 --features messages_basic,streaming,system_prompt,tool_use,token_counting
```

Expected: 4 surfaces × 5 features = 20 rows; `cp`/`mantle`/`bedrock_invoke`/`bedrock_converse` all `supported`. Any `broken` here is a transport/auth defect (403 → IAM chain: `bedrock-mantle:CreateInference`+`CallWithBearerToken` on the local role; 401 → workspace header), fix before continuing.

- [ ] **Step 3: Full feature sweep for one model**

```bash
python3.12 -m features_runner --smoke --models sonnet-5 --json > /tmp/claude-1000/-home-ec2-user-my-project-model-monitoring/5058926a-f4df-48c6-a740-4422a7c45745/scratchpad/smoke-sonnet5.json
python3.12 -m features_runner --smoke --models sonnet-5 | sort -k4
```

Review every `broken` row's `error`/`evidence` and classify: (a) probe defect → fix probe (e.g. wrong Converse `outputConfig` shape, wrong beta value, `max_tokens` truncation), (b) new clean-rejection phrasing → add marker to `engine._EXTRA_UNSUPPORTED` + test, (c) genuine platform gap → leave as `broken`/`drift` (that is the product). Every `inconclusive` for server/client tools: strengthen the prompt once; if still inconclusive on a second try, accept.

- [ ] **Step 4: Fable 5.1 special cases**

```bash
python3.12 -m features_runner --smoke --models fable-5-1 --features tool_use,strict_tool_use,extended_thinking,adaptive_thinking,advisor_tool,bash_tool,computer_use
```

Expected: `tool_use`/`strict_tool_use` use `tool_choice: auto` and still round-trip; `extended_thinking` → `not_applicable` on every surface; `mantle` rows → `not_applicable` (GovCloud reason).

- [ ] **Step 5: Record findings** — write the smoke summary (counts per surface, drift list, fixed defects) to `docs/superpowers/plans/2026-09-05-claude-features-verify.md` under a new "## Smoke log" section at the end, and commit: `git commit -am "test(features): 로컬 라이브 스모크 결과 반영 — 프로브 결함 수정"`.

---

### Task 8: Frontend pure logic (`lib/claudeFeatures.ts`) + vitest

**Files:**
- Create: `frontend/src/lib/claudeFeatures.ts`
- Create: `frontend/src/lib/claudeFeatures.test.ts`

**Interfaces:**
- Produces: types `FeatureStatus`, `Verdict`, `Documented`, `FeatureCell`, `FeatureDef`, `FeatureGroupDef`, `SurfaceDef`, `ModelDef`, `FeatureRunInfo`, `FeatureChange`; constants `STATUS_STYLE`, `STATUS_LABEL`, `VERDICT_STYLE`, `DOC_LABEL`; functions `aggregateCell(cells) -> {status: CellStatus, counts, probed}`, `buildGroups(features, groups, surfaces, cells, lang, filter) -> GroupView[]`, `surfaceHealth(cells, surface) -> {supported, broken, health}`.

- [ ] **Step 1: Write failing test `frontend/src/lib/claudeFeatures.test.ts`**

```ts
/** Claude API Features 매트릭스 순수 로직 (v2.23.0) — 셀 집계·그룹 구성·헬스 계산 회귀 */
import { describe, expect, test } from "vitest";
import { aggregateCell, buildGroups, surfaceHealth, type FeatureCell, type FeatureDef } from "./claudeFeatures";

const cell = (p: Partial<FeatureCell>): FeatureCell => ({
  feature: "f", surface: "cp", model_key: "opus-5", model_label: "Opus 5", model_id: "claude-opus-5",
  status: "supported", documented: "ga", verdict: "match", latency_ms: 1, ...p,
});

describe("aggregateCell", () => {
  test("all supported → supported", () => {
    expect(aggregateCell([cell({}), cell({ model_key: "sonnet-5" })]).status).toBe("supported");
  });
  test("broken wins", () => {
    expect(aggregateCell([cell({}), cell({ status: "broken", verdict: "drift" })]).status).toBe("broken");
  });
  test("mixed supported/unsupported → partial", () => {
    expect(aggregateCell([cell({}), cell({ status: "unsupported", verdict: "drift" })]).status).toBe("partial");
  });
  test("only not_applicable → not_applicable; empty → empty", () => {
    expect(aggregateCell([cell({ status: "not_applicable", verdict: "none" })]).status).toBe("not_applicable");
    expect(aggregateCell([]).status).toBe("empty");
  });
});

describe("buildGroups", () => {
  const features: FeatureDef[] = [
    { id: "a", group: "core", label_ko: "가", label_en: "A", desc_ko: "", desc_en: "", doc_url: "u",
      documented: { cp: "ga", mantle: "ga" }, verification: "evidence", notes: "" },
    { id: "b", group: "model", label_ko: "나", label_en: "B", desc_ko: "", desc_en: "", doc_url: "u",
      documented: { cp: "no", mantle: "no" }, verification: "acceptance", notes: "" },
  ];
  const groups = [{ id: "core", label_ko: "코어", label_en: "Core" }, { id: "model", label_ko: "모델", label_en: "Model" }];
  const cells = [cell({ feature: "a" }), cell({ feature: "a", surface: "mantle", status: "broken", verdict: "drift" }),
                 cell({ feature: "b", status: "unsupported", documented: "no", verdict: "match" })];

  test("groups keep catalog order and aggregate per surface", () => {
    const g = buildGroups(features, groups, ["cp", "mantle"], cells, "ko", "all");
    expect(g.map((x) => x.id)).toEqual(["core", "model"]);
    expect(g[0].rows[0].label).toBe("가");
    expect(g[0].rows[0].cells.cp.status).toBe("supported");
    expect(g[0].rows[0].cells.mantle.status).toBe("broken");
    expect(g[1].rows[0].cells.mantle.status).toBe("empty");
  });
  test("status filter hides rows without a matching cell", () => {
    const g = buildGroups(features, groups, ["cp", "mantle"], cells, "en", "broken");
    expect(g.map((x) => x.id)).toEqual(["core"]);
  });
});

describe("surfaceHealth", () => {
  test("health = supported / (supported + broken)", () => {
    const h = surfaceHealth([cell({}), cell({ status: "broken" }), cell({ status: "unsupported" })], "cp");
    expect(h).toEqual({ supported: 1, broken: 1, health: 50 });
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd frontend && npx vitest run src/lib/claudeFeatures.test.ts` → FAIL (module not found).

- [ ] **Step 3: Write `frontend/src/lib/claudeFeatures.ts`**

```ts
// Claude API Features 매트릭스 순수 로직 (v2.23.0) — 컴포넌트 밖으로 뺀 타입·스타일·집계 함수 (vitest 대상).

export type FeatureStatus = "supported" | "unsupported" | "broken" | "inconclusive" | "skipped" | "not_applicable";
export type CellStatus = FeatureStatus | "partial" | "empty";
export type Verdict = "match" | "drift" | "undocumented" | "none";
export type Documented = "ga" | "beta" | "no" | "unknown";

export interface FeatureCell {
  feature: string; surface: string; model_key: string; model_label: string; model_id: string | null;
  status: FeatureStatus; documented: Documented; verdict: Verdict; latency_ms: number | null;
}
export interface FeatureDef {
  id: string; group: string; label_ko: string; label_en: string; desc_ko: string; desc_en: string;
  doc_url: string; documented: Record<string, Documented | string>; verification: string; notes: string;
}
export interface FeatureGroupDef { id: string; label_ko: string; label_en: string }
export interface SurfaceDef { id: string; label: string; short: string; group: string; region: string }
export interface ModelDef { key: string; label: string; cp: string; mantle: string | null; bedrock: string; mantle_reason?: string }
export interface FeatureRunInfo {
  id: number; started_at: string | null; finished_at: string | null;
  totals: Record<string, number> | null; catalog_version: string | null; running: boolean;
}
export interface FeatureChange {
  feature: string; surface: string; model_key: string; model_label: string;
  before: FeatureStatus | null; after: FeatureStatus;
}

export const STATUS_STYLE: Record<CellStatus, string> = {
  supported: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  partial: "bg-teal-500/10 border-teal-500/30 text-teal-300",
  unsupported: "bg-amber-500/10 border-amber-500/30 text-amber-300",
  broken: "bg-rose-500/10 border-rose-500/30 text-rose-300",
  inconclusive: "bg-violet-500/10 border-violet-500/30 text-violet-300",
  skipped: "bg-gray-800 border-gray-700 text-gray-500",
  not_applicable: "bg-gray-800 border-gray-700 text-gray-500",
  empty: "bg-transparent border-transparent text-gray-600",
};
export const STATUS_LABEL: Record<CellStatus, string> = {
  supported: "Supported", partial: "Partial", unsupported: "Unsupported", broken: "Broken",
  inconclusive: "Inconclusive", skipped: "Skipped", not_applicable: "N/A", empty: "—",
};
export const VERDICT_STYLE: Record<Verdict, string> = {
  match: "text-emerald-300", drift: "text-rose-300 font-semibold", undocumented: "text-sky-300", none: "text-gray-500",
};
export const DOC_LABEL: Record<string, string> = { ga: "GA", beta: "Beta", no: "—", unknown: "?" };

export interface CellAggregate { status: CellStatus; counts: Record<FeatureStatus, number>; probed: number; cells: FeatureCell[] }

export function aggregateCell(cells: FeatureCell[]): CellAggregate {
  const counts: Record<FeatureStatus, number> = { supported: 0, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 };
  for (const c of cells) counts[c.status] += 1;
  const probed = counts.supported + counts.unsupported + counts.broken + counts.inconclusive;
  let status: CellStatus;
  if (cells.length === 0) status = "empty";
  else if (probed === 0) status = counts.not_applicable > 0 ? "not_applicable" : "skipped";
  else if (counts.broken > 0) status = "broken";
  else if (counts.supported === probed) status = "supported";
  else if (counts.unsupported === probed) status = "unsupported";
  else if (counts.inconclusive === probed) status = "inconclusive";
  else status = "partial";
  return { status, counts, probed, cells };
}

export interface RowView {
  id: string; label: string; desc: string; doc_url: string; verification: string; notes: string;
  documented: Record<string, string>; cells: Record<string, CellAggregate>; drift: number;
}
export interface GroupView { id: string; label: string; rows: RowView[] }

export function buildGroups(
  features: FeatureDef[], groups: FeatureGroupDef[], surfaces: string[], cells: FeatureCell[],
  lang: string, filter: CellStatus | "all" | "drift",
): GroupView[] {
  const byKey = new Map<string, FeatureCell[]>();
  for (const c of cells) {
    const k = `${c.feature}|${c.surface}`;
    const arr = byKey.get(k) ?? [];
    arr.push(c);
    byKey.set(k, arr);
  }
  const out: GroupView[] = [];
  for (const g of groups) {
    const rows: RowView[] = [];
    for (const f of features) {
      if (f.group !== g.id) continue;
      const agg: Record<string, CellAggregate> = {};
      let drift = 0;
      for (const s of surfaces) {
        const cs = byKey.get(`${f.id}|${s}`) ?? [];
        agg[s] = aggregateCell(cs);
        drift += cs.filter((c) => c.verdict === "drift").length;
      }
      const matches =
        filter === "all" ? true
        : filter === "drift" ? drift > 0
        : surfaces.some((s) => agg[s].status === filter || agg[s].cells.some((c) => c.status === filter));
      if (!matches) continue;
      rows.push({
        id: f.id, label: (lang === "en" ? f.label_en : f.label_ko) || f.id,
        desc: (lang === "en" ? f.desc_en : f.desc_ko) || "", doc_url: f.doc_url, verification: f.verification,
        notes: f.notes, documented: f.documented as Record<string, string>, cells: agg, drift,
      });
    }
    if (rows.length) out.push({ id: g.id, label: (lang === "en" ? g.label_en : g.label_ko) || g.id, rows });
  }
  return out;
}

export function surfaceHealth(cells: FeatureCell[], surface: string): { supported: number; broken: number; health: number } {
  let supported = 0, broken = 0;
  for (const c of cells) {
    if (c.surface !== surface) continue;
    if (c.status === "supported") supported += 1;
    else if (c.status === "broken") broken += 1;
  }
  return { supported, broken, health: Math.round((100 * supported) / Math.max(1, supported + broken)) };
}
```

- [ ] **Step 4: Run** — `cd frontend && npx vitest run src/lib/claudeFeatures.test.ts` → PASS (7 tests).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts && git commit -m "feat(frontend): Claude API Features 매트릭스 순수 로직 + vitest"`

---

### Task 9: Frontend page, header entry, API client, panel

**Files:**
- Modify: `frontend/src/lib/api.ts` (append section at end, after line 853)
- Modify: `frontend/src/components/AppHeader.tsx:23-40` (nav item + comment count)
- Create: `frontend/src/app/claude-features/page.tsx`
- Create: `frontend/src/components/ClaudeFeaturesPanel.tsx`

**Interfaces:**
- Consumes: Task 8 lib exports; backend Task 6 payloads.
- Produces: `fetchFeaturesCatalog(): Promise<FeaturesCatalog>`, `fetchFeaturesLatest(): Promise<FeaturesLatest>`, `fetchFeaturesEvidence(q): Promise<FeaturesEvidence>`, `triggerFeaturesRun(): Promise<{triggered: boolean; message: string}>`; nav key `"features"`; route `/claude-features`.

- [ ] **Step 1: Append to `frontend/src/lib/api.ts`**

```ts
// ── Claude API Features 검증 (v2.23.0) ──────────────────────────────────
import type {
  FeatureCell, FeatureChange, FeatureDef, FeatureGroupDef, FeatureRunInfo, ModelDef, SurfaceDef,
} from "./claudeFeatures";

export interface FeaturesCatalog { groups: FeatureGroupDef[]; surfaces: SurfaceDef[]; models: ModelDef[]; features: FeatureDef[] }
export interface FeaturesLatest {
  run: FeatureRunInfo | null; previous_run_id: number | null; changes: FeatureChange[];
  drift: FeatureCell[]; results: FeatureCell[]; running?: boolean;
}
export interface FeaturesEvidence extends FeatureCell {
  evidence: Record<string, unknown> | null; error_message: string | null;
  doc_url: string | null; verification: string | null; notes: string | null;
}

export async function fetchFeaturesCatalog(): Promise<FeaturesCatalog> {
  const res = await fetch(`${BASE}/api/features/catalog`);
  if (!res.ok) throw new Error(`fetchFeaturesCatalog failed: ${res.statusText}`);
  return res.json();
}

export async function fetchFeaturesLatest(): Promise<FeaturesLatest> {
  const res = await fetch(`${BASE}/api/features/latest`);
  if (!res.ok) throw new Error(`fetchFeaturesLatest failed: ${res.statusText}`);
  return res.json();
}

export async function fetchFeaturesEvidence(q: { run_id: number; feature: string; surface: string; model_key: string }): Promise<FeaturesEvidence> {
  const sp = new URLSearchParams({ run_id: String(q.run_id), feature: q.feature, surface: q.surface, model_key: q.model_key });
  const res = await fetch(`${BASE}/api/features/evidence?${sp}`);
  if (!res.ok) throw new Error(`fetchFeaturesEvidence failed: ${res.status}`);
  return res.json();
}

export async function triggerFeaturesRun(): Promise<{ triggered: boolean; message: string }> {
  const res = await fetch(`${BASE}/api/features/trigger`, { method: "POST", headers: authHeaders() });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return { triggered: false, message: body.detail ?? `HTTP ${res.status}` };
  return body;
}
```

Note: `import type` at the bottom of `api.ts` is legal TS but ESLint `import/first` may complain — if `npx tsc --noEmit`/`npm run lint` flags it, move the import to the top of `api.ts`.

- [ ] **Step 2: Header nav (`AppHeader.tsx`)** — change the comment to `/** 표준 11개 내비 항목 …` and insert after the `gptbench` line:

```ts
    { key: "features", label: L("Claude API Features", "Claude API 기능"), href: "/claude-features" },
```

- [ ] **Step 3: Page shell `frontend/src/app/claude-features/page.tsx`** (copy of gpt-on-aws shell without dead imports):

```tsx
"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { AuthUser } from "@/lib/types";
import { fetchMe, getToken, setToken } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n-context";
import LoginForm from "@/components/LoginForm";
import FloatingChat from "@/components/chat/FloatingChat";
import ClaudeFeaturesPanel from "@/components/ClaudeFeaturesPanel";
import AppHeader, { useNavItems } from "@/components/AppHeader";

export default function ClaudeFeaturesPage() {
  return (
    <LanguageProvider>
      <Inner />
    </LanguageProvider>
  );
}

function Inner() {
  const navItems = useNavItems("features");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginModalOpen, setLoginModalOpen] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (token) {
      fetchMe().then(setUser).catch(() => setToken(null)).finally(() => setAuthChecked(true));
    } else {
      setAuthChecked(true);
    }
  }, []);

  const handleLoginSuccess = (username: string) => {
    setUser({ id: 0, username });
    fetchMe().then(setUser).catch(() => {});
    setLoginModalOpen(false);
  };
  const handleLogout = () => { setToken(null); setUser(null); };

  if (!authChecked) return null;

  return (
    <div className="min-h-screen">
      <AppHeader items={navItems} user={user} onLoginClick={() => setLoginModalOpen(true)} onLogout={handleLogout} />
      <ClaudeFeaturesPanel />
      <FloatingChat />
      {loginModalOpen && !user && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button type="button" aria-label="overlay" onClick={() => setLoginModalOpen(false)} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <div className="relative w-full max-w-md bg-gray-900 border border-gray-800 rounded-xl shadow-2xl p-6">
            <button type="button" onClick={() => setLoginModalOpen(false)} className="absolute top-3 right-3 text-gray-400 hover:text-white text-xl leading-none" aria-label="close">×</button>
            <LoginForm onLoginSuccess={handleLoginSuccess} />
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Panel `frontend/src/components/ClaudeFeaturesPanel.tsx`**

```tsx
"use client";

// Claude API Features (v2.23.0) — platform.claude.com "Build with Claude" 33피처(+코어 4, Models API)를
// Claude Platform on AWS / Bedrock Mantle /anthropic / Bedrock InvokeModel / Bedrock Converse 4열에서 실행-증거로 검증.
// 셀 = 피처 × 엔드포인트(대표 모델 4종 집계) — 클릭 시 모델별 상세, 문서 기대치 vs 실측 드리프트 배너.

import { Fragment, useEffect, useMemo, useState } from "react";
import { useLang } from "@/lib/i18n-context";
import {
  fetchFeaturesCatalog, fetchFeaturesEvidence, fetchFeaturesLatest, getToken, triggerFeaturesRun,
  type FeaturesCatalog, type FeaturesEvidence, type FeaturesLatest,
} from "@/lib/api";
import {
  aggregateCell, buildGroups, surfaceHealth, DOC_LABEL, STATUS_LABEL, STATUS_STYLE, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type RowView,
} from "@/lib/claudeFeatures";

const SURFACE_GROUP_LABEL: Record<string, { en: string; ko: string }> = {
  cp: { en: "Claude Platform on AWS", ko: "Claude Platform on AWS" },
  mantle: { en: "Bedrock Mantle /anthropic", ko: "Bedrock Mantle /anthropic" },
  bedrock: { en: "Bedrock runtime", ko: "Bedrock runtime" },
};

function EvidenceModal({ runId, cell, onClose }: { runId: number; cell: FeatureCell; onClose: () => void }) {
  const { lang } = useLang();
  const [data, setData] = useState<FeaturesEvidence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFeaturesEvidence({ run_id: runId, feature: cell.feature, surface: cell.surface, model_key: cell.model_key })
      .then(setData).catch((e) => setError(String(e)));
  }, [runId, cell]);

  const evidence = (data?.evidence ?? {}) as Record<string, unknown>;
  const request = evidence.request as Record<string, unknown> | undefined;
  const response: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(evidence)) if (k !== "request") response[k] = v;
  const errorMsg = data?.error_message ?? null;
  const isOk = cell.status === "supported";

  const verdictText: Record<string, string> = lang === "en"
    ? { supported: "Probe succeeded — the documented evidence signal was present in the response.",
        unsupported: "The endpoint explicitly rejected this capability (clean unsupported response).",
        broken: errorMsg ? `Expected to work but the probe failed: ${errorMsg.slice(0, 220)}` : "Evidence check failed — response received but the documented signal was missing.",
        inconclusive: "Definition accepted, but the model did not exercise the feature (e.g. tool not invoked) — not proof of absence.",
        skipped: "No verification path on this endpoint (capability endpoint missing).",
        not_applicable: `Not applicable by design: ${String(evidence.reason ?? "")}` }
    : { supported: "프로브 성공 — 문서가 정한 증거 신호가 응답에 존재합니다.",
        unsupported: "엔드포인트가 이 기능을 명시적으로 거부했습니다 (깨끗한 미지원 응답).",
        broken: errorMsg ? `동작해야 하는 기능인데 프로브 실패: ${errorMsg.slice(0, 220)}` : "증거 검사 실패 — 응답은 받았지만 문서상 신호가 없습니다.",
        inconclusive: "정의는 수락됐지만 모델이 기능을 사용하지 않았습니다(도구 미호출 등) — 부재의 증거는 아님.",
        skipped: "이 엔드포인트에는 검증 경로가 없습니다(capability 엔드포인트 부재).",
        not_applicable: `설계상 부적용: ${String(evidence.reason ?? "")}` };

  const Section = ({ title, json, tone }: { title: string; json: unknown; tone?: "error" }) => (
    <details open={!isOk} className="group">
      <summary className="cursor-pointer select-none text-sm text-gray-400 hover:text-gray-200 py-1">
        <span className="inline-block w-3 text-[10px] transition-transform group-open:rotate-90">▶</span> {title}
      </summary>
      <pre className={`mt-1 rounded-lg p-3 overflow-x-auto text-xs leading-relaxed border ${
        tone === "error" ? "bg-gray-950 border-rose-500/30 text-rose-300 whitespace-pre-wrap break-all" : "bg-gray-950 border-gray-800 text-gray-200"}`}>
        {typeof json === "string" ? json : JSON.stringify(json ?? {}, null, 2)}
      </pre>
    </details>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="overlay" onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-gray-900 light:bg-white border border-gray-800 rounded-xl shadow-2xl p-6 space-y-4">
        <button type="button" onClick={onClose} className="absolute top-4 right-4 text-gray-400 hover:text-gray-200 text-xl leading-none" aria-label="close">×</button>
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-blue-400 uppercase">Evidence</div>
          <h2 className="text-base font-bold text-gray-100 font-mono mt-0.5">{cell.feature} · {cell.surface} · {cell.model_label}</h2>
          <div className="text-xs text-gray-500 mt-0.5 font-mono">{cell.model_id ?? "—"}</div>
        </div>
        <div className="bg-gray-950/60 light:bg-gray-50 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2.5 py-0.5 text-[11px] font-medium rounded-full border ${STATUS_STYLE[cell.status]}`}>{STATUS_LABEL[cell.status]}</span>
            <span className="text-xs text-gray-500">{lang === "en" ? "documented" : "문서"}: <b className="text-gray-300">{DOC_LABEL[cell.documented]}</b></span>
            <span className={`text-xs ${VERDICT_STYLE[cell.verdict]}`}>verdict: {cell.verdict}</span>
            {data?.verification && <span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400">{data.verification}</span>}
            <span className="text-xs text-gray-500 ml-auto tabular-nums">{cell.latency_ms != null ? `${Math.round(cell.latency_ms)} ms` : "-"}</span>
          </div>
          <p className={`text-sm leading-relaxed ${isOk ? "text-gray-300" : cell.status === "broken" ? "text-rose-300" : "text-amber-300"}`}>{verdictText[cell.status]}</p>
          {data?.notes && <p className="text-[11px] text-gray-500">{data.notes}</p>}
          {data?.doc_url && (
            <a href={data.doc_url} target="_blank" rel="noreferrer" className="text-[11px] text-blue-400 hover:underline">
              {lang === "en" ? "Open documentation →" : "공식 문서 열기 →"}
            </a>
          )}
          {error && <div className="text-xs text-rose-400">{lang === "en" ? "Failed to load evidence" : "증거 로드 실패"}: {error}</div>}
          {data && (
            <div className="space-y-1 pt-1">
              {errorMsg && <Section title="Error" json={errorMsg} tone="error" />}
              {request && <Section title="Request JSON" json={request} />}
              <Section title="Response / evidence" json={response} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CellBadge({ agg, onPick }: { agg: CellAggregate; onPick: (c: FeatureCell) => void }) {
  const { lang } = useLang();
  const [open, setOpen] = useState(false);
  if (agg.status === "empty") return <span className="text-gray-600">—</span>;
  const single = agg.cells.length === 1;
  const drift = agg.cells.filter((c) => c.verdict === "drift").length;
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => (single ? onPick(agg.cells[0]) : setOpen((o) => !o))}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={`px-2 py-0.5 text-[10px] font-medium rounded-full border transition-transform hover:scale-105 ${STATUS_STYLE[agg.status]}`}
        title={lang === "en" ? "Click for per-model evidence" : "클릭해서 모델별 증거 보기"}
      >
        {STATUS_LABEL[agg.status]}
        {!single && agg.probed > 0 && <span className="ml-1 text-gray-400">{agg.counts.supported}/{agg.probed}</span>}
        {drift > 0 && <span className="ml-1 text-rose-300">▲{drift}</span>}
      </button>
      {open && (
        <ul className="absolute z-20 mt-1 left-0 min-w-[14rem] bg-gray-900 light:bg-white border border-gray-700 rounded-lg shadow-xl py-1">
          {agg.cells.map((c) => (
            <li key={c.model_key}>
              <button type="button" onMouseDown={() => onPick(c)} className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-[11px] hover:bg-blue-600/20">
                <span className="text-gray-300">{c.model_label}</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.status]}`}>{STATUS_LABEL[c.status]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ClaudeFeaturesPanel() {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const [catalog, setCatalog] = useState<FeaturesCatalog | null>(null);
  const [latest, setLatest] = useState<FeaturesLatest | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<CellStatus | "all" | "drift">("all");
  const [selected, setSelected] = useState<FeatureCell | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const load = () => {
    Promise.all([fetchFeaturesLatest(), fetchFeaturesCatalog()])
      .then(([l, c]) => { setLatest(l); setCatalog(c); })
      .catch((e) => console.error("features load failed:", e))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const handleTrigger = async () => {
    if (!getToken()) { setTriggerMsg(L("Login required to trigger a run.", "런 실행에는 로그인이 필요합니다.")); return; }
    const r = await triggerFeaturesRun();
    setTriggerMsg(r.message);
  };

  const surfaces = useMemo(() => catalog?.surfaces.map((s) => s.id) ?? [], [catalog]);
  const cells = latest?.results ?? [];
  const groups = useMemo(
    () => (catalog ? buildGroups(catalog.features, catalog.groups, surfaces, cells, lang, filter) : []),
    [catalog, surfaces, cells, lang, filter],
  );
  const run = latest?.run ?? null;
  const drift = latest?.drift ?? [];

  if (loading) {
    return <div className="flex items-center justify-center py-24"><div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
  }

  // 헤더 열 그룹: cp / mantle / bedrock(InvokeModel·Converse 2열)
  const colGroups = catalog ? catalog.surfaces.reduce<{ group: string; ids: string[] }[]>((acc, s) => {
    const last = acc[acc.length - 1];
    if (last && last.group === s.group) last.ids.push(s.id); else acc.push({ group: s.group, ids: [s.id] });
    return acc;
  }, []) : [];

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-100">{L("Claude API Features", "Claude API 기능 검증")}</h2>
          <p className="text-sm text-gray-400 mt-1 max-w-3xl leading-relaxed">
            {L("Every documented \"Build with Claude\" feature, executed for real on Claude Platform on AWS, Bedrock Mantle /anthropic and Bedrock runtime (InvokeModel · Converse) with Fable 5.1 · Fable 5 · Opus 5 · Sonnet 5. Cells compare what the docs promise with what actually happened.",
               "공식 \"Build with Claude\" 문서의 모든 피처를 Claude Platform on AWS · Bedrock Mantle /anthropic · Bedrock runtime(InvokeModel · Converse)에서 Fable 5.1 · Fable 5 · Opus 5 · Sonnet 5로 실제 실행합니다. 셀은 문서가 약속한 것과 실측을 비교합니다.")}
          </p>
          {run && (
            <p className="text-xs text-gray-500 mt-1">
              {L("Last run", "최근 런")} #{run.id} · {run.finished_at ? new Date(run.finished_at).toLocaleString() : "-"} · catalog {run.catalog_version}
              {run.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
        </div>
        <button onClick={handleTrigger} className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors">
          {L("Run verification", "검증 런 실행")}
        </button>
      </div>
      {triggerMsg && <div className="px-3 py-2 bg-blue-500/10 border border-blue-500/30 rounded-md text-xs text-blue-300">{triggerMsg}</div>}

      {/* 드리프트 배너 */}
      {run && drift.length > 0 && (
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4">
          <div className="text-sm font-semibold text-rose-300 mb-2">
            {L(`Documentation drift: ${drift.length} cells documented as available but not working`, `문서 드리프트: 문서상 제공인데 동작하지 않는 셀 ${drift.length}개`)}
          </div>
          <ul className="space-y-1 text-xs text-gray-300">
            {drift.slice(0, 10).map((c) => (
              <li key={`${c.feature}|${c.surface}|${c.model_key}`} className="flex items-center gap-2 flex-wrap">
                <button type="button" onClick={() => setSelected(c)} className="font-mono text-rose-200 hover:underline">{c.feature}</button>
                <span className="text-gray-500">{c.surface} · {c.model_label}</span>
                <span className="text-gray-600">documented {DOC_LABEL[c.documented]} → observed</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.status]}`}>{STATUS_LABEL[c.status]}</span>
              </li>
            ))}
            {drift.length > 10 && <li className="text-gray-500">{L(`+${drift.length - 10} more`, `외 ${drift.length - 10}건`)}</li>}
          </ul>
        </div>
      )}
      {run && latest && latest.changes.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-gray-300">
          <div className="text-sm font-semibold text-amber-300 mb-1">{L(`Changes since run #${latest.previous_run_id}: ${latest.changes.length}`, `이전 런(#${latest.previous_run_id}) 대비 변경 ${latest.changes.length}건`)}</div>
          <ul className="space-y-0.5">
            {latest.changes.slice(0, 10).map((c) => (
              <li key={`${c.feature}|${c.surface}|${c.model_key}`}>
                <span className="font-mono">{c.feature}</span> · {c.surface} · {c.model_label}: {c.before ?? L("new", "신규")} → <span className={c.after === "supported" ? "text-emerald-300" : c.after === "broken" ? "text-rose-300" : "text-amber-300"}>{c.after}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 엔드포인트 헬스 카드 */}
      {run && catalog && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          {catalog.surfaces.map((s) => {
            const h = surfaceHealth(cells, s.id);
            return (
              <div key={s.id} className="bg-gray-900/50 light:bg-white border border-gray-800 rounded-xl p-4">
                <div className="text-sm font-bold text-gray-100">{s.label}</div>
                <div className="text-[11px] text-gray-500 font-mono">{s.region}</div>
                <div className="mt-2 flex items-end gap-2">
                  <span className="text-2xl font-bold text-gray-100 tabular-nums">{h.health}%</span>
                  <span className="text-[11px] text-gray-500 mb-1">{L("of should-work checks pass", "동작해야 하는 검사 통과")}</span>
                </div>
                <div className="text-[11px] mt-1"><span className="text-emerald-300">● {h.supported}</span> <span className="text-rose-300 ml-2">● {h.broken} broken</span></div>
              </div>
            );
          })}
        </div>
      )}

      {!run && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-8 text-center text-sm text-gray-400">
          {L("No verification run yet — click \"Run verification\" (login required) or wait for the daily schedule.", "아직 실행된 검증 런이 없습니다 — \"검증 런 실행\"(로그인 필요)을 누르거나 일일 스케줄을 기다려 주세요.")}
        </div>
      )}

      {run && (
        <div className="flex items-center gap-2 flex-wrap">
          {(["all", "drift", "supported", "partial", "unsupported", "broken", "inconclusive"] as const).map((s) => (
            <button key={s} onClick={() => setFilter(s)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${filter === s ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"}`}>
              {s === "all" ? L("All", "전체") : s === "drift" ? L("Drift", "드리프트") : STATUS_LABEL[s]}
            </button>
          ))}
          <span className="text-xs text-gray-500 ml-2">{groups.reduce((n, g) => n + g.rows.length, 0)} {L("features", "피처")}</span>
        </div>
      )}

      {run && catalog && (
        <div className="overflow-x-auto bg-gray-900/50 border border-gray-800 rounded-xl">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-gray-800">
                <th rowSpan={2} className="text-left px-3 py-2 text-gray-400 font-medium sticky left-0 bg-gray-900 light:bg-white align-bottom">{L("Feature", "피처")}</th>
                {colGroups.map((g) => (
                  <th key={g.group} colSpan={g.ids.length} className="text-left px-3 pt-2 text-gray-300 font-semibold whitespace-nowrap border-l border-gray-800">
                    {SURFACE_GROUP_LABEL[g.group]?.[lang === "en" ? "en" : "ko"] ?? g.group}
                  </th>
                ))}
              </tr>
              <tr className="border-b border-gray-800">
                {catalog.surfaces.map((s) => (
                  <th key={s.id} className="text-left px-3 pb-2 text-gray-500 font-medium whitespace-nowrap border-l border-gray-800">{s.short}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const open = !collapsed.has(g.id);
                return (
                  <Fragment key={g.id}>
                    <tr onClick={() => setCollapsed((c) => { const n = new Set(c); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n; })}
                        className="border-t-2 border-t-gray-700 bg-gray-900/80 light:bg-gray-50 cursor-pointer hover:bg-gray-800/60">
                      <td className="px-3 py-2 sticky left-0 bg-gray-900 light:bg-white" colSpan={1}>
                        <span className={`text-[10px] text-gray-500 inline-block mr-2 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
                        <span className="font-bold text-gray-100 text-sm">{g.label}</span>
                        <span className="ml-2 text-[11px] text-gray-500">{g.rows.length}</span>
                      </td>
                      <td colSpan={surfaces.length} />
                    </tr>
                    {open && g.rows.map((row: RowView) => (
                      <tr key={row.id} className="border-b border-gray-800/60" title={row.desc}>
                        <td className="px-3 py-1.5 pl-8 sticky left-0 bg-gray-900 light:bg-white">
                          <div className="flex items-center gap-2">
                            <span className="text-gray-200 text-[12px]">{row.label}</span>
                            {row.verification !== "evidence" && <span className="px-1 py-px text-[9px] rounded bg-gray-800 text-gray-500" title={L("Verification strength", "검증 강도")}>{row.verification}</span>}
                            {row.drift > 0 && <span className="text-[10px] text-rose-300">▲{row.drift}</span>}
                          </div>
                          <div className="text-gray-500 font-mono text-[10px]">{row.id}</div>
                        </td>
                        {surfaces.map((s) => (
                          <td key={s} className="px-3 py-1.5 border-l border-gray-800/60">
                            <div className="flex items-center gap-2">
                              <span className="w-7 text-[9px] text-gray-500 tabular-nums" title={L("documented", "문서")}>{DOC_LABEL[row.documented[s]] ?? "?"}</span>
                              <CellBadge agg={row.cells[s] ?? aggregateCell([])} onPick={setSelected} />
                            </div>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 text-xs text-gray-400 leading-relaxed space-y-1.5">
        <div className="text-sm font-semibold text-gray-200 mb-1">{L("How to read", "읽는 법")}</div>
        <p>1 · {L("Rows are the features listed on platform.claude.com/docs/en/build-with-claude/overview (+4 core Messages checks and the Models API). The small GA/Beta/— tag in each cell is what the documentation says for that platform.", "행은 platform.claude.com/docs/en/build-with-claude/overview의 피처 목록(+코어 Messages 4종, Models API)입니다. 셀 앞의 GA/Beta/— 태그가 해당 플랫폼의 문서상 기대치입니다.")}</p>
        <p>2 · {L("Each cell aggregates Fable 5.1, Fable 5, Opus 5 and Sonnet 5 (Mantle excludes Fable 5.1 — US GovCloud only). Click to open per-model evidence: request snapshot, response signal, error.", "각 셀은 Fable 5.1·Fable 5·Opus 5·Sonnet 5 결과를 집계합니다(Mantle은 Fable 5.1 제외 — US GovCloud 전용). 클릭하면 모델별 증거(요청 스냅샷·응답 신호·오류)를 볼 수 있습니다.")}</p>
        <p>3 · {L("Drift = documented as available but observed unsupported/broken. Inconclusive = definition accepted but the model did not use the feature. N/A = not applicable by design (e.g. Converse has no field for it).", "드리프트 = 문서상 제공인데 실측 미지원/오류. Inconclusive = 정의는 수락됐지만 모델이 기능을 쓰지 않음. N/A = 설계상 부적용(예: Converse에 해당 필드 없음).")}</p>
        <p>4 · {L("Runs daily via EventBridge → Fargate (manual trigger runs inside the backend). Evidence is stored in RDS; the previous run is diffed at the top.", "EventBridge → Fargate로 매일 실행(수동 트리거는 backend 내부). 증거는 RDS에 저장되고 직전 런 대비 변경이 상단에 표시됩니다.")}</p>
      </div>

      {selected && run && <EvidenceModal runId={run.id} cell={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
```

- [ ] **Step 5: Type-check + lint** — `cd frontend && npx tsc --noEmit && npm run lint` → clean (fix any `import/first` by hoisting the type import in `api.ts`).

- [ ] **Step 6: Commit** — `git add frontend/src && git commit -m "feat(frontend): /claude-features 페이지 + 헤더 메뉴 + 4열 매트릭스 패널(드리프트 배너·증거 모달·트리거)"`

---

### Task 10: CDK — daily Fargate task, env, tests

**Files:**
- Modify: `cdk/lib/stacks/scheduler-stack.ts` (after `gptBenchTaskDef` L267-274: new task def; `RunTaskFamilyWildcard` resources L296-303; new Schedule after `GptBenchSchedule` L353-365; `environment` L199-221: add two env vars)
- Modify: `cdk/lib/stacks/app-services-stack.ts` (`backendEnv` L170-190: add the same two env vars)
- Modify: `cdk/test/scheduler-stack.test.ts` (counts 3→5, add `rate(24 hours)` + CMD test)

**Interfaces:**
- Produces: task def `FeaturesVerifyTaskDef` (CMD `python -m features_runner --once`, log group `/ecs/features`), schedule `FeaturesVerifySchedule` `rate(24 hours)`; env `MANTLE_ANTHROPIC_REGION=ap-northeast-1`, `FEATURES_MCP_SERVER_URL=https://mcp.deepwiki.com/mcp` on all scheduler tasks and the backend service.

- [ ] **Step 1: Update tests first** in `cdk/test/scheduler-stack.test.ts`:

```ts
  it("Schedule이 5개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify)", () => {
    template.resourceCountIs("AWS::Scheduler::Schedule", 5);
  });
  // ... (기존 3 → 5)
  it("TaskDefinition이 5개 생성된다", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 5);
  });

  it("FeaturesVerify는 rate(24 hours) 스케줄 + features_runner --once CMD (v2.23.0)", () => {
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({ ScheduleExpression: "rate(24 hours)" }));
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([Match.objectLike({
        Command: ["python", "-m", "features_runner", "--once"],
        Environment: Match.arrayWith([Match.objectLike({ Name: "MANTLE_ANTHROPIC_REGION", Value: "ap-northeast-1" })]),
      })]),
    }));
  });
```

Run: `cd cdk && npx jest test/scheduler-stack.test.ts` → the two count tests and the new test FAIL (3/4 vs 5).

- [ ] **Step 2: `scheduler-stack.ts` edits**

Environment block (inside `buildTaskDef`, after `OPENAI_GLOBAL_BASE_URL` line):
```ts
          // Claude API Features 검증 (v2.23.0) — Mantle /anthropic 리전 명시(기본값과 동일하나 코드 의존 제거),
          // MCP 커넥터 프로브용 공개 read-only MCP 서버 (서버 장애는 inconclusive로 격리).
          MANTLE_ANTHROPIC_REGION: "ap-northeast-1",
          FEATURES_MCP_SERVER_URL: "https://mcp.deepwiki.com/mcp",
```

After `gptBenchTaskDef`:
```ts
    // Claude API Features 검증 (v2.23.0) — 33 문서 피처 × 4 surface × 대표 4모델 실행-증거, 일 1회.
    // bedrock:* + bedrock-mantle:* IAM 체인이 필요하므로 autoprober role 재사용. CP는 API 키(secret).
    const featuresTaskDef = buildTaskDef(
      "FeaturesVerifyTaskDef",
      autoProberTaskRole,
      ["python", "-m", "features_runner", "--once"],
      "/ecs/features",
    );
```

`RunTaskFamilyWildcard` resources: append
```ts
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${featuresTaskDef.family}:*`,
```

After `GptBenchSchedule`:
```ts
    new scheduler.Schedule(this, "FeaturesVerifySchedule", {
      // 일 1회 (사용자 결정 2026-09-05) — 1런 ≈ 550 API 호출, 토큰 비용 대략 $3~5 (Fable 2종 지배)
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.hours(24)),
      description: "Claude API Features verification: 39 features x CP/Mantle/InvokeModel/Converse, daily",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: featuresTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });
```

Also update the file header comment (add a `rate(24 hours) → FeaturesVerify` line) and the `AwsSolutions-ECS2` reason is unchanged (values are non-sensitive).

- [ ] **Step 3: `app-services-stack.ts`** — in `backendEnv` after `OPENAI_GLOBAL_BASE_URL` add the same two entries with the same comment.

- [ ] **Step 4: Verify** — `cd cdk && npm run lint && npx tsc --noEmit && npx jest test/scheduler-stack.test.ts && npx cdk synth --all --quiet` → all green (synth runs cdk-nag; no new wildcard resources were added so no new suppressions).

- [ ] **Step 5: Commit** — `git add cdk && git commit -m "infra(scheduler): FeaturesVerify 일일 Fargate 태스크 + MANTLE_ANTHROPIC_REGION/FEATURES_MCP_SERVER_URL env, stale 스케줄러 테스트 3→5 수정"`

---

### Task 11: Version bump, ADR-026, CHANGELOG, README/CLAUDE/architecture docs

**Files:**
- Modify: `frontend/src/lib/version.ts` (`"v2.23.0"`), `frontend/package.json` (`"2.23.0"`), `README.md:4` badge, `CLAUDE.md` overview line + architecture tree + directory tree + models section, `CHANGELOG.md` (new top entry), `docs/architecture.md` (job table, log groups, ADR table), `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `frontend/CLAUDE.md`, `frontend/src/components/CLAUDE.md`
- Create: `docs/decisions/ADR-026-claude-api-feature-verification-matrix.md`

- [ ] **Step 1: Version strings** — set `APP_VERSION = "v2.23.0"`, package.json `2.23.0`, README badge `version-2.23.0`, CLAUDE.md `(v2.23.0 — …)`. (`backend/main.py` was done in Task 6.) Verify: `grep -rn "2\.22\.1" --include=*.ts --include=*.json --include=*.py --include=*.md . | grep -v CHANGELOG | grep -v node_modules` → only historical mentions remain.

- [ ] **Step 2: ADR-026** — `docs/decisions/ADR-026-claude-api-feature-verification-matrix.md`:

```markdown
# ADR-026: Claude API Features 검증 매트릭스 — 문서 기대치 vs 실측 드리프트 (별도 메뉴)

- **Status**: Accepted
- **Date**: 2026-09-05
- **Related**: ADR-021 (실행-증거), ADR-022 (Mantle bearer + IAM 체인), ADR-023 (정직한 제외), v2.23.0
- **Spec**: docs/superpowers/specs/2026-09-05-claude-features-verify-design.md

## Context

platform.claude.com "Build with Claude" 개요는 33개 피처를 플랫폼별 가용성(GA/Beta/미제공)과 함께 나열한다.
운영자는 이 목록이 Claude Platform on AWS · Bedrock Mantle `/anthropic` · Bedrock runtime(InvokeModel/Converse)에서
오늘 실제로 동작하는지 알아야 한다. 기존 `/parity`는 모델 중심(43모델 × 6 surface × 19피처)이라 "문서 기대치"
차원이 없고, 피처 12개가 acceptance 수준이며 도구 타입 문자열이 낡았다.

## Decision

1. **형제 패키지 `backend/claude_features/`** — 패리티는 그대로 두고 순수 함수만 공유. 카탈로그는 문서 33 + 코어 4 + Models API = 39행,
   행마다 `documented{cp,mantle,bedrock_invoke,bedrock_converse}`와 검증 강도(`evidence|acceptance|capability|negative`)를 명시.
2. **전송기 4개, 본문 1개** — Anthropic Messages JSON을 raw httpx(CP: x-api-key+workspace, Mantle: SigV4 파생 bearer) /
   boto3 InvokeModel(`anthropic_version`+body `anthropic_beta`) / boto3 Converse(프로브가 넘긴 Converse 매핑만)로 흘린다.
   SDK 미사용 — `anthropic>=0.40.0` 미고정으로 빌드 시 1.x 메이저 업이 들어오기 때문.
3. **대표 모델 4종 고정**(Fable 5.1·Fable 5·Opus 5·Sonnet 5, Haiku 제외). Mantle은 Fable 5.1 제외 — US GovCloud 전용 → `not_applicable`.
4. **상태 6종 + 판정 4종** — `supported|unsupported|broken|inconclusive|skipped|not_applicable` × `match|drift|undocumented|none`.
   `inconclusive`(정의 수락, 미호출)와 `not_applicable`(설계상 부적용)을 unsupported와 분리해 오판을 막는다.
5. **부정 제어(negative)** — effort/inference_geo처럼 응답에 신호가 없는 파라미터는 잘못된 값이 그 파라미터를 지목하는 400으로
   거부되는지를 함께 확인해 "조용히 무시"와 "검증됨"을 구분한다.
6. **일 1회 Fargate + JWT 수동 트리거**, 별도 테이블 `feature_runs/feature_results`(60런 보존), `/api/features/*`, `/claude-features` 메뉴.
7. **고비용 프로브도 실행**(web search·code execution·advisor·batches·files·skills; 생성물은 즉시 취소/삭제). 1M 컨텍스트만 capability 검사.

## Consequences

- (+) 문서 드리프트가 배너로 드러남; 셀 클릭으로 요청 스냅샷·응답 신호·문서 링크까지 추적.
- (+) 문서 상충 지점(Mantle `anthropic-beta` 헤더, Mantle/InvokeModel structured outputs, P-AWS 서버측 fallback)이 실측으로 닫힘.
- (−) 런당 토큰 비용 대략 $3~5(월 ~$100~150), MCP 프로브는 공개 MCP 서버 의존(장애는 inconclusive로 격리).
- (−) 신규 피처 추가 시 3단: 카탈로그 행(+documented) → 프로브 함수(4 surface 분기) → 테스트. Converse 표현 불가 목록(`_CONVERSE_NOT_EXPRESSIBLE`) 갱신.
```

- [ ] **Step 3: CHANGELOG** — new top entry (bilingual bullets, `### Added` / `### Infra` / `### Fixed`):

```markdown
## v2.23.0 — 2026-09-05

### Added
- **Claude API Features page (`/claude-features`)** — every feature on platform.claude.com "Build with Claude" (33) plus 4 core Messages checks and the Models API, executed for real against Claude Platform on AWS, Bedrock Mantle `/anthropic` (ap-northeast-1) and Bedrock runtime (InvokeModel + Converse sub-columns) with Claude Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5 (Mantle excludes Fable 5.1 — US GovCloud only). Each cell carries the documented availability (GA/Beta/—) next to the observed status; a **documentation-drift banner** lists cells documented as available but observed unsupported/broken. Evidence modal shows request snapshot, response signal, error, doc link and verification strength. New package `backend/claude_features/` (catalog 39 × 4 surfaces, raw httpx/boto3 transports, probes, pure engine, runner), tables `feature_runs`/`feature_results`, API `/api/features/{catalog,latest,evidence,trigger}`, CLI `features_runner --once|--smoke`. See ADR-026.
- **Claude API 기능 검증 페이지(`/claude-features`)** — platform.claude.com "Build with Claude"의 피처 33개 + 코어 Messages 4종 + Models API를 Claude Platform on AWS · Bedrock Mantle `/anthropic`(ap-northeast-1) · Bedrock runtime(InvokeModel + Converse 서브열)에서 Claude Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5로 실제 실행(Mantle은 Fable 5.1 제외 — US GovCloud 전용). 셀마다 문서상 가용성(GA/Beta/—)과 실측 상태를 병기하고, 문서상 제공인데 미지원/오류인 셀은 **문서 드리프트 배너**로 표시. 증거 모달에 요청 스냅샷·응답 신호·오류·문서 링크·검증 강도. 신규 패키지 `backend/claude_features/`(카탈로그 39 × 4 surface, raw httpx/boto3 전송기, 프로브, 순수 엔진, 러너), 테이블 `feature_runs`/`feature_results`, API `/api/features/{catalog,latest,evidence,trigger}`, CLI `features_runner --once|--smoke`. ADR-026 참조.

### Infra
- New EventBridge schedule `FeaturesVerifySchedule` (`rate(24 hours)`) → Fargate `FeaturesVerifyTaskDef` (`python -m features_runner --once`, log group `/ecs/features`, autoprober task role reused — no new IAM). Env `MANTLE_ANTHROPIC_REGION=ap-northeast-1` and `FEATURES_MCP_SERVER_URL` injected into all scheduler tasks and the backend service. Estimated cost ≈ $3–5 per run (Fable-dominated), approved by the user on 2026-09-05.
- 신규 EventBridge 스케줄 `FeaturesVerifySchedule`(`rate(24 hours)`) → Fargate `FeaturesVerifyTaskDef`(`python -m features_runner --once`, 로그 그룹 `/ecs/features`, autoprober 태스크 롤 재사용 — 신규 IAM 없음). env `MANTLE_ANTHROPIC_REGION=ap-northeast-1`·`FEATURES_MCP_SERVER_URL`을 스케줄 태스크 전체와 backend 서비스에 주입. 런당 비용 대략 $3~5(Fable 지배), 2026-09-05 사용자 승인.

### Fixed
- `cdk/test/scheduler-stack.test.ts` was stale since v2.18.0 (expected 3 schedules/task definitions, actual 4) and failed `make verify`; counts updated to 5 with the new task.
- v2.18.0 이후 낡아 `make verify`를 깨뜨리던 `cdk/test/scheduler-stack.test.ts`(기대 3, 실제 4) 카운트를 신규 태스크 포함 5로 갱신.
```

- [ ] **Step 4: README** — EN/KO: "Nine analytical pages" → "Ten analytical pages" adding `Claude API Features (documented feature × endpoint × model evidence matrix with doc-drift detection)` / "10개 분석 페이지 … Claude API 기능 검증(문서 피처 × 엔드포인트 × 모델 증거 매트릭스 + 문서 드리프트 감지)"; add job bullet `- **Daily Claude API Features sweep** — …` / `- **일일 Claude API 기능 검증 스윕** — …`; project-structure lines add `/claude-features`; "ADR-001 through ADR-025" → 026 (both languages).

- [ ] **Step 5: CLAUDE.md (root)** — overview version; architecture tree add `├── /claude-features — Claude API Features (33 문서 피처 × CP/Mantle/InvokeModel/Converse × 4모델 실행-증거 + 문서 드리프트, v2.23.0)` and scheduler line `└── FeaturesVerify Fargate Task → 일 1회 …`; directory tree add `claude_features/`, `features_runner.py`, `routers/features.py`, `app/claude-features/page.tsx`, `components/ClaudeFeaturesPanel.tsx`, `lib/claudeFeatures.ts`; env table add `MANTLE_ANTHROPIC_REGION` (`ap-northeast-1`) and `FEATURES_MCP_SERVER_URL`; ADR range `ADR-001~026`; add a short "Claude API Features (v2.23.0)" bullet under Monitored Models noting the 4-model set and Mantle Fable 5.1 GovCloud exclusion.

- [ ] **Step 6: Sub-CLAUDE.md + architecture.md** — `backend/CLAUDE.md` Key Files: `features_runner.py`, `claude_features/` (one line each); `backend/routers/CLAUDE.md`: `features.py` line + "17 routers"; `frontend/CLAUDE.md` Pages: add `/gpt-on-aws` (missing) and `/claude-features`; `frontend/src/components/CLAUDE.md`: `ClaudeFeaturesPanel.tsx` line; `docs/architecture.md`: scheduling table row (FeaturesVerify, rate 24h, `/ecs/features`), also add the missing GptBench row, log-group list, Scheduler stack "EventBridge ×5, TaskDef ×5", ADR table row 025 (missing) + 026, "ADR-001 ~ ADR-026".

- [ ] **Step 7: Commit** — `git add -A docs CHANGELOG.md README.md CLAUDE.md backend/CLAUDE.md backend/routers/CLAUDE.md frontend/CLAUDE.md frontend/src/components/CLAUDE.md frontend/src/lib/version.ts frontend/package.json && git commit -m "docs(release): v2.23.0 — ADR-026, CHANGELOG, README/CLAUDE/architecture 갱신 + 버전 6곳 범프"`

---

### Task 12: Full verification run, review, PR

- [ ] **Step 1: Full local run for all 4 models (smoke, no DB)** — `cd backend && python3.12 -m features_runner --smoke --json > <scratchpad>/smoke-all.json` then summarize counts per surface/status and the drift list. Fix any probe defects (own commits). Record the summary in the plan's "## Smoke log".
- [ ] **Step 2: Whole test suite** — `cd backend && python3.12 -m pytest tests/ -q`; `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`; `cd cdk && npm test && npx cdk synth --all --quiet`; `ruff check backend/`.
- [ ] **Step 3: Code review** — request review via `superpowers:requesting-code-review` (or `pr-review-toolkit:review-pr`) focusing on: probe evidence honesty (no acceptance masquerading as evidence), secrets never logged (`_req` trims but must never include `x-api-key`), thread-safety (no DB session in worker threads), Converse mapping correctness.
- [ ] **Step 4: Push + PR** — `git push -u origin feat/claude-features-verify`; `gh pr create --title "feat(features): Claude API Features 검증 메뉴 — 33 문서 피처 × CP/Mantle/InvokeModel/Converse × 4모델 (v2.23.0)" --body-file <summary>`. Deployment (image build → cdk deploy with digests → CloudFront invalidation → first run log check) follows `docs/runbooks/deploy.md` and is a separate user-confirmed step.

---

## Self-review (writing-plans)

- **Spec coverage**: catalog 39 rows/4 surfaces/documented+verification (T1); transports & SDK-free (T2); probes incl. negative controls, inconclusive, not_applicable, route-less endpoints, computer-use fallback, MCP env (T3–T4); tables/runner/failed status/retention/CLI smoke (T5); API incl. drift + diff (T6); local smoke before deploy (T7, T12); frontend lib+tests, page, nav, panel with drift banner/health cards/evidence modal/trigger (T8–T9); CDK schedule/env/test fix (T10); ADR-026, CHANGELOG, README, CLAUDE, architecture, version 6 places (T11). Spec "Risks" are closed by T7/T12 measurements.
- **Placeholders**: none — every step has concrete code or exact commands.
- **Type consistency**: `is_applicable -> (bool, str|None)` used identically in T1/T5; `ProbeOutcome(status, latency_ms, evidence, error)` in T3/T5; `NormalizedResponse.{content,usage,stop_reason,top,events}` in T2/T3/T4; frontend `FeatureCell` fields mirror `build_latest_payload` results (T6/T8/T9); nav key `features` in T9 page + header.

---

## Smoke log

### 2026-09-05 — Task 7 로컬 라이브 스모크 (python3.12, IAM 롤 `VscodeServerStack-VSCode-Role`, SSM 키)

명령 (자격은 `aws ssm get-parameter --with-decryption`으로 export, 값 미출력):

```bash
python3.12 -m features_runner --smoke --models sonnet-5 --features messages_basic,streaming,system_prompt,tool_use,token_counting
python3.12 -m features_runner --smoke --models sonnet-5 --json > <scratchpad>/smoke-sonnet5.json
python3.12 -m features_runner --smoke --models fable-5-1 --features tool_use,strict_tool_use,extended_thinking,adaptive_thinking,advisor_tool,bash_tool,computer_use
```

**sonnet-5 전체 스윕 (39피처 × 4 surface = 156행, 프로브 결함 수정 후)** — `broken` 0, `inconclusive` 0.

| surface | supported | unsupported | broken | inconclusive | not_applicable | skipped |
|---|---|---|---|---|---|---|
| cp | 37 | 1 | 0 | 0 | 1 | 0 |
| mantle | 0 | 38 | 0 | 0 | 0 | 1 |
| bedrock_invoke | 22 | 15 | 0 | 0 | 1 | 1 |
| bedrock_converse | 12 | 8 | 0 | 0 | 18 | 1 |

판정 합계: `match` 100 · `drift` 29 · `undocumented` 2 · `none` 25.

**드리프트 목록 (29)**
- `mantle` 23건 — 전부 같은 원인: ap-northeast-1 `/anthropic`이 `anthropic.claude-sonnet-5`에 `not_found_error`
  ("The model 'anthropic.claude-sonnet-5' does not exist"). Opus 4.8은 같은 리전에서 200이므로 자격·전송 문제가 아니라
  **모델 서빙 리전 문제**(사용자 결정으로 리전은 ap-northeast-1 고정). 문서상 `ga`인 피처가 전부 `unsupported`로 떨어진다.
  나머지 15건은 문서도 `no`라 `match`(batches/files/models/서버측 도구 등) — Mantle의 404는 실측으로 확인됐다.
- `bedrock_invoke` 3건 · `bedrock_converse` 3건 — 동일 3피처:
  - `strict_tool_use`: `tools.0.custom.strict: Extra inputs are not permitted` (문서 ga → 미지원 실측)
  - `structured_outputs`: `output_config.format: Extra inputs are not permitted` (AWS 문서 ga vs Anthropic Bedrock 페이지 미지원 → **Anthropic 쪽이 맞다**)
  - `token_counting`: `The provided model doesn't support counting tokens.` — Bedrock `CountTokens`가 Seoul에서 Claude 5 세대를 거부.
    `global.anthropic.claude-sonnet-5` / 베이스 `anthropic.claude-sonnet-5` / `global.anthropic.claude-{opus-5,fable-5,fable-5-1,sonnet-4-6}` 모두 동일 거부,
    `us.*`·`apac.*`는 Seoul에서 identifier invalid → 프로파일 형태 문제가 아니라 모델 지원 문제.

**문서 미기재 지원 (undocumented) 2건** — `browser_use`가 `cp`와 `bedrock_invoke`에서 실제 동작
(`tool_use{name: screenshot, toolset_name: browser}`). 카탈로그 기대치는 4열 전부 `no`.

**닫힌 스펙 리스크**
- computer use: `computer_toolset_20260801`이 CP·InvokeModel 모두 1차 시도에서 통과(레거시 폴백 미사용) → 스펙의 "toolset 미제공 우려" 해소.
- `search_results` Converse: 구모델 전용이 아니라 Sonnet 5·Converse에서 `searchResultLocation` 인용까지 정상.
- `server_side_fallback` CP: `'claude-sonnet-5' does not support the `fallbacks` parameter.` → 문서 기대치 `unknown`이 `unsupported`로 확정(verdict `none` 유지).
- Ruling H(`files_api`·`agent_skills`는 CP에 beta 헤더 미전송): 두 피처 모두 헤더 없이 200 → 레거시 beta 폴백 불필요.
- MCP 커넥터: 공개 서버(`https://mcp.deepwiki.com/mcp`) 도달 성공 → `supported`. 서버 장애 시 `inconclusive` 경로는 미발동.

**fable-5-1 부분 스윕 (7피처)** — 기대대로: `tool_use`/`strict_tool_use`가 `tool_choice: auto` + 프롬프트 지시로 왕복 성공(CP),
`extended_thinking`은 4열 전부 `not_applicable`(adaptive-only 모델의 정확한 거부 문구 확인), `mantle` 7행 전부 `not_applicable`(GovCloud).
`strict_tool_use`는 Bedrock 두 열에서 sonnet-5와 같은 이유로 `unsupported`(drift).

### 발견·수정한 프로브 결함 4건

| # | 증상 | 근본 원인 | 수정 | 커밋 |
|---|---|---|---|---|
| 1 | Mantle 전 행 `broken` + `AttributeError: 'dict' object has no attribute 'dumps'` | `_HttpTransport.request(json=…)` 파라미터가 `json` 모듈을 가려, 4xx **JSON 본문** 직렬화(`json.dumps`)에서 터짐. 문자열 본문 404(streaming)만 정상 분류돼 증상이 부분적이었다 | 모듈 별칭 `_json` 도입 | `3ca2509` |
| 2 | `effort` bedrock_invoke·bedrock_converse `broken` | 부정 제어 400이 "effort" 문자열을 포함해야 통과 — Bedrock은 필드 경로를 지우고 ``unknown variant `ultra`, expected one of `low`…`xhigh`…`` 만 남긴다 | `engine.effort_rejection_names_param()` — 파라미터 지목 또는 (잘못된 값 + effort 전용 값 `xhigh` 열거)만 인정(아무 400이나 통과시키지 않음) | `52b8b53` |
| 3 | `agent_skills` cp `broken` (`container: null`) | 컨테이너는 코드 실행의 부산물인데 프롬프트가 "스킬 이름을 말해라"여서 모델이 코드를 실행하지 않았다 | 프롬프트를 실제 `ls /mnt/skills` 실행 지시로 교체(→ `container.id` + `container.skills[pdf@20260709]`), 도구 미호출 시 `broken` 대신 `inconclusive` | `5f0808e` |
| 4 | `adaptive_thinking` fable-5-1의 Bedrock 두 열 `broken` | `effort: medium`에서 adaptive 모델이 쉬운 문제에 사고를 생략(프롬프트 난이도로는 안 바뀜 — 어려운 프롬프트도 미사고 확인). 또한 Bedrock Fable 5.1은 요약 텍스트를 비우고 `signature`만 채운다 | `effort: high` 고정 + `engine.has_thinking_evidence()`(텍스트 또는 서명) — 빈 블록은 계속 실패 | `0067db2` |

추가로 증거를 **강화**한 1건: `search_results`의 Converse 경로가 "아무 인용이나 있으면 통과"였다(문서 출처 인용도 통과).
실측 shape에 맞춰 `engine.citation_is_search_result()`로 `search_result_location` / `location.searchResultLocation`만 인정 — `1ac28c4`.
수정 4건 + 강화 1건 모두 순수 로직 회귀 테스트를 동반한다(`backend/tests/test_claude_features.py`, 총 172 passed).

### 남은 이슈 / 미해결

- `inconclusive` 0건 — 서버측 도구·advisor·MCP 모두 CP에서 증거를 냈으므로 프롬프트 재강화 대상 없음. (Mantle 열은 모델 부재로 도달 전 실패.)
- Bedrock `CountTokens`의 Claude 5 세대 미지원은 **플랫폼 갭**으로 남긴다(카탈로그 기대치 `ga` 유지 → drift 표시가 제품 의도).
  기대치를 `no`로 바꾸는 것은 컨트롤러 결정 사항.
- Mantle 23건 drift도 리전 결정(ap-northeast-1 고정)에 따른 실측 결과로 남긴다. us-east-1은 sonnet-5를 서빙하므로,
  리전을 옮기면 Mantle 열이 대부분 되살아날 것으로 보이지만 이는 사용자 결정 영역.
- `browser_use`의 undocumented 지원 2건은 카탈로그 `documented`를 고칠 근거가 될 수 있으나(문서 기대치 변경) 컨트롤러 결정 사항.

---

### Task 13: Add the 5th surface — Bedrock runtime · Anthropic Messages API (`bedrock_messages`)

**Why (2026-09-05, user-provided references):** AWS "Build" guide and "Endpoints" page state that `bedrock-runtime` natively hosts the Anthropic Messages API at `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/messages` and recommend it for new applications and for "Migrating from Anthropic APIs". It supports cross-Region inference profile ids (`global.anthropic.claude-*`), SigV4 or a short-term token from `aws-bedrock-token-generator` (`x-api-key`), `anthropic-version: 2023-06-01`, and `anthropic-beta` headers. Verified in Seoul: `/v1/messages` 200; beta header accepted (200); `output_config.format` → 400 `Extra inputs are not permitted`; `/v1/messages/count_tokens` → HTTP **200 with body `{"Output":{"__type":"com.amazon.coral.service#UnknownOperationException"}}`**; `/v1/models/{id}` → 404 `<UnknownOperationException/>`.

**Files:**
- Modify: `backend/claude_features/catalog.py` (SURFACES/SURFACE_META/model_id_for/_SKIPPED/documented defaults), `backend/claude_features/transports.py` (`BedrockMessagesTransport`, coral UnknownOperation → `TransportError(404, …)`, `build_transport`), `backend/claude_features/probes.py` (`probe_tool_search` beta also on `bedrock_messages`), `backend/tests/test_claude_features.py`, `frontend/src/components/ClaudeFeaturesPanel.tsx` (grid cols + intro text), `cdk/lib/stacks/scheduler-stack.ts` (schedule description text), docs touched by Task 11 (surface count 4→5, cells 624→780, jobs 658 + pre-decided 122, ≈800 calls, ≈$5–7/run), `CHANGELOG.md` entry, ADR-026.

**Interfaces:**
- `SURFACES = ["cp", "mantle", "bedrock_messages", "bedrock_invoke", "bedrock_converse"]` (bedrock group contiguous). `SURFACE_META["bedrock_messages"] = {"label": "Bedrock runtime · Messages API", "short": "Messages API", "group": "bedrock", "region_env": "BEDROCK_FEATURES_REGION", "default_region": "ap-northeast-2"}`. `model_id_for("bedrock_messages", k)` → the `bedrock` id (same as invoke/converse).
- Documented defaults for `bedrock_messages`: copy the row's `bedrock_invoke` value, then override `structured_outputs: no`, `strict_tool_use: no`, `token_counting: no`, `tool_search: unknown` (AWS: tool search documented for InvokeModel only). Implement in `_f`: `documented.setdefault("bedrock_messages", documented["bedrock_invoke"])` followed by `_BEDROCK_MESSAGES_OVERRIDES` applied after `FEATURES` is built. Existing 4-key constant dicts (`ALL`, `CP_ONLY`, …) stay as they are.
- `_SKIPPED` gains `("context_window_1m", "bedrock_messages")`.
- `class BedrockMessagesTransport(_HttpTransport)`: `surface = "bedrock_messages"`, `routes = frozenset({"messages","count_tokens","batches","files","models","skills"})` (measure every route — this endpoint answers unknown routes explicitly), `__init__(region=None)`: `self.region = region or region_for("bedrock_messages")`, `self.base_url = f"https://bedrock-runtime.{self.region}.amazonaws.com/anthropic"`, `self._token = provide_token(region=self.region)`; `_headers` identical to Mantle's.
- `_HttpTransport.request`: after `parsed` is computed and before the `>= 400` check, add:
  `if isinstance(parsed, dict) and isinstance(parsed.get("Output"), dict) and "UnknownOperation" in str(parsed["Output"].get("__type", "")): raise TransportError(404, "UnknownOperationException: route not available on this endpoint")`.
- `build_transport` adds `"bedrock_messages": BedrockMessagesTransport`.
- `probe_tool_search`: `betas = ["tool-search-tool-2025-10-19"] if t.surface in ("bedrock_invoke", "bedrock_messages") else []`.
- Tests to update/add: `test_surfaces_and_models` (5 surfaces; `model_id_for("bedrock_messages","sonnet-5") == "global.anthropic.claude-sonnet-5"`); `test_is_applicable_rules` add `catalog.is_applicable("context_window_1m", "bedrock_messages", "opus-5") == (False, "skipped")`; `test_documented_defaults_from_overview` add `documented_for("token_counting","bedrock_messages") == "no"`, `documented_for("adaptive_thinking","bedrock_messages") == "ga"`, `documented_for("structured_outputs","bedrock_messages") == "no"`; `test_default_job_count_matches_spec_estimate` → `total == 39*5*4` and `(len(jobs), len(decided)) == (658, 122)` with the comment updated (+4 skipped on bedrock_messages); `test_routes_per_surface` add `"batches" in T.BedrockMessagesTransport.routes`; new `test_bedrock_messages_transport_headers_and_base(monkeypatch)` (monkeypatch `T.provide_token`? — `provide_token` is imported inside `__init__`; monkeypatch `aws_bedrock_token_generator.provide_token` via `monkeypatch.setattr("aws_bedrock_token_generator.provide_token", lambda region=None: "tok")`, assert base_url and `_headers()["x-api-key"] == "tok"`); new `test_http_request_maps_coral_unknown_operation_to_404(monkeypatch)` using the `_fake_httpx_client`-style fake whose `request()` returns status 200 and JSON `{"Output":{"__type":"com.amazon.coral.service#UnknownOperationException"},"Version":"1.0"}` → `pytest.raises(T.TransportError)` with `status_code == 404`.
- Frontend: `ClaudeFeaturesPanel.tsx` health-card grid `xl:grid-cols-4` → `xl:grid-cols-5`; intro sentence "Bedrock runtime (InvokeModel · Converse)" → "(Messages API · InvokeModel · Converse)" in EN/KO; no lib changes (columns are data-driven).
- CDK: `FeaturesVerifySchedule` description → `"Claude API Features verification: 39 rows x CP/Mantle/Bedrock(Messages,InvokeModel,Converse) x 4 models, daily"`; jest unchanged.
- Docs: every "4 surface"/"4열"/"624셀"/"506+118"/"≈650"/"$4~6" written by Task 11 → 5 surface/5열(Bedrock 3 서브열)/780셀/658+122/≈800/$5~7; add the AWS references (Build guide, Endpoints page, Messages API page) to ADR-026 and the spec's Goal table (new row for the surface).

- [ ] **Step 1: Update tests first, run to see failures** — `cd backend && python3.12 -m pytest tests/test_claude_features.py -q`.
- [ ] **Step 2: catalog.py + transports.py + probes.py edits** as specified; run tests → PASS; `ruff check backend/`.
- [ ] **Step 3: Live smoke of the new surface only** — `python3.12 -m features_runner --smoke --surfaces bedrock_messages --models sonnet-5` (39 rows). Expect: core 4 + adaptive/extended/citations/pdf/search_results/effort/fallback/caching/… supported or unsupported with clean errors; `token_counting`/`models_api`/`batch_processing`/`files_api` → unsupported via the coral/404 mapping; `structured_outputs`/`strict_tool_use` → unsupported. Triage any `broken` as in Task 7 (fix probe/transport with regression test, or add classifier marker). Record results in the plan's "## Smoke log".
- [ ] **Step 4: Frontend + CDK text edits**; `cd frontend && npx tsc --noEmit && npx vitest run`; `cd cdk && npx tsc --noEmit && npx jest test/scheduler-stack.test.ts`.
- [ ] **Step 5: Docs** — update the numbers/surface lists in CLAUDE.md, README (EN/KO), docs/architecture.md, ADR-026, CHANGELOG v2.23.0 (add a bullet pair for the new surface + AWS reference links), backend/CLAUDE.md, frontend/src/components/CLAUDE.md, and the spec's Goal table.
- [ ] **Step 6: Commit** — `feat(features): Bedrock runtime Anthropic Messages API 5번째 surface (bedrock_messages) + coral UnknownOperation→404 정규화 + 문서 5 surface 반영`.
