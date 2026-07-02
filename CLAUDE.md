# CLAUDE.md — Project Context for Claude Code

## Project Overview / 프로젝트 개요

**Amazon Bedrock LLM Monitor** (v2.2.0) — A real-time dashboard for response speed, throughput, reliability, cost, and output-quality monitoring of AWS Bedrock + Anthropic CP on AWS LLM channels.

**Amazon Bedrock LLM 모니터** — Bedrock + Anthropic CP on AWS 채널의 응답 속도·처리량·신뢰성·비용·출력 품질을 실시간으로 모니터링하는 대시보드.

### Tech Stack

- **Backend**: FastAPI + SQLAlchemy + RDS PostgreSQL 16 (t4g.micro, Single-AZ) + AgentCore Memory
- **Frontend**: Next.js 14 standalone + React 18 + Tailwind + Recharts + react-markdown + FloatingChat
- **Infra**: CDK v2 TypeScript / 8 stacks (Network, Data, Cluster, AgentCore, AppServices, Edge, Scheduler, Observability)
- **Edge**: CloudFront VPC Origin → Internal ALB (HTTPS-only) → ECS Fargate × 2 (backend, frontend)
- **Scheduling**: EventBridge Scheduler → AutoProber + Insights Fargate Tasks (모두 `rate(5 minutes)`)
- **AI**: Claude Sonnet 4.6 챗봇 (4 tools, dynamic followups), Haiku 4.5 인사이트 잡

자세한 v2 설계는 [`docs/architecture.md`](./docs/architecture.md) / [`docs/decisions/ADR-*.md`](./docs/decisions/) / [`.kiro/specs/v2-upgrade/`](./.kiro/specs/v2-upgrade/).

---

## Architecture / 아키텍처 (v2)

```
CloudFront (d36s7ml54xwemr.cloudfront.net)
  ↓  VPC Origin (HTTPS)
Internal ALB
  ├── /api/*  → backend Fargate Task (FastAPI, port 8000)
  └── /*      → frontend Fargate Task (Next.js standalone, port 3000)
                ├── /             — Dashboard (status + 28 model cards + trend)
                ├── /prompts      — Prompt CRUD + Bedrock OptimizePrompt (auth)
                ├── /cost         — 30-day projection + per-model + channel compare
                ├── /reliability  — Family/channel success rate + error buckets
                ├── /efficiency   — 0-100 Token Efficiency Score (weighted)
                └── /analysis     — Stop reason 분포 + Output length 분포

EventBridge Scheduler (rate 5 min)
  ├── AutoProber Fargate Task  → 1 cycle = 28 models × 1 workload preset (round-robin 6 categories)
  └── Insights Fargate Task    → Haiku 4.5 summary, save Insight row

Backend ↔ Bedrock (Seoul region inference profiles us.*, global.*) + Anthropic CP on AWS + OpenAI (Bedrock Mantle + 1P direct api.openai.com)
                                  (aws-external-anthropic.us-east-2.api.aws, workspace-id header)
```

`/api/auto-probe/status`는 in-process state가 아닌 **DB의 최근 `ProbeRun(is_auto=1)` row를 source of truth**로 사용 (Fargate task 분리 이후 일관성 확보).

---

## Directory Structure / 디렉토리 구조

