// SchedulerStack - EventBridge Scheduler + AutoProber / Insights / ParityRun / GptBench / FeaturesVerify one-shot TaskDefinitions.
//
// 책임:
//   - rate(5 minutes) → AutoProber Fargate Task (auto_prober_runner --once)
//   - rate(5 minutes) → Insights   Fargate Task (insights_runner --window 6h)
//     (사용자 요청: 새로고침이 없을 때도 인사이트가 최근 데이터를 반영하도록 5분 주기로 단축)
//   - rate(12 hours) → ParityRun Fargate Task (parity_runner --once)
//   - rate(15 minutes) → GptBench Fargate Task (gptbench_runner --once)
//   - rate(24 hours) → FeaturesVerify Fargate Task (features_runner --once)
//   - 각 TaskDefinition은 backend ECR 이미지를 재사용하고 CMD만 override.
//   - 모든 task는 RDS:5432 egress + Bedrock/Mantle 액세스 필요 → 별도 SG + RDS SG에 ingress(standalone) 추가.
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as schedulerTargets from "aws-cdk-lib/aws-scheduler-targets";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";
import { pinnedContainerImage } from "../constructs/pinned-image";

export interface SchedulerStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly appSubnets: ec2.SubnetSelection;
  readonly cluster: ecs.ICluster;
  readonly backendRepo: ecr.IRepository;
  readonly dbSecret: secretsmanager.ISecret;
  readonly dbSecurityGroup: ec2.ISecurityGroup;
  readonly jwtSecretParam: ssm.IStringParameter;
  readonly agentCoreMemoryIdParam: ssm.IStringParameter;
  readonly agentCoreMemoryAccessPolicy: iam.IManagedPolicy;
}

// OpenAI 1P direct(Path 5) 노출 스위치 — 2026-07-31 사용자 결정으로 비활성(키 폐기 상태).
// 코드·SSM 파라미터·프로버 경로는 전부 보존 — true로 되돌리고 유효 키를 SSM에 넣으면 즉시 복원.
const ENABLE_OPENAI_1P = false;

export class SchedulerStack extends cdk.Stack {
  public readonly autoProberSchedule: scheduler.Schedule;
  public readonly insightsSchedule: scheduler.Schedule;

  constructor(scope: Construct, id: string, props: SchedulerStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // 1) 공통 SG - 두 task 모두 RDS egress + 443 egress 필요.
    // ---------------------------------------------------------------------
    const schedulerTaskSg = new ec2.SecurityGroup(this, "SchedulerTaskSg", {
      vpc: props.vpc,
      description: "AutoProber / Insights Fargate task SG (egress only)",
      allowAllOutbound: true,
    });

    // RDS SG에 standalone ingress 추가 - cross-stack cycle 회피.
    new ec2.CfnSecurityGroupIngress(this, "DbIngressFromScheduler", {
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      groupId: props.dbSecurityGroup.securityGroupId,
      sourceSecurityGroupId: schedulerTaskSg.securityGroupId,
      description: "Scheduler tasks to RDS PostgreSQL",
    });

    // ---------------------------------------------------------------------
    // 2) Shared ExecutionRole - ECR pull + Logs put + Secrets/SSM read.
    // ---------------------------------------------------------------------
    const executionRole = new iam.Role(this, "TaskExecRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
      description: "Execution role for Scheduler-invoked Fargate tasks",
    });

