# Design: Claude API Features — 3 Claude-on-AWS 엔드포인트 실행-증거 검증 메뉴

- **Date**: 2026-09-05
- **Branch**: `feat/claude-features-verify`
- **Version**: v2.23.0
- **Status**: Approved (design) — 2026-09-05 (사용자 결정 4건 반영: Bedrock 열 = InvokeModel + Converse 서브열 / 일 1회 + 수동 트리거 / 고비용 프로브 전부 실행·1M만 capability / 별도 패키지·별도 메뉴)
- **Related**: ADR-021 (실행-증거 원칙), ADR-022 (Mantle `/anthropic` bearer + IAM 체인), ADR-023 (패리티 카탈로그 확장·정직한 제외), ADR-026 (본 기능, 신규)

## Goal

[Claude Developer Platform "Build with Claude" 개요](https://platform.claude.com/docs/en/build-with-claude/overview)가
나열하는 **33개 피처 전부**(+ 코어 Messages 4종 + Models API)가 다음 세 Claude-on-AWS 엔드포인트(5 surface 열)에서 **실제로
동작하는지**를 주기적으로 실행해 증거와 함께 보여 주는 **별도 메뉴 `/claude-features`**를 추가한다.

| 열 | 엔드포인트 | 인증 | 모델 id | 리전 |
|---|---|---|---|---|
| **Claude Platform on AWS** (`cp`) | `https://aws-external-anthropic.{region}.api.aws/v1/*` | `x-api-key` envelope key + `anthropic-workspace-id` | bare `claude-fable-5-1` … | `ANTHROPIC_AWS_REGION` (기본 us-east-2) |
| **Bedrock Mantle `/anthropic`** (`mantle`) | `https://bedrock-mantle.{region}.api.aws/anthropic/v1/*` | SigV4 파생 단기 bearer (`aws_bedrock_token_generator.provide_token`) → `x-api-key` | FM id `anthropic.claude-fable-5` … | `MANTLE_ANTHROPIC_REGION` (**us-east-1** — 2026-09-05 사용자 결정; ap-northeast-1은 Opus 4.8만 서빙) |
| **Bedrock runtime — Anthropic Messages API** (`bedrock_messages`, 2026-09-05 추가) | `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/*` | SigV4 파생 단기 bearer → `x-api-key` (`anthropic-version`/`-beta` 헤더) | 프로파일 `global.anthropic.claude-fable-5-1` … | `BEDROCK_FEATURES_REGION` (기본 ap-northeast-2) |
| **Bedrock runtime — InvokeModel** (`bedrock_invoke`) | boto3 `bedrock-runtime` `invoke_model(_with_response_stream)` | SigV4 (태스크 롤) | 프로파일 `global.anthropic.claude-fable-5-1` … | ap-northeast-2 (Seoul) |
| **Bedrock runtime — Converse** (`bedrock_converse`, 서브열) | boto3 `converse(_stream)` / `count_tokens` | SigV4 | 동일 프로파일 | ap-northeast-2 |

이 메뉴의 차별점은 **문서 기대치 vs 실측 드리프트**다. 개요 페이지는 피처마다 플랫폼별 가용성(GA / Beta / 미제공)을
명시하므로, 각 셀은 "문서가 말하는 것"과 "오늘 실제로 되는 것"을 나란히 보여 주고 어긋나면 배너로 알린다.

## Scope decisions (확정)

1. **대표 모델 4종 고정**: Claude Fable 5.1 · Fable 5 · Opus 5 · Sonnet 5. Haiku 제외.
   Mantle 열은 **Fable 5.1 제외** — Mantle의 Fable 5.1은 US GovCloud(`us-gov-west-1`) 리전에서만 서빙되므로
   상용 리전에서 호출 불가. 해당 셀은 `not_applicable` + 사유 "Mantle Fable 5.1 = US GovCloud 전용"으로 표시한다
   (unsupported/skipped와 구분).
2. **기존 `/parity`는 건드리지 않는다.** 패리티는 모델 중심(43모델 × 6 surface × 19피처) 매트릭스로 남기고, 새 기능은
   형제 패키지 `backend/claude_features/`로 만든다. 순수 함수(`parity/engine.py`의 `classify_error`·`check_*`,
   `parity/catalog.py`의 `mantle_fm_id`·`supports_forced_tool_choice`)와 `prober.py`의 CP 클라이언트 헬퍼만 import한다.
   **기각한 대안**: (a) 패리티 카탈로그 확장 + 필터 뷰 — 모델 중심 데이터 모델에 "문서 기대치" 차원이 없고 셀이 수천 개로
   폭증, 사용자 요구(별도 메뉴)와 불일치. (b) 패리티까지 공통 엔진으로 리팩터 — 범위 과대·회귀 위험.
3. **SDK 대신 raw httpx + boto3.** 프로덕션 `requirements.txt`가 `anthropic>=0.40.0` 미고정이라 빌드 시 1.4.0(메이저 업)이
   설치된다. 새 엔진은 Anthropic Messages JSON 본문 하나를 세 전송기로 그대로 흘리므로 SDK 파라미터 표면 변화에 영향받지
   않는다. (패리티는 SDK 사용 — 그대로 둠.)
4. **스케줄**: EventBridge `rate(24 hours)` Fargate one-shot(`python -m features_runner --once`) + `POST /api/features/trigger`(JWT)
   수동 실행. 설계 시 추정은 1런 ≈ 550 API 호출·$3~5였고, **구현 확정값은 1런 = 프로브 658 + 사전판정 122 = 780셀
   (39행 × 5 surface × 4모델) · ≈800 API 호출 · $5~7**(5번째 surface `bedrock_messages` 추가 반영, ADR-026 §9).
   Bedrock runtime의 Anthropic Messages API는 AWS Build 가이드·Endpoints 페이지가 신규 앱과 "Migrating from Anthropic
   APIs"에 권장하는 경로여서 InvokeModel/Converse와 별개 열로 실측한다:
   <https://docs.aws.amazon.com/bedrock/latest/userguide/build.html> ·
   <https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html> ·
   <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html>
5. **고비용·부작용 프로브도 실행한다** (실행-증거 원칙 유지): web search(1회, ≈$0.01), web fetch, code execution(컨테이너
   최소 5분 과금·무료 티어 내), advisor(추가 추론), batches(1건 배치 생성 → 조회 → 즉시 취소), files(업로드 → 조회 → 삭제),
   agent skills(컨테이너). **1M 컨텍스트만 capability 검사로 대체**(실전송 $2+/회): CP는 Models API `max_input_tokens`,
   Mantle/Bedrock은 capability 엔드포인트가 없어 `skipped`("검증 경로 없음")로 기록.

## Catalog (행 정의 — `backend/claude_features/catalog.py`)

행마다: `id`, `group`, `label_ko/en`, `desc_ko/en`, `doc_url`, `documented: {cp, mantle, bedrock_messages, bedrock_invoke, bedrock_converse}`
(`bedrock_messages`는 별도 override가 없으면 `bedrock_invoke` 값을 상속한다 — `catalog._BEDROCK_MESSAGES_OVERRIDES`)
(값 `ga | beta | no | unknown`), `verification`(증거 강도), 모델 제약. 문서 기대치의 1차 출처는 개요 페이지 Availability
컬럼(Bedrock 단일 컬럼), Converse/InvokeModel 차이와 Mantle 특례는 AWS 공식 문서와 platform.claude.com의 Bedrock 두
페이지(Opus 4.7+ = Mantle, Opus 4.6 이하 = legacy)로 보정한다. 출처가 상충하는 항목은 `notes`에 기록하고 실측으로 판정한다.

**증거 강도 `verification`**
- `evidence` — 응답 내용이 문서가 정한 신호를 포함해야 supported (카나리·블록 타입·usage 필드).
- `acceptance` — 파라미터/도구 정의가 400 없이 수락되면 supported. 응답에 객관 신호가 없는 피처에만 사용하고 UI에 "수락만 확인" 배지.
- `negative` — 잘못된 값이 **해당 파라미터를 지목하는 400**으로 거부돼야 supported (파라미터가 파싱·검증됨을 증명; 조용히 무시되는 경로와 구분). `acceptance`와 짝으로 쓴다.
- `capability` — Models API `capabilities` 등 메타데이터로 판정.

| # | id | group | 프로브 요약 (전송기 무관 본문) | 증거 | 문서 기대치 cp / mantle / invoke / converse |
|---|---|---|---|---|---|
| C1 | `messages_basic` | core | 논스트리밍 1건 | 비어 있지 않은 text | ga / ga / ga / ga |
| C2 | `streaming` | core | `stream: true` (Converse: converse_stream) | content delta ≥ 2 | ga / ga / ga / ga |
| C3 | `system_prompt` | core | `system` 카나리 강제 | 카나리 반영 | ga / ga / ga / ga |
| C4 | `tool_use` | core | echo 도구, `tool_choice` 강제(Fable 5.1은 auto + 지시) | 카나리 왕복 | ga / ga / ga / ga |
| 1 | `context_window_1m` | model | CP: `GET /v1/models/{id}` | `max_input_tokens == 1_000_000` | ga / ga / ga / ga (mantle·bedrock은 `skipped`: capability 경로 없음) |
| 2 | `adaptive_thinking` | model | `thinking: {type: adaptive, display: summarized}` + `output_config.effort: low`, max_tokens 4000 | `thinking` 블록(+signature) 존재 | ga / ga / ga / ga (Converse: `additionalModelRequestFields`, `reasoningContent`) |
| 3 | `batch_processing` | model | `POST /v1/messages/batches` 1건 → GET → cancel | `processing_status` | ga / no / no / no (bedrock 두 열은 라우트 부재 → 호출 없이 `unsupported`) |
| 4 | `citations` | model | `document{source.text, citations.enabled}` + 질문 | `text.citations[]` 존재 | ga / ga / ga / ga (Converse: `DocumentBlock.citations` → `citationsContent`) |
| 5 | `data_residency` | model | `inference_geo: "us"` | `usage.inference_geo == "us"`; 부정 제어 `"mars"` → 400 | ga / no / no / no |
| 6 | `effort` | model | `output_config.effort: low` 수락 + 부정 제어 `effort: "ultra"` → 400 | acceptance+negative | ga / ga / ga / ga |
| 7 | `fallback_credit` | model | beta `fallback-credit-2026-07-01` + 무해 요청 | acceptance (`stop_details` null 기록) | beta / beta / beta / beta |
| 8 | `pdf_support` | model | base64 1페이지 PDF(코드 생성, 카나리 텍스트) + 질문 | 카나리 답변 | ga / ga / ga / ga (Converse: `document.source.bytes`) |
| 9 | `search_results` | model | `search_result` 블록 + citations | `search_result_location` citation | ga / ga / ga / ga (Converse: `searchResult` — AWS 문서는 구모델만 지원 명시 → notes) |
| 10 | `server_side_fallback` | model | beta `server-side-fallback-2026-07-01` + `fallbacks: "default"` | acceptance | beta(문서 상충: 개요는 Claude API only, fallback-credit 페이지는 P-AWS 인식 → `unknown`) / no / no / no |
| 11 | `structured_outputs` | model | `output_config.format json_schema` | 스키마 유효 JSON | ga / **no**(Mantle 페이지 명시 400) / ga(AWS 문서) / ga (`outputConfig.textFormat`) — Anthropic Bedrock 페이지와 AWS 문서 상충 → notes |
| 11b | `strict_tool_use` | model | `strict: true` 도구 + 지시 | `tool_use.input` 키 집합 == 스키마 | ga / unknown / ga / ga (`toolSpec.strict`) |
| 12 | `extended_thinking` | model | `thinking: {type: enabled, budget_tokens}` | 대표 4모델은 adaptive-only → 문서상 400이 정상. 정확한 거부 문구 확인 시 `not_applicable`(사유: 모델 제약), 그 외 결과는 `broken` | ga / ga / ga / ga |
| 13 | `advisor_tool` | server | beta `advisor-tool-2026-03-01`, `advisor_20260301` (executor→advisor 쌍: Fable 5.1→Fable 5.1, Fable 5→Fable 5, Opus 5→Opus 5, Sonnet 5→Opus 5), 강제 호출(Fable 5.1은 지시) | `server_tool_use{advisor}` + `advisor_tool_result`/`advisor_redacted_result`; 미호출 → `inconclusive` | beta / no / no / no |
| 14 | `code_execution` | server | `code_execution_20260521`, "7391*3 출력" | `bash_code_execution_tool_result.stdout` ∋ 22173 | ga / no / no / no |
| 15 | `web_fetch` | server | `web_fetch_20260209`, 메시지에 URL 명시 | `web_fetch_tool_result.web_fetch_result` | ga / no / no / no |
| 16 | `web_search` | server | `web_search_20260209`, `max_uses: 1` | `web_search_tool_result` 리스트 | ga / no / no / no |
| 17 | `bash_tool` | client | `bash_20250124` + 지시 | `tool_use{name: bash}` | ga / ga / ga / n.a.(Converse는 Anthropic-defined tool 표현 불가 → `not_applicable`) |
| 18 | `browser_use` | client | `browser_toolset_20260801` | `tool_use{toolset_name: browser}` | no / no / no / n.a. |
| 19 | `computer_use` | client | 1차 `computer_toolset_20260801`, 400이면 2차 `computer_20251124` + beta `computer-use-2025-11-24`; 두 시도 모두 evidence에 기록 | `tool_use`(screenshot) | beta / beta / beta / n.a. |
| 20 | `memory_tool` | client | `memory_20250818` | `tool_use{memory, command: view}` | ga / ga / ga / n.a. |
| 21 | `text_editor` | client | `text_editor_20250728` | `tool_use{str_replace_based_edit_tool}` | ga / ga / ga / n.a. |
| 22 | `agent_skills` | infra | `container.skills [pdf]` + code_execution; CP는 `GET /v1/skills`도 기록 | 200 + `container.id` | beta / no / no / no |
| 23 | `fine_grained_tool_streaming` | infra | 도구에 `eager_input_streaming: true` + stream, 300자 텍스트 인자 | `input_json_delta` ≥ 2 (acceptance+evidence) | ga / ga / ga / n.a. |
| 24 | `mcp_connector` | infra | beta `mcp-client-2025-11-20`, `mcp_servers` + `mcp_toolset` (서버 URL env `FEATURES_MCP_SERVER_URL`, 기본 공개 read-only MCP) | `mcp_tool_use`/`mcp_tool_result`; 서버 도달 실패 → `inconclusive` | beta / no / no / no |
| 25 | `programmatic_tool_calling` | infra | `code_execution_20260120` + `allowed_callers` 도구 | `tool_use.caller.type == code_execution_20260120` + `container.id` | ga / no / no / no |
| 26 | `tool_search` | infra | `tool_search_tool_regex_20251119` + defer 도구 3개 (Bedrock invoke는 `anthropic_beta: tool-search-tool-2025-10-19`) | `tool_search_tool_result.tool_references` | ga / ga / ga / **no**(AWS: InvokeModel only) |
| 27 | `compaction` | context | beta `compact-2026-01-12`, `context_management.edits[compact_20260112, trigger 50000]` 소량 요청 | acceptance (+CP capability `compact_20260112.supported`) | beta / beta / beta / **no**(AWS: Converse 미지원) |
| 28 | `context_editing` | context | beta `context-management-2025-06-27`, `edits[clear_thinking_20251015]` | 응답 `context_management.applied_edits` 존재 | beta / beta / beta / unknown |
| 29 | `automatic_prompt_caching` | context | 최상위 `cache_control` + 안정 프리픽스(≥1,500 토큰), 2회 순차 | 1차 `cache_creation_input_tokens>0` 또는 2차 `cache_read_input_tokens>0` | ga / ga / ga / n.a.(Converse 표현 불가) |
| 30 | `prompt_caching_5m` | context | 블록 `cache_control ephemeral`, 2회 | 2차 `cache_read_input_tokens>0` | ga / ga / ga / ga (`cachePoint`) |
| 31 | `prompt_caching_1h` | context | `cache_control {ttl: 1h}`, 2회 | `cache_creation.ephemeral_1h_input_tokens>0` 또는 2차 read>0 | ga / ga / ga / ga (`cachePoint.ttl: 1h`) |
| 32 | `token_counting` | context | count_tokens (cp `/v1/messages/count_tokens`, mantle `/anthropic/v1/messages/count_tokens`, bedrock `CountTokens` invokeModel/converse) | `input_tokens > 0` | ga / ga / ga / ga |
| 33 | `files_api` | files | `POST /v1/files`(텍스트 1KB) → GET → DELETE | `type: file` + 삭제 200 | beta / no / no / no |
| E1 | `models_api` | endpoints | `GET /v1/models/{id}` | id 일치 + `capabilities` 존재 | ga / no / no / no |

행 39개. 프롬프트 캐싱 최소 토큰(Fable 5.1/5·Opus 5 = 512, Sonnet 5 = 1,024)을 넘기도록 패딩은 ≥1,500 토큰.
샘플링 파라미터(`temperature` 등)는 전송하지 않는다(Fable/Opus 5/Sonnet 5는 비기본값 400).

## Architecture

```
backend/claude_features/
├── catalog.py      FEATURES(39) · GROUPS(7) · SURFACES(4) · MODELS(4) · documented 기대치 · is_applicable()
├── transports.py   CpTransport / MantleTransport / BedrockInvokeTransport / BedrockConverseTransport
│                   공통 인터페이스: messages(body, betas, stream) · count_tokens(body) · get(path) · post(path, body) · delete(path)
│                   응답 정규화 NormalizedResponse{content_blocks, usage{input,output,cache_read,cache_creation,cache_1h}, stop_reason, raw, top_level}
├── probes.py       피처당 함수 1개: probe_<id>(transport, model) -> ProbeOutcome — 본문은 Anthropic Messages 스키마로만 작성
├── engine.py       verdict(documented, observed) -> match|drift|undocumented|none · aggregate_cell() · diff_runs() (순수 함수, 단위 테스트)
└── runner.py       run_features(surfaces, features, models) -> run_id — 잡 팬아웃 → ThreadPoolExecutor(4) → 메인 스레드 일괄 저장
backend/features_runner.py   CLI: --once [--surfaces cp,mantle,...] [--features id,...] [--models fable-5-1,...] [--smoke]
backend/routers/features.py  /api/features/{catalog,latest,evidence,trigger}
```

**전송기 규약**
- 본문은 항상 Anthropic Messages JSON. `BedrockInvokeTransport`는 `model`/`stream`을 제거하고 `anthropic_version: bedrock-2023-05-31`을
  주입하며 `betas` → body `anthropic_beta` 리스트로 변환. `CpTransport`/`MantleTransport`는 `betas` → `anthropic-beta` 헤더(콤마 구분),
  `anthropic-version: 2023-06-01`. `BedrockConverseTransport`는 프로브가 넘긴 Converse 전용 매핑(`converse_kwargs`)만 받는다 —
  Messages 본문을 자동 변환하지 않는다(변환 오류가 판정을 오염시키므로). Converse로 표현 불가한 피처는 `is_applicable()`이
  `not_applicable`로 기록하고 호출하지 않는다.
- 엔드포인트형 피처(batches/files/models/skills)는 전송기의 `routes` 집합으로 판정: 라우트가 없는 전송기(Bedrock 두 열)는
  호출 없이 `unsupported` + 사유 "라우트 부재". Mantle은 `/anthropic/v1/...`로 실제 호출해 404를 실측한다.
- 타임아웃: httpx 90s(read), boto `Config(read_timeout=90, connect_timeout=10, retries={max_attempts: 2, mode: standard})`.
  Mantle bearer는 전송기 인스턴스에서 1회 생성해 런 동안 재사용(≤12h).
- 오류 분류는 `parity.engine.classify_error` 재사용 + 본 기능 추가 마커(`unknown field`, `not supported for this model`,
  `does not support tool types`, `Extra inputs are not permitted`). `AccessDenied`/`Throttling`/timeout은 `broken`.

**상태 어휘 (`observed`)**: `supported | unsupported | broken | inconclusive | skipped | not_applicable`
- `inconclusive`: 도구 정의는 수락됐지만 모델이 도구를 호출하지 않아 증거를 못 얻은 경우(서버 도구·advisor·MCP). unsupported/broken과 구분.
- `not_applicable`: 설계상 부적용 — Mantle Fable 5.1(US GovCloud), Converse 표현 불가 피처, 모델 제약(extended_thinking).
- `skipped`: 검증 경로 없음(1M on mantle/bedrock).

**판정 (`verdict`)** — `engine.verdict(documented, observed)`:
- (ga|beta, supported) → `match` · (no, unsupported) → `match`
- (ga|beta, unsupported|broken) → `drift` · (no, supported) → `undocumented`
- observed ∈ {inconclusive, skipped, not_applicable} 또는 documented = unknown → `none`

셀(피처 × surface)은 모델별 결과를 집계한다: 적용 모델 전부 supported → supported, 일부만 → `partial`(카운트), broken 1건 이상 →
broken 우선 표시. 펼치면 모델 행. 드리프트 배너는 `verdict == drift` 셀 목록.

## Data model

```python
class FeatureRun(Base):            # feature_runs
    id, started_at, finished_at, status ("running|completed|failed"), totals JSON, catalog_version TEXT, error_message TEXT
class FeatureResult(Base):         # feature_results  (Index run_id; Index (run_id, feature))
    id, run_id FK, feature, surface, model_key, model_label, status, documented, verdict,
    latency_ms, evidence JSON, error_message TEXT
```
- 별도 테이블 — 패리티 `/api/parity/latest`(테이블 최신 completed 런 전제) 오염 방지.
- `create_tables()`로 생성(runner 기동 + backend lifespan). 보존: runner 종료 시 최근 60런 초과분 삭제.
- 런 실패 시 `status="failed"` + `error_message` 기록(패리티의 공백 보완).

## API

| 메서드/경로 | 인증 | 응답 |
|---|---|---|
| `GET /api/features/catalog` | 공개 | `{groups, surfaces(라벨·리전·모델 id 맵), models, features[{id, group, label_*, desc_*, doc_url, documented, verification, notes}]}` |
| `GET /api/features/latest` | 공개, `s-maxage=60` | `{run, previous_run_id, changes[], drift[], results[{feature, surface, model_key, model_label, status, documented, verdict, latency_ms}]}` |
| `GET /api/features/evidence?run_id&feature&surface&model_key` | 공개 | `{…, evidence:{request, response 요약, attempts[]}, error_message, doc_url, documented}` |
| `POST /api/features/trigger` | JWT | `{triggered, message}` — backend 내 백그라운드 스레드, 프로세스 로컬 락 |

## Frontend

- `src/app/claude-features/page.tsx` — gpt-on-aws 셸 복사(`useNavItems("features")`).
- `AppHeader.tsx` nav: `{ key: "features", label: L("Claude API Features", "Claude API 기능"), href: "/claude-features" }` — `gptbench` 뒤·`manual` 앞. 주석 "표준 10개"→11개. 데스크톱 폭 확인.
- `src/components/ClaudeFeaturesPanel.tsx` — ParityPanel 골격 copy-adapt: 상단 엔드포인트 헬스 카드 5개(supported/(supported+broken)), 드리프트 배너(`verdict == drift`), 7그룹 헤더(core → model → server → client → infra → context → files/endpoints), 피처 행 × 5열(Bedrock runtime은 Messages API·InvokeModel·Converse 3열을 한 그룹 헤더 아래), 셀 클릭 → 증거 모달(요청 스냅샷·응답 요약·attempts·에러·문서 링크·문서 기대치·검증 강도 배지), 상태 필터 칩, 수동 트리거(JWT), 직전 런 diff. KO/EN은 인라인 `L(en, ko)`.
- 순수 로직은 `src/lib/claudeFeatures.ts`(타입·상태 스타일·`aggregateCell`·`verdictOf`·그룹 계산) + `src/lib/claudeFeatures.test.ts`(vitest).
- `src/lib/api.ts` 하단에 `// ── Claude API Features (v2.23.0)` 섹션: 타입 + `fetchFeaturesCatalog/Latest/Evidence`, `triggerFeaturesRun`.

## Infra

- `cdk/lib/stacks/scheduler-stack.ts`: `buildTaskDef("FeaturesVerifyTaskDef", autoProberTaskRole, ["python","-m","features_runner","--once"], "/ecs/features")`,
  `rate(24 hours)`, `RunTaskFamilyWildcard` resources에 family 추가. IAM 추가 불필요(bedrock:* · bedrock-mantle:* 체인 기존, CP는 API 키).
- env(두 스택 공통): `MANTLE_ANTHROPIC_REGION=us-east-1`(명시), `FEATURES_MCP_SERVER_URL`(선택). 신규 secret 없음.
- `cdk/test/scheduler-stack.test.ts`: 현재 stale(3 기대 vs 실제 4)로 실패 중 → Schedule/TaskDef 5로 갱신 + `rate(24 hours)` 테스트 추가.
- 알람/DLQ는 기존 잡과 동일하게 미도입. 실패 감지는 `/ecs/features` 로그 + `feature_runs.status`.

## Testing & rollout

1. **단위 테스트** `backend/tests/test_claude_features.py`: 카탈로그 정합(39행·5 surface·documented 값 도메인·doc_url 존재), `is_applicable` 규칙(Mantle Fable 5.1 n.a., Converse 표현 불가, 라우트 부재), `verdict`/`aggregate_cell`/`diff_runs`, 전송기의 betas 매핑(헤더 vs body)과 InvokeModel 본문 변환, 증거 검사 함수. 프론트 `claudeFeatures.test.ts`.
2. **로컬 라이브 스모크**(python3.12, 현 IAM 롤, SSM 키): `python -m features_runner --smoke --models sonnet-5` → 5 surface × 39피처 표 출력, DB 미기록. 프로브 결함(패리티 run #1 `max_tokens=64` false-Broken 재현)을 배포 전에 걸러낸다. 이어 4모델 전체 1런.
3. **배포**: 이미지 빌드(immutable tag) → `cdk deploy BedrockMonitor-AppServices BedrockMonitor-Scheduler`(digest 고정) → CloudFront invalidation → 첫 스케줄/수동 런 로그 확인.
4. **문서**: ADR-026, CHANGELOG v2.23.0(KO/EN), 버전 6곳, README 페이지 수 9→10 + 주기 잡 bullet, CLAUDE.md 트리·환경변수, `docs/architecture.md` 잡 표·로그 그룹, `backend/CLAUDE.md`·`routers/CLAUDE.md`·`frontend/CLAUDE.md`·`components/CLAUDE.md`.

## Risks / open items (실측으로 닫는다)

- Mantle `anthropic-beta` 헤더 지원 여부(Anthropic P-AWS 비교표 "미지원" vs AWS 문서 "헤더로 전달") → 베타 피처 전부에서 실측.
- Mantle/InvokeModel structured outputs 문서 상충 → 실측.
- computer use: 대표 4모델은 `computer_toolset_20260801` 전용 모델군인데 P-AWS/Bedrock은 toolset 미제공 → CP에서도 미지원으로 나올 수 있음(정상 발견).
- MCP 커넥터는 공개 MCP 서버 의존 → 서버 장애는 `inconclusive`로 격리.
- `search_results` Converse는 AWS 문서상 구모델만 → 대표 모델에서 unsupported 가능(문서 기대치 notes).