```
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI entrypoint + lifespan (DB migration with pg_advisory_lock + statement_timeout)
│   ├── auto_prober.py       # run_cycle() — EventBridge가 호출하는 1회성 함수 (NOT daemon)
│   ├── auto_prober_runner.py # CLI entry: `python -m auto_prober_runner --once`
│   ├── prober.py            # Probe logic (Bedrock + Anthropic CP + OpenAI Mantle/1P), AVAILABLE_MODELS (28개), retry, stop_reason capture
│   ├── pricing.py           # 모델별 token 단가 + estimate_cost_usd
│   ├── auth.py              # JWT + bcrypt + ADMIN_EMAIL=whchoi98@gmail.com
│   ├── models.py            # ProbeResult.stop_reason, .category 컬럼 포함
│   ├── schemas.py           # Pydantic; ProbeResultResponse.stop_reason Optional
│   ├── database.py          # pool_size=5, max_overflow=5, pool_recycle=300, pool_timeout=10
│   ├── requirements.txt     # email-validator 포함 (EmailStr)
│   └── routers/
│       ├── auth.py          # /api/auth/* — login(공개), register(EmailStr 강제), approve(이메일 토큰), me(인증)
│       ├── admin.py         # /api/admin/* — reset-monitoring-data, users CRUD (admin only)
│       ├── auto_probe.py    # /api/auto-probe/* — status(DB-sourced), latest, trend, categories, trigger
│       ├── probes.py        # /api/probes/run — SSE streaming probe (auth)
│       ├── results.py       # /api/results/* — stored results query + stats
│       ├── models.py        # /api/models — AVAILABLE_MODELS list
│       ├── prompts.py       # /api/prompts/* — prompt set CRUD + Bedrock OptimizePrompt (auth)
│       ├── chat.py          # /api/chat/stream — Sonnet 4.6 + 4 tools + dynamic followups
│       ├── insights.py      # /api/insights/* — list/latest/stream-regenerate
│       ├── cost.py          # /api/cost/* — summary, channel-compare, trend
│       ├── reliability.py   # /api/reliability/multi-channel — family/channel grouped
│       ├── efficiency.py    # /api/efficiency/score — 0-100 weighted score per category
│       └── analysis.py      # /api/analysis/* — stop-reasons, output-length (v2.1.0 신규)
├── frontend/
│   ├── src/
│   │   ├── app/             # App Router pages (force-dynamic)
│   │   │   ├── page.tsx           # Dashboard (status + 28 cards + trend + workload filter)
│   │   │   ├── prompts/page.tsx   # login-gate + PromptsPanel
│   │   │   ├── cost/page.tsx
│   │   │   ├── reliability/page.tsx
│   │   │   ├── efficiency/page.tsx
│   │   │   └── analysis/page.tsx  # v2.1.0 신규
│   │   ├── components/
│   │   │   ├── AutoDashboard.tsx        # workload category filter + multi-select model
│   │   │   ├── ModelStatusGrid.tsx      # family-grouped 28 cards (Bedrock prefix)
│   │   │   ├── TrendChart.tsx           # MODEL_COLORS 28개 (15 Bedrock + 6 Anthropic CP + 7 OpenAI)
│   │   │   ├── CostDashboardPanel.tsx
│   │   │   ├── ReliabilityPanel.tsx
│   │   │   ├── EfficiencyPanel.tsx
│   │   │   ├── AnalysisPanel.tsx        # v2.1.0 신규
│   │   │   ├── InsightsPanel.tsx        # SSE stream-regenerate
│   │   │   ├── PromptsPanel.tsx         # OptimizePrompt
│   │   │   └── chat/                    # FloatingChat + ChatModal/Panel/Input
│   │   ├── hooks/                       # useAutoRefresh, useProbeStream, useChatStream
│   │   └── lib/
│   │       ├── api.ts                   # 모든 fetch 함수 (auth token mgmt)
│   │       ├── i18n.ts + i18n-context.tsx  # KO/EN
│   │       ├── sortModels.ts            # FAMILY_ORDER 10 entries, groupByFamily
│   │       ├── pricing.ts               # backend/pricing.py mirror
│   │       └── version.ts               # APP_VERSION (single source of truth)
│   └── next.config.mjs / middleware.ts
├── cdk/                                  # 8 stacks (TypeScript)
└── docs/
    ├── architecture.md
    ├── decisions/ADR-001~019.md
    └── runbooks/deploy.md, rollback.md, ...
```

---

## Key Commands / 주요 명령어

