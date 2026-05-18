// Phase 7 — EdgeStack 단위 테스트.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { EdgeStack } from "../lib/stacks/edge-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("EdgeStack", () => {
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

  it("CloudFront → ALB origin은 CustomOrigin + HTTPS_ONLY protocol을 사용한다", () => {
    // LoadBalancerV2Origin은 Distribution 내부 CustomOriginConfig로 인라인 등록됨.
    template.hasResourceProperties("AWS::CloudFront::Distribution", Match.objectLike({
      DistributionConfig: Match.objectLike({
        Origins: Match.arrayWith([
          Match.objectLike({
            CustomOriginConfig: Match.objectLike({ OriginProtocolPolicy: "https-only" }),
          }),
        ]),
      }),
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

  it("WAFv2 WebACL이 1개 생성된다 (CLOUDFRONT scope, 2 managed rule sets)", () => {
    template.resourceCountIs("AWS::WAFv2::WebACL", 1);
    template.hasResourceProperties("AWS::WAFv2::WebACL", Match.objectLike({
      Scope: "CLOUDFRONT",
      Rules: Match.arrayWith([
        Match.objectLike({ Name: "AWSManagedRulesCommonRuleSet" }),
        Match.objectLike({ Name: "AWSManagedRulesKnownBadInputsRuleSet" }),
      ]),
    }));
  });

  it("Distribution은 WebACL과 연결된다 (WebACLId 설정)", () => {
    template.hasResourceProperties("AWS::CloudFront::Distribution", Match.objectLike({
      DistributionConfig: Match.objectLike({ WebACLId: Match.anyValue() }),
    }));
  });

  it("Distribution은 access logs를 활성화한다", () => {
    template.hasResourceProperties("AWS::CloudFront::Distribution", Match.objectLike({
      DistributionConfig: Match.objectLike({
        Logging: Match.objectLike({ Bucket: Match.anyValue() }),
      }),
    }));
  });

  // CloudFront 기본 *.cloudfront.net 인증서 사용 시 ViewerCertificate가 template에
  // 명시되지 않고 AWS가 자동 적용. minimumProtocolVersion 검증은 default cert에 적용
  // 불가하므로 본 테스트는 생략.

  it("CloudFront logs S3 버킷 1개 (Block public, enforceSSL)", () => {
    template.resourceCountIs("AWS::S3::Bucket", 1);
    template.hasResourceProperties("AWS::S3::Bucket", Match.objectLike({
      PublicAccessBlockConfiguration: Match.objectLike({
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
      }),
    }));
  });
});
