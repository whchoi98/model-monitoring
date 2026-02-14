# AGENT.MD — Kiro-cli Agent Context / Kiro-cli 에이전트 컨텍스트

## Project Identity / 프로젝트 정체성

**Bedrock LLM Monitor** — Real-time monitoring dashboard for AWS Bedrock LLM models measuring response speed, throughput, and reliability.

**Bedrock LLM 모니터** — AWS Bedrock LLM 모델의 응답 속도, 처리량, 안정성을 실시간으로 모니터링하는 대시보드.

**Stack / 기술 스택**: FastAPI + PostgreSQL 16 + Next.js 14 + React 18 + Tailwind CSS + AWS Bedrock

**Deployment / 배포**: EC2 (Amazon Linux 2023) + CloudFront + ALB + systemd services

---

## Architecture Overview / 아키텍처 개요

```
CloudFront → ALB → EC2
    ├── Next.js (port 3000) — Frontend + API proxy
    ├── FastAPI (port 8000) — Backend + Auto-prober daemon
    ├── PostgreSQL 16 (Docker, port 5432)
    └── AWS Bedrock (us-east-1) — converse_stream API
```

**Key Design / 핵심 설계**: 
- Frontend proxies `/api/*` to backend via Next.js rewrites / 프론트엔드는 Next.js rewrites를 통해 `/api/*`를 백엔드로 프록시
- Auto-prober runs as daemon thread inside FastAPI process (not separate service) / Auto-prober는 FastAPI 프로세스 내부의 데몬 스레드로 실행 (별도 서비스 아님)
- 9 models monitored: Claude Opus/Sonnet/Haiku 4.x + Nova 2.0 Lite (US + Global regions) / 9개 모델 모니터링
- Probing interval: 5 minutes, concurrency: 3 models at a time / 프로빙 간격: 5분, 동시성: 3개 모델

---

## Directory Map / 디렉토리 구조

```
backend/
├── main.py              # FastAPI app + lifespan (DB migration, admin seed, auto-prober start)
                         # FastAPI 앱 + lifespan (DB 마이그레이션, 관리자 생성, auto-prober 시작)
├── auto_prober.py       # AutoProber class (daemon thread, 5min interval)
                         # AutoProber 클래스 (데몬 스레드, 5분 간격)
├── prober.py            # Core probe logic (Bedrock converse_stream, SSE streaming)
                         # 코어 프로브 로직 (Bedrock converse_stream, SSE 스트리밍)
├── auth.py              # JWT + bcrypt utilities / JWT + bcrypt 유틸리티
├── models.py            # SQLAlchemy ORM (ProbeRun, ProbeResult, PromptSet, User)
├── schemas.py           # Pydantic response schemas / Pydantic 응답 스키마
├── database.py          # DB connection config / DB 연결 설정
└── routers/
    ├── auth.py          # /api/auth/* — login, register, approve, me
    ├── auto_probe.py    # /api/auto-probe/* — status, latest, trend, trigger
    ├── probes.py        # /api/probes/run — SSE streaming manual probe
    ├── results.py       # /api/results/* — query stored results / 저장된 결과 조회
    ├── models.py        # /api/models — available model list / 사용 가능한 모델 목록
    └── prompts.py       # /api/prompts/* — prompt set CRUD

frontend/src/
├── app/
│   ├── page.tsx         # Main page with tabs (Dashboard / Manual Probe)
│   │                    # 탭이 있는 메인 페이지 (대시보드 / 수동 프로브)
│   └── layout.tsx       # Root layout (lang="ko") / 루트 레이아웃
├── components/
│   ├── AutoDashboard.tsx    # Auto-probe dashboard (status + grid + charts)
│   │                        # 자동 프로브 대시보드 (상태 + 그리드 + 차트)
│   ├── ModelStatusGrid.tsx  # 3x3 model status cards / 3x3 모델 상태 카드
│   ├── TrendChart.tsx       # Recharts LineChart (TTFT / latency / TPS)
│   ├── LoginForm.tsx        # Login + register form / 로그인 + 회원가입 폼
│   └── ProbeRunner.tsx      # Manual probe execution UI / 수동 프로브 실행 UI
├── hooks/
│   ├── useAutoRefresh.ts    # 30s auto-refresh with countdown / 30초 자동 새로고침
│   └── useProbeStream.ts    # SSE streaming hook / SSE 스트리밍 훅
└── lib/
    ├── api.ts           # API client (auth token mgmt, fetch functions)
    │                    # API 클라이언트 (인증 토큰 관리, fetch 함수)
    ├── i18n.ts          # Korean translations + metric descriptions
    │                    # 한글 번역 + 메트릭 설명
    └── types.ts         # TypeScript interfaces / TypeScript 인터페이스
```

---

## Critical Constraints / 중요 제약사항

### Python 3.9 Compatibility / Python 3.9 호환성
- **DO NOT** use `X | Y` union syntax in FastAPI dependencies / FastAPI 의존성에서 `X | Y` 유니온 문법 사용 금지
- Use `Optional[X]` from `typing` instead / `typing`의 `Optional[X]` 사용
- **DO NOT** use `from __future__ import annotations` (breaks FastAPI runtime type evaluation) / `from __future__ import annotations` 사용 금지 (FastAPI 런타임 타입 평가 손상)