```bash
# Local dev
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev

# Container build/push (production) — IMMUTABLE TAG REQUIRED
REGION=ap-northeast-2; ACCT=061525506239
TAG="v$(date +%s)"   # NEVER use :latest in production task def
docker build --no-cache --pull --platform linux/arm64 -t bedrock-monitor-backend:$TAG backend/
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCT.dkr.ecr.$REGION.amazonaws.com
docker tag bedrock-monitor-backend:$TAG $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend:$TAG
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend:$TAG

# Register new task def with explicit tag + update service
# (see docs/runbooks/deploy.md for full procedure including autoprober schedule)

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

## Monitored Models (28 total) / 모니터링 대상 모델 (총 28개)

| Family | Global (ap-northeast-2 cross-region) | US (us-east-1 cross-region) | Anthropic CP on AWS |
|--------|--------------------------------------|------------------------------|---------------------|
| Claude Fable 5 | ✅ | ✅ | ✅ |
| Claude Opus 4.8 | ✅ | ✅ | ✅ |
| Claude Opus 4.7 | ✅ | ✅ | ✅ |
| Claude Opus 4.6 | ✅ | ✅ | — |
| Claude Sonnet 5 | ✅ | ✅ | ✅ |
| Claude Sonnet 4.6 | ✅ | ✅ | ✅ |
| Claude Haiku 4.5 | ✅ | ✅ | ✅ |
| Amazon Nova 2.0 Lite | — | ✅ | — |

**OpenAI (Bedrock Mantle, in-region)** — 신규 v2.4.0:

| Family | us-east-1 | us-east-2 | us-west-2 | 1P direct |
|--------|-----------|-----------|-----------|-----------|
| GPT 5.5 | ✅ | ✅ | — | ✅ (v2.6.0) |
| GPT 5.4 | ✅ | ✅ | ✅ | ✅ (v2.6.0) |

- **Mantle (Path 4)** model_id 키: `openai:<region>:openai.gpt-5.x`. 라벨: `OpenAI GPT 5.x (<region>)`. OpenAI-compatible `/openai/v1` + Bedrock bearer 토큰(`OPENAI_API_KEY`, `ABSK-…`). 자세히는 ADR-019.
- **1P direct (Path 5, v2.6.0)** model_id 키: `openai:1p:gpt-5.x`. 라벨: `OpenAI GPT 5.x (1P)`. `https://api.openai.com/v1` 직접 호출 + **OpenAI platform 키**(`OPENAI_1P_API_KEY`, `sk-proj-…` — Mantle bearer와 호환 불가). native id(`gpt-5.x`, 접두사 없음). 리전 개념 없음(글로벌 라우팅). env: `OPENAI_1P_API_KEY`(SSM `/bedrock-monitor/openai-1p-api-key`), `OPENAI_1P_GPT_54/55_MODEL_ID`, `OPENAI_1P_BASE_URL`(선택). 자세히는 ADR-020.

**제외 모델 (2026-05-20부터)**: Opus 4.5, Sonnet 4.5 — 사용자 요청으로 모니터링 대상에서 제외. Frontend `AutoDashboard.tsx`에 hard-filter도 적용해서 backend silent bug 대비.

**라벨 정책**: DB의 `model_name`은 항상 `"Bedrock <family> (<channel>)"` 또는 `"Anthropic <family> (<channel>)"` prefix. OpenAI 라벨은 `"OpenAI <family> (<region>)"`(Mantle) 또는 `"OpenAI <family> (1P)"`(1P direct) prefix. Frontend `MODEL_COLORS`/`FAMILY_ORDER`는 이 prefix를 expected. 정렬 순서: **Anthropic → Bedrock Global → Bedrock US → OpenAI** (`channelRank` 함수).

---

## Workload Preset (6 categories, round-robin) / 워크로드 프리셋

매 cycle마다 다음 카테고리 하나를 선택 — 같은 카테고리는 30분(5분 × 6)마다 회전. `probe_results.category` 컬럼으로 필터링.

| id | label_ko | 용도 |
|----|----------|------|
| chat-short | 짧은 대화 | TTFT-sensitive 짧은 응답 |
| reasoning | 추론 | 복잡 추론 (max_tokens 큼) |
| code-gen | 코드 생성 | 코드 출력 |
| summarize | 요약 | 긴 입력 → 짧은 출력 |
| structured-json | 구조화 JSON | JSON schema 강제 |
| creative-writing | 창작 | 긴 출력 |

---

## Metrics / 측정 지표

| Metric | Unit | 설명 |
|--------|------|------|
| TTFT | ms | 요청 → 첫 토큰 |
| Total Latency | ms | 요청 → 마지막 토큰 (클라이언트 측) |
| Server Latency | ms | Bedrock 보고 내부 처리 (network overhead 제외) |
| TPS | tok/s | 첫 토큰 이후 출력 처리량 |
| Input/Output Tokens | count | 비용 산정, 효율성 지표 |
| Stop Reason | enum | end_turn / max_tokens / tool_use / stop_sequence / guardrail_intervened / content_filtered (v2.1.0 신규) |

---

## Authentication / 인증

