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

  it("Schedule이 6개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify + PricingSync)", () => {
    template.resourceCountIs("AWS::Scheduler::Schedule", 6);
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

  it("Task role은 bedrock-mantle:CreateInference + 두 bearer 액션(Mantle/bedrock_messages)을 허용한다 (v2.13.0 messages_mantle, v2.23.0 bedrock_messages — SigV4 파생 bearer)", () => {
    template.hasResourceProperties("AWS::IAM::Role", Match.objectLike({
      Policies: Match.arrayWith([
        Match.objectLike({
          PolicyDocument: Match.objectLike({
            Statement: Match.arrayWith([
              Match.objectLike({ Action: Match.arrayWith(["bedrock-mantle:CreateInference", "bedrock-mantle:CountTokens"]) }),
              // bearer 인증 흐름의 두 번째 필수 액션 (403 실측: resource *) — Mantle + bedrock-runtime
              // Anthropic Messages 라우트(bedrock_messages surface, v2.23.0) 둘 다 필요.
              Match.objectLike({ Action: Match.arrayWith(["bedrock-mantle:CallWithBearerToken", "bedrock:CallWithBearerToken"]) }),
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

  it("TaskDefinition이 6개 생성된다 (PricingSync 포함, v2.30.0)", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 6);
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

  it("FeaturesVerify는 매일 17:30 UTC 고정 cron 스케줄 + features_runner --once CMD (v2.29.0)", () => {
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({
      ScheduleExpression: "cron(30 17 * * ? *)",
      ScheduleExpressionTimezone: "Etc/UTC",
      Description: Match.stringLikeRegexp("daily at 17:30 UTC"),
    }));
    // 일 1회 스케줄은 이 cron 하나뿐 — 이전 rate(1 day)가 남아 하루 두 번 돌지 않는다.
    const expressions = Object.values(template.findResources("AWS::Scheduler::Schedule"))
      .map((resource) => resource.Properties.ScheduleExpression);
    expect(expressions).not.toContain("rate(1 day)");
    expect(expressions.filter((expression: string) => expression.startsWith("cron("))).toEqual(["cron(30 17 * * ? *)"]);
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([Match.objectLike({
        Command: ["python", "-m", "features_runner", "--once"],
        Environment: Match.arrayWith([Match.objectLike({ Name: "MANTLE_ANTHROPIC_REGION", Value: "us-east-1" })]),
      })]),
    }));
  });

  it("autoprober task def에 OpenAI US CRIS 라우팅 + GPT-6 Astra model id가 주입된다 (v2.25.0)", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([Match.objectLike({
        Command: ["python", "-m", "auto_prober_runner", "--once"],
        Environment: Match.arrayWith([
          Match.objectLike({ Name: "OPENAI_US_BASE_URL", Value: "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1" }),
          Match.objectLike({ Name: "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", Value: "openai.gpt-6-astra" }),
        ]),
      })]),
    }));
  });

  it("autoprober task def만 Claude Platform on AWS 수집 주기 env를 명시한다 — v2.29.1 매 사이클(300)", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([Match.objectLike({
        Command: ["python", "-m", "auto_prober_runner", "--once"],
        Environment: Match.arrayWith([Match.objectLike({ Name: "ANTHROPIC_CP_PROBE_INTERVAL_S", Value: "300" })]),
      })]),
    }));
    const withInterval = Object.values(template.findResources("AWS::ECS::TaskDefinition"))
      .flatMap((resource) => resource.Properties.ContainerDefinitions)
      .filter((container: { Environment?: { Name: string }[] }) =>
        (container.Environment ?? []).some((env) => env.Name === "ANTHROPIC_CP_PROBE_INTERVAL_S"))
      .map((container: { Command: string[] }) => container.Command.join(" "));
    expect(withInterval).toEqual(["python -m auto_prober_runner --once"]);
  });

  it("AutoProber 스케줄은 5분 그대로다 — CP 주기(노브)는 사이클 안에서 고른다 (v2.29.0)", () => {
    template.hasResourceProperties("AWS::Scheduler::Schedule", Match.objectLike({
      ScheduleExpression: "rate(5 minutes)",
      Description: Match.stringLikeRegexp("Bedrock 모니터링"),
    }));
  });

  describe("PricingSync (v2.30.0, ADR-030)", () => {
    const PRICING_COMMAND = ["python", "-m", "pricing_sync_runner", "--once"];
    type Container = { Command: string[]; Environment?: { Name: string; Value: string }[]; Secrets?: { Name: string }[] };
    type CfnResource = ReturnType<Template["findResources"]>[string];

    const taskDefByCommand = (command: string[]): [string, CfnResource] => {
      const found = Object.entries(template.findResources("AWS::ECS::TaskDefinition")).filter(([, resource]) =>
        (resource.Properties.ContainerDefinitions as Container[]).some(
          (container) => container.Command.join(" ") === command.join(" ")));
      expect(found).toHaveLength(1);
      return found[0]!;
    };
    const containerOf = (taskDef: CfnResource): Container => taskDef.Properties.ContainerDefinitions[0];
    const pricingRoleLogicalId = (): string => {
      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
      return taskDef.Properties.TaskRoleArn["Fn::GetAtt"][0];
    };
    const schedulerStatement = (sid: string): { Resource: unknown[] } => {
      const statements = Object.entries(template.findResources("AWS::IAM::Policy"))
        .filter(([logicalId]) => logicalId.startsWith("SchedulerInvokeRoleDefaultPolicy"))
        .flatMap(([, policy]) => policy.Properties.PolicyDocument.Statement)
        .filter((statement: { Sid?: string }) => statement.Sid === sid);
      expect(statements).toHaveLength(1);
      return statements[0];
    };

    it("컨테이너 CMD는 pricing_sync_runner --once, 로그 그룹 /ecs/pricingsync 14일, 0.5 vCPU / 1 GB", () => {
      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
      expect(taskDef.Properties.Cpu).toBe("512");
      expect(taskDef.Properties.Memory).toBe("1024");
      const logGroupRef = containerOf(taskDef) as unknown as { LogConfiguration: { Options: { "awslogs-group": { Ref: string } } } };
      const logGroupId = logGroupRef.LogConfiguration.Options["awslogs-group"].Ref;
      const logGroups = template.findResources("AWS::Logs::LogGroup");
      expect(logGroups[logGroupId]?.Properties).toEqual({ LogGroupName: "/ecs/pricingsync", RetentionInDays: 14 });
    });

    it("rate(12 hours) 스케줄이 PricingSync task def를 실행한다 (ParityRun과 별개의 12시간 스케줄)", () => {
      const [taskDefId] = taskDefByCommand(PRICING_COMMAND);
      const targeting = Object.values(template.findResources("AWS::Scheduler::Schedule"))
        .filter((schedule) => schedule.Properties.Target.EcsParameters.TaskDefinitionArn.Ref === taskDefId);
      expect(targeting).toHaveLength(1);
      expect(targeting[0]!.Properties.ScheduleExpression).toBe("rate(12 hours)");
      expect(targeting[0]!.Properties.Description).toMatch(/every 12 hours/);
      const twelveHour = Object.values(template.findResources("AWS::Scheduler::Schedule"))
        .filter((schedule) => schedule.Properties.ScheduleExpression === "rate(12 hours)");
      expect(twelveHour).toHaveLength(2);
    });

    it("AutoProber와 같은 env/secret을 받는다 (CP 디스커버리, OpenAI 등록용) — CP 주기 노브만 빠진다", () => {
      const pricing = containerOf(taskDefByCommand(PRICING_COMMAND)[1]);
      const autoProber = containerOf(taskDefByCommand(["python", "-m", "auto_prober_runner", "--once"])[1]);
      expect(pricing.Environment).toEqual(
        (autoProber.Environment ?? []).filter((variable) => variable.Name !== "ANTHROPIC_CP_PROBE_INTERVAL_S"));
      expect((pricing.Secrets ?? []).map((secret) => secret.Name).sort())
        .toEqual((autoProber.Secrets ?? []).map((secret) => secret.Name).sort());
      expect((pricing.Secrets ?? []).map((secret) => secret.Name)).toEqual(
        expect.arrayContaining(["ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "DB_HOST", "DB_PASSWORD"]));
    });

    it("전용 task role은 가격 읽기 액션 2개만 갖는다 — bedrock:Invoke* 없음, 다른 정책 없음", () => {
      const roleId = pricingRoleLogicalId();
      const role = template.findResources("AWS::IAM::Role")[roleId];
      expect(role).toBeDefined();
      expect(role!.Properties.ManagedPolicyArns).toBeUndefined();
      const statements = (role!.Properties.Policies as { PolicyDocument: { Statement: { Action: string | string[]; Resource: unknown }[] } }[])
        .flatMap((policy) => policy.PolicyDocument.Statement);
      const actions = statements.flatMap((statement) => [statement.Action].flat()).sort();
      expect(actions).toEqual(["bedrock:ListFoundationModelAgreementOffers", "pricing:GetProducts"]);
      expect(statements.map((statement) => statement.Resource)).toEqual(["*"]);
      expect(actions.some((action) => action.startsWith("bedrock:Invoke"))).toBe(false);
      // 이 역할에 붙는 AWS::IAM::Policy(DefaultPolicy 등)가 없어야 한다.
      const attached = Object.values(template.findResources("AWS::IAM::Policy"))
        .filter((policy) => JSON.stringify(policy.Properties.Roles ?? []).includes(roleId));
      expect(attached).toEqual([]);
    });

    it("Scheduler 역할: RunTask family ':*'와 명시 PassRole 목록에 PricingSync가 들어간다 (ADR-011)", () => {
      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
      const family = taskDef.Properties.Family as string;
      expect(schedulerStatement("RunTaskFamilyWildcard").Resource).toContain(
        `arn:aws:ecs:us-east-1:111111111111:task-definition/${family}:*`);
      expect(schedulerStatement("PassTaskRoles").Resource).toContainEqual({ "Fn::GetAtt": [pricingRoleLogicalId(), "Arn"] });
    });

    it("스케줄 이름을 PricingSyncScheduleName output으로 내보낸다 (런북 수동 run-task용)", () => {
      expect(Object.keys(template.findOutputs("PricingSyncScheduleName"))).toEqual(["PricingSyncScheduleName"]);
    });
  });

  it("autoprober task def에 GPT-6 Sol/Luna model id가 주입된다 (v2.27.0)", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([Match.objectLike({
        Command: ["python", "-m", "auto_prober_runner", "--once"],
        Environment: Match.arrayWith([
          Match.objectLike({ Name: "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID", Value: "openai.gpt-6-sol" }),
          Match.objectLike({ Name: "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID", Value: "openai.gpt-6-luna" }),
        ]),
      })]),
    }));
  });
});
