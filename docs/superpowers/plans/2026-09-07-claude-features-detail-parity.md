# Claude API Features 상세도 보강(패리티 수준) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Bring the `/claude-features` page (Claude API Features verification matrix) up to the level of detail the `/parity` page already offers — documented-health cards with a 6-state distribution bar, a Key Findings drawer per endpoint, model chips, catalog-sourced labels, a complete changes banner with a `kind` (catalog rule vs measured) tag, per-model latency in cell tooltips, a filter/collapse bug fix — and make failed cells carry real evidence (request snapshot, operation name, empty-body route) on the backend, without changing any verdict logic. Release as **v2.24.0** (2026-09-07).

**Architecture:** Pure derivations stay in `frontend/src/lib/claudeFeatures.ts` (vitest) and JSX stays in `frontend/src/components/ClaudeFeaturesPanel.tsx`; the panel keeps its inline `L(en, ko)` helper (no `i18n.ts`). Backend changes are confined to `backend/claude_features/{transports,probes,engine,catalog}.py` and `backend/routers/features.py`: a thread-local last-request recorder in the transports that `run_probe` reads on failure, richer `TransportError` messages that never touch `engine.classify` markers, request-snapshot meta keys unified to `api`/`note`, and `changes[].kind` computed in `build_latest_payload` from `FeatureResult.latency_ms IS NULL` (runner pre-decided rows). No DB schema change, no CDK change; backend and frontend ship in one deploy (RUL-4).

**Tech Stack:** Next.js 14 + React 18 + Tailwind (frontend, vitest, `tsc --noEmit`); FastAPI + SQLAlchemy backend tested with pytest under python3.12 and ruff; git on branch `feat/features-detail-parity` (HEAD `a048028`, clean tree).

