// EdgeStack 단위 테스트 - VPC Origin to Internal ALB.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { EdgeStack } from "../lib/stacks/edge-stack";

const env: cdk.Environment = { account: "111111111111", region: "ap-northeast-2" };

describe("EdgeStack (VPC Origin + Internal ALB)", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const network = new NetworkStack(app, "Network", { env });
    const data = new DataStack(app, "Data", {
      env,
      vpc: network.vpc,
      dataSubnets: network.dataSubnets,
    });
    const cluster = new ClusterStack(app, "Cluster", { env, vpc: network.vpc });
    const agentCore = new AgentCoreStack(app, "AgentCore", { env });
    const appServices = new AppServicesStack(app, "AppServices", {
      env,
      vpc: network.vpc,
      appSubnets: network.appSubnets,
      cluster: cluster.cluster,
      backendRepo: cluster.backendRepo,
      frontendRepo: cluster.frontendRepo,
      dbSecret: data.dbSecret,
      dbSecurityGroup: data.dbSecurityGroup,
      jwtSecretParam: data.jwtSecretParam,
      agentCoreMemoryAccessPolicy: agentCore.memoryAccessPolicy,
      agentCoreMemoryIdParam: agentCore.memoryIdParam,
    });
    const edge = new EdgeStack(app, "Edge", { env, alb: appServices.alb });
    template = Template.fromStack(edge);
  });

  it("CloudFront Distribution이 1개 생성된다", () => {
    template.resourceCountIs("AWS::CloudFront::Distribution", 1);
  });

  it("CloudFront VpcOrigin이 https-only protocol을 사용한다", () => {
    template.hasResourceProperties("AWS::CloudFront::VpcOrigin", Match.objectLike({
      VpcOriginEndpointConfig: Match.objectLike({ OriginProtocolPolicy: "https-only" }),
    }));
  });

  it("Distribution의 /api/* behavior가 정의된다", () => {
    template.hasResourceProperties("AWS::CloudFront::Distribution", Match.objectLike({
      DistributionConfig: Match.objectLike({
        CacheBehaviors: Match.arrayWith([
          Match.objectLike({ PathPattern: "/api/*" }),
        ]),
      }),
    }));
  });

  it("Distribution은 access logs를 활성화한다", () => {
    template.hasResourceProperties("AWS::CloudFront::Distribution", Match.objectLike({
      DistributionConfig: Match.objectLike({
        Logging: Match.objectLike({ Bucket: Match.anyValue() }),
      }),
    }));
  });

  it("CloudFront logs S3 버킷 1개 (Block public)", () => {
    template.resourceCountIs("AWS::S3::Bucket", 1);
    template.hasResourceProperties("AWS::S3::Bucket", Match.objectLike({
      PublicAccessBlockConfiguration: Match.objectLike({
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
      }),
    }));
  });
});
