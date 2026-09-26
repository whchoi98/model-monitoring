# Runbook — v2 배포 절차

## 0. 사전 요구사항

1. **AWS CLI 자격** — 대상 계정/리전(ap-northeast-2)에 admin 권한.
2. **CDK Bootstrap** — `npx cdk bootstrap aws://ACCOUNT/ap-northeast-2`가 완료된 계정. 모든 스택이 ap-northeast-2에
   배포된다(`cdk/bin/app.ts` — `CDK_DEFAULT_REGION`이 없을 때의 기본값). CDK CLI는 셸의 AWS 기본 리전으로
   `CDK_DEFAULT_REGION`을 채우므로 기본 리전이 다르면 먼저 `export AWS_REGION=ap-northeast-2`. us-east-1 bootstrap은 필요 없다.
3. **ACM 인증서 2개**
   - ALB internal listener용 (ADR-005) — ALB와 같은 **ap-northeast-2** 인증서. `-c albCertificateArn`으로 주입
     (운영 계정 값은 `cdk/cdk.json` context에 있다).
   - CloudFront 대체 도메인용 — **us-east-1** 인증서(CloudFront viewer cert 제약). EdgeStack은 ARN으로 가져오기만
     하므로(`fromCertificateArn`) us-east-1에 스택이나 bootstrap은 없다. 기본값은 운영 계정의 `llm-monitor.whchoi.net`과
     `*.whchoi.net` 인증서 — 다른 계정은 `-c monitorDomain=… -c monitorCertArn=…`.
4. **Docker / Node 20 / Python 3.11** — 로컬 빌드 환경.

## 1. 로컬 검증

```bash
make verify
```

CDK lint + typecheck + jest + synth(cdk-nag) + ruff + pytest + frontend typecheck + vitest를 차례로 돌린다. 마지막 줄
`✓ make verify PASS`를 확인한다. 테스트 수는 릴리스마다 바뀌므로 여기에 적지 않는다 — 스위트별로 따로 돌릴 때:

```bash
(cd cdk && npm test)                          # jest
(cd backend && python3.12 -m pytest tests/ -q) # Python 3.10+ 필요 — 시스템 python3가 3.9면 수집 단계에서 실패
(cd frontend && npm test)                     # vitest run
```

브라우저 회귀(Playwright, `make test-ui`)는 `make verify`에 포함되지 않는다.

## 2. 컨테이너 이미지 빌드 + ECR push

첫 deploy는 저장소 준비 → push 두 단계다. CDK(`BedrockMonitor-Cluster`)는 `bedrock-monitor-frontend`와 옛
`bedrock-monitor-backend`(둘 다 MUTABLE)만 만든다. 운영 backend 저장소 `bedrock-monitor-backend-v2`(IMMUTABLE, ADR-018)는
CDK가 만들지 않으므로 최초 1회 CLI로 만든다.

> **중요 (ADR-010)**: `:latest` tag는 **로컬 dev 전용**. Production task definition에는 **immutable tag (`v<timestamp>` 또는 `v<git-sha>`)** 만 사용. `:latest`로 push하면 Docker layer dedupe + ECS image cache 콤보로 새 코드가 production에 silent 반영 안 되는 사고가 발생.

```bash
# (a) ECR repo 준비 (최초 1회).
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-northeast-2
# (a-1) CDK 관리 repo(frontend + 옛 backend). 의존 스택 Network도 함께 배포된다.
(cd cdk && npx cdk deploy BedrockMonitor-Cluster)
# (a-2) 운영 backend repo — CDK 밖에서 생성 (이미 있으면 RepositoryAlreadyExistsException, 무시)
aws ecr create-repository --repository-name bedrock-monitor-backend-v2 \
  --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true --region $REGION

# (b) 로그인 → 빌드 → push. 항상 immutable tag 사용.
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

# (c) push한 이미지의 digest — §3 CDK 배포의 -c backendImage/-c frontendImage에 쓴다 (값은 "sha256:…")
BE_DIGEST=$(aws ecr describe-images --repository-name bedrock-monitor-backend-v2 --image-ids imageTag=$TAG \
  --region $REGION --query 'imageDetails[0].imageDigest' --output text)
FE_DIGEST=$(aws ecr describe-images --repository-name bedrock-monitor-frontend --image-ids imageTag=$TAG \
  --region $REGION --query 'imageDetails[0].imageDigest' --output text)
echo "$BE_DIGEST $FE_DIGEST"
```

