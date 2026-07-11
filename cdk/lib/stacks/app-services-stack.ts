// AppServicesStack - frontend / backend Fargate Service 2개 + IAM 4개 + SG 매트릭스 + TG 2개 +
// Internal ALB (HTTPS only) + ALB access logs S3 bucket.
//
// ALB가 본 스택에 함께 있는 이유:
//   - ECS Service.attachToApplicationTargetGroup이 Listener 생성에 자동 의존성을 추가하여
//     ALB를 별도 스택에 두면 순환 참조가 발생.
//   - 같은 스택에 두면 CDK가 단일 스택 내 dependency tree로 자연스럽게 해결.
//
// 주요 흐름:
//   - DataStack의 dbSecurityGroup에 backend SG로부터 5432 ingress 추가 (cross-stack).
//   - AgentCoreStack의 memoryAccessPolicy를 BackendTaskRole에 attach.
//   - ALB SG  to  backend/frontend SG ingress는 본 스택 내에서 추가 (cycle 없음).
//   - 컨테이너 이미지: ECR 'latest' tag (배포 시점에 사전 push 필요).
import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";
import { FargateServiceConstruct } from "../constructs/fargate-service";

export interface AppServicesStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly appSubnets: ec2.SubnetSelection;
  /** ALB가 internet-facing이면 Public 서브넷 필요. 미주입 시 ALB는 internal scheme으로 fallback. */
  readonly publicSubnets?: ec2.SubnetSelection;
  /** ALB ingress를 CloudFront managed prefix list로 한정 (CF to ALB 보안 패턴). 미주입 시 internal ALB. */
  readonly cloudFrontPrefixListId?: string;
  readonly cluster: ecs.ICluster;
  readonly backendRepo: ecr.IRepository;
  readonly frontendRepo: ecr.IRepository;
  readonly dbSecret: secretsmanager.ISecret;
  readonly dbSecurityGroup: ec2.ISecurityGroup;
  readonly jwtSecretParam: ssm.IStringParameter;
  readonly agentCoreMemoryAccessPolicy: iam.IManagedPolicy;
  readonly agentCoreMemoryIdParam: ssm.IStringParameter;
  /** ALB HTTPS:443 listener용 ACM 인증서 ARN. 미주입 시 synth용 placeholder. */
  readonly albCertificateArn?: string;
}

export class AppServicesStack extends cdk.Stack {
  public readonly backend: FargateServiceConstruct;
  public readonly frontend: FargateServiceConstruct;
  public readonly backendService: ecs.FargateService;
  public readonly frontendService: ecs.FargateService;
  public readonly backendTargetGroup: elbv2.IApplicationTargetGroup;
  public readonly frontendTargetGroup: elbv2.IApplicationTargetGroup;
  public readonly backendSecurityGroup: ec2.ISecurityGroup;
  public readonly frontendSecurityGroup: ec2.ISecurityGroup;
  public readonly alb: elbv2.ApplicationLoadBalancer;
  public readonly albSecurityGroup: ec2.SecurityGroup;
  public readonly albLogsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: AppServicesStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // backend Task Role - Bedrock + AgentCore Memory + SSM + Secrets + SES.
    // ---------------------------------------------------------------------
    const backendTaskRoleStatements: iam.PolicyStatement[] = [
      new iam.PolicyStatement({
        sid: "BedrockInvokeModel",
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        // global.* inference profile은 cross-region 라우팅이라 region-less foundation-model
        // ARN (arn:aws:bedrock:::foundation-model/*) 권한도 필요. 모든 region scope 허용.
        resources: [
          `arn:aws:bedrock:*::foundation-model/*`,
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
        ],
      }),
      new iam.PolicyStatement({
        // messages_mantle 패리티 프로브 (v2.13.0) — 수동 트리거는 backend 프로세스에서
        // 실행되므로 backend role에도 동일 권한 필요 (SigV4 파생 bearer가 롤 권한 사용).
        sid: "BedrockMantleInference",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock-mantle:CreateInference"],
        resources: [`arn:aws:bedrock-mantle:*:${this.account}:project/*`],
      }),
      new iam.PolicyStatement({
        // bearer 인증 흐름의 두 번째 필수 액션 — 403 실측상 resource scope가 * 뿐.
        sid: "BedrockMantleBearer",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock-mantle:CallWithBearerToken"],
        resources: ["*"],
      }),
      new iam.PolicyStatement({
        sid: "SESSendEmail",
        effect: iam.Effect.ALLOW,
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: ["*"], // SES API에는 리소스 ARN scope이 제한적임.
      }),
      new iam.PolicyStatement({
        sid: "BedrockOptimizePrompt",
        effect: iam.Effect.ALLOW,
        // bedrock-agent-runtime의 OptimizePrompt API - foundation-model ARN 단위 권한.
        actions: ["bedrock:OptimizePrompt"],
        resources: [`arn:aws:bedrock:*::foundation-model/*`],
      }),
    ];

