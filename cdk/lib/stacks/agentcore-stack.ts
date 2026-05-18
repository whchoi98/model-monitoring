// AgentCoreStack - AgentCore Memory + backend invoke용 IAM 정책 + SSM 참조.
//
// Phase 5 범위 결정 (사용자 옵션 A):
//   - AgentCore Memory만 생성. Runtime은 후속 Phase로 이연.
//   - backend ECS 컨테이너가 boto3/Strands SDK로 Bedrock과 Memory를 직접 호출.
//   - 채팅 흐름:
//       1) backend가 user 메시지 수신 → Memory에 CreateEvent
//       2) backend가 Bedrock InvokeModel(Sonnet 4.6)로 응답 생성, 필요시 자체 tool 호출
//       3) backend가 assistant 메시지 → Memory에 CreateEvent
//
// 후속 Phase 가능성:
//   - AgentCore Runtime (agent 컨테이너 + CfnRuntime + Endpoint)
//   - AgentCore Gateway (외부 tool target 정의)
import * as cdk from "aws-cdk-lib";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export type AgentCoreStackProps = cdk.StackProps;

export class AgentCoreStack extends cdk.Stack {
  public readonly memory: bedrockagentcore.CfnMemory;
  public readonly memoryAccessPolicy: iam.ManagedPolicy;
  public readonly memoryIdParam: ssm.IStringParameter;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // AgentCore Memory - 채팅 세션 기록.
    //   - eventExpiryDuration: 30일 (사용자 대화 보존 기간, OOS-6 검색 미지원).
    //   - 별도 memory execution role 없이 기본 동작 사용.
    // ---------------------------------------------------------------------
    this.memory = new bedrockagentcore.CfnMemory(this, "ChatMemory", {
      name: "BedrockMonitorChatMemory",
      description: "Conversation memory for the Bedrock Monitor chatbot",
      eventExpiryDuration: 30,
    });

    // ---------------------------------------------------------------------
    // IAM Managed Policy - backend ECS Task Role에 첨부될 권한.
    //   - 특정 Memory ID로 scope된 read/write 권한.
    //   - bedrock:InvokeModel*, bedrock:InvokeModelWithResponseStream은 별도 attach.
    // ---------------------------------------------------------------------
    this.memoryAccessPolicy = new iam.ManagedPolicy(this, "MemoryAccessPolicy", {
      managedPolicyName: "BedrockMonitorAgentCoreMemoryAccess",
      description: "Allows the backend to read/write AgentCore Memory events for the chatbot",
      statements: [
        new iam.PolicyStatement({
          sid: "MemoryReadWrite",
          effect: iam.Effect.ALLOW,
          actions: [
            "bedrock-agentcore:CreateEvent",
            "bedrock-agentcore:GetEvent",
            "bedrock-agentcore:ListEvents",
            "bedrock-agentcore:DeleteEvent",
            "bedrock-agentcore:RetrieveMemoryRecords",
            "bedrock-agentcore:GetMemoryRecord",
            "bedrock-agentcore:ListMemoryRecords",
            "bedrock-agentcore:ListSessions",
            "bedrock-agentcore:ListActors",
          ],
          // Memory ARN과 그 하위 session/event 리소스로 제한.
          resources: [
            this.memory.attrMemoryArn,
            `${this.memory.attrMemoryArn}/*`,
          ],
        }),
      ],
    });

    // wildcard 사용 사유: Memory의 event/session sub-resource는 동적 생성되며
    // 사전에 ARN을 알 수 없다. Memory 자체 ARN으로 path-prefix 한정 → 다른 Memory에는 접근 불가.
    NagSuppressions.addResourceSuppressions(this.memoryAccessPolicy, [
      {
        id: "AwsSolutions-IAM5",
        reason:
          "Memory's child resources (events, sessions) are dynamic and addressed by ARN path under the specific Memory ARN. The wildcard is scoped to this Memory only.",
        appliesTo: ["Resource::<ChatMemory.MemoryArn>/*"],
      },
    ]);

    // ---------------------------------------------------------------------
    // SSM Parameter - backend가 런타임에 Memory ID를 읽어가도록 노출.
    // ---------------------------------------------------------------------
    this.memoryIdParam = new ssm.StringParameter(this, "MemoryIdParam", {
      parameterName: "/bedrock-monitor/agentcore-memory-id",
      stringValue: this.memory.attrMemoryId,
      description: "AgentCore Memory ID for the chatbot conversation store",
    });

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "MemoryId", { value: this.memory.attrMemoryId });
    new cdk.CfnOutput(this, "MemoryArn", { value: this.memory.attrMemoryArn });
    new cdk.CfnOutput(this, "MemoryAccessPolicyArn", {
      value: this.memoryAccessPolicy.managedPolicyArn,
    });
    new cdk.CfnOutput(this, "MemoryIdParamName", { value: this.memoryIdParam.parameterName });
  }
}