### 2-1. Task Definition을 새 tag로 update (incremental redeploy)

`:latest`를 사용하지 않으므로 push 후 task definition을 새 revision으로 register하는 단계가 추가된다:

```bash
# Backend — 서비스가 지금 쓰는 task def에서 시작 (--task-definition은 와일드카드를 받지 않는다)
BE_TD=$(aws ecs describe-services --cluster bedrock-monitor --services backend --region $REGION \
  --query 'services[0].taskDefinition' --output text)
aws ecs describe-task-definition --task-definition "$BE_TD" \
  --region $REGION > /tmp/td-be.json
python3 -c "
import json
td = json.load(open('/tmp/td-be.json'))['taskDefinition']
out = {k:v for k,v in td.items() if k in ['family','containerDefinitions','volumes','taskRoleArn','executionRoleArn','networkMode','cpu','memory','requiresCompatibilities','runtimePlatform']}
for c in out['containerDefinitions']:
    if 'bedrock-monitor-backend' in c.get('image',''):
        c['image'] = '${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/bedrock-monitor-backend-v2:${TAG}'  # ADR-018 repo
open('/tmp/td-be-new.json','w').write(json.dumps(out))
"
BE_ARN=$(aws ecs register-task-definition --region $REGION \
  --cli-input-json file:///tmp/td-be-new.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)
aws ecs update-service --cluster bedrock-monitor --service backend \
  --task-definition "$BE_ARN" --region $REGION

# 스케줄 태스크 5개 모두 동일하게 (각각 별도 Fargate Task — backend image 공용). 하나라도 빠지면 그 태스크만 옛 이미지로 돈다.
# AutoProber:     family BedrockMonitorSchedulerAutoProberTaskDef*,     schedule rate(5 minutes),  CLI auto_prober_runner --once (CP 채널은 10분, env ANTHROPIC_CP_PROBE_INTERVAL_S — v2.29.0)
# Insights:       family BedrockMonitorSchedulerInsightsTaskDef*,       schedule rate(5 minutes),  CLI insights_runner --window 6h
# ParityRun:      family BedrockMonitorSchedulerParityRunTaskDef*,      schedule rate(12 hours),   CLI parity_runner --once (v2.11.0)
# GptBench:       family BedrockMonitorSchedulerGptBenchTaskDef*,       schedule rate(15 minutes), CLI gptbench_runner --once (v2.18.0)
# FeaturesVerify: family BedrockMonitorSchedulerFeaturesVerifyTaskDef*, schedule cron(30 17 * * ? *) Etc/UTC, CLI features_runner --once (v2.23.0, 고정 cron v2.29.0)
# 정확한 family 이름: aws ecs list-task-definition-families --family-prefix BedrockMonitorScheduler --status ACTIVE --region $REGION
AP_FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerAutoProberTaskDef \
  --status ACTIVE --region $REGION --query 'families[0]' --output text)
aws ecs describe-task-definition --task-definition "$AP_FAM" \
  --region $REGION > /tmp/td-ap.json
# ... (위와 동일하게 image 교체 + register) ...
AP_ARN=...
# 스케줄 이름 — AutoProber/Insights는 Scheduler 스택 output(AutoProberScheduleName / InsightsScheduleName)에 있다.
# 5개 전부: aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION --query 'Schedules[].Name'
AP_SCHED=$(aws cloudformation describe-stacks --stack-name BedrockMonitor-Scheduler --region $REGION \
  --query "Stacks[0].Outputs[?OutputKey=='AutoProberScheduleName'].OutputValue" --output text)
aws scheduler get-schedule --name "$AP_SCHED" --region $REGION > /tmp/sched.json
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
> # 현재 운영 image URI 확인 (backend, frontend 순서로 한 줄씩 — 레지스트리 호스트 포함 전체 URI)
> for s in backend frontend; do
>   TD=$(aws ecs describe-services --cluster bedrock-monitor --services $s --region ap-northeast-2 \
>     --query 'services[0].taskDefinition' --output text)
>   aws ecs describe-task-definition --task-definition "$TD" --region ap-northeast-2 \
>     --query 'taskDefinition.containerDefinitions[0].image' --output text
> done
> # 새 이미지(§2-(c)) 또는 위에서 확인한 URI로 — 앱 스택 두 개만, 의존 스택은 건드리지 않는다 (cdk/에서 실행)
> npx cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never \
>   -c backendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:<tag>@sha256:<digest> \
>   -c frontendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-frontend:<tag>@sha256:<digest>
> ```
>
> repo 이름만 넘기면(레지스트리 호스트 누락) ECS가 `docker.io/library/…`로 해석해 pull에 실패하고 서킷 브레이커가
> 롤백한다. `make deploy`(= `cdk deploy --all`)는 이미지 context를 넘기지 않으므로 운영 배포에 쓰지 않는다.
>
> 대체 도메인(`llm-monitor.whchoi.net`)과 ACM cert 연결도 CDK(edge-stack)가 소유한다(인증서 자체는 ARN으로 가져옴) —
> 콘솔에서 수동 추가한 배포판 설정은 다음 cdk deploy 때 제거되므로 금지.

