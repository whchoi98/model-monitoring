// EdgeStack - CloudFront Distribution + VPC Origin (Internal ALB) + CloudFront access logs.
//
// 사용자 요구: "CF - Prefix List SG - ALB (Private Subnet)" 구조.
// 구현:
//   - CloudFront VPC Origin이 ALB의 사설망 IP로 직접 접근 (PrivateLink-like).
//   - ALB는 Internal scheme + Private Subnet + VPC CIDR SG ingress.
//   - WAFv2 CLOUDFRONT scope은 us-east-1 강제이므로 본 stack에서는 제외
//     (필요 시 별도 us-east-1 stack에서 attach).
//   - Origin protocol HTTPS_ONLY 유지 (ALB의 cert는 cert hostname 무관하게
//     PrivateLink 경로에서 동작 - 운영 cert 정착 후 SNI 동작도 정상).
import * as cdk from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as s3 from "aws-cdk-lib/aws-s3";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export interface EdgeStackProps extends cdk.StackProps {
  readonly alb: elbv2.IApplicationLoadBalancer;
}

export class EdgeStack extends cdk.Stack {
  public readonly distribution: cloudfront.Distribution;
  public readonly cfLogsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: EdgeStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // CloudFront access logs S3 버킷.
    // ---------------------------------------------------------------------
    this.cfLogsBucket = new s3.Bucket(this, "CfLogsBucket", {
      bucketName: `bedrock-monitor-cf-logs-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      lifecycleRules: [{ expiration: cdk.Duration.days(90) }],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ---------------------------------------------------------------------
    // CloudFront VPC Origin -> Internal ALB.
    //   VPC Origin은 ALB와 같은 리전에 위치해야 한다 (현재는 ap-northeast-2).
    // ---------------------------------------------------------------------
    // 운영 cert 정착 전 임시 HTTP origin - ALB는 internal scheme + Private Subnet이고
    // SG가 VPC CIDR만 허용하므로 외부 노출 없음. CloudFront VPC Origin ENI만 통신 가능.
    // Cert 발급 후 HTTPS_ONLY + httpPort 제거로 원복.
    const albOrigin = origins.VpcOrigin.withApplicationLoadBalancer(props.alb, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
      httpPort: 80,
      readTimeout: cdk.Duration.seconds(60),
      keepaliveTimeout: cdk.Duration.seconds(60),
    });

    // ---------------------------------------------------------------------
    // CloudFront Distribution.
    // ---------------------------------------------------------------------
    this.distribution = new cloudfront.Distribution(this, "Distribution", {
      defaultBehavior: {
        origin: albOrigin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        compress: true,
      },
      additionalBehaviors: {
        "/api/*": {
          origin: albOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          compress: false,
        },
      },
      enableLogging: true,
      logBucket: this.cfLogsBucket,
      logIncludesCookies: false,
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      comment: "Bedrock Monitor v2 distribution",
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-S1",
        reason: "Access logs bucket cannot itself log access (infinite recursion).",
      },
      {
        id: "AwsSolutions-CFR1",
        reason:
          "Geo restriction is intentionally not applied - the monitoring tool is used by global engineers.",
      },
      {
        id: "AwsSolutions-CFR2",
        reason:
          "WAFv2 attachment deferred to a separate us-east-1 stack (CLOUDFRONT scope is region-bound).",
      },
      {
        id: "AwsSolutions-CFR4",
        reason:
          "Default *.cloudfront.net cert enforces TLS_V1_2_2021 minimumProtocolVersion.",
      },
    ]);

    new cdk.CfnOutput(this, "CloudFrontDomain", {
      value: this.distribution.distributionDomainName,
    });
    new cdk.CfnOutput(this, "CloudFrontDistributionId", {
      value: this.distribution.distributionId,
    });
  }
}
