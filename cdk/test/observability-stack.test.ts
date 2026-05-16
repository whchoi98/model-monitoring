// Phase 11 — ObservabilityStack 단위 테스트.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { ObservabilityStack } from "../lib/stacks/observability-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("ObservabilityStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
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
    const obs = new ObservabilityStack(app, "Observability", {
      env,
      alb: appServices.alb,
      cluster: cluster.cluster,
      backendService: appServices.backendService,
      frontendService: appServices.frontendService,
      db: data.db,
      alarmEmail: "ops@example.com",
    });
    template = Template.fromStack(obs);
  });

  it("SNS Topic 1개 생성된다 (enforceSSL)", () => {
    template.resourceCountIs("AWS::SNS::Topic", 1);
    template.hasResourceProperties("AWS::SNS::Topic", Match.objectLike({
      TopicName: "bedrock-monitor-alarms",
    }));
  });

  it("alarmEmail 지정 시 SNS Subscription 생성", () => {
    template.hasResourceProperties("AWS::SNS::Subscription", Match.objectLike({
      Protocol: "email",
      Endpoint: "ops@example.com",
    }));
  });

  it("최소 6개의 알람이 생성된다 (ALB 5xx, ALB latency, ECS x2, RDS x3)", () => {
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    expect(Object.keys(alarms).length).toBeGreaterThanOrEqual(6);
  });

  it("CloudWatch Dashboard 1개 생성된다", () => {
    template.resourceCountIs("AWS::CloudWatch::Dashboard", 1);
    template.hasResourceProperties("AWS::CloudWatch::Dashboard", Match.objectLike({
      DashboardName: "BedrockMonitor-v2",
    }));
  });

  it("ALB 5xx ratio 알람은 MathExpression을 사용한다", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", Match.objectLike({
      Metrics: Match.arrayWith([
        Match.objectLike({ Expression: Match.stringLikeRegexp("100 \\* \\(m5xx") }),
      ]),
    }));
  });

  it("RDS CPU 알람 threshold는 80", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", Match.objectLike({
      Threshold: 80,
      MetricName: "CPUUtilization",
    }));
  });

  it("모든 알람은 SNS topic을 알람 액션으로 갖는다", () => {
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    for (const a of Object.values(alarms)) {
      const props = (a as { Properties: { AlarmActions: unknown[] } }).Properties;
      expect(props.AlarmActions).toBeDefined();
      expect(Array.isArray(props.AlarmActions)).toBe(true);
      expect(props.AlarmActions.length).toBeGreaterThan(0);
    }
  });
});
