// SchedulerStack - EventBridge Scheduler + AutoProber / Insights one-shot TaskDefinitions.
//
// 책임:
//   - rate(5 minutes) → AutoProber Fargate Task (auto_prober_runner --once)
//   - rate(5 minutes) → Insights   Fargate Task (insights_runner --window 6h)
//     (사용자 요청: 새로고침이 없을 때도 인사이트가 최근 데이터를 반영하도록 5분 주기로 단축)
//   - 각 TaskDefinition은 backend ECR 이미지를 재사용하고 CMD만 override.
//   - 두 task 모두 RDS:5432 egress가 필요 → 별도 SG + RDS SG에 ingress(standalone) 추가.
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
          actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
          // global.* inference profile은 cross-region 라우팅이라 region-less foundation-model
          // ARN 권한도 필요.
          resources: [
            `arn:aws:bedrock:*::foundation-model/*`,
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
            `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
          ],
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

    // ---------------------------------------------------------------------
    // 4) TaskDefinition 빌더 - backend 이미지 + command override 패턴.
    // ---------------------------------------------------------------------
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
        image: ecs.ContainerImage.fromEcrRepository(props.backendRepo, "latest"),
        containerName: id.toLowerCase(),
        command,
        environment: {
          AWS_REGION: this.region,
          PYTHONUNBUFFERED: "1",
          OPENAI_US_EAST_1_BASE_URL: "https://bedrock-mantle.us-east-1.api.aws/openai/v1",
          OPENAI_US_EAST_2_BASE_URL: "https://bedrock-mantle.us-east-2.api.aws/openai/v1",
          BEDROCK_OPENAI_GPT_54_MODEL_ID: "openai.gpt-5.4",
          BEDROCK_OPENAI_GPT_55_MODEL_ID: "openai.gpt-5.5",
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

    // ---------------------------------------------------------------------
    // 4-1) Scheduler invoke role (ADR-011).
    //    L2 EcsRunFargateTask가 자동 생성하는 role은 ecs:RunTask Resource를 task def의
    //    **특정 revision**(taskDefinitionArn)에 pin한다. 런북의 수동 재배포
    //    (register-task-definition)로 revision이 bump되면 pinned 권한이 새 revision을
    //    거부 → autoprober/insights가 silent fail (EventBridge metric도 비어 디버깅 난해).
    //    이를 방지하기 위해 명시적 role에 task def family ':*' wildcard RunTask 권한을
    //    부여하고 두 target에 전달한다 (CLAUDE.md / ADR-011 지침).
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
    //    명시적 schedulerInvokeRole(ADR-011 family ':*' wildcard)을 두 target에 전달.
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
