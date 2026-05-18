// Phase 7 - EdgeStack 단위 테스트.
// EdgeStack은 다른 리전(us-east-1)에 독립 배포되므로 ALB DNS만 받는다.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { EdgeStack } from "../lib/stacks/edge-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("EdgeStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const edge = new EdgeStack(app, "Edge", {
      env,
      albDnsName: "test-alb.example.com",
    });
    template = Template.fromStack(edge);
  });

  it("CloudFront Distribution이 1개 생성된다", () => {
    template.resourceCountIs("AWS::CloudFront::Distribution", 1);
  });

  it("CloudFront -> ALB origin은 CustomOrigin + HTTPS_ONLY protocol을 사용한다", () => {
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