**Spec:** `/home/ec2-user/my-project/model-monitoring/docs/decisions/ADR-026-claude-api-feature-verification-matrix.md` (the feature's design ADR; this release adds an addendum) and the completeness critic `/tmp/claude-1000/-home-ec2-user-my-project-model-monitoring/ef68f2b5-02fd-4585-a92e-3dd15047f81b/scratchpad/parity-ref/critic.md` (sections 4-A..4-F are folded into the tasks below). Per-candidate verification reports with file:line evidence: `/tmp/claude-1000/-home-ec2-user-my-project-model-monitoring/ef68f2b5-02fd-4585-a92e-3dd15047f81b/scratchpad/verify-{C1,C3,C4,C5,C6,C7,C8,C9,C10,C11,R1,R2,R3,R4,R5,R6,R7,R10,R11,R12}.md`; lens syntheses `parity-ref/synth-ui.md`, `parity-ref/synth-data.md`. (An older scratchpad prefix `…/5058926a-f4df-48c6-a740-4422a7c45745/scratchpad` is a symlink to the same directory.)

**Baselines (verified 2026-09-07 on `a048028`):** frontend `npx vitest run` → 50 passed (5 files), `npx tsc --noEmit -p .` → exit 0; backend `python3.12 -m pytest tests/test_claude_features.py -q` → 69 passed, `ruff check claude_features tests/test_claude_features.py` → All checks passed; full backend suite 191 passed. Line anchors in every task are for this HEAD; each edit also quotes the old text, so after earlier tasks shift lines, locate by the quoted text. Abbreviations: `CF:` = `ClaudeFeaturesPanel.tsx`, `CFL:` = `claudeFeatures.ts`, `PP:` = `ParityPanel.tsx` (reference only — never modified).

---

## Design decisions (binding)

D1 Health card headline = documented health: docHealth = supportedAmongDocumented / probedAmongDocumented where documented in {ga,beta} and probed status in {supported,unsupported,broken,inconclusive}; show "-" when probedAmongDocumented === 0. Below it a 6-state segmented bar over ALL cells of the surface (supported emerald, unsupported amber, broken rose, inconclusive violet, documented-only skipped sky, other skipped/N.A gray), a "{total} 셀" chip (total = all cells of the surface incl. N/A), a counts line, and a "▲ 드리프트 N" pill when drift > 0. Keep surfaceHealth() exported for backward compat but add surfaceSummary().

D2 Labels: build Map<featureId, label(lang)> and Map<surfaceId, short> from the loaded catalog (single source) and use them in the drift banner, changes banner, evidence modal header and the drawer. Keep raw ids in mono as secondary text.

D3 Changes banner: always render when previous_run_id != null: either the list (with "외 N건" beyond 10) or a gray "이전 런(#N) 대비 변경 없음." card; items clickable -> open the evidence modal via latest.results lookup; after-status pill uses the 6-state STATUS_STYLE. Backend: /api/features/latest changes[] gets kind: "catalog" | "measured" - "catalog" when either the before or after row is pre-decided (FeatureResult.latency_ms IS NULL, i.e. runner-decided not_applicable/skipped), else "measured"; frontend shows a small tag per item and a one-line summary "카탈로그 규칙 변경 N건, 실측 변경 M건".

D4 Drawer (Key Findings): the health card becomes a <button>; clicking opens a SurfaceDrawer for that surface with verdict-based sections: (1) 문서 드리프트 - verdict === "drift" grouped by feature, sorted by count desc, each with model list; (2) 프로브 오류 - status === "broken" regardless of verdict; (3) 의도된 격차 - status === "unsupported" && verdict === "match" as unique feature chips, subtitle "문서상 미제공, 실측도 미지원 (버그 아님)"; (4) 문서 미확정 - status unsupported && verdict none (documented unknown); (5) 문서에 없는 동작 - verdict === "undocumented" chips; (6) 모델별 문서 일치율 - per-model docHealth bar for all 4 models, Mantle Fable 5.1 shows mantle_reason instead of a bar. Empty sections show a green "없음" line. The pure derivation function surfaceFindings() lives in claudeFeatures.ts with vitest.

D5 Model chips: a chip row "전체 | Fable 5.1 | Fable 5 | Opus 5 | Sonnet 5" above the matrix; selecting one filters cells to that model_key before aggregation (buildGroups gets an optional modelKey param); a single-cell aggregate renders the cell badge normally (N/A and 문서상 지원 rules preserved).

D6 Latency: cell badge title (tooltip) lists per-model "label: N ms" lines (only for probed statuses with latency_ms != null; runtime-N/A rows with latency are excluded); dropdown items append "N ms" (or "-"); no backend change.

D7 Filter/collapse bug: when a status/drift filter is active, all groups render expanded and the toggle is disabled (chevron hidden); add "모두 펼치기 / 모두 접기" buttons when no filter is active.

D8 Backend evidence: (a) request snapshot on failure - transports record the last request body per thread (threading.local) via a record_request() hook called by every transport call path; run_probe uses last_request() (falling back to {"model": model_id}) on TransportError and generic exception paths and also for the success-path setdefault; (b) error context - boto ClientError wrapping keeps the AWS operation name: f"{code} ({operation}): {msg}"; empty-body HTTP errors render "HTTP 404: (empty body) GET /path" so the "http 404" marker still classifies as unsupported; (c) snapshot meta keys unified to api and note in _req/_req_snapshot callers (stream, path, endpoint -> api/note); (d) adaptive/extended thinking evidence stores n.usage. Classification (engine.classify) must remain unchanged - add regression tests proving classification of representative error strings is identical before/after.

D9 Docs: docs/api-reference.md gets an /api/features section (catalog, latest incl. changes.kind, evidence, trigger) mirroring the /api/parity section; CLAUDE.md overview corrects "프로브 658 + 사전판정 122" to 643 + 137 and mentions v2.24.0; frontend/src/components/CLAUDE.md ClaudeFeaturesPanel line updated (drawer, model chips, latency); docs/decisions/ADR-026 gets a short "v2.24.0 UI detail parity" addendum.

D10 Copy rules for Korean UI text: commas instead of middle dots for enumerations, list numbering "1.", assertive verdict wording; English strings via the panel inline L(en, ko) helper (this panel does not use i18n.ts). Version strings to bump in the final task: frontend/src/lib/version.ts APP_VERSION, frontend/package.json version, backend/main.py FastAPI(version=), README.md badge, CLAUDE.md overview, CHANGELOG.md new "## v2.24.0 - 2026-09-07" entry with bilingual bullets (EN then KO, as existing entries).

---

## Rulings

RUL-1 Drift-zero card: when latest.run exists and latest.drift.length === 0, render a one-line gray card "문서 드리프트 없음." / "No documentation drift." where the drift banner would be (negative results are stated explicitly, same principle as "변경 없음"). Belongs to the frontend-A changes-banner task.

RUL-2 D1 denominator keeps inconclusive (D1 verbatim).

RUL-3 i18n exception: frontend/src/components/CLAUDE.md records that ClaudeFeaturesPanel uses the inline L(en, ko) helper instead of i18n.ts (docs task).

RUL-4 Deploy: backend and frontend ship in one CDK deploy; frontend treats changes[].kind as optional (graceful without it). No code impact.

RUL-5 Health card counts line: always show supported / unsupported / broken; show inconclusive, documented-only skipped, and other skipped/N.A only when count > 0.

RUL-6 Label maps: frontend-A defines export interface LabelMaps { featureLabel: Map<string,string>; surfaceShort: Map<string,string> } and export function labelMaps(catalog, lang): LabelMaps plus featureLabelOf(maps, id) / surfaceShortOf(maps, id). frontend-B's SurfaceDrawer takes labels: LabelMaps (not a separate featureLabels Map) and uses featureLabelOf.

RUL-7 PROBED_STATUSES, isProbed(status), isDocumented(documented) are defined ONCE in the frontend-A surfaceSummary task; frontend-B tasks import them (delete the duplicate 3-line definition from the frontend-B draft).

RUL-8 filterActive = filter !== "all" only; the model chip does not force groups open.

RUL-9 Drawer chips (의도된 격차 / 문서 미확정 / 문서에 없는 동작) are <button>s that call onPick(chip.cells[0]) to open the evidence modal for the first model; the title attribute lists all models.

RUL-10 formatMs: null -> "-", 0 < ms < 1 -> "<1 ms", else Intl-formatted integer + " ms".

RUL-11 Backend change_kind gets a third input: change_kind(before_predecided: bool, after_predecided: bool, before_missing: bool = False) -> str returning "catalog" when before_missing is True (a cell that did not exist in the previous run can only appear through a catalog change) or when either row is pre-decided, else "measured". annotate_change_kinds passes before_missing = (change["before"] is None). Tests cover all four combinations.

RUL-12 D8(c): probe-side stream=True extras become api="messages (stream)" / api="converse (stream)" exactly as the backend draft specifies; transport-recorded failure snapshots keep the real body param stream: true.

RUL-13 Boto-path failure snapshots record the native InvokeModel/Converse body (truthful "what was sent"); shapes may differ slightly from the success path - acceptable, documented in a code comment.

RUL-14 CATALOG_VERSION (claude_features/runner.py) is NOT bumped in v2.24.0 (desc-only catalog edits); the docs task adds a release-checklist line to CLAUDE.md: "catalog rule changes (_NOT_APPLICABLE_BY_DOC, expectations) -> bump CATALOG_VERSION".

RUL-15 critic 4-F: the docs task also fixes frontend/src/components/CLAUDE.md:20 stale "도넛" wording for ParityPanel (segment bar since v2.16.3) and docs/api-reference.md parity trigger duration ("~3 min" -> "약 5-10분", per routers/parity.py); the new features section says "약 7분" per routers/features.py.

RUL-16 Task order and numbering: backend draft Tasks 1-5, then frontend-A Tasks 1-5, then frontend-B Tasks 1-5, then one final "Docs + version bump + CHANGELOG" task; renumber 1..16 in that order. Each task ends with green test commands and a commit step using the repo convention "<type>(<scope>): <한국어 요약>" (types feat/fix/test/docs; e.g. "feat(features): 헬스 카드 6상태 분포 막대 + 문서 기준 헬스"). No git push, no PR, no tag in any task - release is handled separately.

---

## Global Constraints

- **Korean UI copy (D10):** enumerations use commas, never middle dots (·); list numbering is `1.`; verdict wording is assertive ("확실한 미지원 응답"). The ` · ` separator between mono tokens in the run meta line (`#3 · catalog …`) and the evidence-modal title is an existing pattern, not sentence punctuation, and stays. EN/KO pairs in `ClaudeFeaturesPanel` go through the inline `L(en, ko)` closure (`CF:147`); `L` is scoped to the main component, so `CellBadge`, `EvidenceModal` and the new `SurfaceDrawer` use `const { lang } = useLang();` plus a local ternary/`T(en, ko)` helper. This panel does **not** use `src/lib/i18n.ts` (RUL-3 records the exception in Task 16).
- **Pure logic in `claudeFeatures.ts` with vitest; JSX in the panel.** There is no component test harness (all 5 vitest files live under `lib/`), so JSX-only tasks gate on `npx tsc --noEmit -p .` + the full `npx vitest run` staying green, plus a manual checklist.
- **Backend:** never add `from __future__ import annotations` to `backend/routers/features.py` (FastAPI router). `backend/claude_features/*.py` already use it and FastAPI does not import them directly — keep as is. `engine.classify` verdicts must not change (Task 1 pins them; every later backend task must keep the pins green). New error wording must not contain classification markers (`not found`, `no route`, `http 404`, `request is not valid`, … — `claude_features/engine.py:16-31`, `parity/engine.py:15-39`). No DB schema change (`FeatureResult.evidence` is JSON; `latency_ms` exists).
- **Test commands (every task must end green):**
  - frontend: `cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run` and `cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p .`
  - backend: `cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q` and `cd /home/ec2-user/my-project/model-monitoring/backend && ruff check claude_features tests/test_claude_features.py` (Task 5 and Task 15 add `routers/features.py` / run the full backend suite).
  - Expected running totals — frontend vitest: 50 → 58 (T6) → 58 (T7) → 60 (T8) → 62 (T9) → 64 (T10) → 70 (T11) → 70 (T12) → 72 (T13) → 74 (T14) → 75 (T15) → 75 (T16) → 76 only if optional T17 is executed. Backend `tests/test_claude_features.py`: 69 → 107 (T1) → 110 (T2) → 118 (T3) → 122 (T4) → 125 (T5) → 126 (T15); full backend suite 191 → 247 (T5) → 248 (T15).
- **New backend tests are appended at the END of `backend/tests/test_claude_features.py`** (currently 754 lines) so existing line anchors do not move; the only existing test edited is `test_build_latest_payload_computes_changes_and_drift` (:632-648, Task 5).
- **Version touchpoints (Task 16 only):** `frontend/src/lib/version.ts` `APP_VERSION`, `frontend/package.json` `"version"` (line 3), `backend/main.py` `FastAPI(version="2.23.1")` (line 215), `README.md` badge (line 4), `CLAUDE.md` overview (line 5), `CHANGELOG.md` (`## Unreleased` becomes `## v2.24.0 — 2026-09-07`, existing entries use the em dash). `cdk/package.json` is not bumped. `CATALOG_VERSION` is not bumped (RUL-14).
- **Commits:** one per task, message `<type>(<scope>): <한국어 요약>` with type ∈ feat/fix/test/docs, run from `/home/ec2-user/my-project/model-monitoring`. **No `git push`, no PR, no tag anywhere in this plan** — release is handled separately.
- **Never touch** `ParityPanel.tsx`, `backend/parity/*`, `i18n.ts`, CDK.

---

## Task map

| Task | Bundle / original | Candidates, critic ids, rulings | Files |
|------|-------------------|---------------------------------|-------|
| 1 | backend T1 | R6 (precondition), D8 classification invariance | `backend/tests/test_claude_features.py` |
| 2 | backend T2 | R6, D8(b) | `backend/claude_features/transports.py`, tests |
| 3 | backend T3 | R1, critic 4-B, D8(a), RUL-13 | `backend/claude_features/transports.py`, `backend/claude_features/probes.py`, `backend/CLAUDE.md`, tests |
| 4 | backend T4 | R7, R10, D8(c)(d), RUL-12 | `backend/claude_features/probes.py`, tests |
| 5 | backend T5 | R5 backend (§3 corrected mechanism), critic 4-A backend side, D3-backend, RUL-11 | `backend/claude_features/engine.py`, `backend/routers/features.py`, `backend/routers/CLAUDE.md`, tests |
| 6 | frontend-A T1 | C9, R2 (+C2 merged), critic 4-C, D1, RUL-2, RUL-5, RUL-7 | `frontend/src/lib/claudeFeatures.ts`, `frontend/src/lib/claudeFeatures.test.ts` |
| 7 | frontend-A T2 | C9, R2, critic 4-C, D1, RUL-5 | `frontend/src/components/ClaudeFeaturesPanel.tsx` |
| 8 | frontend-A T3 | C3, C10 (+R8 merged), D2, RUL-6 | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx` |
| 9 | frontend-A T4 | C5, R5 frontend, critic 4-A, D3-frontend, RUL-1, RUL-4 | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx` |
| 10 | frontend-A T5 | C7-a, C7 expand/collapse-all, D7, RUL-8 | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx` |
| 11 | frontend-B T1 | C1, R3, D4, RUL-7 | `claudeFeatures.ts`, test |
| 12 | frontend-B T2 | C1, R3, critic 4-E (drawer subtitle), D4, RUL-6, RUL-9 | `ClaudeFeaturesPanel.tsx` |
| 13 | frontend-B T3 | C4, critic 4-C, D5, RUL-8 | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx` |
| 14 | frontend-B T4 | C8, R4, critic 4-E (mono model_id), D6, RUL-10 | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx` |
| 15 | frontend-B T5 | C11, R11 §2-b residue, critic 4-D, critic 4-E ("지연시간") | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx`, `backend/claude_features/catalog.py`, backend tests |
| 16 | final | R12, critic 4-F, D9, D10, RUL-3, RUL-14, RUL-15 | `docs/api-reference.md`, `docs/decisions/ADR-026-*.md`, `CLAUDE.md`, `frontend/src/components/CLAUDE.md`, `frontend/src/lib/version.ts`, `frontend/package.json`, `backend/main.py`, `README.md`, `CHANGELOG.md` |
| 17 (optional) | — (critic §6 demoted C6; verify-C6 §3b verdict-axis adaptation) | C6 | `claudeFeatures.ts`, test, `ClaudeFeaturesPanel.tsx`, `CHANGELOG.md`, `frontend/src/components/CLAUDE.md` |

Not implemented (deliberately, per critic §6): C7-b default-collapse (39 rows are manageable), R9 (rejected — features `classify` coverage already exceeds parity's), R11 as a structural desc rewrite (only its residue lands in Task 15). C6 (group-summary mini bars) is demoted to **optional Task 17** after the release task — low value per critic §6 (35 mini bars are dense; cell badges already show `x/probed`), and it must use the verdict axis, not parity's status axis (verify-C6 §3b).

## Pre-flight (once, before Task 1)

```bash
cd /home/ec2-user/my-project/model-monitoring && git status --short && git log --oneline -1
# expect: HEAD a048028 on feat/features-detail-parity; the only untracked paths are the pre-existing tests/20260810_SB/
#         and this plan file docs/superpowers/plans/2026-09-07-claude-features-detail-parity.md (leave it untracked or
#         commit it on its own — it is NOT part of any task's `git add` list)
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run 2>&1 | tail -4 && npx tsc --noEmit -p . && echo TSC-OK
# expect: Tests 50 passed (50), TSC-OK
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q 2>&1 | tail -1 && ruff check claude_features tests/test_claude_features.py
# expect: 69 passed, All checks passed!
```

---

### Task 1: `engine.classify` 회귀 핀 — 라이브 오류 문자열 24건 + D8(b) 형식 쌍 14건

**Implements:** verify-R6.md §3·§5 (precondition for Task 2), D8 classification-invariance requirement. Bundle backend T1.

D8(b)가 오류 문자열에 AWS operation 이름과 빈 본문 라우트 표기를 덧붙인다. `classify`는 소문자 부분 문자열 매칭(`claude_features/engine.py:34-40` → `parity/engine.py:42-49`)이므로 새 문구에 마커가 끼면 판정이 뒤집힌다. 이 Task는 **현재 판정을 고정**하고, D8(b) 이후 형식이 현재 형식과 같은 판정임을 미리 못 박는다.

**Files:**
- Test: `/home/ec2-user/my-project/model-monitoring/backend/tests/test_claude_features.py` — 파일 끝(:754 뒤)에 append
- Modify: 없음

**Interfaces:**
- Consumes: `claude_features.engine.classify(error_message: str | None) -> str` (변경 없음)
- Produces: 없음 (테스트만)

- [ ] **Step 1: 핀 테스트 작성**

`backend/tests/test_claude_features.py` 끝에 다음을 append한다. 문자열은 라이브 run #3 증거(`scratchpad/parity-ref/samples/**`, `unsupported-shapes.txt`)와 `transports.py`가 만드는 형식 그대로다.

```python


# ==================================================================== v2.24.0 — Task 1: engine.classify 회귀 핀 (D8(b) 전제)
# 라이브 run #3(2026-09-06) 증거·parity-ref 샘플에서 뽑은 대표 오류 문자열. classify는 소문자 부분 문자열 매칭이므로
# D8(b)가 오류 문자열에 AWS operation 이름·빈 본문 표기를 덧붙일 때 새 문구에 마커("not found", "no route" 등)가
# 끼어들면 broken→unsupported로 뒤집힌다 — 이 핀이 그 회귀를 막는다.
_CLASSIFY_PINS = [
    # (id, 오류 문자열 그대로, 기대 판정)
    ("bedrock-count-tokens", "HTTP 400: ValidationException: The provided model doesn't support counting tokens.", "unsupported"),
    ("invoke-structured-extra-inputs", "HTTP 400: ValidationException: output_config.format: Extra inputs are not permitted", "unsupported"),
    ("mantle-data-retention", 'HTTP 400: {"type": "error", "request_id": "req_37kb", "error": {"type": "invalid_request_error", '
                              '"message": "data retention mode \'default\' is not available for this model"}}', "unsupported"),
    ("mantle-beta-header", 'HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
                           '"message": "Unexpected value(s) `fallback-credit-2026-07-01` for the `anthropic-beta` header"}}', "unsupported"),
    ("invoke-tool-type", "HTTP 400: ValidationException: tool type 'advisor_20260301' is not supported for this model", "unsupported"),
    ("cp-strict-extra-inputs", 'HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
                               '"message": "tools.0.custom.strict: Extra inputs are not permitted"}}', "unsupported"),
    ("cp-fallbacks-param", 'HTTP 400: {"type": "error", "error": {"type": "invalid_request_error", '
                           '"message": "\'claude-sonnet-5\' does not support the `fallbacks` parameter."}, "request_id": "req_011Ce"}', "unsupported"),
    ("mantle-empty-404", "HTTP 404: ", "unsupported"),
    ("coral-unknown-operation", "HTTP 404: UnknownOperationException: route not available on this endpoint", "unsupported"),
    ("bedrock-messages-403-as-404", 'HTTP 404: route not served by the Anthropic-compatible handler (403 {"Message": "Authorization header is missing"})',
     "unsupported"),
    ("no-route-gate", "no route: bedrock_invoke has no HTTP endpoint for /v1/messages/batches", "unsupported"),
    ("thinking-enabled-rejected", 'HTTP 400: ValidationException: "thinking.type.enabled" is not supported for this model. '
                                  'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.', "unsupported"),
    ("mantle-model-does-not-exist", 'HTTP 404: {"type": "error", "error": {"type": "not_found_error", '
                                    '"message": "The model \'anthropic.claude-fable-5-1\' does not exist or you do not have access to it."}}', "unsupported"),
    ("with-fallback-tail", "HTTP 400: ValidationException: tools.0: Input tag 'computer_toolset_20260801' found using 'type' does not match "
                           "any of the expected tags: 'bash_20250124' | attempts=[{\"attempt\": \"computer_toolset_20260801\", \"result\": \"HTTP 400\"}]",
     "unsupported"),
    ("bedrock-request-not-valid", "HTTP 400: ValidationException: request is not valid", "unsupported"),
    ("bedrock-messages-403-auth", 'HTTP 403: {"Message": "Authorization header is missing"}', "broken"),
    ("empty-400", "HTTP 400: ", "broken"),
    ("rate-limit-429", 'HTTP 429: {"type": "error", "error": {"type": "rate_limit_error", "message": "Too many requests"}}', "broken"),
    ("api-error-500", 'HTTP 500: {"type":"error","error":{"type":"api_error","message":"Internal server error"}}', "broken"),
    ("access-denied", "HTTP 403: AccessDeniedException: User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock:InvokeModel",
     "broken"),
    ("effort-unknown-variant", "HTTP 400: ValidationException: unknown variant `ultra`, expected one of `low`, `medium`, `high`, `xhigh`, "
                               "`max`, `Unhandled` at line 1 column 125", "broken"),
    ("read-timeout", "ReadTimeout: HTTPSConnectionPool(host='aws-external-anthropic.us-east-2.api.aws', port=443): Read timed out.", "broken"),
    ("connect-error", "ConnectError: [Errno 111] Connection refused", "broken"),
    ("transport-init", "transport init: KeyError: 'ANTHROPIC_API_KEY'", "broken"),
]


@pytest.mark.parametrize("msg,expected", [(m, e) for _, m, e in _CLASSIFY_PINS], ids=[i for i, _, _ in _CLASSIFY_PINS])
def test_classify_pins_live_error_strings(msg, expected):
    assert engine.classify(msg) == expected


# D8(b) 이후 형식 ↔ 현재 형식 — 같은 판정이어야 한다 (operation 괄호 표기, "(empty body) METHOD path")
_CLASSIFY_FORMAT_PAIRS = [
    # (현재 형식, D8(b) 형식, 기대 판정)
    ("HTTP 400: ValidationException: The provided model doesn't support counting tokens.",
     "HTTP 400: ValidationException (CountTokens): The provided model doesn't support counting tokens.", "unsupported"),
    ("HTTP 400: ValidationException: output_config.format: Extra inputs are not permitted",
     "HTTP 400: ValidationException (InvokeModel): output_config.format: Extra inputs are not permitted", "unsupported"),
    ('HTTP 400: ValidationException: "thinking.type.enabled" is not supported for this model.',
     'HTTP 400: ValidationException (Converse): "thinking.type.enabled" is not supported for this model.', "unsupported"),
    ("HTTP 400: ValidationException: request is not valid",
     "HTTP 400: ValidationException (InvokeModelWithResponseStream): request is not valid", "unsupported"),
    ("HTTP 403: AccessDeniedException: User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock:InvokeModel",
     "HTTP 403: AccessDeniedException (InvokeModel): User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock:InvokeModel",
     "broken"),
    ("HTTP 429: ThrottlingException: Too many requests, please wait before trying again.",
     "HTTP 429: ThrottlingException (Converse): Too many requests, please wait before trying again.", "broken"),
    ("HTTP 404: ", "HTTP 404: (empty body) GET /v1/files", "unsupported"),
    ("HTTP 404: ", "HTTP 404: (empty body) POST /v1/messages/batches", "unsupported"),
    ("HTTP 404: ", "HTTP 404: (empty body) GET /v1/models/anthropic.claude-fable-5", "unsupported"),
    ("HTTP 405: ", "HTTP 405: (empty body) DELETE /v1/files/file_01", "unsupported"),
    ("HTTP 400: ", "HTTP 400: (empty body) POST /v1/messages", "broken"),
    ("HTTP 400: ", "HTTP 400: (empty body) POST /v1/messages (stream)", "broken"),
    ("HTTP 403: ", "HTTP 403: (empty body) GET /v1/models/anthropic.claude-fable-5", "broken"),
    ("HTTP 500: ", "HTTP 500: (empty body) POST /v1/messages", "broken"),
]


@pytest.mark.parametrize("before,after,expected", _CLASSIFY_FORMAT_PAIRS)
def test_classify_unchanged_by_d8b_error_context(before, after, expected):
    assert engine.classify(before) == expected
    assert engine.classify(after) == expected
```

- [ ] **Step 2: 실행 — 핀은 의도적으로 red 단계가 없다**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q -k "classify_pins or unchanged_by_d8b"
```
기대: `38 passed, 69 deselected`. (핀 테스트는 현 동작을 고정하는 것이 목적이므로 첫 실행부터 초록이다. red가 되는 순간은 Task 2가 마커에 걸리는 문구를 만들었을 때 — 그때 이 테스트가 잡는다.) 참고로 `bedrock-request-not-valid`는 parity 마커 `"request is not valid"`(`parity/engine.py:31`) 때문에 unsupported로 고정된다 — 현 동작 그대로.

- [ ] **Step 3: 전체 파일 + ruff**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q && ruff check claude_features tests/test_claude_features.py
```
기대: `107 passed`, `All checks passed!`.

- [ ] **Step 4: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add backend/tests/test_claude_features.py && git commit -m "test(features): engine.classify 회귀 핀 — 라이브 오류 문자열 24건 + D8(b) 문맥 추가 전후 동일 판정 14쌍"
```

---

### Task 2: D8(b) 오류 문맥 — boto operation 이름 + 본문 없는 4xx/5xx 라우트 표기 (R6)

**Implements:** verify-R6.md §2-a, §2-b, §4-4; D8(b). Bundle backend T2.

`_client_error`(`transports.py:308-313`)는 `err["Message"]`만 쓰므로 botocore가 `str(exc)`와 `.operation_name`에만 담는 operation 이름이 탈락한다(botocore 1.43.43 `ClientError.__init__` 확인). 본문 없는 4xx는 `parsed = ""` → `TransportError(404, "")` → `"HTTP 404: "`(`:189-200`; 라이브 Mantle files/batches/models 전부 이 문구). 스트림 경로(`:213-214`)도 동일.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/claude_features/transports.py` — `_client_error` (:308-313), `_HttpTransport.request` 4xx 분기 (:198-200), `_HttpTransport.messages` 스트림 4xx (:213-214)
- Test: `/home/ec2-user/my-project/model-monitoring/backend/tests/test_claude_features.py` — 파일 끝에 append (기존 `test_client_error_maps_botocore_shape` :190-199는 수정 없이 통과해야 함)

**Interfaces:**
- Consumes: botocore `ClientError.operation_name: str` (있을 때만), `httpx.Response.content/status_code`
- Produces: `TransportError.message` 형식 3종 —
  - boto: `f"{code} ({operation}): {msg}"` (operation 없으면 종전 `f"{code}: {msg}"`)
  - HTTP 본문 없음: `f"(empty body) {method} {path}"` → `str(exc) == "HTTP 404: (empty body) GET /v1/files"`
  - 스트림 본문 없음: `"(empty body) POST /v1/messages (stream)"`
- 불변: `TransportError(status_code: int | None, message: str)` 시그니처, `engine.classify` 판정(Task 1 핀)

- [ ] **Step 1: 실패 테스트 작성** — 파일 끝에 append

```python


# ==================================================================== v2.24.0 — Task 2: D8(b) 오류 문맥

def test_client_error_keeps_boto_operation_name():
    """boto ClientError는 operation 이름을 str(exc)와 .operation_name에만 담는다 — Error.Message만 쓰면 탈락 (R6).

    라이브 run #3: `bedrock_invoke/token_counting`과 `bedrock_converse/token_counting`이 같은 문구라 CountTokens에서
    난 것인지 문자열만으로 구분 불가였다 (parity 샘플은 "CountTokens operation" 명시).
    """
    class E(Exception):
        response = {"Error": {"Code": "ValidationException", "Message": "The provided model doesn't support counting tokens."},
                    "ResponseMetadata": {"HTTPStatusCode": 400}}
        operation_name = "CountTokens"
    err = T._client_error(E("x"))
    assert str(err) == "HTTP 400: ValidationException (CountTokens): The provided model doesn't support counting tokens."
    assert err.status_code == 400
    assert engine.classify(str(err)) == "unsupported"

    class NoOp(Exception):
        response = {"Error": {"Code": "ThrottlingException", "Message": "slow down"}, "ResponseMetadata": {"HTTPStatusCode": 429}}
        operation_name = None
    assert str(T._client_error(NoOp("x"))) == "HTTP 429: ThrottlingException: slow down"


def test_http_empty_error_body_names_method_and_path(monkeypatch):
    """본문 없는 4xx는 'HTTP 404: '로 끝나 어느 라우트였는지 알 수 없었다 (라이브 run #3 Mantle files/batches/models) (R6)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()

    class _R:
        status_code = 404
        content = b""
        def json(self):
            raise ValueError("no body")

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError) as exc:
        t.request("GET", "/v1/files")
    assert str(exc.value) == "HTTP 404: (empty body) GET /v1/files"
    assert engine.classify(str(exc.value)) == "unsupported"  # 'http 404' 마커 유지

    _R.status_code = 500
    with pytest.raises(T.TransportError) as exc5:
        t.request("POST", "/v1/messages", json={"model": "m"})
    assert str(exc5.value) == "HTTP 500: (empty body) POST /v1/messages"
    assert engine.classify(str(exc5.value)) == "broken"


def test_http_stream_empty_error_body_is_labelled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    t = T.CpTransport()
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(404, b"")))
    with pytest.raises(T.TransportError) as ei:
        t.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert str(ei.value) == "HTTP 404: (empty body) POST /v1/messages (stream)"
    # 본문이 있으면 그대로 (회귀 방지)
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(400, b'{"type":"error","error":{"message":"nope"}}')))
    with pytest.raises(T.TransportError) as ei2:
        t.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert str(ei2.value) == 'HTTP 400: {"type":"error","error":{"message":"nope"}}'
```

- [ ] **Step 2: 실행 → 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q -k "keeps_boto_operation or empty_error_body"
```
기대: `3 failed` —
- `AssertionError: assert 'HTTP 400: Va...nting tokens.' == ...` (`- HTTP 400: ValidationException (CountTokens): ...` / `+ HTTP 400: ValidationException: ...`)
- `AssertionError: assert 'HTTP 404: ' == 'HTTP 404: (e...GET /v1/files'`
- `AssertionError: assert 'HTTP 404: ' == 'HTTP 404: (e...ages (stream)'`

- [ ] **Step 3: 구현** — `backend/claude_features/transports.py` 세 곳

(1) `_client_error` (:308-313) — 마지막 두 줄(`code, msg = …` / `return TransportError(status, f"{code}: {msg}")`)을 교체:

```python
    code, msg = err.get("Code", type(exc).__name__), err.get("Message", str(exc))
    # botocore.ClientError는 operation 이름을 str(exc)와 .operation_name에만 담고 Error.Message에는 없다.
    # 같은 문구("doesn't support counting tokens")가 CountTokens인지 InvokeModel인지 증거만으로 구분하려면 남겨야 한다.
    # 괄호 표기는 engine.classify 마커에 걸리지 않는다 (tests: test_classify_unchanged_by_d8b_error_context).
    op = getattr(exc, "operation_name", None)
    return TransportError(status, f"{code} ({op}): {msg}" if op else f"{code}: {msg}")
```

(2) `_HttpTransport.request` (:198-200) — `if r.status_code >= 400:` 블록:

```python
        if r.status_code >= 400:
            msg = parsed if isinstance(parsed, str) else _json.dumps(parsed, ensure_ascii=False)[:1500]
            if not msg.strip():
                # 본문 없는 4xx/5xx — 어느 라우트였는지 오류 문자열에 남긴다 (라이브 run #3: Mantle files/batches/models가
                # 전부 "HTTP 404: "). 문구는 판정 마커("not found", "no route" 등)를 포함하지 않는 중립 표현이어야 한다.
                msg = f"(empty body) {method} {path}"
            raise TransportError(r.status_code, msg)
        return r.status_code, parsed
```

(3) `_HttpTransport.messages` 스트림 경로 (:212-214) — `raise TransportError(r.status_code, text[:1500])` 한 줄을 교체:

```python
            text = r.read().decode("utf-8", "replace")
            if r.status_code >= 400:
                msg = text[:1500]
                if not msg.strip():
                    msg = "(empty body) POST /v1/messages (stream)"
                raise TransportError(r.status_code, msg)
```

`BedrockMessagesTransport.request`(:283-298)의 403→404 래퍼는 `"authorization header is missing" in exc.message`를 요구하므로 빈 본문 403은 종전처럼 403(broken)으로 남는다 — 변경 불필요.

- [ ] **Step 4: 실행 → 전부 초록 + 핀 유지**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q && ruff check claude_features tests/test_claude_features.py
```
기대: `110 passed` (Task 1 핀 38건 포함), `All checks passed!`. 기존 `test_client_error_maps_botocore_shape`(:190-199)는 `E`에 `operation_name`이 없어 종전 형식이 유지되므로 무수정 통과.

- [ ] **Step 5: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add backend/claude_features/transports.py backend/tests/test_claude_features.py && git commit -m "fix(features): 오류 문자열에 boto operation 이름과 빈 본문 라우트 표기 추가 — engine.classify 판정 불변 (R6)"
```

---

### Task 3: D8(a) 실패 경로 요청 스냅샷 — 전송기 스레드 로컬 `record_request`/`last_request` + `run_probe` 회수 (R1, critic 4-B)

**Implements:** verify-R1.md §3·§5, critic §4-B (success-path `setdefault` also uses the transport snapshot), D8(a), RUL-13 (boto-path snapshots record the native body). Bundle backend T3.

`run_probe`(`probes.py:136-157`)는 성공 반환에서만 프로브가 만든 `request`를 받고, `except TransportError`(:150-153)·`except Exception`(:154-157)은 `{"request": _req(model_id)}` = `{"model": …}`만 남긴다. 라이브 run #3 unsupported 206셀 중 **182셀(드리프트 25건 전부)**이 이 경로다(verify-R1 §3). parity `_run(fn, request)`(`parity/probes.py:75-91`)는 호출 전에 스냅샷을 받아 :90에서 보존한다. 전송기는 surface당 1개를 `ThreadPoolExecutor(4)`(`runner.py:24, :48-56, :70`)의 스레드가 공유하므로 인스턴스 속성이 아닌 `threading.local`을 쓴다(verify-R1 §5). 성공 경로 `setdefault`(:141)도 전송기 스냅샷으로 채운다(critic §4-B).

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/claude_features/transports.py` — import (:10-13), `_snippet_bytes` 뒤(:153-155 다음)에 recorder 섹션 신설, 기록 지점 7곳(비스트림 `messages`/`count_tokens`는 `self.request`를 거치므로 (d)가 덮는다): `Transport.request` (:171-172), `_HttpTransport.request` 첫 줄 (:182-183), `_HttpTransport.messages` 스트림 (:209), `BedrockInvokeTransport.messages` (:325-326), `.count_tokens` (:339-340), `BedrockConverseTransport.converse` (:359), `.count_tokens_converse` (:418). (Task 2 이후 :197 아래는 +4, :214 아래는 +7, :313 아래는 +11 밀린다 — 아래 앵커 텍스트로 찾을 것.)
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/claude_features/probes.py` — import (:18), `run_probe` (:136-157)
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/CLAUDE.md` — `claude_features/` 한 줄 (:24) `transports.py` 설명 보강
- Test: `/home/ec2-user/my-project/model-monitoring/backend/tests/test_claude_features.py` — 파일 끝에 append. 기존 `test_run_probe_classifies_transport_error`(:430-435)는 `_FakeT`(:413-427)가 recorder를 부르지 않으므로 종전 `{"model"}` 폴백으로 통과.

**Interfaces:**
- Produces (`claude_features.transports`):
  - `record_request(snapshot: dict) -> None` — 이 스레드의 마지막 요청 스냅샷 기록(절단 없음)
  - `last_request() -> dict | None`
  - `clear_last_request() -> None`
  - `_http_snapshot(method: str, path: str, json: Any, betas, files, data) -> dict` — `{"api": "METHOD path", **json_body, "anthropic_beta"?: list[str], "files"?: Any, "data"?: Any}` (dict가 아닌 json은 `"json"` 키)
  - boto 경로 스냅샷 형태: `{"api": "InvokeModel" | "InvokeModelWithResponseStream" | "CountTokens" | "Converse" | "ConverseStream", "model": model_id, **native_or_kw}` — InvokeModel은 `invoke_body()`가 만든 **native 본문**(anthropic_version, anthropic_beta 리스트 포함) 그대로. 성공 경로 `_req(model_id, kw)`(Anthropic 스키마)와 형태가 조금 다르다 — "실제로 보낸 것"을 남기는 것이 목적이므로 허용 (RUL-13, 코드 주석으로 명시).
- Produces (`claude_features.probes.run_probe`): 실패 행 `evidence.request == _req(model_id, last_request())` = `{"model": model_id, **_trim(snapshot)}`; recorder 미호출 전송기면 종전 `{"model": model_id}`
- Consumes: `probes._req(model_id: str, body: dict | None = None, betas=(), **extra) -> dict` (:87-94, 변경 없음 — `body=None`이면 `{"model"}`만), `probes._trim` (:75-84, bytes → `"<N bytes>"`, 200자 절단)
- 불변: `Transport`/`_HttpTransport` 공개 메서드 시그니처, `engine.classify`, `FeatureResult` 스키마

- [ ] **Step 1: 실패 테스트 작성 (+ 회귀 가드 1건)** — 파일 끝에 append. `test_run_probe_without_recorder_falls_back_to_model_only`는 Task 1 핀과 같은 성격의 **회귀 가드**라 구현 전에도 통과한다(Step 2의 `1 passed`).

```python


# ==================================================================== v2.24.0 — Task 3: D8(a) 실패 경로 요청 스냅샷

class _RecordingT(_FakeT):
    """실제 전송기처럼 호출 직전에 record_request를 부른다 — 실패 경로 스냅샷 회수 검증용."""

    def messages(self, model_id, body, betas=(), stream=False):
        payload = {**body, "model": model_id}
        if stream:
            payload["stream"] = True
        T.record_request(T._http_snapshot("POST", "/v1/messages", payload, betas, None, None))
        return super().messages(model_id, body, betas, stream)


def test_run_probe_transport_error_keeps_full_request_snapshot():
    """실패 셀도 요청 본문을 남긴다 — 라이브 run #3 unsupported 206셀 중 182셀(드리프트 25건 전부)이 {"model"}만 남겼다 (R1)."""
    t = _RecordingT(exc=T.TransportError(400, "data retention mode 'default' is not available for this model"))
    out = P.run_probe(P.PROBES["tool_use"], t, "claude-opus-5", "opus-5")
    assert out.status == "unsupported" and out.error.startswith("HTTP 400")
    req = out.evidence["request"]
    assert req["model"] == "claude-opus-5" and req["api"] == "POST /v1/messages"
    assert req["max_tokens"] == P._TOOL_MAX and req["messages"][0]["role"] == "user"
    assert req["tools"][0]["name"] == "echo" and req["tool_choice"] == {"type": "tool", "name": "echo"}


def test_run_probe_generic_exception_keeps_request_snapshot():
    t = _RecordingT(exc=RuntimeError("socket closed"))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.status == "broken" and out.error.startswith("RuntimeError: socket closed")
    assert out.evidence["request"]["api"] == "POST /v1/messages" and out.evidence["request"]["max_tokens"] == P._MAX


def test_run_probe_with_fallback_failure_records_last_attempt():
    """_with_fallback 최종 실패는 마지막 시도 본문이 남는다 (라이브 computer_use/mantle/fable-5는 attempts 문자열만 있었다)."""
    t = _RecordingT(exc=T.TransportError(400, "tools.0: Input tag 'x' found using 'type' does not match any of the expected tags"))
    out = P.run_probe(P.PROBES["computer_use"], t, "claude-opus-5", "opus-5")
    assert out.status == "unsupported" and "attempts=" in out.error
    assert out.evidence["request"]["tools"][0]["type"] == "computer_20251124"
    assert out.evidence["request"]["anthropic_beta"] == ["computer-use-2025-11-24"]
    assert len(t.calls) == 2


def test_run_probe_without_recorder_falls_back_to_model_only():
    """회귀 가드 — 구현 전에도 통과해야 한다. record_request를 부르지 않는 전송기(구형/가짜)는 종전처럼 {"model"}만 남긴다 — 하위 호환."""
    t = _FakeT(exc=T.TransportError(400, "thinking.type.enabled is not supported for this model"))
    out = P.run_probe(P.PROBES["messages_basic"], t, "claude-opus-5", "opus-5")
    assert out.evidence["request"] == {"model": "claude-opus-5"}


def test_run_probe_clears_stale_snapshot_from_previous_probe():
    """같은 워커 스레드의 직전 프로브 스냅샷이 호출 없는 프로브(route gate)에 새지 않아야 한다."""
    T.record_request({"api": "POST /v1/messages", "model": "stale", "messages": ["stale"]})
    t = _FakeT()
    t.surface, t.routes = "bedrock_invoke", frozenset({"messages", "count_tokens"})
    out = P.run_probe(P.PROBES["batch_processing"], t, "global.anthropic.claude-opus-5", "opus-5")
    assert out.status == "unsupported"
    assert out.evidence["request"] == {"model": "global.anthropic.claude-opus-5"}


def test_run_probe_success_setdefault_uses_transport_snapshot():
    """프로브가 request를 빠뜨려도 전송기 스냅샷으로 채운다 (critic 4-B, parity `_run` :81-82 동형)."""
    t = _RecordingT(resp=T.NormalizedResponse(content=[{"type": "text", "text": "pong"}]))

    def forgetful(t_, m, k):
        return bool(t_.messages(m, {"max_tokens": 4, "messages": []}).content), {}

    out = P.run_probe(forgetful, t, "claude-opus-5", "opus-5")
    assert out.status == "supported"
    assert out.evidence["request"] == {"model": "claude-opus-5", "api": "POST /v1/messages", "max_tokens": 4, "messages": []}


def test_last_request_is_thread_local():
    from concurrent.futures import ThreadPoolExecutor
    import time as _time

    def work(i):
        T.record_request({"model": f"m{i}"})
        _time.sleep(0.01)
        return T.last_request()["model"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(work, range(8))) == [f"m{i}" for i in range(8)]
    T.clear_last_request()
    assert T.last_request() is None


def test_transports_record_request_before_calling(monkeypatch):
    """모든 전송 경로가 호출 직전 record_request를 부른다 — InvokeModel/CountTokens/Converse/HTTP/no-route."""
    class _Down:
        def invoke_model(self, modelId, body):
            raise RuntimeError("down")
        def count_tokens(self, modelId, input):
            raise RuntimeError("down")
        def converse(self, modelId, **kw):
            raise RuntimeError("down")

    monkeypatch.setattr(T, "_boto_client", lambda region: _Down())
    inv = T.BedrockInvokeTransport(region="ap-northeast-2")
    with pytest.raises(RuntimeError):
        inv.messages("global.anthropic.claude-opus-5", {"max_tokens": 8, "messages": []}, betas=["b1"])
    rec = T.last_request()
    assert rec["api"] == "InvokeModel" and rec["model"] == "global.anthropic.claude-opus-5"
    assert rec["anthropic_version"] == "bedrock-2023-05-31" and rec["anthropic_beta"] == ["b1"] and rec["max_tokens"] == 8
    with pytest.raises(RuntimeError):
        inv.count_tokens("global.anthropic.claude-opus-5", {"max_tokens": 8, "messages": []})
    assert T.last_request()["api"] == "CountTokens" and "max_tokens" not in T.last_request()

    conv = T.BedrockConverseTransport(region="ap-northeast-2")
    with pytest.raises(RuntimeError):
        conv.converse("global.anthropic.claude-opus-5", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    assert T.last_request() == {"api": "Converse", "model": "global.anthropic.claude-opus-5",
                                "messages": [{"role": "user", "content": [{"text": "hi"}]}]}
    with pytest.raises(RuntimeError):
        conv.count_tokens_converse("global.anthropic.claude-opus-5", messages=[])
    assert T.last_request() == {"api": "CountTokens", "model": "global.anthropic.claude-opus-5", "messages": []}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "w")
    cp = T.CpTransport()

    class _R:
        status_code = 404
        content = b"{}"
        def json(self):
            return {"type": "error"}

    class _C:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **kw):
            return _R()

    monkeypatch.setattr(T.httpx, "Client", _C)
    with pytest.raises(T.TransportError):
        cp.request("POST", "/v1/files", files={"file": ("a.txt", b"x", "text/plain")})
    assert T.last_request()["api"] == "POST /v1/files" and T.last_request()["files"]["file"][0] == "a.txt"
    with pytest.raises(T.TransportError):
        cp.count_tokens("claude-opus-5", {"max_tokens": 8, "messages": []}, betas=["b2"])
    assert T.last_request() == {"api": "POST /v1/messages/count_tokens", "messages": [], "model": "claude-opus-5", "anthropic_beta": ["b2"]}
    monkeypatch.setattr(T.httpx, "Client", _fake_httpx_client(_FakeHttpStream(400, b'{"type":"error"}')))
    with pytest.raises(T.TransportError):
        cp.messages("claude-opus-5", {"max_tokens": 8, "messages": []}, stream=True)
    assert T.last_request()["stream"] is True and T.last_request()["api"] == "POST /v1/messages"

    # 라우트 없는 전송기의 base request()도 기록한다
    with pytest.raises(T.TransportError):
        T.Transport().request("GET", "/v1/models/x")
    assert T.last_request() == {"api": "GET /v1/models/x"}
```

- [ ] **Step 2: 실행 → 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q -k "keeps_full_request or generic_exception_keeps or with_fallback_failure_records or falls_back_to_model_only or clears_stale or success_setdefault or thread_local or record_request_before"
```
기대: `7 failed, 1 passed`(`falls_back_to_model_only`만 통과). 실패 문구: `AttributeError: module 'claude_features.transports' has no attribute 'record_request'` — `_RecordingT`가 recorder를 못 찾아 `run_probe`가 `broken`을 돌려 `assert 'broken' == 'unsupported'`로 실패.

- [ ] **Step 3: 구현 (1/3)** — `backend/claude_features/transports.py`

(a) import (:10-13):
```python
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any
```

(b) `_snippet_bytes`(:153-155) 바로 뒤, `# ---- base` 주석 앞에 신설:
```python


# ---------------------------------------------------------------- last-request recorder (v2.24.0)
# 전송기는 surface당 1개를 4개 워커 스레드가 공유하므로 인스턴스 속성은 쓸 수 없고, 프로브 1건은 한 스레드에서
# 끝나므로 threading.local이 맞다. 모든 호출 경로가 호출 *직전에* record_request()를 부르고, run_probe가
# 실패 경로에서 last_request()로 회수한다 (parity `_run(fn, request)`가 호출 전에 스냅샷을 받는 것과 동형).

_tls = threading.local()


def record_request(snapshot: dict) -> None:
    """이 스레드가 마지막으로 보낸 요청 스냅샷을 기록한다. 절단(_trim)은 회수 측(probes._req)이 한다."""
    _tls.last_request = snapshot


def last_request() -> dict | None:
    return getattr(_tls, "last_request", None)


def clear_last_request() -> None:
    _tls.last_request = None


def _http_snapshot(method: str, path: str, json: Any, betas, files, data) -> dict:
    """HTTP 호출 1건의 스냅샷 — `api`(METHOD path) + JSON 본문 평탄화 + anthropic_beta/files/data."""
    snap: dict = {"api": f"{method} {path}"}
    if isinstance(json, dict):
        snap.update(json)
    elif json is not None:
        snap["json"] = json
    betas = [b for b in (betas or []) if b]
    if betas:
        snap["anthropic_beta"] = betas
    if files is not None:
        snap["files"] = files
    if data is not None:
        snap["data"] = data
    return snap
```

(c) `Transport.request` (:171-172) — raise 앞에 한 줄:
```python
    def request(self, method: str, path: str, json: Any = None, betas=(), files=None, data=None) -> tuple[int, Any]:
        record_request(_http_snapshot(method, path, json, betas, files, data))
        raise TransportError(None, f"no route: {self.surface} has no HTTP endpoint for {path}")
```

(d) `_HttpTransport.request` (:182-183) — 첫 문장 앞에 한 줄:
```python
    def request(self, method: str, path: str, json: Any = None, betas=(), files=None, data=None) -> tuple[int, Any]:
        record_request(_http_snapshot(method, path, json, betas, files, data))
        headers = self._headers(betas)
```
(비스트림 `messages`/`count_tokens`는 `self.request`를 거치므로 여기서 함께 기록된다.)

(e) `_HttpTransport.messages` 스트림 경로 (:209) — `payload["stream"] = True` 다음 줄:
```python
        payload["stream"] = True
        record_request(_http_snapshot("POST", "/v1/messages", payload, betas, None, None))
        with httpx.Client(timeout=_TIMEOUT) as c, c.stream("POST", self.base_url + "/v1/messages",
```

(f) `BedrockInvokeTransport.messages` (:325-326) — `native = …` 다음 줄 (RUL-13 주석 포함):
```python
        native = invoke_body(body, betas)
        # 실패 스냅샷은 *native* InvokeModel 본문(anthropic_version + anthropic_beta 리스트, model 추가)을 남긴다 —
        # 성공 경로의 _req(model_id, kw)(Anthropic 스키마)와 형태가 조금 다르지만 "실제로 보낸 것"이 진실이다 (RUL-13).
        record_request({"api": "InvokeModelWithResponseStream" if stream else "InvokeModel", "model": model_id, **native})
        try:
```

(g) `BedrockInvokeTransport.count_tokens` (:339-340):
```python
        native = invoke_body({k: v for k, v in body.items() if k != "max_tokens"}, betas)
        record_request({"api": "CountTokens", "model": model_id, **native})
        try:
```

(h) `BedrockConverseTransport.converse` (:359) — 첫 문장 (kw는 Converse native 인자 그대로 — RUL-13):
```python
    def converse(self, model_id: str, stream: bool = False, **kw) -> NormalizedResponse:
        record_request({"api": "ConverseStream" if stream else "Converse", "model": model_id, **kw})
        try:
```

(i) `BedrockConverseTransport.count_tokens_converse` (:418):
```python
    def count_tokens_converse(self, model_id: str, **kw) -> dict:
        record_request({"api": "CountTokens", "model": model_id, **kw})
        try:
```

- [ ] **Step 4: 구현 (2/3)** — `backend/claude_features/probes.py`

(a) import (:18):
```python
from claude_features.transports import NormalizedResponse, Transport, TransportError, clear_last_request, last_request
```

(b) `run_probe` (:136-157) 전체를 다음으로 교체:
```python
def run_probe(fn: Callable, t: Transport, model_id: str, model_key: str) -> ProbeOutcome:
    start = time.time()
    clear_last_request()  # 같은 워커 스레드에서 직전 프로브가 남긴 스냅샷이 새지 않도록
    try:
        result, evidence = fn(t, model_id, model_key)
        latency = (time.time() - start) * 1000
        # 프로브가 request를 빠뜨리면 전송기가 마지막으로 보낸 본문으로 채운다 (parity `_run` setdefault 동형)
        evidence.setdefault("request", _req(model_id, last_request()))
        if result is True:
            return ProbeOutcome("supported", latency, evidence)
        if result is False:
            evidence.setdefault("reason", "evidence check failed")
            return ProbeOutcome("broken", latency, evidence)
        if str(result) not in engine.STATUSES:
            return ProbeOutcome("broken", latency, {**evidence, "reason": f"probe returned unknown status {result!r}"})
        return ProbeOutcome(str(result), latency, evidence)
    except TransportError as exc:
        latency = (time.time() - start) * 1000
        msg = str(exc)
        # 실패 셀에도 전송기가 마지막으로 보낸 본문을 남긴다 (없으면 {"model"}만) — 드리프트 셀 트리아지의 전제
        return ProbeOutcome(engine.classify(msg), latency, {"request": _req(model_id, last_request())}, error=msg[:1500])
    except Exception as exc:  # noqa: BLE001 — 네트워크/파싱 오류 전체
        latency = (time.time() - start) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        return ProbeOutcome(engine.classify(msg), latency, {"request": _req(model_id, last_request())}, error=msg[:1500])
```
`_req(model_id, None)`은 `{"model": model_id}`를 돌려주므로(:87-94) recorder를 부르지 않는 전송기(`_FakeT`)에서 종전 동작이 그대로다. `_trim`이 bytes(PDF `source.bytes`)→`"<N bytes>"`, 200자 초과 문자열(CACHE_PAD, base64)→절단을 처리하므로 evidence 크기는 실패 행당 약 +200~600B(verify-R1 §5).

- [ ] **Step 5: 구현 (3/3)** — `backend/CLAUDE.md:24` 문서 한 줄

`transports.py` 설명 `(raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화)`를 다음으로 교체:
```
(raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화; 스레드 로컬 `record_request`/`last_request`로 마지막 요청 본문을 남겨 `run_probe`가 실패 셀 증거에 회수, v2.24.0)
```

- [ ] **Step 6: 실행 → 전부 초록**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q && ruff check claude_features tests/test_claude_features.py
```
기대: `118 passed`, `All checks passed!`. 특히 `test_run_probe_classifies_transport_error`(:430-435), `test_route_less_endpoint_feature_is_unsupported_without_call`(:452-457), `test_bedrock_invoke_messages_and_count_tokens_with_fake_client`(:251-278) 무수정 통과.

- [ ] **Step 7: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add backend/claude_features/transports.py backend/claude_features/probes.py backend/CLAUDE.md backend/tests/test_claude_features.py && git commit -m "feat(features): 실패 셀에도 요청 본문 스냅샷 보존 — 전송기 스레드 로컬 record_request/last_request + run_probe 회수 (R1)"
```

---

### Task 4: D8(c) 요청 스냅샷 메타 키 `api`/`note` 통일 + D8(d) thinking 증거 `usage` 저장 (R7, R10)

**Implements:** verify-R7.md §2 (parity `_req_snapshot` `api=`/`note=` convention), verify-R10.md §2·§3 (thinking usage), D8(c)(d), RUL-12 (stream extras become `api="messages (stream)"` / `api="converse (stream)"`; the transport-recorded failure snapshot from Task 3 still carries the real body param `stream: true`, so no information is lost). Bundle backend T4.

`_req(model_id, body, betas, **extra)`(`probes.py:87-94`)의 `extra`가 `path=`(:226), `endpoint=`(:762, :773, :791), `stream=True`(:178, :182, :613)로 혼용된다 — 라이브 run #3 cp/fable-5-1은 같은 `GET /v1/models/{id}`를 `context_window_1m`은 `path`, `models_api`는 `endpoint`로 표기(verify-R7 §2). parity는 `api=`/`note=` 두 키만 쓴다(`parity/probes.py:139, :204, :226, :507, :538, :612, :619`). 다중 호출 프로브(`_cache_evidence` :704, `probe_effort` :357, `probe_data_residency` :335, `probe_batch_processing` :283, `_with_fallback` :442)는 요청 스냅샷에 방법론이 없다. thinking 프로브(:243-246, :266)는 `usage`를 저장하지 않아 Bedrock Fable 5.1(`thinking_chars=0`, signature만)의 추론량을 숫자로 볼 수 없다(verify-R10 §2, §3).

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/claude_features/probes.py` — 14곳 (Task 3 이후 :136 아래는 +3 밀림; 앵커 텍스트로 찾을 것): `probe_streaming` (:178, :182), `probe_context_window_1m` (:226), `probe_adaptive_thinking` (:243-246), `probe_extended_thinking` (:266), `probe_batch_processing` (:283), `probe_data_residency` (:335), `probe_effort` (:357), `_with_fallback` (:442), `probe_fine_grained_tool_streaming` (:613), `_cache_evidence` (:704), `probe_token_counting` (:762), `probe_files_api` (:773), `probe_models_api` (:791)
- Test: `/home/ec2-user/my-project/model-monitoring/backend/tests/test_claude_features.py` — 파일 끝에 append

**Interfaces:**
- Produces (evidence 계약, `FeatureResult.evidence` JSON):
  - `request.api: str` — 비-Messages 호출·복합 라우트 라벨: `"count_tokens"`, `"messages (stream)"`, `"converse (stream)"`, `f"GET /v1/models/{model_id}"`, `"POST /v1/messages/batches → GET → POST cancel"`, `"POST /v1/files → GET → DELETE"`
  - `request.note: str` — 다중 호출 방법론(영문, 기존 evidence 값 `"rejected: …"`와 일관): `"same request twice; cache judged on 2nd call usage"`, `"2 calls: effort=low, then effort=ultra as negative control"`, `"2 calls: inference_geo=us, then inference_geo=mars as negative control"`, `f"fallback attempt: {label}"`
  - `evidence.usage: dict` — `probe_adaptive_thinking`, `probe_extended_thinking`의 `n.usage` 전체(CP/Mantle/bedrock_messages/bedrock_invoke는 `output_tokens_details.thinking_tokens` 포함; Converse는 `normalize_converse` 4키만)
- 제거: `request.path`, `request.endpoint`, `request.stream`(프로브 측 extra — 전송기 스냅샷의 본문 `stream`은 별개)
- Consumes: `_req(model_id, body=None, betas=(), **extra)` (시그니처 변경 없음)
- 불변: 판정식(`engine.has_thinking_evidence`, `has_block`, `effort_rejection_names_param`), `verdict`, 프론트 raw 렌더(`ClaudeFeaturesPanel.tsx:36-38, :97-98`은 `evidence.request`를 JSON 그대로 그린다)

- [ ] **Step 1: 실패 테스트 작성** — 파일 끝에 append

```python


# ==================================================================== v2.24.0 — Task 4: D8(c) api/note 통일 + D8(d) thinking usage

class _SeqT(_FakeT):
    """호출 순서대로 응답/예외를 내는 전송기 — 2회 호출 프로브(effort, data_residency, _with_fallback) 검증용."""

    def __init__(self, *steps):
        super().__init__()
        self.steps = list(steps)

    def messages(self, model_id, body, betas=(), stream=False):
        self.calls.append(("messages", body, tuple(betas), stream))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _text(text="pong", **kw):
    return T.NormalizedResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", **kw)


def test_request_snapshots_use_api_key_instead_of_path_endpoint_stream():
    """요청 스냅샷 메타는 `api`/`note` 두 키로 통일 — path/endpoint/stream 혼용 제거 (R7, parity `_req_snapshot` 관례).

    라이브 run #3 cp/fable-5-1: context_window_1m은 {"path": "/v1/models/…"}, models_api는 {"endpoint": "/v1/models/…"} —
    같은 GET을 두 키로 표기했다.
    """
    _, ev = P.probe_token_counting(_FakeT(), "claude-opus-5", "opus-5")
    assert ev["request"]["api"] == "count_tokens" and "endpoint" not in ev["request"]

    stream = T.NormalizedResponse(content=[{"type": "text", "text": "1,2"}], events=[
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "1,"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "2"}}])
    ok, ev = P.probe_streaming(_FakeT(resp=stream), "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "messages (stream)" and "stream" not in ev["request"]

    class _ModelsT(_FakeT):
        routes = frozenset({"messages", "models"})
        def request(self, method, path, json=None, betas=(), files=None, data=None):
            return 200, {"id": "claude-opus-5", "capabilities": {}, "max_input_tokens": 1_000_000}

    ok, ev = P.probe_context_window_1m(_ModelsT(), "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "GET /v1/models/claude-opus-5" and "path" not in ev["request"]
    ok, ev = P.probe_models_api(_ModelsT(), "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "GET /v1/models/claude-opus-5" and "endpoint" not in ev["request"]

    # 소스 수준 가드 — 옛 키가 되살아나지 않도록
    import inspect
    src = inspect.getsource(P)
    assert "endpoint=" not in src and "path=f" not in src


def test_multi_call_probes_explain_themselves_with_note():
    """2회 호출 프로브는 요청 스냅샷에 note로 방법론을 적는다 (parity `note=` 관례, R7)."""
    ev, _ = P._cache_evidence("m", {"max_tokens": 1}, _text(usage={"input_tokens": 1}), _text(usage={"cache_read_input_tokens": 9}))
    assert ev["request"]["note"] == "same request twice; cache judged on 2nd call usage"

    t = _SeqT(_text(usage={"output_tokens": 3}),
              T.TransportError(400, "output_config.effort: Input should be 'low', 'medium', 'high', 'xhigh' or 'max'"))
    ok, ev = P.probe_effort(t, "claude-opus-5", "opus-5")
    assert ok is True and ev["request"]["note"] == "2 calls: effort=low, then effort=ultra as negative control"
    assert ev["negative_control"].startswith("rejected:")

    t = _SeqT(_text(usage={"inference_geo": "us"}), T.TransportError(400, "inference_geo: Input should be 'us'"))
    ok, ev = P.probe_data_residency(t, "claude-opus-5", "opus-5")
    assert ok is True and ev["request"]["note"] == "2 calls: inference_geo=us, then inference_geo=mars as negative control"

    t = _SeqT(T.TransportError(400, "tools.0: Input tag 'computer_toolset_20260801' found using 'type' does not match any of the expected tags"),
              T.NormalizedResponse(content=[{"type": "tool_use", "name": "computer", "input": {"action": "screenshot"}}], stop_reason="tool_use"))
    ok, ev = P.probe_computer_use(t, "claude-opus-5", "opus-5")
    assert ok is True and ev["request"]["note"] == "fallback attempt: computer_20251124+beta"
    assert ev["attempts"][0]["result"].startswith("HTTP 400") and ev["attempts"][1]["result"] == "ok"


def test_batch_and_files_probes_name_their_route_sequence():
    class _RoutesT(_FakeT):
        routes = frozenset({"messages", "batches", "files"})
        def request(self, method, path, json=None, betas=(), files=None, data=None):
            self.calls.append((method, path))
            if path.startswith("/v1/messages/batches"):
                return 200, {"id": "msgbatch_1", "processing_status": "in_progress"}
            if path == "/v1/files":
                return 200, {"id": "file_1", "type": "file"}
            return 200, {"id": "file_1"}

    t = _RoutesT()
    ok, ev = P.probe_batch_processing(t, "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "POST /v1/messages/batches → GET → POST cancel"
    assert [m for m, _ in t.calls] == ["POST", "GET", "POST"]
    t = _RoutesT()
    ok, ev = P.probe_files_api(t, "claude-opus-5", "opus-5")
    assert ok and ev["request"]["api"] == "POST /v1/files → GET → DELETE" and ev["deleted"] is True
    assert [m for m, _ in t.calls] == ["POST", "GET", "DELETE"]


def test_thinking_probes_store_usage():
    """thinking 증거에 usage 전체를 남긴다 — Bedrock Fable 5.1은 요약 텍스트가 비어 thinking_tokens가 유일한 수치 증거 (R10).

    필드명(`output_tokens_details.thinking_tokens`)은 공식 문서 미기재라 숫자만 뽑지 않고 usage 전체를 저장한다
    (캐싱 프로브 `first_usage`/`second_usage`와 같은 방식).
    """
    usage = {"input_tokens": 20, "output_tokens": 15, "output_tokens_details": {"thinking_tokens": 11}}
    resp = T.NormalizedResponse(content=[{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "107"}],
                                usage=usage)
    ok, ev = P.probe_adaptive_thinking(_FakeT(resp=resp), "global.anthropic.claude-fable-5-1", "fable-5-1")
    assert ok is True and ev["usage"] == usage and ev["thinking_signed"] is True and ev["thinking_chars"] == 0
    ok, ev = P.probe_extended_thinking(_FakeT(resp=resp), "claude-opus-5", "opus-5")
    assert ok is True and ev["usage"] == usage
```

- [ ] **Step 2: 실행 → 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q -k "api_key_instead or explain_themselves or route_sequence or thinking_probes_store"
```
기대: `4 failed` — `KeyError: 'api'`, `KeyError: 'note'`, `KeyError: 'api'`, `KeyError: 'usage'`.

- [ ] **Step 3: 구현** — `backend/claude_features/probes.py` 14곳 (각각 앵커 줄 → 교체 결과)

(1) `probe_streaming` converse 분기 (:178) — `"request": _req(model_id, kw, stream=True)` →
```python
        return deltas >= 2, {"request": _req(model_id, kw, api="converse (stream)"), "content_events": deltas}
```
(2) `probe_streaming` messages 분기 (:182):
```python
    return deltas >= 2, {"request": _req(model_id, body, api="messages (stream)"), "content_events": deltas, "response_snippet": _snippet(n)}
```
(3) `probe_context_window_1m` (:226) — `path=f"/v1/models/{model_id}"` →
```python
    return obj.get("max_input_tokens") == 1_000_000, {"request": _req(model_id, api=f"GET /v1/models/{model_id}"), **caps}
```
(4) `probe_adaptive_thinking` (:243-246) — return 문 전체:
```python
    # usage 전체를 남긴다 — Bedrock Fable 5.1은 요약 텍스트를 비워 보내므로(thinking_chars=0, signature만)
    # usage.output_tokens_details.thinking_tokens가 "추론을 실제로 했다"를 보여주는 유일한 수치 증거다.
    # (Converse는 normalize_converse가 usage를 4키로 재구성해 details가 없다 — 그 열은 수치 없이 남는다.)
    return engine.has_thinking_evidence(n.content), {
        "request": _req(model_id, kw), "content_types": [b.get("type") for b in n.content],
        "thinking_chars": len((th or {}).get("thinking") or ""),
        "thinking_signed": bool((th or {}).get("signature")), "usage": n.usage, "response_snippet": _snippet(n)}
```
(5) `probe_extended_thinking` (:266):
```python
    return engine.has_block(n.content, "thinking"), {"request": _req(model_id, kw), "content_types": [b.get("type") for b in n.content],
                                                     "usage": n.usage}
```
(6) `probe_batch_processing` (:283):
```python
    return ok, {"request": _req(model_id, req, api="POST /v1/messages/batches → GET → POST cancel"),
                "batch_id": bid, "processing_status": got.get("processing_status")}
```
(7) `probe_data_residency` messages 분기 (:335):
```python
    ev = {"request": _req(model_id, kw, note="2 calls: inference_geo=us, then inference_geo=mars as negative control"),
          "usage_inference_geo": n.usage.get("inference_geo")}
```
(8) `probe_effort` (:357):
```python
    ev = {"request": _req(model_id, kw, note=f"2 calls: effort=low, then effort={_BAD_EFFORT} as negative control"),
          "output_tokens_low": n.usage.get("output_tokens"), "response_snippet": _snippet(n)}
```
(9) `_with_fallback` (:442):
```python
            return n, {"attempts": log, "request": _req(model_id, body, betas=betas, note=f"fallback attempt: {label}")}
```
(10) `probe_fine_grained_tool_streaming` (:613):
```python
    return deltas >= 2, {"request": _req(model_id, kw, api="messages (stream)"), "input_json_deltas": deltas,
                         "tool_call": _trim(_tool_use_named(n, "echo"))}
```
(11) `_cache_evidence` (:704):
```python
    ev = {"request": _req(model_id, kw, note="same request twice; cache judged on 2nd call usage"),
          "first_usage": n1.usage, "second_usage": n2.usage,
          "stop_reason": [n1.stop_reason, n2.stop_reason],
          "stop_details": [_trim(n1.top.get("stop_details")), _trim(n2.top.get("stop_details"))]}
```
(12) `probe_token_counting` (:762) — `endpoint="count_tokens"` →
```python
    return isinstance(n, int) and n > 0, {"request": _req(model_id, kw, api="count_tokens"), "input_tokens": n}
```
(13) `probe_files_api` (:773) — `endpoint="/v1/files"` →
```python
    ev = {"request": _req(model_id, api="POST /v1/files → GET → DELETE"), "file_id": fid, "type": up.get("type")}
```
(14) `probe_models_api` (:791) — `endpoint=f"/v1/models/{model_id}"` →
```python
    return m.get("id") == model_id and "capabilities" in m, {"request": _req(model_id, api=f"GET /v1/models/{model_id}"),
                                                              "retrieved_id": m.get("id"), "capabilities": _trim(m.get("capabilities"))}
```

- [ ] **Step 4: 실행 → 전부 초록**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q && ruff check claude_features tests/test_claude_features.py
```
기대: `122 passed`, `All checks passed!`. 캐시 3프로브 테스트(:710-754)는 `ev["request"]`를 단언하지 않아 무영향.

- [ ] **Step 5: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add backend/claude_features/probes.py backend/tests/test_claude_features.py && git commit -m "fix(features): 요청 스냅샷 메타 키 api/note 통일 + thinking 증거 usage 보존 (R7, R10)"
```

---

### Task 5: D3-backend — `/api/features/latest` `changes[].kind: "catalog" | "measured"` (R5 §3 교정안, RUL-11)

**Implements:** verify-R5.md §3 (corrected mechanism: `latency_ms IS NULL` ⇔ runner pre-decided), critic §4-A backend side, D3-backend, RUL-11 (`before_missing` third input — a cell absent in the previous run can only appear through a catalog change). Bundle backend T5.

라이브 run #2→#3의 changes 15건은 전부 `data_residency: unsupported → not_applicable`(v2.23.1 `_NOT_APPLICABLE_BY_DOC`) — 실측 회귀가 아닌 카탈로그 규칙 변경인데 배너가 구분하지 못한다. `documented`(두 런 모두 "no")와 `catalog_version`(둘 다 "2026-09-05", 범프 누락)은 이 15건을 잡지 못한다(verify-R5 §3 refuted). 정확한 신호: 러너는 사전판정 행을 `latency_ms` 없이 저장(`runner.py:104-109`)하고 프로브 행은 route-gate까지 `run_probe`가 항상 latency를 채운다(`probes.py:136-157`) → `latency_ms IS NULL` ⇔ 사전판정. `diff_runs`(`engine.py:98-106`)는 그대로 두고(`test_diff_runs_keys` :86-93 정확 비교) 순수 함수를 추가해 `build_latest_payload`(`routers/features.py:40-62`)에서 태그한다.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/claude_features/engine.py` — `diff_runs` 뒤(:106 다음)에 `change_kind`, `annotate_change_kinds` 추가
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/routers/features.py` — 모듈 docstring (:4), import (:19), `build_latest_payload` changes 블록 (:47-52), `get_latest` prev_rows 쿼리 (:78-79). **`from __future__ import annotations` 금지** (FastAPI 라우터)
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/routers/CLAUDE.md:23` features 한 줄
- Test: `/home/ec2-user/my-project/model-monitoring/backend/tests/test_claude_features.py` — 기존 `test_build_latest_payload_computes_changes_and_drift`(:632-648) 2줄 수정 + 파일 끝에 3건 append

**Interfaces:**
- Produces (`claude_features.engine`):
  - `change_kind(before_predecided: bool, after_predecided: bool, before_missing: bool = False) -> str` — `"catalog"` if `before_missing` or either side pre-decided, else `"measured"`
  - `annotate_change_kinds(changes: list[dict[str, Any]], prev_predecided: set[tuple], cur_predecided: set[tuple]) -> list[dict[str, Any]]` — 키 `(feature, surface, model_key)`; `before_missing = (c["before"] is None)`
- Produces (HTTP `GET /api/features/latest`): `changes[i] = {feature, surface, model_key, before, after, kind: "catalog" | "measured", model_label}` — 신규 셀(`before: null`)은 `"catalog"`(RUL-11). 프론트(Task 9)가 `FeatureChange.kind?: "catalog" | "measured"`(optional — RUL-4)로 소비, 배너에 태그 + "카탈로그 규칙 변경 N건, 실측 변경 M건" 요약(D3).
- Consumes: `FeatureResult.latency_ms: Float | None`(`models.py:211` — `latency_ms = Column(Float, nullable=True)`), `engine.diff_runs` (변경 없음)
- 불변: `diff_runs` 출력(`kind` 없음), `previous_run_id`, `drift`, `results` 페이로드

- [ ] **Step 1: 실패 테스트 작성**

(a) 기존 `test_build_latest_payload_computes_changes_and_drift`(:632-648)에서 두 줄을 수정 — :644 `prev = [...]`와 :647 `assert p["changes"] == [...]`:
```python
    prev = [NS(feature="a", surface="cp", model_key="opus-5", status="supported", latency_ms=9.0)]
    p = build_latest_payload(run, rows, prev, 1, running=False)
    assert p["run"]["id"] == 2 and p["previous_run_id"] == 1
    assert p["changes"] == [{"feature": "a", "surface": "cp", "model_key": "opus-5", "before": "supported", "after": "broken",
                             "kind": "measured", "model_label": "Opus 5"}]
```

(b) 파일 끝에 append:
```python


# ==================================================================== v2.24.0 — Task 5: D3 backend changes[].kind

def test_change_kind_covers_all_four_predecided_combinations():
    assert engine.change_kind(False, False) == "measured"
    assert engine.change_kind(True, False) == "catalog"
    assert engine.change_kind(False, True) == "catalog"
    assert engine.change_kind(True, True) == "catalog"


def test_change_kind_new_cell_is_catalog_and_annotate_passes_before_missing():
    """직전 런에 없던 셀(before None)은 카탈로그 변경으로만 생길 수 있다 (RUL-11)."""
    assert engine.change_kind(False, False, before_missing=True) == "catalog"
    assert engine.change_kind(False, True, before_missing=True) == "catalog"
    assert engine.change_kind(True, False, before_missing=True) == "catalog"
    assert engine.change_kind(False, False, before_missing=False) == "measured"
    changes = engine.diff_runs(
        {("dr", "bedrock_converse", "opus-5"): "unsupported", ("x", "cp", "opus-5"): "supported"},
        {("dr", "bedrock_converse", "opus-5"): "not_applicable", ("new", "cp", "opus-5"): "supported", ("x", "cp", "opus-5"): "broken"})
    tagged = engine.annotate_change_kinds(changes, prev_predecided=set(), cur_predecided={("dr", "bedrock_converse", "opus-5")})
    # sorted(cur) 순서: dr → new → x
    assert [(c["feature"], c["kind"]) for c in tagged] == [("dr", "catalog"), ("new", "catalog"), ("x", "measured")]
    assert tagged[0]["before"] == "unsupported" and tagged[0]["after"] == "not_applicable"
    assert tagged[1]["before"] is None
    assert "kind" not in changes[0]  # diff_runs 자체는 그대로


def test_build_latest_payload_tags_catalog_rule_changes(monkeypatch):
    """run #2→#3 data_residency 15건: documented도 catalog_version도 그대로였고 latency만 1180ms→null (R5 교정안)."""
    import importlib
    from types import SimpleNamespace as NS

    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    build_latest_payload = importlib.import_module("routers.features").build_latest_payload
    run = NS(id=3, started_at=None, finished_at=None, totals={}, catalog_version="2026-09-05")
    rows = [
        NS(feature="data_residency", surface="bedrock_converse", model_key="opus-5", model_label="Claude Opus 5",
           model_id="global.anthropic.claude-opus-5", status="not_applicable", documented="no", verdict="none", latency_ms=None),
        NS(feature="token_counting", surface="bedrock_invoke", model_key="opus-5", model_label="Claude Opus 5",
           model_id="global.anthropic.claude-opus-5", status="unsupported", documented="no", verdict="match", latency_ms=310.0),
        NS(feature="models_api", surface="cp", model_key="opus-5", model_label="Claude Opus 5",
           model_id="claude-opus-5", status="supported", documented="ga", verdict="match", latency_ms=120.0),
    ]
    prev = [
        NS(feature="data_residency", surface="bedrock_converse", model_key="opus-5", status="unsupported", latency_ms=1179.99),
        NS(feature="token_counting", surface="bedrock_invoke", model_key="opus-5", status="supported", latency_ms=290.0),
    ]
    p = build_latest_payload(run, rows, prev, 2, running=False)
    kinds = {(c["feature"], c["surface"]): c["kind"] for c in p["changes"]}
    assert kinds == {("data_residency", "bedrock_converse"): "catalog",
                     ("token_counting", "bedrock_invoke"): "measured",
                     ("models_api", "cp"): "catalog"}  # 신규 셀(before None)은 카탈로그 변경 (RUL-11)
    assert all(c["model_label"] == "Claude Opus 5" for c in p["changes"])
```

- [ ] **Step 2: 실행 → 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q -k "change_kind or tags_catalog_rule or computes_changes_and_drift"
```
기대: `4 failed` — `AttributeError: module 'claude_features.engine' has no attribute 'change_kind'` ×2, `KeyError: 'kind'`, 그리고 수정한 기존 테스트의 `AssertionError`(changes에 `kind` 없음).

- [ ] **Step 3: 구현 (1/3)** — `backend/claude_features/engine.py`, `diff_runs`의 `return out`(:106) 뒤에 추가

```python


def change_kind(before_predecided: bool, after_predecided: bool, before_missing: bool = False) -> str:
    """런 간 변경 1건의 원인 태그 — "catalog"(카탈로그 규칙 변경) | "measured"(실측 변경).

    러너는 카탈로그 사전판정 행(`is_applicable` → not_applicable/skipped)을 latency_ms 없이 저장하고,
    프로브 행은 route-gate unsupported까지 항상 latency를 채운다 → `latency_ms IS NULL` ⇔ 사전판정.
    before/after 어느 한쪽이 사전판정이면 카탈로그 변경, 둘 다 프로브 결과면 실측 변경.
    직전 런에 없던 셀(before_missing)은 카탈로그에 행/모델/surface가 추가됐다는 뜻이므로 항상 카탈로그 변경이다.
    (run #2→#3의 data_residency 15건은 documented도 catalog_version도 그대로였고 latency만 1180ms→null이었다 —
    documented 비교나 catalog_version 비교로는 잡히지 않는다.)
    """
    if before_missing:
        return "catalog"
    return "catalog" if (before_predecided or after_predecided) else "measured"


def annotate_change_kinds(changes: list[dict[str, Any]], prev_predecided: set[tuple], cur_predecided: set[tuple]) -> list[dict[str, Any]]:
    """diff_runs 결과에 kind를 덧붙인다 — 키는 (feature, surface, model_key). diff_runs 자체는 그대로 둔다."""
    out: list[dict[str, Any]] = []
    for c in changes:
        key = (c["feature"], c["surface"], c["model_key"])
        out.append({**c, "kind": change_kind(key in prev_predecided, key in cur_predecided, before_missing=c["before"] is None)})
    return out
```

- [ ] **Step 4: 구현 (2/3)** — `backend/routers/features.py` 네 곳 (`from __future__ import annotations` 금지 — FastAPI 라우터)

(a) docstring (:4):
```python
- GET  /api/features/latest    — 최신 완료 런 매트릭스 + 직전 런 diff(kind: catalog|measured) + 드리프트 목록 (s-maxage=60)
```
(b) import (:19):
```python
from claude_features.engine import annotate_change_kinds, diff_runs
```
(c) `build_latest_payload` changes 블록 (:47-52):
```python
    changes: list[dict] = []
    if prev_rows is not None:
        prev_map = {(p.feature, p.surface, p.model_key): p.status for p in prev_rows}
        cur_map = {(r.feature, r.surface, r.model_key): r.status for r in rows}
        # latency_ms IS NULL ⇔ 러너 사전판정 행(카탈로그 규칙) — engine.change_kind 참조
        prev_pre = {(p.feature, p.surface, p.model_key) for p in prev_rows if p.latency_ms is None}
        cur_pre = {(r.feature, r.surface, r.model_key) for r in rows if r.latency_ms is None}
        labels = {r.model_key: r.model_label for r in rows}
        changes = [{**c, "model_label": labels.get(c["model_key"], c["model_key"])}
                   for c in annotate_change_kinds(diff_runs(prev_map, cur_map), prev_pre, cur_pre)]
```
(d) `get_latest` prev_rows 쿼리 (:78-79) — `FeatureResult.latency_ms` 컬럼 추가:
```python
        prev_rows = (db.query(FeatureResult.feature, FeatureResult.surface, FeatureResult.model_key, FeatureResult.status,
                              FeatureResult.latency_ms)
                     .filter(FeatureResult.run_id == prev_run.id).all())
```

- [ ] **Step 5: 구현 (3/3)** — `backend/routers/CLAUDE.md:23` 한 줄

`latest (완료 런 매트릭스 + 직전 런 대비 diff + drift)`를 다음으로 교체:
```
latest (완료 런 매트릭스 + 직전 런 대비 diff — `kind: catalog|measured`로 카탈로그 규칙 변경과 실측 변경 구분(신규 셀·사전판정 행 = catalog), v2.24.0 + drift)
```

- [ ] **Step 6: 실행 → 전부 초록 + backend 전체 스위트**

```bash
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q && ruff check claude_features tests/test_claude_features.py routers/features.py && python3.12 -m pytest tests -q
```
기대: `125 passed` / `All checks passed!` / `247 passed, 1 warning`(passlib crypt DeprecationWarning은 기존).

- [ ] **Step 7: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add backend/claude_features/engine.py backend/routers/features.py backend/routers/CLAUDE.md backend/tests/test_claude_features.py && git commit -m "feat(features): /api/features/latest changes[].kind — 사전판정(latency_ms null)·신규 셀 기준 catalog|measured 태그 (R5, RUL-11)"
```

---

### Task 6: Pure logic — `surfaceSummary()`, `runSummary()`, `formatDuration()`, `visibleSegments()` + shared `PROBED_STATUSES`/`isProbed`/`isDocumented` (D1, RUL-2, RUL-5, RUL-7, critic 4-C; C9/R2 logic)

**Implements:** verify-R2.md (documented health formula, probed/N-A split) with **C2 merged into it** (critic §6-1 M1 — the health-card redefinition: 6-state distribution bar, `{total} 셀` chip, drift pill; C2's `match/(match+drift)` 76% formula is superseded by R2's docHealth 63%), verify-C9.md (run totals strip + duration), critic §4-C (`probedAmongDocumented === 0` → "-", `{total} 셀` counts all cells incl. N/A), D1 verbatim (RUL-2 — denominator keeps `inconclusive`), RUL-5 (counts-line visibility rule as a pure helper), RUL-7 (the ONE definition of `PROBED_STATUSES`/`isProbed`/`isDocumented`, exported for Tasks 11 and 14). Bundle frontend-A T1.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — append after `surfaceHealth` (CFL:120-128, end of file). `surfaceHealth` stays exported and unchanged (D1 backward compat; existing test CFL-test:63-68 stays green).
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — replace the import (line 3) and append two `describe` blocks after `describe("surfaceHealth", …)` (closing `});` at line 68).

**Interfaces:**
- Consumes: `FeatureCell` (CFL:8-11: `status: FeatureStatus; documented: Documented; verdict: Verdict; surface: string`), `FeatureRunInfo.totals: Record<string, number> | null` (CFL:21), `FeatureRunInfo.started_at/finished_at: string | null` (CFL:20).
- Produces (all exported from `claudeFeatures.ts`):
  ```ts
  export const PROBED_STATUSES: ReadonlySet<FeatureStatus>;                 // supported|unsupported|broken|inconclusive
  export function isProbed(status: FeatureStatus): boolean;
  export function isDocumented(documented: Documented): boolean;            // ga|beta
  export type SummarySegment = "supported" | "unsupported" | "broken" | "inconclusive" | "documented_only" | "other";
  export const SEGMENT_ORDER: SummarySegment[];
  export const SEGMENT_BAR_COLOR: Record<SummarySegment, string>;   // solid bg-* for the stacked bar
  export const SEGMENT_TEXT: Record<SummarySegment, string>;        // text-* for count legends
  export const SEGMENT_LABEL: Record<SummarySegment, { en: string; ko: string }>;
  export const STATUS_TEXT: Record<FeatureStatus, string>;          // text-* per raw status (run strip)
  export const RUN_STATUS_ORDER: FeatureStatus[];
  export interface SurfaceSummary {
    surface: string; total: number; counts: Record<FeatureStatus, number>; segments: Record<SummarySegment, number>;
    probed: number; drift: number; undocumented: number; docSupported: number; docProbed: number; docHealth: number | null;
    supported: number; broken: number; health: number;   // identical to surfaceHealth()
  }
  export function surfaceSummary(cells: FeatureCell[], surface: string): SurfaceSummary;
  export function visibleSegments(summary: SurfaceSummary): SummarySegment[];   // RUL-5 counts-line rule
  export interface RunSummary { total: number; statuses: { status: FeatureStatus; count: number }[]; drift: number }
  export function runSummary(totals: Record<string, number> | null | undefined): RunSummary | null;
  export function formatDuration(startedAt: string | null, finishedAt: string | null, lang: string): string | null;
  ```
  Semantics (D1): `docHealth = round(100 * docSupported / docProbed)` where `docSupported` = cells with `documented ∈ {ga, beta}` and `status === "supported"`, `docProbed` = cells with `documented ∈ {ga, beta}` and `status ∈ PROBED_STATUSES`; `docHealth === null` when `docProbed === 0` (critic 4-C guard). `total` counts every cell of the surface incl. N/A. Segments: `documented_only` = `skipped ∧ documented ∈ {ga, beta}` (same rule as `cellBadge`, CFL:52), `other` = remaining skipped + not_applicable. `visibleSegments` (RUL-5) = `supported`, `unsupported`, `broken` always, then `inconclusive`/`documented_only`/`other` only when `> 0`, in `SEGMENT_ORDER`. Live check (run #3 Mantle, `scratchpad/features-latest.json`): docSupported 42, docProbed 67 → **63%** (not the 76% quoted in older candidate text); cp/bedrock 100%.

- [ ] **Step 1: Write the failing tests**

Edit `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts`. Replace line 3
```ts
import { aggregateCell, buildGroups, surfaceHealth, type FeatureCell, type FeatureDef } from "./claudeFeatures";
```
with
```ts
import {
  aggregateCell, buildGroups, formatDuration, isDocumented, isProbed, runSummary, surfaceHealth, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureDef,
} from "./claudeFeatures";
```
Append after the closing `});` of `describe("surfaceHealth", …)` (line 68 on a048028; line 71 once the import replacement above has grown the file by three lines — use the text anchor, not the number):
```ts
describe("surfaceSummary (v2.24.0 헬스 카드)", () => {
  // Mantle run #3 축소판 — surface "mantle"만 집계, "cp" 셀은 무시돼야 함
  const mantle = (p: Partial<FeatureCell>) => cell({ surface: "mantle", ...p });
  const cells: FeatureCell[] = [
    mantle({ feature: "a" }),                                                            // ga supported
    mantle({ feature: "b", documented: "beta" }),                                        // beta supported
    mantle({ feature: "c", status: "unsupported", verdict: "drift" }),                   // ga unsupported → drift
    mantle({ feature: "d", status: "unsupported", documented: "no", verdict: "match" }), // 음성 일치(문서 미제공, 실측 미지원)
    mantle({ feature: "e", status: "unsupported", documented: "no", verdict: "match" }),
    mantle({ feature: "f", status: "skipped", verdict: "none" }),                        // ga skipped → 문서상 지원(sky)
    mantle({ feature: "g", status: "not_applicable", documented: "no", verdict: "none" }),
    mantle({ feature: "h", status: "not_applicable", documented: "no", verdict: "none" }),
    mantle({ feature: "i", status: "inconclusive", documented: "unknown", verdict: "none" }),
    mantle({ feature: "j", documented: "no", verdict: "undocumented" }),                 // 문서 미제공인데 동작
    cell({ feature: "z", status: "broken", verdict: "drift" }),                          // surface cp → 제외
  ];
  test("total/counts/segments cover ALL cells of the surface (N/A included)", () => {
    const s = surfaceSummary(cells, "mantle");
    expect(s.total).toBe(10);
    expect(s.counts).toEqual({ supported: 3, unsupported: 3, broken: 0, inconclusive: 1, skipped: 1, not_applicable: 2 });
    expect(s.segments).toEqual({ supported: 3, unsupported: 3, broken: 0, inconclusive: 1, documented_only: 1, other: 2 });
    expect(s.probed).toBe(7);
    expect(s.drift).toBe(1);
    expect(s.undocumented).toBe(1);
  });
  test("docHealth = documented(ga/beta) ∧ supported / documented ∧ probed — negative matches do not inflate it", () => {
    const s = surfaceSummary(cells, "mantle");
    expect(s.docSupported).toBe(2); // a, b
    expect(s.docProbed).toBe(3);    // a, b, c — i(unknown), d/e(documented=no) 제외
    expect(s.docHealth).toBe(67);
    const withoutNegatives = surfaceSummary(cells.filter((c) => c.feature !== "d" && c.feature !== "e"), "mantle");
    expect(withoutNegatives.docHealth).toBe(67);
  });
  test("legacy fields stay identical to surfaceHealth()", () => {
    const s = surfaceSummary(cells, "mantle");
    const h = surfaceHealth(cells, "mantle");
    expect({ supported: s.supported, broken: s.broken, health: s.health }).toEqual(h);
    expect(h).toEqual({ supported: 3, broken: 0, health: 100 });
  });
  test("no documented+probed cell → docHealth null (card shows '-'); empty surface → total 0", () => {
    const onlyNa = [mantle({ status: "not_applicable", verdict: "none" }), mantle({ status: "skipped", verdict: "none", model_key: "sonnet-5" })];
    const s = surfaceSummary(onlyNa, "mantle");
    expect(s.docHealth).toBeNull();
    expect(s.total).toBe(2);
    expect(s.segments.documented_only).toBe(1);
    expect(s.segments.other).toBe(1);
    expect(surfaceSummary([], "mantle")).toMatchObject({ total: 0, docHealth: null, drift: 0, health: 0 });
  });
  test("visibleSegments: supported/unsupported/broken always, the other three only when > 0 (RUL-5); shared predicates", () => {
    expect(visibleSegments(surfaceSummary(cells, "mantle"))).toEqual(["supported", "unsupported", "broken", "inconclusive", "documented_only", "other"]);
    expect(visibleSegments(surfaceSummary([mantle({ feature: "a" })], "mantle"))).toEqual(["supported", "unsupported", "broken"]);
    expect(visibleSegments(surfaceSummary([mantle({ status: "not_applicable", verdict: "none" })], "mantle"))).toEqual(["supported", "unsupported", "broken", "other"]);
    expect(isProbed("inconclusive")).toBe(true);
    expect(isProbed("skipped")).toBe(false);
    expect(isProbed("not_applicable")).toBe(false);
    expect(isDocumented("beta")).toBe(true);
    expect(isDocumented("unknown")).toBe(false);
    expect(isDocumented("no")).toBe(false);
  });
});

describe("runSummary / formatDuration (v2.24.0 런 합계 스트립)", () => {
  test("totals → 6 status counts in fixed order, total = their sum, drift kept separate", () => {
    const s = runSummary({ supported: 419, unsupported: 206, broken: 0, inconclusive: 0, skipped: 15, not_applicable: 140, drift: 25 });
    expect(s).not.toBeNull();
    expect(s!.total).toBe(780);
    expect(s!.statuses.map((x) => x.status)).toEqual(["supported", "unsupported", "broken", "inconclusive", "skipped", "not_applicable"]);
    expect(s!.statuses[0].count).toBe(419);
    expect(s!.drift).toBe(25);
  });
  test("missing keys count as 0; null/undefined totals → null", () => {
    expect(runSummary({ supported: 1 })!.total).toBe(1);
    expect(runSummary({ supported: 1 })!.drift).toBe(0);
    expect(runSummary(null)).toBeNull();
    expect(runSummary(undefined)).toBeNull();
  });
  test("formatDuration: run #3 → '6분 15초' / '6m 15s'; seconds only under a minute; null when missing or reversed", () => {
    expect(formatDuration("2026-09-06T00:26:35.455128+00:00", "2026-09-06T00:32:50.794359+00:00", "ko")).toBe("6분 15초");
    expect(formatDuration("2026-09-06T00:26:35.455128+00:00", "2026-09-06T00:32:50.794359+00:00", "en")).toBe("6m 15s");
    expect(formatDuration("2026-09-06T00:00:00Z", "2026-09-06T00:00:42Z", "ko")).toBe("42초");
    expect(formatDuration(null, "2026-09-06T00:32:50Z", "ko")).toBeNull();
    expect(formatDuration("2026-09-06T00:32:50Z", "2026-09-06T00:26:35Z", "ko")).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests — expect failure**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
Expected: 8 new tests fail with `TypeError: surfaceSummary is not a function` / `TypeError: visibleSegments is not a function` / `TypeError: runSummary is not a function` / `TypeError: formatDuration is not a function` (vitest resolves a missing named export to `undefined`; verified on this toolchain). The 11 existing tests stay green.

- [ ] **Step 3: Implement**

Append to `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` after line 128 (the closing `}` of `surfaceHealth`):
```ts

// ── v2.24.0 UI detail parity — 공용 술어 (RUL-7: 여기 한 번만 정의, 드로어·지연시간 헬퍼가 import) ──────────
export const PROBED_STATUSES: ReadonlySet<FeatureStatus> = new Set<FeatureStatus>(["supported", "unsupported", "broken", "inconclusive"]);
export function isProbed(status: FeatureStatus): boolean { return PROBED_STATUSES.has(status); }
export function isDocumented(documented: Documented): boolean { return documented === "ga" || documented === "beta"; }

// ── v2.24.0 UI detail parity — 헬스 카드 요약 (C2/R2, D1), 런 합계 스트립 (C9) ────────────────────

/** 헬스 카드 막대 세그먼트 — 6상태를 표시 단위로 접음: skipped는 문서 GA/Beta면 '문서상 지원'(sky, cellBadge 규칙과 동일),
 *  나머지 skipped와 N/A는 other(gray). */
export type SummarySegment = "supported" | "unsupported" | "broken" | "inconclusive" | "documented_only" | "other";
export const SEGMENT_ORDER: SummarySegment[] = ["supported", "unsupported", "broken", "inconclusive", "documented_only", "other"];
// 누적 막대용 솔리드 색 — STATUS_STYLE(반투명 배지 배경)은 막대에서 보이지 않으므로 parity BAR_COLORS(ParityPanel.tsx:86-91) 패턴을 따름.
export const SEGMENT_BAR_COLOR: Record<SummarySegment, string> = {
  supported: "bg-emerald-400", unsupported: "bg-amber-400", broken: "bg-rose-400",
  inconclusive: "bg-violet-400", documented_only: "bg-sky-400", other: "bg-gray-600",
};
export const SEGMENT_TEXT: Record<SummarySegment, string> = {
  supported: "text-emerald-300", unsupported: "text-amber-300", broken: "text-rose-300",
  inconclusive: "text-violet-300", documented_only: "text-sky-300", other: "text-gray-500",
};
export const SEGMENT_LABEL: Record<SummarySegment, { en: string; ko: string }> = {
  supported: { en: "Supported", ko: "Supported" }, unsupported: { en: "Unsupported", ko: "Unsupported" },
  broken: { en: "Broken", ko: "Broken" }, inconclusive: { en: "Inconclusive", ko: "Inconclusive" },
  documented_only: { en: "Documented", ko: "문서상 지원" }, other: { en: "N/A", ko: "N/A" },
};
export const STATUS_TEXT: Record<FeatureStatus, string> = {
  supported: "text-emerald-300", unsupported: "text-amber-300", broken: "text-rose-300",
  inconclusive: "text-violet-300", skipped: "text-gray-500", not_applicable: "text-gray-500",
};

export interface SurfaceSummary {
  surface: string;
  total: number;                          // surface의 전체 셀 수 (N/A 포함) — 카드 "{total} 셀" 칩
  counts: Record<FeatureStatus, number>;  // 6상태 원시 카운트
  segments: Record<SummarySegment, number>;
  probed: number;                         // supported+unsupported+broken+inconclusive
  drift: number;                          // verdict === "drift"
  undocumented: number;                   // verdict === "undocumented"
  docSupported: number;                   // documented ∈ {ga,beta} ∧ supported
  docProbed: number;                      // documented ∈ {ga,beta} ∧ status ∈ probed 4상태 (inconclusive 포함 — RUL-2)
  docHealth: number | null;               // round(100·docSupported/docProbed); docProbed=0 → null (카드 "-")
  supported: number; broken: number; health: number; // surfaceHealth() 호환 필드
}

/** 헬스 카드 헤드라인은 "문서상 제공(GA/Beta) 기능 중 실측 동작 비율"(docHealth). 음성 일치(documented=no ∧ unsupported)는
 *  분모·분자 어디에도 들어가지 않는다 — match/(match+drift) 공식이 76%로 부풀던 문제의 교정(verify-R2). */
export function surfaceSummary(cells: FeatureCell[], surface: string): SurfaceSummary {
  const counts: Record<FeatureStatus, number> = { supported: 0, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 };
  let total = 0, drift = 0, undocumented = 0, docSupported = 0, docProbed = 0, documentedOnly = 0;
  for (const c of cells) {
    if (c.surface !== surface) continue;
    total += 1;
    counts[c.status] += 1;
    if (c.verdict === "drift") drift += 1;
    else if (c.verdict === "undocumented") undocumented += 1;
    if (c.status === "skipped" && isDocumented(c.documented)) documentedOnly += 1;
    if (isDocumented(c.documented) && isProbed(c.status)) {
      docProbed += 1;
      if (c.status === "supported") docSupported += 1;
    }
  }
  const probed = counts.supported + counts.unsupported + counts.broken + counts.inconclusive;
  const segments: Record<SummarySegment, number> = {
    supported: counts.supported, unsupported: counts.unsupported, broken: counts.broken, inconclusive: counts.inconclusive,
    documented_only: documentedOnly, other: counts.skipped - documentedOnly + counts.not_applicable,
  };
  return {
    surface, total, counts, segments, probed, drift, undocumented, docSupported, docProbed,
    docHealth: docProbed === 0 ? null : Math.round((100 * docSupported) / docProbed),
    supported: counts.supported, broken: counts.broken,
    health: Math.round((100 * counts.supported) / Math.max(1, counts.supported + counts.broken)),
  };
}

const ALWAYS_SEGMENTS: ReadonlySet<SummarySegment> = new Set<SummarySegment>(["supported", "unsupported", "broken"]);
/** 헬스 카드 카운트 줄 (RUL-5): supported/unsupported/broken은 항상, inconclusive/문서상 지원/N/A는 0이 아닐 때만. */
export function visibleSegments(summary: SurfaceSummary): SummarySegment[] {
  return SEGMENT_ORDER.filter((seg) => ALWAYS_SEGMENTS.has(seg) || summary.segments[seg] > 0);
}

/** 런 합계 스트립 (C9): totals의 6 status 키는 합 = 전체 셀(780), drift는 verdict 카운트라 status와 겹침 → 별도 필드로 분리. */
export const RUN_STATUS_ORDER: FeatureStatus[] = ["supported", "unsupported", "broken", "inconclusive", "skipped", "not_applicable"];
export interface RunSummary { total: number; statuses: { status: FeatureStatus; count: number }[]; drift: number }

export function runSummary(totals: Record<string, number> | null | undefined): RunSummary | null {
  if (!totals) return null;
  const statuses = RUN_STATUS_ORDER.map((status) => ({ status, count: totals[status] ?? 0 }));
  return { total: statuses.reduce((n, x) => n + x.count, 0), statuses, drift: totals.drift ?? 0 };
}

/** finished_at − started_at → "6분 15초" / "6m 15s". 입력 누락, 역순, 파싱 실패는 null. */
export function formatDuration(startedAt: string | null, finishedAt: string | null, lang: string): string | null {
  if (!startedAt || !finishedAt) return null;
  const ms = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60), s = totalSec % 60;
  if (lang === "en") return m > 0 ? `${m}m ${s}s` : `${s}s`;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}
```

- [ ] **Step 4: Run tests and typecheck — expect green**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run && npx tsc --noEmit -p . && echo TSC-OK
```
Expected: `Tests 58 passed (58)` (50 + 8), `TSC-OK`.

- [ ] **Step 5: Commit**
```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts && git commit -m "feat(features): surfaceSummary/runSummary/formatDuration/visibleSegments 순수 로직 — 문서 기준 헬스(docHealth), 6세그먼트 분포, probed=0 가드, 런 합계·소요시간, 공용 isProbed/isDocumented (C9/R2, D1, RUL-5/7)"
```

---

### Task 7: Health cards (docHealth headline + 6-state bar + cells chip + drift pill + RUL-5 counts line) and run totals strip (D1, critic 4-C; C9/R2 UI)

**Implements:** verify-R2.md, verify-C9.md, critic §4-C, D1, RUL-5. Bundle frontend-A T2.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx`
  - CF:14-17 import block (swap `surfaceHealth` for the Task 6 exports)
  - CF:145 — insert `HealthBar` component immediately above `export default function ClaudeFeaturesPanel()`
  - CF:176-177 — add `runTotals` / `duration` derived values after `const drift = latest?.drift ?? [];`
  - CF:199-204 — run meta line gains duration; run totals strip inserted below it
  - CF:244-262 — replace the health-card block
- Test: no new vitest (JSX only); gate = `npx tsc --noEmit -p .` + full `npx vitest run` staying at 58.

**Interfaces:**
- Consumes (from Task 6): `surfaceSummary`, `visibleSegments`, `runSummary`, `formatDuration`, `SEGMENT_ORDER`, `SEGMENT_BAR_COLOR`, `SEGMENT_TEXT`, `SEGMENT_LABEL`, `STATUS_TEXT`, `type SurfaceSummary`; existing `STATUS_LABEL` (CFL:38-41); `catalog.surfaces: SurfaceDef[]` (`id, label, short, group, region`, CFL:17); `latest.run` (`FeatureRunInfo`, CFL:19-22); `useLang().lang: "ko" | "en"` (`src/lib/i18n-context.tsx:40`).
- Produces: `function HealthBar({ summary, lang }: { summary: SurfaceSummary; lang: "en" | "ko" }): JSX.Element` (module-private in the panel). Card DOM: `<div key={s.id} className="bg-gray-900/50 light:bg-white border border-gray-800 rounded-xl p-4">` — Task 12 converts this wrapper to `<button type="button" onClick={() => setSurfaceDetail(s.id)}>` and appends a CTA line without touching the other children.

- [ ] **Step 1: Update imports (CF:14-17)**

Replace
```tsx
import {
  aggregateCell, buildGroups, cellBadge, surfaceHealth, DOC_LABEL, STATUS_LABEL, STATUS_STYLE, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type RowView,
} from "@/lib/claudeFeatures";
```
with
```tsx
import {
  aggregateCell, buildGroups, cellBadge, formatDuration, runSummary, surfaceSummary, visibleSegments,
  DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type RowView, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```
Run `cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p .` — expected failure: `error TS2304: Cannot find name 'surfaceHealth'` at the card block (CF:248). This is the red step for this task.

- [ ] **Step 2: Add the `HealthBar` component**

Insert immediately before line 145 (`export default function ClaudeFeaturesPanel() {`):
```tsx
// 헬스 카드 분포 막대 — parity HealthBar(ParityPanel.tsx:93-110) 이식, features 6세그먼트 (v2.24.0, D1)
function HealthBar({ summary, lang }: { summary: SurfaceSummary; lang: "en" | "ko" }) {
  const total = Math.max(1, summary.total);
  return (
    <div className="flex h-2 w-full rounded-full overflow-hidden bg-gray-800" role="img"
         aria-label={SEGMENT_ORDER.map((seg) => `${SEGMENT_LABEL[seg][lang]} ${summary.segments[seg]}`).join(", ")}>
      {SEGMENT_ORDER.map((seg) =>
        summary.segments[seg] > 0 ? (
          <div key={seg} className={SEGMENT_BAR_COLOR[seg]} style={{ width: `${(100 * summary.segments[seg]) / total}%` }}
               title={`${SEGMENT_LABEL[seg][lang]} ${summary.segments[seg]}`} />
        ) : null,
      )}
    </div>
  );
}

```

- [ ] **Step 3: Derived run values (CF:176-177)**

After
```tsx
  const run = latest?.run ?? null;
  const drift = latest?.drift ?? [];
```
add
```tsx
  const runTotals = runSummary(run?.totals);
  const duration = formatDuration(run?.started_at ?? null, run?.finished_at ?? null, lang);
```

- [ ] **Step 4: Run meta line + run totals strip (CF:199-204)**

Replace
```tsx
          {run && (
            <p className="text-xs text-gray-500 mt-1">
              {L("Last run", "최근 런")} #{run.id} · {run.finished_at ? new Date(run.finished_at).toLocaleString() : "-"} · catalog {run.catalog_version}
              {run.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
```
with
```tsx
          {run && (
            <p className="text-xs text-gray-500 mt-1">
              {L("Last run", "최근 런")} #{run.id} · {run.finished_at ? new Date(run.finished_at).toLocaleString() : "-"} · catalog {run.catalog_version}
              {duration && <> · {L("took", "소요")} {duration}</>}
              {run.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
          {/* 런 합계 스트립 (C9, v2.24.0) — 6 status 합 = 전체 셀, 드리프트는 verdict 카운트라 별도 pill (배너·카드와 같은 수를 가리켜야 함).
              run.totals는 런 전체 값이라 모델 칩 필터(D5)에 영향받지 않는다. */}
          {run && runTotals && (
            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap mt-1.5 text-[11px] tabular-nums">
              <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{runTotals.total} {L("cells", "셀")}</span>
              {runTotals.statuses.map((x) => (
                <span key={x.status} className={STATUS_TEXT[x.status]}>● {x.count} {STATUS_LABEL[x.status]}</span>
              ))}
              <span className="px-1.5 py-0.5 rounded-full border border-rose-500/30 bg-rose-500/10 text-rose-300">▲ {L("drift", "드리프트")} {runTotals.drift}</span>
            </div>
          )}
```

- [ ] **Step 5: Replace the health-card block (CF:244-262)**

Replace the whole block from `{/* 엔드포인트 헬스 카드 */}` through its closing `)}` (currently:
```tsx
      {/* 엔드포인트 헬스 카드 */}
      {run && catalog && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
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
```
) with
```tsx
      {/* 엔드포인트 헬스 카드 (v2.24.0, D1) — 헤드라인 = 문서 기준 헬스(docHealth: 문서상 GA/Beta ∧ 실측된 셀 중 supported 비율),
          6세그먼트 분포 막대(전체 셀), "{total} 셀" 칩(N/A 포함), 드리프트 pill(>0). docProbed=0이면 "-" (critic 4-C).
          카운트 줄은 visibleSegments (RUL-5: supported/unsupported/broken 항상, 나머지는 >0일 때만). */}
      {run && catalog && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
          {catalog.surfaces.map((s) => {
            const sm = surfaceSummary(cells, s.id);
            return (
              <div key={s.id} className="bg-gray-900/50 light:bg-white border border-gray-800 rounded-xl p-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-gray-100">{s.label}</span>
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400 tabular-nums">{sm.total} {L("cells", "셀")}</span>
                  {sm.drift > 0 && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded-full border border-rose-500/30 bg-rose-500/10 text-rose-300 tabular-nums">▲ {L("drift", "드리프트")} {sm.drift}</span>
                  )}
                </div>
                <div className="text-[11px] text-gray-500 font-mono">{s.region}</div>
                <div className="mt-2 flex items-end gap-2">
                  <span className="text-2xl font-bold text-gray-100 tabular-nums leading-none">{sm.docHealth == null ? "-" : `${sm.docHealth}%`}</span>
                  <span className="text-[11px] text-gray-500">
                    {sm.docHealth == null
                      ? L("no documented feature measured on this endpoint", "문서상 제공 기능 중 실측된 셀 없음")
                      : L("of documented (GA/Beta) features work as measured", "문서상 제공(GA/Beta) 기능 중 실측 동작")}
                  </span>
                </div>
                <div className="mt-2"><HealthBar summary={sm} lang={lang} /></div>
                <div className="flex items-center gap-x-3 gap-y-1 flex-wrap mt-2 text-[11px] tabular-nums">
                  {visibleSegments(sm).map((seg) => (
                    <span key={seg} className={SEGMENT_TEXT[seg]}>● {sm.segments[seg]} {SEGMENT_LABEL[seg][lang]}</span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
```

- [ ] **Step 6: Typecheck, tests, visual check**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && echo TSC-OK && npx vitest run 2>&1 | tail -4
```
Expected: `TSC-OK`, `Tests 58 passed (58)`.
Manual check (optional but recommended, needs backend reachable via the `next.config.mjs` `/api/*` rewrite): `npm run dev`, open `http://localhost:3000/claude-features`. Against run #3 data expect: run strip `780 셀 ● 419 Supported ● 206 Unsupported ● 0 Broken ● 0 Inconclusive ● 15 Skipped ● 140 N/A ▲ 드리프트 25`, meta line `… · 소요 6분 15초`; Mantle card `63%`, chip `156 셀`, pill `▲ 드리프트 25`, bar segments 44/65/0/0/3/44, counts line `● 44 Supported ● 65 Unsupported ● 0 Broken ● 3 문서상 지원 ● 44 N/A` (Inconclusive 0 → hidden per RUL-5); the other four cards `100%` with no drift pill.

- [ ] **Step 7: Commit**
```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "feat(features): 헬스 카드 문서 기준 헬스(docHealth)+6세그먼트 분포+전체 셀 칩+드리프트 pill, 런 합계 스트립·소요시간 — Mantle 100%→63% 오독 해소 (C9/R2, D1, RUL-5)"
```

---

### Task 8: Catalog-sourced label maps — drift banner, evidence modal header (D2, RUL-6; C3/C10)

**Implements:** verify-C3.md (feature label in banner rows), verify-C10.md (evidence modal header labels + verdict label i18n), **R8 merged** (synth-data.md §R8 — human-readable catalog labels `label_ko/en` + surface `short` in the drift/changes banners and the modal header; critic §6-1 M3), D2, RUL-6 (`LabelMaps` shape and `featureLabelOf`/`surfaceShortOf` are the shared contract Task 12's drawer consumes). Bundle frontend-A T3.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — append `LabelMaps`, `labelMaps()`, `featureLabelOf()`, `surfaceShortOf()` at end of file (after Task 6 additions).
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx`
  - CF:25 `EvidenceModal` signature — add `labels: LabelMaps` prop
  - CF:75-76 modal title/subtitle
  - CF:82 `verdict:` label i18n (C10 local cleanup)
  - CF:170 — add `labels` memo after `surfaces` memo
  - CF:219-225 drift banner items
  - CF:369 modal mount — pass `labels`
  - import block — add `labelMaps, featureLabelOf, surfaceShortOf, type LabelMaps`
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — extend import, append `describe("labelMaps", …)`.

**Interfaces:**
- Consumes: `FeatureDef.label_ko/label_en` (CFL:13), `SurfaceDef.short` (CFL:17), `FeaturesCatalog` (`src/lib/api.ts:860` — `{ groups; surfaces; models; features }`), loaded into `catalog` state at CF:148/157-158.
- Produces:
  ```ts
  export interface LabelMaps { featureLabel: Map<string, string>; surfaceShort: Map<string, string> }
  export function labelMaps(catalog: { features: FeatureDef[]; surfaces: SurfaceDef[] } | null | undefined, lang: string): LabelMaps;
  export function featureLabelOf(maps: LabelMaps, id: string): string;   // maps.featureLabel.get(id) ?? id
  export function surfaceShortOf(maps: LabelMaps, id: string): string;   // maps.surfaceShort.get(id) ?? id
  ```
  Panel: `const labels = useMemo(() => labelMaps(catalog, lang), [catalog, lang]);` — Task 9 (changes banner) and Task 12 (drawer, prop `labels: LabelMaps`) consume this same memo (RUL-6).

- [ ] **Step 1: Write the failing test**

In `claudeFeatures.test.ts` extend the import (from Task 6) to
```ts
import {
  aggregateCell, buildGroups, featureLabelOf, formatDuration, isDocumented, isProbed, labelMaps, runSummary, surfaceHealth,
  surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureDef,
} from "./claudeFeatures";
```
Append at end of file:
```ts
describe("labelMaps (v2.24.0 — 카탈로그 단일 출처 라벨)", () => {
  const catalog = {
    features: [
      { id: "a", group: "core", label_ko: "가", label_en: "A", desc_ko: "", desc_en: "", doc_url: "u", documented: {}, verification: "evidence", notes: "" },
      { id: "b", group: "core", label_ko: "", label_en: "", desc_ko: "", desc_en: "", doc_url: "u", documented: {}, verification: "evidence", notes: "" },
    ] as FeatureDef[],
    surfaces: [{ id: "bedrock_messages", label: "Bedrock runtime · Messages API", short: "Messages API", group: "bedrock", region: "us-east-1" }],
  };
  test("ko/en feature labels and surface short names from the catalog; empty label falls back to id", () => {
    const ko = labelMaps(catalog, "ko");
    expect(featureLabelOf(ko, "a")).toBe("가");
    expect(featureLabelOf(labelMaps(catalog, "en"), "a")).toBe("A");
    expect(featureLabelOf(ko, "b")).toBe("b");
    expect(surfaceShortOf(ko, "bedrock_messages")).toBe("Messages API");
  });
  test("unknown id and null catalog fall back to the raw id (catalog not loaded yet)", () => {
    expect(featureLabelOf(labelMaps(catalog, "ko"), "zzz")).toBe("zzz");
    const empty = labelMaps(null, "ko");
    expect(featureLabelOf(empty, "a")).toBe("a");
    expect(surfaceShortOf(empty, "mantle")).toBe("mantle");
  });
});
```

- [ ] **Step 2: Run — expect failure**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
Expected: 2 new tests fail with `TypeError: labelMaps is not a function`; the other 19 in this file pass.

- [ ] **Step 3: Implement the lib helpers**

Append to `claudeFeatures.ts`:
```ts

// ── v2.24.0 — 배너·모달·드로어 공용 라벨 맵 (D2, RUL-6): 카탈로그 label_ko/en + surface short 단일 출처, 미로드 시 id 폴백 ──
export interface LabelMaps { featureLabel: Map<string, string>; surfaceShort: Map<string, string> }

export function labelMaps(catalog: { features: FeatureDef[]; surfaces: SurfaceDef[] } | null | undefined, lang: string): LabelMaps {
  const featureLabel = new Map<string, string>();
  const surfaceShort = new Map<string, string>();
  for (const f of catalog?.features ?? []) featureLabel.set(f.id, (lang === "en" ? f.label_en : f.label_ko) || f.id);
  for (const s of catalog?.surfaces ?? []) surfaceShort.set(s.id, s.short || s.id);
  return { featureLabel, surfaceShort };
}
export function featureLabelOf(maps: LabelMaps, id: string): string { return maps.featureLabel.get(id) ?? id; }
export function surfaceShortOf(maps: LabelMaps, id: string): string { return maps.surfaceShort.get(id) ?? id; }
```
Run `cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts` → 21 passed.

- [ ] **Step 4: Wire the panel**

(a) Import block (as left by Task 7) — add the four symbols:
```tsx
import {
  aggregateCell, buildGroups, cellBadge, featureLabelOf, formatDuration, labelMaps, runSummary, surfaceShortOf, surfaceSummary, visibleSegments,
  DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type LabelMaps, type RowView, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```

(b) CF:25 — replace
```tsx
function EvidenceModal({ runId, cell, onClose }: { runId: number; cell: FeatureCell; onClose: () => void }) {
```
with
```tsx
function EvidenceModal({ runId, cell, labels, onClose }: { runId: number; cell: FeatureCell; labels: LabelMaps; onClose: () => void }) {
```

(c) CF:75-76 — replace
```tsx
          <h2 className="text-base font-bold text-gray-100 font-mono mt-0.5">{cell.feature} · {cell.surface} · {cell.model_label}</h2>
          <div className="text-xs text-gray-500 mt-0.5 font-mono">{cell.model_id ?? "—"}</div>
```
with (title = human labels, subtitle = raw ids in mono — parity PP:318/320 pattern, one step further with the feature label per verify-C10)
```tsx
          <h2 className="text-base font-bold text-gray-100 mt-0.5">{featureLabelOf(labels, cell.feature)} · {surfaceShortOf(labels, cell.surface)} · {cell.model_label}</h2>
          <div className="text-xs text-gray-500 mt-0.5 font-mono">{cell.feature} · {cell.surface} · {cell.model_id ?? "—"}</div>
```

(d) CF:82 — replace
```tsx
            <span className={`text-xs ${VERDICT_STYLE[cell.verdict]}`}>verdict: {cell.verdict}</span>
```
with
```tsx
            <span className={`text-xs ${VERDICT_STYLE[cell.verdict]}`}>{lang === "en" ? "verdict" : "판정"}: {cell.verdict}</span>
```

(e) CF:170 — after
```tsx
  const surfaces = useMemo(() => catalog?.surfaces.map((s) => s.id) ?? [], [catalog]);
```
add
```tsx
  const labels = useMemo(() => labelMaps(catalog, lang), [catalog, lang]);
```

(f) CF:219-225 drift banner items — replace
```tsx
            {drift.slice(0, 10).map((c) => (
              <li key={`${c.feature}|${c.surface}|${c.model_key}`} className="flex items-center gap-2 flex-wrap">
                <button type="button" onClick={() => setSelected(c)} className="font-mono text-rose-200 hover:underline">{c.feature}</button>
                <span className="text-gray-500">{c.surface} · {c.model_label}</span>
                <span className="text-gray-600">documented {DOC_LABEL[c.documented]} → observed</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.status]}`}>{STATUS_LABEL[c.status]}</span>
              </li>
            ))}
```
with
```tsx
            {drift.slice(0, 10).map((c) => (
              <li key={`${c.feature}|${c.surface}|${c.model_key}`} className="flex items-center gap-2 flex-wrap">
                <button type="button" onClick={() => setSelected(c)} className="text-rose-200 hover:underline">{featureLabelOf(labels, c.feature)}</button>
                <span className="font-mono text-[10px] text-gray-600">{c.feature}</span>
                <span className="text-gray-500">{surfaceShortOf(labels, c.surface)}, {c.model_label}</span>
                <span className="text-gray-600">{L(`documented ${DOC_LABEL[c.documented]} → observed`, `문서 ${DOC_LABEL[c.documented]} → 실측`)}</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.status]}`}>{STATUS_LABEL[c.status]}</span>
              </li>
            ))}
```

(g) CF:369 — replace
```tsx
      {selected && run && <EvidenceModal runId={run.id} cell={selected} onClose={() => setSelected(null)} />}
```
with
```tsx
      {selected && run && <EvidenceModal runId={run.id} cell={selected} labels={labels} onClose={() => setSelected(null)} />}
```

- [ ] **Step 5: Typecheck + tests**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && echo TSC-OK && npx vitest run 2>&1 | tail -4
```
Expected: `TSC-OK`, `Tests 60 passed (60)`. Visual (run #3 data): drift banner rows read `기본 응답  messages_basic  Mantle, Claude Fable 5  문서 GA → 실측 [Unsupported]`; modal title `데이터 레지던시 (inference_geo) · Converse · Claude Fable 5`, subtitle `data_residency · bedrock_converse · anthropic.claude-fable-5…`.

- [ ] **Step 6: Commit**
```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "feat(features): 카탈로그 단일 출처 라벨 맵(labelMaps) — 드리프트 배너·증거 모달 제목에 피처/surface 표시명, 원시 id는 mono 보조 표기, 판정 라벨 i18n (C3/C10, D2, RUL-6)"
```

---

### Task 9: Changes banner completeness — "외 N건", "변경 없음" card, clickable items, 6-state pill, `kind` tag + summary; drift-zero card (D3-frontend, RUL-1, RUL-4, critic 4-A; C5/R5)

**Implements:** verify-C5.md (banner completeness incl. §4.2 negative-result cards), verify-R5.md frontend side (`kind` tag + summary), critic §4-A (`after` pill uses 6-state `STATUS_STYLE` — today `not_applicable` renders amber via the 3-way ternary at CF:237), D3-frontend, RUL-1 (drift-zero card "문서 드리프트 없음."), RUL-4 (`kind` optional — renders correctly against pre-v2.24 payloads). Bundle frontend-A T4.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — `FeatureChange` gains `kind?: ChangeKind` (CFL:23-26); append `ChangeKind`, `CHANGE_KIND_LABEL`, `ChangeSummary`, `summarizeChanges()`, `findCell()`.
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx`
  - import block — add `findCell, summarizeChanges, CHANGE_KIND_LABEL`
  - after the `labels` memo (Task 8) — add `changeSummary` memo
  - after the drift banner block (CF:213-230) — add the drift-zero card (RUL-1)
  - CF:231-242 — replace the changes banner block
- Test: `claudeFeatures.test.ts` — extend import, append `describe("summarizeChanges / findCell", …)`.

**Interfaces:**
- Consumes: `FeaturesLatest` (`api.ts:861-864`: `previous_run_id: number | null; changes: FeatureChange[]; results: FeatureCell[]`); backend `build_latest_payload` (`backend/routers/features.py:40-62`) — `changes[]` items are `{feature, surface, model_key, model_label, before, after}` today; Task 5 adds `kind`. `STATUS_STYLE`/`STATUS_LABEL` (CFL:28-41) — 6-state pill. `labels` memo + `featureLabelOf`/`surfaceShortOf` (Task 8).
- Produces:
  ```ts
  export type ChangeKind = "catalog" | "measured";
  export interface FeatureChange { feature: string; surface: string; model_key: string; model_label: string; before: FeatureStatus | null; after: FeatureStatus; kind?: ChangeKind }
  export const CHANGE_KIND_LABEL: Record<ChangeKind, { en: string; ko: string }>;
  export interface ChangeSummary { total: number; catalog: number; measured: number; untagged: number }
  export function summarizeChanges(changes: FeatureChange[]): ChangeSummary;
  export function findCell(cells: FeatureCell[], ref: { feature: string; surface: string; model_key: string }): FeatureCell | null;
  ```
  Panel: `const changeSummary = useMemo(() => summarizeChanges(latest?.changes ?? []), [latest]);` (Task 13 re-points it at the model-filtered `visibleChanges`).

- [ ] **Step 1: Write the failing tests**

Extend the test import to
```ts
import {
  aggregateCell, buildGroups, featureLabelOf, findCell, formatDuration, isDocumented, isProbed, labelMaps, runSummary, summarizeChanges,
  surfaceHealth, surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureChange, type FeatureDef,
} from "./claudeFeatures";
```
Append:
```ts
describe("summarizeChanges / findCell (v2.24.0 변경 배너)", () => {
  const ch = (p: Partial<FeatureChange>): FeatureChange => ({
    feature: "f", surface: "cp", model_key: "opus-5", model_label: "Opus 5", before: "unsupported", after: "not_applicable", ...p,
  });
  test("counts catalog / measured / untagged (kind absent on pre-v2.24 payloads)", () => {
    expect(summarizeChanges([ch({ kind: "catalog" }), ch({ kind: "catalog", model_key: "sonnet-5" }), ch({ kind: "measured", feature: "g" }), ch({ feature: "h" })]))
      .toEqual({ total: 4, catalog: 2, measured: 1, untagged: 1 });
    expect(summarizeChanges([])).toEqual({ total: 0, catalog: 0, measured: 0, untagged: 0 });
  });
  test("findCell resolves a change to its result cell by (feature, surface, model_key); null when absent", () => {
    const cells = [
      cell({ feature: "f", surface: "cp", model_key: "opus-5" }),
      cell({ feature: "f", surface: "cp", model_key: "sonnet-5", status: "unsupported", verdict: "drift" }),
    ];
    expect(findCell(cells, ch({ model_key: "sonnet-5" }))?.status).toBe("unsupported");
    expect(findCell(cells, ch({ model_key: "opus-5" }))?.status).toBe("supported");
    expect(findCell(cells, ch({ surface: "mantle" }))).toBeNull();
  });
});
```

- [ ] **Step 2: Run — expect failure**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
Expected: 2 new tests fail with `TypeError: summarizeChanges is not a function` / `TypeError: findCell is not a function`.

- [ ] **Step 3: Implement the lib part**

Replace CFL:23-26
```ts
export interface FeatureChange {
  feature: string; surface: string; model_key: string; model_label: string;
  before: FeatureStatus | null; after: FeatureStatus;
}
```
with
```ts
// kind (v2.24.0, 백엔드 D3/RUL-11): "catalog" = 직전 런에 없던 셀, 또는 before/after 중 하나가 사전판정 행(latency_ms IS NULL —
// 러너가 not_applicable/skipped로 결정), "measured" = 둘 다 프로브 결과. 구 페이로드에는 없으므로 optional(RUL-4) —
// 태그·요약 줄은 kind가 있을 때만 렌더.
export type ChangeKind = "catalog" | "measured";
export interface FeatureChange {
  feature: string; surface: string; model_key: string; model_label: string;
  before: FeatureStatus | null; after: FeatureStatus; kind?: ChangeKind;
}
```
Append at end of file:
```ts

// ── v2.24.0 — 변경 배너 (D3): kind 요약 + 변경 항목 → 증거 모달용 셀 조회 ─────────────────────────────
export const CHANGE_KIND_LABEL: Record<ChangeKind, { en: string; ko: string }> = {
  catalog: { en: "catalog rule", ko: "카탈로그 규칙" }, measured: { en: "measured", ko: "실측" },
};
export interface ChangeSummary { total: number; catalog: number; measured: number; untagged: number }

export function summarizeChanges(changes: FeatureChange[]): ChangeSummary {
  const out: ChangeSummary = { total: changes.length, catalog: 0, measured: 0, untagged: 0 };
  for (const c of changes) {
    if (c.kind === "catalog") out.catalog += 1;
    else if (c.kind === "measured") out.measured += 1;
    else out.untagged += 1;
  }
  return out;
}

/** 변경 항목(FeatureChange)은 status/documented/verdict가 없어 그대로 모달을 열 수 없다 → latest.results에서 같은 (feature, surface, model_key) 셀을 찾는다. */
export function findCell(cells: FeatureCell[], ref: { feature: string; surface: string; model_key: string }): FeatureCell | null {
  return cells.find((c) => c.feature === ref.feature && c.surface === ref.surface && c.model_key === ref.model_key) ?? null;
}
```
Run `cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts` → 23 passed.

- [ ] **Step 4: Wire the panel**

(a) Import block — add `findCell`, `summarizeChanges`, `CHANGE_KIND_LABEL`:
```tsx
import {
  aggregateCell, buildGroups, cellBadge, featureLabelOf, findCell, formatDuration, labelMaps, runSummary, summarizeChanges, surfaceShortOf, surfaceSummary, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type LabelMaps, type RowView, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```

(b) After `const labels = useMemo(…)` (Task 8) add
```tsx
  const changeSummary = useMemo(() => summarizeChanges(latest?.changes ?? []), [latest]);
```

(c) RUL-1 — immediately after the drift banner block's closing `)}` (the block starting `{/* 드리프트 배너 */}` at CF:212-230, ending with `</div>\n      )}`), insert:
```tsx
      {/* 드리프트 0건도 명시한다 (RUL-1) — "변경 없음" 카드와 같은 원칙: 음성 결과를 빈 화면이 아닌 문장으로 */}
      {run && drift.length === 0 && (
        <div className="px-3 py-2 bg-gray-900/50 border border-gray-800 rounded-xl text-xs text-gray-500">
          {L("No documentation drift.", "문서 드리프트 없음.")}
        </div>
      )}
```

(d) Replace the changes banner block CF:231-242 (currently:
```tsx
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
```
) with
```tsx
      {/* 이전 런 대비 변경 (v2.24.0, D3) — previous_run_id가 있으면 항상 렌더: 목록(10건 초과 '외 N건') 또는 '변경 없음' 카드.
          항목 클릭 → latest.results에서 셀을 찾아 증거 모달. after는 6상태 STATUS_STYLE pill (critic 4-A: N/A가 amber로 찍히던 문제).
          kind 태그(카탈로그 규칙/실측)와 요약 줄은 백엔드가 kind를 내려줄 때만 표시 (RUL-4). */}
      {run && latest && latest.changes.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-gray-300">
          <div className="text-sm font-semibold text-amber-300 mb-1">{L(`Changes since run #${latest.previous_run_id}: ${latest.changes.length}`, `이전 런(#${latest.previous_run_id}) 대비 변경 ${latest.changes.length}건`)}</div>
          {changeSummary.catalog + changeSummary.measured > 0 && (
            <div className="text-[11px] text-gray-400 mb-2">
              {L(`Catalog rule changes ${changeSummary.catalog}, measured changes ${changeSummary.measured}`, `카탈로그 규칙 변경 ${changeSummary.catalog}건, 실측 변경 ${changeSummary.measured}건`)}
            </div>
          )}
          <ul className="space-y-1">
            {latest.changes.slice(0, 10).map((c) => {
              const target = findCell(cells, c);
              return (
                <li key={`${c.feature}|${c.surface}|${c.model_key}`} className="flex items-center gap-2 flex-wrap">
                  {c.kind && (
                    <span className={`px-1.5 py-px text-[10px] rounded ${c.kind === "catalog" ? "bg-sky-500/10 text-sky-300" : "bg-gray-800 text-gray-400"}`}>{CHANGE_KIND_LABEL[c.kind][lang]}</span>
                  )}
                  <button type="button" disabled={!target} onClick={() => target && setSelected(target)}
                          className={target ? "text-amber-100 hover:underline" : "text-gray-400 cursor-default"}>
                    {featureLabelOf(labels, c.feature)}
                  </button>
                  <span className="font-mono text-[10px] text-gray-600">{c.feature}</span>
                  <span className="text-gray-500">{surfaceShortOf(labels, c.surface)}, {c.model_label}:</span>
                  <span className={c.before ? "text-gray-300" : "text-gray-500"}>{c.before ? STATUS_LABEL[c.before] : L("new", "신규")}</span>
                  <span className="text-gray-500">→</span>
                  <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.after]}`}>{STATUS_LABEL[c.after]}</span>
                </li>
              );
            })}
            {latest.changes.length > 10 && <li className="text-gray-500">{L(`+${latest.changes.length - 10} more`, `외 ${latest.changes.length - 10}건`)}</li>}
          </ul>
        </div>
      )}
      {run && latest && latest.previous_run_id != null && latest.changes.length === 0 && (
        <div className="px-3 py-2 bg-gray-900/50 border border-gray-800 rounded-xl text-xs text-gray-500">
          {L(`No changes since run #${latest.previous_run_id}.`, `이전 런(#${latest.previous_run_id}) 대비 변경 없음.`)}
        </div>
      )}
```

- [ ] **Step 5: Typecheck + tests**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && npx vitest run 2>&1 | tail -4
```
Expected: tsc clean, `Tests 62 passed (62)`. Visual (run #3: 15 changes, all `data_residency unsupported → not_applicable`): list shows 10 rows `데이터 레지던시 (inference_geo)  data_residency  Converse, Claude Fable 5:  Unsupported → [N/A gray pill]` plus `외 5건`; clicking a row opens the evidence modal for that cell; with the Task 5 backend deployed each row gets a sky `카탈로그 규칙` tag and the header line `카탈로그 규칙 변경 15건, 실측 변경 0건`. When a run completes with 0 changes, the gray card `이전 런(#N) 대비 변경 없음.` appears instead of nothing; when drift is 0 the gray card `문서 드리프트 없음.` appears where the rose banner would be.

- [ ] **Step 6: Commit**
```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "feat(features): 변경 배너 완결성 — '외 N건', '이전 런 대비 변경 없음'·'문서 드리프트 없음' 카드, 항목 클릭→증거 모달, after 6상태 pill(N/A amber 오표기 수정), kind 태그+카탈로그/실측 요약 (C5/R5, D3, RUL-1, critic 4-A)"
```

---

### Task 10: Filter forces groups open + expand/collapse-all (D7, RUL-8; C7-a, C7 buttons)

**Implements:** verify-C7.md §2 (collapse → drift filter hides matching rows — a friction bug), §5.3 (collapsed-Set direction), D7, RUL-8 (`filterActive = filter !== "all"` only — the Task 13 model chip does not force groups open). Bundle frontend-A T5.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — append `isGroupOpen()`.
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx`
  - import block — add `isGroupOpen`
  - after `const [collapsed, setCollapsed] = …` (CF:154) — add `filterActive`
  - CF:270-280 filter bar — add expand/collapse-all buttons (only when `!filterActive`)
  - CF:302-308 group header row — `open` via `isGroupOpen`, toggle disabled + cursor/hover + chevron hidden when `filterActive`
- Test: `claudeFeatures.test.ts` — extend import, append `describe("isGroupOpen", …)`.

**Interfaces:**
- Consumes: `filter` state `CellStatus | "all" | "drift"` (CF:151); `collapsed: Set<string>` keyed by `GroupView.id` (CF:154, CF:305); `groups: GroupView[]` (CF:172-175 — `buildGroups` already drops groups with no matching rows, CFL:115).
- Produces: `export function isGroupOpen(filterActive: boolean, collapsed: Set<string>, groupId: string): boolean` (= `filterActive || !collapsed.has(groupId)`), and `const filterActive = filter !== "all";` in the panel (RUL-8 — Task 13 must NOT extend this). Set direction note (verify-C7 §5.3): this panel keeps a **collapsed** Set, so "모두 펼치기" = `new Set()` and "모두 접기" = `new Set(groups.map((g) => g.id))` — the reverse of parity's expanded Set (PP:661/667); do not copy parity literally.

- [ ] **Step 1: Write the failing test**

Extend the test import with `isGroupOpen`:
```ts
import {
  aggregateCell, buildGroups, featureLabelOf, findCell, formatDuration, isDocumented, isGroupOpen, isProbed, labelMaps, runSummary,
  summarizeChanges, surfaceHealth, surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureChange, type FeatureDef,
} from "./claudeFeatures";
```
Append:
```ts
describe("isGroupOpen (v2.24.0 — 필터 활성 시 강제 펼침)", () => {
  test("no filter: open unless the user collapsed the group", () => {
    const collapsed = new Set(["model"]);
    expect(isGroupOpen(false, collapsed, "core")).toBe(true);
    expect(isGroupOpen(false, collapsed, "model")).toBe(false);
  });
  test("active filter forces every group open, even one collapsed earlier (collapse → drift filter regression)", () => {
    expect(isGroupOpen(true, new Set(["model"]), "model")).toBe(true);
    expect(isGroupOpen(true, new Set(), "core")).toBe(true);
  });
});
```

- [ ] **Step 2: Run — expect failure**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
Expected: 2 new tests fail with `TypeError: isGroupOpen is not a function`.

- [ ] **Step 3: Implement the lib helper**

Append to `claudeFeatures.ts`:
```ts

// ── v2.24.0 — 그룹 접기 (D7): 상태/드리프트 필터가 켜져 있으면 접힘 상태를 무시하고 전부 펼친다 (parity PP:469-470 규칙).
//   collapsed는 "접힌 그룹" Set(펼침 Set이 아님) — 모두 펼치기 = new Set(), 모두 접기 = 모든 g.id.
export function isGroupOpen(filterActive: boolean, collapsed: Set<string>, groupId: string): boolean {
  return filterActive || !collapsed.has(groupId);
}
```
Run `cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts` → 25 passed.

- [ ] **Step 4: Wire the panel**

(a) Import block — add `isGroupOpen` (alphabetical slot after `formatDuration`):
```tsx
import {
  aggregateCell, buildGroups, cellBadge, featureLabelOf, findCell, formatDuration, isGroupOpen, labelMaps, runSummary, summarizeChanges, surfaceShortOf, surfaceSummary, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type LabelMaps, type RowView, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```

(b) After CF:154
```tsx
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
```
add
```tsx
  // 필터가 켜져 있으면 접힘을 무시하고 전부 펼침 (D7). 모델 칩(D5)은 행을 숨기지 않으므로 여기에 포함하지 않는다 (RUL-8).
  const filterActive = filter !== "all";
```

(c) CF:278 — after
```tsx
          <span className="text-xs text-gray-500 ml-2">{groups.reduce((n, g) => n + g.rows.length, 0)} {L("features", "피처")}</span>
```
add (inside the same flex container, before its closing `</div>`)
```tsx
          {!filterActive && (
            <div className="flex gap-1 ml-auto">
              <button type="button" onClick={() => setCollapsed(new Set())}
                      className="px-2 py-1 text-[11px] rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300">
                {L("Expand all", "모두 펼치기")}
              </button>
              <button type="button" onClick={() => setCollapsed(new Set(groups.map((g) => g.id)))}
                      className="px-2 py-1 text-[11px] rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300">
                {L("Collapse all", "모두 접기")}
              </button>
            </div>
          )}
```

(d) CF:302-308 — replace
```tsx
                const open = !collapsed.has(g.id);
                return (
                  <Fragment key={g.id}>
                    <tr onClick={() => setCollapsed((c) => { const n = new Set(c); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n; })}
                        className="border-t-2 border-t-gray-700 bg-gray-900/80 light:bg-gray-50 cursor-pointer hover:bg-gray-800/60">
                      <td className="px-3 py-2 sticky left-0 bg-gray-900 light:bg-white" colSpan={1}>
                        <span className={`text-[10px] text-gray-500 inline-block mr-2 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
```
with
```tsx
                const open = isGroupOpen(filterActive, collapsed, g.id);
                return (
                  <Fragment key={g.id}>
                    <tr onClick={() => { if (filterActive) return; setCollapsed((c) => { const n = new Set(c); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n; }); }}
                        className={`border-t-2 border-t-gray-700 bg-gray-900/80 light:bg-gray-50 ${filterActive ? "" : "cursor-pointer hover:bg-gray-800/60"}`}>
                      <td className="px-3 py-2 sticky left-0 bg-gray-900 light:bg-white" colSpan={1}>
                        {!filterActive && <span className={`text-[10px] text-gray-500 inline-block mr-2 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>}
```
(The `{open && g.rows.map(…)}` at CF:314 is unchanged — it now reads the forced-open value.)

- [ ] **Step 5: Typecheck + tests**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && npx vitest run 2>&1 | tail -4
```
Expected: tsc clean, `Tests 64 passed (64)`. Manual regression (verify-C7 §2 repro): collapse `모델 기능`, click the `드리프트` filter → the group is shown expanded with its drift rows (7 in run #3), header has no chevron and no pointer cursor; click `전체` → group returns to collapsed; `모두 펼치기`/`모두 접기` visible only while `전체` is selected.

- [ ] **Step 6: Commit**
```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "fix(features): 상태/드리프트 필터 활성 시 접힌 그룹 강제 펼침(토글 무효, chevron 숨김) + 모두 펼치기/모두 접기 — 접기 후 필터 시 매칭 행이 가려지던 마찰 결함 (C7-a/C7, D7, RUL-8)"
```

---

### Task 11: `surfaceFindings()` — 드로어 6섹션 파생 순수 함수 + vitest (D4, RUL-7; C1/R3)

**Implements:** verify-C1.md §3 (verdict-axis adaptation, correction A "unsupported && none 4셀 귀속"), verify-R3.md corrections 1-3 (Mantle ratio at cell level, unknown-unsupported as its own section, probed=0 model guard), D4, RUL-7 (imports `isProbed`/`isDocumented`/`PROBED_STATUSES` from Task 6 — **no redefinition**). Bundle frontend-B T1.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — append at end of file (after Task 10 additions)
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — extend import (`surfaceFindings`, `type ModelDef`), append `describe("surfaceFindings")`

**Interfaces:**

Consumes (existing, `claudeFeatures.ts`):
```ts
export interface FeatureCell { feature: string; surface: string; model_key: string; model_label: string; model_id: string | null;
  status: FeatureStatus; documented: Documented; verdict: Verdict; latency_ms: number | null }   // :8-11
export interface ModelDef { key: string; label: string; cp: string; mantle: string | null; bedrock: string; mantle_reason?: string }  // :18
isProbed(status), isDocumented(documented)   // Task 6 (RUL-7)
```

Produces (new exports):
```ts
export interface FindingFeatureGroup { feature: string; count: number; probed: number; models: string[]; cells: FeatureCell[] }
export interface FindingChip { feature: string; models: string[]; cells: FeatureCell[] }
export interface ModelDocHealth { model_key: string; model_label: string; supported: number; probed: number;
  docHealth: number | null; drift: number; na_reason: string | null }
export interface SurfaceFindings {
  surface: string; total: number;
  drift: FindingFeatureGroup[];      // (1) verdict === "drift", 피처별, count desc → feature asc
  broken: FindingFeatureGroup[];     // (2) status === "broken", verdict 무관
  intendedGaps: FindingChip[];       // (3) status unsupported && verdict match, 피처 고유
  undecidedGaps: FindingChip[];      // (4) status unsupported && verdict none (documented unknown)
  undocumented: FindingChip[];       // (5) verdict === "undocumented", 피처 고유
  perModel: ModelDocHealth[];        // (6) 카탈로그 models 전부, 카탈로그 순서
}
export function surfaceFindings(cells: FeatureCell[], surface: string, models: ModelDef[], lang: string): SurfaceFindings;
```

의미 규칙(테스트가 고정):
- `probed`(그룹) = 해당 피처·surface에서 `isProbed(status)`인 셀 수(N/A·skipped 제외 — 라이브 Mantle은 Fable 5.1이 전부 N/A라 최대 3, verify-R3 보정 1).
- `docHealth`(모델) = `isDocumented` **이면서** `isProbed`인 셀 중 supported 비율 `Math.round(100*supported/probed)`; `probed === 0`이면 `null`(D1 공식과 동일, verify-R3 보정 3).
- `na_reason` = `surface === "mantle" && m.mantle === null`일 때만 non-null: `lang === "en"`이면 고정 영문(기존 참조 노트 CF:347 문장 재사용), 아니면 `m.mantle_reason ?? "측정 불가"`.
- 다른 surface의 셀은 무시. `total`은 이 surface 셀 전부(N/A 포함).

- [ ] **Step 1: 실패 테스트 작성**

`claudeFeatures.test.ts` import를 다음으로 교체(Task 10 상태 + `surfaceFindings`, `type ModelDef`):
```ts
import {
  aggregateCell, buildGroups, featureLabelOf, findCell, formatDuration, isDocumented, isGroupOpen, isProbed, labelMaps, runSummary,
  summarizeChanges, surfaceFindings, surfaceHealth, surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureChange, type FeatureDef, type ModelDef,
} from "./claudeFeatures";
```
파일 끝에 추가:
```ts
describe("surfaceFindings", () => {
  const models: ModelDef[] = [
    { key: "fable-5-1", label: "Claude Fable 5.1", cp: "claude-fable-5-1", mantle: null, bedrock: "global.anthropic.claude-fable-5-1",
      mantle_reason: "측정 불가 — GovCloud 전용" },
    { key: "fable-5", label: "Claude Fable 5", cp: "claude-fable-5", mantle: "anthropic.claude-fable-5", bedrock: "global.anthropic.claude-fable-5" },
    { key: "opus-5", label: "Claude Opus 5", cp: "claude-opus-5", mantle: "anthropic.claude-opus-5", bedrock: "global.anthropic.claude-opus-5" },
  ];
  const mantle = (p: Partial<FeatureCell>) => cell({ surface: "mantle", ...p });
  const cells: FeatureCell[] = [
    // messages_basic: Fable 5.1 N/A, Fable 5 drift, Opus 5 ok
    mantle({ feature: "messages_basic", model_key: "fable-5-1", model_label: "Claude Fable 5.1", model_id: null, status: "not_applicable", verdict: "none", latency_ms: null }),
    mantle({ feature: "messages_basic", model_key: "fable-5", model_label: "Claude Fable 5", status: "unsupported", verdict: "drift" }),
    mantle({ feature: "messages_basic", model_key: "opus-5", model_label: "Claude Opus 5" }),
    // fallback_credit (documented beta): 두 모델 모두 drift
    mantle({ feature: "fallback_credit", model_key: "fable-5", model_label: "Claude Fable 5", documented: "beta", status: "unsupported", verdict: "drift" }),
    mantle({ feature: "fallback_credit", model_key: "opus-5", model_label: "Claude Opus 5", documented: "beta", status: "unsupported", verdict: "drift" }),
    // batch_processing (documented no): 의도된 격차
    mantle({ feature: "batch_processing", model_key: "fable-5", model_label: "Claude Fable 5", documented: "no", status: "unsupported", verdict: "match" }),
    mantle({ feature: "batch_processing", model_key: "opus-5", model_label: "Claude Opus 5", documented: "no", status: "unsupported", verdict: "match" }),
    // strict_tool_use (documented unknown): 문서 미확정
    mantle({ feature: "strict_tool_use", model_key: "opus-5", model_label: "Claude Opus 5", documented: "unknown", status: "unsupported", verdict: "none" }),
    // browser_use (documented no, supported): 문서에 없는 동작
    mantle({ feature: "browser_use", model_key: "opus-5", model_label: "Claude Opus 5", documented: "no", status: "supported", verdict: "undocumented" }),
    // pdf_support (documented no, broken → verdict none): 프로브 오류 섹션에는 status 기준으로 잡혀야 함
    mantle({ feature: "pdf_support", model_key: "opus-5", model_label: "Claude Opus 5", documented: "no", status: "broken", verdict: "none" }),
    // 다른 surface — 무시돼야 함
    cell({ feature: "messages_basic", surface: "cp", status: "unsupported", verdict: "drift" }),
  ];
  // lazy: describe 스코프에서 직접 호출하면 구현 전(import가 undefined) TypeError가 수집 단계에서 나 파일 전체가 `Failed Suites 1`로
  // 죽는다(기존 25건도 실행되지 않음). 각 test 안에서 호출해야 red 단계가 "6건 실패, 25건 통과"로 나온다.
  const findings = () => surfaceFindings(cells, "mantle", models, "ko");

  test("drift grouped by feature, count desc then id asc; probed excludes N/A", () => {
    const f = findings();
    expect(f.drift.map((g) => [g.feature, g.count, g.probed])).toEqual([["fallback_credit", 2, 2], ["messages_basic", 1, 2]]);
    expect(f.drift[1].models).toEqual(["Claude Fable 5"]);
    expect(f.drift[0].cells.map((c) => c.model_key)).toEqual(["fable-5", "opus-5"]);
  });
  test("broken is status-based: documented no + broken (verdict none) is still listed", () => {
    const f = findings();
    expect(f.broken.map((g) => [g.feature, g.count, g.probed])).toEqual([["pdf_support", 1, 1]]);
  });
  test("intended / undecided / undocumented buckets are disjoint and unique per feature", () => {
    const f = findings();
    expect(f.intendedGaps.map((c) => c.feature)).toEqual(["batch_processing"]);
    expect(f.intendedGaps[0].models).toEqual(["Claude Fable 5", "Claude Opus 5"]);
    expect(f.undecidedGaps.map((c) => c.feature)).toEqual(["strict_tool_use"]);
    expect(f.undocumented.map((c) => c.feature)).toEqual(["browser_use"]);
  });
  test("perModel: docHealth = supported/probed among documented ga|beta, null when probed 0, mantle=null → na_reason", () => {
    const f = findings();
    expect(f.perModel.map((m) => m.model_key)).toEqual(["fable-5-1", "fable-5", "opus-5"]);
    const by = Object.fromEntries(f.perModel.map((m) => [m.model_key, m]));
    expect(by["fable-5-1"]).toMatchObject({ supported: 0, probed: 0, docHealth: null, drift: 0, na_reason: "측정 불가 — GovCloud 전용" });
    // fable-5: messages_basic(ga) + fallback_credit(beta) 둘 다 unsupported; batch_processing(no)는 분모 제외
    expect(by["fable-5"]).toMatchObject({ supported: 0, probed: 2, docHealth: 0, drift: 2, na_reason: null });
    // opus-5: messages_basic(ga, supported) + fallback_credit(beta, unsupported) → 1/2; unknown/no 행은 분모 제외
    expect(by["opus-5"]).toMatchObject({ supported: 1, probed: 2, docHealth: 50, drift: 1, na_reason: null });
  });
  test("other surfaces are ignored; total counts every cell of the surface incl. N/A", () => {
    const f = findings();
    expect(f.total).toBe(10);
    expect(surfaceFindings(cells, "cp", models, "ko").drift.map((g) => g.feature)).toEqual(["messages_basic"]);
  });
  test("lang en → English na_reason; no drift → empty arrays, not undefined", () => {
    expect(surfaceFindings(cells, "mantle", models, "en").perModel[0].na_reason).toMatch(/GovCloud/);
    const empty = surfaceFindings([], "cp", models, "ko");
    expect(empty).toMatchObject({ surface: "cp", total: 0, drift: [], broken: [], intendedGaps: [], undecidedGaps: [], undocumented: [] });
    expect(empty.perModel.every((m) => m.docHealth === null && m.na_reason === null)).toBe(true);
  });
});
```

- [ ] **Step 2: 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
기대: `TypeError: surfaceFindings is not a function` (esbuild 변환은 없는 named export를 `undefined`로 통과시킴) — `surfaceFindings` describe 6건 실패, 기존 25건 통과. (호출이 `findings()` 헬퍼로 각 test 안에 있어 수집 단계는 통과한다 — describe 스코프에서 직접 호출하면 `Failed Suites 1` / `(0 test)`로 파일 전체가 실패하니 그 형태로 되돌리지 말 것.)

- [ ] **Step 3: 구현** — `claudeFeatures.ts` 파일 끝에 추가 (RUL-7: `isProbed`/`isDocumented`는 Task 6 정의를 그대로 쓴다 — 여기서 다시 선언하면 tsc 중복 export 오류)

```ts

// ── Key Findings 드로어 파생 (v2.24.0, D4) ──────────────────────────────────────────
// surface 카드 클릭 → verdict 축 6섹션. 셀(모델별 FeatureCell) 단위로 계산하므로 aggregateCell의 4모델 접기와 충돌 없음.
// 술어 isProbed/isDocumented는 위(RUL-7)의 단일 정의를 사용한다.
export interface FindingFeatureGroup { feature: string; count: number; probed: number; models: string[]; cells: FeatureCell[] }
export interface FindingChip { feature: string; models: string[]; cells: FeatureCell[] }
export interface ModelDocHealth {
  model_key: string; model_label: string;
  supported: number;         // 문서상 GA/Beta이면서 probed인 셀 중 supported
  probed: number;            // 문서상 GA/Beta이면서 probed인 셀
  docHealth: number | null;  // Math.round(100 * supported / probed), probed === 0 → null (막대 대신 "-")
  drift: number;             // verdict === "drift" 셀 수 (이 모델, 이 surface)
  na_reason: string | null;  // 이 surface에서 모델 미서빙(mantle=null)일 때만 — 막대 대신 사유 표기
}
export interface SurfaceFindings {
  surface: string; total: number;
  drift: FindingFeatureGroup[]; broken: FindingFeatureGroup[];
  intendedGaps: FindingChip[]; undecidedGaps: FindingChip[]; undocumented: FindingChip[];
  perModel: ModelDocHealth[];
}

const MANTLE_NA_EN = "Not measurable — Mantle serves this model only in US GovCloud regions (us-gov-west-1); shown as N/A.";

export function surfaceFindings(cells: FeatureCell[], surface: string, models: ModelDef[], lang: string): SurfaceFindings {
  const own = cells.filter((c) => c.surface === surface);
  const order = new Map(models.map((m, i) => [m.key, i]));
  const byModel = (a: FeatureCell, b: FeatureCell) => (order.get(a.model_key) ?? 99) - (order.get(b.model_key) ?? 99);

  const probedByFeature = new Map<string, number>();
  for (const c of own) if (isProbed(c.status)) probedByFeature.set(c.feature, (probedByFeature.get(c.feature) ?? 0) + 1);

  const bucket = (pick: (c: FeatureCell) => boolean): Map<string, FeatureCell[]> => {
    const m = new Map<string, FeatureCell[]>();
    for (const c of own) if (pick(c)) m.set(c.feature, [...(m.get(c.feature) ?? []), c]);
    return m;
  };
  const groups = (pick: (c: FeatureCell) => boolean): FindingFeatureGroup[] =>
    Array.from(bucket(pick).entries())
      .map(([feature, cs]) => {
        const sorted = [...cs].sort(byModel);
        return { feature, count: sorted.length, probed: probedByFeature.get(feature) ?? 0, models: sorted.map((c) => c.model_label), cells: sorted };
      })
      .sort((a, b) => b.count - a.count || a.feature.localeCompare(b.feature));
  const chips = (pick: (c: FeatureCell) => boolean): FindingChip[] =>
    Array.from(bucket(pick).entries()).map(([feature, cs]) => {
      const sorted = [...cs].sort(byModel);
      return { feature, models: sorted.map((c) => c.model_label), cells: sorted };
    });

  const perModel: ModelDocHealth[] = models.map((m) => {
    let supported = 0, probed = 0, drift = 0;
    for (const c of own) {
      if (c.model_key !== m.key) continue;
      if (c.verdict === "drift") drift += 1;
      if (!isDocumented(c.documented) || !isProbed(c.status)) continue;
      probed += 1;
      if (c.status === "supported") supported += 1;
    }
    const notServed = surface === "mantle" && m.mantle === null;
    return {
      model_key: m.key, model_label: m.label, supported, probed,
      docHealth: probed === 0 ? null : Math.round((100 * supported) / probed), drift,
      na_reason: notServed ? (lang === "en" ? MANTLE_NA_EN : (m.mantle_reason ?? "측정 불가")) : null,
    };
  });

  return {
    surface, total: own.length,
    drift: groups((c) => c.verdict === "drift"),
    broken: groups((c) => c.status === "broken"),
    intendedGaps: chips((c) => c.status === "unsupported" && c.verdict === "match"),
    undecidedGaps: chips((c) => c.status === "unsupported" && c.verdict === "none"),
    undocumented: chips((c) => c.verdict === "undocumented"),
    perModel,
  };
}
```

- [ ] **Step 4: 통과 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run && npx tsc --noEmit -p .
```
기대: `Tests 70 passed (70)` (64 + 6), tsc 출력 없음.

- [ ] **Step 5: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts && git commit -m "feat(features): surfaceFindings() — surface 드로어 6섹션(드리프트/프로브 오류/의도된 격차/문서 미확정/문서에 없는 동작/모델별 문서 일치율) 순수 파생 + vitest 6건 (D4, C1+R3)"
```

---

### Task 12: `SurfaceDrawer` 컴포넌트 + 헬스 카드 `<button>`화 + 마운트 (D4, RUL-6, RUL-9; C1/R3, critic 4-E)

**Implements:** verify-C1.md §4 (ParityPanel.tsx:112-265 skeleton port, :565-588 card button, item click → existing `setSelected` modal), verify-R3.md §3 corrections, critic §4-E third item (drawer subtitle keeps the "computed from" line), D4, RUL-6 (prop `labels: LabelMaps` + `featureLabelOf` — the Task 8 memo, no second map), RUL-9 (chips are `<button>`s → `onPick(chip.cells[0])`, `title` lists all models). Bundle frontend-B T2.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx`
  - `:8` react import에 `type ReactNode` 추가
  - import block(Task 10 상태)에 `surfaceFindings, type FindingChip, type FindingFeatureGroup, type SurfaceDef, type SurfaceFindings` 추가
  - `EvidenceModal` 닫는 `}`(:105) 뒤에 `SurfaceDrawer` 함수 삽입
  - state 블록(:154 `collapsed` 다음)에 `surfaceDetail` 추가
  - Task 7 헬스 카드 `<div key={s.id} …>` → `<button …>` (+ CTA 줄)
  - 모달 마운트(`{selected && run && <EvidenceModal …/>}`) **앞**에 드로어 마운트 (모달이 DOM 뒤에 와야 같은 `z-50`에서 드로어 위에 뜬다)
- Test: 컴포넌트 단위 테스트 하네스 없음 → `npx tsc --noEmit -p .` + `npx vitest run`(70 유지) + 수동 확인 체크리스트

**Interfaces:**

Consumes:
```ts
surfaceFindings(cells: FeatureCell[], surface: string, models: ModelDef[], lang: string): SurfaceFindings   // Task 11
labels: LabelMaps + featureLabelOf(labels, id)   // Task 8 memo (RUL-6)
setSelected: (c: FeatureCell | null) => void     // 기존 :152, 증거 모달
catalog.surfaces: SurfaceDef[]  // { id, label, short, group, region };  catalog.models: ModelDef[]
STATUS_STYLE.unsupported  // 의도된 격차 칩 스타일
```

Produces (파일 내부 컴포넌트, export 아님):
```ts
function SurfaceDrawer(props: {
  surface: SurfaceDef; findings: SurfaceFindings; labels: LabelMaps;
  onPick: (c: FeatureCell) => void; onClose: () => void;
}): JSX.Element
const [surfaceDetail, setSurfaceDetail] = useState<string | null>(null);   // Key Findings 드로어 대상 surface id
```

- [ ] **Step 1: import 확장**

`:8` →
```ts
import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
```
`@/lib/claudeFeatures` import 블록(Task 10 상태) →
```ts
import {
  aggregateCell, buildGroups, cellBadge, featureLabelOf, findCell, formatDuration, isGroupOpen, labelMaps, runSummary, summarizeChanges,
  surfaceFindings, surfaceShortOf, surfaceSummary, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type FindingChip, type FindingFeatureGroup, type LabelMaps, type RowView,
  type SurfaceDef, type SurfaceFindings, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```
Run `cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p .` — expected: clean (unused imports are not tsc errors under this config). JSX-only task — there is no red step; the gate is `npx tsc --noEmit -p .` clean and `npx vitest run` staying at 70 (Step 6). Keep the order Step 2 → 3 → 4: Step 4's `setSurfaceDetail` reference needs Step 3's state, so reordering to "see red" only produces a transient tsc error.

- [ ] **Step 2: `SurfaceDrawer` 작성** — `EvidenceModal` 닫는 `}`(:105) 뒤에 삽입 (ParityPanel.tsx:166-179 골격 copy-adapt)

```tsx
// Key Findings 드로어 (v2.24.0, D4) — surface 카드 클릭 → verdict 축 6섹션. 라벨은 카탈로그 LabelMaps(D2/RUL-6), 항목·칩 클릭 → 증거 모달(RUL-9).
function SurfaceDrawer({ surface, findings, labels, onPick, onClose }: {
  surface: SurfaceDef; findings: SurfaceFindings; labels: LabelMaps;
  onPick: (c: FeatureCell) => void; onClose: () => void;
}) {
  const { lang } = useLang();
  const T = (en: string, ko: string) => (lang === "en" ? en : ko);
  const label = (id: string) => featureLabelOf(labels, id);
  const none = (
    <div className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">{T("None.", "없음")}</div>
  );

  const Sec = ({ title, sub, color, empty, children }: { title: string; sub: string; color: string; empty: boolean; children: ReactNode }) => (
    <section>
      <h3 className={`text-sm font-semibold mb-1 ${color}`}>{title}</h3>
      <p className="text-[11px] text-gray-500 mb-2">{sub}</p>
      {empty ? none : children}
    </section>
  );
  const GroupCards = ({ groups, tone }: { groups: FindingFeatureGroup[]; tone: "rose" | "amber" }) => (
    <div className="space-y-2">
      {groups.map((g) => (
        <div key={g.feature} className={`rounded-lg px-3 py-2 border ${tone === "rose" ? "bg-rose-500/10 border-rose-500/20" : "bg-amber-500/10 border-amber-500/20"}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-gray-100">{label(g.feature)}</span>
            <span className={`text-xs font-semibold whitespace-nowrap ${tone === "rose" ? "text-rose-300" : "text-amber-300"}`}>{g.count}/{g.probed} {T("cells", "셀")}</span>
          </div>
          <div className="text-[11px] text-gray-500 font-mono mt-0.5">{g.feature}</div>
          <div className="flex flex-wrap gap-1 mt-1">
            {g.cells.map((c) => (
              <button key={c.model_key} type="button" onClick={() => onPick(c)} title={T("Open evidence", "증거 보기")}
                className="px-1.5 py-0.5 text-[10px] rounded border border-gray-700 text-gray-300 hover:border-blue-500/60 hover:text-blue-300">
                {c.model_label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
  // RUL-9: 칩은 button — 첫 모델의 증거 모달을 연다. title에 모델 전체 목록.
  const Chips = ({ chips, style }: { chips: FindingChip[]; style: string }) => (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((u) => (
        <button key={u.feature} type="button" onClick={() => onPick(u.cells[0])}
          title={`${u.models.join(", ")} (${T("click: evidence of the first model", "클릭: 첫 모델 증거")})`}
          className={`px-2 py-0.5 text-[11px] rounded-full border hover:border-blue-500/60 ${style}`}>
          {label(u.feature)}
        </button>
      ))}
    </div>
  );

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label="overlay" onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <aside className="absolute right-0 top-0 h-full w-full max-w-md overflow-y-auto bg-gray-900 light:bg-white border-l border-gray-800 shadow-2xl p-6 space-y-6">
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-blue-400 uppercase">Key Findings</div>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-100">{surface.label}</h2>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-200 text-xl leading-none" aria-label="close">×</button>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            <span className="font-mono">{surface.id}</span> · <span className="font-mono">{surface.region}</span> · {T(`latest run, computed from all ${findings.total} cells of this endpoint`, `최근 런 기준, 이 엔드포인트의 전체 ${findings.total}셀에서 계산`)}
          </p>
        </div>

        <Sec color="text-rose-300" empty={findings.drift.length === 0}
          title={T(`1. Documentation drift (${findings.drift.length} features)`, `1. 문서 드리프트 (${findings.drift.length}개 피처)`)}
          sub={T("Documented GA/Beta but measured unsupported or broken. Check the request snapshot in the evidence modal for a probe defect first.",
                 "문서상 GA/Beta인데 실측이 unsupported 또는 broken인 셀입니다. 증거 모달의 요청 스냅샷으로 프로브 결함 여부를 먼저 확인합니다.")}>
          <GroupCards groups={findings.drift} tone="rose" />
        </Sec>

        <Sec color="text-rose-300" empty={findings.broken.length === 0}
          title={T(`2. Probe errors (${findings.broken.length} features)`, `2. 프로브 오류 (${findings.broken.length}개 피처)`)}
          sub={T("Cells that returned an error instead of a response. Listed by status (broken) regardless of the documented expectation.",
                 "응답 대신 오류를 받은 셀입니다. 문서 기대치와 무관하게 status가 broken이면 여기에 옵니다.")}>
          <GroupCards groups={findings.broken} tone="rose" />
        </Sec>

        <Sec color="text-amber-300" empty={findings.intendedGaps.length === 0}
          title={T(`3. Intended gaps (${findings.intendedGaps.length})`, `3. 의도된 격차 (${findings.intendedGaps.length})`)}
          sub={T("Documented as unavailable and measured unsupported (not a bug).", "문서상 미제공, 실측도 미지원 (버그 아님)")}>
          <Chips chips={findings.intendedGaps} style={STATUS_STYLE.unsupported} />
        </Sec>

        <Sec color="text-gray-300" empty={findings.undecidedGaps.length === 0}
          title={T(`4. Documentation undecided (${findings.undecidedGaps.length})`, `4. 문서 미확정 (${findings.undecidedGaps.length})`)}
          sub={T("Documented expectation is unknown and the probe measured unsupported. Once the docs settle, these move to drift or intended gaps.",
                 "문서 기대치가 unknown인데 실측 미지원인 피처입니다. 문서가 확정되면 드리프트 또는 의도된 격차로 귀속됩니다.")}>
          <Chips chips={findings.undecidedGaps} style="bg-gray-800 border-gray-700 text-gray-400" />
        </Sec>

        <Sec color="text-sky-300" empty={findings.undocumented.length === 0}
          title={T(`5. Undocumented behaviour (${findings.undocumented.length})`, `5. 문서에 없는 동작 (${findings.undocumented.length})`)}
          sub={T("Not promised by the docs, yet measured supported.", "문서가 약속하지 않았지만 실측이 supported인 피처입니다.")}>
          <Chips chips={findings.undocumented} style="bg-sky-500/10 border-sky-500/30 text-sky-300" />
        </Sec>

        <section>
          <h3 className="text-sm font-semibold text-gray-200 mb-1">{T("6. Documented health per model", "6. 모델별 문서 일치율")}</h3>
          <p className="text-[11px] text-gray-500 mb-2">
            {T("Share of documented GA/Beta cells that measured supported. Models not served here show the reason instead of a bar.",
               "문서상 GA/Beta 셀 중 supported 비율입니다. 측정 불가 모델은 막대 대신 사유를 표기합니다.")}
          </p>
          <div className="space-y-1.5">
            {findings.perModel.map((m) => (
              <div key={m.model_key} className="flex items-center gap-2 text-[11px]">
                <span className="w-24 shrink-0 truncate text-gray-300">{m.model_label.replace(/^Claude /, "")}</span>
                {m.na_reason ? (
                  <span className="flex-1 text-gray-500 leading-snug">{m.na_reason}</span>
                ) : m.docHealth == null ? (
                  <span className="flex-1 text-gray-500">{T("no documented probed cells", "문서상 프로브 셀 없음")}</span>
                ) : (
                  <>
                    <div className="flex-1 h-1.5 rounded-full bg-gray-800 overflow-hidden">
                      <div className={`h-full rounded-full ${m.docHealth < 60 ? "bg-rose-400" : "bg-emerald-400"}`} style={{ width: `${m.docHealth}%` }} />
                    </div>
                    <span className="w-28 text-right text-gray-400 tabular-nums whitespace-nowrap">
                      {m.docHealth}% ({m.supported}/{m.probed}){m.drift > 0 && <span className="text-rose-300 ml-1">▲{m.drift}</span>}
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
```

- [ ] **Step 3: state 추가** — `const [collapsed, setCollapsed] = useState<Set<string>>(new Set());` 다음 줄(Task 10의 `filterActive` 주석 앞)

```ts
  const [surfaceDetail, setSurfaceDetail] = useState<string | null>(null);   // Key Findings 드로어 대상 surface id (D4)
```

- [ ] **Step 4: 헬스 카드 `<div>` → `<button>`** — Task 7 Step 5가 만든 카드 래퍼

`<div key={s.id} className="bg-gray-900/50 light:bg-white border border-gray-800 rounded-xl p-4">` →
```tsx
              <button key={s.id} type="button" onClick={() => setSurfaceDetail(s.id)}
                      className="text-left w-full bg-gray-900/50 light:bg-white border border-gray-800 hover:border-blue-500/60 rounded-xl p-4 transition-colors">
```
카드 내부(제목 줄, region, 헤드라인, HealthBar, counts 줄)는 그대로 두고, counts 줄 `</div>` 바로 뒤(닫는 태그 앞)에 CTA 한 줄을 추가하고 닫는 `</div>`를 `</button>`로 바꾼다:
```tsx
                <div className="text-[11px] text-blue-400 mt-1.5">{L("Key findings →", "상세 요약 →")}</div>
              </button>
```
(PP:565-588과 같은 구조 — 카드 내부에 다른 button이 없으므로 중첩 button은 없다.) 같은 스텝에서 Task 7이 남긴 헬스 카드 JSX 주석(`{/* 엔드포인트 헬스 카드 (v2.24.0, D1) … */}`)의 마지막 줄 뒤에 다음 한 줄을 추가한다(플랜 태스크 번호는 코드 주석에 남기지 않는다):
```tsx
          카드 전체가 <button> — 클릭 시 해당 surface의 SurfaceDrawer(D4). 내부 마크업은 카드 그대로. */}
```
(기존 마지막 줄의 ` */}`를 지우고 위 줄로 닫는다.)

- [ ] **Step 5: 드로어 마운트** — `{selected && run && <EvidenceModal … labels={labels} … />}` **바로 앞** 줄에 삽입

```tsx
      {surfaceDetail && run && catalog && (() => {
        const sdef = catalog.surfaces.find((s) => s.id === surfaceDetail);
        if (!sdef) return null;
        return (
          <SurfaceDrawer surface={sdef} findings={surfaceFindings(cells, sdef.id, catalog.models, lang)} labels={labels}
            onPick={setSelected} onClose={() => setSurfaceDetail(null)} />
        );
      })()}
```
(Task 13에서 `cells` → `visibleCells`로 교체한다.)

- [ ] **Step 6: 타입/테스트 통과 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && npx vitest run
```
기대: tsc 출력 없음, `Tests 70 passed`.

- [ ] **Step 7: 수동 확인 (optional, non-gating — `next.config.mjs` `/api/*` rewrite로 backend에 닿는 dev 서버 + 라이브 run #3 데이터 필요; 게이트는 Step 6의 `npx tsc --noEmit -p .` + `npx vitest run`만)** (`cd frontend && npm run dev` → http://localhost:3000/claude-features)

1. 5장 카드에 커서 → 테두리 파란색, "상세 요약 →" 표시. Mantle 카드 클릭 → 우측 드로어.
2. 라이브 run #3 기준 Mantle 드로어: 1. 문서 드리프트 — 22개 피처(Fable 5 ×23 + fallback_credit Opus/Sonnet ×2, `fallback_credit` 카드가 `3/3 셀`로 맨 위), 2. 프로브 오류 없음(초록), 3. 의도된 격차 13칩, 4. 문서 미확정 1칩(`strict_tool_use`), 5. 문서에 없는 동작 1칩(`browser_use`), 6. Fable 5.1 = 사유 문장, Fable 5 = 0% 로즈 막대 ▲23, Opus 5/Sonnet 5 = 97% 초록.
3. 드리프트 카드의 "Claude Fable 5" 버튼 클릭 → 증거 모달이 드로어 **위에** 뜬다(DOM 순서). 3/4/5절 칩 클릭 → 첫 모델 증거 모달(RUL-9), 칩 hover title에 모델 목록. 모달 닫기 → 드로어 유지. 오버레이 클릭 → 드로어 닫힘.
4. EN 토글 → 6개 제목/부제 영문, Fable 5.1 사유가 영문 GovCloud 문장.

- [ ] **Step 8: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "feat(features): surface 헬스 카드 클릭 → Key Findings 드로어(6섹션, 항목·칩 클릭 시 증거 모달), 카드 button화 + '상세 요약 →' CTA (D4, C1+R3, RUL-6/9)"
```

---

### Task 13: 모델 칩(전체 | Fable 5.1 | Fable 5 | Opus 5 | Sonnet 5) + `buildGroups(..., modelKey)` + 카드/배너/드로어 동일 필터 (D5, RUL-8; C4, critic 4-C)

**Implements:** verify-C4.md §4 (single cell → `cellBadge` keeps N/A and 문서상 지원 rules, `single` path opens the modal directly), §5 corrections 1-3 (`buildGroups` parameter, chip UI from `catalog.models`, drift/changes banners and health cards share the same model filter), critic §4-C (Fable 5.1 on Mantle → 39 N/A cells → card shows "-" via Task 6's `docHealth: null`), D5, RUL-8 (`filterActive` unchanged). Bundle frontend-B T3.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — `buildGroups` signature (`:81-84`), cell selection (`:100`), append `pickModel()`
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx` — state, derived memo block, banners/cards/drawer sources, chip row above the filter bar, import
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — `describe("buildGroups")` 안에 2건 추가, import에 `pickModel`

**Interfaces:**

Produces (시그니처 변경, 마지막 인자 optional이라 기존 호출 호환):
```ts
export function buildGroups(
  features: FeatureDef[], groups: FeatureGroupDef[], surfaces: string[], cells: FeatureCell[],
  lang: string, filter: CellStatus | "all" | "drift", modelKey: string | null = null,
): GroupView[]
export function pickModel<T extends { model_key: string }>(xs: T[], key: string | null): T[]   // key null → xs 그대로
```
Panel 내부:
```ts
const [modelFilter, setModelFilter] = useState<string | null>(null);   // catalog.models[].key, null = 전체 집계
const visibleCells: FeatureCell[]        // pickModel(cells, modelFilter) — 헬스 카드, 드로어
const drift: FeatureCell[]               // pickModel(latest.drift, modelFilter) — 드리프트 배너 + RUL-1 카드
const visibleChanges: FeatureChange[]    // pickModel(latest.changes, modelFilter) — 변경 배너 + changeSummary
```
`filterActive`는 Task 10 그대로 `filter !== "all"` (RUL-8). `runTotals`는 런 전체 값이라 필터와 무관.

- [ ] **Step 1: 실패 테스트** — `claudeFeatures.test.ts` import에 `pickModel` 추가:
```ts
import {
  aggregateCell, buildGroups, featureLabelOf, findCell, formatDuration, isDocumented, isGroupOpen, isProbed, labelMaps, pickModel, runSummary,
  summarizeChanges, surfaceFindings, surfaceHealth, surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureChange, type FeatureDef, type ModelDef,
} from "./claudeFeatures";
```
`describe("buildGroups")` 블록의 마지막 `test(` 뒤 — `expect(g[0].rows[0].drift).toBe(1);` 테스트의 닫는 `});` 뒤, describe의 닫는 `});` 앞(a048028 기준 :60/:61, Task 6의 import 확장(+3줄) 이후에는 :63/:64 — 텍스트 앵커로 찾을 것)에 추가:

```ts
  test("modelKey narrows every cell to that model before aggregation (single-cell badge); pickModel shares the rule", () => {
    const two = [cell({ feature: "a" }), cell({ feature: "a", model_key: "sonnet-5", model_label: "Sonnet 5", status: "unsupported", verdict: "drift" })];
    expect(buildGroups(features, groups, ["cp"], two, "ko", "all")[0].rows[0].cells.cp.status).toBe("partial");
    const only = buildGroups(features, groups, ["cp"], two, "ko", "all", "sonnet-5")[0].rows[0];
    expect(only.cells.cp).toMatchObject({ status: "unsupported", probed: 1 });
    expect(only.cells.cp.cells.map((c) => c.model_key)).toEqual(["sonnet-5"]);
    expect(only.drift).toBe(1);
    // 선택 모델에 셀이 없으면 empty (N/A 규칙은 aggregateCell이 그대로 적용)
    expect(buildGroups(features, groups, ["cp"], two, "ko", "all", "fable-5-1")[0].rows[0].cells.cp.status).toBe("empty");
    expect(pickModel(two, null)).toBe(two);
    expect(pickModel(two, "sonnet-5").map((c) => c.model_key)).toEqual(["sonnet-5"]);
    expect(pickModel(two, "fable-5-1")).toEqual([]);
  });
  test("modelKey combines with status/drift filters", () => {
    const two = [cell({ feature: "a" }), cell({ feature: "a", model_key: "sonnet-5", status: "unsupported", verdict: "drift" })];
    expect(buildGroups(features, groups, ["cp"], two, "ko", "drift", "opus-5")).toEqual([]);          // opus-5는 드리프트 없음
    expect(buildGroups(features, groups, ["cp"], two, "ko", "drift", "sonnet-5").map((g) => g.id)).toEqual(["core"]);
    expect(buildGroups(features, groups, ["cp"], two, "ko", "unsupported", "opus-5")).toEqual([]);
  });
```

- [ ] **Step 2: 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
기대: 2건 실패 — 첫 테스트는 `.toBe("partial")` 단언(현 동작)은 통과하고 그다음 `expect(only.cells.cp).toMatchObject({ status: "unsupported", probed: 1 })`에서 `toMatchObject` diff로 실패(`expected { status: 'partial', …, probed: 2, … } to match object { status: 'unsupported', probed: 1 }` — 7번째 인자가 무시돼 두 셀이 그대로 집계됨), 두 번째 `expected [ { id: 'core', … } ] to deeply equal []`. tsc는 아직 돌리지 않는다(인자 개수 초과·`pickModel` 미존재로 실패하는 것이 정상).

- [ ] **Step 3: 구현** — `claudeFeatures.ts`

`:81-84`
```ts
export function buildGroups(
  features: FeatureDef[], groups: FeatureGroupDef[], surfaces: string[], cells: FeatureCell[],
  lang: string, filter: CellStatus | "all" | "drift", modelKey: string | null = null,
): GroupView[] {
```
`:100`
```ts
        const cs = byKey.get(`${f.id}|${s}`) ?? [];
```
→
```ts
        // D5: 모델 칩 선택 시 그 모델의 셀만 집계 → 단일 셀 배지(N/A·문서상 지원 규칙은 aggregateCell/cellBadge가 그대로 적용)
        const cs = (byKey.get(`${f.id}|${s}`) ?? []).filter((c) => modelKey == null || c.model_key === modelKey);
```
파일 끝에 추가:
```ts

// ── v2.24.0 — 모델 칩 (D5): 셀·드리프트·변경 배열을 같은 규칙으로 좁힌다. key null이면 입력 그대로(참조 동일 — useMemo 안정).
export function pickModel<T extends { model_key: string }>(xs: T[], key: string | null): T[] {
  return key ? xs.filter((x) => x.model_key === key) : xs;
}
```

- [ ] **Step 4: 통과 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run && npx tsc --noEmit -p .
```
기대: `Tests 72 passed`, tsc 출력 없음.

- [ ] **Step 5: 패널 state + 파생 memo** — `ClaudeFeaturesPanel.tsx`

(a) import 블록에 `pickModel` 추가 (`labelMaps` 뒤):
```tsx
import {
  aggregateCell, buildGroups, cellBadge, featureLabelOf, findCell, formatDuration, isGroupOpen, labelMaps, pickModel, runSummary, summarizeChanges,
  surfaceFindings, surfaceShortOf, surfaceSummary, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type FindingChip, type FindingFeatureGroup, type LabelMaps, type RowView,
  type SurfaceDef, type SurfaceFindings, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```

(b) `const [filter, setFilter] = useState<CellStatus | "all" | "drift">("all");` (:151) 다음 줄:
```ts
  const [modelFilter, setModelFilter] = useState<string | null>(null);   // D5 모델 칩 (catalog.models[].key), null = 전체 집계
```

(c) 파생 블록 교체 — Task 7/8/9 이후 현재 코드:
```tsx
  const surfaces = useMemo(() => catalog?.surfaces.map((s) => s.id) ?? [], [catalog]);
  const labels = useMemo(() => labelMaps(catalog, lang), [catalog, lang]);
  const changeSummary = useMemo(() => summarizeChanges(latest?.changes ?? []), [latest]);
  const cells = latest?.results ?? [];
  const groups = useMemo(
    () => (catalog ? buildGroups(catalog.features, catalog.groups, surfaces, cells, lang, filter) : []),
    [catalog, surfaces, cells, lang, filter],
  );
  const run = latest?.run ?? null;
  const drift = latest?.drift ?? [];
  const runTotals = runSummary(run?.totals);
  const duration = formatDuration(run?.started_at ?? null, run?.finished_at ?? null, lang);
```
→
```tsx
  const surfaces = useMemo(() => catalog?.surfaces.map((s) => s.id) ?? [], [catalog]);
  const labels = useMemo(() => labelMaps(catalog, lang), [catalog, lang]);
  const cells = latest?.results ?? [];
  // D5 모델 칩: 셀·드리프트·변경을 같은 규칙으로 좁힌다 (null = 전체 집계). 헬스 카드, 배너, 드로어, 매트릭스가 같은 수를 가리켜야 한다.
  const visibleCells = useMemo(() => pickModel(cells, modelFilter), [cells, modelFilter]);
  const drift = useMemo(() => pickModel(latest?.drift ?? [], modelFilter), [latest, modelFilter]);
  const visibleChanges = useMemo(() => pickModel(latest?.changes ?? [], modelFilter), [latest, modelFilter]);
  const changeSummary = useMemo(() => summarizeChanges(visibleChanges), [visibleChanges]);
  const groups = useMemo(
    () => (catalog ? buildGroups(catalog.features, catalog.groups, surfaces, cells, lang, filter, modelFilter) : []),
    [catalog, surfaces, cells, lang, filter, modelFilter],
  );
  const run = latest?.run ?? null;
  const runTotals = runSummary(run?.totals);
  const duration = formatDuration(run?.started_at ?? null, run?.finished_at ?? null, lang);
```

- [ ] **Step 6: 배너/카드/드로어 소스 교체**

(a) 변경 배너(Task 9 Step 4-d 블록) 안의 `latest.changes` **8회 전부(5개 위치)**를 `visibleChanges`로 치환 — 조건 1회, 제목 템플릿 EN/KO 2회, 목록 1회, 외 N건 줄 3회(`> 10` 조건 + EN/KO 산술), 변경 없음 카드 1회. 치환 후 `grep -c 'latest\.changes' /home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx` = `0`(`latest?.changes`를 읽는 Step 5의 `visibleChanges` 정의는 이 패턴에 걸리지 않는다):
- 조건 `{run && latest && latest.changes.length > 0 && (` → `{run && latest && visibleChanges.length > 0 && (`
- 제목 `${latest.changes.length}` 2회 (EN/KO 템플릿) → `${visibleChanges.length}`
- 목록 `{latest.changes.slice(0, 10).map((c) => {` → `{visibleChanges.slice(0, 10).map((c) => {`
- 외 N건 `{latest.changes.length > 10 && <li …>{L(`+${latest.changes.length - 10} more`, `외 ${latest.changes.length - 10}건`)}</li>}` → `{visibleChanges.length > 10 && <li className="text-gray-500">{L(`+${visibleChanges.length - 10} more`, `외 ${visibleChanges.length - 10}건`)}</li>}`
- "변경 없음" 카드 조건 `latest.previous_run_id != null && latest.changes.length === 0` → `latest.previous_run_id != null && visibleChanges.length === 0`
(드리프트 배너와 RUL-1 카드는 이미 `drift` 변수를 읽으므로 자동으로 필터를 따른다.)

(b) 헬스 카드(Task 7/12): `const sm = surfaceSummary(cells, s.id);` → `const sm = surfaceSummary(visibleCells, s.id);` (Fable 5.1 선택 시 Mantle 카드 = 39셀 전부 N/A → `docHealth null` → "-" — critic 4-C, Task 6 가드).

(c) 드로어(Task 12 Step 5): `surfaceFindings(cells, sdef.id, catalog.models, lang)` → `surfaceFindings(visibleCells, sdef.id, catalog.models, lang)`.

- [ ] **Step 7: 모델 칩 행** — 필터 바 블록 `{run && (` `<div className="flex items-center gap-2 flex-wrap">`(Task 10 상태) **바로 앞**에 삽입

```tsx
      {/* 모델 칩 (v2.24.0, D5) — 전체 집계 또는 모델 하나의 열만. 행을 숨기지 않으므로 filterActive에는 포함하지 않는다 (RUL-8). */}
      {run && catalog && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-gray-500 mr-1">{L("Model", "모델")}</span>
          {[{ key: null as string | null, label: L("All (aggregate)", "전체") },
            ...catalog.models.map((m) => ({ key: m.key as string | null, label: m.label.replace(/^Claude /, "") }))].map((m) => (
            <button key={m.key ?? "all"} type="button" onClick={() => setModelFilter(m.key)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${modelFilter === m.key ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"}`}>
              {m.label}
            </button>
          ))}
          {modelFilter && (
            <span className="text-[11px] text-gray-500 ml-1">
              {L("Cells, health cards and banners show this model only.", "셀, 헬스 카드, 배너가 이 모델의 결과만 표시합니다.")}
            </span>
          )}
        </div>
      )}
```

- [ ] **Step 8: 타입/테스트 통과 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && npx vitest run
```
기대: tsc 출력 없음, `Tests 72 passed`.

- [ ] **Step 9: 수동 확인 (optional, non-gating — `next.config.mjs` `/api/*` rewrite로 backend에 닿는 dev 서버 + 라이브 run #3 데이터 필요; 게이트는 Step 8의 `npx tsc --noEmit -p .` + `npx vitest run`만)**

1. "Fable 5" 칩 → Mantle 열 배지가 전부 단일 셀(`Unsupported`, 카운트 `x/probed` 없음), 클릭 즉시 모달(`single` 경로 CF:111,118). 드리프트 배너 23건(Fable 5만), Mantle 카드 값 변화(0%, 칩 `39 셀`), 드로어 6. 모델별 섹션은 Fable 5 한 줄에 막대, 다른 모델은 probed 0 → "문서상 프로브 셀 없음", Fable 5.1은 사유.
2. "Fable 5.1" 칩 → Mantle 열 전부 `N/A`, Mantle 카드 헤드라인 `-` + "문서상 제공 기능 중 실측된 셀 없음", 드리프트 배너 대신 `문서 드리프트 없음.` 카드(RUL-1), `context_window_1m` 행 Mantle/Bedrock은 여전히 "문서상 지원"(sky).
3. "전체" → 원래 집계 배지 복귀. 상태 필터(드리프트)와 모델 칩 동시 적용 시 행 수가 교집합으로 줄어들고, 그룹 강제 펼침은 상태 필터에만 반응한다(RUL-8). 런 합계 스트립은 칩과 무관하게 780셀 유지.

- [ ] **Step 10: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "feat(features): 모델 칩(전체/Fable 5.1/Fable 5/Opus 5/Sonnet 5) — buildGroups modelKey 집계 + pickModel, 헬스 카드·드리프트/변경 배너·드로어 동일 필터 (D5, C4, RUL-8)"
```

---

### Task 14: 셀 툴팁 모델별 지연시간 + 드롭다운 ms/mono model_id (D6, RUL-10; C8/R4, critic 4-E)

**Implements:** verify-C8.md §3 (null 혼재 37셀 → `—` 아닌 생략, not_applicable-with-latency 18셀 제외, `L` 스코프 주의), verify-R4.md §3-1 (probed ∧ latency != null), §3-2 (서브 ms 24행 → "<1 ms"), §3-4 ("프로브 소요(wall-clock)" 표기), critic §4-E (드롭다운 mono `model_id` 병기), D6 (백엔드 무변경), RUL-10 (`formatMs` 규칙: null → "-", 0 < ms < 1 → "<1 ms", 그 외 Intl 정수 + " ms"). Bundle frontend-B T4.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — 파일 끝에 헬퍼 2개 (`isProbed`는 Task 6 정의 사용 — RUL-7)
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx` `CellBadge` (:107-143 — title :121-123, 드롭다운 :130-138), import
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — `describe("latency helpers")` 추가

**Interfaces:**

Produces:
```ts
export interface LatencyLine { model_key: string; model_label: string; model_id: string | null; ms: number }
export function cellLatencyLines(cells: FeatureCell[]): LatencyLine[];   // isProbed(status) && latency_ms != null, 입력 순서 유지
export function formatMs(ms: number | null | undefined): string;         // RUL-10: null → "-", 0 < ms < 1 → "<1 ms", else Intl en-US 정수 + " ms"
```

- [ ] **Step 1: 실패 테스트** — `claudeFeatures.test.ts` import에 `cellLatencyLines, formatMs` 추가:
```ts
import {
  aggregateCell, buildGroups, cellLatencyLines, featureLabelOf, findCell, formatDuration, formatMs, isDocumented, isGroupOpen, isProbed, labelMaps,
  pickModel, runSummary, summarizeChanges, surfaceFindings, surfaceHealth, surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureChange, type FeatureDef, type ModelDef,
} from "./claudeFeatures";
```
파일 끝에:
```ts
describe("latency helpers (D6)", () => {
  test("cellLatencyLines keeps probed rows with latency only — runtime N/A with latency and null latency are dropped", () => {
    const lines = cellLatencyLines([
      cell({ latency_ms: 1234.4 }),
      cell({ model_key: "sonnet-5", model_label: "Sonnet 5", status: "unsupported", verdict: "match", latency_ms: 0.0006 }),
      cell({ model_key: "fable-5", status: "not_applicable", verdict: "none", latency_ms: 300 }),   // extended_thinking 런타임 N/A 18셀 패턴
      cell({ model_key: "fable-5-1", status: "skipped", verdict: "none", latency_ms: null }),
      cell({ model_key: "x", status: "broken", verdict: "drift", latency_ms: null }),
    ]);
    expect(lines.map((l) => [l.model_key, l.ms])).toEqual([["opus-5", 1234.4], ["sonnet-5", 0.0006]]);
    expect(lines[0]).toMatchObject({ model_label: "Opus 5", model_id: "claude-opus-5" });
  });
  test("formatMs (RUL-10): null → '-', sub-ms (no network call) → '<1 ms', 0 → '0 ms', otherwise rounded with thousands separator", () => {
    expect(formatMs(null)).toBe("-");
    expect(formatMs(undefined)).toBe("-");
    expect(formatMs(0.0006)).toBe("<1 ms");
    expect(formatMs(0)).toBe("0 ms");
    expect(formatMs(1234.4)).toBe("1,234 ms");
    expect(formatMs(25656)).toBe("25,656 ms");
  });
});
```

- [ ] **Step 2: 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
기대: `TypeError: cellLatencyLines is not a function`, `TypeError: formatMs is not a function` — 2건 실패.

- [ ] **Step 3: 구현** — `claudeFeatures.ts` 파일 끝

```ts

// ── 지연시간 표시 (v2.24.0, D6) — 값은 프로브 함수 전체 wall-clock(다중 호출 프로브는 합산). 백엔드 변경 없음.
export interface LatencyLine { model_key: string; model_label: string; model_id: string | null; ms: number }

// probed 상태(supported/unsupported/broken/inconclusive)이면서 latency_ms가 있는 행만 — 런타임 not_applicable(extended_thinking 등)이
// latency를 갖는 18셀은 "측정했는데 부적용"으로 읽히므로 제외 (verify-R4 §3-1). isProbed는 위의 단일 정의 (RUL-7).
export function cellLatencyLines(cells: FeatureCell[]): LatencyLine[] {
  return cells
    .filter((c) => isProbed(c.status) && c.latency_ms != null)
    .map((c) => ({ model_key: c.model_key, model_label: c.model_label, model_id: c.model_id, ms: c.latency_ms as number }));
}

const MS_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
// RUL-10. 서브 ms(0.0005~0.0007)는 네트워크 호출 없이 unsupported로 라우팅된 행(_route_or_unsupported) → "<1 ms" (verify-R4 §3-2).
export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "-";
  if (ms > 0 && ms < 1) return "<1 ms";
  return `${MS_FORMAT.format(Math.round(ms))} ms`;
}
```

- [ ] **Step 4: 통과 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run
```
기대: `Tests 74 passed`.

- [ ] **Step 5: `CellBadge` 툴팁** — `ClaudeFeaturesPanel.tsx`

(a) import 블록에 `cellLatencyLines, formatMs, isProbed` 추가 (Task 13 상태 기준, 알파벳 슬롯):
```tsx
import {
  aggregateCell, buildGroups, cellBadge, cellLatencyLines, featureLabelOf, findCell, formatDuration, formatMs, isGroupOpen, isProbed, labelMaps,
  pickModel, runSummary, summarizeChanges, surfaceFindings, surfaceShortOf, surfaceSummary, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type FindingChip, type FindingFeatureGroup, type LabelMaps, type RowView,
  type SurfaceDef, type SurfaceFindings, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```

(b) `CellBadge` 안 `const badge = cellBadge(agg.status, documented, lang);` (:113) 다음에:
```ts
  const lines = cellLatencyLines(agg.cells);
  const hint = badge.documentedOnly
    ? (lang === "en" ? "Documented as available — no verification path on this endpoint (not measured)" : "문서상 지원 — 이 엔드포인트에는 실측 경로가 없어 측정하지 않음")
    : (lang === "en" ? "Click for per-model evidence" : "클릭해서 모델별 증거 보기");
  // D6: 모델별 "라벨: N ms" 줄 + 지표 성격 한 줄 + 기존 안내. title은 \n으로 줄바꿈 렌더. L()은 메인 컴포넌트 클로저라 여기서는 삼항.
  const title = lines.length === 0 ? hint
    : [...lines.map((l) => `${l.model_label}: ${formatMs(l.ms)}`), lang === "en" ? "probe wall-clock time (multi-call probes are summed)" : "프로브 소요 시간(wall-clock, 다중 호출 프로브는 합산)", hint].join("\n");
```
(c) :121-123의
```tsx
        title={badge.documentedOnly
          ? (lang === "en" ? "Documented as available — no verification path on this endpoint (not measured)" : "문서상 지원 — 이 엔드포인트에는 실측 경로가 없어 측정하지 않음")
          : (lang === "en" ? "Click for per-model evidence" : "클릭해서 모델별 증거 보기")}
```
→ `title={title}`.

- [ ] **Step 6: 드롭다운 항목** — :130-138

`:130` `min-w-[14rem]` → `min-w-[17rem]`.
`:133-136`의 `<button …>` 전체를 다음으로 교체:
```tsx
              <button type="button" onMouseDown={() => onPick(c)} className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-[11px] hover:bg-blue-600/20">
                <span className="flex flex-col items-start min-w-0">
                  <span className="text-gray-300">{c.model_label}</span>
                  <span className="font-mono text-[9px] text-gray-500 truncate max-w-[11rem]">{c.model_id ?? "—"}</span>
                </span>
                <span className="flex items-center gap-2 shrink-0">
                  <span className="tabular-nums text-gray-500">{isProbed(c.status) ? formatMs(c.latency_ms) : "-"}</span>
                  <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${cellBadge(c.status, c.documented, lang).style}`}>{cellBadge(c.status, c.documented, lang).label}</span>
                </span>
              </button>
```

- [ ] **Step 7: 통과 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && npx vitest run
```
기대: tsc 출력 없음, `Tests 74 passed`.

- [ ] **Step 8: 수동 확인 (optional, non-gating — `next.config.mjs` `/api/*` rewrite로 backend에 닿는 dev 서버 + 라이브 run #3 데이터 필요; 게이트는 Step 7의 `npx tsc --noEmit -p .` + `npx vitest run`만)**

1. `web_fetch` 행 CP 배지에 마우스 → 4줄 `Claude Opus 5: 7,592 ms` … `Claude Fable 5: 25,656 ms` + "프로브 소요 시간…" + "클릭해서 모델별 증거 보기".
2. `extended_thinking` 행 CP 배지(전 모델 N/A) → 지연 줄 없이 안내문만. `context_window_1m` Mantle "문서상 지원" 배지 → 기존 문서상 지원 안내만.
3. `files_api` 행 InvokeModel 배지 드롭다운 → 각 모델 `<1 ms` + mono `global.anthropic.claude-…`. Mantle 열 드롭다운의 Fable 5.1 행 → `—` id, `-` ms, `N/A` 배지.

- [ ] **Step 9: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx && git commit -m "feat(features): 셀 툴팁에 모델별 프로브 소요 시간(probed 행만, 서브 ms는 <1 ms), 드롭다운에 ms + mono model_id (D6, C8+R4, RUL-10)"
```

---

### Task 15: 방법론 문장 + 검증 강도 범례/툴팁 + 카탈로그 파생 모델 문장 + catalog desc 2행(acceptance 사유) (C11, R11 §2-b 잔여, critic 4-D/4-E)

**Implements:** verify-C11.md corrections 1-5 (header sentence, "읽는 법" `5.`, `:319`·`:83` tag title, `:196-197`·`:364` model sentence derived from `catalog.models`, do NOT add parity's "카탈로그가 소스, 신규 모델 자동 반영" line — features is fixed at 4 models), verify-R11.md §2-b·§4(a)(b), critic §4-D (`catalog.py` `server_side_fallback`/`compaction` desc get the acceptance reason), critic §4-E ("지연시간" added to the stored-evidence list). Bundle frontend-B T5.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — `VERIFICATION_DESC`, `verificationDesc()`
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx` — `:83`(EvidenceModal 태그), `:195-198`(헤더 문장), `:319`(행 태그 title), `:364`(읽는 법 2항), `:366` 뒤(5항), import
- Modify: `/home/ec2-user/my-project/model-monitoring/backend/claude_features/catalog.py` `:132-133`, `:187-188` (각 `_f(...)` 호출의 desc 인자 두 줄만 교체 — 이어지는 `documented` dict·verification·notes 줄(:134-135, :189)은 그대로)
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — `describe("VERIFICATION_DESC")`; `/home/ec2-user/my-project/model-monitoring/backend/tests/test_claude_features.py` — `test_acceptance_only_rows_state_why_in_desc` 파일 끝에 append

**Interfaces:**

Produces:
```ts
export const VERIFICATION_DESC: Record<"evidence" | "acceptance" | "negative" | "capability", { en: string; ko: string }>;
export function verificationDesc(kind: string, lang: string): string;   // 미정의 kind → kind 그대로
```
Python: 시그니처 변경 없음(`_f(...)` 문자열 인자만). `CATALOG_VERSION`은 범프하지 않는다 — desc/label만 바뀌고 판정 규칙은 그대로 (RUL-14).

- [ ] **Step 1: 프론트 실패 테스트** — import에 `VERIFICATION_DESC, verificationDesc` 추가:
```ts
import {
  aggregateCell, buildGroups, cellLatencyLines, featureLabelOf, findCell, formatDuration, formatMs, isDocumented, isGroupOpen, isProbed, labelMaps,
  pickModel, runSummary, summarizeChanges, surfaceFindings, surfaceHealth, surfaceShortOf, surfaceSummary, verificationDesc, visibleSegments,
  VERIFICATION_DESC,
  type FeatureCell, type FeatureChange, type FeatureDef, type ModelDef,
} from "./claudeFeatures";
```
파일 끝:
```ts
describe("VERIFICATION_DESC (C11 legend)", () => {
  test("covers the four catalog strengths, both languages, Korean without middle dots", () => {
    expect(Object.keys(VERIFICATION_DESC).sort()).toEqual(["acceptance", "capability", "evidence", "negative"]);
    for (const d of Object.values(VERIFICATION_DESC)) {
      expect(d.en.length).toBeGreaterThan(20);
      expect(d.ko.length).toBeGreaterThan(10);
      expect(d.ko).not.toContain("·");
    }
    expect(verificationDesc("acceptance", "ko")).toBe(VERIFICATION_DESC.acceptance.ko);
    expect(verificationDesc("acceptance", "en")).toBe(VERIFICATION_DESC.acceptance.en);
    expect(verificationDesc("weird", "ko")).toBe("weird");
  });
});
```

- [ ] **Step 2: 백엔드 실패 테스트** — `backend/tests/test_claude_features.py` 파일 끝에 append

```python


# ==================================================================== v2.24.0 — Task 15: catalog desc — acceptance 사유 (critic 4-D)

def test_acceptance_only_rows_state_why_in_desc():
    """critic 4-D (v2.24.0): server_side_fallback/compaction은 acceptance 행인데 desc에 사유가 없었다."""
    by_id = {f["id"]: f for f in catalog.FEATURES}
    for fid in ("server_side_fallback", "compaction"):
        f = by_id[fid]
        assert f["verification"] == "acceptance", fid
        assert "수락만 검증" in f["desc_ko"], fid
        assert "acceptance only" in f["desc_en"], fid
        assert "·" not in f["desc_ko"], fid  # 한글 UI 문장부호 규칙: 가운데 점 대신 쉼표
```

- [ ] **Step 3: 실패 확인**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q -k acceptance_only
```
기대: vitest `TypeError: Cannot convert undefined or null to object`(`Object.keys(undefined)`) 1건 실패; pytest `AssertionError: server_side_fallback` (`assert '수락만 검증' in 'fallbacks default + beta 수락'`) 1 failed.

- [ ] **Step 4: 프론트 구현** — `claudeFeatures.ts` 파일 끝

```ts

// ── 검증 강도 4종 정의 (v2.24.0, C11) — 행 태그·증거 모달 태그 title, '읽는 법' 5항에서 공유. 출처: ADR-026 결정 1·5·7, catalog.py:110/126/189.
export const VERIFICATION_DESC: Record<"evidence" | "acceptance" | "negative" | "capability", { en: string; ko: string }> = {
  evidence: {
    en: "Evidence: the response content itself is checked (canary round-trip, 2+ stream deltas, cache_read tokens, schema-valid JSON). HTTP 200 alone is never enough.",
    ko: "evidence: 응답 내용 자체를 검사합니다(카나리 왕복, 스트림 델타 2개 이상, cache_read 토큰, 스키마 유효 JSON). HTTP 200만으로는 supported로 두지 않습니다.",
  },
  acceptance: {
    en: "Acceptance: only checks that the request (beta header, parameter) is accepted without error — the feature fires under conditions a short probe cannot force, so no response signal exists.",
    ko: "acceptance: 요청(beta 헤더, 파라미터)이 오류 없이 수락되는지만 확인합니다. 짧은 프로브로는 발동 조건을 만들 수 없어 응답 신호가 없습니다.",
  },
  negative: {
    en: "Negative: additionally sends an invalid value and requires a 400 that names the parameter — separates 'validated' from 'silently ignored'.",
    ko: "negative: 잘못된 값도 함께 보내 해당 파라미터를 지목하는 400 거부를 요구합니다. '검증됨'과 '조용히 무시'를 구분합니다.",
  },
  capability: {
    en: "Capability: read from Models API metadata (e.g. max_input_tokens) instead of a live request — only CP exposes this endpoint.",
    ko: "capability: 실요청 대신 Models API 메타데이터(max_input_tokens 등)를 조회합니다. CP에만 이 엔드포인트가 있습니다.",
  },
};
export function verificationDesc(kind: string, lang: string): string {
  const d = (VERIFICATION_DESC as Record<string, { en: string; ko: string } | undefined>)[kind];
  return d ? (lang === "en" ? d.en : d.ko) : kind;
}
```

- [ ] **Step 5: 백엔드 구현** — `backend/claude_features/catalog.py`

`:132-133`
```python
    _f("server_side_fallback", "model", "서버측 Fallback", "Server-side fallback", "fallbacks default + beta 수락",
       "fallbacks default + beta accepted", _DOC + "build-with-claude/refusals-and-fallback",
```
→
```python
    _f("server_side_fallback", "model", "서버측 Fallback", "Server-side fallback",
       "fallbacks default + beta 수락만 검증 (fallback은 원 모델이 refusal을 낼 때만 발동해 짧은 프로브로는 응답 신호를 강제할 수 없음)",
       "fallbacks default + beta accepted — acceptance only (a fallback fires only on a refusal by the primary model, so a short probe cannot force a response signal)",
       _DOC + "build-with-claude/refusals-and-fallback",
```
`:187-188`
```python
    _f("compaction", "context", "컴팩션", "Compaction", "beta compact-2026-01-12 + edits[compact_20260112] 수락",
       "beta compact-2026-01-12 + edits[compact_20260112] accepted", _DOC + "build-with-claude/compaction",
```
→
```python
    _f("compaction", "context", "컴팩션", "Compaction",
       "beta compact-2026-01-12 + edits[compact_20260112] 수락만 검증 (컴팩션은 입력 토큰이 trigger 임계치를 넘을 때만 발동해 짧은 프로브로는 응답 신호를 강제할 수 없음, CP는 Models API capability를 보조 확인)",
       "beta compact-2026-01-12 + edits[compact_20260112] accepted — acceptance only (compaction fires only once input tokens pass the trigger threshold, unreachable by a short probe; CP adds a Models API capability check)",
       _DOC + "build-with-claude/compaction",
```
(근거: `probes.py:380-390` `probe_server_side_fallback`는 수락 후 `served_model`만 기록, `:666-677` `probe_compaction`은 trigger 50,000 input_tokens 설정 + `models` 라우트가 있으면 `capability_compact_20260112` 보조 조회. ruff 기본 룰셋은 E501을 켜지 않으므로 긴 문자열 줄이 허용된다 — `backend/`에 ruff 설정 파일 없음 확인 2026-09-07.)

- [ ] **Step 6: 패널 문구** — `ClaudeFeaturesPanel.tsx`

(0) import 블록(Task 14 상태)에 `verificationDesc` 추가 — `surfaceSummary` 뒤, 최종 형태:
```tsx
import {
  aggregateCell, buildGroups, cellBadge, cellLatencyLines, featureLabelOf, findCell, formatDuration, formatMs, isGroupOpen, isProbed, labelMaps,
  pickModel, runSummary, summarizeChanges, surfaceFindings, surfaceShortOf, surfaceSummary, verificationDesc, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type FindingChip, type FindingFeatureGroup, type LabelMaps, type RowView,
  type SurfaceDef, type SurfaceFindings, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```

(a) `:195-198` 헤더 `<p …>{L(…)}</p>` → 카탈로그 파생 + 방법론 한 문장:
```tsx
          {(() => {
            const modelList = (catalog?.models ?? []).map((m) => m.label.replace(/^Claude /, "")).join(", ") || L("the representative models", "대표 모델");
            return (
              <p className="text-sm text-gray-400 mt-1 max-w-3xl leading-relaxed">
                {L(`Every documented "Build with Claude" feature, executed for real on Claude Platform on AWS, Bedrock Mantle and Bedrock runtime (Messages API, InvokeModel, Converse) with ${modelList}. Cells compare what the docs promise with what actually happened. Evidence rows are judged on response content (canary, deltas, usage), never on HTTP 200 alone; acceptance rows only verify the request is accepted.`,
                   `공식 "Build with Claude" 문서의 모든 피처를 Claude Platform on AWS, Bedrock Mantle, Bedrock runtime(Messages API, InvokeModel, Converse)에서 ${modelList}로 실제 실행합니다. 셀은 문서가 약속한 것과 실측을 비교합니다. evidence 행은 응답 내용(카나리, 델타, usage)을 검사해 판정하며 HTTP 200만으로는 supported로 두지 않습니다. acceptance 행은 요청 수락 여부까지만 검증합니다.`)}
              </p>
            );
          })()}
```
(b) `:319` `title={L("Verification strength", "검증 강도")}` → `title={verificationDesc(row.verification, lang)}`.
(c) `:83` `<span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400">{data.verification}</span>` → `<span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400" title={verificationDesc(data.verification, lang)}>{data.verification}</span>` (`EvidenceModal`은 이미 `const { lang } = useLang();` :26).
(d) `:364` 읽는 법 2항 → 모델 문장 파생 + "지연시간":
```tsx
        <p>2. {(() => {
          const models = (catalog?.models ?? []).map((m) => m.label.replace(/^Claude /, ""));
          const list = models.join(", ") || L("the representative models", "대표 모델");
          const na = (catalog?.models ?? []).filter((m) => m.mantle === null).map((m) => m.label.replace(/^Claude /, "")).join(", ");
          return L(`Each cell aggregates ${list}${na ? ` (${na} is not measurable on Bedrock Mantle — US GovCloud only; see the Note under the table)` : ""}. Click to open per-model evidence: request snapshot, response signal, latency, error.`,
                   `각 셀은 ${list} 결과를 집계합니다${na ? `(${na}은 Bedrock Mantle에서 측정 불가 — US GovCloud 리전 전용, 표 하단 참조)` : ""}. 클릭하면 모델별 증거(요청 스냅샷, 응답 신호, 지연시간, 오류)를 볼 수 있습니다.`);
        })()}</p>
```
(e) `:366` 4항 뒤에 5항 추가(강도 분포는 카탈로그에서 파생):
```tsx
        <p>5. {(() => {
          const n: Record<string, number> = {};
          for (const f of catalog?.features ?? []) n[f.verification] = (n[f.verification] ?? 0) + 1;
          const dist = ["evidence", "acceptance", "negative", "capability"].filter((k) => n[k]).map((k) => `${k} ${n[k]}`).join(", ");
          return L(`Verification strength (${dist}): evidence = response signal checked, acceptance = request accepted only, negative = invalid value must be rejected with 400, capability = metadata endpoint lookup. The small gray tag next to a row marks non-evidence rows. Treat Broken and drift cells as real only after the request snapshot in the evidence modal rules out a probe defect.`,
                   `검증 강도(${dist}): evidence = 응답 신호 확인, acceptance = 요청 수락만, negative = 잘못된 값 400 거부 확인, capability = 메타 엔드포인트 조회. 행 옆 회색 태그는 evidence가 아닌 행에만 붙습니다. Broken, 드리프트 셀은 증거 모달의 요청 스냅샷으로 프로브 결함 여부를 먼저 확인한 뒤 신뢰합니다.`);
        })()}</p>
```
'카탈로그가 소스, 신규 모델 자동 반영'(ParityPanel.tsx:773)은 features가 4모델 고정이라 **추가하지 않는다**(verify-C11 교정 5).

- [ ] **Step 7: 통과 확인 (양쪽)**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && npx vitest run
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests/test_claude_features.py -q && ruff check claude_features tests/test_claude_features.py && python3.12 -m pytest tests -q
```
기대: tsc 출력 없음, `Tests 75 passed`; pytest `126 passed`; ruff `All checks passed!`; 전체 스위트 `248 passed, 1 warning`.

- [ ] **Step 8: 수동 확인 (optional, non-gating — `next.config.mjs` `/api/*` rewrite로 backend에 닿는 dev 서버 + 라이브 run #3 데이터 필요; 게이트는 Step 7의 `npx tsc --noEmit -p .` + `npx vitest run` + backend `pytest`/`ruff`만)**

1. 헤더 문장에 "Fable 5.1, Fable 5, Opus 5, Sonnet 5"가 카탈로그 순서로, 이어서 방법론 문장.
2. `fallback_credit` 행의 `acceptance` 태그에 마우스 → 한 문장 정의. 증거 모달의 태그도 같은 title.
3. 읽는 법 5항에 "(evidence 33, acceptance 3, negative 2, capability 1)". EN 토글 시 전부 영문.
4. `server_side_fallback`, `compaction` 행 hover(`title={row.desc}` :315) → 새 desc(사유 절 포함). 배포 후 `/api/features/catalog`에서 동일 문자열 확인.

- [ ] **Step 9: 커밋**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx backend/claude_features/catalog.py backend/tests/test_claude_features.py && git commit -m "feat(features): 실행-증거 방법론 문장 + 검증 강도 4종 범례/태그 툴팁, 헤더·읽는 법 모델 문장을 catalog.models에서 파생, '지연시간' 열거 추가; catalog server_side_fallback/compaction desc에 acceptance 사유 (C11, critic 4-D/4-E)"
```

---

### Task 16: Docs + version bump + CHANGELOG (D9, D10, RUL-3, RUL-14, RUL-15; R12, critic 4-F)

**Implements:** verify-R12.md (api-reference `/api/features` section, CLAUDE.md per-run count), critic §4-F (components/CLAUDE.md:20 stale "도넛"; api-reference parity trigger "~3 min"), D9, D10 version touchpoints, RUL-3 (record the `L(en, ko)` i18n exception), RUL-14 (`CATALOG_VERSION` not bumped; add the release-checklist line), RUL-15 (parity trigger → "약 5-10분", features trigger "약 7분"). No push, no PR, no tag.

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/docs/api-reference.md` — :199 parity trigger duration; insert a `## Claude API Features` section between the parity section's closing `---` (:202) and `## Admin` (:204)
- Modify: `/home/ec2-user/my-project/model-monitoring/docs/decisions/ADR-026-claude-api-feature-verification-matrix.md` — append addendum after :117 (end of `## Consequences`)
- Modify: `/home/ec2-user/my-project/model-monitoring/CLAUDE.md` — :5 version, :125/:135 directory-tree lines, :220 per-run count + v2.24.0 sentence, after :284 release-checklist line (RUL-14)
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/CLAUDE.md` — :20 ParityPanel ("도넛"), :21 ClaudeFeaturesPanel (+ RUL-3 i18n exception)
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/version.ts` :3, `/home/ec2-user/my-project/model-monitoring/frontend/package.json` :3, `/home/ec2-user/my-project/model-monitoring/backend/main.py` :215, `/home/ec2-user/my-project/model-monitoring/README.md` :4
- Modify: `/home/ec2-user/my-project/model-monitoring/CHANGELOG.md` — `## Unreleased` (:10) → `## v2.24.0 — 2026-09-07` with new `### Added` / `### Changed` / `### Docs` blocks inserted above the existing `### Fixed` block (PR #51's startup-migration entry stays under this version)
- Test: full frontend + backend suites stay green (no code change in this task); `git diff --stat` lists exactly the 9 files above.

**Interfaces:** none (docs only). `CATALOG_VERSION` in `backend/claude_features/runner.py:22` stays `"2026-09-05"` (RUL-14).

- [ ] **Step 1: Version strings (D10)**

(a) `frontend/src/lib/version.ts:3` — `export const APP_VERSION = "v2.23.1";` → `export const APP_VERSION = "v2.24.0";`
(b) `frontend/package.json:3` — `"version": "2.23.1",` → `"version": "2.24.0",`
(c) `backend/main.py:215` — `    version="2.23.1",` → `    version="2.24.0",`
(d) `README.md:4` — `[![Version](https://img.shields.io/badge/version-2.23.1-blue.svg)](CHANGELOG.md)` → `[![Version](https://img.shields.io/badge/version-2.24.0-blue.svg)](CHANGELOG.md)`
(e) `CLAUDE.md:5` — `**Amazon Bedrock LLM Monitor** (v2.23.1 — 현재 버전은` → `**Amazon Bedrock LLM Monitor** (v2.24.0 — 현재 버전은`

Verify (on `a048028` these five files contain exactly five `2.23.1` occurrences — the five touchpoints above and nothing else, checked 2026-09-07):
```bash
cd /home/ec2-user/my-project/model-monitoring && grep -rn '2\.23\.1' frontend/src/lib/version.ts frontend/package.json backend/main.py README.md CLAUDE.md; echo "exit=$? (1 = no stale version strings left)"
cd /home/ec2-user/my-project/model-monitoring && grep -rn '2\.24\.0' frontend/src/lib/version.ts frontend/package.json backend/main.py README.md CLAUDE.md | wc -l
```
Expected: first command prints only `exit=1`; second prints `5`. **Run this check right after Step 1, before Step 4** — Step 4 adds four more `v2.24.0` lines to `CLAUDE.md` ((a) :125, (b) :135, (c) the appended sentence, (d) the `CATALOG_VERSION` checklist paragraph), so the same count command prints `9` from then on; the first command (`2.23.1` absent) stays valid at any later step.

- [ ] **Step 2: `docs/api-reference.md`**

(a) Line 199 — replace
```
Start a manual parity run in a backend background thread (~3 min). Rejects if already running.
```
with
```
Start a manual parity run in a backend background thread (약 5-10분 — the duration the router itself reports in `routers/parity.py`; the old "~3 min" was stale). Rejects if already running.
```

(b) Insert after the parity section's closing `---` (line 202, blank line after it) and before `## Admin (Admin Only — `username == "admin"`)`:
```markdown
## Claude API Features (Public read, trigger = Auth Required) — v2.23.0, `changes[].kind` + failed-cell evidence v2.24.0

### GET /api/features/catalog
Feature catalog: `groups` (7 feature groups with `label_ko`/`label_en`), `surfaces` (5 — `cp`, `mantle`, `bedrock_messages`,
`bedrock_invoke`, `bedrock_converse`; each `{id, label, short, group, region}`, the Mantle region is `MANTLE_ANTHROPIC_REGION`),
`models` (4 representative models `fable-5-1`, `fable-5`, `opus-5`, `sonnet-5` with per-surface native ids; `mantle: null` plus
`mantle_reason` when Mantle does not serve the model) and `features` (39 rows = 33 documented "Build with Claude" features + 4 core
Messages checks + Models API + the strict_tool_use split; each with `label_ko/label_en`, `desc_ko/desc_en`, `doc_url`, per-surface
`documented` ∈ ga|beta|no|unknown, `verification` ∈ evidence|acceptance|negative|capability, `notes`). Since v2.24.0 the UI takes every
feature label and surface short name from this payload (`labelMaps`) — it is the single source for banners, modal titles and the drawer.

### GET /api/features/latest
Latest completed run: `run` (id, started_at, finished_at, `totals` — the 6 status counts plus `drift`, catalog_version, running flag),
`previous_run_id`, `changes`, `drift`, `results`. `results[]` = one row per (feature, surface, model_key): `model_label`, `model_id`,
`status` ∈ supported|unsupported|broken|inconclusive|skipped|not_applicable, `documented`, `verdict` ∈ match|drift|undocumented|none,
`latency_ms` (null for runner pre-decided rows). `drift[]` = the results whose verdict is `drift`. `changes[]` = cells whose status differs
from the previous completed run: `{feature, surface, model_key, model_label, before, after, kind}` — `before: null` for cells absent in
the previous run; **`kind` (v2.24.0)** is `"catalog"` when the cell did not exist before or when either side is a runner pre-decided row
(`latency_ms IS NULL` — a catalog rule such as `_NOT_APPLICABLE_BY_DOC`), else `"measured"`. `Cache-Control: s-maxage=60`.
With no completed run: `{"run": null, "previous_run_id": null, "changes": [], "drift": [], "results": [], "running": false}`.

### GET /api/features/evidence?run_id=&feature=&surface=&model_key=
Full evidence for one cell: the result row fields plus `evidence` JSON, `error_message`, and the catalog `doc_url`, `verification`,
`notes`. `evidence.request` is the request snapshot: `model`, the Anthropic/Converse body (strings over 200 chars trimmed, bytes as
`<N bytes>`), `anthropic_beta`, and the v2.24.0 meta keys `api` (e.g. `count_tokens`, `messages (stream)`, `GET /v1/models/{id}`,
`POST /v1/files → GET → DELETE`, or the boto operation `InvokeModel`/`Converse`/`CountTokens` on failed cells) and `note` for multi-call
probes (`same request twice; cache judged on 2nd call usage`, `2 calls: effort=low, then effort=ultra as negative control`, …).
Since v2.24.0 failed cells also carry the last body the transport actually sent (thread-local recorder; previously only `{"model"}`),
`error_message` keeps the boto operation name (`ValidationException (CountTokens): …`) and names the route for empty error bodies
(`HTTP 404: (empty body) GET /v1/files`), and the thinking probes store `usage`. 404 if the cell does not exist.

### POST /api/features/trigger (Auth Required)
Start a manual Claude API Features run in a backend background thread (약 7분 — the duration the router reports in
`routers/features.py`). Rejects if already running. The daily scheduled run uses a separate Fargate task instead
(`python -m features_runner --once`).

---

```

- [ ] **Step 3: ADR-026 addendum** — append at the end of `docs/decisions/ADR-026-claude-api-feature-verification-matrix.md` (after line 117)

```markdown

## Addendum — v2.24.0 UI 상세도 보강 (2026-09-07)

`/parity`(ParityPanel)와 `/claude-features`의 상세도 갭 분석(후보 C1~C11, R1~R12를 코드 라인 단위로 검증) 결과를 반영해 UI와 증거를 패리티
수준으로 끌어올렸다. 판정 로직(`engine.classify`, `verdict`)과 카탈로그 규칙은 바꾸지 않았고 `CATALOG_VERSION`도 유지한다(desc 문구만 변경).

- **헬스 카드 헤드라인 = 문서 기준 헬스(docHealth)**: 문서상 GA/Beta이면서 실측된(supported/unsupported/broken/inconclusive) 셀 중 supported 비율.
  기존 `supported/(supported+broken)` 공식은 드리프트 25건이 있는 run #3에서도 5장 전부 100%를 보여 오독을 유발했다(Mantle 실제 63%).
  카드에는 6상태 분포 막대(전체 셀, N/A 포함), "{total} 셀" 칩, 드리프트 pill을 함께 두고, 실측된 문서 셀이 0이면 "-"를 낸다.
- **Key Findings 드로어**: 카드 클릭 → verdict 축 6섹션(문서 드리프트, 프로브 오류, 의도된 격차, 문서 미확정, 문서에 없는 동작, 모델별 문서 일치율).
  순수 파생 `surfaceFindings()`는 vitest로 고정. 칩과 모델 버튼은 증거 모달을 연다.
- **모델 칩**: 전체 집계 또는 모델 하나의 열만(Mantle Fable 5 클러스터 격리) — 셀, 헬스 카드, 배너, 드로어가 같은 필터를 공유한다.
- **변경 배너 `kind`**: `/api/features/latest` `changes[]`에 `kind: catalog | measured`. 직전 런에 없던 셀 또는 어느 한쪽이 러너 사전판정 행
  (`latency_ms IS NULL`)이면 `catalog`. run #2→#3의 15건은 전부 v2.23.1 `_NOT_APPLICABLE_BY_DOC` 규칙 변경이었으나 배너가 실측 회귀와 구분하지
  못했고, `CATALOG_VERSION` 범프가 누락돼 버전 비교로도 잡을 수 없었다 → CLAUDE.md 릴리스 체크리스트에 "카탈로그 규칙 변경 시 `CATALOG_VERSION` 범프" 추가.
  배너는 직전 런이 있으면 항상 렌더(0건은 "변경 없음" 카드), 드리프트 0건도 "문서 드리프트 없음" 카드로 명시한다.
- **증거 보강(백엔드)**: 실패 셀에도 전송기가 마지막으로 보낸 요청 본문을 남긴다(`transports.record_request`/`last_request`, 스레드 로컬 —
  run #3 unsupported 206셀 중 182셀, 드리프트 25건 전부가 `{"model"}`만 남겼다); 오류 문자열에 boto operation 이름
  (`ValidationException (CountTokens): …`)과 빈 본문 라우트(`HTTP 404: (empty body) GET /v1/files`)를 표기 — 분류 마커에 걸리지 않음을
  회귀 핀 38건으로 보장; 요청 스냅샷 메타 키를 `api`/`note`로 통일; thinking 증거에 `usage` 저장.
- **MCP connector 정책 차이**(패리티는 ADR-023으로 제외, features는 포함 후 장애를 inconclusive로 격리)는 의도된 차이로 유지한다 — 문서 피처 목록을
  그대로 따르는 것이 이 매트릭스의 목적이다.
```

- [ ] **Step 4: `CLAUDE.md` (root)**

(a) :125 — replace
```
│   │   │   ├── ClaudeFeaturesPanel.tsx  # Claude API Features 5열(CP/Mantle/Bedrock 3서브열) 매트릭스 + 드리프트 배너 + 증거 모달 + 수동 트리거 (v2.23.0)
```
with
```
│   │   │   ├── ClaudeFeaturesPanel.tsx  # Claude API Features 5열(CP/Mantle/Bedrock 3서브열) 매트릭스 + 헬스 카드(docHealth, 클릭 → Key Findings 드로어) + 모델 칩 + 드리프트/변경(kind) 배너 + 증거 모달 + 수동 트리거 (v2.24.0)
```
(b) :135 — replace
```
│   │       ├── claudeFeatures.ts        # Claude API Features 매트릭스 순수 로직 — 셀 집계·그룹 구성·헬스 계산 (v2.23.0)
```
with
```
│   │       ├── claudeFeatures.ts        # Claude API Features 매트릭스 순수 로직 — 셀 집계·그룹 구성(modelKey)·surfaceSummary/surfaceFindings·labelMaps·지연시간 헬퍼 (v2.24.0)
```
(c) :220 — replace the fragment `(1런 = 프로브 658 + 사전판정 122 = 780셀)` with `(1런 = 프로브 643 + 사전판정 137 = 780셀 — v2.23.1에서 data_residency Bedrock 15셀이 사전판정으로 이동)` and append this sentence at the very end of the same paragraph (after `자세한 드리프트는 ADR-026.`):
```
 **v2.24.0 UI 상세도 보강(패리티 수준)**: 헬스 카드 헤드라인은 문서 기준 헬스(docHealth = 문서상 GA/Beta ∧ 실측 셀 중 supported 비율) + 6상태 분포 막대, 카드 클릭 → Key Findings 드로어(6섹션), 모델 칩(전체/모델별), 변경 배너 `kind`(카탈로그 규칙/실측) 태그, 셀 툴팁 모델별 지연시간; 백엔드는 실패 셀에도 요청 스냅샷 보존(스레드 로컬 recorder), 오류 문자열에 boto operation/빈 본문 라우트 표기(`engine.classify` 판정 불변, 회귀 핀 38건). ADR-026 부록 참조.
```
(d) After :284 (`(`cdk/package.json`은 인프라 패키지 버전이라 앱 버전과 무관 — 범프 대상 아님.)`) add a blank line and:
```
**Claude API Features 카탈로그 규칙 변경 시 `CATALOG_VERSION` 범프** (`backend/claude_features/runner.py`): `backend/claude_features/catalog.py`의 `_NOT_APPLICABLE_BY_DOC`, `documented` 기대치, `_CONVERSE_NOT_EXPRESSIBLE`, `is_applicable` 규칙이 바뀌면 함께 범프한다 — v2.23.1에서 누락돼 run #2→#3 변경 15건을 버전 비교로 식별할 수 없었고, 그래서 `/api/features/latest` `changes[].kind`는 `latency_ms IS NULL`(사전판정 행)로 카탈로그 변경을 식별한다. label/desc 문구만 바뀐 릴리스(v2.24.0)는 범프 대상이 아니다.
```

- [ ] **Step 5: `frontend/src/components/CLAUDE.md`**

(a) :20 — replace `provider 요약 카드(도넛)+Key Findings 드로어` with `provider 요약 카드(세그먼트 막대 `HealthBar`, v2.16.3에서 도넛 대체)+Key Findings 드로어`.

(b) :21 — replace the whole line with
```
- `ClaudeFeaturesPanel.tsx` — Claude API Features: 5열(CP/Mantle/Bedrock runtime Messages API·InvokeModel·Converse) 매트릭스; 헬스 카드(문서 기준 헬스 docHealth + 6상태 분포 막대 + "{total} 셀" 칩, 클릭 → `SurfaceDrawer` Key Findings 6섹션); 모델 칩(전체/Fable 5.1/Fable 5/Opus 5/Sonnet 5 — `buildGroups(..., modelKey)`, 카드·배너·드로어 동일 필터); 문서 드리프트 배너(0건이면 "문서 드리프트 없음" 카드); 직전 런 대비 변경 배너(`kind` 카탈로그 규칙/실측 태그, 항목 클릭 → 증거 모달, 0건이면 "변경 없음" 카드); 셀 툴팁 모델별 프로브 소요 시간 + 드롭다운 ms/mono model_id; 상태/드리프트 필터 활성 시 그룹 강제 펼침 + 모두 펼치기/접기; 증거 모달(요청 스냅샷·응답 신호·문서 링크·검증 강도 툴팁); 수동 트리거 (`lib/claudeFeatures.ts` 순수 로직 + vitest, v2.24.0). **i18n 예외**: 이 패널과 `ParityPanel`은 `src/lib/i18n.ts` 대신 인라인 `L(en, ko)`/삼항 헬퍼를 쓴다(하위 컴포넌트는 `useLang()` + 로컬 `T`). 라벨은 카탈로그(`labelMaps`)가 단일 출처, 한글 문장은 쉼표 열거·"1." 번호·단정형 판정 문구.
```

- [ ] **Step 6: `CHANGELOG.md`**

(a) Line 10 — replace `## Unreleased` with `## v2.24.0 — 2026-09-07`.

(b) Immediately below that heading (before the existing `### Fixed` block that holds the startup-migration entry) insert:
```markdown

### Added
- **Claude API Features detail parity with `/parity`** (`/claude-features`) — health cards now headline **documented health** (share of documented GA/Beta cells that measured supported — Mantle reads 63% on run #3 instead of a misleading 100%) with a 6-state distribution bar over every cell, a "{total} cells" chip, a drift pill and a counts line; clicking a card opens a **Key Findings drawer** (documentation drift by feature, probe errors, intended gaps, documentation undecided, undocumented behaviour, per-model documented health — Mantle Fable 5.1 shows its reason instead of a bar); **model chips** (All / Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5) narrow cells, cards, banners and the drawer to one model; the run meta line gains the run duration and a totals strip; cell tooltips list per-model probe wall-clock latency (sub-millisecond route-gated cells as "<1 ms") and the per-model dropdown shows ms + the mono model id; a methodology sentence and a verification-strength legend (evidence / acceptance / negative / capability) with tag tooltips.
- **Claude API Features 상세도를 `/parity` 수준으로 보강** (`/claude-features`) — 헬스 카드 헤드라인을 **문서 기준 헬스**(문서상 GA/Beta 셀 중 실측 supported 비율 — run #3 Mantle은 오독을 부르던 100% 대신 63%)로 바꾸고 전체 셀 6상태 분포 막대, "{total} 셀" 칩, 드리프트 pill, 카운트 줄을 추가; 카드 클릭 → **Key Findings 드로어**(피처별 문서 드리프트, 프로브 오류, 의도된 격차, 문서 미확정, 문서에 없는 동작, 모델별 문서 일치율 — Mantle Fable 5.1은 막대 대신 사유); **모델 칩**(전체/Fable 5.1/Fable 5/Opus 5/Sonnet 5)으로 셀, 카드, 배너, 드로어를 모델 하나로 좁힘; 런 메타 줄에 소요 시간과 합계 스트립; 셀 툴팁에 모델별 프로브 소요 시간(라우트 게이트 셀은 "<1 ms"), 드롭다운에 ms + mono model id; 방법론 문장과 검증 강도 4종 범례(evidence/acceptance/negative/capability) 및 태그 툴팁.
- **`/api/features/latest` `changes[].kind`** — `"catalog"` (the cell did not exist in the previous run, or either side is a runner pre-decided row — `latency_ms IS NULL`) vs `"measured"`; the changes banner tags each item and summarises "카탈로그 규칙 변경 N건, 실측 변경 M건". Run #2→#3's 15 changes were all catalog rule changes (`data_residency` → N/A on Bedrock) that the banner could not tell from measured regressions.
- **`/api/features/latest` `changes[].kind`** — `"catalog"`(직전 런에 없던 셀, 또는 어느 한쪽이 러너 사전판정 행 — `latency_ms IS NULL`) vs `"measured"`; 변경 배너가 항목마다 태그를 붙이고 "카탈로그 규칙 변경 N건, 실측 변경 M건"으로 요약. run #2→#3의 변경 15건은 전부 카탈로그 규칙 변경(`data_residency` → Bedrock N/A)이었는데 배너가 실측 회귀와 구분하지 못했다.
- **Evidence for failed cells** — transports record the last request body per thread (`record_request`/`last_request`) and `run_probe` keeps it on `TransportError` and generic exceptions (previously only `{"model"}` — 182 of the 206 unsupported cells on run #3, including all 25 drift cells); boto `ClientError` messages keep the AWS operation name (`ValidationException (CountTokens): …`); empty error bodies name the route (`HTTP 404: (empty body) GET /v1/files`); request-snapshot meta keys unified to `api`/`note` (`count_tokens`, `messages (stream)`, `GET /v1/models/{id}`, `2 calls: effort=low, then effort=ultra as negative control`, …); thinking probes store `usage`. `engine.classify` is unchanged — 38 regression pins (24 live error strings + 14 before/after pairs) prove identical verdicts.
- **실패 셀 증거** — 전송기가 스레드별 마지막 요청 본문을 기록(`record_request`/`last_request`)하고 `run_probe`가 `TransportError`·일반 예외 경로에서 회수(종전에는 `{"model"}`만 — run #3 unsupported 206셀 중 182셀, 드리프트 25건 전부); boto `ClientError` 문구에 AWS operation 이름 유지(`ValidationException (CountTokens): …`); 빈 오류 본문은 라우트를 표기(`HTTP 404: (empty body) GET /v1/files`); 요청 스냅샷 메타 키를 `api`/`note`로 통일(`count_tokens`, `messages (stream)`, `GET /v1/models/{id}`, `2 calls: effort=low, then effort=ultra as negative control` 등); thinking 프로브는 `usage` 저장. `engine.classify`는 불변 — 회귀 핀 38건(라이브 오류 문자열 24 + 전후 형식 쌍 14)으로 동일 판정 보장.

### Changed
- **Banners** — the changes banner is always rendered when a previous run exists: the list ("외 N건" beyond 10, each item opens the evidence modal, after-status pill in the 6-state style — N/A was painted amber) or a gray "이전 런(#N) 대비 변경 없음." card; the drift banner shows a gray "문서 드리프트 없음." card when there is no drift. Drift banner, changes banner, evidence modal title and drawer use catalog labels (feature label + surface short name) with raw ids in mono as secondary text.
- **배너** — 직전 런이 있으면 변경 배너를 항상 렌더: 목록(10건 초과 "외 N건", 항목 클릭 → 증거 모달, after 상태 pill은 6상태 스타일 — N/A가 amber로 찍히던 문제 수정) 또는 회색 "이전 런(#N) 대비 변경 없음." 카드; 드리프트 0건이면 회색 "문서 드리프트 없음." 카드. 드리프트 배너, 변경 배너, 증거 모달 제목, 드로어는 카탈로그 라벨(피처 라벨 + surface 약칭)을 쓰고 원시 id는 mono 보조 표기.
- **Filter vs collapsed groups** — an active status/drift filter forces every group open (toggle disabled, chevron hidden), fixing matching rows hidden under a group collapsed earlier; "모두 펼치기 / 모두 접기" buttons appear when no filter is active. The model chip does not force groups open.
- **필터와 접힌 그룹** — 상태/드리프트 필터가 켜지면 모든 그룹을 강제로 펼침(토글 무효, chevron 숨김) — 접어 둔 그룹 아래에 매칭 행이 가려지던 결함 수정; 필터가 없을 때 "모두 펼치기 / 모두 접기" 버튼. 모델 칩은 그룹을 강제로 펼치지 않는다.
- Catalog descriptions of `server_side_fallback` and `compaction` now state why they are acceptance-only rows (a fallback fires only on a refusal; compaction only past the input-token trigger). `CATALOG_VERSION` is unchanged (wording only).
- `server_side_fallback`, `compaction`의 카탈로그 desc에 acceptance 행인 사유를 명시(fallback은 refusal 때만, 컴팩션은 입력 토큰 trigger 초과 때만 발동). `CATALOG_VERSION`은 유지(문구만 변경).

### Docs
- `docs/api-reference.md` gains a `/api/features` section (catalog, latest incl. `changes[].kind`, evidence incl. the `api`/`note` snapshot keys, trigger "약 7분") and corrects the parity trigger duration ("~3 min" → 약 5-10분); ADR-026 gets a "v2.24.0 UI 상세도 보강" addendum; `CLAUDE.md` corrects the per-run count to 643 probes + 137 pre-decided and adds the release-checklist line "catalog rule changes → bump `CATALOG_VERSION`"; `frontend/src/components/CLAUDE.md` records that `ClaudeFeaturesPanel` uses the inline `L(en, ko)` helper instead of `i18n.ts` and fixes the stale ParityPanel "도넛" wording (segment bar since v2.16.3).
- `docs/api-reference.md`에 `/api/features` 섹션 추가(catalog, `changes[].kind` 포함 latest, `api`/`note` 스냅샷 키 포함 evidence, trigger "약 7분") 및 패리티 트리거 소요 시간 교정("~3 min" → 약 5-10분); ADR-026에 "v2.24.0 UI 상세도 보강" 부록; `CLAUDE.md`의 런당 수치를 프로브 643 + 사전판정 137로 교정하고 릴리스 체크리스트에 "카탈로그 규칙 변경 시 `CATALOG_VERSION` 범프" 추가; `frontend/src/components/CLAUDE.md`에 `ClaudeFeaturesPanel`이 `i18n.ts` 대신 인라인 `L(en, ko)` 헬퍼를 쓴다는 예외를 기록하고 ParityPanel의 낡은 "도넛" 표기(v2.16.3부터 세그먼트 막대)를 수정.
```
(The existing `### Fixed` block — "Backend startup no longer full-scans `probe_results` 29 times" EN + KO — stays below, now under `## v2.24.0 — 2026-09-07`.)

- [ ] **Step 7: Verify everything is still green and only the intended files changed**

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run 2>&1 | tail -4 && npx tsc --noEmit -p . && echo TSC-OK
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests -q 2>&1 | tail -1 && ruff check claude_features tests/test_claude_features.py routers/features.py
cd /home/ec2-user/my-project/model-monitoring && git diff --stat && grep -n '^## ' CHANGELOG.md | head -3 && grep -n 'CATALOG_VERSION = ' backend/claude_features/runner.py
```
Expected: `Tests 75 passed (75)`, `TSC-OK`; `248 passed, 1 warning`, `All checks passed!`; `git diff --stat` lists exactly `CHANGELOG.md`, `CLAUDE.md`, `README.md`, `backend/main.py`, `docs/api-reference.md`, `docs/decisions/ADR-026-claude-api-feature-verification-matrix.md`, `frontend/package.json`, `frontend/src/components/CLAUDE.md`, `frontend/src/lib/version.ts` (9 files); the first CHANGELOG headings are `## v2.24.0 — 2026-09-07` then `## v2.23.1 — 2026-09-05`; `CATALOG_VERSION = "2026-09-05"` (unchanged — RUL-14).

- [ ] **Step 8: Commit (no push, no PR, no tag)**

```bash
cd /home/ec2-user/my-project/model-monitoring && git add CHANGELOG.md CLAUDE.md README.md backend/main.py docs/api-reference.md docs/decisions/ADR-026-claude-api-feature-verification-matrix.md frontend/package.json frontend/src/components/CLAUDE.md frontend/src/lib/version.ts && git commit -m "docs(release): v2.24.0 — 버전 문자열 범프, CHANGELOG, api-reference /api/features 섹션, ADR-026 부록, CLAUDE.md 런 수치·CATALOG_VERSION 체크리스트, components/CLAUDE.md i18n 예외"
```

---

### Task 17 (optional): 그룹 요약행 surface별 미니 막대 — verdict 축 (C6)

**Implements:** verify-C6.md §1-§4 (parity `PP:696-733` group-summary bar ported with three corrections: §3b the colour axis must be **verdict** (match / drift / undocumented / undecided), not parity's status axis — 177 of run #3's 206 unsupported cells are `match` (documented no, measured unsupported) and would paint amber under the status axis; §3d denominator = probed cells (`isProbed`), `probed === 0` renders `—` (bedrock_converse server_tools/client_tools/tool_infra are all N/A); §3a features groups are expanded by default so the bar is a subtotal row, not a collapsed-state summary). Critic §6 rank 13 (low value) — **skip unless the owner asks for it.** If executed, run it AFTER Task 16 so the CHANGELOG bullet lands under `## v2.24.0` in the same commit. No backend change (verify-C6 §4).

**Files:**
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.ts` — `GroupView` (CFL:79 on `a048028`; locate by text `export interface GroupView { id: string; label: string; rows: RowView[] }`), the `out.push({ id: g.id, label: …, rows })` line inside `buildGroups` (CFL:115 on `a048028`), append `GroupSegment`/`groupSurfaceSummary()` at end of file
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/ClaudeFeaturesPanel.tsx` — import block (Task 15 state), the group header row's `<td colSpan={surfaces.length} />` (CF:312 on `a048028`, inside the `<tr onClick=…>` that Task 10 rewrote)
- Modify: `/home/ec2-user/my-project/model-monitoring/CHANGELOG.md` — one EN+KO bullet pair appended to the `### Added` block of `## v2.24.0 — 2026-09-07`
- Modify: `/home/ec2-user/my-project/model-monitoring/frontend/src/components/CLAUDE.md` — the `ClaudeFeaturesPanel.tsx` line written by Task 16
- Test: `/home/ec2-user/my-project/model-monitoring/frontend/src/lib/claudeFeatures.test.ts` — one test appended inside `describe("buildGroups", …)` after the two Task 13 tests

**Interfaces:**
- Consumes: `RowView.cells: Record<string, CellAggregate>` (`CellAggregate.cells: FeatureCell[]`, CFL:58), `isProbed` (Task 6, RUL-7), `buildGroups(features, groups, surfaces, cells, lang, filter, modelKey = null)` (Task 13 signature — unchanged here).
- Produces:
  ```ts
  export type GroupSegment = "match" | "drift" | "undocumented" | "undecided";
  export const GROUP_SEGMENT_ORDER: GroupSegment[];                                   // match, drift, undocumented, undecided
  export const GROUP_SEGMENT_BAR_COLOR: Record<GroupSegment, string>;                 // emerald / rose / sky / violet solid bg-*
  export const GROUP_SEGMENT_LABEL: Record<GroupSegment, { en: string; ko: string }>;
  export interface GroupSurfaceSummary { probed: number; counts: Record<FeatureStatus, number>; segments: Record<GroupSegment, number> }
  export function groupSurfaceSummary(rows: RowView[], surface: string): GroupSurfaceSummary;
  export interface GroupView { id: string; label: string; rows: RowView[]; perSurface: Record<string, GroupSurfaceSummary> }
  ```
  Semantics: `counts` = raw 6-status counts over every cell of the group's rows (post-filter rows, so the header row is a subtotal of what is rendered under it) on that surface; `probed` = cells with `isProbed(status)`; `segments` are counted over probed cells only — `verdict === "drift"` → `drift`, `"undocumented"` → `undocumented`, `"match"` → `match`, `"none"` (probed but no documented expectation: inconclusive, or documented `unknown`) → `undecided`. Bar widths = `segments[k] / probed`; the tooltip keeps the raw `S/U/B/I` counts (verify-C6 §3b).

- [ ] **Step 1: Write the failing test** — append inside `describe("buildGroups", …)` after the two Task 13 tests (before the describe's closing `});`)
```ts
  test("(optional C6) perSurface: verdict-axis subtotal per surface over the group's rows; probed excludes N/A and skipped", () => {
    const g = buildGroups(features, groups, ["cp", "mantle"], cells, "ko", "all");
    expect(g[0].perSurface.cp).toEqual({
      probed: 1, counts: { supported: 1, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 },
      segments: { match: 1, drift: 0, undocumented: 0, undecided: 0 },
    });
    expect(g[0].perSurface.mantle.segments).toEqual({ match: 0, drift: 1, undocumented: 0, undecided: 0 });
    // b: unsupported + documented no → verdict match → emerald, not amber (verify-C6 §3b — 의도된 격차는 경고색이 아님)
    expect(g[1].perSurface.cp.segments).toEqual({ match: 1, drift: 0, undocumented: 0, undecided: 0 });
    expect(g[1].perSurface.mantle).toEqual({
      probed: 0, counts: { supported: 0, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 },
      segments: { match: 0, drift: 0, undocumented: 0, undecided: 0 },
    });
    const extra = [...cells,
      cell({ feature: "a", model_key: "sonnet-5", status: "inconclusive", verdict: "none" }),
      cell({ feature: "a", model_key: "fable-5-1", status: "not_applicable", documented: "no", verdict: "none" })];
    expect(buildGroups(features, groups, ["cp", "mantle"], extra, "ko", "all")[0].perSurface.cp).toEqual({
      probed: 2, counts: { supported: 1, unsupported: 0, broken: 0, inconclusive: 1, skipped: 0, not_applicable: 1 },
      segments: { match: 1, drift: 0, undocumented: 0, undecided: 1 },
    });
  });
```

- [ ] **Step 2: Run — expect failure**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts
```
Expected: 1 new test fails with `TypeError: Cannot read properties of undefined (reading 'cp')` (`perSurface` does not exist on `GroupView` yet); the other 36 tests in this file pass (11 baseline + 25 added by Tasks 6-15).

- [ ] **Step 3: Implement the lib part** — `claudeFeatures.ts`

(a) Replace
```ts
export interface GroupView { id: string; label: string; rows: RowView[] }
```
with
```ts
export interface GroupView { id: string; label: string; rows: RowView[]; perSurface: Record<string, GroupSurfaceSummary> }
```
(b) Inside `buildGroups`, replace
```ts
    if (rows.length) out.push({ id: g.id, label: (lang === "en" ? g.label_en : g.label_ko) || g.id, rows });
```
with
```ts
    if (rows.length) {
      // (optional C6) 그룹 요약행 미니 막대 — 표시 중인 행(필터 적용 후)의 surface별 소계, verdict 축
      const perSurface = Object.fromEntries(surfaces.map((s) => [s, groupSurfaceSummary(rows, s)])) as Record<string, GroupSurfaceSummary>;
      out.push({ id: g.id, label: (lang === "en" ? g.label_en : g.label_ko) || g.id, rows, perSurface });
    }
```
(c) Append at end of file (function declarations hoist, so `buildGroups` above may call `groupSurfaceSummary` defined here; `isProbed` is the Task 6 definition — RUL-7):
```ts

// ── (optional C6) 그룹 요약행 surface별 미니 막대 — verdict 축 ──────────────────────────────────────
// parity PP:696-733은 status 축(S/U/B)이지만 features에서는 unsupported 206셀 중 177셀이 match(문서상 미제공, 실측 미지원)라
// status 축으로 그리면 의도된 격차가 경고색이 된다 (verify-C6 §3b). 분모는 실측 셀(isProbed), N/A·skipped 제외 (§3d).
export type GroupSegment = "match" | "drift" | "undocumented" | "undecided";
export const GROUP_SEGMENT_ORDER: GroupSegment[] = ["match", "drift", "undocumented", "undecided"];
export const GROUP_SEGMENT_BAR_COLOR: Record<GroupSegment, string> = {
  match: "bg-emerald-400", drift: "bg-rose-400", undocumented: "bg-sky-400", undecided: "bg-violet-400",
};
export const GROUP_SEGMENT_LABEL: Record<GroupSegment, { en: string; ko: string }> = {
  match: { en: "Match", ko: "문서 일치" }, drift: { en: "Drift", ko: "드리프트" },
  undocumented: { en: "Undocumented", ko: "문서에 없는 동작" }, undecided: { en: "Undecided", ko: "미확정" },
};
export interface GroupSurfaceSummary { probed: number; counts: Record<FeatureStatus, number>; segments: Record<GroupSegment, number> }

export function groupSurfaceSummary(rows: RowView[], surface: string): GroupSurfaceSummary {
  const counts: Record<FeatureStatus, number> = { supported: 0, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 };
  const segments: Record<GroupSegment, number> = { match: 0, drift: 0, undocumented: 0, undecided: 0 };
  let probed = 0;
  for (const row of rows) {
    for (const c of row.cells[surface]?.cells ?? []) {
      counts[c.status] += 1;
      if (!isProbed(c.status)) continue;
      probed += 1;
      if (c.verdict === "drift") segments.drift += 1;
      else if (c.verdict === "undocumented") segments.undocumented += 1;
      else if (c.verdict === "match") segments.match += 1;
      else segments.undecided += 1;   // verdict none on a probed cell: inconclusive, or documented unknown
    }
  }
  return { probed, counts, segments };
}
```
Run `cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run src/lib/claudeFeatures.test.ts` → 37 passed.

- [ ] **Step 4: Wire the panel**

(a) Import block (Task 15 state) — add `GROUP_SEGMENT_BAR_COLOR, GROUP_SEGMENT_LABEL, GROUP_SEGMENT_ORDER` to the constants line:
```tsx
import {
  aggregateCell, buildGroups, cellBadge, cellLatencyLines, featureLabelOf, findCell, formatDuration, formatMs, isGroupOpen, isProbed, labelMaps,
  pickModel, runSummary, summarizeChanges, surfaceFindings, surfaceShortOf, surfaceSummary, verificationDesc, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, GROUP_SEGMENT_BAR_COLOR, GROUP_SEGMENT_LABEL, GROUP_SEGMENT_ORDER,
  SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type FindingChip, type FindingFeatureGroup, type LabelMaps, type RowView,
  type SurfaceDef, type SurfaceFindings, type SurfaceSummary,
} from "@/lib/claudeFeatures";
```
(b) In the group header row (the `<tr onClick={() => { if (filterActive) return; … }}>` from Task 10), replace the empty spacer cell
```tsx
                      <td colSpan={surfaces.length} />
```
with
```tsx
                      {/* (optional C6) surface별 소계 미니 막대 — verdict 축(문서 일치/드리프트/문서에 없는 동작/미확정), 분모 = 실측 셀, N/A 열은 — */}
                      {surfaces.map((s) => {
                        const ps = g.perSurface[s];
                        if (!ps || ps.probed === 0) {
                          return <td key={s} className="px-3 py-2 border-l border-gray-800/60 text-center text-gray-600 text-[10px]">—</td>;
                        }
                        const tip = `S ${ps.counts.supported}, U ${ps.counts.unsupported}, B ${ps.counts.broken}, I ${ps.counts.inconclusive} / ${L("probed", "실측")} ${ps.probed}`
                          + (ps.segments.drift > 0 ? ` (${L("drift", "드리프트")} ${ps.segments.drift})` : "");
                        return (
                          <td key={s} className="px-3 py-2 border-l border-gray-800/60">
                            <div className="flex items-center justify-center gap-2" title={tip}>
                              <div className="flex h-1.5 w-20 rounded-full overflow-hidden bg-gray-800 shrink-0" role="img"
                                   aria-label={GROUP_SEGMENT_ORDER.map((k) => `${GROUP_SEGMENT_LABEL[k][lang]} ${ps.segments[k]}`).join(", ")}>
                                {GROUP_SEGMENT_ORDER.map((k) =>
                                  ps.segments[k] > 0 ? (
                                    <div key={k} className={GROUP_SEGMENT_BAR_COLOR[k]} style={{ width: `${(100 * ps.segments[k]) / ps.probed}%` }} />
                                  ) : null,
                                )}
                              </div>
                              <span className="text-[10px] tabular-nums text-gray-500 whitespace-nowrap">
                                <span className="text-emerald-300">{ps.segments.match}</span>
                                {ps.segments.drift > 0 && <span className="text-rose-300 font-semibold ml-1">▲{ps.segments.drift}</span>}
                                <span className="text-gray-600"> / {ps.probed}</span>
                              </span>
                            </div>
                          </td>
                        );
                      })}
```
(The header `<tr>` keeps its toggle `onClick`; clicking a mini bar toggles the group exactly like the label cell — same as parity PP:701.)

- [ ] **Step 5: Docs touch (same commit)**

(a) `CHANGELOG.md` — inside `## v2.24.0 — 2026-09-07` → `### Added`, append after the last bullet of that block (the KO bullet beginning `- **실패 셀 증거**`):
```markdown
- **Group subtotal mini bars** (`/claude-features`, optional C6) — each group header row shows, per endpoint column, a verdict-axis bar (match emerald, drift rose, undocumented sky, undecided violet) over the probed cells of the rows beneath it, with `match / probed` and a `▲drift` count; N/A-only columns show `—`. The tooltip keeps the raw S/U/B/I counts. The verdict axis avoids parity's status-axis pitfall where documented-unavailable + measured-unsupported cells (177 of 206 on run #3) would read as warnings.
- **그룹 소계 미니 막대** (`/claude-features`, 옵션 C6) — 그룹 요약행이 엔드포인트 열마다 아래 행들의 실측 셀에 대한 verdict 축 막대(문서 일치 emerald, 드리프트 rose, 문서에 없는 동작 sky, 미확정 violet)와 `문서 일치 / 실측`, `▲드리프트` 수를 표시; 전부 N/A인 열은 `—`. 툴팁에는 원시 S/U/B/I 카운트. status 축으로 그리면 문서상 미제공+실측 미지원 셀(run #3 206건 중 177건)이 경고색으로 읽히는 패리티식 함정을 verdict 축으로 피한다.
```
(b) `frontend/src/components/CLAUDE.md` — in the `ClaudeFeaturesPanel.tsx` line written by Task 16, replace `상태/드리프트 필터 활성 시 그룹 강제 펼침 + 모두 펼치기/접기;` with `상태/드리프트 필터 활성 시 그룹 강제 펼침 + 모두 펼치기/접기; 그룹 요약행 surface별 소계 미니 막대(verdict 축: 문서 일치/드리프트/문서에 없는 동작/미확정, 분모 = 실측 셀, 옵션 C6);`.

- [ ] **Step 6: Typecheck + tests**
```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx tsc --noEmit -p . && echo TSC-OK && npx vitest run 2>&1 | tail -4
```
Expected: `TSC-OK`, `Tests 76 passed (76)`. Manual check (run #3): `server_tools` group header — CP bar all emerald `20 / 20`, Mantle emerald+rose with `▲…`, bedrock_converse `—`; `model` group Mantle shows `▲9`; no amber anywhere on the header rows (unsupported-match cells are emerald); tooltip on the Mantle bar reads `S 10, U 21, B 0, I 0 / 실측 31 (드리프트 9)`. Select the `Fable 5` chip (Task 13) → bars recompute from the single-model cells.

- [ ] **Step 7: Commit**
```bash
cd /home/ec2-user/my-project/model-monitoring && git add frontend/src/lib/claudeFeatures.ts frontend/src/lib/claudeFeatures.test.ts frontend/src/components/ClaudeFeaturesPanel.tsx CHANGELOG.md frontend/src/components/CLAUDE.md && git commit -m "feat(features): (옵션 C6) 그룹 요약행 surface별 소계 미니 막대 — verdict 축(문서 일치/드리프트/문서에 없는 동작/미확정), 분모 = 실측 셀, N/A 열은 — 표기"
```

---

## Plan exit criteria

```bash
cd /home/ec2-user/my-project/model-monitoring/frontend && npx vitest run 2>&1 | tail -4 && npx tsc --noEmit -p . && echo TSC-OK
cd /home/ec2-user/my-project/model-monitoring/backend && python3.12 -m pytest tests -q 2>&1 | tail -1 && ruff check claude_features tests/test_claude_features.py routers/features.py
cd /home/ec2-user/my-project/model-monitoring && git log --oneline a048028..HEAD | cat && git status --short
```
Expected: `Tests 75 passed (75)` across 5 files (baseline 50 + 25; `76` if optional Task 17 was executed), `TSC-OK`; backend `248 passed` (baseline 191 + 57; `tests/test_claude_features.py` alone 126), ruff clean; 16 commits on `feat/features-detail-parity` above `a048028` (17 with optional Task 17); working tree clean except the pre-existing untracked `tests/20260810_SB/` and this plan file (`docs/superpowers/plans/2026-09-07-claude-features-detail-parity.md`, untracked unless committed on its own). `surfaceHealth` is still exported and its original test (`claudeFeatures.test.ts:63-68`) is untouched; `engine.classify` pins (38) are green; `CATALOG_VERSION` unchanged; nothing pushed, no PR, no tag — the release (image build with immutable tag, digest-pinned CDK deploy of backend + frontend together per RUL-4, git tag `v2.24.0`) is handled separately per `docs/runbooks/deploy.md`.
