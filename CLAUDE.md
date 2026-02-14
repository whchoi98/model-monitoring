# CLAUDE.md — Project Context for Claude Code

## Project Overview / 프로젝트 개요

**Bedrock LLM Monitor** — A real-time dashboard for monitoring response speed, throughput, and reliability of AWS Bedrock LLM models.

**Bedrock LLM 모니터** — AWS Bedrock LLM 모델의 응답 속도, 처리량, 안정성을 실시간으로 모니터링하는 대시보드.

- **Backend**: FastAPI + SQLAlchemy ORM + PostgreSQL 16 (Docker)
- **Frontend**: Next.js 14 + React 18 + Tailwind CSS + Recharts
- **Infra**: EC2 (Amazon Linux 2023) + CloudFront + ALB + systemd

### Dashboard Screenshot / 대시보드 스크린샷

![Dashboard](docs/images/dashboard.png)

### Manual Probe Screenshot / 수동 프로브 스크린샷

![Manual Probe](docs/images/manual-probe.png)

---

## Architecture / 아키텍처

```
CloudFront (d1ra694ytoup3r.cloudfront.net)
    → ALB → EC2
        ├── Next.js 14 (port 3000) — /api/* proxied to backend
        ├── FastAPI (port 8000)
        │   ├── Auto Prober Thread (5min interval, 9 models, concurrency=3)
        │   └── PostgreSQL 16 (Docker, port 5432)
        └── AWS Bedrock (us-east-1) — converse_stream API
```

**EN**: The frontend proxies all `/api/*` requests to the FastAPI backend via Next.js rewrites. The backend runs a background daemon thread that automatically probes 9 Bedrock models every 5 minutes and stores results in PostgreSQL. CloudFront serves as the public entry point through an ALB.

**KO**: 프론트엔드는 Next.js rewrite를 통해 모든 `/api/*` 요청을 FastAPI 백엔드로 프록시합니다. 백엔드는 백그라운드 데몬 스레드로 5분마다 9개 Bedrock 모델을 자동 프로빙하여 결과를 PostgreSQL에 저장합니다. CloudFront가 ALB를 통해 퍼블릭 진입점 역할을 합니다.

---

## Directory Structure / 디렉토리 구조

```
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI entrypoint + lifespan / FastAPI 엔트리포인트 + lifespan
│   ├── auto_prober.py       # Background auto-probing thread / 백그라운드 자동 프로빙 스레드
│   ├── prober.py            # Core probe logic (Bedrock converse_stream) / 코어 프로브 로직
│   ├── auth.py              # JWT + bcrypt auth utilities / JWT + bcrypt 인증 유틸리티
│   ├── models.py            # SQLAlchemy ORM models / SQLAlchemy ORM 모델
│   ├── schemas.py           # Pydantic response schemas / Pydantic 응답 스키마
│   ├── database.py          # DB connection config / DB 연결 설정
│   ├── requirements.txt     # Python dependencies / Python 의존성
│   └── routers/
│       ├── auth.py          # /api/auth/* — login, register, approve, me
│       ├── auto_probe.py    # /api/auto-probe/* — status, latest, trend, trigger
│       ├── probes.py        # /api/probes/run — SSE streaming probe (auth required)
│       ├── results.py       # /api/results/* — query stored results
│       ├── models.py        # /api/models — available model list
│       └── prompts.py       # /api/prompts/* — prompt set CRUD (auth required)
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx         # Main page with tabs (Dashboard / Manual Probe)
│   │   │   └── layout.tsx       # Root layout (lang="ko", Korean metadata)
│   │   ├── components/
│   │   │   ├── AutoDashboard.tsx    # Auto-probe dashboard (status + grid + charts)
│   │   │   ├── ModelStatusGrid.tsx  # 3x3 model status cards with color-coded metrics
│   │   │   ├── TrendChart.tsx       # Recharts LineChart (TTFT / latency / TPS)
│   │   │   ├── LoginForm.tsx        # Login + register form with approval-pending state
│   │   │   ├── ProbeRunner.tsx      # Manual probe execution UI
│   │   │   ├── ResultsTable.tsx     # Probe results table
│   │   │   └── ...
│   │   ├── hooks/
│   │   │   ├── useAutoRefresh.ts    # 30s auto-refresh with countdown
│   │   │   └── useProbeStream.ts    # SSE streaming hook for manual probes
│   │   └── lib/
│   │       ├── api.ts       # API client (auth token mgmt, all fetch functions)
│   │       ├── i18n.ts      # Korean translations + metric descriptions
│   │       └── types.ts     # TypeScript interfaces
│   ├── next.config.ts       # API rewrites: /api/* → localhost:8000
│   ├── package.json
│   └── tailwind.config.ts
├── docker-compose.yml       # PostgreSQL container
├── deploy.sh                # One-click deployment script / 원클릭 배포 스크립트
└── cloudformation.yaml      # AWS CloudFormation template
```

