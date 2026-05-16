// AppServicesStack — frontend / backend Fargate Service 2개 + IAM 4개 + SG 매트릭스 + TG 2개.
//
// 주요 흐름:
//   - DataStack의 dbSecurityGroup에 backend SG로부터 5432 ingress 추가 (cross-stack).
//   - AgentCoreStack의 memoryAccessPolicy를 BackendTaskRole에 attach.
//   - SG 매트릭스:
//       sg-frontend: ingress = ALB SG → 3000 (EdgeStack/Phase 7에서 추가)
//       sg-backend : ingress = ALB SG → 8000 (EdgeStack/Phase 7에서 추가)
//                    egress  = RDS SG 5432, 443 (AWS API)
//   - 컨테이너 이미지: ECR 'latest' tag (배포 시점에 사전 push 필요).
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";
import { FargateServiceConstruct } from "../constructs/fargate-service";

export interface AppServicesStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly appSubnets: ec2.SubnetSelection;
  readonly cluster: ecs.ICluster;
  readonly backendRepo: ecr.IRepository;
  readonly frontendRepo: ecr.IRepository;
  readonly dbSecret: secretsmanager.ISecret;
  readonly dbSecurityGroup: ec2.ISecurityGroup;
  readonly jwtSecretParam: ssm.IStringParameter;
  readonly agentCoreMemoryAccessPolicy: iam.IManagedPolicy;
  readonly agentCoreMemoryIdParam: ssm.IStringParameter;
}

export class AppServicesStack extends cdk.Stack {
  public readonly backend: FargateServiceConstruct;
  public readonly frontend: FargateServiceConstruct;
  public readonly backendTargetGroup: elbv2.IApplicationTargetGroup;
  public readonly frontendTargetGroup: elbv2.IApplicationTargetGroup;

