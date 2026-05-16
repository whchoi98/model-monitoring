# v2 업그레이드 작업 계획 (Tasks)

각 Phase는 git commit으로 마감하며 Conventional Commits 형식 (`feat(v2): ...`, `chore(v2): ...`, `docs(v2): ...`, `refactor(v2): ...`)을 사용한다.
Phase 종료 전 `make verify`가 0 종료코드로 통과해야 한다.

---

## Phase 0 — 스펙 작성 및 레거시 정리

**산출물**
- [x] `.kiro/specs/v2-upgrade/requirements.md`
- [x] `.kiro/specs/v2-upgrade/design.md`
- [x] `.kiro/specs/v2-upgrade/tasks.md` (본 문서)
- [ ] 레거시 삭제: `src/`, `dashboard/`, `run_dashboard.py`, `run_prober.py`, 루트 `requirements.txt`, `cloudformation.yaml`, `cloudformation-alb.yaml`

**검증**
- `git status`로 삭제 확인.

**커밋 메시지**
```
chore(v2): bootstrap v2-upgrade specs and purge legacy artifacts
```

---

## Phase 1 — CDK 골격 + Makefile + Dockerfile

**산출물**
- [ ] `cdk/` 디렉토리 생성 (`bin/app.ts`, `lib/`, `cdk.json`, `package.json`, `tsconfig.json`, `jest.config.js`)
- [ ] CDK 의존성: `aws-cdk-lib@2`, `constructs@10`, `cdk-nag`, `aws-cdk@2`, `typescript@5`, `eslint`, `ts-node`
- [ ] `Makefile`: `verify`, `synth`, `build-backend`, `build-frontend`, `clean`
- [ ] `backend/Dockerfile` (multi-stage, non-root, uid 1000)
- [ ] `frontend/Dockerfile` (multi-stage, standalone output, non-root)
- [ ] `frontend/next.config.mjs`에 `output: "standalone"` 추가
- [ ] `cdk/lib/stacks/` 빈 스택 8개 placeholder

**검증**
- `make verify` PASS (synth 시 stack 0개도 OK)
- `docker build -t bedrock-monitor-backend backend/` 빌드 성공
- `docker build -t bedrock-monitor-frontend frontend/` 빌드 성공

**커밋 메시지**
```
feat(v2): scaffold CDK TypeScript project, Dockerfiles, and Makefile
```

---

## Phase 2 — NetworkStack

**산출물**
- [ ] `cdk/lib/stacks/network-stack.ts`
- [ ] VPC: 기존 VPC `from_lookup` 우선, 미존재 시 `new Vpc(...)` 신규 (2 AZ, 1 NAT)
- [ ] VPC Endpoints (Interface): `ecr.api`, `ecr.dkr`, `secretsmanager`, `ssm`, `logs`, `bedrock-runtime`, `bedrock-agentcore`, `bedrock-agentcore-control`
- [ ] VPC Endpoint (Gateway): `s3`
- [ ] Endpoint SGs (backend SG에서만 443 ingress)
- [ ] CfnOutput: vpcId, privateSubnetIds, isolatedSubnetIds

**검증**
- `make verify` PASS
- `cdk synth NetworkStack` 출력 확인 (HTTP listener 0개)

**커밋 메시지**
```
feat(v2): add NetworkStack with VPC and PrivateLink endpoints
```

---

## Phase 3 — DataStack

**산출물**
- [ ] `cdk/lib/stacks/data-stack.ts`
- [ ] RDS PostgreSQL 16 (t4g.micro, Single-AZ, 20GB gp3, 7d 백업, performance insights ON)
- [ ] RDS SG (backend/autoprober/insights SG에서만 5432 ingress) — 단, 해당 SG는 AppServices에서 생성되므로 import 패턴 사용
- [ ] Secrets Manager로 RDS credentials 자동 생성
- [ ] SSM SecureString: `JWT_SECRET_KEY` (CDK가 빈 placeholder만 생성, 값은 배포 후 수동)
- [ ] CfnOutput: dbEndpoint, dbSecretArn, jwtSecretParamName

**검증**
- `make verify` PASS
- `cdk synth` 후 RDS publicly_accessible=false 확인

**커밋 메시지**
```
feat(v2): add DataStack with RDS PostgreSQL and Secrets Manager
```

---

