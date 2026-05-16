// Phase 6 — AppServicesStack 단위 테스트.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("AppServicesStack", () => {
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
    const app_ = new AppServicesStack(app, "AppServices", {
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
    template = Template.fromStack(app_);
  });

  it("ECS Service가 정확히 2개 생성된다", () => {
    template.resourceCountIs("AWS::ECS::Service", 2);
  });

  it("Task Definition이 2개 생성되고 awsvpc 모드를 사용한다", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 2);
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      NetworkMode: "awsvpc",
      RequiresCompatibilities: ["FARGATE"],
      Cpu: "512",
      Memory: "1024",
    }));
  });

  it("Target Group이 2개 생성되고 ip 타겟 타입을 사용한다", () => {
    template.resourceCountIs("AWS::ElasticLoadBalancingV2::TargetGroup", 2);
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::TargetGroup", Match.objectLike({
      TargetType: "ip",
      Protocol: "HTTP",
    }));
  });

  it("backend Service 컨테이너는 8000 포트, frontend는 3000 포트를 노출한다", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Name: "backend",
          PortMappings: Match.arrayWith([
            Match.objectLike({ ContainerPort: 8000 }),
          ]),
        }),
      ]),
    }));
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Name: "frontend",
          PortMappings: Match.arrayWith([
            Match.objectLike({ ContainerPort: 3000 }),
          ]),
        }),
      ]),
    }));
  });

  it("IAM Role: ExecRole × 2 + TaskRole × 2 = 4개", () => {
    // SG ingress 등 추가 Role이 있을 수 있어 최소 4개 이상.
    const roles = template.findResources("AWS::IAM::Role");
    expect(Object.keys(roles).length).toBeGreaterThanOrEqual(4);
  });

  it("backend TaskRole에 Bedrock InvokeModel 권한이 부여된다", () => {
    template.hasResourceProperties("AWS::IAM::Policy", Match.objectLike({
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: "BedrockInvokeModel",
            Action: Match.arrayWith([
              "bedrock:InvokeModel",
              "bedrock:InvokeModelWithResponseStream",
            ]),
          }),
        ]),
      }),
    }));
  });

  it("backend SG → RDS SG 5432 ingress 규칙이 추가된다", () => {
    template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", Match.objectLike({
      IpProtocol: "tcp",
      FromPort: 5432,
      ToPort: 5432,
    }));
  });

  it("Auto Scaling Target이 2개 (frontend / backend)", () => {
    template.resourceCountIs("AWS::ApplicationAutoScaling::ScalableTarget", 2);
  });

  it("Internal ALB가 1개 생성된다 (Scheme=internal)", () => {
    template.resourceCountIs("AWS::ElasticLoadBalancingV2::LoadBalancer", 1);
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::LoadBalancer", Match.objectLike({
      Scheme: "internal",
    }));
  });

  it("HTTPS:443 listener가 1개 존재하고 HTTP:80은 없다", () => {
    template.resourceCountIs("AWS::ElasticLoadBalancingV2::Listener", 1);
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::Listener", Match.objectLike({
      Port: 443,
      Protocol: "HTTPS",
    }));
    template.resourcePropertiesCountIs(
      "AWS::ElasticLoadBalancingV2::Listener",
      { Port: 80 },
      0,
    );
  });

  it("Listener Rule /api/* → priority 10 (backend TG forward)", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::ListenerRule", Match.objectLike({
      Priority: 10,
      Conditions: Match.arrayWith([
        Match.objectLike({
          Field: "path-pattern",
          PathPatternConfig: Match.objectLike({ Values: ["/api/*"] }),
        }),
      ]),
    }));
  });

  it("ALB drop_invalid_header_fields가 활성화된다", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::LoadBalancer", Match.objectLike({
      LoadBalancerAttributes: Match.arrayWith([
        Match.objectLike({ Key: "routing.http.drop_invalid_header_fields.enabled", Value: "true" }),
      ]),
    }));
  });
});
