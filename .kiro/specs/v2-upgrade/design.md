# v2 업그레이드 설계 (Design)

## 1. 시스템 아키텍처

### 1.1 전체 데이터 흐름

```
                    ┌────────────────────────────────────┐
                    │  User Browser                      │
                    │  ┌──────────────────────────────┐  │
                    │  │  Next.js Dashboard           │  │
                    │  │  + FloatingChat (popup/iframe)│  │
                    │  └──────────────────────────────┘  │
                    └─────────────┬──────────────────────┘
                                  │ HTTPS 443
                                  ▼
                    ┌────────────────────────────────────┐
                    │  CloudFront Distribution           │
                    │  - default *.cloudfront.net cert   │
                    │  - WAFv2 (AWS managed common)      │
                    │  - Access logs → S3 (KMS)          │
                    │  - Lambda@Edge: VIEWER_REQUEST only │  ◀ SSE 안전
                    └─────────────┬──────────────────────┘
                                  │ HTTPS 443 (https-only)
                                  │ Origin Protocol Policy
                                  ▼
                    ┌────────────────────────────────────┐
                    │  CloudFront VPC Origin             │
                    │  - Managed ENIs in private subnets │
                    └─────────────┬──────────────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────────────┐
                    │  Internal ALB (scheme=internal)    │
                    │  - HTTPS 443 listener only          │
                    │  - Cert: ACM Private CA             │
                    │  - SG: ingress from VPC Origin SG   │
                    │  - Access logs → S3 (KMS)          │
                    └────┬───────────────────┬────────────┘
                         │ /                  │ /api/*
                         ▼                    ▼
                ┌────────────────┐  ┌──────────────────────┐
                │ ECS Service:   │  │ ECS Service:         │
                │ frontend       │  │ backend              │
                │ (Next.js :3000)│  │ (FastAPI :8000)      │
                │ Fargate        │  │ Fargate              │
                └────────────────┘  └──────────┬───────────┘
                                               │
              ┌────────────────────────────────┼────────────────────────────┐
              │                                │                            │
              ▼                                ▼                            ▼
   ┌──────────────────────┐   ┌──────────────────────────┐    ┌──────────────────────────┐
   │ RDS PostgreSQL       │   │ Bedrock Runtime          │    │ AgentCore                │
   │ - t4g.micro          │   │ - Sonnet/Haiku/Opus      │    │ - Memory (sessions)      │
   │ - Single-AZ, 20GB gp3│   │ - converse_stream API    │    │ - Runtime (Sonnet 4.6)   │
   │ - 7d 자동 백업       │   │                          │    │ - Tools: 4 functions     │
   │ - SG: backend SG only│   │                          │    │                          │
   └──────────────────────┘   └──────────────────────────┘    └──────────────────────────┘

   ┌──────────────────────────────────────────────────────────────────┐
   │ EventBridge Scheduler                                            │
   │  ├─ rate(5 minutes)  → ECS RunTask: AutoProber TaskDef           │
   │  └─ rate(30 minutes) → ECS RunTask: Insights TaskDef (Sonnet 4.6)│
   └──────────────────────────────────────────────────────────────────┘
```

### 1.2 데이터 흐름 요약 (Critical Path)

```
Browser ──HTTPS──▶ CloudFront ──https-only──▶ VPC Origin ──▶ Internal ALB
   ──▶ ECS frontend (정적/SSR)
   ──▶ ECS backend (/api/*) ──▶ RDS / Bedrock / AgentCore
```

---

## 2. CDK 스택 분해

| 스택 | 책임 | 의존 |
|------|------|------|
| `NetworkStack` | VPC(재사용/신규), VPC Endpoints (ECR, S3, Logs, SSM, Bedrock, Bedrock-AgentCore) | - |
| `DataStack` | RDS PostgreSQL, SSM SecureString | Network |
| `ClusterStack` | ECS Cluster, ECR repos, KMS keys (logs) | Network |
| `AgentCoreStack` | AgentCore Memory, Agent Runtime (Sonnet 4.6 binding), IAM roles | Network |
| `AppServicesStack` | ECS Service × 2 (frontend, backend), Task Defs, IAM | Cluster, Data, AgentCore |
| `EdgeStack` | ACM Private CA cert, Internal ALB + HTTPS listener, CloudFront + VPC Origin, WAFv2, S3 logs bucket, Lambda@Edge (viewer_request only) | AppServices |
| `SchedulerStack` | EventBridge Schedules, AutoProber TaskDef, Insights TaskDef | Cluster, AppServices, AgentCore |
| `ObservabilityStack` | Log Groups, Alarms, Dashboard | 모든 스택 |

