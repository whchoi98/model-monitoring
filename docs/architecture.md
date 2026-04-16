<p align="center">
  <kbd><a href="#english">English</a></kbd> &nbsp;|&nbsp; <kbd><a href="#한국어">한국어</a></kbd>
</p>

---

# <a id="english"></a>Architecture — Bedrock LLM Monitor

## System Overview

Bedrock LLM Monitor is a real-time dashboard that measures response speed, throughput, and reliability of AWS Bedrock LLM models. The system auto-probes 13 models every 5 minutes and presents metrics through a Next.js frontend backed by a FastAPI API server and PostgreSQL database.

## Components by Layer

### Presentation Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Dashboard UI | Next.js 14 + React 18 + Tailwind CSS | Model status grid, trend charts, manual probe UI |
| Recharts | Recharts 2.12 | TTFT / latency / TPS line charts |
| i18n | Custom (i18n.ts) | Korean/English language toggle |

### Processing Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Server | FastAPI + Uvicorn | REST API + SSE streaming |
| Auto Prober | Python daemon thread | 5-min interval probing, concurrency=3 |
| Auth System | JWT + bcrypt + SES | Registration, approval, token management |

### Storage Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Database | PostgreSQL 16 (Docker) | Probe runs, results, users, prompt sets |
| ORM | SQLAlchemy 2.0 | Schema management, query builder |

### Infrastructure Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Compute | EC2 (Amazon Linux 2023) | Application hosting |
| CDN | CloudFront | Public entry point, caching |
| Load Balancer | ALB | HTTPS termination, routing |
| AI Service | AWS Bedrock (us-east-1, ap-northeast-2) | LLM inference via converse_stream |
| Process Mgmt | systemd | Backend + frontend service lifecycle |

## Architecture Diagram

```
                    ┌──────────────────────────────┐
                    │     Internet / Users          │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │   CloudFront CDN              │
                    │   d1ra694ytoup3r.cloudfront.net│
                    │   llm-monitor.whchoi.net      │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │   Application Load Balancer   │
                    └──────────────┬───────────────┘
                                   ▼
              ┌────────────────────────────────────────┐
              │              EC2 Instance               │
              │                                        │
              │  ┌──────────────┐  ┌────────────────┐  │
              │  │  Next.js 14  │  │   FastAPI       │  │
              │  │  :3000       │──▶  :8000          │  │
              │  │  (Frontend)  │  │  (Backend)      │  │
              │  └──────────────┘  │                 │  │
              │                    │  ┌────────────┐ │  │
              │                    │  │Auto Prober │ │  │
              │                    │  │(daemon thd)│ │  │
              │                    │  └─────┬──────┘ │  │
              │                    └────┬───┼────────┘  │
              │                         │   │           │
              │                    ┌────▼───▼────┐      │
              │                    │ PostgreSQL   │      │
              │                    │ :5432        │      │
              │                    │ (Docker)     │      │
              │                    └─────────────┘      │
              └────────────────────────┬───────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │    AWS Bedrock           │
                          │  us-east-1 (US models)   │
                          │  ap-northeast-2 (Global) │
                          │  converse_stream API     │
                          └─────────────────────────┘
```

## Data Flow

```
User Request ▶ CloudFront ▶ ALB ▶ Next.js (/api/* rewrite) ▶ FastAPI ▶ PostgreSQL
                                                                  ▼
Auto Prober (5min) ▶ Bedrock converse_stream ▶ Metrics ▶ PostgreSQL ▶ Dashboard
```

## Key Design Decisions

| Decision | Why |
|----------|-----|
| Daemon thread (not separate service) | Simplifies deployment — single process manages both API and probing |
| SSE streaming for manual probes | Real-time token-by-token feedback without WebSocket complexity |
| PostgreSQL over SQLite | Production-grade concurrent writes from auto-prober threads |
| CloudFront + ALB | HTTPS termination + caching + DDoS protection |
| Global inference profiles | Seoul (ap-northeast-2) access to all Anthropic models via cross-region routing |
| Temperature exclusion for Opus 4.7 | Model-specific API compatibility — Opus 4.7 deprecated temperature param |

## Operations

See runbooks in `docs/runbooks/` for:
- Service restart procedures
- Database maintenance
- Model addition workflow
- Incident response

---

# <a id="한국어"></a>아키텍처 — Bedrock LLM 모니터

## 시스템 개요

Bedrock LLM 모니터는 AWS Bedrock LLM 모델의 응답 속도, 처리량, 안정성을 실시간으로 측정하는 대시보드입니다. 5분마다 13개 모델을 자동 프로빙하여 Next.js 프론트엔드 + FastAPI 백엔드 + PostgreSQL 구성으로 메트릭을 제공합니다.

