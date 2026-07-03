# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다.

작성 규칙:
- 최신 변경 사항이 위에, 과거 변경이 아래에 옵니다.
- 카테고리: `Added` / `Changed` / `Fixed` / `Removed` / `Security` / `Infra` / `Docs`
- 매 commit 시 PR 또는 작업 종료 시 한 항목 추가.

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
