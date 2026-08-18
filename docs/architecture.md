# Bedrock LLM Monitor v2 — Architecture

<p align="center">
  <kbd><a href="#한국어">🇰🇷 한국어</a></kbd>
  &nbsp;|&nbsp;
  <kbd><a href="#english">🇺🇸 English</a></kbd>
</p>

---

## 한국어

### 시스템 개요

Bedrock LLM Monitor v2는 AWS Bedrock·Anthropic CP on AWS·OpenAI(Mantle/1P) 채널의 LLM 모델 성능(활성 40개 카탈로그)을 5분 주기로 자동 측정하고, 12시간 주기 모델×API surface×피처 패리티 런(v2.11.0, v2.12.0부터 12h)을 수행하며, 챗봇 인터페이스로 자연어 질의를 제공하는 풀스택 모니터링 도구입니다. CloudFront VPC Origin → 내부 ALB → ECS Fargate(frontend/backend) → RDS PostgreSQL 구조이며 모든 외부 인입은 HTTPS만 허용합니다.

### 데이터 흐름 (Critical Path)

```
Browser ──HTTPS──▶ CloudFront(WAF, default cert) ──VPC Origin, https-only──▶ Internal ALB(HTTPS:443) ──▶
   ├─ "/"      → ECS Fargate "frontend" (Next.js standalone)
   └─ "/api/*" → ECS Fargate "backend"  (FastAPI)
                    │
                    ├─ RDS PostgreSQL t4g.micro :5432
                    ├─ Bedrock Runtime (Claude Sonnet 4.6, etc.)
                    └─ AgentCore Memory (대화 컨텍스트)

EventBridge Scheduler
   ├─ rate(5 minutes)  → ECS RunTask "auto-prober" → 40 모델 프로빙 → RDS
   ├─ rate(5 minutes)  → ECS RunTask "insights"    → 최근 6h 요약 → RDS
   └─ rate(12 hours)     → ECS RunTask "parityrun"  → 모델×surface×피처 실행-증거 스윕 → RDS
```

### 컴포넌트 (Layer별)

#### 진입 / Edge
| 리소스 | 역할 |
|--------|------|
| CloudFront Distribution | 단일 진입점, `*.cloudfront.net` 기본 cert, TLS 1.2_2021 |
| WAFv2 (CLOUDFRONT scope) | Common rules + KnownBadInputs |
| VPC Origin | CloudFront ENI in private subnets → ALB |
| S3 (CF logs) | CloudFront access logs (KMS, 90일) |

#### 컴퓨트 / Application
| 리소스 | 역할 |
|--------|------|
| Internal ALB | HTTPS:443만, ACM Private CA cert, `/api/*` → backend / 기본 → frontend |
| S3 (ALB logs) | ALB access logs (90일) |
| ECS Cluster `bedrock-monitor` | Container Insights ON |
| ECR `bedrock-monitor-backend-v2` / `-frontend` | IMMUTABLE tag, scan-on-push, 10개 유지 (ADR-018) |
| Backend Fargate Service | FastAPI :8000, 0.5 vCPU / 1 GB, AS 1~3 |
| Frontend Fargate Service | Next.js standalone :3000, AS 1~3 |

#### 데이터 / Storage
| 리소스 | 역할 |
|--------|------|
| RDS PostgreSQL 16.3 (t4g.micro) | 20GB gp3, Single-AZ, 7d backup, encrypted |
| Secrets Manager `bedrock-monitor/db` | RDS credentials 자동 생성 |
| SSM `/bedrock-monitor/jwt-secret-key` | JWT signing key |
| SSM `/bedrock-monitor/agentcore-memory-id` | AgentCore Memory ID |

