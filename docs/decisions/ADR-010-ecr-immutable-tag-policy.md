# ADR-010: ECR Immutable Tag Policy

- **Status**: Accepted
- **Date**: 2026-05-20
- **Deciders**: Platform team

## Context / 배경

v2.1.0 deploy 중 발견 — backend `:latest` 태그로 push 후 ECS `force-new-deployment`를 해도 새 코드가 production에 반영되지 않았다.

조사 결과:
1. Docker layer dedupe: 새 build의 일부 layer가 ECR에 이미 존재하면 ECR `:latest` tag의 manifest digest가 옛 image와 동일하게 유지될 수 있다.
2. ECS Fargate가 task 시작 시 imageDigest를 "manifest 시점"으로 resolve하지만, 실제로 실행하는 container는 caching된 옛 image를 사용하는 케이스가 관측됨.
3. ECS API는 `containers[0].imageDigest`로 "새 digest"를 보고하지만, /api/* 응답은 옛 코드로 동작 — 매우 추적하기 어려운 silent failure.

결과: 운영자가 새 코드 배포했다고 믿지만 실제 production은 옛 코드. 사용자 화면은 옛 동작.

## Decision / 결정

**모든 production backend image는 immutable tag로 push + task definition에 그 immutable tag를 명시한다.**

규칙:
1. Image tag 형식: `v<timestamp>` 또는 `v<git-sha>` (예: `v1779258431`, `v8a3c2f1`).
2. `:latest` 태그는 **로컬 개발 / docker compose 전용**. Production ECS task definition에서 사용 금지.
3. 새 image push 시:
   - `docker build --no-cache --pull` 강제 (layer cache 회피)
   - 새 immutable tag로 push (`docker tag ... ECR/repo:v<ts>` + `docker push ECR/repo:v<ts>`)
   - `aws ecs register-task-definition` 으로 새 revision 생성 (container image = 그 immutable tag)
   - `aws ecs update-service --task-definition <new-arn>` 으로 service가 새 revision을 사용
   - EventBridge Scheduler가 별도 task def를 가리키면 schedule도 동일 절차로 갱신
4. ECR repository setting: `imageTagMutability: IMMUTABLE` 권장 (같은 tag 재 push 방지).

## Consequences / 결과

**Pros**:
- "어느 image가 실제 production에 있는가"가 task def에 명시되어 의심의 여지 없음
- Rollback이 단순 — 옛 task def revision으로 service update
- Git commit SHA와 image tag 1:1 매핑 가능 (CI/CD 통합)

**Cons**:
- ECR repository size 증가 (lifecycle policy로 7일 미만 image 자동 삭제 권장)
- 수동 deploy 시 명령 길이 증가 (스크립트화 필요)

## Implementation / 구현

`docs/runbooks/deploy.md`에 전체 절차 명시. CDK 코드도 `ContainerImage.fromEcrRepository(repo, "latest")` 대신 명시적 tag 또는 image asset 패턴으로 전환 권장 (다음 CDK PR).

## References

- v2.1.0 incident log: 2026-05-20 — backend `:latest` push 후 silent fail
- 관련: ADR-011 (Scheduler IAM wildcard)