### bcrypt Version / bcrypt 버전
- Must be `>=4.0,<4.1` (version 5.x incompatible with passlib) / 반드시 `>=4.0,<4.1` (5.x 버전은 passlib과 비호환)

### Korean UI / 한글 UI
- All user-facing text is in Korean / 모든 사용자 화면 텍스트는 한글
- Translations in `frontend/src/lib/i18n.ts` / 번역은 `frontend/src/lib/i18n.ts`에 위치

### Auto-prober Singleton / Auto-prober 싱글톤
- Runs as daemon thread inside FastAPI process / FastAPI 프로세스 내부의 데몬 스레드로 실행
- Singleton instance at `backend/auto_prober.py` / `backend/auto_prober.py`에 싱글톤 인스턴스
- Started in `main.py` lifespan / `main.py` lifespan에서 시작

---

## Key Metrics / 핵심 메트릭

| Metric / 지표 | Unit / 단위 | Description / 설명 |
|----------------|-------------|-------------------|
| TTFT | ms | Time to first token (perceived initial response speed) / 첫 토큰까지의 시간 (체감 초기 응답 속도) |
| Total Latency / 총 응답시간 | ms | End-to-end time (client-measured) / 종단간 시간 (클라이언트 측정) |
| Server Latency / 서버 처리시간 | ms | Bedrock internal processing time / Bedrock 내부 처리 시간 |
| TPS | tok/s | Tokens per second (output throughput) / 초당 토큰 수 (출력 처리량) |
| Input Tokens / 입력 토큰 | count / 개 | Prompt token consumption / 프롬프트 토큰 소비량 |
| Output Tokens / 출력 토큰 | count / 개 | Generated response tokens / 생성된 응답 토큰 수 |

---

## Authentication Flow / 인증 플로우

1. **Register / 회원가입** → pending (approved=0) → SES email to admin (`whchoi98@gmail.com`) / 관리자에게 SES 이메일 발송
2. **Admin clicks approval link / 관리자가 승인 링크 클릭** → approved (approved=1) / 승인됨
3. **Login / 로그인** → JWT token (24h expiry) / JWT 토큰 (24시간 유효)
4. **Protected endpoints / 보호된 엔드포인트**: `/api/probes/run`, `/api/prompts` (POST/DELETE), `/api/auth/me`
5. **Public endpoints / 공개 엔드포인트**: `/api/auto-probe/*`, `/api/results/*`, `/api/models`

**Admin account / 관리자 계정**: Auto-seeded on first startup in `main.py` lifespan / 최초 기동 시 `main.py` lifespan에서 자동 생성

---

## Common Tasks / 일반 작업

### Backend Development / 백엔드 개발

```bash
# Start backend / 백엔드 시작
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Check auto-prober status / auto-prober 상태 확인
curl http://localhost:8000/api/auto-probe/status

# Trigger immediate probe / 즉시 프로브 실행
curl -X POST http://localhost:8000/api/auto-probe/trigger

# View logs (production) / 로그 확인 (프로덕션)
journalctl -u monitor-backend -f
```

### Frontend Development / 프론트엔드 개발

```bash
# Dev mode / 개발 모드
cd frontend && npm run dev

# Production build / 프로덕션 빌드
cd frontend && npm run build && npm start

# View logs (production) / 로그 확인 (프로덕션)
journalctl -u monitor-frontend -f
```

### Database / 데이터베이스

```bash
# Start PostgreSQL / PostgreSQL 시작
docker compose up -d

# Check connection / 연결 확인
docker exec monitoring-postgres pg_isready -U postgres

# Direct access / 직접 접속
docker exec -it monitoring-postgres psql -U postgres -d monitoring

# Query recent results / 최근 결과 조회
SELECT model_name, ttft_ms, total_latency_ms, tps, status
FROM probe_results ORDER BY timestamp DESC LIMIT 9;
```

### Service Management / 서비스 관리

```bash
# Restart services / 서비스 재시작
sudo systemctl restart monitor-backend
sudo systemctl restart monitor-frontend

# Check status / 상태 확인
sudo systemctl status monitor-backend
sudo systemctl status monitor-frontend
```

---

## API Endpoints Reference / API 엔드포인트 레퍼런스

### Auto Probe (Public) / 자동 프로브 (공개)
- `GET /api/auto-probe/status` — Prober status (running, last/next time) / 프로버 상태 (실행 여부, 마지막/다음 시각)
- `GET /api/auto-probe/latest` — Latest results per model / 모델별 최신 결과
- `GET /api/auto-probe/trend?hours=24` — Time-series data / 시계열 데이터
- `POST /api/auto-probe/trigger` — Trigger immediate probe cycle / 즉시 프로브 사이클 실행