최초 전체 배포(§2 push 직후, 같은 셸의 `$ACCOUNT`/`$REGION`/`$TAG`/`$BE_DIGEST`/`$FE_DIGEST` 사용). `--all`도 이미지
context 없이 돌리면 AppServices/Scheduler가 `:latest`로 synth된다.

```bash
cd cdk
npx cdk deploy --all --require-approval never \
  -c albCertificateArn="arn:aws:acm:ap-northeast-2:$ACCOUNT:certificate/UUID" \
  -c alarmEmail="ops@example.com" \
  -c backendImage="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-backend-v2:$TAG@$BE_DIGEST" \
  -c frontendImage="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/bedrock-monitor-frontend:$TAG@$FE_DIGEST"
```

이후 릴리스는 위 경고 블록의 `--exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler` 형태를 쓴다.
`alarmEmail`을 빼고 `BedrockMonitor-Observability`를 배포하면 SNS 이메일 구독이 삭제된다.

`-c existingVpcId=vpc-xxx -c appSubnetIds=... -c dataSubnetIds=...` 옵션으로 기존 VPC 재사용 가능 (`cdk/cdk.json` context에는
운영 계정의 VPC/서브넷/ALB 인증서 값이 들어 있다 — 다른 계정은 `-c`로 덮어쓴다).

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
aws ssm put-parameter --region ap-northeast-2 \
  --name /bedrock-monitor/jwt-secret-key \
  --value "$NEW_SECRET" \
  --type SecureString --overwrite
