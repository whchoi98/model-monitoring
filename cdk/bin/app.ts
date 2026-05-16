#!/usr/bin/env node
// CDK 진입점 — 모든 스택을 등록하고 cdk-nag aspect를 적용한다.
// Phase 1: 빈 스택 8개 골격. 스택 간 props wiring은 각 Phase에서 추가.
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";

import { NetworkStack } from "../lib/stacks/network-stack";
import { DataStack } from "../lib/stacks/data-stack";
import { ClusterStack } from "../lib/stacks/cluster-stack";
import { AgentCoreStack } from "../lib/stacks/agentcore-stack";
import { AppServicesStack } from "../lib/stacks/app-services-stack";
import { EdgeStack } from "../lib/stacks/edge-stack";
import { SchedulerStack } from "../lib/stacks/scheduler-stack";
import { ObservabilityStack } from "../lib/stacks/observability-stack";

const app = new cdk.App();

// 배포 환경 — Bedrock + AgentCore + 모든 인프라가 us-east-1 단일 리전.
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? "us-east-1",
};

// 공통 prefix — 다중 스택 deploy 시 리소스 이름 충돌 방지.
const prefix = "BedrockMonitor";

// 스택 등록 순서는 후속 Phase에서 의존성 wiring과 동일하게 정렬.
const network = new NetworkStack(app, `${prefix}-Network`, { env });
new DataStack(app, `${prefix}-Data`, {
  env,
  vpc: network.vpc,
  dataSubnets: network.dataSubnets,
});
new ClusterStack(app, `${prefix}-Cluster`, { env });
new AgentCoreStack(app, `${prefix}-AgentCore`, { env });
new AppServicesStack(app, `${prefix}-AppServices`, { env });
new EdgeStack(app, `${prefix}-Edge`, { env });
new SchedulerStack(app, `${prefix}-Scheduler`, { env });
new ObservabilityStack(app, `${prefix}-Observability`, { env });

// cdk-nag — 모든 스택에 AWS Solutions ruleset 적용.
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));

app.synth();
