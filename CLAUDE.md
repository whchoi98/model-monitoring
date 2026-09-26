# CLAUDE.md — Project Context for Claude Code

## Project Overview / 프로젝트 개요

**Amazon Bedrock LLM Monitor** (v2.30.0 — 현재 버전은 `frontend/src/lib/version.ts`가 source of truth) — A real-time dashboard for response speed, throughput, reliability, cost, and output-quality monitoring of AWS Bedrock + Anthropic CP on AWS + OpenAI (Mantle/1P) LLM channels.

**Amazon Bedrock LLM 모니터** — Bedrock + Anthropic CP on AWS 채널의 응답 속도·처리량·신뢰성·비용·출력 품질을 실시간으로 모니터링하는 대시보드.

### Tech Stack

- **Backend**: FastAPI + SQLAlchemy + RDS PostgreSQL 16 (t4g.micro, Single-AZ) + AgentCore Memory
- **Frontend**: Next.js 16 standalone + React + Tailwind + Recharts + react-markdown + FloatingChat + PWA(iPhone/iPad 홈 화면 설치 — manifest.ts·앱 아이콘·safe-area, v2.21.0)
- **Infra**: CDK v2 TypeScript / 8 stacks (Network, Data, Cluster, AgentCore, AppServices, Edge, Scheduler, Observability)
- **Edge**: CloudFront VPC Origin → Internal ALB → ECS Fargate × 2 (backend, frontend). VPC Origin → ALB는 현재 VPC 내부 HTTP:80(`edge-stack.ts` `HTTP_ONLY`, 운영 cert 정착 전 임시 — ALB는 internal + private subnet + VPC CIDR SG), ALB에는 HTTPS:443 리스너도 있음
- **Scheduling**: EventBridge Scheduler → AutoProber + Insights (`rate(5 minutes)`, Claude Platform on AWS 채널도 매 사이클 — v2.29.1에서 v2.29.0의 10분 주기를 되돌림) + ParityRun (12시간 주기) + GptBench (`rate(15 minutes)`) + FeaturesVerify (매일 17:30 UTC) + PricingSync (`rate(12 hours)`, 공식 단가 동기화 — v2.30.0) Fargate Tasks — `cdk/lib/stacks/scheduler-stack.ts`
- **AI**: Claude Sonnet 4.6 챗봇 (4 tools) + Haiku 4.5 dynamic followups + Sonnet 4.6 인사이트 잡 (KO·EN 요약) — 모델 ID는 `backend/agent/bedrock.py` `CHAT_MODEL_ID`/`INSIGHTS_MODEL_ID`, followups는 `backend/routers/chat.py` `_generate_followups`가 source of truth

자세한 v2 설계는 [`docs/architecture.md`](./docs/architecture.md) / [`docs/decisions/ADR-*.md`](./docs/decisions/) / [`.kiro/specs/v2-upgrade/`](./.kiro/specs/v2-upgrade/) (v2.0.0 당시 설계 기록 — 9개 모델, 인사이트 30분 주기 기준이라 현행과 다름).

---

## Architecture / 아키텍처 (v2)

```text
CloudFront (d36s7ml54xwemr.cloudfront.net, alias llm-monitor.whchoi.net — edge-stack.ts가 소유)
  ↓  VPC Origin (HTTP:80, VPC 내부 — 임시 HTTP_ONLY)
Internal ALB
  ├── /api/*  → backend Fargate Task (FastAPI, port 8000)
  └── /*      → frontend Fargate Task (Next.js standalone, port 3000)
                ├── /             — Dashboard (status + 55 model cards + trend)
                ├── /?view=manual — 수동 프로브 (ProbeConfigPanel + StreamingView, 결과/차트/비교 탭, auth)
                ├── /chat         — 챗봇 팝업 창 진입점 (Firefox/Safari, FloatingChat이 연다)
                ├── /prompts      — Prompt CRUD + Bedrock OptimizePrompt (auth)
                ├── /cost         — 30-day projection + per-model + channel compare (프로브 시각의 단가로 계산, v2.30.0)
                ├── /pricing      — 비용 단가 (모델 패밀리 × 채널 Standard 입력/출력 단가 + 번호 각주 출처 + CSV/Markdown/JSON 다운로드 + 면책 문구, 12시간 자동 갱신, v2.30.0)
                ├── /reliability  — Family/channel success rate + error buckets
                ├── /efficiency   — 0-100 Token Efficiency Score (weighted)
                ├── /analysis     — Stop reason 분포 + Output length 분포
                ├── /models       — Model Explorer (모델 카드 + 코드 예제 + 링크, v2.9.0)
                ├── /parity       — Parity Run (모델×surface×피처 실행-증거 매트릭스, v2.11.0)
                ├── /gpt-on-aws   — GPT on AWS (GPT 18채널 TTFB/TTFT 벤치 — Mantle 인리전 11 + CRIS 7 — Terra Global 포함 v2.20.1, GPT-6 Astra 3채널 v2.25.1, GPT-6 Sol/Luna 6채널 v2.28.0, 15분 주기)
                └── /claude-features — Claude API Features (33 문서 피처 × CP/Mantle/Bedrock(Messages API·InvokeModel·Converse) × 대표 5모델 실행-증거 + 문서 드리프트, v2.23.0; Opus 5.5 편입 v2.28.0)

EventBridge Scheduler (rate 5 min)
  ├── AutoProber Fargate Task  → 1 cycle = 55 models × 1 workload preset (round-robin 6 categories);
  │                              Claude Platform on AWS 9채널(anthropic:*)도 매 사이클 같은 카테고리 (v2.29.1 복귀; ANTHROPIC_CP_PROBE_INTERVAL_S=600이면 두 사이클에 한 번 + 자체 회전)
  ├── Insights Fargate Task    → Sonnet 4.6 KO+EN summary (`INSIGHTS_MODEL_ID`), save Insight row
  ├── ParityRun Fargate Task   → 12시간 주기 모델×surface×피처 실행-증거 스윕 (v2.12.0)
  ├── GptBench Fargate Task    → 15분 주기 GPT 18채널(Mantle 인리전 11 + Global/US CRIS 7) × 10회 TTFB/TTFT 벤치 (v2.18.0; Terra Global CRIS 포함 v2.20.1, GPT-6 Astra 3채널 v2.25.1, GPT-6 Sol/Luna 6채널 v2.28.0)
  ├── FeaturesVerify Fargate Task → 일 1회(cron 17:30 UTC = 02:30 KST 고정, v2.29.0) Claude API Features 39행(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1) × 5 surface × 대표 5모델 = 975셀 실행-증거 스윕 (v2.23.0; Opus 5.5 편입 v2.28.0)
  └── PricingSync Fargate Task → 12시간 주기(rate(12 hours)) 공식 단가 동기화 — Bedrock agreement offer rate card + AWS Price List + Anthropic pricing.md → price_history (50% 초과 변경은 관리자 승인 대기, v2.30.0, ADR-030)

Backend ↔ Bedrock (Seoul region inference profiles us.*, global.*) + Anthropic CP on AWS + OpenAI (Bedrock Mantle + 1P direct api.openai.com)
                                  (aws-external-anthropic.us-east-2.api.aws, workspace-id header)
```

`/api/auto-probe/status`는 in-process state가 아닌 **DB의 최근 `ProbeRun(is_auto=1)` row를 source of truth**로 사용 (Fargate task 분리 이후 일관성 확보).

---

## Directory Structure / 디렉토리 구조

