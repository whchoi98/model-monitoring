# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다.

작성 규칙:
- 최신 변경 사항이 위에, 과거 변경이 아래에 옵니다.
- 카테고리: `Added` / `Changed` / `Fixed` / `Removed` / `Security` / `Infra` / `Docs`
- 매 commit 시 PR 또는 작업 종료 시 한 항목 추가.

## v2.23.1 — 2026-09-05

### Changed
- **Claude API Features UI polish** (`/claude-features`): the Mantle column header now reads "Bedrock Mantle" (was "Bedrock Mantle /anthropic"); a **Note line under the matrix** states that Fable 5.1 cannot be measured on Bedrock Mantle because Mantle serves it only in US GovCloud (us-gov-west-1) — cells stay N/A; cells that are `skipped` for lack of a verification path while the docs say GA/Beta (e.g. 1M context window on Mantle/Bedrock) now render as **"Documented"** (sky badge, explicitly not a measurement) instead of "Skipped"; surface header titles and cell contents are center-aligned; the unsupported verdict wording became "확실한 미지원 응답".
- **Claude API Features UI 다듬기** (`/claude-features`): Mantle 열 제목을 "Bedrock Mantle"로 변경(기존 "Bedrock Mantle /anthropic"); 표 하단 **참조 줄**에 Fable 5.1은 Mantle이 US GovCloud(us-gov-west-1) 리전에서만 서빙해 측정 불가임을 표기(셀은 N/A 유지); 실측 경로가 없어 `skipped`이지만 문서상 GA/Beta인 셀(예: Mantle/Bedrock의 1M 컨텍스트)은 "Skipped" 대신 **"문서상 지원"**(하늘색 배지, 측정값 아님 명시)으로 표기; surface 헤더 제목과 셀 내용을 가운데 정렬; 미지원 판정 문구를 "확실한 미지원 응답"으로 변경.
- **Punctuation**: Korean UI sentences on `/claude-features` use commas instead of middle dots (·) for enumerations; "How to read" items are numbered `1.`–`4.`; the group heading became "파일 및 엔드포인트".
- **문장 부호**: `/claude-features`의 한글 UI 문장에서 나열 구분을 가운데 점(·) 대신 쉼표로 변경; "읽는 법" 항목 번호를 `1.`~`4.` 형식으로; 그룹 제목은 "파일 및 엔드포인트"로.

### Infra (post-tag deploy fix)
- **Backend ECS health-check grace period 60s → 300s** (`FargateServiceConstruct.healthCheckGracePeriod`, backend only). The first v2.23.1 rollout (2026-09-06 00:00 UTC) was rolled back by the deployment circuit breaker: all three new backend tasks spent ~130s in the lifespan migration block (29 full-table-scan `UPDATE`/`DELETE` statements on `probe_results` that run on every boot) before `/api/health` opened, exceeding the default 60s grace. v2.23.0 had booted in 36s only because one statement hit the 30s `statement_timeout` and aborted the block early. During each attempt the queued `ALTER TABLE insights` blocked `/api/insights/latest` (30s timeouts) — the migration block itself is a follow-up item.
- **backend ECS 헬스체크 유예 60s → 300s** (`FargateServiceConstruct.healthCheckGracePeriod`, backend만). 첫 v2.23.1 롤아웃(2026-09-06 00:00 UTC)은 배포 서킷 브레이커로 롤백됨: 새 backend 태스크 3개가 모두 lifespan 마이그레이션 블록(매 기동마다 실행되는 `probe_results` 전수 스캔 `UPDATE`/`DELETE` 29문장)에 ~130초를 쓴 뒤에야 `/api/health`가 열려 기본 유예 60초를 초과. v2.23.0이 36초에 기동한 것은 한 문장이 30초 `statement_timeout`에 걸려 블록이 조기 중단된 우연. 각 시도 중 대기열에 걸린 `ALTER TABLE insights`가 `/api/insights/latest`를 막아 30초 타임아웃 발생 — 마이그레이션 블록 자체는 후속 과제.

### Fixed
- **Data residency (`inference_geo`) read as "Unsupported" on Bedrock** — the official data-residency doc states that on Amazon Bedrock the inference region is determined by the endpoint URL or inference profile, so `inference_geo` is *not applicable* there. The 15 Bedrock cells (Mantle, Messages API, InvokeModel, Converse × the measurable models) were classified `unsupported` (verdict match), which read as "Bedrock has no data residency". They are now pre-decided `not_applicable` (new catalog `_NOT_APPLICABLE_BY_DOC`) with the reason in the evidence modal; the row is labelled "데이터 레지던시 (inference_geo)" and a Note under the matrix explains it. Per run: 643 probes + 137 pre-decided (was 658 + 122). Cells update from the next FeaturesVerify run.
- **데이터 레지던시(`inference_geo`)가 Bedrock에서 "미지원"으로 읽히던 오해 수정** — 공식 데이터 레지던시 문서는 Amazon Bedrock에서는 엔드포인트 URL 또는 추론 프로파일이 추론 리전을 결정하므로 `inference_geo`가 *비적용*이라고 명시. Bedrock 15셀(Mantle, Messages API, InvokeModel, Converse × 측정 가능 모델)이 `unsupported`(match)로 분류되어 "Bedrock은 데이터 레지던시가 안 된다"로 읽혔음. 이제 사전판정 `not_applicable`(카탈로그 `_NOT_APPLICABLE_BY_DOC` 신설)로 분류하고 사유를 증거 모달에 표기, 행 라벨은 "데이터 레지던시 (inference_geo)", 표 하단 참조에 설명 추가. 런당 프로브 643 + 사전판정 137(기존 658 + 122). 셀은 다음 FeaturesVerify 런부터 반영.

## v2.23.0 — 2026-09-05

### Added
- **Claude API Features page (`/claude-features`)** — every feature on platform.claude.com "Build with Claude" (33) plus 4 core Messages checks and the Models API, executed for real against Claude Platform on AWS, Bedrock Mantle `/anthropic` (`us-east-1`) and Bedrock runtime (Messages API + InvokeModel + Converse sub-columns) with Claude Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5 (Mantle excludes Fable 5.1 — US GovCloud only). Each cell carries the documented availability (GA/Beta/—) next to the observed status; a **documentation-drift banner** lists cells documented as available but observed unsupported/broken. Evidence modal shows request snapshot, response signal, error, doc link and verification strength. New package `backend/claude_features/` (catalog 39 × 5 surfaces, raw httpx/boto3 transports, probes, pure engine, runner), tables `feature_runs`/`feature_results`, API `/api/features/{catalog,latest,evidence,trigger}`, CLI `features_runner --once|--smoke`. See ADR-026.
- **Claude API 기능 검증 페이지(`/claude-features`)** — platform.claude.com "Build with Claude"의 피처 33개 + 코어 Messages 4종 + Models API를 Claude Platform on AWS · Bedrock Mantle `/anthropic`(`us-east-1`) · Bedrock runtime(Messages API + InvokeModel + Converse 서브열)에서 Claude Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5로 실제 실행(Mantle은 Fable 5.1 제외 — US GovCloud 전용). 셀마다 문서상 가용성(GA/Beta/—)과 실측 상태를 병기하고, 문서상 제공인데 미지원/오류인 셀은 **문서 드리프트 배너**로 표시. 증거 모달에 요청 스냅샷·응답 신호·오류·문서 링크·검증 강도. 신규 패키지 `backend/claude_features/`(카탈로그 39 × 5 surface, raw httpx/boto3 전송기, 프로브, 순수 엔진, 러너), 테이블 `feature_runs`/`feature_results`, API `/api/features/{catalog,latest,evidence,trigger}`, CLI `features_runner --once|--smoke`. ADR-026 참조.
- **5th surface — Bedrock runtime · Anthropic Messages API (`bedrock_messages`)** — the matrix now also probes `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/messages` (Seoul), the route AWS recommends for new applications and for migrating from the Anthropic APIs. Cross-Region inference profile ids (`global.anthropic.claude-*`), a short-term token from `aws-bedrock-token-generator` as `x-api-key`, `anthropic-version` and `anthropic-beta` headers. The Bedrock column is now three sub-columns (Messages API · InvokeModel · Converse) and one run grows from 624 to 780 cells. Unknown routes on this endpoint answer with a coral `UnknownOperationException` (sometimes under HTTP 200), which the transport normalizes to `404` so they classify as `unsupported` instead of a false success/failure. Refs: https://docs.aws.amazon.com/bedrock/latest/userguide/build.html · https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html · https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html
- **5번째 surface — Bedrock runtime · Anthropic Messages API(`bedrock_messages`)** — `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/messages`(서울)를 매트릭스에 추가. AWS가 신규 애플리케이션과 "Migrating from Anthropic APIs"에 권장하는 경로로, 크로스리전 추론 프로파일 id(`global.anthropic.claude-*`) + `aws-bedrock-token-generator` 단기 토큰(`x-api-key`) + `anthropic-version`/`anthropic-beta` 헤더를 쓴다. Bedrock 열은 3개 서브열(Messages API · InvokeModel · Converse)이 되고 1런은 624셀 → 780셀로 늘어난다. 이 엔드포인트는 모르는 라우트에 coral `UnknownOperationException`(HTTP 200 본문으로 오는 경우도 있음)을 돌려주므로 전송기가 `404`로 정규화해 false-supported·false-broken 없이 `unsupported`로 판정한다. 참조: https://docs.aws.amazon.com/bedrock/latest/userguide/build.html · https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html · https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html

### Changed
- **Shared env `MANTLE_ANTHROPIC_REGION` now defaults to `us-east-1`** for the `FeaturesVerify`/`ParityRun`/`GptBench`/`AutoProber`/`Insights` scheduler tasks and the backend service (CDK-injected; was `ap-northeast-1`) — user decision on 2026-09-05, because `ap-northeast-1` serves only Opus 4.8 in this account while `us-east-1` serves the 4 Claude API Features representative models (`sonnet-5` verified 200). Because Parity Run's `messages_mantle` surface reads the same env, it also starts probing `us-east-1` from this release — expect more `Supported` cells there. The in-code fallback when the env is absent (`backend/parity/runner.py`) is unchanged at `ap-northeast-1`; CDK now injects the value explicitly everywhere.
- **공용 env `MANTLE_ANTHROPIC_REGION` 기본값이 `us-east-1`로 전환** — `FeaturesVerify`/`ParityRun`/`GptBench`/`AutoProber`/`Insights` 스케줄 태스크와 backend 서비스 전체(CDK 주입, 기존 `ap-northeast-1`) — 2026-09-05 사용자 결정. 이 계정에서 `ap-northeast-1`은 Opus 4.8만 서빙하고, Claude API Features 대표 4모델은 `us-east-1`에서 서빙(`sonnet-5` 200 확인)되기 때문. 패리티 런 `messages_mantle` surface도 같은 env를 읽으므로 이번 릴리스부터 `us-east-1`을 프로빙 — Supported 셀 증가 예상. env 미주입 시 코드 폴백(`backend/parity/runner.py`)은 여전히 `ap-northeast-1`이며, CDK가 모든 곳에 값을 명시적으로 주입한다.