```

backend Fargate Service를 한 번 force-deploy해서 새 값 로드 (같은 task def로 task만 재기동 — secret은 기동 시 읽힌다):

```bash
aws ecs update-service --region ap-northeast-2 \
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
CF_DOMAIN=$(aws cloudformation describe-stacks --region ap-northeast-2 \
  --stack-name BedrockMonitor-Edge \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomain'].OutputValue" \
  --output text)

# 헬스 체크.
curl -i "https://$CF_DOMAIN/api/health"

# 첫 자동 프로빙 결과 (5분 후).
curl -i "https://$CF_DOMAIN/api/auto-probe/latest"

# OpenAI (v2.27.0 기준) — 25개 채널 토큰 수 확인 (Mantle 인리전 16 + Global CRIS 6 + US CRIS 3).
# Bedrock Mantle 엔드포인트가 stream_options.include_usage를 무시하면
# input_tokens/output_tokens 가 0 으로 silent drop → TPS·비용도 0.
# 1P direct 채널(openai:1p:*)은 v2.19.1부터 휴면(env 미주입 + visibility "(1P)" 필터) — 0행이 정상.
# Global CRIS 6채널(openai:global:global.openai.gpt-5.6-*, gpt-6-*)은 첫 success 확인 필수:
#   bedrock-runtime.ap-northeast-2 호스트는 BedrockRuntime interface VPC endpoint 경유라
#   로컬 라이브 검증과 Fargate 내부의 네트워크 경로가 다름 (ADR-025).
# US CRIS 3채널(openai:us:us.openai.gpt-6-*)은 OPENAI_US_BASE_URL(bedrock-runtime.us-east-1) 주입 필수.
#   미주입이면 prober가 조용히 skip해 25행이 22행이 된다 (ADR-027).
# GPT-6 Astra Mantle us-east-1/us-east-2는 현재 미지원(2026-09-23 사용자 결정으로 제외, 정기 재확인 대상 아님),
#   GPT-6 Sol/Luna Mantle us-east-2/us-west-2도 현재 미지원(404, 2026-09-23 사용자 결정으로 제외) — 그 채널은 없는 것이 정상 (ADR-027, ADR-028).
#   Sol/Luna env(BEDROCK_OPENAI_GPT_6_{SOL,LUNA}_MODEL_ID)가 빠지면 6채널이 조용히 사라진다 — 이미지-only 배포 금지,
#   CDK 양 스택 배포 (v2.27.0).
# v2.28.0부터 GPT-6 Sol/Luna 6채널도 비용이 표시된다(agreement offer rate card 단가 — Sol $2.20/$11, Global $2/$10,
#   Luna $0.11/$0.55, Global $0.10/$0.50). /cost에서 이 6채널이 "-"면 이미지가 v2.28.0이 아니다(pricing 키 누락).
# 첫 프로브 cycle 후 아래 명령으로 25행 + non-zero 토큰 수를 반드시 확인 (응답은 배열).
curl -s "https://$CF_DOMAIN/api/auto-probe/latest" \
  | jq '[.[] | select(.model_id|startswith("openai:")) | {model_name, status, input_tokens, output_tokens}]'
# 기댓값: 25개 행 (Mantle 16 + Global 6 + US 3), status "success", input_tokens > 0, output_tokens > 0.
# CP(anthropic:*)는 9행 — anthropic:claude-opus-5가 "Anthropic Claude Opus 5 (US)", anthropic:claude-opus-5-5가
#   "Anthropic Claude Opus 5.5 (US)"인지 확인 (v2.27.0 점 버전 오등록 수정, ADR-028).
```

- v2.23.0: `aws ecs run-task`로 FeaturesVerify 1회 실행 후 `/ecs/features` 로그에 `bedrock_messages` AccessDenied 0건 +
  `GET /api/features/latest` run.status completed, 드리프트 25건(Mantle fable-5 23 + fallback_credit 2) 대조.
  (v2.28.0부터 Mantle fallback_credit 2건은 프로브 수정으로 해소 — 아래 v2.28.0 확인 참조.)

### 5-1. v2.28.0 배포 경로와 확인 (2026-09-23)

**배포 경로**: 신규 env, IAM 변경 없음. CDK 변경은 주석과 `FeaturesVerifySchedule` description
("Claude API Features verification: 39 rows x CP/Mantle/Bedrock(Messages,InvokeModel,Converse) x 5 models, daily")뿐이다.
backend 서비스와 스케줄 태스크 5개가 함께 새 이미지로 가도록 **digest 고정 CDK로 `BedrockMonitor-AppServices` +
`BedrockMonitor-Scheduler`**를 배포한다(§3 경고 — `-c backendImage=<전체 URI>:$TAG@sha256:…`, `-c frontendImage=…`).
배포 후 두 스택의 task def image가 새 digest인지 확인한다(`aws ecs describe-task-definition … --query 'taskDefinition.containerDefinitions[].image'`).

**GPT on AWS 벤치 (18채널)**:

```bash
# 첫 18채널 사이클 로그 — "cycle start: 18 channels x 10 runs", 끝에 "cycle done: rows=180 errors=0 skipped=none elapsed=…s"
aws logs tail /ecs/gptbench --since 30m --region ap-northeast-2 | grep -E "cycle (start|done)|WallClockTimeout"
# 스코어 카드 — 18장, 그중 GPT 6 Sol/Luna 6장(Global, US, us-east-1)
curl -s "https://$CF_DOMAIN/api/gptbench/latest" | jq '{cycle_ts, n: (.channels|length),
  sol_luna: [.channels[] | select(.family|test("^GPT 6 (Sol|Luna)$")) | {model_name, runs, success, cache_hit_rate, median_reasoning_tokens}]}'
