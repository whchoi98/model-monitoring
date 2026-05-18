// ClusterStack - ECS Cluster + ECR Repos + 로그용 KMS Key.
//
// 책임:
//   - ECS Fargate 워크로드를 호스팅할 Cluster (Container Insights 활성).
//   - frontend / backend 컨테이너 이미지를 보관할 ECR repo 2개.
//     - imageTagMutability: IMMUTABLE (이미 push된 tag 덮어쓰기 방지).
//     - imageScanOnPush: true (CVE 자동 스캔).
//     - lifecycle: untagged 7일, 최근 10개 tagged 이미지 유지.
//   - 모든 로그/시크릿 암호화에 쓸 customer-managed KMS Key (회전 활성).
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as kms from "aws-cdk-lib/aws-kms";
import { Construct } from "constructs";

export interface ClusterStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
}

export class ClusterStack extends cdk.Stack {
  public readonly cluster: ecs.Cluster;
  public readonly backendRepo: ecr.Repository;
  public readonly frontendRepo: ecr.Repository;
  public readonly logKey: kms.Key;

  constructor(scope: Construct, id: string, props: ClusterStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // KMS Key - CloudWatch Logs / S3 access logs / Secrets 암호화 공용.
    // ---------------------------------------------------------------------
    this.logKey = new kms.Key(this, "LogKey", {
      alias: "alias/bedrock-monitor/logs",
      description: "Encryption key for Bedrock Monitor logs and secrets",
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    // CloudWatch Logs 서비스가 이 키로 암호화된 로그그룹을 다룰 수 있도록 권한 부여.
    this.logKey.addToResourcePolicy(
      new cdk.aws_iam.PolicyStatement({
        sid: "AllowCloudWatchLogs",
        principals: [
          new cdk.aws_iam.ServicePrincipal(`logs.${this.region}.amazonaws.com`),
        ],
        actions: [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*",
        ],
        resources: ["*"],
        conditions: {
          ArnLike: {
            "kms:EncryptionContext:aws:logs:arn": `arn:aws:logs:${this.region}:${this.account}:*`,
          },
        },
      }),
    );

    // ---------------------------------------------------------------------
    // ECS Cluster - Container Insights ON.
    // ---------------------------------------------------------------------
    this.cluster = new ecs.Cluster(this, "Cluster", {
      clusterName: "bedrock-monitor",
      vpc: props.vpc,
      containerInsightsV2: ecs.ContainerInsights.ENABLED,
      enableFargateCapacityProviders: true,
    });

    // ---------------------------------------------------------------------
    // ECR Repositories - immutable tag + scan on push + lifecycle.
    // ---------------------------------------------------------------------
    this.backendRepo = this.createImageRepo("BackendRepo", "bedrock-monitor-backend");
    this.frontendRepo = this.createImageRepo("FrontendRepo", "bedrock-monitor-frontend");

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "ClusterName", { value: this.cluster.clusterName });
    new cdk.CfnOutput(this, "ClusterArn", { value: this.cluster.clusterArn });
    new cdk.CfnOutput(this, "BackendRepoUri", { value: this.backendRepo.repositoryUri });
    new cdk.CfnOutput(this, "FrontendRepoUri", { value: this.frontendRepo.repositoryUri });
    new cdk.CfnOutput(this, "LogKeyArn", { value: this.logKey.keyArn });
  }

  private createImageRepo(id: string, repoName: string): ecr.Repository {
    return new ecr.Repository(this, id, {
      repositoryName: repoName,
      // MUTABLE: 'latest' tag을 새 이미지로 push 가능하도록. 운영 정착 시 IMMUTABLE + 버전 tag으로 전환.
      imageTagMutability: ecr.TagMutability.MUTABLE,
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          description: "untagged 이미지는 7일 후 삭제",
          tagStatus: ecr.TagStatus.UNTAGGED,
          maxImageAge: cdk.Duration.days(7),
        },
        {
          description: "tagged 이미지는 최근 10개만 유지",
          tagStatus: ecr.TagStatus.ANY,
          maxImageCount: 10,
        },
      ],
    });
  }
}