## Phase 4 — ClusterStack

**산출물**
- [ ] `cdk/lib/stacks/cluster-stack.ts`
- [ ] ECS Cluster `bedrock-monitor`
- [ ] ECR repos: `bedrock-monitor-backend`, `bedrock-monitor-frontend` (lifecycle 정책: 최근 10개 유지)
- [ ] KMS key for log encryption
- [ ] CfnOutput: clusterArn, ecrBackendUri, ecrFrontendUri

**검증**
- `make verify` PASS

**커밋 메시지**
```
feat(v2): add ClusterStack with ECS, ECR, and KMS key
```

---

## Phase 5 — AgentCoreStack (범위 축소: Memory만)

**범위 결정**
- AgentCore Runtime의 CfnRuntime L1은 별도 agent 컨테이너 이미지(ECR)를 요구하므로 본 Phase에서 제외.
- backend ECS가 boto3/Strands SDK로 Bedrock + AgentCore Memory를 직접 호출.
- Runtime + Gateway tool targets은 후속 Phase로 이연 (필요 시 별도 Phase 5b 신설).

**산출물**
- [x] `cdk/lib/stacks/agentcore-stack.ts`
- [x] `CfnMemory` (eventExpiryDuration 30일)
- [x] IAM Managed Policy `BedrockMonitorAgentCoreMemoryAccess` (Memory ARN scope)
- [x] SSM Parameter `/bedrock-monitor/agentcore-memory-id`
- [x] CfnOutput: memoryId, memoryArn, policyArn, paramName
- [ ] (이연) AgentCore Runtime + Gateway + tool targets

**검증**
- `make verify` PASS
- AgentCore IAM 정책 wildcard는 Memory ARN sub-resource에 한정 (cdk-nag 명시적 suppress).

**커밋 메시지**
```
feat(v2): add AgentCoreStack with Memory and backend access policy (Runtime deferred)
```

---

## Phase 6 — AppServicesStack

**산출물**
- [ ] `cdk/lib/constructs/fargate-service.ts` — 공통 Construct
- [ ] `cdk/lib/stacks/app-services-stack.ts`
- [ ] backend Service (0.5 vCPU / 1 GB, desiredCount=1, autoScaling 1~3)
- [ ] frontend Service (0.5 vCPU / 1 GB, desiredCount=1, autoScaling 1~3)
- [ ] Target Groups 2개 (HTTP backend protocol)
- [ ] IAM Roles: BackendTaskRole (bedrock·agentcore·ssm·ses), FrontendTaskRole (none)
- [ ] CfnOutput: backendTargetGroupArn, frontendTargetGroupArn

**검증**
- `make verify` PASS
- Task Definition에 secret 주입 확인 (env로 노출되지 않음)

**커밋 메시지**
```
feat(v2): add AppServicesStack with frontend and backend Fargate services
```

---

## Phase 7 — EdgeStack

**산출물**
- [ ] `cdk/lib/stacks/edge-stack.ts`
- [ ] ACM Private CA root (Optional: 기존 PCA ARN을 context로 전달 가능)
- [ ] Private CA에서 ALB internal cert 발급
- [ ] Internal ALB (scheme=internal) + HTTPS:443 listener (**HTTP listener 없음**)
- [ ] Listener Rules: priority 10 `/api/*` → backend TG, default → frontend TG
- [ ] S3 buckets: ALB access logs, CloudFront access logs (KMS 암호화, 90d 보존)
- [ ] WAFv2 WebACL (managed rules: `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesKnownBadInputsRuleSet`)
- [ ] CloudFront Distribution
- [ ] CloudFront VPC Origin (private subnet ENIs)
- [ ] CloudFront → ALB origin: `OriginProtocolPolicy: HTTPS_ONLY`
- [ ] CloudFront cache policy: API 경로 (`/api/*`) bypass cache, 그 외 default
- [ ] CloudFront → WAFv2 연결
- [ ] CloudFront access logs → S3
- [ ] Lambda@Edge (선택, 토큰 검증) — **VIEWER_REQUEST**에만 부착
- [ ] CfnOutput: cloudfrontDomain, albDns

**검증**
- `make verify` PASS
- synth된 템플릿에서 `Listener.Protocol == "HTTPS"`만 존재, `HTTP` 없음 grep 검증
- `cdk-nag` 위반 없음

