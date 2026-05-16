// Phase 5 — AgentCoreStack 단위 테스트.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("AgentCoreStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    template = Template.fromStack(new AgentCoreStack(app, "AgentCore", { env }));
  });

  it("AgentCore Memory가 1개 생성된다", () => {
    template.resourceCountIs("AWS::BedrockAgentCore::Memory", 1);
  });

  it("Memory 이름과 만료 기간이 설정된다", () => {
    template.hasResourceProperties("AWS::BedrockAgentCore::Memory", Match.objectLike({
      Name: "BedrockMonitorChatMemory",
      EventExpiryDuration: 30,
    }));
  });

  it("Memory 접근용 Managed Policy가 생성된다", () => {
    template.hasResourceProperties("AWS::IAM::ManagedPolicy", Match.objectLike({
      ManagedPolicyName: "BedrockMonitorAgentCoreMemoryAccess",
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: "MemoryReadWrite",
            Effect: "Allow",
            Action: Match.arrayWith([
              "bedrock-agentcore:CreateEvent",
              "bedrock-agentcore:RetrieveMemoryRecords",
            ]),
          }),
        ]),
      }),
    }));
  });

  it("SSM Parameter에 Memory ID가 노출된다", () => {
    template.hasResourceProperties("AWS::SSM::Parameter", Match.objectLike({
      Name: "/bedrock-monitor/agentcore-memory-id",
      Type: "String",
    }));
  });
});
