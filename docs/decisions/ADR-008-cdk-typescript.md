# ADR-008 — IaC 언어로 CDK TypeScript 선택

- 상태: Accepted (Phase 0)
- 일자: 2026-05-16

## 배경

v2 IaC 언어로 Python과 TypeScript를 비교. 초기 지침은 Python이었으나 사용자 요청으로 재검토.

## 결정

**AWS CDK v2 TypeScript** 채택.

## 근거

1. **CDK 네이티브성**: CDK 자체가 TypeScript로 작성됨. 모든 신규 기능이 TS에 먼저 출시 → JSII 바인딩 lag 없음.
2. **VPC Origin·Service Connect 등 신기능 L2**: 본 v2의 핵심 기능. Python에서는 L1로 우회해야 할 가능성.
3. **타입 안전성**: `strict: true` + `noUncheckedIndexedAccess` 조합으로 `process.env.FOO!` non-null assertion 제거.
4. **프론트엔드 TS 툴체인 재사용**: `tsconfig.json`, eslint, npm 인프라가 이미 모노레포에 존재.
5. **cdk-nag aspect**: TS에서는 `Aspects.of(app).add(new AwsSolutionsChecks())` 한 줄. Python도 가능하지만 TS 샘플이 훨씬 풍부.

## 트레이드오프

- backend가 Python인데 IaC가 TS → 언어 이중화. 그러나 IaC와 앱 코드 공유 권장 안 하므로 실제 영향 미미.
- TS 학습 곡선이 필요한 운영자가 있으면 ramp-up.

## 결과

- 9개 스택, 63개 단위 테스트, cdk-nag clean 달성.
- `make verify` 7초 내 완료 (CDK 영역).
- 신기능(VPC Origin, EventBridge Scheduler L2, EcsRunFargateTask)을 모두 L2로 사용.
