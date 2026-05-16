// SchedulerStack — Phase 9에서 EventBridge Scheduler + AutoProber/Insights TaskDef 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type SchedulerStackProps = cdk.StackProps;

export class SchedulerStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SchedulerStackProps) {
    super(scope, id, props);
    // Phase 9 작업 영역 — rate(5 min): AutoProber, rate(30 min): Insights.
  }
}
