// 이미지 고정(pinning) 회귀 테스트 — 2026-07-09 실사고 재발 방지.
//
// 배경: 스택이 `imageTag: "latest"` + 옛 backend repo를 하드코딩한 탓에, 어떤 cdk deploy든
// (단일 스택 지정이라도 의존 스택 diff가 있으면) backend 서비스를 두 달 전 :latest 이미지로
// 조용히 되돌렸다. context(`backendImage`/`frontendImage`)로 전체 이미지 URI(digest 고정)를
// 주입하면 task definition이 운영 배포 관행(immutable digest)과 일치해야 한다.
import * as cdk from "aws-cdk-lib";
import { Annotations, Match, Template } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { SchedulerStack } from "../lib/stacks/scheduler-stack";
import { repoNameFromImageUri } from "../lib/constructs/pinned-image";

const env: cdk.Environment = { account: "111111111111", region: "us-east-1" };

const BE_URI =
  "111111111111.dkr.ecr.us-east-1.amazonaws.com/bedrock-monitor-backend-v2@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const FE_URI =
  "111111111111.dkr.ecr.us-east-1.amazonaws.com/bedrock-monitor-frontend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function buildStacks(context: Record<string, string>) {
  const app = new cdk.App({ context });
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
  return { appServices, scheduler };
}

describe("repoNameFromImageUri", () => {
  it("digest URI에서 repo 이름을 추출한다", () => {
    expect(repoNameFromImageUri(BE_URI)).toBe("bedrock-monitor-backend-v2");
  });
  it("tag URI에서도 추출한다", () => {
    expect(
      repoNameFromImageUri("1.dkr.ecr.us-east-1.amazonaws.com/my-repo:v123"),
    ).toBe("my-repo");
  });
  it("네임스페이스가 있는 repo도 처리한다", () => {
    expect(
      repoNameFromImageUri("1.dkr.ecr.us-east-1.amazonaws.com/team/my-repo@sha256:abc"),
    ).toBe("team/my-repo");
  });
});

describe("context 이미지 주입 (backendImage/frontendImage)", () => {
  let appSvcTemplate: Template;
  let schedTemplate: Template;

  beforeAll(() => {
    const { appServices, scheduler } = buildStacks({
      backendImage: BE_URI,
      frontendImage: FE_URI,
    });
    appSvcTemplate = Template.fromStack(appServices);
    schedTemplate = Template.fromStack(scheduler);
  });

  it("backend/frontend task definition이 주입된 digest URI를 그대로 사용한다", () => {
    appSvcTemplate.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({ Name: "backend", Image: BE_URI }),
      ]),
    }));
    appSvcTemplate.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({ Name: "frontend", Image: FE_URI }),
      ]),
    }));
  });

  it("scheduler의 autoprober/insights/parity/gptbench/features task definition도 backend digest URI를 사용한다", () => {
    const tds = schedTemplate.findResources("AWS::ECS::TaskDefinition");
    const images = Object.values(tds).map(
      (td) => (td as any).Properties.ContainerDefinitions[0].Image,
    );
    expect(images).toHaveLength(5); // autoprober + insights + parityrun (v2.11.0) + gptbench (v2.18.0) + featuresverify (v2.23.0)
    for (const img of images) {
      expect(img).toBe(BE_URI);
    }
  });

  it(":latest 참조가 템플릿에 남지 않는다", () => {
    for (const t of [appSvcTemplate, schedTemplate]) {
      const tds = t.findResources("AWS::ECS::TaskDefinition");
      for (const td of Object.values(tds)) {
        const image = (td as any).Properties.ContainerDefinitions[0].Image;
        expect(JSON.stringify(image)).not.toContain("latest");
      }
    }
  });
});

describe("context 미주입 (로컬 synth/테스트 fallback)", () => {
  it("기존 repo+latest로 synth는 되지만 경고를 남긴다", () => {
    const { appServices, scheduler } = buildStacks({});
    // synth 가능해야 한다 (테스트/로컬 diff 용).
    Template.fromStack(appServices);
    Template.fromStack(scheduler);
    // 운영 배포 실수를 막는 경고 — deploy 시 눈에 띄게.
    Annotations.fromStack(appServices).hasWarning(
      "*",
      Match.stringLikeRegexp("backendImage"),
    );
    Annotations.fromStack(scheduler).hasWarning(
      "*",
      Match.stringLikeRegexp("backendImage"),
    );
  });
});