### Infra
- New EventBridge schedule `FeaturesVerifySchedule` (`rate(24 hours)`) → Fargate `FeaturesVerifyTaskDef` (`python -m features_runner --once`, log group `/ecs/features`, autoprober task role reused). Env `MANTLE_ANTHROPIC_REGION=us-east-1` and `FEATURES_MCP_SERVER_URL` injected into all scheduler tasks and the backend service. One run = 658 probes + 122 pre-decided rows = 780 cells (39 features × 5 surfaces × 4 models); with 2-call caching probes and negative controls, ≈800 API calls. Daily cadence and the 5-surface cost estimate (≈$5–7 per run, ≈$150–210/month) approved by the user on 2026-09-05 (the earlier 4-surface estimate was $4–6). **New IAM**: `bedrock:CallWithBearerToken` added to the autoprober task role and the backend task role (alongside the pre-existing `bedrock-mantle:CallWithBearerToken`), Resource `*` — required for `BedrockMessagesTransport`'s `aws-bedrock-token-generator` short-term bearer sent as `x-api-key` to the bedrock-runtime Anthropic Messages route (`bedrock_messages` surface); AWS separates this Bedrock-endpoint action from the Mantle one, and `simulate-principal-policy` confirmed an implicit deny without it.
- 신규 EventBridge 스케줄 `FeaturesVerifySchedule`(`rate(24 hours)`) → Fargate `FeaturesVerifyTaskDef`(`python -m features_runner --once`, 로그 그룹 `/ecs/features`, autoprober 태스크 롤 재사용). env `MANTLE_ANTHROPIC_REGION=us-east-1`·`FEATURES_MCP_SERVER_URL`을 스케줄 태스크 전체와 backend 서비스에 주입. 1런 = 프로브 658 + 사전판정 122 = 780셀(39피처 × 5 surface × 4모델), 캐싱 프로브·부정 제어 포함 ≈800 API 호출. 일 1회 주기와 5 surface 기준 비용 추정(런당 ≈$5~7, 월 ≈$150~210)은 2026-09-05 사용자 승인 (4 surface 기준 초기 추정은 $4~6). **신규 IAM**: autoprober 태스크 롤과 backend 태스크 롤에 `bedrock:CallWithBearerToken`(Resource `*`) 추가 — 기존 `bedrock-mantle:CallWithBearerToken`과 별개로, `BedrockMessagesTransport`가 `aws-bedrock-token-generator` 단기 bearer를 `x-api-key`로 bedrock-runtime Anthropic Messages 라우트(`bedrock_messages` surface)에 보내는 데 필수. AWS는 이 Bedrock 엔드포인트 액션을 Mantle 액션과 별도로 구분하며, `simulate-principal-policy`로 미추가 시 implicit deny를 확인했다.

### Fixed
- `cdk/test/scheduler-stack.test.ts` was stale since v2.18.0 (expected 3 schedules/task definitions, actual 4) and failed `make verify`; counts updated to 5 with the new task.
- v2.18.0 이후 낡아 `make verify`를 깨뜨리던 `cdk/test/scheduler-stack.test.ts`(기대 3, 실제 4) 카운트를 신규 태스크 포함 5로 갱신.

### Notes
- Live smoke (2026-09-05, sonnet-5 full sweep, run against `ap-northeast-1` before the region switch above): Bedrock Mantle `/anthropic` in `ap-northeast-1` serves only Opus 4.8 in this account — `anthropic.claude-{fable-5,opus-5,sonnet-5}` return `not_found_error` (`us-east-1` serves sonnet-5) — this is the finding that drove the `MANTLE_ANTHROPIC_REGION` default switch to `us-east-1`. Bedrock InvokeModel and Converse reject `output_config.format`/`strict: true` with "Extra inputs are not permitted" for the Claude 5 generation, and Bedrock `CountTokens` does not support these CRIS-only (`global.*`) models — catalog `documented` expectations for `token_counting`/`structured_outputs`/`strict_tool_use` updated to match. `browser_toolset_20260801` works on CP on AWS and Bedrock InvokeModel although the docs list it as unavailable (recorded as `undocumented`, catalog notes updated).
- 라이브 스모크(2026-09-05, sonnet-5 전체 스윕, 위 리전 전환 전 `ap-northeast-1` 기준으로 실행): Bedrock Mantle `/anthropic`의 `ap-northeast-1`은 이 계정에서 Opus 4.8만 서빙 — `anthropic.claude-{fable-5,opus-5,sonnet-5}`는 `not_found_error`(`us-east-1`은 sonnet-5 서빙) — 이 발견이 `MANTLE_ANTHROPIC_REGION` 기본값을 `us-east-1`로 전환시킨 근거다. Bedrock InvokeModel·Converse는 Claude 5 세대에서 `output_config.format`/`strict: true`를 "Extra inputs are not permitted"로 거부하고, Bedrock `CountTokens`는 이 CRIS 전용(`global.*`) 모델들을 미지원 — 카탈로그 `documented` 기대치(`token_counting`/`structured_outputs`/`strict_tool_use`)를 실측에 맞춰 갱신. `browser_toolset_20260801`은 문서상 미제공이지만 CP on AWS·Bedrock InvokeModel에서 동작(`undocumented`로 기록, 카탈로그 notes 갱신).
- **Full sweep — 4 models × 5 surfaces, 780 cells (39 features × 5 surfaces × 4 models), 2026-09-05**: **broken 0 / inconclusive 0** after two probe fixes (the first full run recorded broken 39). Totals: supported 419 · unsupported 221 · skipped 15 · not_applicable 125; verdicts match 590 · drift 25 · undocumented 14 · none 151. `token_counting`, `models_api`, `files_api` and `batch_processing` are cleanly absent on `bedrock_messages`: the first three answer with a coral `UnknownOperationException`, and `/v1/messages/batches` falls through to the SigV4 front door (403 "Authorization header is missing") because the two auth schemes are mutually exclusive. `tool_search` works there even though AWS documents it for InvokeModel only (expectation left `unknown`). Per-surface × model breakdown and triage in ADR-026 and `task-12-report.md`.
- **전체 스윕 — 4모델 × 5 surface, 780셀(39피처 × 5 surface × 4모델), 2026-09-05**: 프로브 결함 2건 수정 후 **broken 0 / inconclusive 0**(최초 전체 실행은 broken 39). 합계: supported 419 · unsupported 221 · skipped 15 · not_applicable 125; 판정 match 590 · drift 25 · undocumented 14 · none 151. `bedrock_messages`에서 `token_counting`·`models_api`·`files_api`·`batch_processing`은 깨끗하게 부재로 확인 — 앞 3개는 coral `UnknownOperationException`, `/v1/messages/batches`는 SigV4 프론트도어로 떨어져 403 "Authorization header is missing"(두 인증 스킴이 배타적). `tool_search`는 AWS 문서가 InvokeModel만 명시하는데도 이 경로에서 동작(기대치 `unknown` 유지). surface×모델별 세부와 트리아지는 ADR-026·`task-12-report.md` 참조.
- **Drift 25 breaks into two clusters, not 25 isolated feature gaps**: 23 cells are Mantle (`us-east-1`) Fable 5 rejecting every probed feature with `data retention mode 'default' is not available for this model` (one account-level Covered-Model data-retention opt-in, not a probe defect — resolving it is an account/org decision, catalog expectations were deliberately left unchanged), plus 2 cells where Mantle rejects the `fallback_credit` beta header (a real surface gap). All 14 `undocumented` rows are `browser_use` (`browser_toolset_20260801`) working on cp (4 models) / mantle (opus-5, sonnet-5) / bedrock_messages (4 models) / bedrock_invoke (4 models) though undocumented; Converse has no field to express it. The sweep also tightened the caching verdict: all three caching probes now require the **second call's `cache_read_input_tokens > 0`** (creation/`ephemeral_1h` fields are supporting evidence only, no longer a passing condition) — the old creation-only OR branch had let 5 rows pass without proving reuse (4 safety refusals + 1 normal cache miss on `bedrock_messages`/Fable 5).
- **드리프트 25건은 개별 피처 갭이 아니라 클러스터 2개로 수렴**: 23셀은 Mantle(`us-east-1`) Fable 5가 프로브된 모든 피처를 `data retention mode 'default' is not available for this model`로 거부(계정 단위 Covered Model 데이터 보존 opt-in 미적용 하나의 원인 — 프로브 결함이 아니라 계정/조직 결정 항목, 카탈로그 기대치는 의도적으로 유지), 나머지 2셀은 Mantle이 `fallback_credit` beta 헤더를 거부(실제 surface 갭). `undocumented` 14건은 전부 `browser_use`(`browser_toolset_20260801`)가 cp(4모델)·mantle(opus-5, sonnet-5)·bedrock_messages(4모델)·bedrock_invoke(4모델)에서 문서 없이 동작(Converse는 표현 필드 없음). 이번 스윕에서 캐싱 판정식도 강화 — 캐시 3프로브 전부 **2차 호출 `cache_read_input_tokens > 0`**을 요구(생성/`ephemeral_1h` 필드는 이제 보조 증거일 뿐, 통과 조건 아님) — 종전 창작-only OR 분기는 재사용을 증명하지 않고도 5행(안전 거부 4건 + `bedrock_messages`/Fable 5 정상 캐시 미스 1건)을 통과시켰다.

## v2.22.1 — 2026-09-01

### Fixed
- **History view showed "Anthropic Claude Fable 5 (US)" twice and no Fable 5.1 CP entry.** Root cause: the CP on AWS workspace began serving `claude-fable-5-1` at 17:52 UTC on 2026-09-01, and the pre-v2.22.0 substring matcher (`"fable-5" in id`) registered that id under the Fable 5 label — 53 `probe_results` rows for `model_id=anthropic:claude-fable-5-1` carry the wrong `model_name`. `/api/results/stats` labelled each model_id group by its oldest row, so the 5.1 group surfaced as a duplicate Fable 5. Fixes: (1) stats now takes the label from the live catalog (`AVAILABLE_MODELS`, falling back to the newest row); (2) new `label_repair.py` runs at backend startup in its own transaction and rewrites stored `model_name` to the catalog label for any catalogued model_id (`probe_results` + `probe_results_hourly`), so trend/analysis/cost views heal too. The old `_label_renames` block is currently dead in production — its transaction rolls back on the `ALTER TABLE probe_runs` statement timeout at every startup since at least 2026-08-19 (pre-existing, logged as "Migration block failed").
- **이력 조회에 "Anthropic Claude Fable 5 (US)"가 두 번 보이고 Fable 5.1 CP 항목이 없던 문제.** 원인: CP on AWS 워크스페이스가 2026-09-01 17:52 UTC부터 `claude-fable-5-1`을 서빙했고, v2.22.0 이전 substring 매칭(`"fable-5" in id`)이 이 id를 Fable 5 라벨로 등록 → `model_id=anthropic:claude-fable-5-1` 행 53건의 `model_name`이 오기재. `/api/results/stats`가 model_id 그룹의 가장 오래된 행 라벨을 쓰므로 5.1 그룹이 Fable 5 중복으로 표시됨. 수정: (1) 통계 라벨을 현행 카탈로그(`AVAILABLE_MODELS`, 없으면 최신 행)에서 취득, (2) 신규 `label_repair.py`가 backend 기동 시 별도 트랜잭션으로 카탈로그 model_id의 저장 `model_name`을 카탈로그 라벨로 정정(`probe_results` + `probe_results_hourly`) → 추이/분석/비용 화면도 함께 복구. 기존 `_label_renames` 블록은 같은 트랜잭션의 `ALTER TABLE probe_runs` statement timeout으로 최소 2026-08-19부터 매 기동 롤백되는 상태(기존 문제, "Migration block failed" 로그).
- `/api/results/stats` called without `start_time`/`run_id` now defaults to the last 24h instead of loading the whole `probe_results` table into ORM objects — an unbounded call OOM-killed the backend container (1024 MB, exit 137, ~2 min outage) on 2026-09-01.
- `/api/results/stats`를 `start_time`/`run_id` 없이 호출하면 전체 `probe_results`를 ORM으로 적재하던 것을 최근 24h 기본값으로 한정 — 2026-09-01 기간 미지정 호출이 backend 컨테이너 OOM(1024MB, exit 137, 약 2분 중단)을 유발.

## v2.22.0 — 2026-09-01

### Added
- **Claude Fable 5.1** joins the monitored catalog in all 3 Claude channels (active catalog 40 → 43): Bedrock Global (`global.anthropic.claude-fable-5-1`, Seoul), Bedrock US (`us.anthropic.claude-fable-5-1`, us-east-1) and Anthropic CP on AWS (pre-registered `fable-5-1` discovery target — auto-registers as soon as the workspace serves it). Both Bedrock inference profiles verified ACTIVE and live-probed (`pong` / `end_turn`) before the change. Same Covered-Model constraints and price tier as Fable 5 ($10 / $50 per MTok). Frontend: `FAMILY_ORDER` (Fable 5.1 on top), `MODEL_COLORS` (3 sky-blue entries), Comparison Lab names, OptimizePrompt targets.
- **Claude Fable 5.1** 을 Claude 3채널 전부에 모니터링 대상으로 편입 (활성 카탈로그 40 → 43): Bedrock Global(`global.anthropic.claude-fable-5-1`, Seoul), Bedrock US(`us.anthropic.claude-fable-5-1`, us-east-1), Anthropic CP on AWS(`fable-5-1` 발견 타깃 선등록 — 워크스페이스에서 서빙되는 즉시 자동 등록). 두 Bedrock 프로파일은 변경 전 ACTIVE 확인 + 라이브 프로브(`pong` / `end_turn`) 검증. Covered Model 제약·단가 티어는 Fable 5와 동일($10 / $50 per MTok). 프론트: `FAMILY_ORDER` 최상단, `MODEL_COLORS` 3개(sky 계열), Comparison Lab 이름, OptimizePrompt 대상.

