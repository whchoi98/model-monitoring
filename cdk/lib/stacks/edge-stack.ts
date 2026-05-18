// EdgeStack - CloudFront Distribution + VPC Origin + WAFv2 + CloudFront access logs.
//
// 책임 분리:
//   - ALB와 Listener는 AppServicesStack에 위치 (Service↔Listener CDK 자동 의존 cycle 회피).
//   - 본 스택은 edge 계층: CloudFront, VPC Origin, WAF, edge 로그.
//
// 보안 원칙:
//   - CloudFront → ALB: VPC Origin + https-only.
//   - WAFv2 (CLOUDFRONT scope) - AWS managed common rules + bad inputs.
//   - CloudFront access logs → S3 (KMS unused, S3-managed encryption).
//   - 도메인 없음 → CloudFront은 기본 *.cloudfront.net 사용 + TLS1.2_2021 enforced.
import * as cdk from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export interface EdgeStackProps extends cdk.StackProps {
  readonly alb: elbv2.IApplicationLoadBalancer;
}

export class EdgeStack extends cdk.Stack {
  public readonly distribution: cloudfront.Distribution;
  public readonly webAcl: wafv2.CfnWebACL;
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
    // WAFv2 WebACL - CLOUDFRONT scope (us-east-1 필수).
    // ---------------------------------------------------------------------
    this.webAcl = new wafv2.CfnWebACL(this, "WebAcl", {
      name: "BedrockMonitorWebAcl",
      scope: "CLOUDFRONT",
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: "BedrockMonitorWebAcl",
        sampledRequestsEnabled: true,
      },
      rules: [
        {
          name: "AWSManagedRulesCommonRuleSet",
          priority: 10,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: "AWS",
              name: "AWSManagedRulesCommonRuleSet",
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: "AWSManagedRulesCommonRuleSet",
            sampledRequestsEnabled: true,
          },
        },
        {
          name: "AWSManagedRulesKnownBadInputsRuleSet",
          priority: 20,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: "AWS",
              name: "AWSManagedRulesKnownBadInputsRuleSet",
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: "AWSManagedRulesKnownBadInputsRuleSet",
            sampledRequestsEnabled: true,
          },
        },
      ],
    });

    // ---------------------------------------------------------------------
    // CloudFront Origin → ALB.
    //   internet-facing ALB + CloudFront managed prefix list 패턴 사용 시
    //   HttpOrigin(ALB DNS, HTTPS_ONLY)으로 직접 접근.
    //   VPC Origin이 spec ADR-001-revised에서 폐기됨.
    // ---------------------------------------------------------------------
    const albOrigin = new origins.LoadBalancerV2Origin(props.alb, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
      readTimeout: cdk.Duration.seconds(60),
      keepaliveTimeout: cdk.Duration.seconds(60),
      // ALB cert hostname mismatch 시 - CF는 cert chain만 검증 (FQDN match 무관, CloudFront는 origin domain 자체를 SNI로 사용).
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
          // API: 캐시 절대 금지. SSE 청크가 viewer로 그대로 흘러가야 함 (NFR-4).
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          compress: false,
        },
      },
      webAclId: this.webAcl.attrArn,
      enableLogging: true,
      logBucket: this.cfLogsBucket,
      logIncludesCookies: false,
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      comment: "Bedrock Monitor v2 distribution",
    });

    // ---------------------------------------------------------------------
    // cdk-nag suppressions.
    // ---------------------------------------------------------------------
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
          "WAFv2 WebACL is attached to the distribution; AwsSolutions-CFR2 occasionally misreports due to L1 binding.",
      },
      {
        id: "AwsSolutions-CFR4",
        reason:
          "Default *.cloudfront.net cert enforces TLS_V1_2_2021 minimumProtocolVersion; custom domain is out of scope (no domain owned).",
      },
    ]);

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "CloudFrontDomain", {
      value: this.distribution.distributionDomainName,
    });
    new cdk.CfnOutput(this, "CloudFrontDistributionId", {
      value: this.distribution.distributionId,
    });
    new cdk.CfnOutput(this, "WebAclArn", { value: this.webAcl.attrArn });
  }
}