```

- 기댓값: `n` = 18, Sol/Luna 6장 모두 `runs` 10, `success` 10, `cache_hit_rate` ≈ 1.0(워밍업 1회가 콜드 캐시를 흡수 — 저장되는
  10회는 캐시 히트), Sol `median_reasoning_tokens` 0은 정상(결함 아님), Luna는 수십 토큰.
- `/api/gptbench/latest`는 **시작 후 14분이 지난 사이클만 "완료"로 보고** 진행 중이면 직전 사이클을 돌려주므로 최신
  사이클보다 약 15~30분 늦다. 배포 직후 12장이 보이면 아직 옛 사이클이다 — 다음 15분 뒤 다시 확인.
- 사이클 예측 p50 약 10분, p95 약 775초(데드라인 780초). `skipped=`에 Sol/Luna가 찍히면 데드라인 컷이다(뒤 채널부터 잘리도록
  Sol/Luna를 목록 끝에 둠). 반복되면 `GPT_BENCH_RUNS` 또는 `GPT_BENCH_DEADLINE`을 조정한다.
- `WallClockTimeout: wall-clock timeout after 90s` 오류 행은 호출당 상한(`GPT_BENCH_CALL_TIMEOUT`)에 걸린 호출이다 — 드물어야 정상.

**FeaturesVerify 수동 1회 (975셀)** — 일 1회 스케줄을 기다리지 않고 확인:

```bash
REGION=ap-northeast-2
FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerFeaturesVerifyTaskDef   --status ACTIVE --region $REGION --query 'families[0]' --output text)
# 네트워크 설정은 스케줄 타깃에서 복사: aws scheduler get-schedule … --query 'Target.EcsParameters.NetworkConfiguration'
#   (Scheduler는 Subnets/SecurityGroups/AssignPublicIp, run-task는 subnets/securityGroups/assignPublicIp 키)
aws ecs run-task --cluster bedrock-monitor --task-definition "$FAM" --launch-type FARGATE --region $REGION   --network-configuration '{"awsvpcConfiguration":{"assignPublicIp":"DISABLED","securityGroups":["<sg>"],"subnets":["<subnet-a>","<subnet-b>"]}}'
# 약 9분 뒤
curl -s "https://$CF_DOMAIN/api/features/latest" | jq '{id: .run.id, cv: .run.catalog_version, totals: .run.totals,
  n: (.results|length), opus55: ([.results[]|select(.model_key=="opus-5-5")]|length),
  catalog_changes: ([.changes[]|select(.kind=="catalog")]|length),
  measured: [.changes[]|select(.kind=="measured")|{feature,surface,model_key,before,after}],
  fc_mantle: [.results[]|select(.feature=="fallback_credit" and .surface=="mantle")|{model_key,status,verdict}]}'
```

- 기댓값: `cv` = `2026-09-23`, `n` = 975(totals 6상태 합도 975), `opus55` = 195, broken 0 목표.
- 변경 배너: **카탈로그 변경 195건**(직전 런에 없던 `opus-5-5` 셀) — 정상. 실측 변경에는 Mantle `fallback_credit`
  opus-5, sonnet-5의 `unsupported → supported`가 보여야 한다(beta 이름 수정).
- `fc_mantle`: opus-5-5, opus-5, sonnet-5 = supported / match, fable-5 = unsupported / drift(데이터 보존 opt-in — 기존 클러스터),
  fable-5-1 = not_applicable. Mantle fallback_credit이 여전히 drift ×3이면 이미지가 v2.28.0이 아니다.
- 스케줄 런은 이후 일 1회 그대로다. 수동 트리거(`POST /api/features/trigger`, JWT)도 가능하나 backend 스레드에서 약 9분 돈다.

**비용 화면**: `/cost`에서 GPT-6 Sol/Luna 6채널에 금액이 나오는지(위 §5 주석) 확인.

**운영 후속 (코드 없음)**: 패리티 구 라벨 확인은 릴리스 12시간 뒤(다음 패리티 런 이후)로 예약돼 있다.

### 5-2. v2.29.0 배포 경로와 확인 (CP 10분 주기, FeaturesVerify 고정 cron)

**배포 경로**: CDK 변경이 있다(FeaturesVerify 스케줄 `rate(24 hours)` → `cron(30 17 * * ? *)` Etc/UTC, AutoProber task def
env `ANTHROPIC_CP_PROBE_INTERVAL_S=600`). 이미지-only 경로(§2-1) 금지 — env가 복사되지 않는다(코드 기본값도 600이라
동작은 같지만 설정이 보이지 않는다). **digest 고정 CDK로 `BedrockMonitor-AppServices` + `BedrockMonitor-Scheduler`**를
배포한다(§3 경고). IAM 변경 없음, DB 마이그레이션 없음.

```bash
REGION=ap-northeast-2
# 1. FeaturesVerify 스케줄 — cron + Etc/UTC, rate(1 day)가 남아 있지 않아야 한다
N=$(aws scheduler list-schedules --region $REGION --query 'Schedules[].Name' --output text | tr '\t' '\n' | grep FeaturesVerify)
aws scheduler get-schedule --name "$N" --region $REGION --query '{e:ScheduleExpression,tz:ScheduleExpressionTimezone,d:Description}'
# 기댓값: {"e": "cron(30 17 * * ? *)", "tz": "Etc/UTC", "d": "… daily at 17:30 UTC"}

