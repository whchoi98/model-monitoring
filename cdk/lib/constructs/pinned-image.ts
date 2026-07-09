// 이미지 고정(pinning) 헬퍼 — 2026-07-09 실사고 재발 방지.
//
// 스택들이 `imageTag: "latest"`를 하드코딩하면, 수동 immutable-digest 배포(runbook §2-1)
// 이후의 어떤 cdk deploy든 서비스를 옛 :latest 이미지로 되돌린다. context로 전체 이미지
// URI(digest 고정)를 주입받아 task definition이 운영 상태와 항상 일치하게 한다.
//
// 사용: cdk deploy -c backendImage=<acct>.dkr.ecr.<region>.amazonaws.com/bedrock-monitor-backend-v2@sha256:...
//                  -c frontendImage=<acct>.dkr.ecr.<region>.amazonaws.com/bedrock-monitor-frontend@sha256:...
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

/** ECR 이미지 URI(`host/repo@sha256:…` 또는 `host/repo:tag`)에서 repo 이름을 추출한다. */
export function repoNameFromImageUri(uri: string): string | undefined {
  const match = uri.match(/^[^/]+\/(.+?)(?:@sha256:[0-9a-f]+|:[^/@]+)?$/);
  return match?.[1];
}

/**
 * URI 문자열로 ContainerImage를 만들고, execution role에 해당 repo pull 권한을 부여한다.
 * (`ContainerImage.fromRegistry`는 `fromEcrRepository`와 달리 IAM grant를 하지 않으므로
 * repo 이름을 파싱해 명시적으로 grantPull한다.)
 */
export function pinnedContainerImage(
  scope: Construct,
  id: string,
  imageUri: string,
  grantee: iam.IGrantable,
): ecs.ContainerImage {
  const repoName = repoNameFromImageUri(imageUri);
  if (repoName) {
    ecr.Repository.fromRepositoryName(scope, id, repoName).grantPull(grantee);
  }
  return ecs.ContainerImage.fromRegistry(imageUri);
}
