// EdgeStack — Phase 7에서 ACM Private CA cert + Internal ALB(HTTPS only) +
// CloudFront VPC Origin + WAFv2 + S3 access logs + Lambda@Edge(VIEWER_REQUEST only) 정의.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

export type EdgeStackProps = cdk.StackProps;

export class EdgeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: EdgeStackProps) {
    super(scope, id, props);
    // Phase 7 작업 영역 — ALB internal, CloudFront, WAF, ACM Private CA.
    // HTTP:80 listener는 어떤 형태로도 생성하지 않는다.
  }
}
