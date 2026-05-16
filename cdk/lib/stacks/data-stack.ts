// DataStack — Phase 3에서 RDS PostgreSQL + Secrets Manager + SSM SecureString 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type DataStackProps = cdk.StackProps;

export class DataStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    // Phase 3 작업 영역 — RDS t4g.micro, Single-AZ, 20GB gp3, 7d 자동 백업.
  }
}
