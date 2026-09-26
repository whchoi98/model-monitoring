# CDK — AWS CDK v2 TypeScript infrastructure (8 stacks)

## Role
All AWS infrastructure for the monitor in ap-northeast-2: VPC, RDS, ECS cluster, AgentCore Memory, Fargate
services + internal ALB, CloudFront, EventBridge Scheduler tasks and alarms. Covers `bin/`, `lib/stacks/`,
`lib/constructs/`, `test/`.

## Key Files
- `bin/app.ts` — registers `BedrockMonitor-{Network,Data,Cluster,AgentCore,AppServices,Edge,Scheduler,Observability}`; region `CDK_DEFAULT_REGION ?? "ap-northeast-2"`; applies cdk-nag `AwsSolutionsChecks` to the whole app (suppressions live in each stack)
- `lib/stacks/network-stack.ts` — new VPC (1 NAT, PrivateLink endpoints) or existing-VPC mode via `existingVpcId` + `appSubnetIds` + `dataSubnetIds` (`cdk.json` sets these, so production uses existing mode)
- `lib/stacks/data-stack.ts` — RDS PostgreSQL 16.8 t4g.micro Single-AZ, deletion protection, DB secret; imports the existing SSM `/bedrock-monitor/jwt-secret-key`
- `lib/stacks/cluster-stack.ts` — cluster `bedrock-monitor`, KMS log key, ECR `bedrock-monitor-backend` (legacy) + `bedrock-monitor-frontend`, both MUTABLE with scan-on-push and "keep 10 tagged" lifecycle. `bedrock-monitor-backend-v2` (the backend repo in use, ADR-018) is created outside CDK. `exportValue` keeps the repo exports alive for consumers
- `lib/stacks/agentcore-stack.ts` — `CfnMemory` (30-day event expiry), memory access policy, SSM `/bedrock-monitor/agentcore-memory-id`
- `lib/stacks/app-services-stack.ts` — backend (8000, `/api/health`, 300 s health-check grace) and frontend (3000) services, internal ALB with HTTPS:443 and a temporary HTTP:80 listener, `/api/*` → backend at priority 10, backend env + SSM secrets, `ENABLE_OPENAI_1P = false`
- `lib/stacks/edge-stack.ts` — CloudFront → VPC Origin (currently `HTTP_ONLY` port 80 until the ALB cert is settled), alias `monitorDomain` (default `llm-monitor.whchoi.net`) + `monitorCertArn`; `/api/auto-probe/*` (short edge cache, compression) must stay declared before `/api/*` (no cache, no compression for SSE). No WAF is attached (cdk-nag CFR2 suppressed, deferred to a us-east-1 stack)
- `lib/stacks/scheduler-stack.ts` — 6 schedules (AutoProber and Insights `rate(5 minutes)`, ParityRun 12 h, GptBench 15 min, FeaturesVerify `cron(30 17 * * ? *)` UTC, PricingSync 12 h); `buildTaskDef` reuses the backend image with a CMD override (512 CPU / 1024 MiB, ARM64); `ANTHROPIC_CP_PROBE_INTERVAL_S=300` (every cycle, v2.29.1; 600 = every other cycle) only on the AutoProber task. PricingSync (v2.30.0, ADR-030) runs `python -m pricing_sync_runner --once` with its own `PricingSyncTaskRole` — only `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts` on `*`, no model invocation — and the same env and secrets as AutoProber (CP discovery and OpenAI registration), log group `/ecs/pricingsync`, output `PricingSyncScheduleName`
- `lib/stacks/observability-stack.ts` — SNS topic (+ email subscription when `alarmEmail` is set), ALB/ECS/RDS alarms, dashboard
- `lib/constructs/fargate-service.ts` — task def (default 512/1024, ARM64), circuit breaker with rollback, target group, CPU 70% autoscaling 1..3; `imageOverride` switches to a pinned URI but keeps the legacy repo `grantPull`
- `lib/constructs/pinned-image.ts` — `repoNameFromImageUri`, `pinnedContainerImage` (`ContainerImage.fromRegistry` + explicit `grantPull` on the parsed repo)

## Rules
- Always pass the running images: `-c backendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:<tag>@sha256:<digest>` and `-c frontendImage=…/bedrock-monitor-frontend:<tag>@sha256:<digest>`. Without them AppServices and Scheduler synth `:latest` of the CDK-managed repos (legacy backend repo included — only a synth warning) and a deploy reverts production. Use the full registry host — a bare repo name resolves to docker.io and the deploy rolls back
- Deploy app changes with `npx cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never -c backendImage=… -c frontendImage=…`; without `--exclusively` CDK also deploys upstream stacks that have diffs. Never `npm run deploy` (`cdk deploy --all` with no image context). Procedure: `docs/runbooks/deploy.md`
- Scheduler `ecs:RunTask` stays on task-def family `:*` (ADR-011) — a pinned revision fails silently after the next deploy. A new scheduled task adds its family to `RunTaskFamilyWildcard` and its task role to `PassTaskRoles`
- Backend env is defined twice (`backendEnv` in app-services-stack, `buildTaskDef` in scheduler-stack), and `ENABLE_OPENAI_1P` exists in both files — change both, deploy both stacks
- Some test names are stale ("immutable tag", "X86_64"); the assertions check MUTABLE and CPU/memory only

## Commands
```bash
cd cdk
npm test             # jest, synthesizes every stack (~10 s, 85 tests) — CI runs `npx jest --ci`
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npm run synth        # cdk synth --all --quiet (cdk-nag reports in cdk.out/*NagReport.csv)
```
