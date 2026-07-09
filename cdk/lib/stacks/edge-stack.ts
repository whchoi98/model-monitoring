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
import * as acm from "aws-cdk-lib/aws-certificatemanager";
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
    // Response Headers Policy - HTML 응답의 cache-control을 강제 override.
    // Next.js 14가 SSR HTML에 자동으로 s-maxage=31536000을 박는데, middleware/dynamic 모두
    // 덮어쓰지 못해 마지막 layer (CloudFront response)에서 강제로 no-store로 교체.
    const htmlNoCachePolicy = new cloudfront.ResponseHeadersPolicy(this, "HtmlNoCachePolicy", {
      responseHeadersPolicyName: "BedrockMonitorHtmlNoCache",
      customHeadersBehavior: {
        customHeaders: [
          {
            header: "Cache-Control",
            value: "no-store, no-cache, must-revalidate, max-age=0",
            override: true,
          },
        ],
      },
    });

    // auto-probe 조회 API 전용 캐시 정책 (2026-07-08 성능 개선).
    // - 원본 Cache-Control(s-maxage=30)을 존중: defaultTtl 0이라 헤더 없는 응답(/status 등)은 캐시 안 됨.
    // - 데이터가 5분 주기로만 갱신되므로 30초 edge 캐시로 다중 사용자·자동새로고침 중복 DB 조회 흡수.
    // - hours/category 쿼리스트링이 캐시 키에 반드시 포함되어야 함 (필터별 응답이 다름).
    // - 기존 /api/*는 compress:false(SSE 보호)라 대용량 JSON이 무압축이었음 — 이 경로만 gzip/br 활성화.
    const autoProbeCachePolicy = new cloudfront.CachePolicy(this, "AutoProbeCachePolicy", {
      cachePolicyName: "BedrockMonitorAutoProbeCache",
      comment: "auto-probe JSON: honor origin Cache-Control + compression",
      minTtl: cdk.Duration.seconds(0),
      defaultTtl: cdk.Duration.seconds(0),
      maxTtl: cdk.Duration.seconds(60),
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.all(),
      headerBehavior: cloudfront.CacheHeaderBehavior.none(),
      cookieBehavior: cloudfront.CacheCookieBehavior.none(),
      enableAcceptEncodingGzip: true,
      enableAcceptEncodingBrotli: true,
    });

    // 대체 도메인 (2026-07-09 실사고 재발 방지).
    // 콘솔에서 수동 추가했던 alias는 cdk deploy가 템플릿 상태로 되돌리며 제거된다 —
    // 그 순간 llm-monitor.whchoi.net 요청이 *.whchoi.net 와일드카드 alias를 가진
    // 다른 배포판(Cognito 인증)으로 넘어가 사용자가 로그인 화면/에러를 보게 된다.
    // 반드시 CDK가 소유한다. context로 교체 가능: -c monitorDomain / -c monitorCertArn.
    const monitorDomain =
      (this.node.tryGetContext("monitorDomain") as string | undefined) ??
      "llm-monitor.whchoi.net";
    const monitorCertArn =
      (this.node.tryGetContext("monitorCertArn") as string | undefined) ??
      // *.whchoi.net (us-east-1 — CloudFront viewer cert는 us-east-1 필수)
      "arn:aws:acm:us-east-1:061525506239:certificate/7d53182a-2a2a-4225-a319-4f94030561b7";
    const aliasCertificate = acm.Certificate.fromCertificateArn(
      this,
      "AliasCertificate",
      monitorCertArn,
    );

    this.distribution = new cloudfront.Distribution(this, "Distribution", {
      domainNames: [monitorDomain],
      certificate: aliasCertificate,
      // Default behavior - HTML 페이지 (/, /prompts 등). 캐시 + 응답 헤더 모두 no-store 강제.
      defaultBehavior: {
        origin: albOrigin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        responseHeadersPolicy: htmlNoCachePolicy,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        compress: true,
      },
      additionalBehaviors: {
        // auto-probe 조회 API - SSE 없음. 단기 edge 캐시 + 압축 (위 autoProbeCachePolicy 주석 참고).
        // 주의: "/api/*"보다 먼저 선언해야 우선 매칭된다.
        "/api/auto-probe/*": {
          origin: albOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: autoProbeCachePolicy,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL, // /trigger POST 포함 (POST는 캐시 안 됨)
          compress: true,
        },
        // API - 절대 캐시 금지 (SSE 스트리밍 포함).
        "/api/*": {
          origin: albOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          compress: false,
        },
        // Next.js 정적 자산 - hash-based filename이라 영구 immutable 캐시 안전.
        "/_next/static/*": {
          origin: albOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
          compress: true,
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