## 레이어별 구성 요소

### 프레젠테이션 레이어
| 구성 요소 | 기술 | 역할 |
|----------|------|------|
| 대시보드 UI | Next.js 14 + React 18 + Tailwind CSS | 모델 상태 그리드, 트렌드 차트, 수동 프로브 UI |
| 차트 | Recharts 2.12 | TTFT / 레이턴시 / TPS 라인 차트 |
| 다국어 | Custom (i18n.ts) | 한국어/영어 토글 |

### 처리 레이어
| 구성 요소 | 기술 | 역할 |
|----------|------|------|
| API 서버 | FastAPI + Uvicorn | REST API + SSE 스트리밍 |
| 자동 프로버 | Python 데몬 스레드 | 5분 간격 프로빙, 동시성=3 |
| 인증 시스템 | JWT + bcrypt + SES | 회원가입, 승인, 토큰 관리 |

### 저장 레이어
| 구성 요소 | 기술 | 역할 |
|----------|------|------|
| 데이터베이스 | PostgreSQL 16 (Docker) | 프로브 실행, 결과, 사용자, 프롬프트 세트 |
| ORM | SQLAlchemy 2.0 | 스키마 관리, 쿼리 빌더 |

### 인프라 레이어
| 구성 요소 | 기술 | 역할 |
|----------|------|------|
| 컴퓨팅 | EC2 (Amazon Linux 2023) | 애플리케이션 호스팅 |
| CDN | CloudFront | 퍼블릭 진입점, 캐싱 |
| 로드 밸런서 | ALB | HTTPS 종단, 라우팅 |
| AI 서비스 | AWS Bedrock (us-east-1, ap-northeast-2) | converse_stream API를 통한 LLM 추론 |
| 프로세스 관리 | systemd | 백엔드 + 프론트엔드 서비스 라이프사이클 |

## 아키텍처 다이어그램

```
                    ┌──────────────────────────────┐
                    │     인터넷 / 사용자            │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │   CloudFront CDN              │
                    │   d1ra694ytoup3r.cloudfront.net│
                    │   llm-monitor.whchoi.net      │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │   Application Load Balancer   │
                    └──────────────┬───────────────┘
                                   ▼
              ┌────────────────────────────────────────┐
              │              EC2 인스턴스                │
              │                                        │
              │  ┌──────────────┐  ┌────────────────┐  │
              │  │  Next.js 14  │  │   FastAPI       │  │
              │  │  :3000       │──▶  :8000          │  │
              │  │  (프론트엔드) │  │  (백엔드)       │  │
              │  └──────────────┘  │                 │  │
              │                    │  ┌────────────┐ │  │
              │                    │  │자동 프로버  │ │  │
              │                    │  │(데몬 스레드)│ │  │
              │                    │  └─────┬──────┘ │  │
              │                    └────┬───┼────────┘  │
              │                         │   │           │
              │                    ┌────▼───▼────┐      │
              │                    │ PostgreSQL   │      │
              │                    │ :5432        │      │
              │                    │ (Docker)     │      │
              │                    └─────────────┘      │
              └────────────────────────┬───────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │    AWS Bedrock           │
                          │  us-east-1 (US 모델)     │
                          │  ap-northeast-2 (Global) │
                          │  converse_stream API     │
                          └─────────────────────────┘
```

## 데이터 흐름

```
사용자 요청 ▶ CloudFront ▶ ALB ▶ Next.js (/api/* rewrite) ▶ FastAPI ▶ PostgreSQL
                                                                  ▼
자동 프로버 (5분) ▶ Bedrock converse_stream ▶ 메트릭 ▶ PostgreSQL ▶ 대시보드
```

## 주요 설계 결정

| 결정 | 이유 |
|------|------|
| 데몬 스레드 (별도 서비스 아님) | 배포 단순화 — 단일 프로세스에서 API와 프로빙 모두 관리 |
| 수동 프로브에 SSE 스트리밍 | WebSocket 없이 실시간 토큰별 피드백 제공 |
| SQLite 대신 PostgreSQL | 자동 프로버 스레드의 동시 쓰기를 위한 프로덕션 등급 DB |
| CloudFront + ALB | HTTPS 종단 + 캐싱 + DDoS 방어 |
| Global 추론 프로필 | 서울(ap-northeast-2)에서 크로스 리전 라우팅으로 모든 Anthropic 모델 접근 |
| Opus 4.7 temperature 제외 | 모델별 API 호환성 — Opus 4.7에서 temperature 파라미터 deprecated |

## 운영

`docs/runbooks/`의 런북 참조:
- 서비스 재시작 절차
- 데이터베이스 유지보수
- 모델 추가 워크플로우
- 장애 대응