---

## Key Commands / 주요 명령어

```bash
# Backend start / 백엔드 시작
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend dev mode / 프론트엔드 개발 모드
cd frontend && npm run dev

# Frontend production build / 프론트엔드 프로덕션 빌드
cd frontend && npm run build && npm start

# PostgreSQL start / PostgreSQL 시작
docker compose up -d
docker exec monitoring-postgres pg_isready -U postgres

# Service management (production) / 서비스 관리 (프로덕션)
sudo systemctl restart monitor-backend
sudo systemctl restart monitor-frontend
journalctl -u monitor-backend -f
journalctl -u monitor-frontend -f

# Auto-probe status check / 자동 프로빙 상태 확인
curl http://localhost:8000/api/auto-probe/status
curl http://localhost:8000/api/auto-probe/latest
curl -X POST http://localhost:8000/api/auto-probe/trigger

# DB direct access / DB 직접 접속
docker exec -it monitoring-postgres psql -U postgres -d monitoring
```

---

## Monitored Models (9 total) / 모니터링 대상 모델 (총 9개)

| Region / 리전 | Models / 모델 |
|----------------|---------------|
| US | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5, Nova 2.0 Lite |
| Global | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5 |

**EN**: Model list is defined in `backend/prober.py` → `AVAILABLE_MODELS` dict. US models have "(US)" suffix, Global models have "(Global)" suffix in display names.

**KO**: 모델 목록은 `backend/prober.py` → `AVAILABLE_MODELS` 딕셔너리에 정의되어 있습니다. US 모델은 "(US)", Global 모델은 "(Global)" 접미사가 표시됩니다.

---

## Metrics / 측정 지표

| Metric / 지표 | Unit / 단위 | EN Description | KO 설명 |
|----------------|-------------|----------------|---------|
| **TTFT** | ms | Time from request to first token arrival. Represents perceived initial response speed. | 요청 전송 후 첫 번째 토큰이 도착하기까지의 시간. 사용자가 체감하는 초기 응답 속도. |
| **Total Latency / 총 응답시간** | ms | End-to-end time from request to last token. Client-measured total latency. | 요청 전송부터 마지막 토큰 수신까지의 전체 소요 시간. |
| **Server Latency / 서버 처리시간** | ms | Internal processing time reported by Bedrock. Difference from total latency = network overhead. | Bedrock 서버가 보고한 내부 처리 시간. 총 응답시간과의 차이가 네트워크 오버헤드. |
| **TPS** | tok/s | Tokens per second. Output throughput from first to last token. | 초당 생성 토큰 수. 첫 토큰 이후부터 마지막 토큰까지의 출력 처리량. |
| **Input Tokens / 입력 토큰** | count / 개 | Tokens consumed by the prompt. Basis for cost calculation. | 프롬프트가 소비한 토큰 수. 비용 산정 기준. |
| **Output Tokens / 출력 토큰** | count / 개 | Tokens generated by the model. Used for cost and TPS calculation. | 모델이 생성한 응답 토큰 수. 비용 및 TPS 계산에 사용. |

---

## Authentication System / 인증 시스템

