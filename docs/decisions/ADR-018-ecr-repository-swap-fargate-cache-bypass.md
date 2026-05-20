# ADR-018: ECR Repository Swap to Bypass Fargate Silent Cache Bug

- **Status**: Accepted
- **Date**: 2026-05-20
- **Deciders**: Platform team

## Context / 배경

v2.1.0 deploy 중 ECS Fargate에서 **silent image cache bug** 발견. 증상:
- 새 image build/push → ECS task definition image URI에 `@sha256:<digest>` 직접 명시
- ECS task start 시 imageDigest 보고는 새 digest
- backend startup log는 새 코드 동작 (e.g., `_discover_anthropic_models()` 새 prefix 라벨로 등록)
- 그러나 HTTP endpoint 응답은 옛 코드 (e.g., `/api/models`가 옛 dict 응답, `/api/admin/users` 404)

시도한 모든 우회 실패:
1. `:latest` → immutable `:v<ts>` tag
2. `@sha256:<digest>` 직접 명시
3. `aws ecs stop-task` 강제 재시작
4. `aws ecs update-service --desired-count 0 → 30s wait → 1`
5. ECR에서 옛 image manifest 일괄 삭제 (단 1개만 남김)
6. `--no-cache --pull`로 fresh build

마지막에 효과 있었던 우회: **다른 ECR repository에 동일 image push + task definition의 image URI에 새 repo 경로**.

가설: ECS Fargate가 image manifest layer를 cached blob storage에 cache하고, 같은 repository path + 같은 family에서는 manifest digest를 보고도 cached layer를 사용. Repository path 자체가 변하면 cache lookup miss → fresh pull.

## Decision / 결정

**Backend image는 `bedrock-monitor-backend-v2` ECR repository를 사용한다.**

규칙:
1. ECR repo: `bedrock-monitor-backend-v2` (`IMMUTABLE` tag mutability)
2. Image tag: `v<unix-timestamp>` immutable
3. Task definition image URI: `<account>.dkr.ecr.<region>.amazonaws.com/bedrock-monitor-backend-v2:<tag>` 또는 `@sha256:<digest>` (둘 다 OK, digest가 더 안전)
4. 옛 repository `bedrock-monitor-backend`는 archive로 유지 — 다른 환경에서 참조 시 lifecycle policy로 7일 후 정리
5. CDK code도 새 repository를 사용하도록 update 필요 (다음 PR)

운영 절차에 추가:
- 새 backend image deploy 시 endpoint sanity check 자동화:
  ```bash
  # 새 endpoint(예: /api/admin/users)가 401 응답이면 OK, 404이면 silent bug 의심.
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://.../api/admin/users)
  [ "$STATUS" = "401" ] || echo "ALERT: backend not running new image" && exit 1
  ```

## Consequences / 결과

**Pros**:
- 해결: 새 코드가 production에 정상 반영됨
- 운영 검증 endpoint 표준화 (admin/users는 옛 image에서는 404)
- 향후 같은 bug 재발 시 repository swap이 효과적인 우회임을 docs에 명시

**Cons**:
- ECR repository 두 개 (옛 + 새) — 약간 비용 증가, 운영 복잡도 ↑
- CDK code와 ECR repo path 불일치 — 다음 CDK redeploy 시 충돌 가능성 → CDK 코드 update 필수
- Root cause(왜 Fargate가 cache miss를 못 하는지) 미해결 → AWS Support 케이스로 보고 권장

## Implementation / 구현

수동 절차:
```bash
# 1. 새 repo 생성
aws ecr create-repository --repository-name bedrock-monitor-backend-v2 \
  --image-tag-mutability IMMUTABLE --region ap-northeast-2

# 2. 옛 image retag + push
docker pull <old-repo>:<tag>
docker tag <old-repo>:<tag> <account>.dkr.ecr.<region>.amazonaws.com/bedrock-monitor-backend-v2:v$(date +%s)
docker push <account>.dkr.ecr.<region>.amazonaws.com/bedrock-monitor-backend-v2:v...

# 3. Task definition 두 곳(AppServices Backend + Scheduler AutoProber) 새 image URI로 register-task-definition

# 4. backend service update + autoprober schedule update
```

자동화 권장: CI/CD pipeline에 sanity check 단계 + 실패 시 자동 rollback.

## References

- v2.1.0 incident: 2026-05-20 backend silent failure (~3시간 진단)
- 관련: ADR-010 (immutable tag policy)
- AWS Support 케이스 권장 — Fargate platform-level investigation
