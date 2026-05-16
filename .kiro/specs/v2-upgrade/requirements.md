# v2 업그레이드 요구사항 (Requirements)

> 본 문서는 Bedrock LLM Monitor의 v1(EC2 + systemd + CloudFormation) →
> v2(ECS Fargate + CloudFront VPC Origin + RDS + AgentCore + 챗봇 + CDK TypeScript)
> 전환의 요구사항을 정의한다.

---

## 1. 기능 요구사항 (Functional)

### FR-1. v1 사용자 경험 보존
- 모든 기존 API 엔드포인트(`/api/auth/*`, `/api/auto-probe/*`, `/api/results/*`, `/api/probes/*`, `/api/models`, `/api/prompts`)의 경로·요청·응답 스키마 동일.
- 프론트엔드 UI/라우팅/한글 i18n 변경 없음. 신규 컴포넌트는 추가만 한다.
- 9개 Bedrock 모델 대상 5분 주기 자동 프로빙 동작 유지.

### FR-2. 컴퓨트 재구성
- ECS Fargate (`awsvpc` 네트워크 모드)에서 **frontend / backend** 2개 컨테이너 분리 실행.
- Auto-prober는 backend 프로세스에서 분리되어 **EventBridge Scheduler가 5분마다 트리거하는 독립 Fargate Task**로 단발 실행.
- 인사이트 도출(Insights)은 **EventBridge Scheduler가 30분마다 트리거하는 독립 Fargate Task**로 단발 실행.

### FR-3. 진입 경로
- 외부 사용자는 CloudFront 도메인을 통해서만 접근.
- CloudFront → **VPC Origin** → 내부 ALB → ECS 서비스의 단방향 흐름.
- 외부 인터넷에서 ALB로의 직접 접근은 불가능해야 한다(ALB scheme=internal).

### FR-4. 데이터 영속성
- **Amazon RDS for PostgreSQL** (t4g.micro, Single-AZ, gp3 20GB, 7일 자동 백업) 사용.
- backend ECS 태스크는 SG 기반 접근만 허용 (5432).
- 비밀번호는 SSM SecureString 또는 Secrets Manager에 저장.

### FR-5. 챗봇 (신규)
- 모든 페이지 우하단에 `FloatingChat` 버튼.
- 클릭 시 브라우저별 분기:
  - Chrome 등: iframe modal로 열림.
  - Firefox 등: `window.open(..., features)` popup window로 열림 (Site Engagement Score 무관).
  - 팝업 차단 시 UA 감지 후 iframe modal로 fallback.
- 챗봇 응답은 `react-markdown@10` + `remark-gfm`으로 렌더 (테이블·코드블럭 지원).
- 챗봇은 AgentCore Agent를 호출해 모니터링 데이터 질의 + 프롬프트 최적화 제안을 수행한다.

### FR-6. Bedrock AgentCore 통합 (신규)
- **AgentCore Runtime (관리형)**에 에이전트 1개 배포. 모델: **Claude Sonnet 4.6 (US)**.
- **AgentCore Memory**로 세션별 대화 컨텍스트 유지 (사용자 단위 actor).
- Agent가 호출할 **tools (function calling)** 정의:
  - `get_latest_results(model_id?: str)` — 최신 프로브 결과
  - `get_trend(hours: int, metric: str)` — 시계열 추세 (TTFT / 총지연 / TPS)
  - `compare_models(metric: str)` — 모델 간 비교 요약
  - `optimize_prompt(prompt: str, target: str)` — 프롬프트 최적화 제안 (이유 포함)

### FR-7. 인사이트 도출 (신규)
- 주기적 잡 (30분): 최근 N시간 데이터를 Sonnet 4.6에 요약시켜 `insights` 테이블에 저장. 대시보드의 인사이트 패널에 노출.
- 챗봇 온디맨드: 사용자가 챗봇에 질의 시 Agent가 tool 호출 후 자연어 답변.

---

## 2. 비기능 요구사항 (Non-functional)

### NFR-1. 보안
- ALB는 **internal scheme만** 허용. internet-facing 금지.
- ALB SG는 **CloudFront VPC Origin의 ENI SG**만 inbound 443 허용.
- 모든 ALB listener는 **HTTPS:443만**. HTTP:80 listener는 어떤 스택에서도 생성 금지.
- CloudFront → ALB origin 호출은 **`OriginProtocolPolicy=https-only`**.
- Lambda@Edge는 **VIEWER_REQUEST 단계에만 부착** (auth 검증 등). `ORIGIN_RESPONSE` 사용 금지(SSE chunked transfer 깨짐).
- 컨테이너 간 통신은 awsvpc 내부 SG 그룹만으로 제어.
- IAM 최소 권한:
  - `bedrock:InvokeModel*` — AutoProber / Insights / AgentCore 실행 역할만
  - RDS `connect` — backend ECS Task Role만
- 비밀(JWT_SECRET_KEY, RDS_PASSWORD, AgentCore IDs)은 SSM Parameter Store SecureString.