**EN**:
- **JWT Bearer Token** (24h expiry), signing key configurable via `JWT_SECRET_KEY` env var
- **Password hashing**: bcrypt via passlib (`bcrypt>=4.0,<4.1` pinned for compatibility)
- **Registration flow**: register → pending (approved=0) → admin notified via SES email → admin clicks approve link → approved (approved=1) → login allowed
- **Admin email**: `whchoi98@gmail.com` (configured in `backend/auth.py` → `ADMIN_EMAIL`)
- **Public base URL**: `https://d1ra694ytoup3r.cloudfront.net` (used in approval email links)
- **Protected endpoints**: `/api/probes/run`, `/api/prompts` (POST/DELETE), `/api/auth/me`
- **Public endpoints**: `/api/auto-probe/*`, `/api/results/*`, `/api/models`
- Admin account is auto-seeded on first startup in `main.py` lifespan

**KO**:
- **JWT Bearer Token** (24시간 유효), `JWT_SECRET_KEY` 환경변수로 서명 키 설정
- **비밀번호 해싱**: passlib을 통한 bcrypt (호환성을 위해 `bcrypt>=4.0,<4.1` 고정)
- **회원가입 흐름**: 가입 → 승인 대기(approved=0) → 관리자에게 SES 이메일 알림 → 관리자가 승인 링크 클릭 → 승인(approved=1) → 로그인 가능
- **관리자 이메일**: `whchoi98@gmail.com` (`backend/auth.py` → `ADMIN_EMAIL`에서 설정)
- **퍼블릭 베이스 URL**: `https://d1ra694ytoup3r.cloudfront.net` (승인 이메일 링크에 사용)
- **인증 필요 엔드포인트**: `/api/probes/run`, `/api/prompts` (POST/DELETE), `/api/auth/me`
- **공개 엔드포인트**: `/api/auto-probe/*`, `/api/results/*`, `/api/models`
- 최초 기동 시 `main.py` lifespan에서 관리자 계정 자동 생성

---

## API Endpoints / API 엔드포인트

### Auth / 인증

| Method | Path | Auth | EN Description | KO 설명 |
|--------|------|------|----------------|---------|
| POST | `/api/auth/login` | - | Login → JWT token (approved accounts only) | 로그인 → JWT 토큰 발급 (승인된 계정만) |
| POST | `/api/auth/register` | - | Register (pending state, sends admin email) | 회원가입 (승인 대기 상태, 관리자 이메일 발송) |
| GET | `/api/auth/approve?token=` | - | One-click approval link (for admin) | 이메일 승인 링크 (관리자 클릭용) |
| GET | `/api/auth/me` | Bearer | Current user info | 현재 사용자 정보 |

### Auto Probe / 자동 프로빙

| Method | Path | EN Description | KO 설명 |
|--------|------|----------------|---------|
| GET | `/api/auto-probe/status` | Prober status (running, last/next time) | 프로버 상태 (실행 여부, 마지막/다음 실행 시각) |
| GET | `/api/auto-probe/latest` | Latest results per model | 모델별 최신 결과 |
| GET | `/api/auto-probe/trend?hours=24` | Time-series data (default 24h) | 시계열 데이터 (기본 24시간) |
| POST | `/api/auto-probe/trigger` | Trigger immediate probe cycle | 즉시 1회 프로빙 실행 |

### Manual Probe / 수동 프로브 (Auth Required / 인증 필요)

| Method | Path | EN Description | KO 설명 |
|--------|------|----------------|---------|
| POST | `/api/probes/run` | SSE streaming probe execution | SSE 스트리밍 프로브 실행 |
| GET | `/api/models` | Available model list | 사용 가능한 모델 목록 |

### Results / 결과 조회

| Method | Path | EN Description | KO 설명 |
|--------|------|----------------|---------|
| GET | `/api/results` | Query results (filter: model_id, run_id, limit, offset) | 결과 조회 (필터 지원) |
| GET | `/api/results/latest` | Latest results | 최신 결과 |
| GET | `/api/results/stats` | Statistics (avg, p50, p95, p99) | 통계 (avg, p50, p95, p99) |

### Prompt Sets / 프롬프트 세트

| Method | Path | EN Description | KO 설명 |
|--------|------|----------------|---------|
| GET | `/api/prompts` | List prompt sets | 프롬프트 세트 목록 |
| POST | `/api/prompts` | Create prompt set (auth required) | 프롬프트 세트 생성 (인증 필요) |
| DELETE | `/api/prompts/{id}` | Delete prompt set (auth required) | 프롬프트 세트 삭제 (인증 필요) |

