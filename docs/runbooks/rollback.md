# Runbook — 롤백 절차

## 시나리오별 롤백

### A. 코드 회귀 — 컨테이너 이미지만 되돌리기

운영 task def는 CDK context로 주입한 digest 고정 URI(`<repo>:<tag>@sha256:<digest>`, `cdk/lib/constructs/pinned-image.ts`)를
쓴다. 롤백은 직전 정상 이미지의 tag@digest로 AppServices + Scheduler를 다시 배포하는 것이다. backend 저장소
`bedrock-monitor-backend-v2`는 CDK 밖에서 만든 IMMUTABLE 저장소라 push된 tag가 다른 이미지로 바뀌지 않는다. CDK가 관리하는
`bedrock-monitor-frontend`(와 옛 `bedrock-monitor-backend`)는 MUTABLE이라 tag가 아니라 digest가 기준이고, lifecycle이 이미지를
최근 10개만 남기므로 오래된 frontend 이미지는 없을 수 있다. 릴리스마다 backend와 frontend는 같은 `v<epoch>` tag로 push된다.

**A-1. 직전 정상 이미지 찾기**

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-northeast-2
# 지금 운영 중인 image (backend, frontend 순서)
for s in backend frontend; do
  TD=$(aws ecs describe-services --cluster bedrock-monitor --services $s --region $REGION \
    --query 'services[0].taskDefinition' --output text)
  aws ecs describe-task-definition --task-definition "$TD" --region $REGION \
    --query 'taskDefinition.containerDefinitions[0].image' --output text
done
# 최근 push 순 이미지 (tag, digest, push 시각) — 운영 중인 tag 바로 앞의 정상 tag를 고른다
for r in bedrock-monitor-backend-v2 bedrock-monitor-frontend; do
  aws ecr describe-images --repository-name $r --region $REGION \
    --query 'reverse(sort_by(imageDetails,&imagePushedAt))[:5].[imageTags[0],imageDigest,imagePushedAt]' --output text
done
```

**A-2. 권장 — digest 고정 CDK 재배포** (backend·frontend 서비스와 스케줄 태스크 6개가 함께 돌아간다)

```bash
PREV_TAG="v<epoch>"   # ← A-1에서 고른 직전 정상 tag로 바꾼다
BE_PREV=$(aws ecr describe-images --repository-name bedrock-monitor-backend-v2 --image-ids imageTag=$PREV_TAG \
  --region $REGION --query 'imageDetails[0].imageDigest' --output text)
FE_PREV=$(aws ecr describe-images --repository-name bedrock-monitor-frontend --image-ids imageTag=$PREV_TAG \
  --region $REGION --query 'imageDetails[0].imageDigest' --output text)
cd cdk
npx cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never \
  -c backendImage="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$PREV_TAG@$BE_PREV" \
  -c frontendImage="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$PREV_TAG@$FE_PREV"
```

되돌리는 릴리스가 CDK(env, 스케줄, IAM)도 바꿨다면 직전 릴리스 git tag의 `cdk/`에서 실행한다
(예: `git worktree add /tmp/rb vX.Y.Z && cd /tmp/rb/cdk && npm ci`). 현재 CDK로 배포하면 image만 돌아가고 env·스케줄은 새 값 그대로다.

**A-3. 빠른 경로 — 서비스만 이전 revision으로** (스케줄 태스크 6개는 되돌아가지 않는다)

CloudFormation은 task def를 교체할 때 자신이 만든 옛 revision을 INACTIVE로 등록 해제하고(수동 등록한 revision은 ACTIVE로
남는다), INACTIVE revision으로는 `update-service`를 할 수 없다. 그래서 ACTIVE 목록에서 고르고, 직전 image의 revision이 없으면 A-2를 쓴다.

```bash
TD=$(aws ecs describe-services --cluster bedrock-monitor --services backend --region $REGION \
  --query 'services[0].taskDefinition' --output text)
FAMILY=$(echo "$TD" | sed 's#.*/##; s#:[0-9]*$##')   # 예: BedrockMonitorAppServicesBackendTaskDef81C53F03
aws ecs list-task-definitions --family-prefix "$FAMILY" --status ACTIVE --sort DESC --max-items 5 \
  --region $REGION --query 'taskDefinitionArns'
REV=<previous revision>   # ← 위 목록에서 고른 revision 번호
aws ecs describe-task-definition --task-definition "$FAMILY:$REV" --region $REGION \
  --query 'taskDefinition.containerDefinitions[0].image' --output text   # 직전 정상 image인지 확인
aws ecs update-service --cluster bedrock-monitor --service backend --region $REGION \
  --task-definition "$FAMILY:$REV"