```text
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI entrypoint + lifespan (DB migration with pg_advisory_lock + statement_timeout + lock_timeout)
│   ├── auto_prober.py       # run_cycle() — EventBridge가 호출하는 1회성 함수 (NOT daemon); 멈춘 모델은 오류 행 + run completed (v2.28.2); _plan_cycle = CP 주기 노브(기본 매 사이클, 600이면 두 사이클에 한 번 + 자체 회전 — v2.29.0, 기본값 v2.29.1)
│   ├── probe_cadence.py     # 채널별 수집 주기 — ANTHROPIC_CP_PROBE_INTERVAL_S(기본 300 = 매 사이클, v2.29.1), interval_for(), channel_intervals() (v2.29.0)
│   ├── latest_results.py    # /latest와 챗봇 공용, 모델별 최신 자동 행 (모델 주기 기준 bounded 범위, v2.29.0)
│   ├── auto_prober_runner.py # CLI entry: `python -m auto_prober_runner --once`
│   ├── insights_runner.py   # CLI entry: `python -m insights_runner --window 6h` (Insights Fargate task)
│   ├── stream_watchdog.py   # 스트림 wall-clock watchdog — prober·gptbench 공용 (v2.28.2)
│   ├── label_repair.py      # 기동 시 저장 행 model_name을 카탈로그 라벨로 정정 (v2.22.1)
│   ├── visibility.py        # 조회 노출 필터 — HIDDEN_MODEL_PATTERNS (기본 `(1P)`) (v2.19.1)
│   ├── tests/               # pytest (python3.12)
│   ├── prober.py            # Probe logic (Bedrock + Anthropic CP + OpenAI Mantle/Global/US/1P), AVAILABLE_MODELS (55개 활성 + 1P 5개 휴면), retry, stop_reason capture
│   ├── pricing_sources.py   # 단가 순수 데이터 — price_identity(model_id → family/채널/출처), 오퍼 FM id, Anthropic 문서 모델명, Price List usagetype 매핑, PROVIDER_ORDER, FAMILY_ORDER(프런트와 동일, pytest 고정), DISCLAIMER, OFFICIAL_PAGES, PRICE_NOTES (v2.30.0)
│   ├── pricing_seed.py      # 활성 55채널 공식 단가 seed(SEED, CP는 CP_SEED family_key 단위) + ensure_seed(model_id 단위 멱등, SET LOCAL statement_timeout 30초와 lock_timeout 5초 뒤 pg_advisory_xact_lock(917350003))
│   ├── pricing_parsers.py   # 출처별 순수 파서 — offers rateCard(DIMENSION_RE 허용 목록), Price List(1K → 1M), Anthropic markdown(헤더 이름, <sup> 제거, 정확 일치)
│   ├── pricing_sync.py      # 12시간 동기화 — 가져오기, 관측 값 소수 6자리 정규화, 비교(CHANGE_THRESHOLD 0.5 경계 포함), pending_review, price_sync_runs 기록, 상한 300초. 파서 예외는 종류와 상관없이 그 출처 채널만 skipped:parse_failed
│   ├── pricing_sync_runner.py # CLI entry: `python -m pricing_sync_runner --once` (PricingSync Fargate task) — create_tables → CP/OpenAI 등록 → ensure_seed → run_sync(pg_try_advisory_lock(917350004) — 점유 중이면 즉시 exit 1) → os._exit
│   ├── price_history.py     # 유효 단가 조회, 행 단위 비용 서브쿼리(with_row_cost — /api/cost/*, /api/efficiency/score), verification(seed_only/verified/stale)
│   ├── pricing_payload.py   # /api/pricing 응답 조립(표시 순서, 각주 번호, 참고 자료) + 숫자 직렬화
│   ├── pricing_export.py    # CSV(BOM + 따옴표로 감싼 면책 첫 줄), Markdown, JSON 내보내기 순수 함수
│   ├── auth.py              # JWT + bcrypt + ADMIN_EMAIL=whchoi98@gmail.com
│   ├── models.py            # ProbeResult.stop_reason, .category 컬럼 포함
│   ├── schemas.py           # Pydantic; ProbeResultResponse.stop_reason Optional
│   ├── database.py          # pool_size=5, max_overflow=5, pool_recycle=300, pool_timeout=10
│   ├── retention.py         # RETENTION_DAYS 초과 probe_results → probe_results_hourly 집계 이관
│   ├── anomalies.py         # 최근 N시간 프로브 실패 요약 (대시보드 이상 징후 박스, v2.12.0)
│   ├── parity_runner.py     # CLI entry: `python -m parity_runner --once` (ParityRun Fargate task)
│   ├── gptbench.py          # GPT on AWS 벤치 사이클 (GPT 18채널 = Mantle 인리전 11 + CRIS 7, × 10회 — Terra Global 포함 v2.20.1, GPT-6 Astra 3채널 v2.25.1, GPT-6 Sol/Luna 6채널 v2.28.0, TTFB/TTFT/GAP; 호출당 wall-clock watchdog + max_retries=0 v2.28.0)
│   ├── gptbench_runner.py   # CLI entry: `python -m gptbench_runner --once` (15분 스케줄)
│   ├── requirements.txt     # email-validator 포함 (EmailStr)
│   ├── agent/               # 챗봇 core: bedrock.py(CHAT/INSIGHTS model ID), tools.py(4 tools), memory.py(AgentCore), streaming.py
│   ├── parity/              # 패리티 런 엔진: catalog.py(6 surface×19 피처), engine.py(판정 순수 로직), probes.py(surface별 실행기+요청 스냅샷), runner.py(오케스트레이터)
│   ├── claude_features/     # Claude API Features 검증 엔진: catalog.py(39행×5 surface), transports.py(raw httpx/boto3), probes.py, engine.py(판정 순수 로직), runner.py (v2.23.0)
│   ├── features_runner.py   # CLI entry: `python -m features_runner --once` (FeaturesVerify Fargate task)
│   └── routers/
│       ├── auth.py          # /api/auth/* — login(공개), register(EmailStr 강제), approve(이메일 토큰), me(인증)
│       ├── admin.py         # /api/admin/* — reset-monitoring-data, users CRUD (admin only)
│       ├── auto_probe.py    # /api/auto-probe/* — status(DB-sourced), latest, trend, categories, trigger, anomalies(12h 실패 요약)
│       ├── probes.py        # /api/probes/run — SSE streaming probe (auth)
│       ├── results.py       # /api/results/* — stored results query + stats
│       ├── models.py        # /api/models — AVAILABLE_MODELS list
│       ├── prompts.py       # /api/prompts/* — prompt set CRUD + Bedrock OptimizePrompt (auth)
│       ├── chat.py          # /api/chat/stream — Sonnet 4.6 + 4 tools + dynamic followups
│       ├── insights.py      # /api/insights/* — list/latest/stream-regenerate
│       ├── cost.py          # /api/cost/* — summary, channel-compare, trend (행 단위 시점 단가, v2.30.0)
│       ├── pricing.py       # /api/pricing(60초 캐시), /api/pricing/export(csv|md|json) 공개 + admin_router /api/admin/pricing/pending, approve, reject (v2.30.0)
│       ├── reliability.py   # /api/reliability/multi-channel — family/channel grouped
│       ├── efficiency.py    # /api/efficiency/score — 0-100 weighted score per category
│       ├── analysis.py      # /api/analysis/* — stop-reasons, output-length (v2.1.0)
│       ├── compare.py       # /api/compare/run — Comparison Lab: 1 prompt → N models 병렬, SSE (auth)
│       ├── parity.py        # /api/parity/* — catalog, latest(+직전 런 diff), evidence, trigger(auth)
│       ├── gptbench.py      # /api/gptbench/* — latest(스코어 카드), trend(사이클 시계열) (v2.18.0)
│       └── features.py      # /api/features/* — catalog, latest(+diff+drift), evidence, trigger(auth) (v2.23.0)
├── frontend/
│   ├── src/
│   │   ├── app/             # App Router pages (force-dynamic)
│   │   │   ├── page.tsx           # Dashboard (status + 55 cards + trend + workload filter)
│   │   │   ├── models/page.tsx    # Model Explorer (v2.9.0)
│   │   │   ├── parity/page.tsx    # Parity Run 매트릭스 (v2.11.0)
│   │   │   ├── gpt-on-aws/page.tsx # GPT on AWS 벤치 (v2.18.0)
│   │   │   ├── claude-features/page.tsx # Claude API Features 매트릭스 (v2.23.0)
│   │   │   ├── chat/page.tsx      # 챗봇 팝업 창 (ChatPanel variant="popup")
│   │   │   ├── prompts/page.tsx   # login-gate + PromptsPanel
│   │   │   ├── cost/page.tsx
│   │   │   ├── pricing/page.tsx   # 비용 단가 (v2.30.0)
│   │   │   ├── reliability/page.tsx
│   │   │   ├── efficiency/page.tsx
│   │   │   └── analysis/page.tsx  # v2.1.0
│   │   ├── components/
│   │   │   ├── AppShell.tsx             # 페이지 공용 셸 — AppHeader + FloatingChat
│   │   │   ├── Providers.tsx            # LanguageProvider + AuthProvider (layout.tsx)
│   │   │   ├── AppHeader.tsx            # 공용 헤더 — 데스크톱 내비 + 모바일 햄버거, `AppShell.tsx`가 렌더링 (v2.16.0)
│   │   │   ├── DataState.tsx / Dialog.tsx / RefreshControls.tsx / ThemeToggle.tsx  # 공용 로딩·오류·빈 상태, 모달, 새로고침, 테마 토글
│   │   │   ├── MonitoringOverview.tsx   # 대시보드 건강 요약 + HealthBadge (lib/monitoring.ts)
│   │   │   ├── ProbeConfigPanel.tsx / StreamingView.tsx / ComparisonView.tsx  # 수동 프로브 뷰 (`/?view=manual`)
│   │   │   ├── ComparePanel.tsx         # Comparison Lab (/api/compare/run) — 현재 어느 페이지에도 마운트되지 않음
│   │   │   ├── GptOnAwsPanel.tsx        # GPT on AWS 스코어 카드 + 시계열 (v2.18.0)
│   │   │   ├── RumProvider.tsx          # RUM 수집 — 자체 호스팅 rum-sdk 로드, NEXT_PUBLIC_RUM_* 미설정 시 비활성 (v2.16.5)
│   │   │   ├── AutoDashboard.tsx        # workload category filter + multi-select model
│   │   │   ├── ModelStatusGrid.tsx      # family-grouped 55 cards (Bedrock prefix) + 지표 값 등급 색(양호 파랑/경고 호박 ▲/위험 장미 ◆, data-grade, 범례 + 접이식 기준표 — lib/metricGrade.ts, ADR-029, v2.28.0)
│   │   │   ├── TrendChart.tsx           # MODEL_COLORS 라벨 (21 Bedrock + 9 Anthropic CP + 25 OpenAI Mantle/Global/US 활성; 1P 5개는 휴면)
│   │   │   ├── CostDashboardPanel.tsx   # 방법론 문단이 /pricing으로 연결 (v2.30.0)
│   │   │   ├── PricingPanel.tsx         # 비용 단가 표(제공사 섹션, 채널 4열, 각주 → #ref-n) + 면책 상자 + 마지막 공식 단가 동기화 + 다운로드 3종 + 참고 자료 (v2.30.0)
│   │   │   ├── ReliabilityPanel.tsx
│   │   │   ├── EfficiencyPanel.tsx
│   │   │   ├── AnalysisPanel.tsx        # v2.1.0
│   │   │   ├── InsightsPanel.tsx        # SSE stream-regenerate
│   │   │   ├── PromptsPanel.tsx         # OptimizePrompt
│   │   │   ├── ModelExplorer.tsx        # 모델 카드 + API 탭(Converse/InvokeModel/Messages/Responses) 코드 예제 (v2.9.x)
│   │   │   ├── ParityPanel.tsx          # 패리티 매트릭스 + 증거 모달 + 수동 트리거 (v2.11.0)
│   │   │   ├── ClaudeFeaturesPanel.tsx  # Claude API Features 5열(CP/Mantle/Bedrock 3서브열) 매트릭스 + 헬스 카드(docHealth, 클릭 → Key Findings 드로어) + 모델 칩 + 드리프트/변경(kind) 배너 + 증거 모달 + 수동 트리거 (v2.24.0)
│   │   │   └── chat/                    # FloatingChat + ChatModal/Panel/Input
│   │   ├── hooks/                       # useAsyncResource, useAutoRefresh, useProbeStream, useChatStream, usePageTitle, useUaPopupStrategy
│   │   └── lib/
│   │       ├── api.ts                   # 모든 fetch 함수 (auth token mgmt)
│   │       ├── http.ts / auth-context.tsx / types.ts / format.ts  # fetchJson+ApiError, AuthProvider/useAuth, 공용 타입, 시각 포맷(UTC 파싱)
│   │       ├── monitoring.ts / trendSelection.ts / pivotTrend.ts / costProjection.ts  # 카드 건강·신선도, 트렌드 선택·URL 상태, 트렌드 피벗, 비용 외삽
│   │       ├── i18n.ts + i18n-context.tsx  # KO/EN
│   │       ├── sortModels.ts            # FAMILY_ORDER, groupByFamily, channelRank, EXCLUDED_FAMILIES/isExcludedModel
│   │       ├── pricing.ts               # formatCost만 (v2.30.0부터 단가 표는 backend /api/pricing — 프런트 미러 없음)
│   │       ├── pricingTable.ts          # /pricing 순수 함수 — formatUnitPrice, formatPricePair, tierBadges, costFromPrices (정렬과 번호 매기기 없음, v2.30.0)
│   │       ├── theme.ts + chartTheme.ts # 다크/화이트 테마 (v2.8.0)
│   │       ├── modelExplorer.ts         # 채널/네이티브ID/코드예제/링크 유도 (lang 파라미터로 KO/EN, v2.16.2)
│   │       ├── claudeFeatures.ts        # Claude API Features 매트릭스 순수 로직 — 셀 집계·그룹 구성(modelKey, modelOrder)·surfaceSummary/surfaceFindings·labelMaps·지연시간 헬퍼 (v2.24.0)
│   │       ├── metricGrade.ts           # 대시보드 카드 지표 등급 단일 출처 — 카테고리별 TTFT/총 응답시간 임계치, TPS 공통(<40 경고, <15 위험), roundForDisplay, 색·표지 (v2.28.0, ADR-029)
│   │       └── version.ts               # APP_VERSION (single source of truth)
│   └── next.config.mjs / src/proxy.ts
├── cdk/                                  # lib/stacks/ 8 stacks + lib/constructs/{fargate-service,pinned-image}.ts (TypeScript)
└── docs/
    ├── architecture.md, api-reference.md
    ├── decisions/ADR-001~030.md
    └── runbooks/deploy.md, rollback.md, troubleshooting.md
```

