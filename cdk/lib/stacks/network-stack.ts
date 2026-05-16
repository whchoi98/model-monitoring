// NetworkStack — Phase 2에서 VPC 조회/생성 + PrivateLink 엔드포인트 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type NetworkStackProps = cdk.StackProps;

export class NetworkStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);
    // Phase 2 작업 영역 — VPC + Interface/Gateway Endpoints.
  }
}