# frontend도 같은 방식 (--services frontend / --service frontend)
```

이 경로는 CDK 상태와 어긋나므로 다음 CDK 배포가 context 이미지로 덮어쓴다. 스케줄 태스크만 되돌려야 하면
[deploy.md §2-1](./deploy.md)의 절차(image 교체 revision 등록 → `get-schedule` → `TaskDefinitionArn` 교체 → `update-schedule`)를
직전 image로 6개 스케줄에 적용한다(v2.30.0 PricingSync 포함).

**ECS circuit breaker**(`circuitBreaker: { rollback: true }`)는 새 task가 기동이나 헬스체크에 계속 실패할 때만 직전 안정
배포로 자동 복귀한다. task가 정상 기동하는 코드 회귀(기능 버그, 잘못된 값)는 위 절차로 직접 되돌린다.

### B. 인프라 회귀 — CDK 롤백

CloudFormation은 실패한 update를 기본으로 자동 롤백한다. 명령이 필요한 경우는 두 가지다:

```bash
REGION=ap-northeast-2
aws cloudformation describe-stacks --stack-name BedrockMonitor-AppServices --region $REGION \
  --query 'Stacks[0].StackStatus' --output text
# UPDATE_IN_PROGRESS인 update를 중단하고 되돌릴 때
aws cloudformation cancel-update-stack --stack-name BedrockMonitor-AppServices --region $REGION
# UPDATE_ROLLBACK_FAILED에 멈췄을 때만 (다른 상태에서는 오류)
aws cloudformation continue-update-rollback --stack-name BedrockMonitor-AppServices --region $REGION
```

또는 git에서 직전 커밋 checkout 후 되돌릴 스택만 배포한다. 이미지 context는 **현재 운영** URI(A-1 첫 루프 출력)를 넘긴다 —
빠뜨리면 AppServices/Scheduler가 `:latest`로 synth되어 서비스가 옛 이미지로 돌아간다.

```bash
git checkout <prev-commit>
cd cdk
npx cdk deploy --exclusively <되돌릴 스택…> --require-approval never \
  -c backendImage=<현재 운영 backend URI> -c frontendImage=<현재 운영 frontend URI>
# BedrockMonitor-Observability를 포함하면 -c alarmEmail=…도 넘긴다 (빼면 SNS 이메일 구독이 삭제된다)
```

CDK가 desired vs current 상태 diff를 계산해 변경분만 되돌림 — 같은 인자로 `npx cdk diff`를 먼저 확인한다.

### C. DB 데이터 손상

RDS 자동 백업 (7일 보존)으로 point-in-time restore.

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier <current> \
  --target-db-instance-identifier <restored> \
  --restore-time 2026-05-16T08:00:00Z
```

복구 후 `restored` 인스턴스에 backend가 가리키도록 Secrets Manager의 host 필드 갱신 → ECS service force-redeploy.

### D. AgentCore Memory 초기화

대화 컨텍스트 오염 시:

```bash
MEMORY_ID=$(aws ssm get-parameter --region ap-northeast-2 \
  --name /bedrock-monitor/agentcore-memory-id \
  --query "Parameter.Value" --output text)

# 특정 actor의 모든 event 삭제 — boto3 스크립트 권장. list-sessions는 --actor-id가 필수다.
aws bedrock-agentcore list-actors --memory-id $MEMORY_ID --region ap-northeast-2
aws bedrock-agentcore list-sessions --memory-id $MEMORY_ID --actor-id <actor-id> --region ap-northeast-2
# 그 후 각 session의 events를 delete_event로 정리.
```

영구 DELETE는 30일 자동 만료(`eventExpiryDuration=30`)에 의해 자연 해결되기도 함.

### E. 전체 롤백 (긴급)

`backend` / `frontend` ECS service desiredCount=0으로 즉시 중단:

```bash
REGION=ap-northeast-2
aws ecs update-service --cluster bedrock-monitor --service backend  --desired-count 0 --region $REGION
aws ecs update-service --cluster bedrock-monitor --service frontend --desired-count 0 --region $REGION
```

서비스를 멈춰도 스케줄 태스크 6개(autoprober, insights, parityrun, gptbench, featuresverify, pricingsync)는 계속 돈다(pricingsync를 뺀 5개는 모델 호출 비용 발생 — pricingsync는 공식 단가 읽기만 한다).
함께 멈추려면 스케줄을 DISABLED로 바꾼다 (재개는 같은 명령에서 `'DISABLED'` → `'ENABLED'`):

```bash
for n in $(aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION \
    --query 'Schedules[].Name' --output text); do
  aws scheduler get-schedule --name "$n" --region $REGION --output json | python3 -c "
import json, sys
d = json.load(sys.stdin)
d['State'] = 'DISABLED'
for k in ('Arn', 'CreationDate', 'LastModificationDate'): d.pop(k, None)
print(json.dumps(d))" > /tmp/sched-state.json
  aws scheduler update-schedule --region $REGION --cli-input-json file:///tmp/sched-state.json
done
```

CloudFront 단에서 `Disabled` 토글로 전체 차단 가능 (사용자에게 503 반환).

## 배포 전 롤백 포인트 기록

배포 직전에 서비스 2개와 스케줄 태스크 6개가 쓰는 task def와 image를 기록해 둔다. 롤백 기준은 image(tag@digest)다 —
task def revision은 다음 CDK 배포에서 INACTIVE가 되면 `update-service`에 쓸 수 없다(A-3). 기록한 image로 A-2를 실행한다.