    // ---------------------------------------------------------------------
    // backend 컨테이너 비밀/환경.
    // ---------------------------------------------------------------------
    // SEED_ADMIN_PASSWORD는 외부에서 사전 생성된 SSM SecureString을 import (보안 정책).
    const seedAdminPasswordParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "SeedAdminPasswordParam",
      { parameterName: "/bedrock-monitor/seed-admin-password" },
    );

    // Claude Platform on AWS (Path 3 External) - vendor endpoint.
    // 사용자가 사전에 SSM SecureString으로 생성. 없어도 동작 (Bedrock 12개만 모니터링).
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

    // OpenAI 1P direct / api.openai.com (Path 5) - 별도 OpenAI platform 키(sk-proj-…). 없어도 동작.
    const openai1pApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "OpenAi1pApiKeyParam",
      { parameterName: "/bedrock-monitor/openai-1p-api-key" },
    );

    const backendSecrets: Record<string, ecs.Secret> = {
      // DATABASE_URL은 backend/database.py가 DB_USER/PASSWORD/HOST/PORT/NAME 으로 직접 조립한다.
      DB_USER: ecs.Secret.fromSecretsManager(props.dbSecret, "username"),
      DB_PASSWORD: ecs.Secret.fromSecretsManager(props.dbSecret, "password"),
      DB_HOST: ecs.Secret.fromSecretsManager(props.dbSecret, "host"),
      DB_PORT: ecs.Secret.fromSecretsManager(props.dbSecret, "port"),
      DB_NAME: ecs.Secret.fromSecretsManager(props.dbSecret, "dbname"),
      JWT_SECRET_KEY: ecs.Secret.fromSsmParameter(props.jwtSecretParam),
      AGENTCORE_MEMORY_ID: ecs.Secret.fromSsmParameter(props.agentCoreMemoryIdParam),
      SEED_ADMIN_PASSWORD: ecs.Secret.fromSsmParameter(seedAdminPasswordParam),
      ANTHROPIC_API_KEY: ecs.Secret.fromSsmParameter(anthropicApiKeyParam),
      ANTHROPIC_WORKSPACE_ID: ecs.Secret.fromSsmParameter(anthropicWorkspaceIdParam),
      OPENAI_API_KEY: ecs.Secret.fromSsmParameter(openaiApiKeyParam),
      OPENAI_1P_API_KEY: ecs.Secret.fromSsmParameter(openai1pApiKeyParam),
    };

    const backendEnv: Record<string, string> = {
      AWS_REGION: this.region,
      PYTHONUNBUFFERED: "1",
      OPENAI_US_EAST_1_BASE_URL: "https://bedrock-mantle.us-east-1.api.aws/openai/v1",
      OPENAI_US_EAST_2_BASE_URL: "https://bedrock-mantle.us-east-2.api.aws/openai/v1",
      OPENAI_US_WEST_2_BASE_URL: "https://bedrock-mantle.us-west-2.api.aws/openai/v1",
      BEDROCK_OPENAI_GPT_54_MODEL_ID: "openai.gpt-5.4",
      BEDROCK_OPENAI_GPT_55_MODEL_ID: "openai.gpt-5.5",
      // 1P direct — native ids (접두사 없음). base_url은 코드 기본값(api.openai.com) 사용.
      OPENAI_1P_GPT_54_MODEL_ID: "gpt-5.4",
      OPENAI_1P_GPT_55_MODEL_ID: "gpt-5.5",
    };

    // ---------------------------------------------------------------------
    // 이미지 고정 (2026-07-09 실사고 재발 방지 — pinned-image.ts 참고).
    // context 미지정 시 legacy repo:latest로 synth는 가능하지만, 운영 배포에서는 반드시
    // -c backendImage/-c frontendImage로 digest URI를 주입할 것 (runbook §3).
    // ---------------------------------------------------------------------
    const backendImage = this.node.tryGetContext("backendImage") as string | undefined;
    const frontendImage = this.node.tryGetContext("frontendImage") as string | undefined;
    if (!backendImage || !frontendImage) {
      cdk.Annotations.of(this).addWarning(
        "backendImage/frontendImage context 미지정 — legacy :latest 참조로 synth됨. " +
          "운영 배포 시 반드시 -c backendImage=<uri@digest> -c frontendImage=<uri@digest> 주입 " +
          "(미주입 배포는 서비스를 옛 이미지로 되돌린다).",
      );
    }

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
      imageOverride: backendImage,
      containerPort: 8000,
      healthCheckPath: "/api/health",
      environment: backendEnv,
      secrets: backendSecrets,
      taskRolePolicies: [props.agentCoreMemoryAccessPolicy],
      taskRoleStatements: backendTaskRoleStatements,
    });

    // ---------------------------------------------------------------------
    // frontend Service - 권한 없음.
    // ---------------------------------------------------------------------
    this.frontend = new FargateServiceConstruct(this, "Frontend", {
      serviceName: "frontend",
      cluster: props.cluster,
      vpc: props.vpc,
      appSubnets: props.appSubnets,
      repository: props.frontendRepo,
      imageTag: "latest",
      imageOverride: frontendImage,
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
    this.backendSecurityGroup = this.backend.securityGroup;
    this.frontendSecurityGroup = this.frontend.securityGroup;
    this.backendService = this.backend.service;
    this.frontendService = this.frontend.service;

    // ---------------------------------------------------------------------
    // ALB - internal scheme (Private Subnet). CloudFront VPC Origin이 ENI를 만들어 접근.
    //   사용자 요구: "CF - Prefix List SG - ALB (Private Subnet)" 구조.
    //   ALB SG는 VPC CIDR HTTPS:443 허용 (VPC Origin ENI도 VPC 내부 IP를 가짐).
    // ---------------------------------------------------------------------
    this.albSecurityGroup = new ec2.SecurityGroup(this, "AlbSg", {
      vpc: props.vpc,
      description: "Internal ALB SG - VPC HTTPS 443 (CloudFront VPC Origin reaches via ENI)",
      allowAllOutbound: false,
    });
    this.albSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      "VPC internal HTTPS to ALB",
    );
    // NOTE: NFR-1 (HTTP listener 금지) 일시 완화 - 운영 cert 정착 전까지 CloudFront
    // VPC Origin이 HTTP로 origin 호출하도록 80도 허용. ALB는 internal + private
    // subnet이라 외부 인터넷에서 도달 불가.
    this.albSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(80),
      "VPC internal HTTP to ALB (temporary until cert in place)",
    );
    this.albSecurityGroup.addEgressRule(
      this.backend.securityGroup,
      ec2.Port.tcp(8000),
      "ALB  to  Backend",
    );
    this.albSecurityGroup.addEgressRule(
      this.frontend.securityGroup,
      ec2.Port.tcp(3000),
      "ALB  to  Frontend",
    );
    this.backend.securityGroup.addIngressRule(
      this.albSecurityGroup,
      ec2.Port.tcp(8000),
      "Internal ALB  to  Backend",
    );
    this.frontend.securityGroup.addIngressRule(
      this.albSecurityGroup,
      ec2.Port.tcp(3000),
      "Internal ALB  to  Frontend",
    );

    // ALB access logs S3 bucket.
    this.albLogsBucket = new s3.Bucket(this, "AlbLogsBucket", {
      bucketName: `bedrock-monitor-alb-logs-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [{ expiration: cdk.Duration.days(90) }],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.alb = new elbv2.ApplicationLoadBalancer(this, "InternalAlb", {
      vpc: props.vpc,
      internetFacing: false,
      vpcSubnets: props.appSubnets, // 항상 Private Subnet
      securityGroup: this.albSecurityGroup,
      dropInvalidHeaderFields: true,
    });
    this.alb.logAccessLogs(this.albLogsBucket, "alb");

    // 인증서 - context 미주입 시 placeholder (synth만 가능, deploy 시 실 cert 필요).
    const albCertArn =
      props.albCertificateArn ??
      `arn:aws:acm:${this.region}:${this.account}:certificate/00000000-0000-0000-0000-000000000000`;
    const albCert = acm.Certificate.fromCertificateArn(this, "AlbCert", albCertArn);

    const httpsListener = this.alb.addListener("HttpsListener", {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      sslPolicy: elbv2.SslPolicy.TLS13_RES,
      certificates: [albCert],
      defaultAction: elbv2.ListenerAction.forward([this.frontendTargetGroup]),
    });
    // HTTP:80 listener - 운영 cert 정착 전까지 CloudFront origin HTTP 호출을 받기 위한 임시.
    // 외부 도달 불가 (ALB internal scheme + Private Subnet + SG VPC CIDR 한정).
    const httpListener = this.alb.addListener("HttpListener", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.forward([this.frontendTargetGroup]),
    });
    httpListener.addAction("ApiRouteHttp", {
      priority: 10,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/api/*"])],
      action: elbv2.ListenerAction.forward([this.backendTargetGroup]),
    });

    httpsListener.addAction("ApiRoute", {
      priority: 10,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/api/*"])],
      action: elbv2.ListenerAction.forward([this.backendTargetGroup]),
    });

    // ---------------------------------------------------------------------
    // SG cross-stack ingress - backend SG  to  RDS SG :5432.
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
      description: "Backend ECS to RDS PostgreSQL",
    });

    // ---------------------------------------------------------------------
    // cdk-nag suppressions.
    //   - IAM5 (Bedrock foundation-model/*): wildcard는 region scope 내 모든 모델 ID 허용.
    //     동적 모델 추가 시 자동 적용 - spec FR-1의 9 모델 + Sonnet 4.6 모두 포함.
    //   - IAM5 (SES resources:*): SES는 ARN scope이 제한적이므로 *.
    //   - ECS4 (Container Insights): 클러스터에서 활성화 (ClusterStack), 본 스택은 그대로 사용.
    // ---------------------------------------------------------------------
    NagSuppressions.addResourceSuppressions(
      this.backend.taskRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "global.* inference profile는 cross-region 라우팅을 사용하므로 region-less foundation-model ARN과 region wildcard inference-profile ARN을 모두 허용. 다른 계정/서비스는 IAM trust로 제한됨.",
          appliesTo: [
            `Resource::arn:aws:bedrock:*::foundation-model/*`,
            `Resource::arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
            `Resource::arn:aws:bedrock:*:${this.account}:inference-profile/*`,
            // messages_mantle 수동 트리거 (v2.13.0) — 계정 scope project/* 로 제한.
            `Resource::arn:aws:bedrock-mantle:*:${this.account}:project/*`,
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
          "ECS TaskExecutionRole uses the AWS-managed AmazonECSTaskExecutionRolePolicy - this is the standard pattern for ECR pull + CloudWatch Logs publishing.",
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
      {
        id: "AwsSolutions-EC23",
        reason:
          "ALB is internal scheme - the 0.0.0.0/0 rule auto-added by HTTPS listener is restricted to traffic within the VPC and reachable only via CloudFront VPC Origin ENIs in EdgeStack. AWS does not allow us to restrict the ALB SG to a specific VPC Origin SG.",
      },
      {
        id: "AwsSolutions-S1",
        reason:
          "ALB access logs bucket stores logs FROM the ALB; enabling its own S3 server access logs would create a recursive sink. ALB access logging is sufficient observability.",
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
    new cdk.CfnOutput(this, "AlbDns", { value: this.alb.loadBalancerDnsName });
    new cdk.CfnOutput(this, "AlbArn", { value: this.alb.loadBalancerArn });
    new cdk.CfnOutput(this, "AlbSgId", { value: this.albSecurityGroup.securityGroupId });
  }
}