**커밋 메시지**
```
feat(v2): add EdgeStack with CloudFront VPC Origin, internal ALB, and WAFv2
```

---

## Phase 8 — Backend 코드 변경 (auto-prober 분리 + 챗봇 + 인사이트)

**산출물**
- [ ] `backend/auto_prober.py` — 데몬 스레드 삭제, `_run_cycle()` 함수만 유지
- [ ] `backend/auto_prober_runner.py` — CLI 진입점 (`python -m backend.auto_prober_runner --once`)
- [ ] `backend/insights_runner.py` — CLI 진입점 (Sonnet 4.6 호출, insights 테이블 INSERT)
- [ ] `backend/main.py` lifespan에서 `auto_prober.start()` 제거
- [ ] `backend/models.py` — `Insight` 테이블 추가
- [ ] `backend/agent/streaming.py` — `simulateStreaming()`, SSE 헬퍼 (`final` 이벤트 try/finally)
- [ ] `backend/agent/client.py` — AgentCore Runtime invoke 클라이언트
- [ ] `backend/agent/memory.py` — AgentCore Memory wrapper
- [ ] `backend/agent/tools.py` — 4개 tool 함수 (DB 질의)
- [ ] `backend/routers/chat.py` — `POST /api/chat/stream` (SSE)
- [ ] `backend/routers/insights.py` — `GET /api/insights/latest`, `GET /api/insights?limit=`
- [ ] `backend/routers/agent_tools.py` — `POST /api/agent/tool/{name}` (AgentCore Gateway target)
- [ ] `backend/main.py` 라우터 등록
- [ ] 단위 테스트: `tests/test_streaming.py`, `tests/test_tools.py`

**검증**
- `make verify` PASS
- `pytest backend/tests/` PASS
- `curl --no-buffer -N -X POST http://localhost:8000/api/chat/stream -H ...` 로 SSE 청크 확인

**커밋 메시지**
```
feat(v2): decouple auto-prober and add chat, insights, and agent tools
```

---

## Phase 9 — SchedulerStack

**산출물**
- [ ] `cdk/lib/stacks/scheduler-stack.ts`
- [ ] AutoProber TaskDefinition (backend 이미지 + command override)
- [ ] Insights TaskDefinition (backend 이미지 + command override)
- [ ] EventBridge Scheduler 그룹 + Schedule × 2
  - `rate(5 minutes)` → AutoProber RunTask
  - `rate(30 minutes)` → Insights RunTask
- [ ] IAM Role: SchedulerInvokeRole (`ecs:RunTask`, `iam:PassRole`)
- [ ] AutoProberTaskRole, InsightsTaskRole
- [ ] CfnOutput: scheduleArns

**검증**
- `make verify` PASS
- AWS 콘솔에서 schedule 표시 확인 (배포 시점)

**커밋 메시지**
```
feat(v2): add SchedulerStack with auto-prober and insights schedules
```

---

## Phase 10 — Frontend 챗봇

**산출물**
- [ ] `frontend/package.json` — `react-markdown@^10`, `remark-gfm@^4` 추가
- [ ] `frontend/src/components/chat/FloatingChat.tsx` — 우하단 플로팅 버튼
- [ ] `frontend/src/components/chat/ChatModal.tsx` — iframe 모달
- [ ] `frontend/src/components/chat/ChatPopup.tsx` — popup window 헬퍼
- [ ] `frontend/src/components/chat/ChatPanel.tsx` — 공통 챗 UI
- [ ] `frontend/src/components/chat/MessageList.tsx`
- [ ] `frontend/src/components/chat/MessageMarkdown.tsx` — react-markdown + remark-gfm
- [ ] `frontend/src/components/chat/ChatInput.tsx`
- [ ] `frontend/src/components/InsightsPanel.tsx` — 대시보드 인사이트 위젯
- [ ] `frontend/src/hooks/useChatStream.ts` — SSE 수신
- [ ] `frontend/src/hooks/useUaPopupStrategy.ts` — Chrome/Firefox 분기
- [ ] `frontend/src/app/chat/page.tsx` — 팝업/iframe 진입점
- [ ] `frontend/src/lib/i18n.ts` — 챗봇 번역 추가
- [ ] `frontend/src/lib/types.ts` — chat 타입 정의
- [ ] `frontend/src/lib/api.ts` — chat/insights fetch 함수

