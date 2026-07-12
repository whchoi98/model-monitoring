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

CDK lint + typecheck + 63 tests + cdk-nag clean + ruff + pytest 23 + frontend tsc 모두 PASS 확인.

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

# Frontend — ⚠️ RUM build args 누락 시 RUM 꺼진 이미지가 나감 (v2.16.5, .env.example 참고)
docker build --no-cache --pull --platform linux/arm64 \
  --build-arg NEXT_PUBLIC_RUM_ENDPOINT="$NEXT_PUBLIC_RUM_ENDPOINT" \
  --build-arg NEXT_PUBLIC_RUM_API_KEY="$NEXT_PUBLIC_RUM_API_KEY" \
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

# Autoprober / Insights / ParityRun schedule도 동일하게 (각각 별도 Fargate Task — backend image 공용)
# ParityRun (v2.11.0): family BedrockMonitorSchedulerParityRunTaskDef*, schedule rate(12 hours)
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

> ⚠️ **CDK 배포 시 이미지 context 필수 (2026-07-09 도입)**: 모든 `cdk deploy`에
> 현재 운영 중인 이미지 digest URI를 context로 주입해야 한다. 미주입 시 legacy `:latest`
> fallback으로 synth되며(경고 출력), 그대로 배포하면 서비스가 옛 이미지로 되돌아간다
> (2026-07-09 실사고 — Edge만 배포해도 의존 스택 AppServices가 함께 갱신됨).
>
> ```bash
> # 현재 운영 digest 확인
> aws ecs describe-services --cluster bedrock-monitor --services backend frontend \
>   --region ap-northeast-2 --query 'services[].taskDefinition' --output text
> # (task def에서 image URI 확인 후)
> npx cdk deploy <스택> --require-approval never \
>   -c backendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2@sha256:... \
>   -c frontendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-frontend@sha256:...
> ```
>
> 대체 도메인(`llm-monitor.whchoi.net`)과 ACM cert도 CDK(edge-stack)가 소유한다 —
> 콘솔에서 수동 추가한 배포판 설정은 다음 cdk deploy 때 제거되므로 금지.

```bash
cd cdk
npx cdk deploy --all \
  -c albCertificateArn="arn:aws:acm:us-east-1:ACCOUNT:certificate/UUID" \
  -c alarmEmail="ops@example.com"
```

`-c existingVpcId=vpc-xxx -c appSubnetIds=... -c dataSubnetIds=...` 옵션으로 기존 VPC 재사용 가능.

## 4. 배포 후 수동 설정

### 4-0. OpenAI (Bedrock Mantle) 키 등록 (v2.4.0 신규, 최초 1회)

```bash
# OpenAI (Bedrock Mantle) bearer key — Path 4. 배포 전 1회, 운영 리전(ap-northeast-2).
aws ssm put-parameter --region ap-northeast-2 \
  --name /bedrock-monitor/openai-api-key --type SecureString \
  --value '<bedrock-long-term-api-key>'
```

> ⚠️ 키 값을 평문으로 공유한 적이 있으면 반드시 교체 후 등록할 것.

### 4-0.5. OpenAI 1P direct 키 등록 (v2.6.0 신규, 최초 1회)

```bash
# OpenAI 1P direct — Path 5. api.openai.com용 OpenAI *platform* 키(sk-proj-…).
# Mantle bearer(ABSK-…)와 다른 자격증명이므로 별도 파라미터. billing 활성 계정 키여야 함
# (미충전 계정 키는 insufficient_quota로 모든 프로브 실패). 배포 전 1회, 운영 리전(ap-northeast-2).
aws ssm put-parameter --region ap-northeast-2 \
  --name /bedrock-monitor/openai-1p-api-key --type SecureString \
  --value '<openai-platform-api-key sk-proj-...>'
```

> ⚠️ `cdk deploy`가 아닌 수동 immutable-digest 배포 시(§2-1), 실행 롤은 파라미터 ARN별로 권한이
> 필요하다. `ssm:GetParameters`를 `/bedrock-monitor/openai-1p-api-key`에 대해 **BackendExecRole +
> Scheduler TaskExecRole** 둘 다에 추가할 것(누락 시 태스크가 secret 로드 실패로 기동 안 됨).

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

# OpenAI (v2.6.0+) — 7개 채널 토큰 수 확인 (Mantle 5 + 1P direct 2).
# Bedrock Mantle 엔드포인트가 stream_options.include_usage를 무시하면
# input_tokens/output_tokens 가 0 으로 silent drop → TPS·비용도 0.
# 1P direct 채널(openai:1p:*)은 계정 quota 없으면 insufficient_quota로 status "failed".
# 첫 프로브 cycle 후 아래 명령으로 7행 + non-zero 토큰 수를 반드시 확인.
curl -s "https://$CF_DOMAIN/api/auto-probe/latest" \
  | jq '[.results[] | select(.model_id|startswith("openai:")) | {model_name, status, input_tokens, output_tokens}]'
# 기댓값: 7개 행 (Mantle 5 + 1P 2), status "success", input_tokens > 0, output_tokens > 0.
```

## 6. 후속 배포 (코드만 변경 시)

```bash
make build              # backend + frontend 이미지 재빌드
# 위 step 2-(b) 동일하게 push
aws ecs update-service --cluster bedrock-monitor --service backend  --force-new-deployment
aws ecs update-service --cluster bedrock-monitor --service frontend --force-new-deployment
```

인프라 변경 없으면 `cdk deploy`는 생략.
