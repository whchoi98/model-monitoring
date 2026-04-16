# Changelog

[![English](https://img.shields.io/badge/lang-English-blue)](#english)
[![한국어](https://img.shields.io/badge/lang-한국어-red)](#한국어)

---

# English

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-04-16

### Added

- Add Claude Opus 4.7 (US and Global) to monitored models, bringing total to 13
- Add Claude Sonnet 4.6 (US and Global) to monitored models
- Add custom domain support (llm-monitor.whchoi.net)
- Add Claude Code project structure: hooks, skills, commands, agents, and test suite
- Add bilingual architecture documentation (English/Korean)
- Add developer onboarding guide and API reference
- Add project structure validation tests (49 tests)

### Changed

- Sort dashboard model cards by newest version first (Opus 4.7 > 4.6 > 4.5), grouped by region (Global first)
- Sort history panel statistics cards with the same version-first ordering
- Update architecture diagram to include CloudFront, ALB, and cross-region inference

### Fixed

- Fix Claude Opus 4.7 probe failure caused by deprecated `temperature` parameter
- Fix XSS vulnerability in approval email and approval result HTML by escaping user input
- Fix CORS misconfiguration: restrict `allow_origins` from wildcard (`*`) to explicit domains

### Security

- Remove hardcoded admin password from source code, load from `DEFAULT_ADMIN_PASSWORD` environment variable
- Remove hardcoded database URL fallback from `database.py`, require `DATABASE_URL` environment variable
- Replace weak default JWT secret key with cryptographically random 48-byte token
- Add HTML escaping for all user-controlled input rendered in HTML responses

## [1.0.0] - 2026-02-14

### Added

- Auto-probing: 5-minute interval background thread probing 9 Bedrock models with concurrency=3
- Real-time dashboard with model status grid and TTFT/latency/TPS trend charts
- Manual probe execution via SSE streaming with JWT authentication
- User authentication with email-based admin approval flow via AWS SES
- Korean/English language toggle for all UI text
- History panel with card layout, time range selector, and percentile statistics
- PostgreSQL database with SQLAlchemy ORM for probe result storage
- One-click deployment script (`deploy.sh`) with systemd service registration
- AWS CloudFormation template for infrastructure provisioning

[Unreleased]: https://github.com/whchoi98/model-monitoring/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/whchoi98/model-monitoring/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/whchoi98/model-monitoring/releases/tag/v1.0.0

---

# 한국어

이 프로젝트의 모든 주요 변경 사항은 이 파일에 기록됩니다.
이 문서는 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)를 기반으로 하며,
[Semantic Versioning](https://semver.org/spec/v2.0.0.html)을 따릅니다.

## [Unreleased]

## [1.1.0] - 2026-04-16

### Added

- Claude Opus 4.7 (US 및 Global) 모니터링 모델 추가, 총 13개로 확대
- Claude Sonnet 4.6 (US 및 Global) 모니터링 모델 추가
- 커스텀 도메인 지원 추가 (llm-monitor.whchoi.net)
- Claude Code 프로젝트 구조 추가: hooks, skills, commands, agents, 테스트 스위트
- 이중 언어 아키텍처 문서 추가 (영어/한국어)
- 개발자 온보딩 가이드 및 API 레퍼런스 추가
- 프로젝트 구조 검증 테스트 추가 (49개 테스트)

### Changed

- 대시보드 모델 카드를 최신 버전순으로 정렬 (Opus 4.7 > 4.6 > 4.5), 리전별 그룹화 (Global 먼저)
- 이력 통계 패널 카드에 동일한 버전순 정렬 적용
- 아키텍처 다이어그램에 CloudFront, ALB, 크로스 리전 추론 반영

### Fixed

- Claude Opus 4.7에서 deprecated된 `temperature` 파라미터로 인한 프로브 실패 수정
- 승인 이메일 및 승인 결과 HTML의 XSS 취약점 수정 (사용자 입력 이스케이프 처리)
- CORS 설정 오류 수정: `allow_origins`를 와일드카드(`*`)에서 명시적 도메인으로 제한

### Security

- 소스 코드에서 하드코딩된 관리자 비밀번호 제거, `DEFAULT_ADMIN_PASSWORD` 환경변수로 전환
- `database.py`에서 하드코딩된 데이터베이스 URL 폴백 제거, `DATABASE_URL` 환경변수 필수화
- 약한 기본 JWT 시크릿 키를 암호학적으로 안전한 48바이트 랜덤 토큰으로 교체
- HTML 응답에 렌더링되는 모든 사용자 입력에 HTML 이스케이프 적용

## [1.0.0] - 2026-02-14

### Added

- 자동 프로빙: 5분 간격 백그라운드 스레드로 9개 Bedrock 모델을 동시성=3으로 프로빙
- 실시간 대시보드: 모델 상태 그리드 + TTFT/응답시간/TPS 추이 차트
- SSE 스트리밍 수동 프로브 실행 (JWT 인증 필요)
- AWS SES를 통한 이메일 기반 관리자 승인 플로우의 사용자 인증 시스템
- 모든 UI 텍스트에 대한 한국어/영어 언어 토글
- 카드 레이아웃, 시간 범위 선택기, 백분위 통계가 포함된 이력 패널
- SQLAlchemy ORM을 사용한 PostgreSQL 데이터베이스 프로브 결과 저장
- systemd 서비스 등록이 포함된 원클릭 배포 스크립트 (`deploy.sh`)
- 인프라 프로비저닝을 위한 AWS CloudFormation 템플릿

[Unreleased]: https://github.com/whchoi98/model-monitoring/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/whchoi98/model-monitoring/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/whchoi98/model-monitoring/releases/tag/v1.0.0