### Changed
- Parity Run `tool_use` probe now uses `tool_choice: auto` + prompt instruction on models that reject forced tool choice (`parity/catalog.py` `supports_forced_tool_choice()` — Fable 5.1 returns 400 on `type: tool`/`any`). Other models keep the forced-tool probe unchanged.
- 패리티 런 `tool_use` 프로브가 forced tool_choice를 거부하는 모델에서는 `tool_choice: auto` + 프롬프트 지시로 동작 (`parity/catalog.py` `supports_forced_tool_choice()` — Fable 5.1은 `type: tool`/`any`에 400). 그 외 모델은 기존 강제 도구 프로브 그대로.

### Fixed
- CP on AWS model discovery (`_discover_anthropic_models`) could mislabel a longer model id with a shorter target's label when substrings overlap (`fable-5` ⊂ `fable-5-1`), depending on `/v1/models` ordering. New `_match_anthropic_model()` excludes ids that contain a longer registered target.
- CP on AWS 모델 자동 발견(`_discover_anthropic_models`)이 substring 접두 충돌(`fable-5` ⊂ `fable-5-1`) 시 `/v1/models` 순서에 따라 긴 id에 짧은 타깃 라벨을 붙일 수 있던 문제 수정. 신규 `_match_anthropic_model()`이 더 긴 등록 타깃을 포함하는 id를 후보에서 제외.

## v2.21.0 — 2026-08-18

### Added
- **iPhone/iPad installable app (PWA)** — Safari Share → "Add to Home Screen" now installs the dashboard as a full-screen standalone app. Web app manifest (`src/app/manifest.ts` → `/manifest.webmanifest`) + generated app icons (emerald pulse glyph on dark gradient; regular + maskable variants, `app/icon.png`·`app/apple-icon.png` conventions) + iOS meta tags (`appleWebApp`, black-translucent status bar) + `viewport-fit=cover` with safe-area padding for the notch/Dynamic Island/home indicator (standalone-only via `display-mode: standalone` media query). Middleware `no-store` matcher excludes the new static PWA assets.
- **iPhone/iPad 설치형 앱 (PWA)** — Safari 공유 → "홈 화면에 추가"로 대시보드를 전체화면 standalone 앱으로 설치. Web app manifest(`src/app/manifest.ts` → `/manifest.webmanifest`) + 생성 앱 아이콘(다크 그라데이션 + 에메랄드 펄스, 일반/maskable 변형, `app/icon.png`·`apple-icon.png` 컨벤션) + iOS 메타태그(`appleWebApp`, 반투명 상태바) + `viewport-fit=cover`와 노치/Dynamic Island/홈 인디케이터 safe-area 패딩(설치형에서만 적용되는 `display-mode: standalone` 미디어 쿼리). middleware `no-store` matcher에서 신규 PWA 정적 자산 제외.

### Fixed
- Synced runtime-visible version strings during release finalization: FastAPI OpenAPI version was stuck at 2.0.0 (now 2.21.0), `frontend/package.json` at 1.0.0, root CLAUDE.md overview at v2.19.2. Canonical locations are now listed in CLAUDE.md "Version strings".
- 릴리스 마무리 과정에서 런타임 노출 버전 문자열 동기화: FastAPI OpenAPI 버전이 2.0.0으로 고착(→ 2.21.0), `frontend/package.json` 1.0.0, 루트 CLAUDE.md 개요 v2.19.2 교정. 정식 위치 목록을 CLAUDE.md "Version strings" 절로 신설.

## v2.20.1 — 2026-08-18

### Added
- GPT on AWS bench (`/gpt-on-aws`) now includes the **GPT 5.6 Terra Global CRIS** channel (8 → 9 channels, user-approved). Same key/label convention as the prober (`openai:global:global.openai.gpt-5.6-terra`, `(Global)`); routed via the Seoul bedrock-runtime OpenAI-compat endpoint (`OPENAI_GLOBAL_BASE_URL`). Panel gets a violet region color + updated legend/description. Estimated cost +~$20/day on top of the existing ~$150/day. GPT 5.4/5.5 have no global profile; Sol/Luna remain out of bench scope.
- GPT on AWS 벤치(`/gpt-on-aws`)에 **GPT 5.6 Terra Global CRIS** 채널 편입 (8 → 9채널, 사용자 승인). prober와 동일한 키/라벨 규약(`openai:global:global.openai.gpt-5.6-terra`, `(Global)`), Seoul bedrock-runtime OpenAI-compat 엔드포인트(`OPENAI_GLOBAL_BASE_URL`) 경유. 패널에 보라색 리전 색상 + 범례/설명 갱신. 비용 추정 기존 ~$150/일 대비 +~$20/일. GPT 5.4/5.5는 global 프로파일 미지원, Sol/Luna는 벤치 대상 아님(기존 결정 유지).

## v2.20.0 — 2026-08-18

### Added
- OpenAI GPT-5.6 (Sol/Terra/Luna) Bedrock **Global cross-region inference** channels — 3 new monitored channels (active catalog 37 → 40), announced by AWS on 2026-08-17 (5.6 generation only; 5.4/5.5 unsupported). Key scheme `openai:global:global.openai.gpt-5.6-*` (pseudo-region `global`, profile id derived by prepending `global.` — no new model-id env), label `OpenAI GPT 5.6 * (Global)`. Called via the Seoul bedrock-runtime OpenAI-compat endpoint (`OPENAI_GLOBAL_BASE_URL`, reuses the existing Mantle bearer key) because the bedrock-mantle host does not support global profiles. Pricing is channel-split with `-global` suffix keys since Global CRIS is cheaper than in-region (Sol $5/$30, Terra $2/$12, Luna $0.20/$1.20 per MTok). See ADR-025.
- OpenAI GPT-5.6 (Sol/Terra/Luna) Bedrock **Global cross-region inference** 채널 3개 추가 (활성 카탈로그 37 → 40) — 2026-08-17 AWS 발표(5.6 세대만, 5.4/5.5 미지원). 키 스킴 `openai:global:global.openai.gpt-5.6-*`(pseudo-region `global`, 프로파일 id는 `global.` 접두사 파생 — 신규 model-id env 없음), 라벨 `OpenAI GPT 5.6 * (Global)`. global 프로파일은 bedrock-mantle 호스트 미지원이라 Seoul bedrock-runtime OpenAI-compat 엔드포인트(`OPENAI_GLOBAL_BASE_URL`, 기존 Mantle bearer 키 재사용)로 호출. Global CRIS 단가가 in-region보다 저렴해 `-global` suffix 키로 가격 분리 (Sol $5/$30, Terra $2/$12, Luna $0.20/$1.20 per MTok). ADR-025 참조.

### Fixed
- Pricing table: GPT-5.6 in-region rates corrected to reflect the 2026-07-30 AWS price reduction (Luna -80%, Terra -20%; Sol unchanged at the official $5.50/$33 — the previous "1P parity $5/$30" entry was stale). Cost dashboards recalculate retroactively at the corrected rates (same policy as the v2.19.0 Opus correction).
- 가격 테이블: GPT-5.6 in-region 단가를 2026-07-30 AWS 인하 반영으로 교정 (Luna -80%, Terra -20%; Sol은 공식 $5.50/$33 — 기존 "1P parity $5/$30" 기재는 낡은 값). 비용 대시보드는 교정 단가로 소급 재계산 (v2.19.0 Opus 교정과 동일 정책).

### Infra
- EventBridge Scheduler invoke role: added the missing `gptbench` task-def family `:*` wildcard to `ecs:RunTask` (ADR-011 hardening — prevents silent schedule failure after a manual task-def revision bump).
- EventBridge Scheduler invoke role의 `ecs:RunTask`에 누락돼 있던 `gptbench` task-def family `:*` wildcard 추가 (ADR-011 예방 — 수동 revision bump 후 스케줄 silent fail 방지).

## v2.19.2 — 2026-08-01

### Changed
- AI insights job (Haiku 4.5) now excludes hidden `"(1P)"` channels from its stats collection (`insights_runner.collect_stats_for_window` / `run_once`) — completes the v2.19.1 exposure removal for AI-generated analysis. Chatbot tools were already filtered in v2.19.1.
- AI 인사이트 잡(Haiku 4.5)의 통계 수집(`insights_runner`)에서도 숨김 `"(1P)"` 채널을 제외 — v2.19.1 비노출 조치를 AI 생성 분석까지 확장. 챗봇 tools는 v2.19.1에서 이미 필터 적용됨.

## v2.19.1 — 2026-07-31

### Changed
- OpenAI 1P direct (Path 5, 5 channels) excluded from comparison/monitoring exposure per user decision — capability preserved, not deleted. Three-layer switch: CDK `ENABLE_OPENAI_1P=false` (env/secret not injected → prober silently skips registration), backend `visibility.py` read-layer filter hiding `"(1P)"` labels from all query APIs (results, auto-probe latest/trend/anomalies, cost, reliability, efficiency, analysis, chatbot tools) while DB rows are retained, frontend `EXCLUDED_FAMILIES` hard-filter. Active catalog 42 → 37. Background: the stored 1P key was revoked (401) as of 2026-07-31. Re-enable path: CDK flag true + valid key in SSM + `HIDDEN_MODEL_PATTERNS=""` + remove frontend filter entry.
- OpenAI 1P direct (Path 5, 5개 채널)를 사용자 결정으로 비교·모니터링 노출에서 제외 — 기능(코드)은 보존. 3중 스위치: CDK `ENABLE_OPENAI_1P=false`(env 미주입 → prober가 등록 조용히 skip), backend `visibility.py` 조회 계층 필터(`"(1P)"` 라벨을 모든 조회 API에서 숨김, DB 행은 보존), frontend `EXCLUDED_FAMILIES` 하드필터. 활성 카탈로그 42 → 37. 배경: 저장된 1P 키가 2026-07-31 기준 폐기(401) 상태. 재노출: CDK 플래그 true + 유효 키 SSM 저장 + `HIDDEN_MODEL_PATTERNS=""` + 프런트 필터 항목 제거.

## v2.19.0 — 2026-07-24