배포 순서: Network → Data → Cluster → AgentCore → AppServices → Edge → Scheduler → Observability.

---

## 3. 컴포넌트 상세

### 3.1 컨테이너 이미지

**backend/Dockerfile** (multi-stage)
```
Stage build: python:3.11-slim
  - pip install -r requirements.txt -t /deps
Stage runtime: python:3.11-slim
  - non-root user (uid 1000)
  - COPY --from=build /deps /usr/local/lib/python3.11/site-packages
  - COPY backend/
  - CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**frontend/Dockerfile** (multi-stage)
```
Stage deps: node:20-alpine
  - npm ci
Stage build: node:20-alpine
  - npm run build  (output: "standalone")
Stage runtime: node:20-alpine
  - non-root user
  - COPY --from=build .next/standalone
  - COPY --from=build .next/static
  - CMD ["node", "server.js"]
```

**autoprober·insights**: backend 이미지를 재사용하고 entrypoint/command만 override.
- AutoProber: `python -m backend.auto_prober_runner --once`
- Insights:   `python -m backend.insights_runner --window 6h`

### 3.2 ECS Service Definition

| 항목 | frontend | backend |
|------|----------|---------|
| CPU/Mem | 0.5 vCPU / 1 GB | 0.5 vCPU / 1 GB |
| desiredCount | 1 (Auto Scaling 1~3) | 1 (Auto Scaling 1~3) |
| Health Check | `GET /` 200 | `GET /api/health` 200 |
| Port | 3000 | 8000 |
| Logs | `/ecs/frontend` | `/ecs/backend` |
| Env | `NEXT_PUBLIC_API_BASE_URL=/api` | `DATABASE_URL`(SSM), `JWT_SECRET_KEY`(SSM), `AGENTCORE_AGENT_ID`(SSM), `AGENTCORE_MEMORY_ID`(SSM) |
| IAM Role | (없음, 정적 SSR만) | bedrock:InvokeModel*, agentcore:Invoke*, ssm:GetParameter, ses:SendEmail |

### 3.3 Security Group 매트릭스

| SG | Inbound | Outbound |
|----|---------|----------|
| `sg-cf-vpc-origin` | (CloudFront 관리) | ALB SG → 443 |
| `sg-alb` | CF VPC Origin SG → 443 | Frontend SG → 3000, Backend SG → 8000 |
| `sg-frontend` | ALB SG → 3000 | 443 (ECR, CloudWatch) |
| `sg-backend` | ALB SG → 8000 | 443 (Bedrock, AgentCore, SES), RDS SG → 5432 |
| `sg-autoprober` | (none) | 443 (Bedrock), RDS SG → 5432 |
| `sg-insights` | (none) | 443 (Bedrock), RDS SG → 5432 |
| `sg-rds` | Backend SG, AutoProber SG, Insights SG → 5432 | (none) |

### 3.4 IAM Role 분리

- `TaskExecutionRole` (공용) — `AmazonECSTaskExecutionRolePolicy`
- `FrontendTaskRole` — 권한 없음
- `BackendTaskRole` — `bedrock:InvokeModel*` (특정 모델), `bedrock-agentcore:InvokeAgentRuntime`, `bedrock-agentcore:CreateMemoryEvent`, `bedrock-agentcore:RetrieveMemoryRecords`, `ssm:GetParameter`, `ses:SendEmail`
- `AutoProberTaskRole` — `bedrock:InvokeModel*` (특정 모델), `ssm:GetParameter`
- `InsightsTaskRole` — `bedrock:InvokeModel*` (Sonnet 4.6만), `ssm:GetParameter`
- `AgentCoreExecutionRole` — `bedrock:InvokeModel` (Sonnet 4.6), tools 함수 invoke 권한 (backend `/api/agent/tool/*` 호출 시 IAM SigV4)

---

## 4. AgentCore 통합 상세

### 4.1 구성요소

- **AgentCore Memory** — `MemoryStrategy=SEMANTIC`. actor = `username`, session = `chat-{sessionId}`.
- **AgentCore Runtime** — Agent 1개. 모델 `claude-sonnet-4-6` (US). System prompt: "당신은 AWS Bedrock LLM 모니터링 도구의 어시스턴트입니다. 사용자의 한국어 질문에 답변하기 위해 도구를 호출하세요."
- **Tools** (Gateway target):
  - `get_latest_results` → backend `/api/agent/tool/latest`
  - `get_trend` → backend `/api/agent/tool/trend`
  - `compare_models` → backend `/api/agent/tool/compare`
  - `optimize_prompt` → backend `/api/agent/tool/optimize`

### 4.2 챗봇 요청 흐름

```
Browser ─▶ /api/chat/stream (SSE)
            ├─ backend: AgentCore Memory에 user message 기록
            ├─ backend: AgentCore Runtime invoke (sync)
            │            └─ Agent: tool 선택 → backend tool endpoint 호출 → 최종 답변 생성
            ├─ backend: 최종 텍스트 수신 (스트리밍 미지원)
            ├─ backend: simulateStreaming() 50자/15ms 청크로 SSE emit
            ├─ backend: try/finally로 final 이벤트 emit
            └─ backend: AgentCore Memory에 assistant message 기록
```

### 4.3 인사이트 잡 흐름 (주기 30분)

```
EventBridge ─▶ ECS RunTask: insights_runner
                ├─ 최근 6시간 ProbeResult 로드
                ├─ 간단한 stats 계산 (avg, p95, error_rate)
                ├─ Sonnet 4.6 converse_stream() 호출 (요약 프롬프트)
                │   └─ chunk를 직접 받아 누적 (이건 batch 잡이라 스트리밍 불필요)
                └─ insights 테이블 INSERT (window, summary_md, model_breakdown JSON)
```

---

## 5. 프론트엔드 챗봇 설계

### 5.1 컴포넌트 트리

```
app/page.tsx
└─ <FloatingChat />                        # 우하단 고정 버튼
   ├─ useUaPopupStrategy()                 # Chrome/Firefox 판별
   ├─ if popup → window.open(...) + <ChatPopup />
   └─ if iframe → <ChatModal><iframe src="/chat" /></ChatModal>

app/chat/page.tsx                          # 팝업/iframe 양쪽 진입점
└─ <ChatPanel />
   ├─ <MessageList />
   │  └─ <MessageMarkdown />               # react-markdown@10 + remark-gfm
   └─ <ChatInput />
       └─ useChatStream() → /api/chat/stream (SSE)
```

### 5.2 브라우저 분기 로직

```ts
// hooks/useUaPopupStrategy.ts
const isFirefox = /Firefox/.test(navigator.userAgent);
const opened = window.open('/chat', '_blank', 'popup=yes,width=420,height=640');
if (!opened || opened.closed || (!isFirefox && opened.outerWidth > 800)) {
  // 차단되었거나 Chrome이 새 탭으로 열린 경우 → iframe modal fallback
  return { mode: 'iframe' };
}
return { mode: 'popup' };
```

### 5.3 SSE 수신 패턴

```ts
const res = await fetch('/api/chat/stream', { method: 'POST', body: ... });
const reader = res.body!.getReader();
const decoder = new TextDecoder();
let buf = '';
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  const events = parseSseEvents(buf);
  // delta → append, final → close, error → display
}
```

---

## 6. 백엔드 변경

```
backend/
├── main.py                       # auto_prober.start() 제거
├── auto_prober.py                # 데몬 스레드 제거, _run_cycle()만 유지
├── auto_prober_runner.py         # NEW: CLI entry (Fargate one-shot)
├── insights_runner.py            # NEW: 인사이트 도출 CLI
├── routers/
│   ├── chat.py                   # NEW: /api/chat/stream
│   ├── insights.py               # NEW: /api/insights
│   ├── agent_tools.py            # NEW: /api/agent/tool/* (AgentCore tool target)
│   └── ... (기존)
├── agent/
│   ├── __init__.py
│   ├── client.py                 # AgentCore Runtime invoke client
│   ├── memory.py                 # AgentCore Memory wrapper
│   ├── streaming.py              # simulateStreaming(), SSE 헬퍼 (final 이벤트 try/finally)
│   └── tools.py                  # tool 함수 (DB 질의 → JSON)
└── models.py                     # Insight 테이블 추가
```

신규 테이블 `insights`:
```sql
CREATE TABLE insights (
  id SERIAL PRIMARY KEY,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  summary_md TEXT NOT NULL,
  model_breakdown JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 7. 디렉토리 구조 (v2 적용 후)

```
model-monitoring/
├── backend/
│   ├── Dockerfile                # 신규
│   ├── auto_prober_runner.py     # 신규
│   ├── insights_runner.py        # 신규
│   ├── agent/                    # 신규 하위 디렉토리
│   └── routers/                  # chat.py, insights.py, agent_tools.py 추가
├── frontend/
│   ├── Dockerfile                # 신규
│   ├── next.config.mjs           # output: "standalone" 추가
│   └── src/
│       ├── app/chat/page.tsx     # 신규 (팝업/iframe 진입점)
│       └── components/chat/      # 신규
├── cdk/                          # 신규 CDK v2 TypeScript
│   ├── bin/app.ts
│   ├── lib/stacks/
│   │   ├── network-stack.ts
│   │   ├── data-stack.ts
│   │   ├── cluster-stack.ts
│   │   ├── agentcore-stack.ts
│   │   ├── app-services-stack.ts
│   │   ├── edge-stack.ts
│   │   ├── scheduler-stack.ts
│   │   └── observability-stack.ts
│   ├── lib/constructs/
│   │   ├── fargate-service.ts
│   │   └── ec2-fallback.ts
│   ├── test/
│   ├── cdk.json
│   ├── package.json
│   ├── tsconfig.json
│   └── jest.config.js
├── docs/
│   ├── architecture.md           # 갱신
│   ├── decisions/                # 신규 ADR 다수
│   └── runbooks/
├── .kiro/specs/v2-upgrade/
│   ├── requirements.md
│   ├── design.md                 # 본 문서
│   └── tasks.md
├── Makefile                      # 신규
└── CLAUDE.md                     # 갱신
```

---

## 8. 핵심 설계 결정 (ADR 후보)

| ADR | 결정 | 사유 |
|-----|------|------|
| ADR-001 | **CloudFront VPC Origin** 채택 | ALB internal scheme 유지 → 외부 노출 zero. 2024-11 GA. v1 prefix-list보다 격리 강함. |
| ADR-002 | **RDS t4g.micro Single-AZ** | 매니지드 운영 부담 ↓, 비용 ~$13/mo. 모니터링 시계열이라 단일 AZ 허용. |
| ADR-003 | **Auto-prober 분리** (EventBridge → Fargate Task) | backend 스케일링 시 중복 방지. |
| ADR-004 | **ALB→ECS는 HTTP** | intra-VPC, awsvpc SG로 격리. HTTPS는 ALB listener까지만. |
| ADR-005 | **ACM Private CA**의 비용 ($400/월) | 도메인 미보유 + 보안 요구. 대안(self-signed)은 CloudFront origin SSL 검증 우회 필요로 보안 약화. |
| ADR-006 | **AgentCore Runtime 관리형** | 스케일·로깅 내장. Backend는 invoke만. |
| ADR-007 | **SSE 패턴**: VIEWER_REQUEST only + simulateStreaming | ORIGIN_RESPONSE Lambda@Edge가 SSE 깨므로 회피. AgentCore 스트리밍 미지원 보완. |
| ADR-008 | **CDK TypeScript** | CDK 네이티브, VPC Origin·Service Connect 등 신기능 L2 우선 지원. 프론트엔드 TS 툴체인 재사용. |
| ADR-009 | **챗봇 듀얼 모드 (iframe + popup)** | Chrome Site Engagement Score로 popup이 새 탭이 되는 케이스 회피. Firefox는 popup 보장. UA 분기로 결정. |

---

## 9. `make verify` 동작

```makefile
verify:
	cd cdk && npm ci
	cd cdk && npm run lint
	cd cdk && npm run typecheck
	cd cdk && npx cdk synth --quiet --all
	cd cdk && npm run nag
	cd backend && python -m ruff check .
	cd frontend && npm run lint
	cd frontend && npx tsc --noEmit
```

각 Phase 완료 전 `make verify`가 PASS여야 커밋.

---

## 10. 알려진 위험 (Known Risks)

1. **VPC Origin + Private CA cert 검증**: CloudFront가 Private CA 체인을 origin SSL로 신뢰하는지 실제 배포 단계에서 확인 필요. 실패 시 대안은 ACM Public cert(도메인 필요) 또는 origin SSL 검증 우회.
2. **Lambda@Edge cold start**: VIEWER_REQUEST 단계에서 인증 검증 시 추가 지연(50~100ms). 챗봇 첫 응답에 영향 가능.
3. **AgentCore Memory 비용**: 세션 수에 비례. 대화 보존 정책 (예: 30일 후 만료) 필요.
4. **RDS Single-AZ 가용성**: ECS는 멀티 AZ인데 RDS가 단일 AZ면 RDS 장애 시 전면 다운. Phase 후속에서 Multi-AZ 전환 고려.
