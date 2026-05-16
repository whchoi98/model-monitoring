// SchedulerStack — EventBridge Scheduler + AutoProber / Insights one-shot TaskDefinitions.
//
// 책임:
//   - rate(5 minutes)  → AutoProber Fargate Task (auto_prober_runner --once)
//   - rate(30 minutes) → Insights   Fargate Task (insights_runner --window 6h)
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
    // 1) 공통 SG — 두 task 모두 RDS egress + 443 egress 필요.
    // ---------------------------------------------------------------------
    const schedulerTaskSg = new ec2.SecurityGroup(this, "SchedulerTaskSg", {
      vpc: props.vpc,
      description: "AutoProber / Insights Fargate task SG (egress only)",
      allowAllOutbound: true,
    });

    // RDS SG에 standalone ingress 추가 — cross-stack cycle 회피.
    new ec2.CfnSecurityGroupIngress(this, "DbIngressFromScheduler", {
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      groupId: props.dbSecurityGroup.securityGroupId,
      sourceSecurityGroupId: schedulerTaskSg.securityGroupId,
      description: "Scheduler tasks → RDS PostgreSQL",
    });

    // ---------------------------------------------------------------------
    // 2) Shared ExecutionRole — ECR pull + Logs put + Secrets/SSM read.
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
          resources: [
            `arn:aws:bedrock:${this.region}::foundation-model/*`,
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          ],
        }),
      ],
    });

    const autoProberTaskRole = new iam.Role(this, "AutoProberTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "AutoProber task role — Bedrock + DB",
      inlinePolicies: { bedrock: sharedTaskPolicy },
    });

    const insightsTaskRole = new iam.Role(this, "InsightsTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "Insights task role — Bedrock + DB + AgentCore Memory (optional)",
      inlinePolicies: { bedrock: sharedTaskPolicy },
    });
    // Insights는 향후 AgentCore Memory를 인사이트 컨텍스트로 활용할 가능성 있음 — 정책 attach.
    insightsTaskRole.addManagedPolicy(props.agentCoreMemoryAccessPolicy);

    // ---------------------------------------------------------------------
    // 4) TaskDefinition 빌더 — backend 이미지 + command override 패턴.
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
          cpuArchitecture: ecs.CpuArchitecture.X86_64,
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
        },
        secrets: {
          DB_USER: ecs.Secret.fromSecretsManager(props.dbSecret, "username"),
          DB_PASSWORD: ecs.Secret.fromSecretsManager(props.dbSecret, "password"),
          DB_HOST: ecs.Secret.fromSecretsManager(props.dbSecret, "host"),
          DB_PORT: ecs.Secret.fromSecretsManager(props.dbSecret, "port"),
          DB_NAME: ecs.Secret.fromSecretsManager(props.dbSecret, "dbname"),
          JWT_SECRET_KEY: ecs.Secret.fromSsmParameter(props.jwtSecretParam),
          AGENTCORE_MEMORY_ID: ecs.Secret.fromSsmParameter(props.agentCoreMemoryIdParam),
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
    // 5) EventBridge Schedules.
    //    L2 EcsRunFargateTask가 scheduler IAM role을 자동 생성 + ecs:RunTask/iam:PassRole 부여.
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
      }),
    });

    this.insightsSchedule = new scheduler.Schedule(this, "InsightsSchedule", {
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(30)),
      description: "30분 주기로 Sonnet 4.6 기반 인사이트 도출",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: insightsTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
      }),
    });

    // ---------------------------------------------------------------------
    // cdk-nag suppressions.
    // ---------------------------------------------------------------------
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM4",
        reason:
          "ExecutionRole uses AWS-managed AmazonECSTaskExecutionRolePolicy — the standard ECS pattern for ECR pull + CloudWatch Logs + Secrets fetch.",
        appliesTo: [
          "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        ],
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "Bedrock foundation-model wildcard is region-scoped (matches FR-1 monitored models + Sonnet 4.6 chat/insights model). TaskExecutionRole DefaultPolicy wildcards target dynamic ECR/Logs/Secrets resources bounded by the role's trust.",
        appliesTo: [
          `Resource::arn:aws:bedrock:${this.region}::foundation-model/*`,
          `Resource::arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          "Resource::*",
        ],
      },
      {
        id: "AwsSolutions-ECS2",
        reason:
          "Plaintext environment variables are non-sensitive metadata (AWS_REGION, PYTHONUNBUFFERED). All secrets (DB credentials, JWT key, AgentCore Memory ID) use ECS secrets backed by Secrets Manager / SSM.",
      },
    ]);

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
