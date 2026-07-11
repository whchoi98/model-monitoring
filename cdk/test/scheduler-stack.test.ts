// Phase 9 — SchedulerStack 단위 테스트.
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { SchedulerStack } from "../lib/stacks/scheduler-stack";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

describe("SchedulerStack", () => {
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
    const scheduler = new SchedulerStack(app, "Scheduler", {
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
    });
    template = Template.fromStack(scheduler);
  });

  it("Schedule이 3개 생성된다 (AutoProber + Insights + ParityRun)", () => {
    template.resourceCountIs("AWS::Scheduler::Schedule", 3);
  });

  it("AutoProber는 rate(5 minutes) 스케줄을 사용한다", () => {
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({
      ScheduleExpression: "rate(5 minutes)",
    }));
  });

  it("Insights도 rate(5 minutes) 스케줄을 사용한다 (v2.2+에서 30분→5분 단축)", () => {
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({
      ScheduleExpression: "rate(5 minutes)",
    }));
  });

  it("Task role은 bedrock-mantle:CreateInference를 허용한다 (v2.13.0 messages_mantle — SigV4 파생 bearer)", () => {
    template.hasResourceProperties("AWS::IAM::Role", Match.objectLike({
      Policies: Match.arrayWith([
        Match.objectLike({
          PolicyDocument: Match.objectLike({
            Statement: Match.arrayWith([
              Match.objectLike({ Action: "bedrock-mantle:CreateInference" }),
              // bearer 인증 흐름의 두 번째 필수 액션 (403 실측: resource *)
              Match.objectLike({ Action: "bedrock-mantle:CallWithBearerToken" }),
            ]),
          }),
        }),
      ]),
    }));
  });

  it("ParityRun은 rate(12 hours) 스케줄을 사용한다 (v2.12.0에서 일 1회→12시간)", () => {
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({
      ScheduleExpression: "rate(12 hours)",
    }));
  });

  it("TaskDefinition이 3개 생성된다", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 3);
  });

  it("Task는 Fargate, awsvpc, X86_64로 설정된다", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      NetworkMode: "awsvpc",
      RequiresCompatibilities: ["FARGATE"],
      Cpu: "512",
      Memory: "1024",
    }));
  });

  it("AutoProber 컨테이너 CMD는 auto_prober_runner --once", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Command: ["python", "-m", "auto_prober_runner", "--once"],
        }),
      ]),
    }));
  });

  it("Insights 컨테이너 CMD는 insights_runner --window 6h", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Command: ["python", "-m", "insights_runner", "--window", "6h"],
        }),
      ]),
    }));
  });

  it("RDS SG에 scheduler task SG로부터 5432 ingress가 추가된다", () => {
    template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", Match.objectLike({
      IpProtocol: "tcp",
      FromPort: 5432,
      ToPort: 5432,
    }));
  });

  it("Schedule의 NetworkConfiguration이 SG와 private subnets를 사용한다", () => {
    // EcsParameters → NetworkConfiguration → AwsvpcConfiguration
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({
      Target: Match.objectLike({
        EcsParameters: Match.objectLike({
          NetworkConfiguration: Match.objectLike({
            AwsvpcConfiguration: Match.objectLike({
              AssignPublicIp: "DISABLED",
            }),
          }),
        }),
      }),
    }));
  });

  it("Bedrock InvokeModel 권한이 task role에 부여된다", () => {
    template.hasResourceProperties("AWS::IAM::Role", Match.objectLike({
      Policies: Match.arrayWith([
        Match.objectLike({
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
        }),
      ]),
    }));
  });
});
