// ClusterStack — Phase 4에서 ECS Cluster + ECR + 로그 KMS 키 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type ClusterStackProps = cdk.StackProps;

export class ClusterStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ClusterStackProps) {
    super(scope, id, props);
    // Phase 4 작업 영역 — ECS Cluster, ECR repos × 2, KMS 로그 키.
  }
}