    // ---------------------------------------------------------------------
    // 3) Task Role 공통 권한 (Bedrock + 가벼운 SES 미사용).
    //    AutoProber/Insights 모두 동일한 모델 호출이 필요하므로 동일 정책.
    // ---------------------------------------------------------------------
    const sharedTaskPolicy = new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          sid: "BedrockInvokeModel",
          effect: iam.Effect.ALLOW,
          actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:CountTokens"],
          // global.* inference profile은 cross-region 라우팅이라 region-less foundation-model
          // ARN 권한도 필요.
          resources: [
            `arn:aws:bedrock:*::foundation-model/*`,
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
            `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
          ],
        }),
        new iam.PolicyStatement({
          // messages_mantle 패리티 프로브 (v2.13.0) — Mantle /anthropic은 SigV4 파생
          // bearer가 태스크 롤 권한을 그대로 사용하므로 bedrock-mantle 액션이 필요.
          sid: "BedrockMantleInference",
          effect: iam.Effect.ALLOW,
          actions: ["bedrock-mantle:CreateInference", "bedrock-mantle:CountTokens"],
          resources: [`arn:aws:bedrock-mantle:*:${this.account}:project/*`],
        }),
        new iam.PolicyStatement({
          // bearer 인증(SigV4 파생 단기 토큰)의 두 번째 필수 액션 — Mantle /anthropic(bedrock-mantle:) +
          // bedrock-runtime /anthropic Messages 라우트(bedrock:, v2.23.0 bedrock_messages surface).
          // 403 실측상 resource scope는 * 뿐.
          sid: "BedrockBearerTokens",
          effect: iam.Effect.ALLOW,
          actions: ["bedrock-mantle:CallWithBearerToken", "bedrock:CallWithBearerToken"],
          resources: ["*"],
        }),
      ],
    });

    const autoProberTaskRole = new iam.Role(this, "AutoProberTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "AutoProber task role - Bedrock + DB",
      inlinePolicies: { bedrock: sharedTaskPolicy },
    });

    const insightsTaskRole = new iam.Role(this, "InsightsTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Insights task role - Bedrock + DB + AgentCore Memory (optional)",
      inlinePolicies: { bedrock: sharedTaskPolicy },
    });
    // Insights는 향후 AgentCore Memory를 인사이트 컨텍스트로 활용할 가능성 있음 - 정책 attach.
    insightsTaskRole.addManagedPolicy(props.agentCoreMemoryAccessPolicy);

    // Claude Platform on AWS (Path 3 External) - vendor endpoint.
    // AppServicesStack과 동일하게 사전 생성된 SSM SecureString을 import.
    const anthropicApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "AnthropicApiKeyParam",
      { parameterName: "/bedrock-monitor/anthropic-api-key" },
    );
    const anthropicWorkspaceIdParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "AnthropicWorkspaceIdParam",
      { parameterName: "/bedrock-monitor/anthropic-workspace-id" },
    );

    // OpenAI via Bedrock Mantle (Path 4) - 사전 생성된 SSM SecureString import. 없어도 동작.
    const openaiApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "OpenAiApiKeyParam",
      { parameterName: "/bedrock-monitor/openai-api-key" },
    );

    // OpenAI 1P direct / api.openai.com (Path 5) - 별도 OpenAI platform 키. 없어도 동작.
    const openai1pApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "OpenAi1pApiKeyParam",
      { parameterName: "/bedrock-monitor/openai-1p-api-key" },
    );

    // ---------------------------------------------------------------------
    // 4) TaskDefinition 빌더 - backend 이미지 + command override 패턴.
    // 이미지 고정: context backendImage(digest URI) 지정 시 그것을 사용 (pinned-image.ts).
    // ---------------------------------------------------------------------
    const backendImage = this.node.tryGetContext("backendImage") as string | undefined;
    if (!backendImage) {
      cdk.Annotations.of(this).addWarning(
        "backendImage context 미지정 — legacy :latest 참조로 synth됨. " +
          "운영 배포 시 -c backendImage=<uri@digest> 주입 필수 (runbook §3).",
      );
    }
    const buildTaskDef = (
      id: string,
      taskRole: iam.IRole,
      command: string[],
      logGroupName: string,
    ): ecs.FargateTaskDefinition => {
      const td = new ecs.FargateTaskDefinition(this, id, {
        cpu: 512,
        memoryLimitMiB: 1024,
        executionRole,
        taskRole,
        runtimePlatform: {
          cpuArchitecture: ecs.CpuArchitecture.ARM64,
          operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        },
      });

      const logGroup = new logs.LogGroup(this, `${id}LogGroup`, {
        logGroupName,
        retention: logs.RetentionDays.TWO_WEEKS,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      });

      td.addContainer("App", {
        image: backendImage
          ? (() => {
              // legacy repo 참조 유지 — cross-stack export 삭제 데드락 방지 (fargate-service.ts 참고).
              props.backendRepo.grantPull(td.obtainExecutionRole());
              return pinnedContainerImage(this, `${id}PinnedImageRepo`, backendImage, td.obtainExecutionRole());
            })()
          : ecs.ContainerImage.fromEcrRepository(props.backendRepo, "latest"),
        containerName: id.toLowerCase(),
        command,
        environment: {
          AWS_REGION: this.region,
          PYTHONUNBUFFERED: "1",
          OPENAI_US_EAST_1_BASE_URL: "https://bedrock-mantle.us-east-1.api.aws/openai/v1",
          OPENAI_US_EAST_2_BASE_URL: "https://bedrock-mantle.us-east-2.api.aws/openai/v1",
          OPENAI_US_WEST_2_BASE_URL: "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
          // global CRIS(global.openai.*)는 bedrock-mantle 호스트 미지원 — bedrock-runtime
          // OpenAI-compat 엔드포인트(Seoul)로만 호출 가능. GPT-5.6 Global 채널 3개용 (v2.20.0).
          OPENAI_GLOBAL_BASE_URL: "https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1",
          // Mantle /anthropic 리전 — ap-northeast-1은 Opus 4.8만 서빙(2026-09-05 실측), 대표 4모델이 서빙되는 us-east-1로 고정(사용자 결정). 패리티 messages_mantle도 같은 env를 읽음
          // MCP 커넥터 프로브용 공개 read-only MCP 서버 (서버 장애는 inconclusive로 격리).
          MANTLE_ANTHROPIC_REGION: "us-east-1",
          FEATURES_MCP_SERVER_URL: "https://mcp.deepwiki.com/mcp",
          BEDROCK_OPENAI_GPT_54_MODEL_ID: "openai.gpt-5.4",
          BEDROCK_OPENAI_GPT_55_MODEL_ID: "openai.gpt-5.5",
          BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID: "openai.gpt-5.6-sol",
          BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID: "openai.gpt-5.6-terra",
          BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID: "openai.gpt-5.6-luna",
          // 1P direct — native ids. ENABLE_OPENAI_1P=false면 미주입 → prober가 조용히 skip.
          ...(ENABLE_OPENAI_1P ? {
            OPENAI_1P_GPT_54_MODEL_ID: "gpt-5.4",
            OPENAI_1P_GPT_55_MODEL_ID: "gpt-5.5",
            OPENAI_1P_GPT_56_SOL_MODEL_ID: "gpt-5.6-sol",
            OPENAI_1P_GPT_56_TERRA_MODEL_ID: "gpt-5.6-terra",
            OPENAI_1P_GPT_56_LUNA_MODEL_ID: "gpt-5.6-luna",
          } : {}),
        },
        secrets: {
          DB_USER: ecs.Secret.fromSecretsManager(props.dbSecret, "username"),
          DB_PASSWORD: ecs.Secret.fromSecretsManager(props.dbSecret, "password"),
          DB_HOST: ecs.Secret.fromSecretsManager(props.dbSecret, "host"),
          DB_PORT: ecs.Secret.fromSecretsManager(props.dbSecret, "port"),
          DB_NAME: ecs.Secret.fromSecretsManager(props.dbSecret, "dbname"),
          JWT_SECRET_KEY: ecs.Secret.fromSsmParameter(props.jwtSecretParam),
          AGENTCORE_MEMORY_ID: ecs.Secret.fromSsmParameter(props.agentCoreMemoryIdParam),
          ANTHROPIC_API_KEY: ecs.Secret.fromSsmParameter(anthropicApiKeyParam),
          ANTHROPIC_WORKSPACE_ID: ecs.Secret.fromSsmParameter(anthropicWorkspaceIdParam),
          OPENAI_API_KEY: ecs.Secret.fromSsmParameter(openaiApiKeyParam),
          ...(ENABLE_OPENAI_1P ? { OPENAI_1P_API_KEY: ecs.Secret.fromSsmParameter(openai1pApiKeyParam) } : {}),
        },
        logging: ecs.LogDrivers.awsLogs({
          logGroup,
          streamPrefix: id.toLowerCase(),
        }),
        essential: true,
      });

      return td;
    };

    const autoProberTaskDef = buildTaskDef(
      "AutoProberTaskDef",
      autoProberTaskRole,
      ["python", "-m", "auto_prober_runner", "--once"],
      "/ecs/autoprober",
    );

    const insightsTaskDef = buildTaskDef(
      "InsightsTaskDef",
      insightsTaskRole,
      ["python", "-m", "insights_runner", "--window", "6h"],
      "/ecs/insights",
    );

    // 패리티 런 (v2.11.0) — 모델×surface×피처 실행-증거 스윕. autoprober와 동일 권한.
    const parityTaskDef = buildTaskDef(
      "ParityRunTaskDef",
      autoProberTaskRole,
      ["python", "-m", "parity_runner", "--once"],
      "/ecs/parityrun",
    );

    // GPT on AWS 벤치 (v2.18.0) — Mantle 8채널 × 10회 TTFB/TTFT 측정, 15분 주기.
    // OpenAI bearer 키(secret)만 사용 — bedrock IAM 불필요하지만 autoprober role 재사용 (패턴 통일).
    const gptBenchTaskDef = buildTaskDef(
      "GptBenchTaskDef",
      autoProberTaskRole,
      ["python", "-m", "gptbench_runner", "--once"],
      "/ecs/gptbench",
    );

    // Claude API Features 검증 (v2.23.0) — 39행(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1)
    //   × 5 surface(CP on AWS / Mantle `/anthropic` / Bedrock runtime Messages API·InvokeModel·Converse) × 대표 4모델 실행-증거, 일 1회.
    // bedrock:* + bedrock-mantle:* IAM 체인이 필요하므로 autoprober role 재사용. CP는 API 키(secret).
    const featuresTaskDef = buildTaskDef(
      "FeaturesVerifyTaskDef",
      autoProberTaskRole,
      ["python", "-m", "features_runner", "--once"],
      "/ecs/features",
    );

    // ---------------------------------------------------------------------
    // 4-1) Scheduler invoke role (ADR-011).
    //    L2 EcsRunFargateTask가 자동 생성하는 role은 ecs:RunTask Resource를 task def의
    //    **특정 revision**(taskDefinitionArn)에 pin한다. 런북의 수동 재배포
    //    (register-task-definition)로 revision이 bump되면 pinned 권한이 새 revision을
    //    거부 → autoprober/insights가 silent fail (EventBridge metric도 비어 디버깅 난해).
    //    이를 방지하기 위해 명시적 role에 task def family ':*' wildcard RunTask 권한을
    //    부여하고 모든 스케줄 target에 전달한다 (CLAUDE.md / ADR-011 지침).
    // ---------------------------------------------------------------------
    const schedulerInvokeRole = new iam.Role(this, "SchedulerInvokeRole", {
      assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
      description:
        "EventBridge Scheduler role - ecs:RunTask (task def family ':*' wildcard, ADR-011) + scoped iam:PassRole",
    });
    schedulerInvokeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "RunTaskFamilyWildcard",
        effect: iam.Effect.ALLOW,
        actions: ["ecs:RunTask"],
        // revision 번호를 박지 않고 family ':*' wildcard 사용 (ADR-011).
        resources: [
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${autoProberTaskDef.family}:*`,
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${insightsTaskDef.family}:*`,
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${parityTaskDef.family}:*`,
          // gptbench도 wildcard 필요 — 누락 시 수동 register-task-definition으로 revision이
          // bump되는 순간 스케줄이 silent fail (ADR-011과 동일 시나리오).
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${gptBenchTaskDef.family}:*`,
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${featuresTaskDef.family}:*`,
        ],
      }),
    );
    schedulerInvokeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "PassTaskRoles",
        effect: iam.Effect.ALLOW,
        actions: ["iam:PassRole"],
        resources: [
          autoProberTaskRole.roleArn,
          insightsTaskRole.roleArn,
          executionRole.roleArn,
        ],
        conditions: {
          StringLike: { "iam:PassedToService": "ecs-tasks.amazonaws.com" },
        },
      }),
    );

    // ---------------------------------------------------------------------
    // 5) EventBridge Schedules.
    //    명시적 schedulerInvokeRole(ADR-011 family ':*' wildcard)을 모든 스케줄 target에 전달.
    // ---------------------------------------------------------------------
    this.autoProberSchedule = new scheduler.Schedule(this, "AutoProberSchedule", {
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(5)),
      description: "5분 주기로 Bedrock 모니터링 프로빙",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: autoProberTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });

    new scheduler.Schedule(this, "ParityRunSchedule", {
      // 12시간 주기 (v2.12.0, 이전 일 1회) — 전체 스윕 ~350 프로브, 저비용(max_tokens 소량)
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.hours(12)),
      description: "Bedrock feature parity sweep (every 12 hours)",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: parityTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });

    new scheduler.Schedule(this, "GptBenchSchedule", {
      // 15분 주기 — 사이클(8채널 × 워밍업1 + 10회 순차) ~6-9분, 데드라인 13분 (겹침 방지)
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(15)),
      description: "GPT on AWS bench: Mantle TTFB/TTFT every 15 minutes",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: gptBenchTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });

    new scheduler.Schedule(this, "FeaturesVerifySchedule", {
      // 일 1회 (사용자 결정 2026-09-05) — 1런 = 658 프로브 + 122 사전판정 = 780셀
      //   (39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1) × 5 surface × 4 모델,
      //   캐싱·부정 제어 포함 ≈ 800 API 호출, 토큰 비용 대략 $5~7 (Fable 지배)
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.hours(24)),
      description: "Claude API Features verification: 39 rows x CP/Mantle/Bedrock(Messages,InvokeModel,Converse) x 4 models, daily",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: featuresTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });

    this.insightsSchedule = new scheduler.Schedule(this, "InsightsSchedule", {
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(5)),
      description: "Insights every 5 minutes (Sonnet 4.6)",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: insightsTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });

    // ---------------------------------------------------------------------
    // cdk-nag suppressions.
    // ---------------------------------------------------------------------
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM4",
        reason:
          "ExecutionRole uses AWS-managed AmazonECSTaskExecutionRolePolicy - the standard ECS pattern for ECR pull + CloudWatch Logs + Secrets fetch.",
        appliesTo: [
          "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        ],
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "global.* inference profile은 cross-region 라우팅이므로 region-less / region-wildcard ARN 필요. TaskExecutionRole DefaultPolicy wildcards는 ECR/Logs/Secrets 동적 리소스용 (role trust로 제한).",
        appliesTo: [
          `Resource::arn:aws:bedrock:*::foundation-model/*`,
          `Resource::arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          `Resource::arn:aws:bedrock:*:${this.account}:inference-profile/*`,
          // messages_mantle 프로브 (v2.13.0) — Mantle project id는 리전별 'default'뿐이라
          // 계정 scope 내 project/* 로 제한. 리전은 MANTLE_ANTHROPIC_REGION로 가변.
          `Resource::arn:aws:bedrock-mantle:*:${this.account}:project/*`,
          "Resource::*",
        ],
      },
      {
        id: "AwsSolutions-ECS2",
        reason:
          "Plaintext environment variables are non-sensitive metadata (AWS_REGION, PYTHONUNBUFFERED). All secrets (DB credentials, JWT key, AgentCore Memory ID) use ECS secrets backed by Secrets Manager / SSM.",
      },
    ]);

    NagSuppressions.addResourceSuppressions(
      schedulerInvokeRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "ADR-011: ecs:RunTask Resource는 task def family ':*' wildcard 사용 - 런북 재배포로 revision이 bump돼도 RunTask가 거부되지 않도록 (silent fail 방지). iam:PassRole은 iam:PassedToService=ecs-tasks 조건으로 제한.",
        },
      ],
      true,
    );

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "AutoProberScheduleName", {
      value: this.autoProberSchedule.scheduleName,
    });
    new cdk.CfnOutput(this, "InsightsScheduleName", {
      value: this.insightsSchedule.scheduleName,
    });
    new cdk.CfnOutput(this, "SchedulerTaskSgId", {
      value: schedulerTaskSg.securityGroupId,
    });
    new cdk.CfnOutput(this, "AutoProberTaskDefArn", {
      value: autoProberTaskDef.taskDefinitionArn,
    });
    new cdk.CfnOutput(this, "InsightsTaskDefArn", {
      value: insightsTaskDef.taskDefinitionArn,
    });
  }
}