---

## Key Commands / 주요 명령어

```bash
# Local dev
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev

# Test
make verify                                            # CDK lint·typecheck·test·synth + backend + frontend (e2e 제외 — `make test-ui`)
cd backend && python3.12 -m pytest tests/ -q           # 3.10+ 필요 (dev 호스트 시스템 python3는 3.9)
cd frontend && npm test && npm run typecheck && npm run test:e2e   # vitest + tsc + Playwright
cd cdk && npm test                                     # jest

# Container build/push (production) — IMMUTABLE TAG REQUIRED
REGION=ap-northeast-2; ACCT=061525506239
TAG="v$(date +%s)"   # NEVER use :latest in production task def
docker build --no-cache --pull --platform linux/arm64 -t bedrock-monitor-backend:$TAG backend/
# frontend는 RUM build args 필수 (누락 시 RUM 꺼진 이미지) — 값은 .env.example/SSM 참고
# docker build --no-cache --pull --platform linux/arm64 \
#   --build-arg NEXT_PUBLIC_RUM_ENDPOINT=... --build-arg NEXT_PUBLIC_RUM_API_KEY=... \
#   -t bedrock-monitor-frontend:$TAG frontend/
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCT.dkr.ecr.$REGION.amazonaws.com
docker tag bedrock-monitor-backend:$TAG $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG

# Deploy (digest 고정 — cdk/lib/constructs/pinned-image.ts, 2026-07-09 CDK가 :latest로 되돌린 실사고 방지.
#   -c backendImage/-c frontendImage를 빼면 AppServices·Scheduler가 legacy repo :latest로 synth돼 서비스가 옛 이미지로 돌아간다)
# cd cdk && npx cdk deploy BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never \
#   -c backendImage="<repo>:$TAG@sha256:<digest>" -c frontendImage="<repo>:$TAG@sha256:<digest>"
#   ⚠️ <repo>는 레지스트리 호스트 포함 전체 URI ($ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2).
#      repo 이름만 넘기면 ECS가 docker.io/library/…로 해석 → pull 실패 → 서킷 브레이커 롤백 (2026-08-01 실사고)
# (see docs/runbooks/deploy.md for full procedure including autoprober/parityrun schedules)

# Verify
curl https://d36s7ml54xwemr.cloudfront.net/api/auto-probe/status
curl https://d36s7ml54xwemr.cloudfront.net/api/auto-probe/latest

# Admin operations (need SEED_ADMIN_PASSWORD)
TOKEN=$(curl -sX POST https://d36s7ml54xwemr.cloudfront.net/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"<pw>"}' | jq -r .access_token)
curl https://d36s7ml54xwemr.cloudfront.net/api/admin/users -H "Authorization: Bearer $TOKEN"
curl -X DELETE "https://d36s7ml54xwemr.cloudfront.net/api/admin/users/<username>" -H "Authorization: Bearer $TOKEN"
curl -X POST "https://d36s7ml54xwemr.cloudfront.net/api/admin/users/<username>/approve" -H "Authorization: Bearer $TOKEN"
```

---

## Monitored Models (55 active) / 모니터링 대상 모델 (활성 55개 — 1P 5개 휴면 제외)

| Family | Global (ap-northeast-2 cross-region) | US (us-east-1 cross-region) | Anthropic CP on AWS |
|--------|--------------------------------------|------------------------------|---------------------|
| Claude Fable 5.1 (v2.22.0) | ✅ | ✅ | ✅ (CP 서빙 시 자동 등록 — 선등록) |
| Claude Fable 5 | ✅ | ✅ | ✅ |
| Claude Opus 5.5 (v2.27.0) | ✅ | ✅ | ✅ |
| Claude Opus 5 (v2.19.0) | ✅ | ✅ | ✅ (2026-07-29 조직 복구로 자동 등록) |
| Claude Opus 4.8 | ✅ | ✅ | ✅ |
| Claude Opus 4.7 | ✅ | ✅ | ✅ |
| Claude Opus 4.6 | ✅ | ✅ | — |
| Claude Sonnet 5 | ✅ | ✅ | ✅ |
| Claude Sonnet 4.6 | ✅ | ✅ | ✅ |
| Claude Haiku 4.5 | ✅ | ✅ | ✅ |
| Amazon Nova 2.0 Lite | — | ✅ | — |

