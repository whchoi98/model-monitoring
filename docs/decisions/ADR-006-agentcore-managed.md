# ADR-006 — AgentCore Memory만 사용, Runtime은 이연

- 상태: Accepted (Phase 5)
- 일자: 2026-05-16

## 배경

v2 초안은 "AgentCore Runtime 관리형 사용"이었다. Phase 5에 진입해 보니 `CfnRuntime` L1은 `agentRuntimeArtifact.containerConfiguration.containerUri`로 **사용자가 직접 작성한 agent 컨테이너 이미지**를 요구. 단순히 Sonnet 4.6을 호출하는 매니지드 서비스가 아니라 "Strands SDK 또는 AgentCore SDK가 담긴 컨테이너 호스팅 런타임"이다.

## 결정

Phase 5에서는 **AgentCore Memory만** 도입하고 Runtime은 차후 Phase로 이연.

- backend ECS 컨테이너가 boto3로 Bedrock InvokeModel + AgentCore Memory를 직접 호출.
- `BackendTaskRole`에 `bedrock-agentcore:CreateEvent/ListEvents/...` 권한 부여.
- 챗봇 흐름은 backend가 직접 tool_use loop를 돌림 — Strands SDK 의존 없음.

## 결과

- 단기 구현 비용 ~1일 절감 (agent 컨테이너 + Dockerfile + ECR 추가 불필요).
- 동일 UX 제공 — 사용자 관점에서 차이 없음.
- backend가 자체적으로 tool 함수를 들고 있어 latency 1 hop 절감.

## 트레이드오프

- AgentCore Runtime의 매니지드 토큰 추적 / scaling / dashboards 미사용.
- 향후 Runtime 도입 시 backend의 chat router 일부를 agent 컨테이너로 옮기는 마이그레이션 필요.

## 후속

- Runtime 도입 시 별도 Phase (5b) 신설: agent 컨테이너 작성 → ECR → CfnRuntime → 챗봇 라우터가 Runtime invoke로 전환.