### NFR-2. 관측성 (모든 로그 활성화)
- **CloudFront access logs** → S3 (KMS 암호화, 90일 보존).
- **WAFv2 logs** → CloudWatch Logs (KMS 암호화, 30일).
- **ALB access logs** → S3 (KMS 암호화, 90일).
- **ECS 컨테이너 로그** → CloudWatch Logs `/ecs/<service>` (awslogs driver, 14일).
- **AgentCore Runtime / Memory** 호출 로그 활성화.
- 알람: ALB 5xx > 1%, ECS Task 실패, Bedrock invocation 실패율, RDS CPU/스토리지, AgentCore invocation 실패율.

### NFR-3. TLS
- CloudFront: 도메인 없음 → 기본 `*.cloudfront.net` 인증서.
- ALB internal listener: **ACM Private CA**에서 발급한 인증서.
- CloudFront → ALB 검증: Private CA 체인 신뢰 설정.

### NFR-4. SSE 운영 원칙 (필수 준수)
SSE 사용 엔드포인트는 다음 5개 원칙을 모두 만족해야 한다.

1. **즉시 emit** — Bedrock `contentBlockDelta` 이벤트마다 즉시 `delta` 이벤트로 클라이언트에 흘려보낸다. 버퍼링 금지.
2. **CloudFront 키프얼라이브 유지** — delta 이벤트 하나가 5초 keep-alive 카운터를 reset해 30초 wall-clock 제약을 우회한다.
3. **응답 변형 0** — Lambda@Edge는 `VIEWER_REQUEST` 단계에만. `ORIGIN_RESPONSE` 사용 금지.
4. **`final` 이벤트 try/finally** — 모든 예외에서 반드시 `final` 이벤트를 emit하고 스택트레이스를 CloudWatch에 logged. 클라이언트가 종료/오류 상태를 명확히 알 수 있어야 한다.
5. **`max_tokens` 시나리오별 분리** — 챗봇 답변/요약/프롬프트 최적화 등 시나리오마다 적정 한도 설정. 일률 8192 금지.
6. **AgentCore 응답은 `simulateStreaming()`** — AgentCore는 스트리밍 미지원이므로 50자 청크 + 15ms 딜레이로 의사 스트리밍. 순수 Bedrock 호출(요약/인사이트)은 실제 `ConverseStream` 사용.

### NFR-5. IaC
- 모든 인프라는 **AWS CDK v2 TypeScript** (`aws-cdk-lib` 2.x).
- 스택 분리: Network / Data / Cluster / AppServices / Edge / Scheduler / AgentCore / Observability.
- Fargate primary, EC2 fallback Construct 제공.
- `cdk-nag`(AwsSolutions ruleset) 통과 필수.
- `make verify`로 `cdk synth + tsc --noEmit + eslint + cdk-nag` 자동화.

### NFR-6. 코드 품질
- TypeScript는 `strict: true`, `noUncheckedIndexedAccess: true`.
- Python(backend) 타입 힌트 필수, Python 3.9 호환 유지 (`Optional[X]` 사용, `X | Y` 금지).
- 한국어 주석 + 영어 변수명.
- 함수/클래스는 SOLID.
- README, ADR, `architecture.md`를 변경과 동시에 갱신.

---

## 3. 제약 (Constraints)

| ID | 내용 |
|----|------|
| C-1 | Python 3.9 호환 — `Optional[X]` 사용, `X \| Y` 금지 |
| C-2 | bcrypt `>=4.0,<4.1` 고정 |
| C-3 | 한국어 UI 유지 (`frontend/src/lib/i18n.ts`) |
| C-4 | 도메인 없음 — CloudFront `*.cloudfront.net` 기본값 |
| C-5 | 기존 v1 데이터는 마이그레이션 없이 폐기 (모니터링 시계열) |
| C-6 | 리전: us-east-1 (Bedrock + AgentCore + 모든 인프라) |
| C-7 | DB: RDS PostgreSQL t4g.micro (Aurora/Serverless 미사용) |
| C-8 | 챗봇 모델: Claude Sonnet 4.6 (US) |
| C-9 | Lambda@Edge는 VIEWER_REQUEST에만 사용 (ORIGIN_RESPONSE 금지) |

---

## 4. 비범위 (Out of Scope)

- OOS-1. 멀티 리전 / DR
- OOS-2. RDS Multi-AZ 활성화 (Single-AZ 시작, 추후 Phase에서)
- OOS-3. CI/CD 파이프라인 (별도 Phase로 분리, 본 v2에 미포함)
- OOS-4. 멀티 테넌트화 / 조직 단위 격리
- OOS-5. 챗봇 음성/이미지 입력
- OOS-6. 챗봇 대화 검색 기능

---

## 5. 수용 기준 (Acceptance Criteria)

각 Phase 종료 시점에 모두 PASS여야 한다.

1. `make verify`가 0 종료코드로 성공한다 (`cdk synth + tsc + eslint + cdk-nag`).
2. `cdk-nag`가 신규 위반을 보고하지 않는다.
3. 새로 추가된 코드/리소스에 단위 또는 시각적 회귀 테스트가 존재한다.
4. README / ADR / `architecture.md` 중 영향받는 문서가 같은 커밋에 포함된다.
5. 커밋 메시지는 Conventional Commits 형식이며 영향 Phase를 명시한다.
6. SSE 변경 시 Phase 검증으로 `curl --no-buffer` 로 30초 이상 long-running 응답 keep-alive 유지 확인.