**OpenAI (Bedrock Mantle, in-region)** (v2.4.0):

| Family | Global CRIS (v2.20.0) | US CRIS (v2.25.0) | us-east-1 | us-east-2 | us-west-2 | 1P direct (휴면) |
|--------|-----------------------|-------------------|-----------|-----------|-----------|-----------|
| GPT 6 Astra (v2.25.0) | ✅ | ✅ | — 미지원(제외, 2026-09-23 사용자 결정) | — 미지원(제외, 2026-09-23 사용자 결정) | ✅ | — |
| GPT 6 Sol (v2.27.0) | ✅ | ✅ | ✅ | — 미지원(제외, 2026-09-23 사용자 결정) | — 미지원(제외, 2026-09-23 사용자 결정) | — |
| GPT 6 Luna (v2.27.0) | ✅ | ✅ | ✅ | — 미지원(제외, 2026-09-23 사용자 결정) | — 미지원(제외, 2026-09-23 사용자 결정) | — |
| GPT 5.6 Sol (v2.17.0) | ✅ | — | ✅ | ✅ | — | ✅ |
| GPT 5.6 Terra (v2.17.0) | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| GPT 5.6 Luna (v2.17.0) | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| GPT 5.5 | — | — | ✅ | ✅ | — | ✅ (v2.6.0) |
| GPT 5.4 | — | — | ✅ | ✅ | ✅ | ✅ (v2.6.0) |

- **Mantle (Path 4)** model_id 키: `openai:<region>:openai.gpt-5.x`. 라벨: `OpenAI GPT 5.x (<region>)`. OpenAI-compatible `/openai/v1` + Bedrock bearer 토큰(`OPENAI_API_KEY`, `ABSK-…`). 자세히는 ADR-019.
- **Global CRIS (v2.20.0, 2026-08-18)**: GPT-5.6 세대(Sol/Terra/Luna) 이상만 Bedrock global cross-region inference profile 지원 (2026-08-17 AWS 발표, GPT-6 Astra는 v2.25.0, GPT-6 Sol/Luna는 v2.27.0에서 합류 — ADR-027, ADR-028). 키: `openai:global:global.openai.gpt-5.6-*` (pseudo-region `global`, 프로파일 id는 in-region id에 `global.` 접두사를 prober가 파생 — 별도 model-id env 없음). 라벨: `OpenAI GPT 5.6 * (Global)`. **global 프로파일은 bedrock-mantle 호스트 미지원** — `OPENAI_GLOBAL_BASE_URL=https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1`(Seoul bedrock-runtime OpenAI-compat, 기존 `OPENAI_API_KEY` bearer 재사용)로만 호출. **단가가 in-region보다 저렴**해 채널마다 단가 행이 따로 있다(v2.30.0부터 `price_history`의 model_id 단위 행, ADR-030 — 이전의 `-global` suffix 키는 ADR-025). gptbench(`_BENCH_SPECS`)에는 GPT-5.6 세대 중 Terra Global만 포함(v2.20.1, 5.6 Sol/Luna Global 미포함)이며 GPT-6 Astra Global은 v2.25.1, GPT-6 Sol/Luna Global은 v2.28.0에서 포함 — 벤치 18채널 = Mantle 인리전 11 + CRIS 7(Global 4 + US 3).
- **GPT-6 Astra (v2.25.0, 2026-09-09)**: 채널 3개. 1. Global CRIS `openai:global:global.openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (Global)`, 기존 `OPENAI_GLOBAL_BASE_URL`(Seoul bedrock-runtime) 재사용. 2. **US CRIS — 유사 리전 `us`** `openai:us:us.openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (US)`, env `OPENAI_US_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1`. 3. Mantle 인리전 `openai:us-west-2:openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (us-west-2)`. Responses API 전용(5.4/5.5/5.6과 동일). env: `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID=openai.gpt-6-astra` 하나만 주입하고 Global/US 프로파일 id는 prober가 `global.`/`us.` 접두로 파생한다. **실측(2026-09-09, 운영 Bedrock 장기 키 + Responses API)**: `bedrock-mantle.us-east-1`, `bedrock-mantle.us-east-2`는 404 `not_found_error`("The model does not exist") — Bedrock 모델 액세스는 전 리전 AVAILABLE/AUTHORIZED이므로 엔티틀먼트가 아니라 Mantle 호스트 온보딩 미완이며, 404 리전을 스펙에 넣으면 프로브가 전부 오류 행이 되므로 두 리전은 제외했다 — **2026-09-23 사용자 결정으로 "현재 미지원 — 제외" 확정**(정기 재확인 대상 아님, AWS가 지원을 발표하면 스펙 튜플에 리전만 추가, ADR-027 v2.28.0 후속). 접두사 없는 평문 id(`openai.gpt-6-astra`)는 온디맨드 호출 불가(추론 프로파일 필요). **단가 (v2.27.0에서 반영 — AWS 공식 모델 카드, Standard, 입력 272K 이하)**: `gpt-6-astra`(인리전 us-west-2) $11/$55, `gpt-6-astra-us`(US CRIS) $11/$55, `gpt-6-astra-global` $10/$50 per MTok — v2.30.0부터 `pricing_seed.SEED`에 model_id 단위로 두고 12시간마다 agreement offer로 확인한다(정확 일치라 prefix fallback 없음, ADR-030). 2026-09-23 재측정에서도 Mantle us-east-1/us-east-2는 404(위 사용자 결정의 근거). gptbench `_BENCH_SPECS` 포함(v2.25.1 — Global, US CRIS, us-west-2 3채널로 벤치 9 → 12채널, v2.28.0 Sol/Luna 합류로 18채널), 1P 스펙 미추가. 자세히는 ADR-027. **패리티 `_REASONING_MARKERS`에 `gpt-6` 미포함**: Responses `reasoning.effort`/chat `reasoning_effort`를 수락하지만 `reasoning_tokens`를 0으로 보고해(2026-09-09 라이브) `reasoning`/`reasoning_effort` 12셀은 skipped 유지 — 판단 근거는 ADR-027.
- **GPT-6 Sol / GPT-6 Luna (v2.27.0, 2026-09-23)**: 2026-09-22 출시(출시 당시 AWS 모델 카드 미게재 — 2026-09-26 게시 확인, 값은 오퍼와 일치). 모델마다 채널 3개: Global CRIS `openai:global:global.openai.gpt-6-{sol,luna}`(라벨 `OpenAI GPT 6 {Sol,Luna} (Global)`), US CRIS `openai:us:us.openai.gpt-6-{sol,luna}`(`(US)`), Mantle 인리전 `openai:us-east-1:openai.gpt-6-{sol,luna}`(`(us-east-1)`). env: `BEDROCK_OPENAI_GPT_6_{SOL,LUNA}_MODEL_ID` 하나씩, Global/US 프로파일 id는 prober가 파생. **실측(2026-09-23)**: Mantle us-east-2/us-west-2는 404 `not_found_error`("The model 'openai.gpt-6-sol' does not exist")라 제외 — Astra(Mantle us-west-2 단독)와 정반대. **2026-09-23 사용자 결정(v2.28.1): "현재 미지원 — 제외"**, 정기 재확인 대상 아님(AWS가 지원을 발표하면 스펙 튜플에 리전만 추가). Mantle us-east-1 첫 호출은 401 "Your subscription to the model is being set up"(Marketplace 구독 개시) → 수 분 뒤 200. 서울 기준 단건: Sol Global TTFB 559/TTFT 856ms, US 927/2059ms · Luna Global 591/857ms, US 919/1064ms. **단가 (v2.28.0에서 반영 — 출처: Bedrock `ListFoundationModelAgreementOffers` rate card, v2.30.0부터 PricingSync가 12시간마다 같은 API로 확인)**: `gpt-6-sol`(인리전 us-east-1)·`gpt-6-sol-us` $2.20/$11, `gpt-6-sol-global` $2/$10, `gpt-6-luna`·`gpt-6-luna-us` $0.11/$0.55, `gpt-6-luna-global` $0.10/$0.50 per MTok. offer: Sol `offer-pycji3sz5gpcc`, Luna `offer-gmo53nkzc5or6` — `*_standard` = In-Region + Geo CRIS, `*_global_standard` = Global CRIS. 같은 API의 Astra offer(`offer-7epta7rbw5aws`)가 Astra 공식 카드와 정확히 일치함을 교차 검증했고, 값은 OpenAI 정가 + In-Region/Geo 10%와도 같다. 모델 카드 게시 후 재대조 완료(2026-09-26, 일치 — ADR-028 후속). **패리티 `_REASONING_MARKERS`에 `gpt-6` 미포함**: 패리티 프로브(effort low, "17 x 23은?")에서 `reasoning_tokens=0`(effort high에서만 13/18) → 넣으면 미지원 오판. gptbench `_BENCH_SPECS`에는 v2.28.0에서 6채널 모두 편입(목록 끝 — 데드라인 컷이 신규 채널에 먼저 떨어짐, 벤치 요청 형태 라이브 200, Sol `reasoning_tokens` 0, Luna 34~47), 1P 스펙 미추가. 자세히는 ADR-028(+ v2.28.0 후속).
- **1P direct (Path 5, v2.6.0 — v2.19.1부터 휴면/비노출)** model_id 키: `openai:1p:gpt-5.x`. 라벨: `OpenAI GPT 5.x (1P)`. `https://api.openai.com/v1` 직접 호출 + **OpenAI platform 키**(`OPENAI_1P_API_KEY`, `sk-proj-…` — Mantle bearer와 호환 불가). native id(`gpt-5.x`, 접두사 없음). 리전 개념 없음(글로벌 라우팅). env: `OPENAI_1P_API_KEY`(SSM `/bedrock-monitor/openai-1p-api-key`), `OPENAI_1P_GPT_54/55_MODEL_ID`, `OPENAI_1P_BASE_URL`(선택). 자세히는 ADR-020. **2026-07-31 사용자 결정으로 비교에서 제외(비노출)**: 코드·DB 행은 보존, CDK `ENABLE_OPENAI_1P=false`로 env 미주입(등록 skip) + backend `visibility.py` `(1P)` 라벨 조회 필터 + frontend `EXCLUDED_FAMILIES` 하드필터. 재노출 = CDK 플래그 true + 유효 키 SSM 저장 + `HIDDEN_MODEL_PATTERNS=""` env + EXCLUDED_FAMILIES에서 제거 + **1P 단가 출처 설계 선행** (v2.30.0부터 단가는 `price_history` model_id 단위이고 `pricing_sources.price_identity`가 1P id를 분류하지 않아 1P 비용은 "-"다. 재노출하려면 `pricing_sources.py` 분류, `pricing_seed.py` 1P 정가 seed, 1P 공식 출처 동기화를 함께 추가한다 — 1P 정가는 in-region 단가와 다르다: Terra/Luna는 in-region이 10% 높고 Sol은 in-region 프로모션 단가($4.40/$22)가 1P 정가($5/$30)보다 낮다, ADR-020, ADR-030).
- **GPT-5.6 세대 (v2.17.0, 2026-07-14)**: Sol(최상위)/Terra(균형)/Luna(저비용) — Mantle native id `openai.gpt-5.6-{sol,terra,luna}`, 1P native id `gpt-5.6-{sol,terra,luna}`. **Sol은 us-west-2 미제공**. Responses API 전용(5.4/5.5와 동일). env: `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID` + `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`. **현행 단가 (v2.20.0에서 교정 — 2026-07-30 AWS 인하 Luna -80%·Terra -20% 반영, 공식 모델 카드 Standard tier 기준)**: in-region/Geo Sol $4.40/$22(**v2.28.1 프로모션 단가 — 공식 출처에는 종료일이 없고 "최소 2026-11-21까지"는 `pricing_sources.PRICE_NOTES` 수동 메모, 구 $5.50/$33. 종료로 구 단가에 돌아오면 +25%/+50%라 50% 경계 포함으로 자동 적용**), Terra $2.20/$13.20, Luna $0.22/$1.32 · Global CRIS Sol $4/$20(프로모션, 구 $5/$30), Terra $2/$12, Luna $0.20/$1.20 per MTok.