#### 에이전트 / AI
| 리소스 | 역할 |
|--------|------|
| AgentCore Memory `BedrockMonitorChatMemory` | 사용자 대화 30일 보존 |
| AgentCore IAM Managed Policy | backend Task Role에 attach |
| Bedrock Runtime | 모니터링 카탈로그 활성 40개: Claude Fable 5 / Opus 5 / Opus 4.6~4.8 / Sonnet 4.6·5 / Haiku 4.5 (Global·US 프로파일), Nova 2.0 Lite + Anthropic CP on AWS 7채널 + OpenAI GPT 5.4/5.5/5.6 Sol·Terra·Luna (Bedrock Mantle 13 + GPT-5.6 Global CRIS 3 = 16, v2.20.0; 1P direct 5는 v2.19.1부터 휴면/비노출) |

#### 주기 잡 / Scheduling
| 리소스 | 역할 |
|--------|------|
| EventBridge Scheduler `AutoProberSchedule` | rate(5 min) → AutoProber TaskDef |
| EventBridge Scheduler `InsightsSchedule` | rate(5 min) → Insights TaskDef |
| EventBridge Scheduler `ParityRunSchedule` | rate(12 hours) → ParityRun TaskDef (v2.12.0에서 일 1회→12h) |
| AutoProber TaskDef | `python -m auto_prober_runner --once` |
| Insights TaskDef | `python -m insights_runner --window 6h` |
| ParityRun TaskDef | `python -m parity_runner --once` — 실행-증거 패리티 스윕 |

#### 네트워크 / Network
| 리소스 | 역할 |
|--------|------|
| VPC 10.20.0.0/16 (또는 기존 VPC) | 2 AZ, Public + App + Data 서브넷 |
| NAT GW × 1 | App 서브넷의 외부 egress (PrivateLink 미커버 영역) |
| Interface VPC Endpoints × 9 | ECR(api+dkr), Logs, SSM(+messages), Secrets, KMS, Bedrock Runtime, AgentCore |
| Gateway VPC Endpoint × 1 | S3 |

#### 관측 / Observability
| 리소스 | 역할 |
|--------|------|
| CloudWatch Log Groups | `/ecs/{backend,frontend,autoprober,insights,parityrun}` (14d) |
| CloudWatch Alarms × 7 | ALB 5xx ratio, ALB latency, ECS task 수 ×2, RDS CPU/Storage/Connections |
| CloudWatch Dashboard `BedrockMonitor-v2` | 5 widgets + alarm status grid |
| SNS Topic `bedrock-monitor-alarms` | 알람 fan-out |
| RUM (aws-rum-pipeline, v2.16.5) | 프론트 실사용자 모니터링 — 페이지뷰·체류시간·Web Vitals·JS 에러, `NEXT_PUBLIC_RUM_*` 빌드 타임 주입 |

### CDK 스택 구성

| 스택 | 의존 | 책임 |
|------|------|------|
| Network | - | VPC, NAT GW, PrivateLink endpoints |
| Data | Network | RDS, Secrets, SSM |
| Cluster | Network | ECS Cluster, ECR, 공유 KMS |
| AgentCore | - | AgentCore Memory + IAM |
| AppServices | Network·Data·Cluster·AgentCore | Fargate ×2, ALB, ALB logs |
| Edge | AppServices | CloudFront, WAF, CF logs |
| Scheduler | Network·Data·Cluster·AgentCore | EventBridge ×3, TaskDef ×3 |
| Observability | AppServices·Cluster·Data | Alarms, Dashboard, SNS |

### 핵심 설계 결정

자세한 사유는 [`docs/decisions/`](./decisions/)의 ADR-001 ~ ADR-025 참조 (012/014/015/016은 결번).

