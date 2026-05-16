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

```bash
# (a) ECR repo만 먼저 생성.
cd cdk && npx cdk deploy BedrockMonitor-Cluster

# (b) 로그인 → 빌드 → push.
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

docker build -t bedrock-monitor-backend:latest backend/
docker tag bedrock-monitor-backend:latest \
  $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend:latest

docker build -t bedrock-monitor-frontend:latest frontend/
docker tag bedrock-monitor-frontend:latest \
  $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:latest
```

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
