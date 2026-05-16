# Runbook — 롤백 절차

## 시나리오별 롤백

### A. 코드 회귀 — 컨테이너 이미지만 되돌리기

ECS Fargate Service의 image tag만 변경하면 됨. ECR이 `IMMUTABLE` tag이라 직전 tag를 그대로 사용 가능.

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
PREV_TAG="v2.0.0"   # 직전 정상 tag

# Task Definition의 image를 PREV_TAG로 가리키도록 새 revision 등록 후 service 갱신.
# CDK에서는 imageTag를 'latest'로 고정해서 ECR 이미지의 디지스트만 추적 — 직접 tag 이동은 콘솔/CLI.

aws ecs update-service \
  --cluster bedrock-monitor --service backend \
  --task-definition $(aws ecs describe-task-definition \
       --task-definition backend \
       --query "taskDefinition.taskDefinitionArn" --output text) \
  --force-new-deployment
```

**ECS circuit breaker가 자동 롤백을 시도**한다. 새 task가 N번 fail하면 직전 안정 revision으로 자동 복귀.

### B. 인프라 회귀 — CDK 롤백

CloudFormation에 의존. 마지막 성공 deploy로 stack rollback:

```bash
aws cloudformation continue-update-rollback --stack-name BedrockMonitor-AppServices
```

또는 git에서 직전 커밋 checkout 후:

```bash
git checkout <prev-commit>
cd cdk
npx cdk deploy --all -c albCertificateArn=... -c alarmEmail=...
```

CDK가 desired vs current 상태 diff를 계산해 변경분만 되돌림.

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
MEMORY_ID=$(aws ssm get-parameter \
  --name /bedrock-monitor/agentcore-memory-id \
  --query "Parameter.Value" --output text)

# 특정 actor의 모든 event 삭제 — boto3 스크립트 권장.
aws bedrock-agentcore list-sessions --memory-id $MEMORY_ID
# 그 후 각 session의 events를 delete_event로 정리.
```

영구 DELETE는 30일 자동 만료(`eventExpiryDuration=30`)에 의해 자연 해결되기도 함.

### E. 전체 롤백 (긴급)

`backend` / `frontend` ECS service desiredCount=0으로 즉시 중단:

```bash
aws ecs update-service --cluster bedrock-monitor --service backend  --desired-count 0
aws ecs update-service --cluster bedrock-monitor --service frontend --desired-count 0
```

CloudFront 단에서 `Disabled` 토글로 전체 차단 가능 (사용자에게 503 반환).

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