| ADR | 결정 |
|-----|------|
| 001 | CloudFront VPC Origin (internet-facing ALB 회피) |
| 002 | RDS t4g.micro Single-AZ (시계열 데이터 손실 허용) |
| 003 | Auto-prober EventBridge + Fargate Task로 분리 |
| 004 | ALB→ECS는 HTTP (intra-VPC, SG로 격리) |
| 005 | ACM Private CA cert (외부에서 cert ARN 주입) |
| 006 | AgentCore Memory만 사용, Runtime 이연 |
| 007 | SSE 패턴: VIEWER_REQUEST only + simulateStreaming |
| 008 | CDK TypeScript (VPC Origin 등 신기능 L2 우선) |
| 009 | FloatingChat 듀얼 모드 (popup/iframe) |
| 010 | ECR immutable tag 정책 (production `:latest` 금지) |
| 011 | Scheduler IAM `ecs:RunTask` Resource를 task def family `:*` wildcard로 |
| 013 | Output Analysis (stop_reason 분포 + output 길이) |
| 017 | 모델 catalogue 축소 (13 → 12) |
| 018 | ECR repository 교체 (`-v2`, Fargate image cache silent bug 우회) |
| 019 | OpenAI/Bedrock-Mantle provider path 추가 (gpt-5.4, gpt-5.5, 4 channels) |
| 020 | OpenAI 1P direct (api.openai.com) provider path 추가 (gpt-5.4/5.5, 2 channels) |
| 021 | 패리티 런 엔진 — 실행-증거 프로브 매트릭스 (HTTP 200 불충분, 12시간 주기 Fargate 스윕) |
| 022 | Mantle /anthropic surface — SigV4 파생 bearer + IAM 액션 체인 |
| 023 | 패리티 피처 19종 확장 — 적용 맵(skipped≠unsupported)·정직한 제외·요청 스냅샷 |
| 024 | RUM 통합 — aws-rum-pipeline + 자체 호스팅 SDK, NEXT_PUBLIC_* 빌드 타임 주입 |

### 운영 / Operations

- **배포**: [`docs/runbooks/deploy.md`](./runbooks/deploy.md)
- **롤백**: [`docs/runbooks/rollback.md`](./runbooks/rollback.md)
- **검증**: `make verify` — CDK lint + typecheck + 63 tests + cdk-nag + ruff + pytest 23 + frontend tsc.

---

## English

### System Overview

Bedrock LLM Monitor v2 is a full-stack monitoring tool that auto-probes a 40-channel active catalog across AWS Bedrock, Anthropic CP on AWS, and OpenAI (Mantle/1P) channels every 5 minutes, runs a model × API-surface × feature parity sweep every 12 hours (v2.11.0, 12h since v2.12.0), and exposes a Korean-language chatbot for natural-language queries. The topology is CloudFront VPC Origin → internal ALB → ECS Fargate (frontend/backend) → RDS PostgreSQL, with HTTPS-only ingress at every hop.

### Critical Path

```
Browser ──HTTPS──▶ CloudFront(WAF, default cert) ──VPC Origin, https-only──▶ Internal ALB(HTTPS:443) ──▶
   ├─ "/"      → ECS Fargate "frontend" (Next.js standalone)
   └─ "/api/*" → ECS Fargate "backend"  (FastAPI)
                    │
                    ├─ RDS PostgreSQL t4g.micro :5432
                    ├─ Bedrock Runtime (Claude Sonnet 4.6 etc.)
                    └─ AgentCore Memory (chat context)

EventBridge Scheduler
   ├─ rate(5 minutes)  → ECS RunTask "auto-prober" → 40 models → RDS
   ├─ rate(5 minutes)  → ECS RunTask "insights"    → 6h summary → RDS
   └─ rate(12 hours)     → ECS RunTask "parityrun"  → model × surface × feature evidence sweep → RDS
```

### Components by Layer

(See the Korean section above — the structure is identical. Layer tables list Edge, Compute, Storage, Agent, Scheduling, Network, Observability resources.)

### CDK Stack Decomposition

Network → Data → Cluster → AgentCore → AppServices → Edge → Scheduler → Observability.

The same table from the Korean section applies — the deploy order follows the dependency arrows.

### Key Design Decisions

See ADR-001 through ADR-025 in [`docs/decisions/`](./decisions/).

### Operations

- **Deploy**: [`docs/runbooks/deploy.md`](./runbooks/deploy.md)
- **Rollback**: [`docs/runbooks/rollback.md`](./runbooks/rollback.md)
- **Verify**: `make verify` — CDK lint + typecheck + 63 tests + cdk-nag + ruff + pytest 23 + frontend tsc.
