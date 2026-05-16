// FargateService 공통 Construct — frontend / backend Service 공통 패턴을 캡슐화.
//
// 책임:
//   - TaskDefinition (vCPU 512, 메모리 1024) + 컨테이너 단일 정의
//   - awsvpc 모드 Service
//   - per-Service SG (ingress는 본 construct 외부에서 부여 — ALB가 Phase 7에서 추가)
//   - CloudWatch Logs (logGroup은 본 construct에서 생성, 보존 정책은 Phase 11에서 조정)
//   - Application Target Group (target_type=ip)
//   - AutoScaling 1~3 (CPU 70% 트리거)
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";

export interface FargateServiceProps {
  readonly serviceName: string;
  readonly cluster: ecs.ICluster;
  readonly vpc: ec2.IVpc;
  readonly appSubnets: ec2.SubnetSelection;
  readonly repository: ecr.IRepository;
  readonly imageTag: string;
  readonly containerPort: number;
  readonly healthCheckPath: string;
  /** 컨테이너에 노출할 환경 변수 (비밀이 아닌 평문). */
  readonly environment?: Record<string, string>;
  /** Secrets Manager / SSM 비밀 참조. */
  readonly secrets?: Record<string, ecs.Secret>;
  /** Task가 호출할 AWS 리소스 권한이 필요한 경우. */
  readonly taskRolePolicies?: iam.IManagedPolicy[];
  readonly taskRoleStatements?: iam.PolicyStatement[];
  readonly cpu?: number; // default 512
  readonly memoryMiB?: number; // default 1024
  readonly desiredCount?: number; // default 1
  readonly maxCapacity?: number; // default 3
}

export class FargateServiceConstruct extends Construct {
  public readonly service: ecs.FargateService;
  public readonly taskDefinition: ecs.FargateTaskDefinition;
  public readonly securityGroup: ec2.SecurityGroup;
  public readonly logGroup: logs.LogGroup;
  public readonly targetGroup: elbv2.ApplicationTargetGroup;
  public readonly taskRole: iam.Role;
  public readonly executionRole: iam.Role;

  constructor(scope: Construct, id: string, props: FargateServiceProps) {
    super(scope, id);

    // ---------------------------------------------------------------------
    // 로그 그룹 — 보존 정책은 ObservabilityStack(Phase 11)에서 LogRetention으로 조정.
    // ---------------------------------------------------------------------
    this.logGroup = new logs.LogGroup(this, "LogGroup", {
      logGroupName: `/ecs/${props.serviceName}`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ---------------------------------------------------------------------
    // IAM Roles — TaskExecutionRole (이미지 pull, 로그 쓰기) + TaskRole (앱 권한).
    // ---------------------------------------------------------------------
    this.executionRole = new iam.Role(this, "ExecRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AmazonECSTaskExecutionRolePolicy"),
      ],
      description: `Execution role for ${props.serviceName} (ECR pull + CloudWatch Logs)`,
    });

    this.taskRole = new iam.Role(this, "TaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Application role for ${props.serviceName} task`,
    });
    if (props.taskRolePolicies) {
      for (const policy of props.taskRolePolicies) {
        this.taskRole.addManagedPolicy(policy);
      }
    }
    if (props.taskRoleStatements) {
      for (const stmt of props.taskRoleStatements) {
        this.taskRole.addToPolicy(stmt);
      }
    }

    // ---------------------------------------------------------------------
    // TaskDefinition — single container.
    // ---------------------------------------------------------------------
    this.taskDefinition = new ecs.FargateTaskDefinition(this, "TaskDef", {
      cpu: props.cpu ?? 512,
      memoryLimitMiB: props.memoryMiB ?? 1024,
      executionRole: this.executionRole,
      taskRole: this.taskRole,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    this.taskDefinition.addContainer("App", {
      image: ecs.ContainerImage.fromEcrRepository(props.repository, props.imageTag),
      containerName: props.serviceName,
      portMappings: [{ containerPort: props.containerPort, protocol: ecs.Protocol.TCP }],
      environment: props.environment,
      secrets: props.secrets,
      logging: ecs.LogDrivers.awsLogs({
        logGroup: this.logGroup,
        streamPrefix: props.serviceName,
      }),
      healthCheck: {
        // Service 자체 health check (curl + sh 둘 다 슬림 이미지에 없을 수 있어 wget로 통일).
        command: [
          "CMD-SHELL",
          `wget -q -O - http://localhost:${props.containerPort}${props.healthCheckPath} >/dev/null 2>&1 || exit 1`,
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(30),
      },
    });

    // ---------------------------------------------------------------------
    // Service SG — ingress 없음 (Phase 7 EdgeStack이 ALB SG로부터 추가).
    // ---------------------------------------------------------------------
    this.securityGroup = new ec2.SecurityGroup(this, "Sg", {
      vpc: props.vpc,
      description: `${props.serviceName} task SG (ingress added by EdgeStack)`,
      allowAllOutbound: true,
    });

    // ---------------------------------------------------------------------
    // Fargate Service.
    // ---------------------------------------------------------------------
    this.service = new ecs.FargateService(this, "Service", {
      cluster: props.cluster,
      serviceName: props.serviceName,
      taskDefinition: this.taskDefinition,
      desiredCount: props.desiredCount ?? 1,
      vpcSubnets: props.appSubnets,
      securityGroups: [this.securityGroup],
      assignPublicIp: false,
      enableExecuteCommand: false,
      minHealthyPercent: 50,
      maxHealthyPercent: 200,
      circuitBreaker: { rollback: true },
    });

    // ---------------------------------------------------------------------
    // Application Target Group — Phase 7에서 ALB listener에 연결.
    // ---------------------------------------------------------------------
    this.targetGroup = new elbv2.ApplicationTargetGroup(this, "Tg", {
      vpc: props.vpc,
      port: props.containerPort,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        path: props.healthCheckPath,
        port: String(props.containerPort),
        protocol: elbv2.Protocol.HTTP,
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(20),
    });
    this.service.attachToApplicationTargetGroup(this.targetGroup);

    // ---------------------------------------------------------------------
    // AutoScaling — CPU 70% 트리거, 1~maxCapacity.
    // ---------------------------------------------------------------------
    const scaling = this.service.autoScaleTaskCount({
      minCapacity: props.desiredCount ?? 1,
      maxCapacity: props.maxCapacity ?? 3,
    });
    scaling.scaleOnCpuUtilization("CpuScaling", {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });
  }
}
