// AgentCoreStack — Phase 5에서 AgentCore Memory + Agent Runtime + Gateway tools 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type AgentCoreStackProps = cdk.StackProps;

export class AgentCoreStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    // Phase 5 작업 영역 — Memory, Runtime (Claude Sonnet 4.6), Gateway with 4 tools.
  }
}