### Auth / 인증
- `POST /api/auth/login` — Login → JWT token / 로그인 → JWT 토큰
- `POST /api/auth/register` — Register (pending state) / 회원가입 (승인 대기 상태)
- `GET /api/auth/approve?token=` — One-click approval link / 원클릭 승인 링크
- `GET /api/auth/me` — Current user info (auth required) / 현재 사용자 정보 (인증 필요)

### Manual Probe (Auth Required) / 수동 프로브 (인증 필요)
- `POST /api/probes/run` — SSE streaming probe execution / SSE 스트리밍 프로브 실행
- `GET /api/models` — Available model list / 사용 가능한 모델 목록

### Results (Public) / 결과 조회 (공개)
- `GET /api/results` — Query results (filter: model_id, run_id, limit, offset) / 결과 조회 (필터 지원)
- `GET /api/results/latest` — Latest results / 최신 결과
- `GET /api/results/stats` — Statistics (avg, p50, p95, p99) / 통계

### Prompt Sets / 프롬프트 세트
- `GET /api/prompts` — List prompt sets / 프롬프트 세트 목록
- `POST /api/prompts` — Create prompt set (auth required) / 프롬프트 세트 생성 (인증 필요)
- `DELETE /api/prompts/{id}` — Delete prompt set (auth required) / 프롬프트 세트 삭제 (인증 필요)

---

## Environment Variables / 환경 변수

| Variable / 변수 | Default / 기본값 | Description / 설명 |
|------------------|-------------------|-------------------|
| `JWT_SECRET_KEY` | `bedrock-monitor-secret-change-me` | JWT signing key / JWT 서명 키 |
| `PUBLIC_BASE_URL` | `https://d1ra694ytoup3r.cloudfront.net` | Base URL for approval email links / 승인 이메일 링크 베이스 URL |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/monitoring` | PostgreSQL connection string / PostgreSQL 접속 문자열 |

---

## Development Guidelines / 개발 가이드라인

### When modifying backend / 백엔드 수정 시:
1. Respect Python 3.9 type hint constraints / Python 3.9 타입 힌트 제약사항 준수
2. Use `Optional[X]` not `X | Y` in FastAPI dependencies / FastAPI 의존성에서 `Optional[X]` 사용 (`X | Y` 금지)
3. Test auto-prober behavior after changes to `auto_prober.py` or `prober.py` / `auto_prober.py` 또는 `prober.py` 변경 후 auto-prober 동작 테스트
4. Run DB migrations in `main.py` lifespan using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `main.py` lifespan에서 DB 마이그레이션 실행
5. Restart backend service / 백엔드 서비스 재시작: `sudo systemctl restart monitor-backend`

### When modifying frontend / 프론트엔드 수정 시:
1. Keep all UI text in Korean / 모든 UI 텍스트를 한글로 유지
2. Add translations to `frontend/src/lib/i18n.ts` / `frontend/src/lib/i18n.ts`에 번역 추가
3. Test SSE streaming behavior for manual probes / 수동 프로브의 SSE 스트리밍 동작 테스트
4. Verify 30s auto-refresh works correctly / 30초 자동 새로고침 정상 작동 확인
5. Build and restart / 빌드 및 재시작: `cd frontend && npm run build && sudo systemctl restart monitor-frontend`

### When adding new models / 새 모델 추가 시:
1. Update `AVAILABLE_MODELS` dict in `backend/prober.py` / `backend/prober.py`의 `AVAILABLE_MODELS` 딕셔너리 업데이트
2. Ensure model ID format matches Bedrock API / 모델 ID 형식이 Bedrock API와 일치하는지 확인
3. Test with manual probe first / 먼저 수동 프로브로 테스트
4. Verify auto-prober picks up new model / auto-prober가 새 모델을 인식하는지 확인

### When debugging / 디버깅 시:
1. Check systemd logs / systemd 로그 확인: `journalctl -u monitor-backend -f` or `journalctl -u monitor-frontend -f`
2. Check auto-prober status / auto-prober 상태 확인: `curl http://localhost:8000/api/auto-probe/status`
3. Query DB directly / DB 직접 조회: `docker exec -it monitoring-postgres psql -U postgres -d monitoring`
4. Test Bedrock connectivity / Bedrock 연결 테스트: Use manual probe UI or `POST /api/probes/run`

---

## Git Repository / Git 저장소

- Remote / 원격: `https://github.com/whchoi98/model-monitoring.git`
- Branch / 브랜치: `main`

---

## Quick Reference / 빠른 참조

**Public URL / 공개 URL**: https://d1ra694ytoup3r.cloudfront.net  
**Admin Email / 관리자 이메일**: whchoi98@gmail.com  
**DB Connection / DB 접속**: `postgresql://postgres:postgres@localhost:5432/monitoring`  
**Backend Port / 백엔드 포트**: 8000  
**Frontend Port / 프론트엔드 포트**: 3000  
**Auto-probe Interval / 자동 프로빙 간격**: 5 minutes / 5분  
**Monitored Models / 모니터링 모델**: 9 (Claude Opus/Sonnet/Haiku 4.x + Nova 2.0 Lite, US + Global)
