// 스택 골격 테스트 — 8개 스택이 합성 단계에서 예외 없이 인스턴스화되는지 확인.
import * as cdk from "aws-cdk-lib";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { EdgeStack } from "../lib/stacks/edge-stack";
import { SchedulerStack } from "../lib/stacks/scheduler-stack";
import { ObservabilityStack } from "../lib/stacks/observability-stack";

describe("스택 골격", () => {
  it("모든 8개 스택이 합성 단계에서 예외 없이 인스턴스화된다", () => {
    const app = new cdk.App();
    const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };
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
    expect(
      () => new EdgeStack(app, "Edge", { env, alb: appServices.alb }),
    ).not.toThrow();
    expect(
      () =>
        new SchedulerStack(app, "Scheduler", {
          env,
          vpc: network.vpc,
          appSubnets: network.appSubnets,
          cluster: cluster.cluster,
          backendRepo: cluster.backendRepo,
          dbSecret: data.dbSecret,
          dbSecurityGroup: data.dbSecurityGroup,
          jwtSecretParam: data.jwtSecretParam,
          agentCoreMemoryIdParam: agentCore.memoryIdParam,
          agentCoreMemoryAccessPolicy: agentCore.memoryAccessPolicy,
        }),
    ).not.toThrow();
    expect(() => new ObservabilityStack(app, "Observability", { env })).not.toThrow();
  });
});