- **Claude Fable 5.1 (v2.22.0, 2026-09-01)**: 2026-08-31 출시. Bedrock 프로파일 `global.`/`us.anthropic.claude-fable-5-1` (Seoul·us-east-1 모두 ACTIVE, 라이브 converse 검증). Fable 5와 동일 Covered Model 제약(provider_data_share 리전 opt-in 기존 적용) + 동일 단가 $10/$50(US $11/$55 — v2.30.0 교정). **forced `tool_choice`(type tool/any)는 400 거부** → 패리티 `tool_use` 프로브는 `parity/catalog.py` `supports_forced_tool_choice()`로 `auto`+프롬프트 지시로 대체. CP 채널은 `_ANTHROPIC_TARGETS` 선등록(`fable-5-1`) — `fable-5` substring 접두 충돌은 `_match_anthropic_model()`이 처리.
- **Claude Opus 5.5 (v2.27.0, 2026-09-23)**: 2026-09-22 출시([AWS 모델 카드](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html)). Bedrock `global.anthropic.claude-opus-5-5`(Seoul — Seoul은 Global CRIS만, Geo 없음) + `us.anthropic.claude-opus-5-5`(us-east-1) + CP `anthropic:claude-opus-5-5`(타깃 `opus-5-5`를 `opus-5` 앞에). 라이브 converse_stream 200(TTFT 약 2.8s), CP 200. **temperature 400 + forced `tool_choice` 400** → `_REASONING_MODEL_PATTERNS`의 `"opus-5"`가 substring으로 포함, 패리티 `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"opus-5-5"` 추가(Opus 5는 forced 유지). 단가 $4/$20(US $4.40/$22 — v2.30.0 교정). v2.30.0부터 model_id 정확 일치라 prefix fallback이 없고, Anthropic 문서 표도 "Claude Opus 5.5"가 "Claude Opus 5"보다 먼저 나오므로 CP 매핑은 정확 일치만 쓴다(ADR-030). **CP 오등록 실사고(2026-09-23)**: CP `/v1/models`가 `claude-opus-5-5`를 `claude-opus-5`보다 먼저 반환해 구 코드가 5.5 id를 `Anthropic Claude Opus 5 (US)`로 프로빙(실제 Opus 5 CP 미측정) → 타깃 추가 + `_is_point_release_of()` 가드(substring 뒤 `-<1~2자리 숫자>`가 오는 id는 자기 타깃 없으면 제외, 8자리 날짜 서픽스는 매칭 유지)로 **다음 점 버전(예: sonnet-5-5)도 fail-closed**. 저장 행은 backend 기동 시 `label_repair.py`가 정정. v2.28.0부터 `/claude-features` 5번째 대표 모델(ADR-026 부록). 자세히는 ADR-028.

**제외 모델 (2026-05-20부터)**: Opus 4.5, Sonnet 4.5 — 사용자 요청으로 모니터링 대상에서 제외. Frontend hard-filter(`lib/sortModels.ts` `EXCLUDED_FAMILIES`/`isExcludedModel` — AutoDashboard, ModelExplorer, `lib/monitoring.ts`가 사용)도 적용해서 backend silent bug 대비.

**Claude API Features (v2.23.0)**: `/claude-features` 페이지는 위 55개 모니터링 모델과 별개로 대표 5모델(Claude Fable 5.1·Fable 5·Opus 5.5·Opus 5·Sonnet 5 — Opus 5.5는 v2.28.0 편입, 카탈로그 `MODELS` 순서가 UI 순서)만 고정 사용해 39행(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1) × 5 surface(CP on AWS/Mantle `/anthropic`/Bedrock runtime Messages API/Bedrock InvokeModel/Bedrock Converse)를 일 1회 실행-증거로 검증한다(1런 = 프로브 813 + 사전판정 162 = 975셀, 약 9분). Opus 5.5는 forced `tool_choice` 400이라 `tool_use`를 auto + 지시로, advisor는 자기 페어링(`claude-opus-5-5`), computer use는 toolset 전용. `fallback_credit` beta 이름은 CP `2026-07-01`, Mantle과 Bedrock `2026-06-01`. Mantle 열은 Fable 5.1을 제외(US GovCloud 전용 → `not_applicable`). **실측(2026-09-05)**: Mantle 리전 `ap-northeast-1`은 이 계정에서 `anthropic.claude-{fable-5,opus-5,sonnet-5}`를 서빙하지 않음(`not_found_error`) — Opus 4.8만 서빙, sonnet-5는 `us-east-1`에서 서빙(200 확인) → **사용자 결정으로 Mantle 열 리전을 `us-east-1`로 전환**(`MANTLE_ANTHROPIC_REGION` 기본값, CDK 주입). 패리티 런 `messages_mantle` surface도 같은 env를 공유해 배포 환경에서는 `us-east-1`을 프로빙한다(`parity/runner.py` 코드 기본값은 `ap-northeast-1`, CDK가 명시 주입으로 override). 자세한 드리프트는 ADR-026. **v2.24.0 UI 상세도 보강(패리티 수준)**: 헬스 카드 헤드라인은 문서 기준 헬스(docHealth = 문서상 GA/Beta ∧ 실측 셀 중 supported 비율) + 6상태 분포 막대, 카드 클릭 → Key Findings 드로어(6섹션), 모델 칩(전체/모델별), 변경 배너 `kind`(카탈로그 규칙/실측) 태그, 셀 툴팁 모델별 지연시간; 백엔드는 실패 셀에도 요청 스냅샷 보존(스레드 로컬 recorder), 오류 문자열에 boto operation/빈 본문 라우트 표기(`engine.classify` 판정 불변, 회귀 핀 38건). ADR-026 부록 참조.