**검증**
- `npm run build` 성공
- 로컬에서 Chrome/Firefox 각각 챗봇 열림 확인 (UI 회귀 테스트)
- `tsc --noEmit` 오류 없음

**커밋 메시지**
```
feat(v2): add FloatingChat with dual popup/iframe mode and InsightsPanel
```

---

## Phase 11 — ObservabilityStack

**산출물**
- [ ] `cdk/lib/stacks/observability-stack.ts`
- [ ] CloudWatch Log Groups: `/ecs/frontend`, `/ecs/backend`, `/ecs/autoprober`, `/ecs/insights`, `/agentcore/runtime`, `/waf` (KMS 암호화, 보존 정책)
- [ ] Alarms:
  - ALB 5xx > 1% (5분)
  - ECS Task failure count > 0
  - RDS CPUUtilization > 80%
  - RDS FreeStorageSpace < 2GB
  - AgentCore Invocation Errors > 5/5min
  - Bedrock InvokeModel 4xx/5xx 비율
- [ ] CloudWatch Dashboard (요약 지표)
- [ ] SNS Topic for alarms (선택)

**검증**
- `make verify` PASS

**커밋 메시지**
```
feat(v2): add ObservabilityStack with log groups, alarms, and dashboard
```

---

## Phase 12 — EC2 Fallback Construct (선택)

**산출물**
- [ ] `cdk/lib/constructs/ec2-fallback.ts` — 동일 워크로드를 EC2 ASG로 배포하는 Construct
- [ ] `cdk/bin/app.ts`에 `--context fallback=ec2` 플래그로 전환 가능
- [ ] 양쪽 모드 모두 `cdk synth` 통과

**검증**
- `cdk synth -c fallback=ec2` 정상
- `cdk synth` 기본 (Fargate) 정상

**커밋 메시지**
```
feat(v2): add EC2 fallback construct for non-Fargate deployment
```

---

## Phase 13 — 문서화 + ADR

**산출물**
- [ ] `docs/architecture.md` — v2 다이어그램 + 한/영 병기
- [ ] `docs/decisions/ADR-001-cloudfront-vpc-origin.md`
- [ ] `docs/decisions/ADR-002-rds-single-az.md`
- [ ] `docs/decisions/ADR-003-autoprober-decoupling.md`
- [ ] `docs/decisions/ADR-004-alb-http-target.md`
- [ ] `docs/decisions/ADR-005-acm-private-ca.md`
- [ ] `docs/decisions/ADR-006-agentcore-managed.md`
- [ ] `docs/decisions/ADR-007-sse-pattern.md`
- [ ] `docs/decisions/ADR-008-cdk-typescript.md`
- [ ] `docs/decisions/ADR-009-floating-chat-dual-mode.md`
- [ ] `docs/runbooks/deploy.md`
- [ ] `docs/runbooks/rollback.md`
- [ ] `README.md` v2 섹션 추가 (`docker build && cdk deploy --all`)
- [ ] `CLAUDE.md` v2 갱신 (RDS, AgentCore, 챗봇, Scheduler 추가)

**검증**
- 문서 링크 깨짐 없음 (`grep -RE '\\]\\([^)]+\\.md\\)' docs/`)
- README의 deploy 단계대로 수동 dry-run

**커밋 메시지**
```
docs(v2): publish architecture diagram, ADRs, runbooks, and update README
```

---

## 완료 기준 (Definition of Done)

전 Phase 종료 후:
1. `make verify` PASS.
2. `cdk deploy --all`이 깨끗하게 끝남 (수동, 자동화는 v3).
3. CloudFront 도메인에서 v1과 동일한 대시보드 + 신규 챗봇 동작.
4. EventBridge Scheduler 2개 schedule이 활성, 5분/30분 주기로 ECS Task 정상 실행.
5. RDS 연결 정상, `insights` 테이블에 데이터 누적.
6. AgentCore Memory에 세션 기록, Agent가 4개 tool 모두 호출 가능.
7. CloudFront/WAF/ALB/ECS/AgentCore 로그가 의도된 위치에 적재됨.
8. `cdk-nag` 0 violation.
9. SSE: `curl --no-buffer -N` 으로 30초 이상 long-running 청크 정상 수신.
10. README/ADR/architecture.md 최신화.
