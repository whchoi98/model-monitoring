// DataStack - RDS PostgreSQL 16 (t4g.micro) + Secrets Manager + SSM SecureString.
//
// 보안:
//   - Single-AZ (C-7 / OOS-2: 초기 비용 최소화, 모니터링 시계열 데이터라 손실 허용).
//   - publicly_accessible=false, 격리 서브넷 배치.
//   - 저장 암호화 on (AWS managed KMS).
//   - 자격 증명은 Secrets Manager가 자동 생성/회전 가능.
//   - SG는 빈 상태로 export → Phase 6(AppServicesStack)에서 backend/autoprober/insights SG로부터 5432 ingress 추가.
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export interface DataStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly dataSubnets: ec2.SubnetSelection;
}

export class DataStack extends cdk.Stack {
  public readonly db: rds.DatabaseInstance;
  public readonly dbSecret: secretsmanager.ISecret;
  public readonly dbSecurityGroup: ec2.SecurityGroup;
  public readonly jwtSecretParam: ssm.IStringParameter;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // DB Security Group - Phase 6에서 backend/autoprober/insights SG ingress 추가.
    // ---------------------------------------------------------------------
    this.dbSecurityGroup = new ec2.SecurityGroup(this, "DbSg", {
      vpc: props.vpc,
      description: "RDS PostgreSQL SG - ingress added by AppServicesStack",
      allowAllOutbound: false,
    });

    // ---------------------------------------------------------------------
    // Secrets Manager - username 'monitoring_admin', password 자동 생성 32자.
    // ---------------------------------------------------------------------
    const dbCredentials = rds.Credentials.fromGeneratedSecret("monitoring_admin", {
      secretName: "bedrock-monitor/db",
    });

    // ---------------------------------------------------------------------
    // RDS Subnet Group - Data subnets.
    // ---------------------------------------------------------------------
    const subnetGroup = new rds.SubnetGroup(this, "DbSubnetGroup", {
      description: "Bedrock Monitor RDS subnet group (Data tier)",
      vpc: props.vpc,
      vpcSubnets: props.dataSubnets,
    });

    // ---------------------------------------------------------------------
    // RDS PostgreSQL 16, t4g.micro, gp3 20GB, Single-AZ, 7d backups.
    // ---------------------------------------------------------------------
    this.db = new rds.DatabaseInstance(this, "Postgres", {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16_8,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      vpc: props.vpc,
      subnetGroup,
      securityGroups: [this.dbSecurityGroup],
      credentials: dbCredentials,
      databaseName: "monitoring",
      // gp3 20GB는 t4g.micro의 baseline IO에 충분 (모니터링 시계열 워크로드).
      allocatedStorage: 20,
      storageType: rds.StorageType.GP3,
      multiAz: false,
      publiclyAccessible: false,
      storageEncrypted: true,
      backupRetention: cdk.Duration.days(7),
      deletionProtection: true,
      enablePerformanceInsights: true,
      performanceInsightRetention: rds.PerformanceInsightRetention.DEFAULT,
      autoMinorVersionUpgrade: true,
      // 운영자가 의도적으로 destroy 시 스냅샷 생성.
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
      // PG 로그를 CloudWatch로 (NFR-2). 보존 정책은 Phase 11(Observability)에서 설정.
      cloudwatchLogsExports: ["postgresql"],
      parameterGroup: new rds.ParameterGroup(this, "PgParams", {
        engine: rds.DatabaseInstanceEngine.postgres({
          version: rds.PostgresEngineVersion.VER_16_8,
        }),
        parameters: {
          // 한국어 로깅을 위해 client_encoding을 UTF8로 고정.
          client_encoding: "UTF8",
        },
      }),
    });

    if (!this.db.secret) {
      throw new Error("DatabaseInstance가 secret을 반환하지 않았다 - credentials 설정 확인.");
    }
    this.dbSecret = this.db.secret;

    // ---------------------------------------------------------------------
    // JWT_SECRET_KEY - 사전 생성된 SSM SecureString을 import (SEED_ADMIN_PASSWORD와 동일 패턴).
    //
    // CloudFormation은 SecureString 직접 생성 불가 + plaintext placeholder는
    // 운영자가 교체 잊을 시 JWT 위조 가능 (Kiro review high).
    // → 배포 전에 운영자가 반드시 SecureString을 만들어 두어야 한다.
    //
    // 사전 생성 명령 (1회):
    //   aws ssm put-parameter --region <region> \
    //     --name /bedrock-monitor/jwt-secret-key \
    //     --type SecureString \
    //     --value "$(openssl rand -base64 48)"
    // ---------------------------------------------------------------------
    this.jwtSecretParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "JwtSecret",
      { parameterName: "/bedrock-monitor/jwt-secret-key" },
    );

    // ---------------------------------------------------------------------
    // cdk-nag 억제.
    //   - RDS3: Single-AZ는 spec C-7/OOS-2 의도된 선택.
    //   - SMG4: 비밀 회전은 후속 Phase로 미룸 (IAM 기반 접근으로 보호).
    //   - IAM4/5 (LogRetention): CDK 내부 Lambda가 사용하는 managed policy / 와일드카드.
    // ---------------------------------------------------------------------
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-RDS3",
        reason:
          "Single-AZ is acceptable for monitoring time-series data per spec C-7/OOS-2. Multi-AZ deferred to a later phase.",
      },
      {
        id: "AwsSolutions-RDS11",
        reason:
          "Default Postgres port 5432 is acceptable - access is restricted to specific SGs (added in Phase 6). Port obfuscation is defense-in-depth, not primary control.",
      },
      {
        id: "AwsSolutions-SMG4",
        reason:
          "Automatic secret rotation deferred to a later phase. Secret access is IAM-gated and the value is auto-generated.",
      },
    ]);


    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "DbEndpoint", { value: this.db.dbInstanceEndpointAddress });
    new cdk.CfnOutput(this, "DbPort", { value: this.db.dbInstanceEndpointPort });
    new cdk.CfnOutput(this, "DbSecretArn", { value: this.dbSecret.secretArn });
    new cdk.CfnOutput(this, "DbSecurityGroupId", { value: this.dbSecurityGroup.securityGroupId });
    new cdk.CfnOutput(this, "JwtSecretParamName", { value: this.jwtSecretParam.parameterName });
  }
}
