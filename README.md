# Bedrock LLM Monitor

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Version](https://img.shields.io/badge/Version-1.1.0-green.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js_14-000000?style=flat&logo=next.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16-4169E1?style=flat&logo=postgresql&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat&logo=tailwindcss&logoColor=white)
[![English](https://img.shields.io/badge/lang-English-blue)](#english)
[![한국어](https://img.shields.io/badge/lang-한국어-red)](#한국어)

**A real-time dashboard for monitoring response speed, throughput, and reliability of AWS Bedrock LLM models.**

**AWS Bedrock LLM 모델의 응답 속도, 처리량, 안정성을 실시간으로 모니터링하는 대시보드입니다.**

---

# English

## Overview

Bedrock LLM Monitor is a full-stack monitoring dashboard that automatically probes 13 AWS Bedrock LLM models every 5 minutes and visualizes performance metrics including TTFT (Time To First Token), total latency, and tokens per second (TPS). It supports both US region (us-east-1) and Global cross-region inference (ap-northeast-2) models, providing real-time insights into model availability and performance.

![Dashboard](docs/images/dashboard.png)

![Manual Probe](docs/images/manual-probe.png)

## Features

- **Auto Probing** — Automatically probes 13 models every 5 minutes with concurrency=3, storing results in PostgreSQL
- **Real-time Dashboard** — Model status cards with color-coded metrics + TTFT / latency / TPS trend charts
- **Manual Probe** — Execute probes with custom prompts, models, and parameters via SSE streaming (auth required)
- **History Statistics** — View historical performance stats (avg, p50, p95, p99) with configurable time ranges
- **Korean/English UI** — Full bilingual interface with metric descriptions and tooltips
- **User Authentication** — JWT-based login with email-based admin approval flow via AWS SES

## Prerequisites

- Python 3.9+
- Node.js 18+
- Docker and Docker Compose
- AWS credentials with `bedrock:InvokeModelWithResponseStream` permission
  - Regions: `us-east-1`, `ap-northeast-2`

## Installation

```bash
# Clone the repository
git clone https://github.com/whchoi98/model-monitoring.git
cd model-monitoring

# Option 1: Automated setup (recommended)
chmod +x deploy.sh
./deploy.sh

# Option 2: Manual setup
# Start PostgreSQL
docker compose up -d

# Install and run backend
cd backend
cp ../.env.example .env   # Edit with your values
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Install and run frontend (in a separate terminal)
cd frontend
npm install
npm run build
npm start
```

## Usage

```bash
# Check auto-prober status
curl http://localhost:8000/api/auto-probe/status

# View latest probe results
curl http://localhost:8000/api/auto-probe/latest

# Trigger an immediate probe cycle
curl -X POST http://localhost:8000/api/auto-probe/trigger

# View available models (13 total)
curl http://localhost:8000/api/models

# Access the dashboard
open http://localhost:3000
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `JWT_SECRET_KEY` | JWT signing key (required) | - |
| `DATABASE_URL` | PostgreSQL connection string (required) | - |
| `ADMIN_EMAIL` | Admin email for approval flow | `admin@example.com` |
| `DEFAULT_ADMIN_PASSWORD` | Initial admin password | `changeme` |
| `PUBLIC_BASE_URL` | Public URL for email links | `https://your-domain.com` |

| Setting | File | Variable |
|---------|------|----------|
| Probe interval | `backend/auto_prober.py` | `PROBE_INTERVAL` (default: 300s) |
| Model list | `backend/prober.py` | `AVAILABLE_MODELS` |
| Auto-refresh interval | `frontend/src/hooks/useAutoRefresh.ts` | `intervalMs` (default: 30000ms) |

## Monitored Models (13 Total)

| Region | Models |
|--------|--------|
| US (us-east-1) | Claude Opus 4.7, Claude Opus 4.6, Claude Sonnet 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5, Nova 2.0 Lite |
| Global (ap-northeast-2) | Claude Opus 4.7, Claude Opus 4.6, Claude Sonnet 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5 |

## Project Structure

```
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI entrypoint + lifespan
│   ├── auto_prober.py       # Background auto-probing thread
│   ├── prober.py            # Core probe logic (Bedrock converse_stream)
│   ├── auth.py              # JWT + bcrypt auth utilities
│   ├── models.py            # SQLAlchemy ORM models
│   ├── database.py          # DB connection config
│   └── routers/             # API endpoint handlers
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js App Router pages
│   │   ├── components/      # Dashboard, charts, forms
│   │   ├── hooks/           # Auto-refresh, SSE streaming
│   │   └── lib/             # API client, i18n, types
│   └── package.json
├── docs/
│   ├── architecture.md      # Architecture document (EN/KO)
│   ├── onboarding.md        # Developer onboarding guide
│   ├── api-reference.md     # API reference
│   ├── decisions/           # Architecture Decision Records
│   └── runbooks/            # Operational runbooks
├── .claude/                 # Claude Code project config
├── scripts/                 # Setup and utility scripts
├── tests/                   # Project structure tests
├── docker-compose.yml       # PostgreSQL container
├── deploy.sh                # One-click deployment script
└── cloudformation.yaml      # AWS CloudFormation template
```

## Architecture

```
                    ┌──────────────────────────────┐
                    │     Internet / Users          │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │       CloudFront CDN          │
                    │  llm-monitor.whchoi.net       │
                    └──────────────┬───────────────┘
                                   ▼
              ┌────────────────────────────────────────┐
              │              EC2 Instance               │
              │                                        │
              │  ┌──────────────┐  ┌────────────────┐  │
              │  │  Next.js 14  │  │   FastAPI       │  │
              │  │  :3000       │──▶  :8000          │  │
              │  └──────────────┘  │                 │  │
              │                    │  ┌────────────┐ │  │
              │                    │  │Auto Prober │ │  │
              │                    │  └─────┬──────┘ │  │
              │                    └────┬───┼────────┘  │
              │                    ┌────▼───▼────┐      │
              │                    │ PostgreSQL   │      │
              │                    │ :5432        │      │
              │                    └─────────────┘      │
              └────────────────────────┬───────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │      AWS Bedrock         │
                          │  us-east-1 (US models)   │
                          │  ap-northeast-2 (Global) │
                          └─────────────────────────┘
```

## Testing

```bash
# Run project structure tests (49 tests)
bash tests/run-all.sh

# Verify backend imports
cd backend && python -c "import main; print('OK')"

# Verify frontend builds
cd frontend && npm run build
```

## API Documentation

See [docs/api-reference.md](docs/api-reference.md) for the complete API reference.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/auto-probe/status` | - | Auto-prober status |
| GET | `/api/auto-probe/latest` | - | Latest results per model |
| GET | `/api/auto-probe/trend?hours=24` | - | Time-series data |
| POST | `/api/auto-probe/trigger` | - | Trigger immediate probe |
| POST | `/api/probes/run` | Bearer | SSE streaming probe |
| GET | `/api/models` | - | Available model list |
| GET | `/api/results/stats` | - | Statistics (avg, p50, p95, p99) |
| POST | `/api/auth/login` | - | Login |
| POST | `/api/auth/register` | - | Register |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `refactor:` code refactoring
- `chore:` maintenance

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact

- **Maintainer**: Woo Hyung Choi (whchoi98)
- **GitHub**: [https://github.com/whchoi98/model-monitoring](https://github.com/whchoi98/model-monitoring)
- **Issues**: [https://github.com/whchoi98/model-monitoring/issues](https://github.com/whchoi98/model-monitoring/issues)
- **Email**: whchoi98@gmail.com

---

# 한국어

## 개요

Bedrock LLM 모니터는 13개의 AWS Bedrock LLM 모델을 5분마다 자동으로 프로빙하여 TTFT(첫 토큰 시간), 총 응답시간, TPS(초당 토큰 수)를 실시간으로 시각화하는 풀스택 모니터링 대시보드입니다. US 리전(us-east-1)과 Global 크로스 리전 추론(ap-northeast-2) 모델을 모두 지원하며, 모델 가용성과 성능에 대한 실시간 인사이트를 제공합니다.

![Dashboard](docs/images/dashboard.png)

![Manual Probe](docs/images/manual-probe.png)

## 주요 기능

- **자동 프로빙** — 5분 간격으로 13개 모델을 동시성=3으로 자동 프로빙하여 PostgreSQL에 저장합니다
- **실시간 대시보드** — 색상 코딩된 모델 상태 카드 + TTFT / 응답시간 / TPS 추이 차트를 제공합니다
- **수동 프로브** — 프롬프트, 모델, 파라미터를 지정하여 SSE 스트리밍으로 즉시 실행합니다 (인증 필요)
- **이력 통계** — 시간 범위별 과거 성능 통계(avg, p50, p95, p99)를 조회합니다
- **한국어/영어 UI** — 지표 설명 및 툴팁이 포함된 완전한 이중 언어 인터페이스입니다
- **사용자 인증** — JWT 기반 로그인과 AWS SES를 통한 이메일 관리자 승인 플로우를 지원합니다

## 사전 요구 사항

- Python 3.9+
- Node.js 18+
- Docker 및 Docker Compose
- `bedrock:InvokeModelWithResponseStream` 권한이 있는 AWS 자격 증명
  - 리전: `us-east-1`, `ap-northeast-2`

## 설치 방법

```bash
# 저장소 클론
git clone https://github.com/whchoi98/model-monitoring.git
cd model-monitoring

# 방법 1: 자동 배포 (권장)
chmod +x deploy.sh
./deploy.sh

# 방법 2: 수동 설치
# PostgreSQL 시작
docker compose up -d

# 백엔드 설치 및 실행
cd backend
cp ../.env.example .env   # 값을 수정하세요
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# 프론트엔드 설치 및 실행 (별도 터미널에서)
cd frontend
npm install
npm run build
npm start
```

## 사용법

```bash
# 자동 프로버 상태 확인
curl http://localhost:8000/api/auto-probe/status

# 최신 프로빙 결과 조회
curl http://localhost:8000/api/auto-probe/latest

# 즉시 1회 프로빙 실행
curl -X POST http://localhost:8000/api/auto-probe/trigger

# 사용 가능한 모델 목록 (총 13개)
curl http://localhost:8000/api/models

# 대시보드 접속
open http://localhost:3000
```

## 환경 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `JWT_SECRET_KEY` | JWT 서명 키 (필수) | - |
| `DATABASE_URL` | PostgreSQL 접속 문자열 (필수) | - |
| `ADMIN_EMAIL` | 승인 알림 관리자 이메일 | `admin@example.com` |
| `DEFAULT_ADMIN_PASSWORD` | 초기 관리자 비밀번호 | `changeme` |
| `PUBLIC_BASE_URL` | 이메일 링크 베이스 URL | `https://your-domain.com` |

| 설정 항목 | 파일 | 변수 |
|-----------|------|------|
| 프로빙 주기 | `backend/auto_prober.py` | `PROBE_INTERVAL` (기본: 300초) |
| 모델 목록 | `backend/prober.py` | `AVAILABLE_MODELS` |
| 자동 새로고침 주기 | `frontend/src/hooks/useAutoRefresh.ts` | `intervalMs` (기본: 30000ms) |

## 모니터링 대상 모델 (총 13개)

| 리전 | 모델 |
|------|------|
| US (us-east-1) | Claude Opus 4.7, Claude Opus 4.6, Claude Sonnet 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5, Nova 2.0 Lite |
| Global (ap-northeast-2) | Claude Opus 4.7, Claude Opus 4.6, Claude Sonnet 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5 |

## 프로젝트 구조

```
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI 엔트리포인트 + lifespan
│   ├── auto_prober.py       # 자동 프로빙 백그라운드 스레드
│   ├── prober.py            # 코어 프로브 로직 (Bedrock converse_stream)
│   ├── auth.py              # JWT + bcrypt 인증 유틸리티
│   ├── models.py            # SQLAlchemy ORM 모델
│   ├── database.py          # DB 연결 설정
│   └── routers/             # API 엔드포인트 핸들러
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js App Router 페이지
│   │   ├── components/      # 대시보드, 차트, 폼
│   │   ├── hooks/           # 자동 새로고침, SSE 스트리밍
│   │   └── lib/             # API 클라이언트, i18n, 타입
│   └── package.json
├── docs/
│   ├── architecture.md      # 아키텍처 문서 (EN/KO)
│   ├── onboarding.md        # 개발자 온보딩 가이드
│   ├── api-reference.md     # API 레퍼런스
│   ├── decisions/           # ADR (아키텍처 결정 기록)
│   └── runbooks/            # 운영 런북
├── .claude/                 # Claude Code 프로젝트 설정
├── scripts/                 # 셋업 및 유틸리티 스크립트
├── tests/                   # 프로젝트 구조 테스트
├── docker-compose.yml       # PostgreSQL 컨테이너
├── deploy.sh                # 원클릭 배포 스크립트
└── cloudformation.yaml      # AWS CloudFormation 템플릿
```

## 아키텍처

```
                    ┌──────────────────────────────┐
                    │     인터넷 / 사용자            │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │       CloudFront CDN          │
                    │  llm-monitor.whchoi.net       │
                    └──────────────┬───────────────┘
                                   ▼
              ┌────────────────────────────────────────┐
              │              EC2 인스턴스                │
              │                                        │
              │  ┌──────────────┐  ┌────────────────┐  │
              │  │  Next.js 14  │  │   FastAPI       │  │
              │  │  :3000       │──▶  :8000          │  │
              │  └──────────────┘  │                 │  │
              │                    │  ┌────────────┐ │  │
              │                    │  │자동 프로버  │ │  │
              │                    │  └─────┬──────┘ │  │
              │                    └────┬───┼────────┘  │
              │                    ┌────▼───▼────┐      │
              │                    │ PostgreSQL   │      │
              │                    │ :5432        │      │
              │                    └─────────────┘      │
              └────────────────────────┬───────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │      AWS Bedrock         │
                          │  us-east-1 (US 모델)     │
                          │  ap-northeast-2 (Global) │
                          └─────────────────────────┘
```

## 테스트

```bash
# 프로젝트 구조 테스트 실행 (49개 테스트)
bash tests/run-all.sh

# 백엔드 임포트 검증
cd backend && python -c "import main; print('OK')"

# 프론트엔드 빌드 검증
cd frontend && npm run build
```

## API 문서

전체 API 레퍼런스는 [docs/api-reference.md](docs/api-reference.md)를 참조하세요.

| 메서드 | 경로 | 인증 | 설명 |
|--------|------|------|------|
| GET | `/api/auto-probe/status` | - | 자동 프로버 상태 |
| GET | `/api/auto-probe/latest` | - | 모델별 최신 결과 |
| GET | `/api/auto-probe/trend?hours=24` | - | 시계열 데이터 |
| POST | `/api/auto-probe/trigger` | - | 즉시 프로빙 실행 |
| POST | `/api/probes/run` | Bearer | SSE 스트리밍 프로브 |
| GET | `/api/models` | - | 사용 가능한 모델 목록 |
| GET | `/api/results/stats` | - | 통계 (avg, p50, p95, p99) |
| POST | `/api/auth/login` | - | 로그인 |
| POST | `/api/auth/register` | - | 회원가입 |

## 기여 방법

1. 저장소를 Fork합니다
2. 기능 브랜치를 생성합니다 (`git checkout -b feat/amazing-feature`)
3. 변경 사항을 커밋합니다 (`git commit -m 'feat: add amazing feature'`)
4. 브랜치에 Push합니다 (`git push origin feat/amazing-feature`)
5. Pull Request를 생성합니다

커밋 메시지는 [Conventional Commits](https://www.conventionalcommits.org/) 형식을 따릅니다:
- `feat:` 새 기능
- `fix:` 버그 수정
- `docs:` 문서
- `refactor:` 코드 리팩토링
- `chore:` 유지보수

## 라이선스

이 프로젝트는 MIT 라이선스로 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 연락처

- **메인테이너**: 최우형 (whchoi98)
- **GitHub**: [https://github.com/whchoi98/model-monitoring](https://github.com/whchoi98/model-monitoring)
- **Issues**: [https://github.com/whchoi98/model-monitoring/issues](https://github.com/whchoi98/model-monitoring/issues)
- **Email**: whchoi98@gmail.com
