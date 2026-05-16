// Phase 4 — ClusterStack 단위 테스트.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("ClusterStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const network = new NetworkStack(app, "Network", { env });
    const cluster = new ClusterStack(app, "Cluster", { env, vpc: network.vpc });
    template = Template.fromStack(cluster);
  });

  it("ECS Cluster가 정확히 1개 생성된다", () => {
    template.resourceCountIs("AWS::ECS::Cluster", 1);
  });

  it("Cluster 이름은 bedrock-monitor이고 Container Insights가 활성화된다", () => {
    template.hasResourceProperties("AWS::ECS::Cluster", Match.objectLike({
      ClusterName: "bedrock-monitor",
      ClusterSettings: Match.arrayWith([
        Match.objectLike({ Name: "containerInsights", Value: "enabled" }),
      ]),
    }));
  });

  it("ECR repo가 backend / frontend 두 개 생성된다", () => {
    template.resourceCountIs("AWS::ECR::Repository", 2);
  });

  it("ECR repo는 immutable tag + scan on push", () => {
    template.hasResourceProperties("AWS::ECR::Repository", Match.objectLike({
      ImageTagMutability: "IMMUTABLE",
      ImageScanningConfiguration: { ScanOnPush: true },
      LifecyclePolicy: Match.objectLike({
        LifecyclePolicyText: Match.stringLikeRegexp("untagged"),
      }),
    }));
  });

  it("KMS Key는 회전이 활성화되어 있다", () => {
    template.hasResourceProperties("AWS::KMS::Key", Match.objectLike({
      EnableKeyRotation: true,
    }));
  });

  it("KMS Key 정책에 CloudWatch Logs principal이 포함된다", () => {
    template.hasResourceProperties("AWS::KMS::Key", Match.objectLike({
      KeyPolicy: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: "AllowCloudWatchLogs",
            Principal: Match.objectLike({
              Service: Match.stringLikeRegexp("logs\\.us-east-1\\.amazonaws\\.com"),
            }),
          }),
        ]),
      }),
    }));
  });
});
