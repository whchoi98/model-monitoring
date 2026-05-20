# ADR-011: EventBridge Scheduler IAM — Task Definition Wildcard

- **Status**: Accepted
- **Date**: 2026-05-20
- **Deciders**: Platform team

## Context / 배경

CDK가 생성한 EventBridge Scheduler role의 `ecs:RunTask` Resource는 **특정 task definition revision에 pinned** 되어 있었다:

```json
{
  "Action": "ecs:RunTask",
  "Resource": [
    "arn:aws:ecs:ap-northeast-2:...:task-definition/...AutoProberTaskDef...:4",
    "arn:aws:ecs:ap-northeast-2:...:task-definition/...InsightsTaskDef...:4"
  ]
}
```

v2.1.0 deploy 중 autoprober task definition을 새 revision (`:7`)으로 등록 + Schedule target을 새 revision arn으로 변경 → **EventBridge가 fire 시 RunTask 권한 거부로 silent fail**.

증상:
- `/api/auto-probe/status`의 `last_run_time`이 ~2시간 전 (autoprober 정지)
- 대시보드 카드/그래프 비어 있음
- EventBridge CloudWatch metric (`InvocationAttemptCount`, `TargetErrorCount`) 모두 empty — failure가 metric에도 잡히지 않음 (매우 추적 어려움)
- ECS task list (STOPPED filter)에 autoprober task가 0개

## Decision / 결정

**Scheduler role의 `ecs:RunTask` Resource를 task definition family `:*` wildcard로 변경**.

```json
"Resource": [
  "arn:aws:ecs:ap-northeast-2:...:task-definition/...AutoProberTaskDef...:*",
  "arn:aws:ecs:ap-northeast-2:...:task-definition/...InsightsTaskDef...:*"
]
```

이렇게 하면 새 revision register 시 IAM 정책 update 없이 schedule이 즉시 새 revision 사용 가능.

추가:
- EventBridge Schedule에 **Dead Letter Queue** (SQS) 설정 권장 — silent fail 방지.
- ECS Run-Task 시 `enable-execute-command` 활성화 권장 — 디버깅 가능.

## Consequences / 결과

**Pros**:
- 새 task def revision 배포 시 IAM 정책 동기화 부담 제거
- Schedule이 항상 가장 최근 revision으로 트리거 가능
- CDK update 없이 deploy 가능

**Cons**:
- 같은 family 안에서 권한 범위가 더 넓어짐 (그러나 task def family 자체가 신뢰 boundary)
- DLQ 추가 시 비용 미미하지만 발생

## Implementation / 구현

CDK code의 `SchedulerRoleForTarget*` policy statement 수정 — Resource를 family `:*`로. 또는 CDK가 만든 정책을 IAM 콘솔/CLI로 in-place patch.

수동 patch (incident 응대용):
```bash
aws iam put-role-policy --role-name <SchedulerRoleForTarget*> \
  --policy-name <DefaultPolicy> \
  --policy-document file://new-policy.json
```

## References

- v2.1.0 incident: 2026-05-20 autoprober 2시간 정지
- 관련: ADR-010 (Immutable tag policy)
