# ADR-022: Bedrock Mantle /anthropic Messages surface — SigV4 파생 bearer + IAM 액션 체인

- **Status**: Accepted
- **Date**: 2026-07-12
- **Related**: ADR-019/020 (provider path ADR 패턴), ADR-021 (패리티 엔진)

## Context

패리티 런에 Bedrock Mantle의 Anthropic Messages 호환 엔드포인트
(`https://bedrock-mantle.<region>.api.aws/anthropic`)를 6번째 surface(`messages_mantle`)로
추가했다. 이 경로는 OpenAI Mantle 경로(ADR-019, ABSK 장기 키)와 달리 어떤 인증을 쓸지가
설계 질문이었다.

## Decision

`aws-bedrock-token-generator`의 **SigV4 파생 단기 bearer**를 사용한다 (ABSK 키 재사용 대신).
리전은 `MANTLE_ANTHROPIC_REGION` env(기본 ap-northeast-1)로 제어하고, 모델 id는
프로파일 접두사를 제거한 FM id(`mantle_fm_id()`)를 쓴다. `does not exist`(리전 미서빙),
본문 없는 404(엔드포인트 미제공)는 깨끗한 미지원으로 분류한다.

## Consequences

- (+) 키 관리 불필요 — 태스크 롤 자격으로 어느 리전이든 즉시 bearer 생성
- (−) **bearer가 IAM을 그대로 타므로 태스크 롤에 액션 체인이 필요** (403 2단계로 실측 발견):
  `bedrock-mantle:CreateInference`(project/*) → `bedrock-mantle:CallWithBearerToken`(*) →
  기능별 추가 액션(`bedrock-mantle:CountTokens` 등). cdk-nag IAM5 suppression appliesTo에
  리소스 병기 필수. backend 롤(수동 트리거)에도 동일 권한 필요.
- 실측 발견 (2026-07-11): ap-northeast-1 Mantle /anthropic은 실존하나 Opus 4.7/4.8만 서빙
  (basic·streaming·시스템 지시·도구·구조화 출력·캐싱 6피처 Supported), 그 외 모델 미서빙.