**라벨 정책**: DB의 `model_name`은 항상 `"Bedrock <family> (<channel>)"` 또는 `"Anthropic <family> (<channel>)"` prefix. OpenAI 라벨은 `"OpenAI <family> (<region>)"`(Mantle 인리전) / `"OpenAI <family> (Global)"`(Global CRIS, v2.20.0) / `"OpenAI <family> (US)"`(US CRIS, v2.25.0) / `"OpenAI <family> (1P)"`(1P direct) prefix. Frontend `MODEL_COLORS`/`FAMILY_ORDER`는 이 prefix를 expected. 정렬 순서: **Anthropic → Global(Bedrock·OpenAI 공통, `(Global)` 서픽스) → US(Bedrock US·OpenAI US CRIS, `(US)` 서픽스) → OpenAI 리전** (`channelRank` 함수). OpenAI US CRIS는 `channelRank`에서 리전 채널보다 앞선 US 티어로 분기한다(v2.25.0) — 이 분기가 없으면 ICU `localeCompare`가 `(us-west-2)`를 `(US)`보다 앞에 놓으므로 `sortModels.ts`의 분기 순서를 바꾸지 말 것.

**단가 (v2.30.0, ADR-030)**: 단가의 단일 출처는 backend `price_history` 테이블이다(`backend/pricing.py`와 `frontend/src/lib/pricing.ts`의 `PRICE_TABLE`, `get_pricing`, `estimate_cost_usd`, `getPricing`, `estimateCost`는 삭제 — 프런트 미러 없음). PricingSync 태스크가 12시간마다 공식 출처 3개(Bedrock agreement offer rate card — Bedrock Claude 20 + OpenAI 25, AWS Price List — Nova 2.0 Lite, Anthropic `pricing.md` — Claude Platform on AWS 9)에서 Standard 입력/출력 단가를 읽어 model_id 단위로 기록한다. 입력이나 출력 변화율이 0.5를 넘으면(0.5는 자동 적용) `pending_review`로 두고 관리자 승인(`POST /api/admin/pricing/pending/{id}/approve`)을 기다린다. 비용(`/api/cost/*`, `/api/efficiency/score`)은 각 프로브 시각에 유효했던 단가로 계산한다 — ADR-025의 "조회 시점 소급 계산"은 폐기됐다. 첫 동기화 이전 구간은 seed(`pricing_seed.py`, effective_from 1970-01-01)로 계산하고 v2.30.0 이전 단가 변경은 재구성하지 않았다. 코드 단가 오류 11채널(Bedrock Claude US 10 = Global × 1.1, Nova 2.0 Lite $0.33/$2.75)은 seed로 과거까지 교정했다. **모델을 추가하면** `pricing_sources.py`(`price_identity` 분류, 오퍼 FM id 또는 Anthropic 문서 모델명 매핑, 새 패밀리면 `FAMILY_ORDER`)와 `pricing_seed.py`(`SEED`, CP는 `CP_SEED`)를 함께 고친다 — "활성 채널 전부가 분류되고 seed 단가가 있다" 테스트가 누락을 잡고, 운영에서는 `no_baseline` 검토 대기로 드러난다. 새 패밀리는 프런트 `lib/sortModels.ts` `FAMILY_ORDER`와 백엔드 `pricing_sources.FAMILY_ORDER`가 바이트 단위로 같아야 한다(pytest 고정). 화면 `/pricing`, API `GET /api/pricing`(태스크마다 60초 캐시), `GET /api/pricing/export?format=csv|md|json&lang=ko|en`.

---

## Workload Preset (6 categories, round-robin) / 워크로드 프리셋

매 cycle마다 다음 카테고리 하나를 선택 — 같은 카테고리는 30분(5분 × 6)마다 회전. `probe_results.category` 컬럼으로 필터링.
Claude Platform on AWS 채널(anthropic:*)도 기본값에서는 매 사이클 같은 카테고리를 쓴다(v2.29.1 — v2.29.0의 10분 주기를 되돌림). `ANTHROPIC_CP_PROBE_INTERVAL_S`를 600으로 올리면 CP만 두 사이클에 한 번이 되고 채널마다 자기 직전 카테고리의 다음 것을 쓴다 — 그때는 같은 카테고리가 약 60분마다 돌아오고, 한 run 안에서 다른 모델과 카테고리가 다를 수 있다(나머지 모델의 회전은 CP 행을 제외하고 읽으므로 어느 모드든 같다).

| id | label_ko | 용도 |
|----|----------|------|
| chat-short | 짧은 대화 | TTFT-sensitive 짧은 응답 |
| reasoning | 추론 | 복잡 추론 (max_tokens 큼) |
| code-gen | 코드 생성 | 코드 출력 |
| summarize | 요약 | 긴 입력 → 짧은 출력 |
| structured | JSON 추출 | 텍스트 → JSON-only 추출 |
| translate | 번역 | 영→한 기술 번역 (뉘앙스 보존) |

정의는 `backend/auto_prober.py` `WORKLOAD_PRESETS`가 source of truth.

---

## Metrics / 측정 지표

| Metric | Unit | 설명 |
|--------|------|------|
| TTFT | ms | 요청 → 첫 토큰 |
| Total Latency | ms | 요청 → 마지막 토큰 (클라이언트 측) |
| Server Latency | ms | Bedrock 보고 내부 처리 (network overhead 제외) |
| TPS | tok/s | 첫 토큰 이후 출력 처리량 |
| Input/Output Tokens | count | 비용 산정, 효율성 지표 |
| Stop Reason | enum | end_turn / max_tokens / tool_use / stop_sequence / guardrail_intervened / content_filtered |

**카드 지표 등급 (v2.28.0, ADR-029)**: 대시보드 모델 카드의 TTFT·총 응답시간·TPS **값 텍스트**를 워크로드 카테고리별 절대 임계치로 양호(파랑)/경고(호박, ▲)/위험(장미, ◆)으로 칠한다(사용자 요청 — 선택지 "카테고리별 절대 기준"). KO 등급 이름은 "양호"다 — 채널 건강 배지가 "정상"이라 같은 단어를 쓰면 "✓ 정상" 배지 옆 ◆ 위험 값이 모순처럼 읽힌다(EN은 Healthy/Normal로 이미 구분). `frontend/src/lib/metricGrade.ts`가 단일 출처(임계치 표, `roundForDisplay` 표시 정밀도 판정, 색 클래스, 표지) — 기준을 바꿀 때는 이 표만 고친다. TPS는 낮을수록 나쁨(경고 <40, 위험 <15 tok/s, 전 카테고리 공통). 임계치는 2026-09-23 운영 48시간 p90/p99 기반(카드 단위 시뮬레이션 — 카드처럼 표시 정밀도로 판정 — 양호 89.0%, 경고 9.6%, 위험 1.4%)이라 주기적 재도출이 필요하며, 원래 느린 모델(GPT-6 Astra, Fable 5/5.1)이 자주 경고색인 것은 의도된 동작이다. 각 값에 `data-grade` 속성, 경고/위험만 sr-only 설명 연결, 카드 위 범례 + 접이식 기준표. 건강 배지(emerald/amber/rose)와 팔레트가 다르다.

---

## Authentication / 인증

- **JWT Bearer** (24h), `JWT_SECRET_KEY` 32자 이상 강제
- **Password**: passlib bcrypt (`bcrypt>=4.0,<4.1` 고정)
- **Register**: `username`은 **EmailStr** 검증 강제 (v2.1.0). approved=0 → admin SES → approved=1 → login
- **Admin email**: `whchoi98@gmail.com` (`backend/auth.py:ADMIN_EMAIL`)
  - SES region: `us-east-1`. **Sandbox 모드 시 sender/recipient 둘 다 verified identity 필요**
