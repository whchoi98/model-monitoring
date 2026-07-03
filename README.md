# Amazon Bedrock LLM Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.6.1-blue.svg)](CHANGELOG.md)
[![Build](https://img.shields.io/badge/build-CDK%20%7C%20Docker-success)](docs/runbooks/deploy.md)
[![English](https://img.shields.io/badge/lang-English-blue.svg)](#english)
[![한국어](https://img.shields.io/badge/lang-한국어-red.svg)](#한국어)

A real-time observability dashboard for Amazon Bedrock + Anthropic CP on AWS LLM channels — speed, throughput, reliability, cost, and output quality.

Amazon Bedrock + Anthropic CP on AWS LLM 채널의 응답 속도·처리량·신뢰성·비용·출력 품질을 실시간으로 모니터링하는 대시보드입니다.

---

# English

## Overview

Amazon Bedrock LLM Monitor is a production-grade observability platform that continuously probes 28 LLM channels across Bedrock Global / US inference profiles, Anthropic CP on AWS, OpenAI GPT via Bedrock Mantle (Path 4), and OpenAI 1P direct / api.openai.com (Path 5). It surfaces latency (TTFT, total, server), throughput (TPS), output token distribution, stop-reason patterns, multi-channel reliability, and 30-day cost projections — all behind a Next.js dashboard with six analytical views.

The system runs on AWS ECS Fargate (CDK-managed, 8 stacks), with EventBridge Scheduler driving 5-minute round-robin workload probes across six prompt categories. A built-in chatbot (Claude Sonnet 4.6 with four Bedrock tools) lets you query the time-series data conversationally.

![Dashboard](docs/images/dashboard.png)

## Features

- **Real-time auto-probing** — EventBridge Scheduler fires a Fargate task every 5 minutes that round-robins six workload categories (chat-short, reasoning, code-gen, summarize, structured-json, creative-writing) across all 28 monitored channels.
- **Six analytical pages** — Dashboard (latency / TPS trends), Cost (30-day projection + channel comparison), Reliability (success rate per family/channel + error buckets), Efficiency (weighted 0-100 score), Analysis (stop-reason distribution + output-length histograms), Prompts (set CRUD + Bedrock OptimizePrompt).
- **Multi-channel comparison** — Same model family invoked through Bedrock Global, Bedrock US, Anthropic CP on AWS (Path 3 External), OpenAI GPT via Bedrock Mantle (Path 4), and OpenAI 1P direct / api.openai.com (Path 5) in parallel for true apples-to-apples evaluation.
- **AI chatbot with tools** — Claude Sonnet 4.6 chatbot answers natural-language questions over the time-series store using four custom Bedrock tools; dynamic follow-up suggestions generated per turn.
- **CDK-managed infrastructure** — Eight TypeScript stacks (Network, Data, Cluster, AgentCore, AppServices, Edge, Scheduler, Observability) with reusable L3 constructs, immutable ECR tags, and idempotent lifespan migrations.

## Prerequisites

- AWS account with administrator credentials in `ap-northeast-2` (Seoul)
- Node.js >= 20 and npm (CDK)
- Python >= 3.11 (backend)
- Docker (image build for backend and frontend)
- PostgreSQL 16 (local development only)
- ACM certificate for the internal ALB listener (issued in the deploy region)
- An Anthropic API key + workspace ID for the CP on AWS channel

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/whchoi98/model-monitoring.git
cd model-monitoring

# 2. Verify the toolchain
make verify

# 3. Pre-create the SSM SecureString secrets (one-time, manual)
aws ssm put-parameter --name /bedrock-monitor/jwt-secret-key --type SecureString \
  --value "$(openssl rand -base64 48)"
aws ssm put-parameter --name /bedrock-monitor/anthropic-api-key --type SecureString \
  --value "<your Anthropic API key>"
aws ssm put-parameter --name /bedrock-monitor/anthropic-workspace-id --type SecureString \
  --value "<your Anthropic workspace ID>"
aws ssm put-parameter --name /bedrock-monitor/seed-admin-password --type SecureString \
  --value "<initial admin password>"

# 4. Build and push container images to ECR (immutable tag — never use :latest in production)
REGION=ap-northeast-2
ACCT=$(aws sts get-caller-identity --query Account --output text)
TAG="v$(date +%s)"

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCT.dkr.ecr.$REGION.amazonaws.com

docker build --no-cache --pull --platform linux/arm64 -t bedrock-monitor-backend:$TAG backend/
docker tag bedrock-monitor-backend:$TAG \
  $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG

docker build --no-cache --pull --platform linux/arm64 -t bedrock-monitor-frontend:$TAG frontend/
docker tag bedrock-monitor-frontend:$TAG \
  $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG

# 5. Deploy the eight CDK stacks
cd cdk
npx cdk deploy --all \
  -c albCertificateArn="arn:aws:acm:ap-northeast-2:ACCOUNT:certificate/UUID" \
  -c alarmEmail="ops@example.com"
```

See `docs/runbooks/deploy.md` for the full step-by-step procedure including post-deploy verification.

## Usage

```bash
# Verify the dashboard endpoint
curl https://<your-cloudfront-domain>/api/auto-probe/status
# {"is_running":true,"last_run_time":"...","next_run_time":"...","interval_seconds":300}

# Inspect the latest 28-model probe results
curl https://<your-cloudfront-domain>/api/auto-probe/latest

# Filter by workload category
curl https://<your-cloudfront-domain>/api/auto-probe/latest?category=code-gen

# Authenticate and run a manual probe (SSE stream)
TOKEN=$(curl -sX POST https://<your-cloudfront-domain>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<your seed password>"}' | jq -r .access_token)

curl -N -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -X POST https://<your-cloudfront-domain>/api/probes/run \
  -d '{"model_ids":["global.anthropic.claude-haiku-4-5-20251001-v1:0"],"prompt":"hello","max_tokens":50}'
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `JWT_SECRET_KEY` | JWT signing key (32+ characters; placeholders rejected) | (required, from SSM) |
| `SEED_ADMIN_USERNAME` | Initial admin username for first-boot seeding | `admin` |
| `SEED_ADMIN_PASSWORD` | Initial admin password (8+ characters) | (required, from SSM) |
| `PUBLIC_BASE_URL` | Public base URL used in approval-email links | `https://<your-cloudfront-domain>` |
| `DATABASE_URL` | PostgreSQL connection string (built from injected env in CDK) | (CDK-injected) |
| `ANTHROPIC_API_KEY` | Anthropic CP on AWS envelope key (AEAAQ…) | (required, from SSM) |
| `ANTHROPIC_WORKSPACE_ID` | Anthropic CP workspace ID header | (required, from SSM) |
| `ANTHROPIC_AWS_REGION` | CP on AWS endpoint region | `us-east-2` |

## Project Structure

```
model-monitoring/
├── backend/                      # FastAPI + SQLAlchemy + auto-prober
│   ├── main.py                   # entrypoint, lifespan, DB migration with advisory_lock
│   ├── prober.py                 # 28-model AVAILABLE_MODELS, retry, Bedrock + Anthropic CP + OpenAI (Mantle + 1P)
│   ├── auto_prober.py            # run_cycle() invoked by EventBridge Fargate task
│   ├── pricing.py                # token unit price table
│   └── routers/                  # 14 router modules (auth, admin, analysis, cost, …)
├── frontend/                     # Next.js 14 standalone + 6 routes
│   ├── src/app/                  # /, /prompts, /cost, /reliability, /efficiency, /analysis
│   ├── src/components/           # 30+ React components (dashboard, panels, chat)
│   └── src/lib/                  # api client, i18n, sortModels, pricing mirror, version
├── cdk/                          # 8 CDK TypeScript stacks
│   ├── lib/stacks/               # Network, Data, Cluster, AgentCore, AppServices, …
│   └── lib/constructs/           # reusable FargateServiceConstruct (L3)
├── docs/
│   ├── architecture.md           # full system design
│   ├── decisions/                # ADR-001 through ADR-019
│   ├── runbooks/                 # deploy, rollback procedures
│   └── CHANGELOG.md              # Keep-a-Changelog format
└── Makefile                      # `make verify` runs CDK lint + tests + ruff + tsc
```

## Testing

```bash
# Full verification (CDK lint + typecheck + 63 Jest tests + cdk-nag + ruff + 23 pytest + frontend tsc)
make verify

# Backend tests only
cd backend && pytest -q

# CDK tests only
cd cdk && npm test

# Frontend typecheck
cd frontend && npx tsc --noEmit
```

## API Documentation

The FastAPI backend exposes auto-generated OpenAPI documentation at:

```
https://<your-cloudfront-domain>/docs    # Swagger UI
https://<your-cloudfront-domain>/openapi.json
```

Key endpoint groups:

| Group | Path prefix | Authentication |
|-------|-------------|----------------|
| Auth | `/api/auth/*` | login/register public, `/me` requires JWT |
| Auto-probe | `/api/auto-probe/*` | public |
| Results | `/api/results/*` | public |
| Manual probe | `/api/probes/run` | JWT required |
| Cost / Reliability / Efficiency / Analysis | `/api/{cost,reliability,efficiency,analysis}/*` | public |
| Chat | `/api/chat/*` | JWT required |
| Insights | `/api/insights/*` | regenerate requires JWT |
| Admin | `/api/admin/*` | admin role only |

## Contributing

1. **Fork** the repository on GitHub.
2. Create a **branch** from `main`: `git checkout -b feat/your-feature`.
3. **Commit** with Conventional Commits style: `feat(scope): add X` / `fix(scope): handle Y`.
4. **Push** the branch: `git push origin feat/your-feature`.
5. Open a **Pull Request** against `main` with a summary and test evidence (`make verify` output).

Run `make verify` before pushing — CI uses the same target as the merge gate.

## License

This project is licensed under the [MIT License](LICENSE).

## Contact

- Maintainer: **WooHyung Choi** ([@whchoi98](https://github.com/whchoi98))
- Issues: [github.com/whchoi98/model-monitoring/issues](https://github.com/whchoi98/model-monitoring/issues)
- Email: whchoi98@gmail.com

---

# 한국어

## 개요

Amazon Bedrock LLM Monitor는 Bedrock Global / US 추론 프로파일, Anthropic CP on AWS, OpenAI GPT via Bedrock Mantle(Path 4)·1P direct api.openai.com(Path 5)을 포함한 28개 LLM 채널을 지속적으로 프로빙하여 지연(TTFT, 총 응답시간, 서버 처리시간), 처리량(TPS), 출력 토큰 분포, 정지 사유 패턴, 다중 채널 신뢰성, 30일 비용 예측을 한 대시보드에서 제공하는 운영 등급 관측 플랫폼입니다.

이 시스템은 AWS ECS Fargate (CDK 8개 스택)에서 동작하며, EventBridge Scheduler가 5분마다 6개 워크로드 카테고리를 라운드로빈하여 모든 채널을 프로빙합니다. Claude Sonnet 4.6 + 4개 Bedrock 도구로 구성된 챗봇이 시계열 데이터에 대해 자연어 질의를 지원합니다.

![대시보드](docs/images/dashboard.png)

## 주요 기능

- **실시간 자동 프로빙** — EventBridge Scheduler가 5분마다 Fargate 태스크를 실행하여 6개 워크로드 카테고리(짧은 대화, 추론, 코드 생성, 요약, 구조화 JSON, 창작)를 라운드로빈으로 28개 모니터링 채널에 호출합니다.
- **6개 분석 페이지** — 대시보드(지연/TPS 추이), 비용(30일 예측 + 채널 비교), 신뢰성(family/channel별 성공률 + 에러 버킷), 효율성(가중 0~100 점수), 분석(정지 사유 분포 + 출력 길이 히스토그램), 프롬프트(세트 CRUD + Bedrock OptimizePrompt).
- **다중 채널 비교** — 동일 모델 family를 Bedrock Global, Bedrock US, Anthropic CP on AWS (Path 3 External), OpenAI GPT via Bedrock Mantle (Path 4), OpenAI 1P direct / api.openai.com (Path 5) 다섯 채널로 병렬 호출하여 정확한 동일 조건 비교를 제공합니다.
- **AI 챗봇 + 도구** — Claude Sonnet 4.6 챗봇이 4개의 Bedrock 커스텀 도구를 사용해 시계열 데이터에 대한 자연어 질의에 응답하며, 매 턴마다 동적 후속 질문을 생성합니다.
- **CDK 기반 인프라** — TypeScript로 작성된 8개 스택(Network, Data, Cluster, AgentCore, AppServices, Edge, Scheduler, Observability)과 재사용 가능한 L3 construct, 불변 ECR tag, 멱등 lifespan 마이그레이션을 제공합니다.

## 사전 요구 사항

- `ap-northeast-2` (서울) 리전 관리자 권한이 있는 AWS 계정
- Node.js 20 이상 + npm (CDK 용)
- Python 3.11 이상 (백엔드)
- Docker (backend / frontend 이미지 빌드)
- PostgreSQL 16 (로컬 개발 시에만 필요)
- 배포 리전에서 발급된 ACM 인증서 (내부 ALB 리스너용)
- CP on AWS 채널을 위한 Anthropic API key + workspace ID

## 설치 방법

```bash
# 1. 저장소 클론
git clone https://github.com/whchoi98/model-monitoring.git
cd model-monitoring

# 2. 툴체인 검증
make verify

# 3. SSM SecureString 시크릿 사전 생성 (최초 1회, 수동)
aws ssm put-parameter --name /bedrock-monitor/jwt-secret-key --type SecureString \
  --value "$(openssl rand -base64 48)"
aws ssm put-parameter --name /bedrock-monitor/anthropic-api-key --type SecureString \
  --value "<Anthropic API key>"
aws ssm put-parameter --name /bedrock-monitor/anthropic-workspace-id --type SecureString \
  --value "<Anthropic workspace ID>"
aws ssm put-parameter --name /bedrock-monitor/seed-admin-password --type SecureString \
  --value "<초기 관리자 비밀번호>"

# 4. 컨테이너 이미지 빌드 + ECR push (불변 태그 — production에서 :latest 금지)
REGION=ap-northeast-2
ACCT=$(aws sts get-caller-identity --query Account --output text)
TAG="v$(date +%s)"

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCT.dkr.ecr.$REGION.amazonaws.com

docker build --no-cache --pull --platform linux/arm64 -t bedrock-monitor-backend:$TAG backend/
docker tag bedrock-monitor-backend:$TAG \
  $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG

docker build --no-cache --pull --platform linux/arm64 -t bedrock-monitor-frontend:$TAG frontend/
docker tag bedrock-monitor-frontend:$TAG \
  $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG

# 5. CDK 8개 스택 배포
cd cdk
npx cdk deploy --all \
  -c albCertificateArn="arn:aws:acm:ap-northeast-2:ACCOUNT:certificate/UUID" \
  -c alarmEmail="ops@example.com"
```

배포 후 검증을 포함한 전체 절차는 `docs/runbooks/deploy.md`를 참고하세요.

## 사용법

```bash
# 대시보드 엔드포인트 동작 확인
curl https://<your-cloudfront-domain>/api/auto-probe/status
# {"is_running":true,"last_run_time":"...","next_run_time":"...","interval_seconds":300}

# 최신 28개 모델 프로빙 결과 조회
curl https://<your-cloudfront-domain>/api/auto-probe/latest

# 워크로드 카테고리별 필터링
curl https://<your-cloudfront-domain>/api/auto-probe/latest?category=code-gen

# 로그인 후 수동 프로브 실행 (SSE 스트리밍)
TOKEN=$(curl -sX POST https://<your-cloudfront-domain>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<seed 비밀번호>"}' | jq -r .access_token)

curl -N -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -X POST https://<your-cloudfront-domain>/api/probes/run \
  -d '{"model_ids":["global.anthropic.claude-haiku-4-5-20251001-v1:0"],"prompt":"안녕","max_tokens":50}'
```

## 환경 설정

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `JWT_SECRET_KEY` | JWT 서명 키 (32자 이상; placeholder 거부) | (필수, SSM 주입) |
| `SEED_ADMIN_USERNAME` | 최초 부팅 시 시드되는 관리자 username | `admin` |
| `SEED_ADMIN_PASSWORD` | 초기 관리자 비밀번호 (8자 이상) | (필수, SSM 주입) |
| `PUBLIC_BASE_URL` | 승인 이메일 링크 기준 URL | `https://<your-cloudfront-domain>` |
| `DATABASE_URL` | PostgreSQL 접속 문자열 (CDK에서 환경변수로 조립) | (CDK 주입) |
| `ANTHROPIC_API_KEY` | Anthropic CP on AWS envelope key (AEAAQ…) | (필수, SSM 주입) |
| `ANTHROPIC_WORKSPACE_ID` | Anthropic CP workspace ID 헤더 | (필수, SSM 주입) |
| `ANTHROPIC_AWS_REGION` | CP on AWS endpoint 리전 | `us-east-2` |

## 프로젝트 구조

```
model-monitoring/
├── backend/                      # FastAPI + SQLAlchemy + auto-prober
│   ├── main.py                   # 엔트리포인트, lifespan, advisory_lock 기반 DB 마이그레이션
│   ├── prober.py                 # 28개 모델 AVAILABLE_MODELS, retry, Bedrock + Anthropic CP + OpenAI (Mantle + 1P)
│   ├── auto_prober.py            # EventBridge Fargate task가 호출하는 run_cycle()
│   ├── pricing.py                # 토큰 단가 테이블
│   └── routers/                  # 14개 라우터 (auth, admin, analysis, cost, …)
├── frontend/                     # Next.js 14 standalone + 6 라우트
│   ├── src/app/                  # /, /prompts, /cost, /reliability, /efficiency, /analysis
│   ├── src/components/           # 30+ React 컴포넌트 (대시보드, 패널, 챗)
│   └── src/lib/                  # API 클라이언트, i18n, sortModels, pricing 미러, version
├── cdk/                          # 8개 CDK TypeScript 스택
│   ├── lib/stacks/               # Network, Data, Cluster, AgentCore, AppServices, …
│   └── lib/constructs/           # 재사용 가능한 FargateServiceConstruct (L3)
├── docs/
│   ├── architecture.md           # 전체 시스템 설계
│   ├── decisions/                # ADR-001 ~ ADR-019
│   ├── runbooks/                 # 배포 / 롤백 절차
│   └── CHANGELOG.md              # Keep a Changelog 형식
└── Makefile                      # `make verify` — CDK lint + tests + ruff + tsc 일괄 실행
```

## 테스트

```bash
# 전체 검증 (CDK lint + typecheck + 63 Jest tests + cdk-nag + ruff + 23 pytest + frontend tsc)
make verify

# 백엔드 테스트
cd backend && pytest -q

# CDK 테스트
cd cdk && npm test

# 프론트엔드 타입 체크
cd frontend && npx tsc --noEmit
```

## API 문서

FastAPI 백엔드는 자동 생성된 OpenAPI 문서를 제공합니다:

```
https://<your-cloudfront-domain>/docs    # Swagger UI
https://<your-cloudfront-domain>/openapi.json
```

주요 엔드포인트 그룹:

| 그룹 | 경로 prefix | 인증 |
|------|-------------|------|
| 인증 | `/api/auth/*` | login/register 공개, `/me` JWT 필요 |
| 자동 프로빙 | `/api/auto-probe/*` | 공개 |
| 결과 조회 | `/api/results/*` | 공개 |
| 수동 프로빙 | `/api/probes/run` | JWT 필요 |
| 비용 / 신뢰성 / 효율성 / 분석 | `/api/{cost,reliability,efficiency,analysis}/*` | 공개 |
| 챗봇 | `/api/chat/*` | JWT 필요 |
| 인사이트 | `/api/insights/*` | 재생성 시 JWT 필요 |
| 관리자 | `/api/admin/*` | admin 전용 |

## 기여 방법

1. GitHub에서 저장소를 **Fork**합니다.
2. `main`에서 **브랜치**를 생성합니다: `git checkout -b feat/your-feature`.
3. Conventional Commits 형식으로 **커밋**합니다: `feat(scope): add X` / `fix(scope): handle Y`.
4. 브랜치를 **Push**합니다: `git push origin feat/your-feature`.
5. `main`을 향한 **Pull Request**를 등록하고 요약과 테스트 증거(`make verify` 출력)를 첨부합니다.

Push 전에 `make verify`를 실행하세요. CI에서도 동일한 target을 머지 게이트로 사용합니다.

## 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE) 하에 배포됩니다.

## 연락처

- 메인테이너: **최우형 (WooHyung Choi)** ([@whchoi98](https://github.com/whchoi98))
- 이슈: [github.com/whchoi98/model-monitoring/issues](https://github.com/whchoi98/model-monitoring/issues)
- 이메일: whchoi98@gmail.com
