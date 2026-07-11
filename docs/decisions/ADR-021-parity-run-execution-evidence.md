# ADR-021: 패리티 런 — 실행-증거(execution-evidence) 프로브 매트릭스

- **Status**: Accepted
- **Date**: 2026-07-11
- **Supersedes**: v2.10.0 스크린샷 갤러리 방식 (`/parity` 페이지의 정적 이미지 전시)
- **Related**: ADR-003 (스케줄 잡 Fargate 분리), ADR-011 (Scheduler IAM task-def wildcard), ADR-019/020 (OpenAI provider paths)

## Context

모니터링 카탈로그(28개 모델, 5개 provider path)가 커지면서 "이 모델이 이 API surface에서
이 기능을 실제로 지원하는가"를 수작업 스크린샷으로 증명하던 방식(v2.10.0)은 유지 불가능해졌다.
사용자 요구: 이미지를 보여주는 것이 아니라 **직접 실행해서** 지원 매트릭스를 만들 것,
전체 구성 대상, 주기 실행 포함.

핵심 설계 질문은 "지원 여부를 무엇으로 판정하는가"였다. HTTP 200은 판정 근거로 불충분하다 —
파라미터가 조용히 무시되거나(예: 비-reasoning 경로에 thinking 전달), 요청은 성공해도
기능이 실제로 동작하지 않는 경우가 흔하다.

## Decision

**실행-증거(execution-evidence) 모델**을 채택한다: `backend/parity/` 패키지가
모델 × surface(Converse / InvokeModel / Messages / ChatCompletions / Responses) × 피처 7종으로
팬아웃해 실제 API를 호출하고, **응답 내용의 증거 검사**를 통과했을 때만 `supported`로 판정한다.

- 증거 검사: 도구 카나리 왕복, 시스템 지시 카나리 반영, JSON 파싱+필수 키, 반복 요청의
  cached-token 카운트 > 0, 스트림 델타 ≥ 2 (`engine.py` 순수 함수 — 단위 테스트 대상)
- 오류 분류: provider의 "깨끗한 미지원 거부" 시그니처(`unsupported_parameter` 등) →
  `unsupported`, 그 외 오류·증거 실패 → `broken`, 해당 없음(비-reasoning 모델의 reasoning) → `skipped`
- 저장: `parity_runs` / `parity_results` (run당 결과 + 증거 JSON + latency + error)
- 실행: 12시간 주기 EventBridge rate(12 hours) — v2.12.0에서 일 1회에서 단축 → 전용 Fargate one-shot (`parity_runner --once`,
  ADR-003과 동일 패턴) + `/api/parity/trigger`(JWT)의 backend 내 스레드 수동 실행
- UI: `/parity` 매트릭스 + 셀 클릭 시 증거 모달 (`/api/parity/evidence`)

## Consequences

- (+) 지원 매트릭스가 항상 실측 기반 — 신규 모델은 `AVAILABLE_MODELS` 순회로 자동 편입
- (+) 실제 격차 발견: Mantle ChatCompletions 전면 미지원(Responses만), GPT 5.4 reasoning_tokens 미보고,
  Fable 5 캐싱의 surface별 차이 등
- (−) 프로브 자체 결함이 오판을 만들 수 있음 — 실제로 run #1에서 `max_tokens=64` 절단이
  structured_output 전량 false-Broken을 유발, v2.11.1에서 피처별 토큰 예산(`max_tokens_for`)으로 수정.
  **Broken 판정은 증거(response_snippet)로 프로브/모델 어느 쪽 결함인지 확인 후 신뢰할 것**
- (−) 12시간마다 실런 비용 발생 (호출당 max_tokens 256~2048로 상한, caching 피처만 2회 호출)