- **Public**: `/api/health`, `/api/auth/{login,register,approve}`, 모든 조회 GET — `/api/auto-probe/*`, `/api/results/*`, `/api/models`, `/api/cost/*`, `/api/reliability/*`, `/api/efficiency/*`, `/api/analysis/*`, `/api/parity/{catalog,latest,evidence}`, `/api/features/{catalog,latest,evidence}`, `/api/gptbench/*`, `/api/pricing`, `/api/pricing/export`, `/api/insights`·`/latest`, `GET /api/prompts`, `GET /api/probes/{run_id}`
- **Auth required** (`Depends(get_current_user)`): `/api/auth/me`, `/api/auto-probe/trigger` (202 accepted / 409 active reservation), `/api/probes/run`, `/api/compare/run`, `/api/parity/trigger`, `/api/features/trigger`, `/api/prompts` (POST/DELETE, `/optimize`), `/api/insights/regenerate`·`/stream-regenerate`, `/api/chat/*`
- **Admin only**: `/api/admin/*` (username == "admin") — `/api/admin/pricing/*` 검토 대기 단가 승인/거부 포함 (v2.30.0). admin 비밀번호는 `SEED_ADMIN_PASSWORD` env var (8자 이상)

---

## Important Constraints / 중요 제약사항

### Version strings (릴리스 시 함께 범프 — /release 스킬 참조)

버전이 표기되는 위치 전부. 하나라도 빠지면 사용자/문서에 stale 버전이 남는다 (v2.21.0 릴리스에서 FastAPI가 2.0.0으로 고착돼 있던 실사례):

| 위치 | 노출 경로 |
|------|-----------|
| `frontend/src/lib/version.ts` `APP_VERSION` | **canonical** — 모든 페이지 헤더 |
| `backend/main.py` `FastAPI(version=…)` | OpenAPI `/docs`·openapi.json |
| `frontend/package.json` `version` | 앱 manifest |
| `README.md` 버전 배지 | GitHub 첫 화면 |
| `CLAUDE.md` 상단 개요 | 이 파일 |
| `CHANGELOG.md` 최신 엔트리 + git tag `vX.Y.Z` | 릴리스 기록 |

(`cdk/package.json`은 인프라 패키지 버전이라 앱 버전과 무관 — 범프 대상 아님.)

**Claude API Features 카탈로그 규칙 변경 시 `CATALOG_VERSION` 범프** (`backend/claude_features/runner.py`): `backend/claude_features/catalog.py`의 `_NOT_APPLICABLE_BY_DOC`, `documented` 기대치, `_CONVERSE_NOT_EXPRESSIBLE`, `is_applicable` 규칙이 바뀌면 함께 범프한다 — v2.23.1에서 누락돼 run #2→#3 변경 15건을 버전 비교로 식별할 수 없었고, 그래서 `/api/features/latest` `changes[].kind`는 `latency_ms IS NULL AND error_message IS NULL`(러너 사전판정 행)로 카탈로그 변경을 식별한다. **대표 `MODELS` 변경**(모델 추가/제거 — 런 형태가 달라짐, v2.28.0 Opus 5.5 편입 시 `2026-09-23`으로 범프)도 범프 트리거다. label/desc 문구만 바뀐 릴리스(v2.24.0)는 범프 대상이 아니다.

### ECR Image Tag Policy

**`:latest` 태그는 production task definition에서 절대 사용 금지.** ECR이 같은 digest로 새 push를 layer-dedupe하면 ECS는 manifest digest만 보고 "동일 image"로 판단해 옛 container를 cache. 새 코드가 production에 silent 반영 안 되는 함정.

**규칙**: 모든 backend image는 `v<timestamp>` 같은 immutable tag + image URI에 `@sha256:<digest>` 직접 명시 (CDK 배포는 `-c backendImage/-c frontendImage`로 주입). 불변성은 CDK가 강제하지 않는다 — `bedrock-monitor-backend-v2`는 CDK 밖에서 만든 **IMMUTABLE** repo이고, CDK(`cluster-stack.ts` `createImageRepo`)가 관리하는 `bedrock-monitor-backend`(legacy)·`bedrock-monitor-frontend`는 **MUTABLE**이라 frontend는 태그 규칙을 지켜야 한다.

### ECR Repository (현재 사용 중)

| Image | Repository | 사유 |
|-------|------------|------|
| backend | `bedrock-monitor-backend-v2` (CDK 외부 생성, IMMUTABLE) | 옛 `bedrock-monitor-backend`에 ECS Fargate silent image cache bug 발생 — repository path 변경으로 우회 (ADR-018) |
| frontend | `bedrock-monitor-frontend` (CDK 관리, MUTABLE) | 변경 없음 |
| autoprober (별도 task) | backend image 공용 — `bedrock-monitor-backend-v2` |

### EventBridge Scheduler IAM

Scheduler role의 `ecs:RunTask` Resource는 **task def family `:*` wildcard** 사용 (revision 번호 박지 말 것). 박으면 새 revision으로 schedule을 update해도 권한 거부로 silent fail. EventBridge metric이 empty라 디버깅 어려움.

### `:latest` 함정 디버깅 표지
- `/api/auto-probe/status`에 `last_run_time`이 N시간 전 → autoprober task 실행 실패
- Scheduler IAM policy → `ecs:RunTask` Resource에 task def `:*` 있는지 확인
- 또는 `aws logs tail /ecs/autoprober` 5분 이내 entries 0개

### Python 3.11 + FastAPI
- FastAPI 의존성 typehint에 `X | Y`는 OK (Python 3.10+). `from __future__ import annotations`도 쓸 수 있다(routers 대부분이 사용). 다만 그 파일에서는 엔드포인트와 `Depends` 시그니처의 타입이 모듈 전역 이름이어야 한다 — 함수 안에서 정의한 모델이나 `TYPE_CHECKING` 전용 import는 문자열 주석이 해석되지 않아 FastAPI가 body 파라미터를 필수 query 파라미터로 오인한다(422).

### bcrypt 4.0.x 고정
- 5.x는 passlib과 호환 안 됨.

### Korean UI Default
- 사용자 화면 텍스트는 `frontend/src/lib/i18n.ts` KO/EN 두 언어 지원. 기본 KO. 헤더 우측 토글.

### DB 마이그레이션 패턴 (`main.py` lifespan)
- `engine.begin()` (자동 commit/rollback + connection return)
- `SET statement_timeout = '30000'` + `SET lock_timeout = '5000'` + `pg_advisory_lock(917350001)` (다중 task 동시 마이그레이션 deadlock 방지; 5초 안에 락을 못 잡으면 블록 포기, 다음 기동에 재시도)
- 모든 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- 예: `probe_results.stop_reason TEXT`
- 기동 마이그레이션이 ~130s 걸릴 수 있어 backend 헬스체크 유예는 300s (`app-services-stack.ts` `healthCheckGracePeriod`, 2026-09-06 서킷 브레이커 롤백 실사고)
- 새 테이블(`price_history`, `price_sync_runs`, v2.30.0)은 `models.py` ORM + `create_all`로 만든다 — lifespan ALTER 블록에 넣지 않는다. seed(`pricing_seed.ensure_seed`)는 마이그레이션 트랜잭션과 분리된 자체 트랜잭션에서 `SET LOCAL statement_timeout = '30000'`, `lock_timeout = '5000'`을 건 뒤 `pg_advisory_xact_lock(917350003)`, 동기화 런은 `pg_try_advisory_lock(917350004)`(기다리지 않음 — 점유 중이면 즉시 exit 1, 런 행 없음). 모든 시각은 timezone-aware datetime 바인드 파라미터로 넣는다(SQLite는 DateTime을 문자열로 비교하므로 raw 시각 리터럴 금지)