### Fixed
- Pricing table: Claude Opus 4.8 / 4.7 / 4.6 corrected from \$15/\$75 to the official \$5/\$25 per MTok (\$15/\$75 is Opus 4.1's rate). Cost dashboards recalculate retroactively at the corrected rate (user decision: display consistency over historical accuracy).
- 가격표: Claude Opus 4.8/4.7/4.6을 \$15/\$75 → 공식 \$5/\$25 per MTok로 교정 (\$15/\$75는 Opus 4.1 단가). 비용 대시보드는 교정 단가로 소급 재계산 (사용자 결정: 표시 일관성 우선).

### Added
- Claude Opus 5 (launched 2026-07-24) across all menus — Bedrock Global/US inference profiles (`global./us.anthropic.claude-opus-5`, both verified live), catalog 39 → 41. CP on AWS target pre-registered (auto-discovers when the org recovers → 42). Reasoning model (temperature rejected). Pricing $5/$25 per MTok (official).
- Claude Opus 5 전 메뉴 추가 (2026-07-24 출시) — Bedrock Global/US 추론 프로파일 2채널 (실측 검증), 카탈로그 39 → 41. CP on AWS 타깃 선등록 (조직 복구 시 자동 발견 → 42). reasoning 모델 (temperature 거부). 가격 $5/$25 per MTok (공식).

## v2.18.1 — 2026-07-22

### Fixed
- GPT on AWS: /latest now returns the most recent **completed** cycle (channel-wise commits exposed a running cycle's partial 4 cards for ~7 of every 15 minutes); /trend excludes the in-progress cycle's partial endpoint.
- GPT on AWS: /latest가 최신 **완료** 사이클을 반환 (채널 단위 커밋 탓에 실행 중 사이클의 부분 카드 4개가 노출되던 문제), /trend도 진행 중 사이클 끝점 제외.

### Added
- GPT on AWS: score cards are now clickable channel filters for the trend charts (empty selection = all — same rule as the dashboard), with an "All" reset and N/8 counter.
- GPT on AWS: 스코어 카드 클릭으로 그래프 채널 선택(빈 선택 = 전체 — 대시보드와 동일 규칙), "전체" 초기화 버튼과 N/8 카운터 추가.

## v2.18.0 — 2026-07-22

### Added
- **GPT on AWS** page (`/gpt-on-aws`): precision latency bench for Bedrock Mantle (3P) GPT channels — GPT 5.4 ×3 US regions + GPT 5.5 ×2 + GPT 5.6 Terra ×3 (8 channels). Every 15 minutes a scheduled Fargate task runs 10 sequential calls per channel with the fixed ~55.8k-token cached prompt (docs/benchmarks methodology): TTFB (first stream event) / TTFT (first text delta) / GAP (≈ thinking). Page shows per-channel score cards (median TTFB/TTFT/GAP, p95, cache hit rate, success) and per-cycle median trend charts with time-range control.
- **GPT on AWS** 페이지(`/gpt-on-aws`): Bedrock Mantle(3P) GPT 채널 정밀 레이턴시 벤치 — GPT 5.4 ×3리전 + 5.5 ×2 + 5.6 Terra ×3 (8채널). 15분마다 스케줄 태스크가 채널당 10회 순차 호출(~55.8k 토큰 고정 캐시 프롬프트, docs/benchmarks 방법론): TTFB/TTFT/GAP(≈thinking). 채널별 스코어 카드(median·p95·캐시 히트율·성공률)와 사이클별 median 시계열 그래프 + 기간 조절 제공.

### Infra
- New table `gpt_bench_results`, router `/api/gptbench/{latest,trend}` (public read), EventBridge schedule `rate(15 minutes)` → GptBench Fargate task (backend image, `python -m gptbench_runner --once`).
- 신규 테이블 `gpt_bench_results`, 라우터 `/api/gptbench/{latest,trend}`(공개 조회), EventBridge `rate(15 minutes)` → GptBench Fargate 태스크 (backend 이미지 공용).

## v2.17.1 — 2026-07-14

### Added
- Historical Stats panel: per-model filter chips (empty selection = all, same rule as the dashboard card filter). Selection persists across time-range changes.
- 이력 통계 패널: 모델별 선택 필터 칩 추가 (빈 선택 = 전체 — 대시보드 카드 필터와 동일 규칙). 조회 기간을 바꿔도 선택 유지.

## v2.17.0 — 2026-07-14

### Added
- OpenAI GPT-5.6 generation (Sol / Terra / Luna) across all menus — 11 new channels (Bedrock Mantle 8: Sol us-east-1/2, Terra·Luna us-east-1/2/west-2 + 1P direct 3), catalog 28 → 39. Sol is not offered in us-west-2. Responses-API-only like GPT-5.4/5.5. Bedrock in-region pricing at parity with OpenAI 1P (Sol $5/$30, Terra $2.5/$15, Luna $1/$6 per MTok — no 10% markup unlike 5.4/5.5).
- OpenAI GPT-5.6 세대(Sol/Terra/Luna)를 전 메뉴에 추가 — 신규 11채널 (Bedrock Mantle 8: Sol은 us-east-1/2, Terra·Luna는 us-east-1/2/west-2 + 1P direct 3), 카탈로그 28 → 39. Sol은 us-west-2 미제공. GPT-5.4/5.5와 동일하게 Responses API 전용. Bedrock in-region 가격은 OpenAI 1P와 동일(parity — Sol $5/$30, Terra $2.5/$15, Luna $1/$6 per MTok, 5.4/5.5식 10% 마크업 없음).

### Infra
- New env vars injected by CDK (AppServices + Scheduler): `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`, `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`.
- CDK(AppServices + Scheduler)가 주입하는 신규 env: `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`, `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`.

## v2.16.5 — 2026-07-12

### Added
- Real User Monitoring via aws-rum-pipeline: `RumProvider` loads the self-hosted RUM SDK and stamps every event with `appName: llm-monitor` (page views, SPA route dwell time, Core Web Vitals, JS errors). Enabled only when `NEXT_PUBLIC_RUM_ENDPOINT`/`NEXT_PUBLIC_RUM_API_KEY` are provided at build time (Docker build args).
- aws-rum-pipeline 연동 RUM(Real User Monitoring): `RumProvider`가 자체 호스팅 SDK를 로드해 모든 이벤트에 `appName: llm-monitor`를 스탬핑 (페이지뷰·SPA 체류시간·Core Web Vitals·JS 에러). 빌드 타임 `NEXT_PUBLIC_RUM_*` 주입 시에만 활성화 (Docker build args).

## v2.16.4 — 2026-07-12

### Changed
- Dashboard model cards: input/output tokens and the probe timestamp now share one line (was two rows).
- 대시보드 모델 카드: 입력/출력 토큰과 프로빙 시간을 한 줄로 병합 (기존 2줄).

## v2.16.3 — 2026-07-12

### Changed
- Parity provider cards: replace the donut chart with a horizontal segmented bar (health % + status distribution) — visually consistent with the feature summary rows.
- 패리티 provider 카드: 도넛 그래프를 가로 세그먼트 막대(헬스 % + 상태 분포)로 교체 — 피처 요약행 막대와 시각 언어 통일.

## v2.16.2 — 2026-07-12

### Fixed
- **Model Explorer i18n**: API descriptions, code comments, link labels, and the copy button now follow the selected language (they were Korean-only under EN).
- **Parity page i18n**: the feature catalog now serves `label_en`/`desc_en` so feature names, tooltips, and the changes banner localize; evidence-modal verdict sentences are bilingual.
- **Terminology**: "깨끗한 미지원" → "명시적 미지원" (UI·주석·문서) — 더 자연스러운 한국어 표현.
- **모델 탐색 i18n**: API 설명·코드 주석·링크 라벨·복사 버튼이 선택 언어를 따르도록 수정 (EN에서도 한글이 출력되던 문제).
- **패리티 페이지 i18n**: 카탈로그에 `label_en`/`desc_en` 추가 — 피처명·툴팁·변경 배너 현지화, 증거 모달 판정 문장 이중언어화.

## v2.16.1 — 2026-07-12

### Changed
- Move login-required menus (Manual Probe, Prompts) to the end of the top navigation — public pages (Dashboard, Models, Parity, Cost, Reliability, Efficiency, Analysis) come first.
- 로그인이 필요한 메뉴(수동 프로브·프롬프트)를 상단 내비 맨 뒤로 이동 — 공개 페이지(대시보드·모델 탐색·패리티 런·비용·신뢰성·효율성·분석)가 앞에 오도록 정렬.

## v2.16.0 — 2026-07-12

### Added
- **Mobile responsive layout**: a shared `AppHeader` component replaces the header duplicated across all 9 pages — desktop keeps the current horizontal nav (lg+), narrow screens get a hamburger menu with a vertical dropdown (page-specific actions included). The manual-probe sidebar stacks vertically on mobile and panel paddings tighten on small screens. Same URLs — layout adapts purely by viewport width.
- **모바일 반응형 레이아웃**: 9개 페이지에 중복돼 있던 헤더를 공용 `AppHeader`로 통합 — 데스크톱(lg+)은 기존 가로 내비 그대로, 좁은 화면은 햄버거(☰) 세로 드롭다운(페이지별 버튼 포함). 수동 프로브 사이드바는 모바일에서 세로 스택, 패널 패딩은 소형 화면에서 축소. URL 변경 없음 — 뷰포트 폭만으로 레이아웃 전환.

## v2.15.1 — 2026-07-12

### Fixed
- Classify "not yet supported" (URL sources on newer Claude models) as cleanly unsupported — the last 12 false-Broken cells from run #10.
- "not yet supported"(신형 Claude 모델의 URL 소스 거부 문구)를 깨끗한 미지원으로 분류 — run #10의 잔여 false-Broken 12셀 해소.

## v2.15.0 — 2026-07-12

### Added
- **Full feature catalog (12 → 19)**: reasoning_effort (effort param acceptance — Claude output_config / GPT reasoning effort), json_schema (strict schema output with key validation), url_sources (remote PDF document source), memory_tool / code_execution (beta server-tool acceptance), files_api (list round-trip), models_api (model retrieve round-trip). Admin/Usage APIs and MCP connector are intentionally excluded (cannot be probed honestly without an admin key / a live MCP server).
- **Collapsible feature matrix**: each feature renders as a summary row (bold name, status distribution bar, supported·unsupported·broken counts) that expands to per-model rows on click; features containing Broken cells auto-expand, search/status filters expand everything, plus expand-all / collapse-all buttons.
- **피처 카탈로그 완성 (12 → 19)**: reasoning_effort(effort 파라미터 수락 — Claude output_config / GPT reasoning effort), json_schema(strict 스키마 출력+키 검증), url_sources(원격 PDF 문서 소스), memory_tool/code_execution(beta 서버 도구 수락), files_api(목록 왕복), models_api(모델 조회 왕복). Admin/Usage API·MCP connector는 정직한 판정 불가(관리자 키/실 MCP 서버 필요)로 의도적 제외.
- **접이식 피처 매트릭스**: 피처별 요약행(굵은 이름 + 상태 분포 바 + supported·unsupported·broken 카운트) 클릭 시 모델 행 펼침. Broken 포함 피처는 자동 펼침, 검색/상태 필터 시 전체 펼침, 모두 펼치기/접기 버튼 제공.

## v2.14.2 — 2026-07-11

### Fixed
- **Final feature-expansion follow-ups (run #8 evidence)**: bare-404 responses (Mantle has no batches endpoint) and explicit tool-schema rejections ("does not match any of the expected tags") now classify as cleanly unsupported; adaptive_thinking probe budget raised to 8000 tokens matching the reference request (at 2048 the model accepted but skipped thinking).
- **피처 확장 최종 후속 (run #8 증거)**: 본문 없는 404(Mantle batches 엔드포인트 미제공)와 도구 스키마 명시 거부("does not match any of the expected tags")를 깨끗한 미지원으로 분류. adaptive_thinking 예산을 참조 요청과 동일한 8000 토큰으로 상향(2048에서는 수락 후 thinking 생략).

## v2.14.1 — 2026-07-11

### Fixed
- **Feature-expansion follow-ups from run #7 evidence**: added missing IAM actions `bedrock:CountTokens` and `bedrock-mantle:CountTokens` (29+14 cells were 403-broken); fixed the batches probe TypeError (`_req_snapshot` model collision); strengthened the adaptive_thinking probe with `output_config: {effort: high}` and a harder prompt (accepted requests were returning no thinking block); classified Bedrock's generic "request is not valid" rejection and "not yet available" (Mantle live web search) as cleanly unsupported.
- **피처 확장 후속 (run #7 증거 기반)**: IAM `bedrock:CountTokens`·`bedrock-mantle:CountTokens` 추가(43셀 403 해소), batches 프로브 TypeError 수정(`_req_snapshot` model 충돌), adaptive_thinking 프로브에 `output_config effort high`+난이도 있는 프롬프트(수락은 되나 thinking 블록 미출력 문제), Bedrock generic "request is not valid" 거부와 "not yet available"(Mantle live 웹 검색)을 깨끗한 미지원으로 분류.

## v2.14.0 — 2026-07-11

### Added
- **Five new parity features** (catalog 7 → 12): `adaptive_thinking` (thinking type adaptive, thinking-block evidence, Fable 5 only), `count_tokens` (endpoint round-trip, input_tokens > 0), `batches` (Message Batches submit → status → cancel), `web_search` and `computer_use` (server-tool definition acceptance; web_search also probes the OpenAI Responses built-in tool). Per-feature surface maps keep non-implemented combinations as skipped; ~536 probes per run.
- **패리티 피처 5종 추가** (카탈로그 7 → 12): `adaptive_thinking`(thinking type adaptive, thinking 블록 증거, Fable 5 전용), `count_tokens`(엔드포인트 왕복, input_tokens > 0), `batches`(Message Batches submit→status→cancel), `web_search`·`computer_use`(서버측 도구 정의 수락 — web_search는 OpenAI Responses 내장 도구도 프로빙). 피처별 surface 맵으로 미구현 조합은 skipped 유지, 런당 ~536 프로브.

## v2.13.0 — 2026-07-11

### Added
- **Mantle Messages surface in parity runs**: Bedrock Claude models now also probe the Bedrock Mantle `/anthropic` (Anthropic Messages-compatible) endpoint in `MANTLE_ANTHROPIC_REGION` (default ap-northeast-1) as a 6th matrix column — SigV4-derived bearer token, FM ids (profile prefix stripped). Live check 2026-07-11: the endpoint exists in ap-northeast-1 but serves no Claude model yet, so cells report as cleanly unsupported (`does not exist` now classifies as unsupported) and will flip automatically when AWS enables models there.
- **패리티 런에 Mantle Messages surface 추가**: Bedrock Claude 모델이 Bedrock Mantle `/anthropic`(Anthropic Messages 호환) 엔드포인트도 프로빙 — 6번째 매트릭스 컬럼, 리전 `MANTLE_ANTHROPIC_REGION`(기본 ap-northeast-1), SigV4 파생 bearer + FM id(프로파일 접두사 제거). 2026-07-11 실측: 엔드포인트는 실존하나 ap-northeast-1 서빙 모델 없음 → "깨끗한 미지원"으로 기록(`does not exist` → unsupported 분류)되며, 서빙 시작 시 자동으로 Supported 전환.
- **Evidence modal with Request/Response JSON**: every parity probe now stores a request snapshot (long strings trimmed with original length noted) in its evidence; the cell modal is restyled as an EVIDENCE panel — `feature · surface · model_id` header, status pill + latency + verdict sentence, and collapsible Error / Request JSON / Response JSON sections (collapsed on success, expanded on failure).
- **증거 모달 Request/Response JSON**: 모든 패리티 프로브가 요청 스냅샷(장문은 원 길이 표기와 함께 절단)을 증거에 저장. 셀 모달을 EVIDENCE 패널로 개편 — `feature · surface · model_id` 헤더, 상태 pill + latency + 판정 문장, 접이식 Error / Request JSON / Response JSON 섹션 (성공 시 접힘, 실패 시 펼침).

### Changed
- **Parity matrix rows**: first column now shows the feature name (bold, on every row) with the model id in monospace beneath — matching the Feature Parity reference layout.
- **Model Explorer Messages API note**: the Bedrock Claude Messages API tab now also mentions the Bedrock Mantle `/anthropic` endpoint (bearer token, some regions e.g. us-east-1) as an alternative path — verified live 2026-07-11.
- **패리티 매트릭스 행**: 첫 컬럼을 피처명(굵게, 매 행) + 모델 id(모노스페이스)로 변경 — 참조 레이아웃과 일치.
- **모델 탐색 Messages API 설명**: Bedrock Mantle `/anthropic` 엔드포인트(bearer 토큰, us-east-1 등 일부 리전) 경로 병기 (2026-07-11 실측).

## v2.12.0 — 2026-07-11

### Added
- **Parity provider summary cards + insights drawer**: /parity now opens with per-provider cards (Anthropic / OpenAI / Amazon — health donut, check counts by status); selecting a card slides in a right-hand Key Findings drawer (broken features with cell ratios and affected models/surfaces, cleanly-unsupported chips, weakest-model bars).
- **Parity run-over-run changes banner**: `/api/parity/latest` now returns `changes` (diff vs the previous completed run, new cells marked); the page shows them at the top (or an explicit "no changes" note).
- **Parity model picker**: the search box is now a combobox — focusing it lists all models for one-click selection, with a clear (×) button.
- **Dashboard anomaly box**: a rounded banner at the top of the dashboard summarizes probe failures in the last 12 hours per model (`GET /api/auto-probe/anomalies?hours=12`), green when all probes succeeded.
- **패리티 provider 요약 카드 + 상세 드로어**: /parity 상단에 provider별 카드(Anthropic/OpenAI/Amazon — 헬스 도넛, 상태별 검사 수). 카드 선택 시 우측 Key Findings 바 — Broken 피처(셀 비율·대상 모델/surface), 깨끗한 미지원 칩, 취약 모델 바.
- **패리티 런 간 변경 배너**: `/api/parity/latest`가 직전 완료 런 대비 `changes`(diff, 신규 셀 표시) 반환, 페이지 상단에 변경사항(또는 "변경 없음") 표시.
- **패리티 모델 선택기**: 검색창이 콤보박스로 — 포커스 시 전체 모델 리스트에서 클릭 선택, 지우기(×) 버튼.
- **대시보드 이상 징후 박스**: 대시보드 상단 라운드 배너가 최근 12시간 프로브 실패를 모델별 요약 (`GET /api/auto-probe/anomalies?hours=12`), 전체 성공 시 녹색 표시.

### Changed
- **Parity schedule: daily → every 12 hours** (`rate(12 hours)` EventBridge schedule, was cron 01:00 UTC).
- **패리티 스케줄: 일 1회 → 12시간 주기** (`rate(12 hours)`, 기존 cron 01:00 UTC).

## v2.11.2 — 2026-07-11

### Fixed
- **Model Explorer: Messages API example missing on Bedrock Claude cards**: Bedrock Claude cards only showed Converse/InvokeModel tabs. Added a third tab — Anthropic Messages API via the `AnthropicBedrock` client (anthropic SDK, SigV4, no Anthropic API key) — matching the Bedrock Central reference (Converse / InvokeModel / Messages all visible).
- **모델 탐색: Bedrock Claude 카드에 Messages API 예제 누락**: Converse/InvokeModel 두 탭만 표시되던 것을 수정 — anthropic SDK의 `AnthropicBedrock` 클라이언트(SigV4, Anthropic API 키 불필요)로 호출하는 Messages API 탭을 추가해 Bedrock Central 참조안처럼 3개 API가 모두 표기되도록 함.

## v2.11.1 — 2026-07-11

### Fixed
- **Parity probe token budget — false-Broken fix**: run #1 evidence showed every Claude `structured_output` cell Broken because `max_tokens=64` truncated the (valid) fenced JSON before its closing `}`, and Fable 5 `system_instructions` returned empty text under the same budget. Introduced per-feature budgets (`max_tokens_for`): structured_output 512, default 256, reasoning unchanged at 2048. Regression tests assert the budgets and that truncated JSON is still rejected.
- **패리티 프로브 토큰 예산 — false-Broken 수정**: 첫 런 증거에서 Claude 전 모델의 `structured_output`이 Broken — 모델은 정상 JSON을 반환했으나 `max_tokens=64`로 닫는 `}` 이전에 절단된 것이 원인. Fable 5 `system_instructions`의 빈 응답도 동일 계열. 피처별 예산(`max_tokens_for`) 도입: structured_output 512, 기본 256, reasoning 2048 유지. 예산 회귀 테스트 + 절단 JSON 거부 테스트 추가.

## v2.11.0 — 2026-07-11

### Added
- **Parity Run engine — real execution-evidence probes** (replaces the v2.10.0 screenshot gallery): a sweep fans out across monitored models × 5 API surfaces (Converse / InvokeModel / Messages / ChatCompletions / Responses) × 7 features (basic, streaming, system_instructions, tool_use, structured_output, reasoning, caching). Each cell is judged from real API responses — tool canary round-trip, system-instruction canary, JSON validity, cached-token counts on repeat, ≥2 stream deltas — never from HTTP 200 alone. Clean provider rejections classify as `unsupported`, evidence failures as `broken`. Results persist to RDS (`parity_runs`/`parity_results`); the /parity page renders a health summary + status matrix with per-cell evidence modal; manual trigger (login) + daily EventBridge schedule (01:00 UTC) via a new Fargate one-shot task.
- **패리티 런 엔진 — 실제 실행-증거 프로브** (v2.10.0 스크린샷 갤러리 대체): 모니터링 모델 × 5개 API surface(Converse/InvokeModel/Messages/ChatCompletions/Responses) × 7개 피처(basic, streaming, system_instructions, tool_use, structured_output, reasoning, caching)로 팬아웃. 도구 카나리 왕복·시스템 지시 카나리·JSON 유효성·반복 요청 캐시 토큰·스트림 델타 2개 이상 등 응답 내용으로 판정 — HTTP 200만으로는 판정하지 않음. provider의 깨끗한 거부는 `unsupported`, 증거 실패는 `broken`. 결과는 RDS(`parity_runs`/`parity_results`)에 저장, /parity 페이지가 헬스 요약 + 상태 매트릭스 + 셀별 증거 모달 렌더링. 수동 트리거(로그인) + 일일 EventBridge 스케줄(01:00 UTC, 신규 Fargate one-shot).

### Changed
- **`APP_VERSION` v2.10.0 → v2.11.0** (`frontend/src/lib/version.ts`).

---

## v2.10.0 — 2026-07-11

### Added
- **Parity Run page (`/parity`)**: new nav menu documenting how a Bedrock feature-parity run works — Korean translation of the 5-step process (scheduled sweep via EventBridge/Step Functions, agent-maintained feature catalog in DynamoDB, model × region × API-surface fan-out, execution-evidence probes, classification & storage) with the original English available via the language toggle, a 20-capture result gallery (deduplicated, WebP-optimized 9.5MB → 2.2MB, click-to-enlarge lightbox), and a link to the full HTML report (2026-07-08).
- **패리티 런 페이지 (`/parity`)**: Bedrock 기능 패리티 런의 동작 방식을 문서화한 신규 메뉴 — 5단계 프로세스(EventBridge/Step Functions 예약 스윕, DynamoDB 에이전트 관리 피처 카탈로그, 모델×리전×API surface 팬아웃, 실행-증거 프로브, 분류·저장)의 한국어 번역(EN 토글 시 원문), 결과 스크린샷 20장 갤러리(중복 제거·WebP 최적화 9.5MB→2.2MB, 클릭 확대), 전체 HTML 리포트(2026-07-08) 링크.

### Changed
- **`APP_VERSION` v2.9.2 → v2.10.0** (`frontend/src/lib/version.ts`).

---

## v2.9.2 — 2026-07-11

### Added
- **Model Explorer: API-type tabs with explanations** — code examples are now labeled by API (Bedrock: Converse API + InvokeModel API for Claude models; Anthropic CP: Messages API; OpenAI: Responses API) with a short description of what each API means, shown when a model card is selected.
- **모델 탐색 코드 예제에 API 종류 탭 + 설명** — Converse API/InvokeModel API(Bedrock), Messages API(Anthropic CP), Responses API(OpenAI)로 표기하고, 카드 선택 시 각 API가 의미하는 바를 설명으로 표시. Claude 계열 Bedrock 모델은 InvokeModel 네이티브 예제 추가.

### Fixed
- **/models 페이지 자체의 내비 순서 누락 수정**: v2.9.1 재배치가 다른 페이지에만 적용되고 모델 탐색 페이지의 활성 탭은 끝에 남아 있었음.
- **`APP_VERSION` v2.9.1 → v2.9.2**.

---

## v2.9.1 — 2026-07-11

### Changed
- **Nav order**: "모델 탐색" menu moved to sit right after "대시보드" on all pages.
- **내비 순서**: "모델 탐색" 메뉴를 전 페이지에서 "대시보드" 바로 다음으로 이동.
- **`APP_VERSION` v2.9.0 → v2.9.1** (`frontend/src/lib/version.ts`).

---

## v2.9.0 — 2026-07-11

### Added
- **Model Explorer (`/models`)**: new nav menu listing all monitored models as a searchable/filterable card grid (channel filter: Anthropic CP / Bedrock / OpenAI Mantle / OpenAI 1P). Selecting a card opens a detail modal with the exact invoke model ID per provider path, endpoint/region, token pricing, copy-ready code examples matching the prober's real call patterns (boto3 `converse_stream`, anthropic SDK + CP on AWS endpoint, openai SDK + Mantle base_url, openai SDK + 1P Responses API), documentation/console links, and a deep link to that model's dashboard trend (v2.7.1 URL-share format). Data comes from `/api/models` — new models appear automatically.
- **모델 탐색 (`/models`)**: 모니터링 중인 전체 모델을 검색·채널 필터 가능한 카드 그리드로 보여주는 신규 메뉴. 카드 선택 시 상세 모달 — provider path별 정확한 호출 모델 ID, 엔드포인트·리전, 토큰 단가, prober 실제 호출 방식과 동일한 복사용 코드 예제(boto3 `converse_stream` / anthropic SDK + CP on AWS / openai SDK + Mantle / openai SDK + 1P Responses API), 문서·콘솔 링크, 해당 모델 대시보드 트렌드 바로가기. 데이터는 `/api/models` 기반 — 모델 추가 시 자동 반영.

### Changed
- **`APP_VERSION` v2.8.4 → v2.9.0** (`frontend/src/lib/version.ts`).

---

## v2.8.4 — 2026-07-11

### Fixed
- **White theme: tinted panel cards now render as clean white cards** (matching the dashboard): reliability channel cards and the cost gradient card keep their colored titles/borders for identity, but the card body is white in the light theme via a new `light:` Tailwind variant (`html.light &`). Dark theme unchanged.
- **화이트 테마 카드 정리**: 신뢰성 채널 카드·비용 그라데이션 카드의 색 틴트 배경을 라이트에서 대시보드와 동일한 흰색 카드로 전환 (채널 식별용 제목·보더 색은 유지). 신규 `light:` Tailwind 변형 도입. 다크 테마는 변경 없음.

### Changed
- **`APP_VERSION` v2.8.3 → v2.8.4** (`frontend/src/lib/version.ts`).

---

## v2.8.3 — 2026-07-11

### Fixed
- **Accent colors unreadable in white theme across all pages**: metric/badge text tuned for dark backgrounds (`text-emerald-400`, `text-rose-400`, `text-amber-400`, `text-blue-300`, …) washed out on white cards. The light tints (steps 200/300/400) of all 17 used accent hues are now CSS variables that swap to the same hue's dark tones (200→800, 300→700, 400→600) in the light theme — no component changes; solid 500+ (buttons) and low-opacity tint boxes stay shared between themes.
- **화이트 테마에서 전 페이지 액센트 색 가독성 저하**: 다크 배경 기준으로 선정된 지표·배지 텍스트(`text-emerald-400`, `text-rose-400`, `text-amber-400`, `text-blue-300` 등)가 흰 카드에서 씻겨 보임. 사용 중인 17개 액센트 hue의 밝은 톤(200/300/400)을 CSS 변수화해 라이트에서 같은 hue의 진한 톤(200→800, 300→700, 400→600)으로 교체 — 컴포넌트 무수정, 500 이상(버튼)과 저투명 틴트 박스는 양 테마 공용 유지.

### Changed
- **`APP_VERSION` v2.8.2 → v2.8.3** (`frontend/src/lib/version.ts`).

---

## v2.8.2 — 2026-07-10

### Fixed
- **AI Insights unreadable in white theme**: `MessageMarkdown` hardcoded `prose-invert` (dark-only typography), rendering light text on white cards. Typography now switches with the theme; chat bubbles use the same component and are fixed together.
- **화이트 테마에서 AI 인사이트 안 보임**: `MessageMarkdown`이 다크 전용 `prose-invert`를 하드코딩해 흰 카드 위 밝은 글자로 렌더링됨. 테마에 따라 typography 분기 — 같은 컴포넌트를 쓰는 챗봇 말풍선도 함께 수정.

### Changed
- **`APP_VERSION` v2.8.1 → v2.8.2** (`frontend/src/lib/version.ts`).

---

## v2.8.1 — 2026-07-10

### Fixed
- **Chatbot `prompt is too long` (1.6M tokens)**: the `get_trend` chat tool returned every raw probe point (56k+ points ≈ 1.6M tokens at hours=168) as a tool_result, blowing ConverseStream's 1M-token limit. Ranges over 6h now aggregate to (model, hour-bucket) averages, responses are capped at `MAX_TREND_POINTS`(2500) with an explicit `aggregation`/`note` field, and the query selects only needed columns. `compare_models` computes p50/p95 from raw values (unaffected by aggregation).
- **챗봇 `prompt is too long`(160만 토큰) 오류**: `get_trend` 도구가 원본 포인트 전부(168h 기준 56k+개 ≈ 1.6M 토큰)를 tool_result로 반환해 ConverseStream 1M 토큰 상한 초과. 6시간 초과 조회는 (모델, 정시 버킷) 평균으로 축약, 응답 포인트는 `MAX_TREND_POINTS`(2500) 상한 + `aggregation` 필드 명시, 필요한 컬럼만 조회. `compare_models`의 p50/p95는 원본 값으로 계산(축약 영향 없음).
- **2026-07-08 커넥션 풀 장애 수정 git 복구**: TCP keepalive + statement_timeout `connect_args`가 미커밋 상태로 운영 이미지에만 존재했음 — 이미지에서 추출해 회귀 테스트와 함께 정식 커밋 (다음 빌드에서의 조용한 소실 방지).

### Changed
- **`APP_VERSION` v2.8.0 → v2.8.1** (`frontend/src/lib/version.ts`).

---

## v2.8.0 — 2026-07-10

### Added
- **Dark/light theme toggle**: header ☀️/🌙 button on all 6 pages switches between the existing dark theme (default) and a new SnowUI-toned white theme; choice persists in localStorage and is restored pre-hydration (no flash). Implementation remaps the Tailwind gray scale to CSS variables (`globals.css` + `tailwind.config.ts`), so all ~495 existing `gray-*` class usages theme automatically with zero component changes; charts (Recharts JS-constant colors) switch via a `useChartTheme()` hook. Light theme adds subtle card shadows for depth.
- **다크/화이트 테마 토글**: 6개 페이지 헤더의 ☀️/🌙 버튼으로 기존 다크(기본)와 SnowUI 톤 화이트 테마 전환. 선택은 localStorage에 저장되고 하이드레이션 전에 복원(FOUC 없음). Tailwind gray 스케일을 CSS 변수로 재매핑해 기존 `gray-*` 클래스 약 495곳이 컴포넌트 수정 없이 자동 테마화, 차트(Recharts JS 상수 색)는 `useChartTheme()` 훅으로 분기. 화이트 테마에는 카드 그림자 추가.

### Changed
- **`APP_VERSION` v2.7.2 → v2.8.0** (`frontend/src/lib/version.ts`).

---

## v2.7.2 — 2026-07-10

### Fixed
- **First-visit selection defaults to All**: the v2.7.1 representative-model auto-selection also highlighted those models' cards in the status grid, which looked like stray pre-selected cards on first load. Auto-selection removed — first visit shows all models (전체) with no cards highlighted; "대표 모델" remains available as an explicit button, and shared URLs still restore their exact selection.
- **첫 진입 선택 기본값을 전체로 복원**: v2.7.1의 대표 모델 자동 선택이 상태 그리드 카드 하이라이트와 연동되어 첫 화면에서 일부 카드가 선택된 것처럼 보였음. 자동 선택 제거 — 첫 진입은 전체 표시(카드 하이라이트 없음), "대표 모델"은 명시적 버튼으로 유지, 공유 URL 복원은 그대로 동작.

### Changed
- **`APP_VERSION` v2.7.1 → v2.7.2** (`frontend/src/lib/version.ts`).

---

## v2.7.1 — 2026-07-09

### Added
- **Trend chart readability**: first visit now shows one representative channel per family (~10 lines instead of 28); "대표 모델"/"전체" buttons switch modes. Legend entries are clickable to toggle model lines. Long-range views (>24h) draw a min–max band behind the average line when a single model is selected (backend now returns per-bucket min/max). Selection state (models/hours/category) is synced to the URL query — survives refresh and is shareable.
- **트렌드 차트 가독성**: 첫 방문 시 패밀리별 대표 채널 1개만 표시(28개 → 약 10개 라인), "대표 모델"/"전체" 버튼으로 전환. 범례 클릭으로 라인 토글. 24h 초과 조회에서 단일 모델 선택 시 평균선 뒤에 min–max 밴드 표시(backend가 버킷별 min/max 반환). 선택 상태(models/hours/category)는 URL query에 동기화 — 새로고침 유지·링크 공유 가능.

### Changed
- **`APP_VERSION` v2.7.0 → v2.7.1** (`frontend/src/lib/version.ts`).

---

## v2.7.0 — 2026-07-09

### Added
- **Data retention policy**: raw `probe_results` older than `RETENTION_DAYS` (default 60) are aggregated into a new `probe_results_hourly` table — per (model, category, hour bucket): total/success counts, avg TTFT/latency/TPS, input/output token sums (cost reconstruction possible) — then deleted, in a single atomic transaction (safe retry, no double-aggregation). Runs at the end of every auto-prober cycle. Old `probe_runs` without remaining results are cleaned up (FK-safe).
- **데이터 보존 정책**: `RETENTION_DAYS`(기본 60일)를 지난 원본 `probe_results`를 신규 `probe_results_hourly` 테이블에 (모델, 카테고리, 정시 버킷)별 집계 — 전체/성공 수, 평균 TTFT/레이턴시/TPS, 토큰 합계(비용 재계산 가능) — 로 이관 후 삭제. 집계+삭제는 단일 트랜잭션(재시도 안전). 매 auto-prober cycle 말미 실행, 결과 없는 옛 `probe_runs`도 정리.

### Infra
- **CI (GitHub Actions)**: push(main)/PR마다 backend pytest + frontend tsc/vitest/next build + CDK jest 병렬 실행 (`.github/workflows/ci.yml`, v2.6.2 이후 추가분 포함).
- **CDK 이미지 digest 고정**: 모든 배포는 `-c backendImage`/`-c frontendImage`(digest URI) 필수 — cdk deploy가 서비스를 :latest 구버전으로 되돌리던 실사고(2026-07-09) 원천 차단. `llm-monitor.whchoi.net` alias + ACM cert도 CDK(edge-stack) 소유로 이전.

### Changed
- **`APP_VERSION` v2.6.2 → v2.7.0** (`frontend/src/lib/version.ts`).

---

## v2.6.2 — 2026-07-09

### Fixed
- **Dashboard graph-selection latency**: `/api/auto-probe/trend` took 4.3s even for `hours=1` (336 rows) and 22.2s / 13.3MB for `hours=168`; category/time-range clicks appeared frozen for up to 22s with no feedback, and model-chip clicks blocked the main thread for seconds. Root causes: zero non-PK DB indexes (full scans on burstable t4g.micro), ORM hydrating unused large TEXT columns (`output_text`), no downsampling, an O(T×M×N) client-side pivot re-running on every render (including the 1-second countdown re-render), and no fetch cancellation (a slow stale response could overwrite a newer selection).
- **대시보드 그래프 선택 지연**: `hours=1`(336행)도 4.3초, `hours=168`은 22.2초/13.3MB — 필터 클릭 후 최대 22초 무반응처럼 보였고 모델 칩 클릭도 수 초 멈춤. 원인: PK 외 인덱스 전무(풀 스캔), 미사용 대형 TEXT 컬럼까지 ORM 로드, 다운샘플링 부재, 매 렌더(1초 카운트다운 포함)마다 재실행되는 O(T×M×N) 클라이언트 피벗, fetch 취소 부재(늦게 도착한 이전 응답이 최신 선택을 덮어쓰는 경쟁 상태).

### Changed
- backend: `probe_runs(is_auto,status,created_at)` / `probe_results(run_id)` / `probe_results(timestamp)` 인덱스 (lifespan 마이그레이션 `ensure_performance_indexes`, 멱등). timestamp 인덱스는 cost/reliability/efficiency/analysis 공통 이득.
- backend: trend 쿼리 다이어트 — 응답에 쓰는 8컬럼만 SELECT + JOIN (`output_text`/`prompt` 미조회).
- backend: `hours>24` 시간 버킷 평균 다운샘플링 (168h: 56k행 → ~4.7k행), 24h 이하는 5분 해상도 유지.
- backend: trend/latest에 `Cache-Control: public, max-age=0, s-maxage=30` (CloudFront 전용, 브라우저 캐시 없음).
- frontend: TrendChart 피벗을 `lib/pivotTrend.ts` Map 기반 O(N)으로 추출 + `useMemo`/`React.memo`, 700 포인트 초과 시 dot 생략 (vitest 테스트 도입).
- frontend: 필터 재조회 중 "데이터 갱신 중…" 오버레이, `AbortController`로 이전 요청 취소, 필터 변경 시 `/status` 재호출 생략.
- **`APP_VERSION` v2.6.1 → v2.6.2** (`frontend/src/lib/version.ts`).

### Infra
- CDK `edge-stack.ts`: `/api/auto-probe/*` 전용 behavior — `BedrockMonitorAutoProbeCache` 캐시 정책(origin Cache-Control 존중, 쿼리스트링 캐시 키, gzip/brotli 압축). 기존 `/api/*`는 SSE 보호로 무압축이었음. **적용에는 `cdk deploy BedrockMonitor-Edge` 필요.**

---

## v2.6.1 — 2026-07-03

### Fixed
- **Reliability view now includes OpenAI/GPT channels**: `routers/reliability.py` `_parse_label` only matched `Bedrock|Anthropic` labels, so every `OpenAI …` label fell to channel `"Other"`, and the formatter's hardcoded 3-channel tuple silently dropped it. Now the regex accepts `OpenAI`, OpenAI labels map to `family="GPT 5.x"` / `channel="OpenAI <region|1P>"`, and the formatter iterates all present channels in rank order (Anthropic → Bedrock Global → Bedrock US → OpenAI Mantle/1P). GPT 5.4 (4 channels: us-east-1/2/west-2 + 1P) and GPT 5.5 (3: us-east-1/2 + 1P) now appear on `/reliability`.
- **신뢰성 화면에 OpenAI/GPT 채널 포함**: `reliability.py` `_parse_label`이 `Bedrock|Anthropic`만 매칭해 모든 `OpenAI …` 라벨이 채널 `"Other"`로 빠졌고, 포매터의 하드코딩 3채널 튜플이 이를 조용히 누락시켰습니다. 이제 regex가 `OpenAI`를 허용하고, OpenAI 라벨은 `family="GPT 5.x"` / `channel="OpenAI <region|1P>"`로 매핑되며, 포매터는 존재하는 모든 채널을 순위 순서로 표시합니다.

### Changed
- **`APP_VERSION` v2.6.0 → v2.6.1** (`frontend/src/lib/version.ts`).
- `ReliabilityPanel.tsx`: OpenAI 채널 색상(green 계열) + 설명 텍스트에 OpenAI 채널 명시.

---

## v2.6.0 — 2026-07-02

### Added
- **OpenAI GPT 1P direct monitoring (2 channels)**: `OpenAI GPT 5.4 (1P)` + `OpenAI GPT 5.5 (1P)` via a **5th provider path** calling `https://api.openai.com/v1` directly (OpenAI Responses API streaming), distinct from the Bedrock Mantle path. Catalog 26 → 28 (Bedrock 15 + Anthropic CP 6 + OpenAI 5 → 7). Key scheme `openai:1p:gpt-5.x` (pseudo-region `1p`, no AWS region) — reuses the `openai:` prefix so pricing/cost/sort normalizers need no change. Separate credential: **OpenAI platform key** (`OPENAI_1P_API_KEY`, `sk-proj-…`) — not interchangeable with the Mantle bearer (`ABSK-…`). Verified live: both models invocable (`status=completed`).
- **OpenAI GPT 1P direct 모니터링 추가 (2채널)**: `OpenAI GPT 5.4 (1P)` + `OpenAI GPT 5.5 (1P)`. `https://api.openai.com/v1` 직접 호출(Responses API 스트리밍)하는 **5번째 provider path** — Bedrock Mantle와 별개. 모니터링 대상 26 → 28개 (Bedrock 15 + Anthropic CP 6 + OpenAI 5 → 7). key 스킴 `openai:1p:gpt-5.x`(pseudo-region `1p`, AWS 리전 없음) — `openai:` prefix 재사용으로 pricing/cost/sort 정규화 수정 불필요. 별도 자격증명: **OpenAI platform 키**(`OPENAI_1P_API_KEY`, `sk-proj-…`) — Mantle bearer(`ABSK-…`)와 호환 불가.
- **ADR-020**: OpenAI 1P direct (api.openai.com) provider path 설계 결정 기록.

### Changed
- **`APP_VERSION` v2.5.0 → v2.6.0** (`frontend/src/lib/version.ts`).
- `_register_openai_models()` — Mantle(`OPENAI_API_KEY`)과 1P(`OPENAI_1P_API_KEY`) 경로를 독립 gate (한쪽 키만 있어도 그쪽만 등록).

### Infra
- CDK `app-services-stack.ts` + `scheduler-stack.ts`: SSM SecureString `/bedrock-monitor/openai-1p-api-key` → `OPENAI_1P_API_KEY` secret + `OPENAI_1P_GPT_54/55_MODEL_ID` env 주입 (backend + autoprober + insights). IAM/SigV4 없음(bearer). 배포 runbook에 1P 키 사전 생성 스텝 추가.

### Docs
- 모니터링 카운트 26 → 28 동기화: CLAUDE.md(Monitored Models 표에 1P 컬럼 + 카운트 8곳 + Path 5 설명 + 라벨 정책), README.md(영/한 + version 배지 2.5.0 → 2.6.0), docs/architecture.md(ADR-020 행 + 토폴로지 카운트), docs/api-reference.md(`model_count`).

---

## v2.5.0 — 2026-06-30

### Added
- **Claude Sonnet 5 monitoring (3 channels)**: Bedrock Global (`global.anthropic.claude-sonnet-5`), Bedrock US/Geo (`us.anthropic.claude-sonnet-5`), Anthropic CP on AWS (`sonnet-5`, `/v1/models` auto-discovery). Catalog 23 → 26 (Bedrock 13 → 15 + Anthropic CP 5 → 6 + OpenAI 5). Reasoning model — `temperature` suppressed via `_REASONING_MODEL_PATTERNS` (adaptive-thinking family, like Opus 4.7/4.8 / Fable 5). `FAMILY_ORDER` 9 → 10 (Sonnet 5 ranks above Sonnet 4.6) + indigo color (`#6366f1`/`#4f46e5`/`#4338ca`).
- **Claude Sonnet 5 모니터링 추가 (3채널)**: Bedrock Global (`global.anthropic.claude-sonnet-5`), Bedrock US/Geo (`us.anthropic.claude-sonnet-5`), Anthropic CP on AWS (`sonnet-5`, `/v1/models` 자동 발견). 모니터링 대상 23 → 26개 (Bedrock 13 → 15 + Anthropic CP 5 → 6 + OpenAI 5). Reasoning 모델 — `_REASONING_MODEL_PATTERNS`로 `temperature` 미전송 (Opus 4.7/4.8 · Fable 5와 동일한 adaptive-thinking family). `FAMILY_ORDER` 9 → 10 (Sonnet 5가 Sonnet 4.6 위) + indigo 색상.
- **Sonnet 5 토큰 단가** (AWS Bedrock 기준, USD/1M): input $2.00 / output $10.00 — `backend/pricing.py` + `frontend/src/lib/pricing.ts`. `/cost`·효율성 점수 자동 반영.

### Changed
- **`APP_VERSION` v2.4.1 → v2.5.0** (`frontend/src/lib/version.ts`).

### Docs
- 모니터링 카운트 23 → 26 동기화: CLAUDE.md(모델 표 + 카운트 6곳), README.md(영/한 8곳 + version 배지 2.2.0 → 2.5.0), docs/architecture.md, docs/api-reference.md(`model_count`), frontend/src/components/CLAUDE.md. CLAUDE.md Monitored Models 표에 Claude Sonnet 5 행 추가 (Global ✅ / US ✅ / CP ✅).

---

## v2.4.1 — 2026-06-26

### Added
- **OpenAI GPT 5.4 monitoring in us-west-2 (Bedrock Mantle)**: catalog 22 → 23 (OpenAI 4 → 5). us-west-2 serves gpt-5.4 only — gpt-5.5 is not available there. Model registration is now per-model region availability via `_OPENAI_MODEL_SPECS`.
- **OpenAI GPT 5.4 모니터링 us-west-2 추가 (Bedrock Mantle)**: 모니터링 대상 22 → 23개 (OpenAI 4 → 5). us-west-2는 gpt-5.4만 제공 — gpt-5.5 미지원. `_OPENAI_MODEL_SPECS`를 통해 모델별 리전 가용성으로 등록.

### Changed
- **`APP_VERSION` v2.4.0 → v2.4.1** (`frontend/src/lib/version.ts`).

### Docs
- CLAUDE.md OpenAI 표에 us-west-2 컬럼 추가 (GPT 5.4 ✅ / GPT 5.5 —). 카운트 22 → 23 동기화. README·architecture.md·api-reference.md·frontend/src/components/CLAUDE.md 업데이트.

---

## v2.4.0 — 2026-06-26

### Added
- **OpenAI GPT 5.4 / GPT 5.5 모니터링 (4채널)**: Bedrock Mantle OpenAI-compatible endpoint 경유. 각 모델을 us-east-1 + us-east-2 2개 리전에서 모니터링 (채널 4개). 새 `"OpenAI"` family 추가. 모니터링 대상 18 → 22개 (Bedrock 13 + Anthropic CP 5 + OpenAI 4).
- **OpenAI 토큰 단가** (USD/1M): gpt-5.4 input $2.75 / output $16.50, gpt-5.5 input $5.50 / output $33.00 — `backend/pricing.py` + `frontend/src/lib/pricing.ts`. `/cost`·효율성 점수 자동 반영.
- **ADR-019**: OpenAI GPT via Bedrock Mantle 설계 결정 기록.

### Changed
- **`APP_VERSION` v2.3.0 → v2.4.0** (`frontend/src/lib/version.ts`).

---

## v2.3.0 — 2026-06-10

### Added
- **Claude Fable 5 모니터링 추가 (3채널)**: Bedrock Global (`global.anthropic.claude-fable-5`), Bedrock US/Geo (`us.anthropic.claude-fable-5`), Anthropic CP on AWS (`anthropic:claude-fable-5`, `/v1/models` 자동 발견). 2026-06-09 GA된 Anthropic 최신 flagship(Mythos-class). 모니터링 대상 15 → 18개 (Bedrock 13 + Anthropic CP 5). `FAMILY_ORDER` 최상단(flagship) + teal 색상. 6개 메뉴 dynamic 집계로 자동 포함.
- **참고 — Fable 5 Covered Model + Data Retention(리전별)**: Fable/Mythos는 `provider_data_share` retention 모드에서만 동작하며 **리전별 설정**이다. us.(us-east-1) + global.(Seoul ap-northeast-2 경유) 둘 다 `provider_data_share` opt-in 적용(2026-06-10). plain `anthropic.*` FM ID는 on-demand 미지원(inference profile 필요). 1P/CP는 별도 계정·워크스페이스라 그 계정에서 관리. ⚠️ 30일 데이터 공유.
- **Fable 5 토큰 단가** input $10 / output $50 per 1M (AWS Bedrock on-demand 출시 가격) — `backend/pricing.py` + `frontend/src/lib/pricing.ts`. US-only(Geo) inference의 1.1x 프리미엄은 기존 단일-키 단가 정책상 미반영(모든 모델 공통).

### Changed
- **`_REASONING_MODEL_PATTERNS`에 `fable-5` 추가** — Opus 4.x와 동일하게 `inferenceConfig.temperature` 생략.
- **`APP_VERSION` v2.2.1 → v2.3.0**.

### Docs
- CLAUDE.md `Monitored Models` 표에 Fable 5 행 추가 + 카운트 15 → 18. README·architecture.md·api-reference.md 동기화.

---

## v2.2.1 — 2026-06-09

### Fixed
- **AutoProber DB connection-pool 고갈 (운영 장애)**: `run_cycle()`가 모델당 `SessionLocal()`을 submit 루프에서 미리 생성하고 in-order 결과 루프에서야 close → 느린 probe(Opus 4.8 Global read-timeout)가 루프를 막는 동안 완료된 세션들의 connection이 누적되어 pool(5+5=10)을 고갈. 모델 수 12→15 확장으로 한계 초과 → tail 5개 모델(Nova US + Anthropic CP 4종)이 `QueuePool limit reached`로 결과 저장 실패(대시보드 카드 누락). 세션 수명을 worker 실행에 묶어 동시 connection을 `max_workers`(3)로 제한 → 모델 수와 무관하게 안전. 회귀 테스트 `backend/tests/test_auto_prober_pool.py` 추가.

---

## v2.2.0 — 2026-06-01

### Added
- **Claude Opus 4.8 모니터링 (3채널)**: Bedrock Global (`global.anthropic.claude-opus-4-8`), Bedrock US (`us.anthropic.claude-opus-4-8`), Anthropic CP on AWS (`anthropic:claude-opus-4-8`, `/v1/models` 자동 발견). `prober.py` `AVAILABLE_MODELS` + `_ANTHROPIC_TARGETS` 등록. 모니터링 대상 12 → 15개 (Bedrock 11 + Anthropic CP 4). 6개 메뉴(Dashboard·Cost·Reliability·Efficiency·Analysis·Prompts)는 dynamic 집계라 자동 포함.
- **Opus 4.8 토큰 단가** input $15 / output $75 per 1M (Opus 4.7과 동일) — `backend/pricing.py` + `frontend/src/lib/pricing.ts` 동기화. `/cost`·효율성 점수 자동 반영.
- **Frontend Opus 4.8 색상/정렬**: `TrendChart.tsx` MODEL_COLORS 3종(rose 계열) + FAMILY_FALLBACK, `StreamingView.tsx` MODEL_COLORS + `extractModelName` 분기, `sortModels.ts` FAMILY_ORDER 최상단, `PromptsPanel.tsx` OptimizePrompt 타겟 2종.

### Changed
- **`_REASONING_MODEL_PATTERNS`에 `opus-4-8` 추가** — Opus 4.7과 동일하게 `inferenceConfig.temperature` 생략 (reasoning model). 4.8이 temperature를 거부해도 프로브 에러 방지.
- **`APP_VERSION` v2.1.0 → v2.2.0** (`frontend/src/lib/version.ts`).

### Fixed
- **`routers/compare.py` SSE 이중 wrap 버그**: `stream_compare_events`가 이미 `"event: X\ndata: Y\n\n"` 형식으로 yield하는데 `EventSourceResponse`로 감싸 이중 wrap → 클라이언트 파싱 불가. `probes.py`/`insights.py`와 동일하게 `StreamingResponse(media_type="text/event-stream")` + `X-Accel-Buffering: no` 헤더로 수정.

### Infra
- **EventBridge Scheduler `ecs:RunTask` ADR-011 wildcard 적용**: 런타임 IAM role의 RunTask Resource가 옛 task def revision(`:12`/`:5`)에 pin되어 autoprober/insights가 silent fail(2일+ 정지) 중이었음 → task def family `:*` wildcard로 교체해 복구.
- **CDK `scheduler-stack.ts`**: L2 `EcsRunFargateTask`의 자동 생성 role(revision pin) 대신 명시적 `SchedulerInvokeRole`(family `:*` wildcard RunTask + scoped PassRole)을 두 schedule target에 전달 — 재배포 시 재발 방지.

### Docs
- CLAUDE.md `Monitored Models` 표에 Opus 4.8 행 추가 + 모델 카운트 12/13 → 15 정정. README·architecture.md·api-reference.md 카운트 동기화.

---

## v2.1.0 — 2026-05-20

### Added
- **Output Analysis 페이지** (`/analysis`): Stop reason 분포 (end_turn / max_tokens / stop_sequence / tool_use / guardrail_intervened / content_filtered) + Output token 길이 분포 (median/p50/p95/std + 7-bin histogram). 모델 가로 비교 + 카테고리/시간 윈도우 필터 + 해석 가이드 박스.
- **Backend `/api/analysis/*`**: `stop-reasons`, `output-length` 두 엔드포인트. `_normalize_stop_reason()` vendor 차이 흡수.
- **`ProbeResult.stop_reason` 컬럼** + lifespan `ALTER TABLE ADD COLUMN IF NOT EXISTS`. Bedrock `messageStop.stopReason` + Anthropic `final_message.stop_reason` 양쪽 capture.
- **모델 catalogue 확장 9 → 13개**: Claude Opus 4.5 / Sonnet 4.5 × Global/US 추가.
- **Admin user management endpoints**: `GET /api/admin/users`, `DELETE /api/admin/users/{username}`, `POST /api/admin/users/{username}/approve`. admin 전용 (`username == "admin"`).
- **챗봇 초기 추천 풍선말 6개**: 효율성/비용/분석/신뢰성/출력 길이/에러 진단 등 신기능 인사이트 질문으로 갱신.
- **헤더에 `APP_VERSION` 표시** (v2.1.0). `frontend/src/lib/version.ts`가 single source of truth.

### Changed
- **회원가입 `username` → `EmailStr` 검증 강제** (Pydantic + `email-validator>=2.1.0`). 이메일 형식 아닌 입력은 422. LoginForm `type="email"` + 안내.
- **모델명 라벨 통일**: `AVAILABLE_MODELS` 13개 모두 `"Bedrock <family> (<channel>)"` prefix. Frontend `MODEL_COLORS`, `FAMILY_ORDER` 통일. 옛 row는 lifespan rename으로 자동 변환.
- **`/api/auto-probe/status`** DB-sourced: backend in-process state 대신 `ProbeRun(is_auto=1)` 최근 row 기준 (Fargate task 분리 이후 일관성).

### Fixed
- **`_probe_single_model` retry-raise 버그**: retry 소진 시 `raise`로 함수 종료 → ProbeResult row 미저장 → 카드 누락. `raise` → `break` + outer try에서 처리로 수정.
- **ECR `:latest` 태그 함정**: ECS Fargate가 cached container를 실행 → 새 코드 silent 반영 안 됨. 모든 task def를 immutable `v<timestamp>` tag로 전환.
- **EventBridge Scheduler IAM role의 `ecs:RunTask` Resource가 task def revision pinned**: 새 revision으로 schedule update 시 silent fail (autoprober 정지). Resource를 task def family `:*` wildcard로 변경.

### Security
- 회원가입 시 username 이메일 형식 강제.
- Admin endpoint `_ensure_admin` gate + 자기 자신 삭제 차단.

### Infra
- `ecr-image-tag-management` 권장 절차: immutable tag → register-task-definition → update-service + autoprober schedule 동시 갱신.
- AutoProber + Insights 모두 `rate(5 minutes)` 주기.
- **ECR repository 변경** — `bedrock-monitor-backend` → `bedrock-monitor-backend-v2` (Fargate image cache silent bug 우회, ADR-018). 새 repo는 `IMMUTABLE` tag mutability.
- ECS Fargate silent failure 완전 우회를 위해 image URI에 `@sha256:<digest>` 직접 명시 (task def `containerDefinitions[].image` 필드).

### Removed
- **Opus 4.5 (Global/US), Sonnet 4.5 (Global/US)** — 사용자 요청으로 모니터링 대상에서 제외 (2026-05-20). backend `AVAILABLE_MODELS` 정리 + lifespan `DELETE FROM probe_results WHERE model_name LIKE '%Opus 4.5%' OR LIKE '%Sonnet 4.5%'` 자동 적용. 모니터링 대상 9개 Bedrock + 3개 Anthropic CP = 12개.

### Fixed
- Frontend `AutoDashboard.tsx`에 `Opus 4.5`/`Sonnet 4.5` hard-filter 추가 — backend silent bug로 옛 row가 응답에 포함되어도 UI 숨김. 방어적 패치.
- `StreamingView.tsx` MODEL_COLORS에서 4.5 reference 정리 + Opus 4.7 / Sonnet 4.6 추가.

### Docs
- README, CLAUDE.md를 v2.1.0 기준으로 재작성.
- ADR-010~018 신규 작성 (immutable tag, scheduler IAM wildcard, model catalog, output analysis, admin endpoints, status DB-sourced, frontend route split, model catalog reduction, ECR repo swap).

---

## v2.X — 진행 중 (2026-05-19)

### Added
- **Claude Platform on AWS (Path 3 External) 채널 통합**: vendor endpoint `aws-external-anthropic.us-east-2.api.aws` 호출 + `anthropic-workspace-id` 헤더. Anthropic SDK base_url override 패턴. SSM SecureString 2종 (`/bedrock-monitor/anthropic-api-key`, `/bedrock-monitor/anthropic-workspace-id`). 3개 Anthropic 직접 API 모델 자동 등록.
- **Prompts 탭 (`/prompts`)**: 별도 라우트 페이지. 프롬프트 세트 CRUD + Bedrock Simple Prompt Optimization (`bedrock-agent-runtime.optimize_prompt`) 통합. 9개 모니터링 모델로 타겟 매핑.
- **그래프 다중 선택**: 모델 칩/카드 toggle → N개 동시 비교. `selectedModels: Set<string>` 패턴.
- **카드 family-grouped grid**: Opus 4.7 / 4.6 / Sonnet 4.6 / Haiku 4.5 / Nova 2.0 Lite 각각 별도 row를 차지하도록 그룹화.
- **상단 헤더 로그인 버튼** (미인증 시 모달 노출).
- **챗봇 아이콘 친근한 로봇 얼굴** (안테나/눈/입/헤드폰), 위치 `bottom-24`.
- **채널 설명 패널**: Bedrock vs Anthropic CP on AWS 호출 채널 + endpoint URL.
- **모델 카드 inference profile ID 표시**.
- **이력조회 정렬 통일** (family/channel 순서).
- **추천 검색어 + Follow-up 풍선말** (FloatingChat + InsightsPanel).
- **AI Insights bilingual (KO/EN)** + 미인증 사용자 새로고침/검색 시 로그인 모달.

### Changed
- 모델 라벨 통일: 1P는 `Anthropic ... (US)`, 나머지는 `Bedrock ... (Global|US)` 접두사. `lib/sortModels.ts` 공유 유틸 추출.
- AI 인사이트 위치를 그래프 밑으로 이동.
- 인사이트 본문 스크롤 박스 제거 (전체 출력).
- 트렌드 그래프 색상 13개 모두 다른 색 (Bedrock 주황·핑크·인디고·시안 + Anthropic 보라 계열).
- `next.config.mjs` HTML route → `cache-control: no-store, no-cache, must-revalidate, max-age=0`, `_next/static/*` → `public, max-age=31536000, immutable`.
- 5분 주기 Insights 잡 (이전 30분).

### Removed
- `Nova Pro (US)` / `Nova Lite (US)` / `Nova 2.0 Lite (Global)` 모니터링 대상 제외 — `Nova 2.0 Lite (US)`만 유지.
- DB row 자동 삭제 마이그레이션 (lifespan).

### Fixed
- ECS Task Definition rev 9 INACTIVE 상태 → manual register rev 10. CDK가 secret 추가 후 ACTIVE 보장 안 되는 문제 회피.
- SSM `/bedrock-monitor/anthropic-workspace-id` 미존재 시 ECS task가 secret fetch 실패 → 사용자에게 SSM 저장 가이드.
- Frontend Docker build가 `cdk/` 작업 디렉토리에서 실행되어 옛 image SHA 그대로 push되는 문제 → 절대경로 + `--no-cache` 빌드 + 명시적 `docker rmi`.
- Frontend `created_at` PromptSet 타입 에러로 npm build 실패 → 참조 제거.
- backend ECS Task ExecutionRole에 `anthropic-workspace-id` SSM read 권한 부족 → inline policy `AnthropicWorkspaceIdAccess`.
- backend TaskRole에 `bedrock:OptimizePrompt` 권한 부족 → inline policy `BedrockOptimizePrompt`.
- `data-stack.ts`의 JWT_SECRET_KEY plaintext placeholder → `fromSecureStringParameterAttributes` 사전 생성 import.

### Security
- ANTHROPIC_API_KEY / ANTHROPIC_WORKSPACE_ID: ECS Secret (SSM SecureString) 주입.
- JWT_SECRET_KEY: SecureString import 패턴으로 통일.
- 노출된 자격증명 회수·재발급 권고 (사용자 측 실행).

### Infra
- CDK context 영구화: `existingVpcId=vpc-0dfa5610180dfa628`, `appSubnetIds`, `dataSubnetIds`, `albCertificateArn` cdk.json에 박음.
- 카드 정렬 + i18n 채널 설명 + endpoint URL.

### Docs
- 이 문서(`CHANGELOG.md`) 최초 생성.

---

## v2 — 기존 (git history 요약)

### v2-Phase 11~13
- ObservabilityStack (알람·대시보드).
- 8 stacks 전체 architecture + 9 ADRs + runbooks 문서화.
- Seoul region 적응 + 기존 VPC + CloudFront prefix list 패턴.

### v2-Phase 10
- FloatingChat (popup/iframe duality).
- InsightsPanel (AI 인사이트 위젯).

### v2-Phase 9
- SchedulerStack (AutoProber + Insights EventBridge 잡).

### v2-Phase 8
- Auto-prober를 Fargate Task로 분리 (one-shot runner).
- agent/insights/chat 모듈 분리.

### v2-Phase 7
- EdgeStack 분리 (AppServices ALB + CloudFront/WAF Edge).

### v2-Phase 6
- AppServicesStack (frontend/backend Fargate services + Internal ALB).

### v2-Phase 5
- AgentCoreStack (Memory + backend access policy). Runtime은 deferred.

### v2-Phase 4
- ClusterStack (ECS, ECR, KMS log key).

### v2-Phase 3
- DataStack (RDS PostgreSQL).
- NetworkStack을 NAT egress 모드로 revise.

### v2-Phase 2
- NetworkStack (dual VPC mode + PrivateLink endpoints).

---

## v1 — Legacy (점진적으로 정리 중)

- EC2 + Docker Compose PostgreSQL + systemd 운영.
- CloudFront → ALB → EC2 (Next.js 14 + FastAPI).
- 자동 프로빙 5분 주기, 9 모델.
- JWT + bcrypt 인증, SES 승인 이메일.
- 한글 UI (`frontend/src/lib/i18n.ts`).
