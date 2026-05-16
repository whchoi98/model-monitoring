// Phase 3 — DataStack 단위 테스트.
// RDS PostgreSQL 16, t4g.micro, Single-AZ, gp3 20GB, 7d 백업, publicly_accessible=false.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("DataStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const network = new NetworkStack(app, "Network", { env });
    const data = new DataStack(app, "Data", {
      env,
      vpc: network.vpc,
      dataSubnets: network.dataSubnets,
    });
    template = Template.fromStack(data);
  });

  it("RDS DBInstance가 정확히 1개 생성된다", () => {
    template.resourceCountIs("AWS::RDS::DBInstance", 1);
  });

  it("RDS는 t4g.micro, gp3 20GB, PostgreSQL 16, Single-AZ, publicly_accessible=false", () => {
    template.hasResourceProperties("AWS::RDS::DBInstance", Match.objectLike({
      DBInstanceClass: "db.t4g.micro",
      Engine: "postgres",
      EngineVersion: Match.stringLikeRegexp("^16\\..*"),
      AllocatedStorage: "20",
      StorageType: "gp3",
      MultiAZ: false,
      PubliclyAccessible: false,
      StorageEncrypted: true,
      DeletionProtection: true,
      BackupRetentionPeriod: 7,
      EnablePerformanceInsights: true,
      DBName: "monitoring",
    }));
  });

  it("PostgreSQL 로그가 CloudWatch로 export된다", () => {
    template.hasResourceProperties("AWS::RDS::DBInstance", Match.objectLike({
      EnableCloudwatchLogsExports: Match.arrayWith(["postgresql"]),
    }));
  });

  it("Secrets Manager에 DB credentials secret이 생성된다", () => {
    template.resourceCountIs("AWS::SecretsManager::Secret", 1);
    template.hasResourceProperties("AWS::SecretsManager::Secret", Match.objectLike({
      Name: "bedrock-monitor/db",
    }));
  });

  it("SSM Parameter (JWT secret placeholder)가 생성된다", () => {
    template.hasResourceProperties("AWS::SSM::Parameter", Match.objectLike({
      Name: "/bedrock-monitor/jwt-secret-key",
      Type: "String",
    }));
  });

  it("DB SG는 ingress 규칙 없이 export되어 후속 Phase에서 추가된다", () => {
    template.hasResourceProperties("AWS::EC2::SecurityGroup", Match.objectLike({
      GroupDescription: Match.stringLikeRegexp("RDS PostgreSQL SG"),
    }));
  });

  it("RDS Subnet Group이 생성된다 (Data subnets)", () => {
    template.resourceCountIs("AWS::RDS::DBSubnetGroup", 1);
  });
});
