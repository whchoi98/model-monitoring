// Phase 1 골격 테스트 — 모든 스택이 빈 템플릿으로라도 합성되는지 확인.
import * as cdk from "aws-cdk-lib";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { EdgeStack } from "../lib/stacks/edge-stack";
import { SchedulerStack } from "../lib/stacks/scheduler-stack";
import { ObservabilityStack } from "../lib/stacks/observability-stack";

describe("Phase 1: stack skeleton", () => {
  it("모든 8개 스택이 합성 단계에서 예외 없이 인스턴스화된다", () => {
    const app = new cdk.App();
    const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };
    expect(() => new NetworkStack(app, "Network", { env })).not.toThrow();
    expect(() => new DataStack(app, "Data", { env })).not.toThrow();
    expect(() => new ClusterStack(app, "Cluster", { env })).not.toThrow();
    expect(() => new AgentCoreStack(app, "AgentCore", { env })).not.toThrow();
    expect(() => new AppServicesStack(app, "AppServices", { env })).not.toThrow();
    expect(() => new EdgeStack(app, "Edge", { env })).not.toThrow();
    expect(() => new SchedulerStack(app, "Scheduler", { env })).not.toThrow();
    expect(() => new ObservabilityStack(app, "Observability", { env })).not.toThrow();
  });
});
