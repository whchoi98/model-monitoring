// Phase 2 — NetworkStack 단위 테스트.
// 1) 신규 VPC 생성 모드: VPC + Endpoints + Flow Logs가 합성된다.
// 2) 기존 VPC 재사용 모드: VPC/Endpoint 생성 없이 import만 한다.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("NetworkStack (신규 VPC 생성)", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new NetworkStack(app, "Network", { env });
    template = Template.fromStack(stack);
  });

  it("VPC가 정확히 1개 생성된다", () => {
    template.resourceCountIs("AWS::EC2::VPC", 1);
  });

  it("Public / App / Data 서브넷이 AZ당 1개씩 (총 6개) 생성된다", () => {
    template.resourceCountIs("AWS::EC2::Subnet", 6);
  });

  it("NAT GW가 1개 생성된다 (단일 AZ, 비용 절감)", () => {
    template.resourceCountIs("AWS::EC2::NatGateway", 1);
  });

  it("Internet Gateway가 1개 생성된다 (Public 서브넷용)", () => {
    template.resourceCountIs("AWS::EC2::InternetGateway", 1);
  });

  it("VPC Flow Logs가 활성화된다", () => {
    template.resourceCountIs("AWS::EC2::FlowLog", 1);
  });

  it("Interface 8개 + AgentCore 1개 + S3 Gateway 1개 = 총 10개 VPC Endpoint", () => {
    template.resourceCountIs("AWS::EC2::VPCEndpoint", 10);
  });

  it("Endpoint SG는 443 ingress 규칙을 갖는다", () => {
    template.hasResourceProperties(
      "AWS::EC2::SecurityGroup",
      Match.objectLike({
        SecurityGroupIngress: Match.arrayWith([
          Match.objectLike({ FromPort: 443, ToPort: 443, IpProtocol: "tcp" }),
        ]),
      }),
    );
  });
});

describe("NetworkStack (기존 VPC 재사용)", () => {
  it("existingVpcId + subnet ID 제공 시 VPC/Endpoint를 생성하지 않는다", () => {
    const app = new cdk.App({
      context: {
        existingVpcId: "vpc-12345678",
        appSubnetIds: "subnet-aaaaaaaaaaaaaaaaa,subnet-bbbbbbbbbbbbbbbbb",
        dataSubnetIds: "subnet-ccccccccccccccccc,subnet-ddddddddddddddddd",
      },
    });
    const stack = new NetworkStack(app, "Network", { env });
    const template = Template.fromStack(stack);
    template.resourceCountIs("AWS::EC2::VPC", 0);
    template.resourceCountIs("AWS::EC2::VPCEndpoint", 0);
    template.resourceCountIs("AWS::EC2::NatGateway", 0);
  });

  it("existingVpcId만 있고 subnet 미지정 시 throw", () => {
    const app = new cdk.App({
      context: { existingVpcId: "vpc-12345678" },
    });
    expect(() => new NetworkStack(app, "Network", { env })).toThrow(
      /appSubnetIds와 dataSubnetIds context도 필요합니다/,
    );
  });
});
