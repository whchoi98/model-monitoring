// ObservabilityStack — Phase 11에서 Log Groups + Alarms + Dashboard 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type ObservabilityStackProps = cdk.StackProps;

export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);
    // Phase 11 작업 영역 — /ecs/* 로그 그룹, ALB/RDS/AgentCore 알람, Dashboard.
  }
}
