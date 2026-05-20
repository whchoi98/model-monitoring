# Bedrock LLM 모니터

AWS Bedrock LLM 모델의 응답 속도, 처리량, 안정성을 실시간으로 모니터링하는 대시보드입니다.

> ⚡ **v2 — CDK TypeScript + ECS Fargate + CloudFront VPC Origin + AgentCore + 챗봇**.
> 설계: [`docs/architecture.md`](./docs/architecture.md) · 배포/롤백: [`docs/runbooks/`](./docs/runbooks/) · ADR: [`docs/decisions/`](./docs/decisions/) · 스펙: [`.kiro/specs/v2-upgrade/`](./.kiro/specs/v2-upgrade/)

![Stack](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Stack](https://img.shields.io/badge/Next.js_14-000000?style=flat&logo=next.js&logoColor=white)
![Stack](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Stack](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat&logo=tailwindcss&logoColor=white)

### 대시보드 스크린샷

![Dashboard](docs/images/dashboard.png)

### 수동 프로브 스크린샷

![Manual Probe](docs/images/manual-probe.png)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **자동 프로빙** | EventBridge Scheduler가 5분 간격으로 별도 Fargate Task를 트리거 → **12개 모델** (9 Bedrock Global/US + 3 Anthropic CP on AWS) 자동 프로빙. 6개 워크로드 카테고리(짧은 대화/추론/코드 생성/요약/구조화 JSON/창작)를 라운드로빈으로 회전. Opus 4.7 / 4.6 / Sonnet 4.6 / Haiku 4.5 / Nova 2.0 Lite (US) family |
| **대시보드 + 5개 탭** | `/` 대시보드 / `/prompts` 프롬프트 / `/cost` 비용 / `/reliability` 신뢰성 / `/efficiency` 효율성 / `/analysis` **출력 분석 (v2.1.0 신규)** |
| **수동 프로브** | 로그인 후 모델·프롬프트·동시성·반복 횟수를 지정하여 즉시 실행, SSE 스트리밍 결과 확인 |
| **출력 분석 (v2.1.0 신규)** | Stop Reason 분포 (end_turn/max_tokens/guardrail 등) + Output Token 길이 분포 (median/p95/std + 7-bin histogram) |
| **사용자 인증** | 회원가입은 이메일 형식 강제 → 관리자 SES 승인 → 로그인. JWT 토큰 24시간 |
| **한글/영어 UI 토글** | 전체 인터페이스 KO/EN 양 언어 |
| **챗봇 (FloatingChat)** | Claude Sonnet 4.6 + 4 tools + dynamic followups |

## 모니터링 대상 모델

| 리전 | 모델 |
|------|------|
| US | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5, Nova 2.0 Lite |
| Global | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5 |

## 측정 지표

| 지표 | 단위 | 설명 |
|------|------|------|
| **TTFT** | ms | 요청 전송 후 첫 번째 토큰이 도착하기까지의 시간 |
| **총 응답시간** | ms | 요청 전송부터 마지막 토큰 수신까지의 전체 소요 시간 |
| **서버 처리시간** | ms | Bedrock 서버가 보고한 내부 처리 시간 |
| **TPS** | tok/s | 초당 생성 토큰 수 (첫 토큰 이후 출력 처리량) |
| **입력/출력 토큰** | 개 | 프롬프트 소비 토큰 수 및 모델 생성 토큰 수 |

---

## 아키텍처

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  Next.js 14 │────▶│  FastAPI      │────▶│ PostgreSQL │
│  (포트 3000)│◀────│  (포트 8000)  │◀────│ (포트 5432)│
└─────────────┘ SSE └──────┬───────┘     └────────────┘
                           │
                    ┌──────▼───────┐
                    │ AWS Bedrock  │
                    │ (us-east-1)  │
                    └──────────────┘
```

- **Frontend** — Next.js 14 + React 18 + Tailwind CSS + Recharts
- **Backend** — FastAPI + SQLAlchemy ORM + SSE 스트리밍
- **Database** — PostgreSQL 16 (Docker)
- **자동 프로버** — Python 백그라운드 스레드 (5분 간격, 동시성 3)

---

## 디렉토리 구조

```
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI 엔트리포인트 + lifespan
│   ├── auto_prober.py       # 자동 프로빙 백그라운드 스레드
│   ├── prober.py            # 코어 프로브 로직 (Bedrock converse_stream)
│   ├── models.py            # SQLAlchemy ORM 모델
│   ├── schemas.py           # Pydantic 스키마
│   ├── database.py          # DB 연결 설정
│   ├── requirements.txt     # Python 의존성
│   └── routers/
│       ├── auto_probe.py    # 자동 프로빙 API (/api/auto-probe/*)
│       ├── probes.py        # 수동 프로브 API (/api/probes/*)
│       ├── results.py       # 결과 조회 API (/api/results/*)
│       ├── models.py        # 모델 목록 API (/api/models)
│       └── prompts.py       # 프롬프트 세트 API (/api/prompts/*)
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx     # 메인 페이지 (대시보드/수동 프로브 탭)
│   │   │   └── layout.tsx   # 루트 레이아웃 (한글)
│   │   ├── components/
│   │   │   ├── AutoDashboard.tsx    # 자동 프로빙 대시보드
│   │   │   ├── ModelStatusGrid.tsx  # 모델별 상태 카드 그리드
│   │   │   ├── TrendChart.tsx       # 시계열 추이 차트
│   │   │   └── ...                  # 기타 컴포넌트
│   │   ├── hooks/
│   │   │   ├── useAutoRefresh.ts    # 자동 새로고침 훅 (30초)
│   │   │   └── useProbeStream.ts    # SSE 스트리밍 훅
│   │   └── lib/
│   │       ├── api.ts       # API 클라이언트
│   │       ├── i18n.ts      # 한글 번역 사전 + 지표 설명
│   │       └── types.ts     # TypeScript 인터페이스
│   ├── package.json
│   └── tailwind.config.ts
├── docker-compose.yml       # PostgreSQL 컨테이너
├── deploy.sh                # 원클릭 배포 스크립트
├── cloudformation.yaml      # AWS CloudFormation 템플릿
└── README.md
```

---

## 사전 요구사항

- **OS**: Amazon Linux 2023 (또는 동등한 Linux)
- **Python**: 3.9+
- **Node.js**: 18+
- **Docker**: PostgreSQL 컨테이너 실행용
- **AWS 자격 증명**: Bedrock 모델 호출 권한이 있는 IAM Role 또는 자격 증명
  - 필요 권한: `bedrock:InvokeModelWithResponseStream`
  - 리전: `us-east-1`

---

## 설치 및 실행

### 방법 1: 자동 배포 (권장)

```bash
git clone <repository-url>
cd model-monitoring
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh`가 아래 작업을 순서대로 수행합니다:
1. 시스템 패키지 설치 (Python, Docker)
2. Docker로 PostgreSQL 기동
3. Backend Python 의존성 설치
4. Frontend 빌드 (`npm install` + `npm run build`)
5. systemd 서비스 등록 및 시작

### 방법 2: 수동 설치

#### 1. PostgreSQL 기동

```bash
docker compose up -d
```

PostgreSQL이 준비될 때까지 대기:

```bash
docker exec monitoring-postgres pg_isready -U postgres
```

#### 2. Backend 설치 및 실행

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

서버 시작 시 자동으로:
- DB 테이블 생성
- `is_auto` 컬럼 마이그레이션
- 자동 프로버 스레드 시작 (5분 간격)

#### 3. Frontend 설치 및 실행

```bash
cd frontend
npm install
npm run build
npm start          # 프로덕션 (포트 3000)
# 또는
npm run dev        # 개발 모드 (HMR)
```

#### 4. systemd 서비스 등록 (선택)

프로덕션 환경에서는 systemd로 관리하는 것을 권장합니다:

```bash
# /etc/systemd/system/monitor-backend.service
[Unit]
Description=Bedrock Monitor Backend (FastAPI)
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/model-monitoring/backend
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# /etc/systemd/system/monitor-frontend.service
[Unit]
Description=Bedrock Monitor Frontend (Next.js)
After=network.target monitor-backend.service

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/model-monitoring/frontend
ExecStart=/usr/bin/node node_modules/.bin/next start -p 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-backend
sudo systemctl enable --now monitor-frontend
```

---

## 접속

| 서비스 | URL |
|--------|-----|
| Frontend 대시보드 | `http://localhost:3000` |
| Backend API | `http://localhost:8000` |
| API 문서 (Swagger) | `http://localhost:8000/docs` |
| Health Check | `http://localhost:8000/api/health` |

---

## 인증

수동 프로브 기능은 로그인이 필요합니다. 대시보드(자동 프로빙)는 인증 없이 접근 가능합니다.

### 기본 계정

서버 최초 기동 시 사용자가 없으면 기본 관리자 계정이 자동 생성됩니다 (즉시 승인 상태).

> 환경변수 `JWT_SECRET_KEY`를 설정하여 토큰 서명 키를 변경하세요.

### 인증 방식

- **JWT Bearer Token** 기반 (24시간 유효)
- 로그인: `POST /api/auth/login` → `access_token` 발급
- 보호 대상 API: `/api/probes/run`, `/api/prompts` (POST/DELETE)
- 프론트엔드에서 수동 프로브 탭 클릭 시 로그인 폼이 표시됨

### 회원가입 (수동 승인 방식)

1. 사용자가 프론트엔드 또는 API로 회원가입
2. 계정은 **승인 대기 상태**(`approved=0`)로 생성
3. 관리자 이메일(`whchoi98@gmail.com`)로 **승인 요청 알림** 발송 (AWS SES)
4. 관리자가 이메일의 **"승인하기"** 버튼 클릭 → 즉시 승인 (`approved=1`)
5. 승인 전에는 로그인 불가 (403 응답)

> SES 샌드박스 환경에서는 관리자 이메일 주소가 사전에 SES에서 인증되어 있어야 합니다.

```bash
# CLI로 회원가입
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"myuser","password":"mypassword"}'
```

---

## API 엔드포인트

### 인증

| 메서드 | 경로 | 인증 | 설명 |
|--------|------|------|------|
| POST | `/api/auth/login` | - | 로그인 → JWT 토큰 발급 (승인된 계정만) |
| POST | `/api/auth/register` | - | 회원가입 (승인 대기 상태로 생성, 관리자 이메일 발송) |
| GET | `/api/auth/approve?token=` | - | 이메일 승인 링크 (관리자 클릭용) |
| GET | `/api/auth/me` | Bearer | 현재 사용자 정보 |

### 자동 프로빙

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/auto-probe/status` | 자동 프로버 상태 (실행 여부, 마지막/다음 실행 시각) |
| GET | `/api/auto-probe/latest` | 가장 최근 자동 프로빙 결과 (모델별 1건) |
| GET | `/api/auto-probe/trend?hours=24` | 시계열 데이터 (기본 24시간) |
| POST | `/api/auto-probe/trigger` | 즉시 1회 프로빙 실행 |

### 수동 프로브 (인증 필요)

| 메서드 | 경로 | 인증 | 설명 |
|--------|------|------|------|
| POST | `/api/probes/run` | Bearer | SSE 스트리밍 프로브 실행 |
| GET | `/api/models` | - | 사용 가능한 모델 목록 |

### 결과 조회

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/results` | 결과 조회 (필터: model_id, run_id, limit, offset) |
| GET | `/api/results/latest` | 최신 결과 |
| GET | `/api/results/stats` | 통계 (avg, p50, p95, p99) |

### 프롬프트 세트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/prompts` | 프롬프트 세트 목록 |
| POST | `/api/prompts` | 프롬프트 세트 생성 |
| DELETE | `/api/prompts/{id}` | 프롬프트 세트 삭제 |

---

## 운영 가이드

### 서비스 관리

```bash
# 상태 확인
sudo systemctl status monitor-backend
sudo systemctl status monitor-frontend

# 재시작
sudo systemctl restart monitor-backend
sudo systemctl restart monitor-frontend

# 로그 확인
journalctl -u monitor-backend -f
journalctl -u monitor-frontend -f
```

### 자동 프로빙 동작 확인

```bash
# 프로버 상태
curl http://localhost:8000/api/auto-probe/status

# 최신 결과
curl http://localhost:8000/api/auto-probe/latest

# 수동 트리거
curl -X POST http://localhost:8000/api/auto-probe/trigger
```

### DB 직접 조회

```bash
docker exec -it monitoring-postgres psql -U postgres -d monitoring

# 자동 프로빙 실행 횟수
SELECT COUNT(*) FROM probe_runs WHERE is_auto = 1;

# 최근 결과
SELECT model_name, ttft_ms, total_latency_ms, tps, status
FROM probe_results
ORDER BY timestamp DESC LIMIT 9;
```

### Frontend 재빌드

코드 수정 후:

```bash
cd frontend
npm run build
sudo systemctl restart monitor-frontend
```

---

## 설정 변경

| 항목 | 파일 | 변수 |
|------|------|------|
| 프로빙 주기 | `backend/auto_prober.py` | `PROBE_INTERVAL` (기본 300초) |
| 프로빙 프롬프트 | `backend/auto_prober.py` | `PROBE_PROMPT` |
| 모델 목록 | `backend/prober.py` | `AVAILABLE_MODELS` |
| DB 접속 정보 | `backend/database.py` | `DATABASE_URL` |
| 자동 새로고침 주기 | `frontend/src/hooks/useAutoRefresh.ts` | `intervalMs` (기본 30000ms) |
| JWT 서명 키 | 환경변수 `JWT_SECRET_KEY` | 기본값: `bedrock-monitor-secret-change-me` |
| 토큰 유효기간 | `backend/auth.py` | `ACCESS_TOKEN_EXPIRE_HOURS` (기본 24시간) |

<!-- harness-eval-badge:start -->
![Harness Score](https://img.shields.io/badge/harness-6.9%2F10-orange)
![Harness Grade](https://img.shields.io/badge/grade-C-orange)
![Last Eval](https://img.shields.io/badge/eval-2026--05--20-blue)
<!-- harness-eval-badge:end -->
