# Runbook — v2 배포 절차

## 0. 사전 요구사항

1. **AWS CLI 자격** — 대상 계정/리전에 admin 권한.
2. **CDK Bootstrap** — `cdk bootstrap aws://ACCOUNT/us-east-1`이 완료된 계정.
3. **ACM Private CA 인증서** — ALB internal listener용 (ADR-005). cert ARN 확보.
4. **Docker / Node 20 / Python 3.11** — 로컬 빌드 환경.

## 1. 로컬 검증

```bash
make verify
```

CDK lint + typecheck + 63 tests + cdk-nag clean + ruff + pytest 7 + frontend tsc 모두 PASS 확인.

## 2. 컨테이너 이미지 빌드 + ECR push

CDK가 ECR repo를 만든 직후 image push가 필요. 첫 deploy는 두 단계:

> **중요 (ADR-010)**: `:latest` tag는 **로컬 dev 전용**. Production task definition에는 **immutable tag (`v<timestamp>` 또는 `v<git-sha>`)** 만 사용. `:latest`로 push하면 Docker layer dedupe + ECS image cache 콤보로 새 코드가 production에 silent 반영 안 되는 사고가 발생.

```bash
# (a) ECR repo만 먼저 생성.
cd cdk && npx cdk deploy BedrockMonitor-Cluster

# (b) 로그인 → 빌드 → push. 항상 immutable tag 사용.
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-northeast-2
TAG="v$(date +%s)"   # 또는 v$(git rev-parse --short HEAD)
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

# Backend — 2026-05-20부터 ECR repository: bedrock-monitor-backend-v2 사용 (ADR-018)
docker build --no-cache --pull --platform linux/arm64 \
  -t bedrock-monitor-backend:$TAG backend/
docker tag bedrock-monitor-backend:$TAG \
  $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG

# Frontend
docker build --no-cache --pull --platform linux/arm64 \
  -t bedrock-monitor-frontend:$TAG frontend/
docker tag bedrock-monitor-frontend:$TAG \
  $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG
```

### 2-1. Task Definition을 새 tag로 update (incremental redeploy)

`:latest`를 사용하지 않으므로 push 후 task definition을 새 revision으로 register하는 단계가 추가된다:

```bash
# Backend
aws ecs describe-task-definition --task-definition BedrockMonitorAppServicesBackendTaskDef* \
  --region $REGION > /tmp/td-be.json
python3 -c "
import json
td = json.load(open('/tmp/td-be.json'))['taskDefinition']
out = {k:v for k,v in td.items() if k in ['family','containerDefinitions','volumes','taskRoleArn','executionRoleArn','networkMode','cpu','memory','requiresCompatibilities','runtimePlatform']}
for c in out['containerDefinitions']:
    if 'bedrock-monitor-backend' in c.get('image',''):
        c['image'] = '${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/bedrock-monitor-backend:${TAG}'
open('/tmp/td-be-new.json','w').write(json.dumps(out))
"
BE_ARN=$(aws ecs register-task-definition --region $REGION \
  --cli-input-json file:///tmp/td-be-new.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)
aws ecs update-service --cluster bedrock-monitor --service backend \
  --task-definition "$BE_ARN" --region $REGION

# Autoprober schedule도 동일하게 (별도 Fargate Task)
aws ecs describe-task-definition --task-definition BedrockMonitorSchedulerAutoProberTaskDef* \
  --region $REGION > /tmp/td-ap.json
# ... (위와 동일하게 image 교체 + register) ...
AP_ARN=...
aws scheduler get-schedule --name "<AutoProberSchedule>" --region $REGION > /tmp/sched.json
python3 -c "
import json
d = json.load(open('/tmp/sched.json'))
d['Target']['EcsParameters']['TaskDefinitionArn'] = '$AP_ARN'
for k in ('Arn','CreationDate','LastModificationDate'): d.pop(k,None)
open('/tmp/sched-upd.json','w').write(json.dumps(d))
"
aws scheduler update-schedule --region $REGION --cli-input-json file:///tmp/sched-upd.json
```

> **ADR-011 주의**: Scheduler IAM role의 `ecs:RunTask` Resource가 task def revision pinned면 위 schedule update가 silent fail. 정책의 Resource를 task def family `:*` wildcard로 유지할 것.

## 3. 전체 CDK 배포

```bash
cd cdk
npx cdk deploy --all \
  -c albCertificateArn="arn:aws:acm:us-east-1:ACCOUNT:certificate/UUID" \
  -c alarmEmail="ops@example.com"
```

`-c existingVpcId=vpc-xxx -c appSubnetIds=... -c dataSubnetIds=...` 옵션으로 기존 VPC 재사용 가능.

## 4. 배포 후 수동 설정

### 4-1. JWT_SECRET_KEY 실 값으로 교체

```bash
NEW_SECRET=$(openssl rand -base64 48)
aws ssm put-parameter \
  --name /bedrock-monitor/jwt-secret-key \
  --value "$NEW_SECRET" \
  --type SecureString --overwrite
```

backend Fargate Service를 한 번 force-deploy해서 새 값 로드:

```bash
aws ecs update-service \
  --cluster bedrock-monitor \
  --service backend \
  --force-new-deployment
```

### 4-2. SES sender 검증 (회원가입 승인 이메일)

`backend/auth.py`의 `ADMIN_EMAIL`이 SES sandbox에서 verified여야 한다.

### 4-3. SNS 알림 구독 확인

`alarmEmail` 컨텍스트 지정 시 해당 주소로 SNS 구독 확인 이메일 발송 → 클릭.

## 5. 동작 확인

```bash
# CloudFront 도메인은 EdgeStack output 또는 콘솔에서 확인.
CF_DOMAIN=$(aws cloudformation describe-stacks \
  --stack-name BedrockMonitor-Edge \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomain'].OutputValue" \
  --output text)

# 헬스 체크.
curl -i "https://$CF_DOMAIN/api/health"

# 첫 자동 프로빙 결과 (5분 후).
curl -i "https://$CF_DOMAIN/api/auto-probe/latest"
```

## 6. 후속 배포 (코드만 변경 시)

```bash
make build              # backend + frontend 이미지 재빌드
# 위 step 2-(b) 동일하게 push
aws ecs update-service --cluster bedrock-monitor --service backend  --force-new-deployment
aws ecs update-service --cluster bedrock-monitor --service frontend --force-new-deployment
```

인프라 변경 없으면 `cdk deploy`는 생략.