---

## Database / 데이터베이스

- PostgreSQL 16 via Docker (`docker-compose.yml`)
- Connection / 접속: `postgresql://postgres:postgres@localhost:5432/monitoring`
- Tables / 테이블: `probe_runs`, `probe_results`, `prompt_sets`, `users`
- Migrations run in `main.py` lifespan via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- 마이그레이션은 `main.py` lifespan에서 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`로 실행

```bash
# Direct DB access / DB 직접 접속
docker exec -it monitoring-postgres psql -U postgres -d monitoring

# Check auto-probe run count / 자동 프로빙 실행 횟수 확인
SELECT COUNT(*) FROM probe_runs WHERE is_auto = 1;

# Recent results / 최근 결과
SELECT model_name, ttft_ms, total_latency_ms, tps, status
FROM probe_results ORDER BY timestamp DESC LIMIT 9;
```

---

## Important Constraints / 중요 제약사항

### Python 3.9 Compatibility / Python 3.9 호환성
**EN**: Do NOT use `X | Y` union syntax in type hints used by FastAPI dependencies. Use `Optional[X]` from typing instead. `from __future__ import annotations` breaks FastAPI's runtime type evaluation.

**KO**: FastAPI 의존성에서 사용하는 타입 힌트에 `X | Y` 유니온 문법을 사용하지 마세요. `typing`의 `Optional[X]`을 사용하세요. `from __future__ import annotations`는 FastAPI의 런타임 타입 평가를 깨뜨립니다.

### bcrypt Version / bcrypt 버전
**EN**: Must be `>=4.0,<4.1`. Version 5.x is incompatible with passlib.

**KO**: 반드시 `>=4.0,<4.1`이어야 합니다. 5.x 버전은 passlib과 호환되지 않습니다.

### Next.js API Proxy / Next.js API 프록시
**EN**: All `/api/*` requests from the frontend are rewritten to `http://localhost:8000` via `next.config.ts` rewrites.

**KO**: 프론트엔드의 모든 `/api/*` 요청은 `next.config.ts`의 rewrites를 통해 `http://localhost:8000`으로 전달됩니다.

### Korean UI / 한글 UI
**EN**: All user-facing text is in Korean. Translations are in `frontend/src/lib/i18n.ts`.

**KO**: 모든 사용자 화면 텍스트는 한글입니다. 번역은 `frontend/src/lib/i18n.ts`에 있습니다.

### Auto-prober / 자동 프로버
**EN**: Runs as a daemon thread inside the FastAPI process. Not a separate service. Singleton instance at `backend/auto_prober.py`.

**KO**: FastAPI 프로세스 내부의 데몬 스레드로 실행됩니다. 별도 서비스가 아닙니다. `backend/auto_prober.py`에 싱글톤 인스턴스.

---

## Environment Variables / 환경 변수

| Variable / 변수 | Default / 기본값 | EN Description | KO 설명 |
|------------------|-------------------|----------------|---------|
| `JWT_SECRET_KEY` | `bedrock-monitor-secret-change-me` | JWT signing key | JWT 서명 키 |
| `PUBLIC_BASE_URL` | `https://d1ra694ytoup3r.cloudfront.net` | Base URL for approval email links | 승인 이메일 링크 베이스 URL |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/monitoring` | PostgreSQL connection string | PostgreSQL 접속 문자열 |

---

## Service Management / 서비스 관리

```bash
# Check status / 상태 확인
sudo systemctl status monitor-backend
sudo systemctl status monitor-frontend

# Restart / 재시작
sudo systemctl restart monitor-backend
sudo systemctl restart monitor-frontend

# View logs / 로그 확인
journalctl -u monitor-backend -f
journalctl -u monitor-frontend -f
```

**EN**: Service files are located at `/etc/systemd/system/monitor-backend.service` and `/etc/systemd/system/monitor-frontend.service`.

**KO**: 서비스 파일 위치: `/etc/systemd/system/monitor-backend.service`, `/etc/systemd/system/monitor-frontend.service`.

---

## Git

- Remote: `https://github.com/whchoi98/model-monitoring.git`
- Branch: `main`
