#!/usr/bin/env node
// CDK 진입점 — 모든 스택을 등록하고 cdk-nag aspect를 적용한다.
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

const prefix = "BedrockMonitor";

// 스택 의존성: Network → Data → Cluster → AgentCore → AppServices → Edge → Scheduler → Observability
const network = new NetworkStack(app, `${prefix}-Network`, { env });

const data = new DataStack(app, `${prefix}-Data`, {
  env,
  vpc: network.vpc,
  dataSubnets: network.dataSubnets,
});

const cluster = new ClusterStack(app, `${prefix}-Cluster`, { env, vpc: network.vpc });

const agentCore = new AgentCoreStack(app, `${prefix}-AgentCore`, { env });

const appServices = new AppServicesStack(app, `${prefix}-AppServices`, {
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
  albCertificateArn: app.node.tryGetContext("albCertificateArn") as string | undefined,
});

new EdgeStack(app, `${prefix}-Edge`, {
  env,
  alb: appServices.alb,
});

new SchedulerStack(app, `${prefix}-Scheduler`, {
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

new ObservabilityStack(app, `${prefix}-Observability`, {
  env,
  alb: appServices.alb,
  cluster: cluster.cluster,
  backendService: appServices.backendService,
  frontendService: appServices.frontendService,
  db: data.db,
  alarmEmail: app.node.tryGetContext("alarmEmail") as string | undefined,
});

// cdk-nag — 모든 스택에 AWS Solutions ruleset 적용.
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));

app.synth();
