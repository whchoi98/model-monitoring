// AppServicesStack — Phase 6에서 frontend / backend Fargate Service 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type AppServicesStackProps = cdk.StackProps;

export class AppServicesStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AppServicesStackProps) {
    super(scope, id, props);
    // Phase 6 작업 영역 — frontend Service, backend Service, Target Groups, IAM Roles.
  }
}