### Auto-Prober는 daemon thread 아님
- v1: backend 프로세스 안의 thread. v2: **별도 Fargate Task** (EventBridge Scheduler가 5분마다 RunTask). backend의 `auto_prober.py`는 `run_cycle()` 함수만 export, daemon 로직 없음. `auto_prober_runner.py`가 CLI entrypoint.
- **Claude Platform on AWS 주기 노브 (v2.29.0 도입, v2.29.1에서 매 사이클로 복귀)**: v2.29.0은 사용자 결정 2026-09-23("API 스로틀링 이슈, 1P만 해당")으로 CP 채널을 10분 주기로 늘렸고, v2.29.1은 사용자 결정 2026-09-26("원래대로 복귀")으로 기본값을 되돌렸다. 이제 기본 `ANTHROPIC_CP_PROBE_INTERVAL_S=300`에서는 CP도 매 사이클, 사이클 카테고리로 프로빙하고 `_plan_cycle`은 CP 이력 조회를 하지 않는다(시간당 CP 호출 108회). 월간 사용량 상한이 다시 걸리면 AutoProber task env를 600으로 올리는 것이 운영 레버다(backend 서비스에도 같은 값 — `/status` 표시용). 기본 주기(300)보다 클 때만 적용되는 규칙: `_plan_cycle`이 CP 채널을 직전 CP 자동 프로브 **run의 시작 시각**(`ProbeRun.created_at`) 기준 `ANTHROPIC_CP_PROBE_INTERVAL_S − 150`초가 지났을 때만 프로빙하고 채널마다 카테고리를 따로 회전한다 — 결과 행 timestamp로 바꾸지 말 것(CP 행은 사이클 1~2분 뒤에 찍혀 600 설정이 실제로는 15분 주기가 된다). Bedrock Claude, Nova, OpenAI는 항상 매 사이클. `/api/auto-probe/latest`는 run 단위가 아니라 모델별 최신 행이고(`latest_results.py`), `/status`의 `channel_intervals`로 프런트엔드가 카드 신선도와 추세 끊김을 채널별 주기로 판정한다.
- **월간 사용량 상한 429는 재시도하지 않는다 (v2.29.0)**: 메시지 "usage limits" / "usage threshold" / `enforced_spend_limit_reached`(`prober._is_usage_cap_error`) — 프로브당 요청 1회, 오류 행 1개, 경고 한 줄. CP 프로브 클라이언트(`_get_anthropic_probe_client`)는 `max_retries=0`이고 SDK가 하던 일시 오류 재시도(408/409/429/5xx, 연결 오류)는 prober 루프가 맡는다. Comparison Lab과 패리티 런은 SDK 기본값 클라이언트(`_get_anthropic_client`) 그대로.
- **Probe wall-clock watchdog (v2.28.2)**: 프로브 스트림은 `PROBE_WALL_CLOCK_S`(기본 90초, `backend/stream_watchdog.py`) 상한 — 만료 모델은 오류 행 `WallClockTimeout: …`, 모델별 사이클 타임아웃(max(120, 상한 + 30)초) 초과 모델은 `… (cycle timeout)` 오류 행이고 run은 **completed**로 끝난다. executor `shutdown(wait=False)` + 러너 `os._exit` — `with ThreadPoolExecutor`/`sys.exit`로 되돌리지 말 것 (2026-09-23 대시보드 동결, [`docs/runbooks/troubleshooting.md`](./docs/runbooks/troubleshooting.md)).

---

## Environment Variables / 환경 변수

| Variable | Default / 기본값 | 설명 |
|----------|------------------|------|
| `JWT_SECRET_KEY` | (필수, 32자 이상) | placeholder 거부 |
| `SEED_ADMIN_USERNAME` | `admin` | 시드 admin username |
| `SEED_ADMIN_PASSWORD` | (필수, 8자 이상) | admin 시드 비번 (변경 시 자동 rotate) |
| `PUBLIC_BASE_URL` | `https://d36s7ml54xwemr.cloudfront.net` | 승인 이메일 링크 base |
| `DATABASE_URL` / `DB_*` | (CDK 주입) | RDS 연결 |
| `ANTHROPIC_API_KEY` | (CDK 주입, secret) | CP on AWS envelope key |
| `ANTHROPIC_WORKSPACE_ID` | (CDK 주입, secret) | CP on AWS workspace |
| `ANTHROPIC_AWS_REGION` | `us-east-2` | CP on AWS endpoint region |
| `NEXT_PUBLIC_RUM_ENDPOINT` / `_API_KEY` | (선택) | RUM 수집 — **빌드 타임 주입** (frontend docker build `--build-arg`), 미설정 시 수집 비활성 (v2.16.5) |
| `RETENTION_DAYS` | `60` | 원본 probe_results 보존 일수 (초과분은 probe_results_hourly 집계 이관, 0 이하=비활성) |
| `ANTHROPIC_CP_PROBE_INTERVAL_S` | `300` (AutoProber task CDK 주입, 코드 기본값도 300 — v2.29.1) | Claude Platform on AWS 채널(anthropic:*) 수집 주기(초) — 읽을 때 5분 사이클 단위로 반올림(동률 내림, due 판정과 같은 결과 — 400은 300, 700은 600), 300(기본)과 300 미만은 매 사이클(다른 채널과 같은 카테고리), 600 = 두 사이클에 한 번 + CP 자체 카테고리 회전(v2.29.0 동작, 사용량 상한 대응 레버). backend 서비스는 미주입(코드 기본값으로 `/status` `channel_intervals` 표시) — 값을 바꿀 때는 backend에도 같은 값 주입 (v2.29.0 도입, 기본값 v2.29.1) |
| `PROBE_WALL_CLOCK_S` | `90` (선택, 미주입) | 프로브 1회(재시도 포함) wall-clock 상한 — 만료 시 그 모델만 `WallClockTimeout` 오류 행, 모델별 사이클 타임아웃은 max(120, 값 + 30)초로 따라감 (v2.28.2) |
| `MANTLE_ANTHROPIC_REGION` | `us-east-1` (CDK 주입) | Claude API Features + 패리티 런 `messages_mantle` 공용 Mantle `/anthropic` surface 리전. ap-northeast-1은 Opus 4.8만 서빙(2026-09-05 실측) → 대표 모델이 서빙되는 us-east-1로 전환(사용자 결정, v2.23.0). env 미주입 시 코드 기본값은 패리티 ap-northeast-1(`parity/runner.py`), Claude API Features us-east-1(`claude_features/catalog.py`) |
| `FEATURES_MCP_SERVER_URL` | (선택) | Claude API Features MCP connector 프로브용 공개 MCP 서버 URL (v2.23.0, 장애 시 inconclusive로 격리) |
| `OPENAI_API_KEY` | (CDK 주입, SSM `/bedrock-monitor/openai-api-key` secret) | Bedrock bearer 키(`ABSK-…`) — Mantle 인리전·Global·US CRIS·gptbench 공용. 미설정 시 OpenAI Mantle 채널 전체 skip |
| `OPENAI_US_EAST_1_BASE_URL` / `OPENAI_US_EAST_2_BASE_URL` / `OPENAI_US_WEST_2_BASE_URL` | `https://bedrock-mantle.<region>.api.aws/openai/v1` (CDK 주입) | Mantle 인리전 엔드포인트 (`prober._OPENAI_REGION_ENV`) — 미주입 리전의 채널은 조용히 skip |
| `OPENAI_GLOBAL_BASE_URL` | `https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1` (CDK 주입) | OpenAI Global CRIS(`global.openai.*`) 유사 리전 `global` 라우팅 (v2.20.0, ADR-025). 미주입 시 Global 채널 skip |
| `OPENAI_US_BASE_URL` | `https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1` (CDK 주입) | OpenAI US CRIS(`us.openai.*`) 유사 리전 `us` 라우팅 — bedrock-mantle 호스트 미지원, 기존 `OPENAI_API_KEY` bearer 재사용 (v2.25.0, ADR-027). 미주입 시 prober가 US 채널을 조용히 skip |
| `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID` | `openai.gpt-6-astra` (CDK 주입) | GPT-6 Astra Mantle 인리전 native id — Global/US 프로파일 id는 prober가 `global.`/`us.` 접두로 파생 (v2.25.0) |
| `BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID` / `BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID` | `openai.gpt-6-sol` / `openai.gpt-6-luna` (CDK 주입) | GPT-6 Sol/Luna Mantle 인리전(us-east-1) native id — Global/US 프로파일 id는 prober가 `global.`/`us.` 접두로 파생. 미주입 시 해당 모델 3채널을 조용히 skip하므로 AppServices+Scheduler 양 스택 배포 필수 (v2.27.0, ADR-028) |
| `GPT_BENCH_RUNS` / `GPT_BENCH_DEADLINE` / `GPT_BENCH_CALL_TIMEOUT` | `10` / `780` / `90` (선택, 미주입) | GPT on AWS 벤치 채널당 호출 수 / 사이클 데드라인(초, 초과 시 남은 채널 skip) / 호출당 wall-clock 상한(초) (`gptbench.py`) |
| `HIDDEN_MODEL_PATTERNS` | `(1P)` | 조회 API에서 숨길 `model_name` 부분 문자열, 쉼표 구분 (`visibility.py`). `""` = 전부 노출 (v2.19.1) |
| `AGENTCORE_MEMORY_ID` | (CDK 주입, SSM) | 챗봇 AgentCore Memory ID (`agent/memory.py`) — 미설정 시 Memory 기록 skip |
| `DB_STATEMENT_TIMEOUT_MS` | `30000` | 런타임 쿼리 `statement_timeout` (`database.py`) |
| `BEDROCK_OPTIMIZE_REGION` | `us-east-1` | `/api/prompts/optimize` Bedrock OptimizePrompt 호출 리전 (`routers/prompts.py`) |
| `BACKEND_INTERNAL_URL` | `http://localhost:8000` | frontend `next.config.mjs` `/api/*` rewrite 대상 (로컬 개발용) — 운영은 ALB가 `/api/*`를 backend로 직접 라우팅해 미주입 |

---

## Git

- Remote: `https://github.com/whchoi98/model-monitoring.git`
- Branch: `main`
- 운영 환경: ap-northeast-2 (Seoul). RDS / ECS / ALB / EventBridge 모두 Seoul.
- CloudFront distribution ID: `E3JNKTNZGS3NX2`. Invalidation `/*` 자주 호출.