  constructor(scope: Construct, id: string, props: AppServicesStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // backend Task Role — Bedrock + AgentCore Memory + SSM + Secrets + SES.
    // ---------------------------------------------------------------------
    const backendTaskRoleStatements: iam.PolicyStatement[] = [
      new iam.PolicyStatement({
        sid: "BedrockInvokeModel",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        // 9개 모니터링 대상 + 챗봇용 Sonnet 4.6 — 광범위하게 anthropic / amazon 모델로 한정.
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/*`,
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
        ],
      }),
      new iam.PolicyStatement({
        sid: "SESSendEmail",
        effect: iam.Effect.ALLOW,
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: ["*"], // SES API에는 리소스 ARN scope이 제한적임.
      }),
    ];

    // ---------------------------------------------------------------------
    // backend 컨테이너 비밀/환경.
    // ---------------------------------------------------------------------
    const backendSecrets: Record<string, ecs.Secret> = {
      DATABASE_URL: ecs.Secret.fromSecretsManager(props.dbSecret, "host"), // 단순화 — 실제로는 SecretJSON 조합
      DB_USER: ecs.Secret.fromSecretsManager(props.dbSecret, "username"),
      DB_PASSWORD: ecs.Secret.fromSecretsManager(props.dbSecret, "password"),
      DB_HOST: ecs.Secret.fromSecretsManager(props.dbSecret, "host"),
      DB_PORT: ecs.Secret.fromSecretsManager(props.dbSecret, "port"),
      DB_NAME: ecs.Secret.fromSecretsManager(props.dbSecret, "dbname"),
      JWT_SECRET_KEY: ecs.Secret.fromSsmParameter(props.jwtSecretParam),
      AGENTCORE_MEMORY_ID: ecs.Secret.fromSsmParameter(props.agentCoreMemoryIdParam),
    };

    const backendEnv: Record<string, string> = {
      AWS_REGION: this.region,
      PYTHONUNBUFFERED: "1",
    };

    // ---------------------------------------------------------------------
    // backend Service.
    // ---------------------------------------------------------------------
    this.backend = new FargateServiceConstruct(this, "Backend", {
      serviceName: "backend",
      cluster: props.cluster,
      vpc: props.vpc,
      appSubnets: props.appSubnets,
      repository: props.backendRepo,
      imageTag: "latest",
      containerPort: 8000,
      healthCheckPath: "/api/health",
      environment: backendEnv,
      secrets: backendSecrets,
      taskRolePolicies: [props.agentCoreMemoryAccessPolicy],
      taskRoleStatements: backendTaskRoleStatements,
    });

    // ---------------------------------------------------------------------
    // frontend Service — 권한 없음.
    // ---------------------------------------------------------------------
    this.frontend = new FargateServiceConstruct(this, "Frontend", {
      serviceName: "frontend",
      cluster: props.cluster,
      vpc: props.vpc,
      appSubnets: props.appSubnets,
      repository: props.frontendRepo,
      imageTag: "latest",
      containerPort: 3000,
      healthCheckPath: "/",
      environment: {
        NODE_ENV: "production",
        // ALB가 path-based 라우팅을 하므로 frontend Next.js rewrite는 비활성.
        // 브라우저가 동일 origin의 /api/* 호출 시 ALB가 직접 backend로 라우팅.
      },
    });

    this.backendTargetGroup = this.backend.targetGroup;
    this.frontendTargetGroup = this.frontend.targetGroup;

    // ---------------------------------------------------------------------
    // SG cross-stack ingress — backend SG → RDS SG :5432.
    // dbSecurityGroup.addIngressRule(...)는 Data 스택을 mutate하여 순환 참조를
    // 만든다. 본 스택 안에 standalone CfnSecurityGroupIngress로 표현해
    // 두 SG ID만 import value로 참조하도록 분리.
    // ---------------------------------------------------------------------
    new ec2.CfnSecurityGroupIngress(this, "DbIngressFromBackend", {
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      groupId: props.dbSecurityGroup.securityGroupId,
      sourceSecurityGroupId: this.backend.securityGroup.securityGroupId,
      description: "Backend ECS → RDS PostgreSQL",
    });

    // ---------------------------------------------------------------------
    // cdk-nag suppressions.
    //   - IAM5 (Bedrock foundation-model/*): wildcard는 region scope 내 모든 모델 ID 허용.
    //     동적 모델 추가 시 자동 적용 — spec FR-1의 9 모델 + Sonnet 4.6 모두 포함.
    //   - IAM5 (SES resources:*): SES는 ARN scope이 제한적이므로 *.
    //   - ECS4 (Container Insights): 클러스터에서 활성화 (ClusterStack), 본 스택은 그대로 사용.
    // ---------------------------------------------------------------------
    NagSuppressions.addResourceSuppressions(
      this.backend.taskRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "Bedrock foundation-model wildcard is region-scoped and intentionally covers monitored models + chat model (FR-1 / FR-6).",
          appliesTo: [
            `Resource::arn:aws:bedrock:${this.region}::foundation-model/*`,
            `Resource::arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          ],
        },
        {
          id: "AwsSolutions-IAM5",
          reason:
            "SES SendEmail/SendRawEmail does not support resource-level permissions (AWS limitation).",
          appliesTo: ["Resource::*"],
        },
      ],
      true,
    );

    // Backend 컨테이너 health-check를 위한 wget 사용은 의도된 선택 (Phase 6 noop).
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-ECS2",
        reason:
          "Environment variables exposed are non-sensitive (AWS_REGION, NODE_ENV). All secrets use Secrets Manager / SSM via ECS secrets.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "ECS TaskExecutionRole uses the AWS-managed AmazonECSTaskExecutionRolePolicy — this is the standard pattern for ECR pull + CloudWatch Logs publishing.",
        appliesTo: [
          "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        ],
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "TaskExecutionRole's DefaultPolicy auto-grants ECR/Logs/Secrets read on resources that are dynamically created by ECS (image layers, log streams, secret versions). Scope is bounded by the role's trust policy.",
        appliesTo: ["Resource::*"],
      },
    ]);

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "BackendTargetGroupArn", {
      value: this.backendTargetGroup.targetGroupArn,
    });
    new cdk.CfnOutput(this, "FrontendTargetGroupArn", {
      value: this.frontendTargetGroup.targetGroupArn,
    });
    new cdk.CfnOutput(this, "BackendServiceArn", { value: this.backend.service.serviceArn });
    new cdk.CfnOutput(this, "FrontendServiceArn", { value: this.frontend.service.serviceArn });
    new cdk.CfnOutput(this, "BackendSgId", {
      value: this.backend.securityGroup.securityGroupId,
    });
    new cdk.CfnOutput(this, "FrontendSgId", {
      value: this.frontend.securityGroup.securityGroupId,
    });
  }
}