- **JWT Bearer** (24h), `JWT_SECRET_KEY` 32자 이상 강제
- **Password**: passlib bcrypt (`bcrypt>=4.0,<4.1` 고정)
- **Register**: `username`은 **EmailStr** 검증 강제 (v2.1.0). approved=0 → admin SES → approved=1 → login
- **Admin email**: `whchoi98@gmail.com` (`backend/auth.py:ADMIN_EMAIL`)
  - SES region: `us-east-1`. **Sandbox 모드 시 sender/recipient 둘 다 verified identity 필요**
- **Public**: `/api/auto-probe/*`, `/api/results/*`, `/api/models`
- **Auth required**: `/api/probes/run`, `/api/prompts` (POST/DELETE), `/api/insights/stream-regenerate`, `/api/chat/*`
- **Admin only**: `/api/admin/*` (username == "admin"). admin 비밀번호는 `SEED_ADMIN_PASSWORD` env var (8자 이상)

---

## Important Constraints / 중요 제약사항

### ECR Image Tag Policy (v2.1.0 강화)

**`:latest` 태그는 production task definition에서 절대 사용 금지.** ECR이 같은 digest로 새 push를 layer-dedupe하면 ECS는 manifest digest만 보고 "동일 image"로 판단해 옛 container를 cache. 새 코드가 production에 silent 반영 안 되는 함정.

**규칙**: 모든 backend image는 `v<timestamp>` 같은 immutable tag + image URI에 `@sha256:<digest>` 직접 명시. CDK 코드도 동일하게.

### ECR Repository (현재 사용 중)

| Image | Repository | 사유 |
|-------|------------|------|
| backend | `bedrock-monitor-backend-v2` | **신규** (2026-05-20). 옛 `bedrock-monitor-backend`에 ECS Fargate silent image cache bug 발생 — repository path 변경으로 우회 (ADR-018) |
| frontend | `bedrock-monitor-frontend` | 변경 없음 |
| autoprober (별도 task) | backend image 공용 — `bedrock-monitor-backend-v2` |

### EventBridge Scheduler IAM

Scheduler role의 `ecs:RunTask` Resource는 **task def family `:*` wildcard** 사용 (revision 번호 박지 말 것). 박으면 새 revision으로 schedule을 update해도 권한 거부로 silent fail. EventBridge metric이 empty라 디버깅 어려움.

### `:latest` 함정 디버깅 표지
- `/api/auto-probe/status`에 `last_run_time`이 N시간 전 → autoprober task 실행 실패
- Scheduler IAM policy → `ecs:RunTask` Resource에 task def `:*` 있는지 확인
- 또는 `aws logs tail /ecs/autoprober` 5분 이내 entries 0개

### Python 3.11 + FastAPI
- FastAPI 의존성 typehint에 `X | Y`는 OK (Python 3.10+). 그러나 `from __future__ import annotations`는 FastAPI의 runtime type resolution을 깨뜨림 — 사용 금지.

### bcrypt 4.0.x 고정
- 5.x는 passlib과 호환 안 됨.

### Korean UI Default
- 사용자 화면 텍스트는 `frontend/src/lib/i18n.ts` KO/EN 두 언어 지원. 기본 KO. 헤더 우측 토글.

### DB 마이그레이션 패턴 (`main.py` lifespan)
- `engine.begin()` (자동 commit/rollback + connection return)
- `SET statement_timeout = '30000'` + `pg_advisory_lock(917350001)` (다중 task 동시 마이그레이션 deadlock 방지)
- 모든 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- 신규 v2.1.0: `probe_results.stop_reason TEXT`

### Auto-Prober는 daemon thread 아님
- v1: backend 프로세스 안의 thread. v2: **별도 Fargate Task** (EventBridge Scheduler가 5분마다 RunTask). backend의 `auto_prober.py`는 `run_cycle()` 함수만 export, daemon 로직 없음. `auto_prober_runner.py`가 CLI entrypoint.

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

---

## Git

- Remote: `https://github.com/whchoi98/model-monitoring.git`
- Branch: `main`
- 운영 환경: ap-northeast-2 (Seoul). RDS / ECS / ALB / EventBridge 모두 Seoul.
- CloudFront distribution ID: `E3JNKTNZGS3NX2`. Invalidation `/*` 자주 호출.