```bash
REGION=ap-northeast-2
# 서비스 (backend, frontend)
for s in backend frontend; do
  TD=$(aws ecs describe-services --cluster bedrock-monitor --services $s --region $REGION \
    --query 'services[0].taskDefinition' --output text)
  echo "$s $TD $(aws ecs describe-task-definition --task-definition "$TD" --region $REGION \
    --query 'taskDefinition.containerDefinitions[0].image' --output text)"
done
# 스케줄 태스크 6개 (autoprober, insights, parityrun, gptbench, featuresverify, pricingsync) — 스케줄이 가리키는 revision 기준
for n in $(aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION \
    --query 'Schedules[].Name' --output text); do
  TD=$(aws scheduler get-schedule --name "$n" --region $REGION \
    --query 'Target.EcsParameters.TaskDefinitionArn' --output text)
  echo "$n $TD $(aws ecs describe-task-definition --task-definition "$TD" --region $REGION \
    --query 'taskDefinition.containerDefinitions[0].image' --output text)"
done
```

### 기록 보관 (역사 — 롤백에 쓰지 말 것)

아래 두 항목은 2026-07-09 당시 기록이다. 적힌 revision 중 일부(예: `BedrockMonitorAppServicesBackendTaskDef81C53F03:36`)는 이후
CDK 배포로 INACTIVE가 되어 `update-service`에 쓸 수 없고, ACTIVE로 남은 것도 v2.7.0 이전 코드와 env다. 스케줄 태스크도 당시
2개(autoprober, insights)만 있었고, 끝의 `cdk deploy BedrockMonitor-Edge`는 이미지 context가 없는 옛 형태다(§B 참고).
롤백은 위 절차를 쓴다.

#### v2.7.0 배포 전 상태 (2026-07-09 기록)

```bash
REGION=ap-northeast-2
aws ecs update-service --cluster bedrock-monitor --service backend --region $REGION \
  --task-definition BedrockMonitorAppServicesBackendTaskDef81C53F03:36
aws ecs update-service --cluster bedrock-monitor --service frontend --region $REGION \
  --task-definition BedrockMonitorAppServicesFrontendTaskDefB3083787:22
# autoprober 스케줄: BedrockMonitorSchedulerAutoProberTaskDefF8B95086:24
# insights 스케줄:   BedrockMonitorSchedulerInsightsTaskDef9396CE7C:17
# v2.6.2 이미지: backend-v2@sha256:8ec3ff6d… / frontend@sha256:41383b05…
# 주의: v2.7.0의 probe_results_hourly 테이블·집계 데이터는 롤백 시에도 무해 (읽는 곳 없음)
```


#### v2.6.2 배포 전 상태 (2026-07-09 기록, v2.6.1)

문제 시 아래 task definition revision으로 즉시 복귀:

```bash
REGION=ap-northeast-2
aws ecs update-service --cluster bedrock-monitor --service backend --region $REGION \
  --task-definition BedrockMonitorAppServicesBackendTaskDef81C53F03:33
aws ecs update-service --cluster bedrock-monitor --service frontend --region $REGION \
  --task-definition BedrockMonitorAppServicesFrontendTaskDefB3083787:21
# autoprober 스케줄: BedrockMonitorSchedulerAutoProberTaskDefF8B95086:23
# insights 스케줄:   BedrockMonitorSchedulerInsightsTaskDef9396CE7C:16
```

| 항목 | v2.6.1 (배포 전) |
|------|------------------|
| backend image | `bedrock-monitor-backend-v2@sha256:ad07f0238d4db5a57bc611488e3fb18ee29e2e3eeaac048f7d6ca4103272dfa6` |
| frontend image | `bedrock-monitor-frontend@sha256:e0faa1b1c7a78a61cec5524c552d28b547173d03f1f58da180dd54613661aa62` |

주의: v2.6.2가 생성한 DB 인덱스 3종(`ix_probe_runs_auto_status_created`, `ix_probe_results_run_id`,
`ix_probe_results_timestamp`)은 롤백 시에도 무해하므로 DROP 불필요. CloudFront `/api/auto-probe/*`
behavior 롤백은 `git revert` 후 `cdk deploy BedrockMonitor-Edge`.

## 알람 응답

각 알람의 대응 방안:

| 알람 | 1차 조치 |
|------|----------|
| Alb5xxRatioAlarm | ECS task logs `/ecs/backend` 확인, 최근 deploy 회귀 확인 |
| AlbLatencyAlarm | RDS Performance Insights, ECS task CPU/Memory 확인 |
| BackendDownAlarm / FrontendDownAlarm | ECS service event log, task stopped reason 확인 |
| RdsCpuAlarm | RDS Performance Insights → top SQL 확인, 쿼리 최적화 또는 인스턴스 업그레이드 |
| RdsStorageAlarm | `aws rds modify-db-instance --allocated-storage <NEW>` 즉시 확장 |
| RdsConnectionsAlarm | backend AS max 줄이거나 connection pool 축소 |