# 2. AutoProber task def env
FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerAutoProberTaskDef --status ACTIVE \
  --region $REGION --query 'families[0]' --output text)
aws ecs describe-task-definition --task-definition "$FAM" --region $REGION \
  --query 'taskDefinition.containerDefinitions[0].environment[?name==`ANTHROPIC_CP_PROBE_INTERVAL_S`]'

# 3. CP 채널이 두 사이클에 한 번만 프로빙되는지 — 사이클마다 한 줄, "9 due"와 "0 due … 9 not due"가 번갈아 나온다
aws logs tail /ecs/autoprober --since 30m --region $REGION | grep "Claude Platform on AWS 600s cadence"
# 예: … 600s cadence - 9 due ['code-gen'], 0 not due   /   … 600s cadence - 0 due [], 9 not due

# 4. CP를 건너뛴 사이클에도 /latest에 CP 9행이 남는다(직전 run의 행, run_id가 다름)
curl -s "https://$CF_DOMAIN/api/auto-probe/latest" | jq '[.[] | select(.model_id|startswith("anthropic:")) | {model_name, run_id, category, timestamp}]'
curl -s "https://$CF_DOMAIN/api/auto-probe/status" | jq '{interval_seconds, channel_intervals, channel_category_intervals}'
# 기댓값: channel_intervals {"anthropic": 600}, channel_category_intervals {"anthropic": 3600}
```

- 대시보드 수집 상태 줄에 "5분 주기"와 "Claude Platform on AWS 10분 주기"가 함께 보인다. CP 카드는 10분 + 5분 유예
  안에서는 "수집 지연"으로 바뀌지 않는다. 추세 차트의 CP 선은 10분 간격 점을 끊김 없이 잇는다.
- CP 카테고리는 채널별로 따로 돈다 — 같은 run 안에서 CP 행의 `category`가 다른 모델과 다른 것이 정상이다. 워크로드 필터에서
  CP 채널은 약 60분마다 갱신된다(다른 채널은 30분).
- **2026-10-01 00:00 UTC 전까지 CP 행은 전부 오류가 정상이다**(조직 월간 사용량 상한 429 — `troubleshooting.md` 참고).
  확인할 것은 재시도가 없어졌는지다: `/ecs/autoprober`에 CP 프로브마다 `usage cap reached, not retried` 경고 한 줄,
  `Retryable error for anthropic:` 0건. 시간당 CP 오류 행은 9채널 × 6회 = 54개 안팎이어야 한다(이전 108개).
- FeaturesVerify 첫 스케줄 런은 배포 뒤 첫 17:30 UTC다. 그 전에 확인하려면 §5-1의 수동 1회 절차를 쓴다.

## 6. 후속 배포 (코드만 변경 시)

⚠️ **신규 env가 추가된 릴리스(예: v2.20.0 `OPENAI_GLOBAL_BASE_URL`, v2.25.0 `OPENAI_US_BASE_URL` + `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID`)에는 이미지-only
경로(§2-1 기존 task-def 복사 재등록)를 쓰지 말 것** — 기존 task definition의 env가
그대로 복사돼 신규 env가 누락되고, prober는 base_url env가 없으면 해당 채널을 **조용히
skip**한다 (에러 없음, 해당 채널만 카탈로그에서 사라짐). 반드시 CDK 배포
(`BedrockMonitor-AppServices` + `BedrockMonitor-Scheduler`, digest 고정 `-c backendImage/-c frontendImage`)로
backend 서비스와 스케줄 태스크(autoprober/insights/parityrun/gptbench/featuresverify) **양쪽** task def를 갱신할 것.

```bash
make build   # 로컬 확인 전용 — :dev 태그, --platform linux/arm64와 RUM build arg가 없어 운영 push 금지
# 운영 이미지: §2-(b) 빌드·push(v<epoch> 태그, arm64, RUM build arg) → §2-(c) digest 확인
# → §3 경고 블록의 digest 고정 CDK 배포(--exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler)
```

`aws ecs update-service --force-new-deployment`는 **새 코드를 내보내지 않는다** — 서비스의 task def가 digest로 고정돼
있어 같은 이미지로 task만 재기동한다(SSM 값 재로딩 용도, §4-1). 인프라 변경이 없어도 새 이미지는 digest 고정 CDK 배포로
내보낸다(신규 env가 없는 릴리스에 한해 §2-1 수동 경로도 가능).
