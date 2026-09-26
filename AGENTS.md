# Project guidance

Use [CLAUDE.md](CLAUDE.md) for the existing architecture, model catalog rules,
authentication contract and release constraints. The implementation and current
AWS resource state are authoritative when older examples differ.

- Run `make verify` for CDK, backend and frontend checks.
- Browser verification and its isolated container recipe are recorded in
  [the UX review](docs/reviews/2026-09-22-monitoring-ux.md).
- Production images use immutable tags and explicit digests.
- Update the backend service and all six scheduled task definitions together
  when their shared backend image changes.
- RUM configuration is injected into the frontend at build time.
- Preserve unrelated local files when staging a release.

## 한국어

기존 프로젝트 규칙은 [CLAUDE.md](CLAUDE.md)를 따른다. 오래된 예시와 실제 코드·운영
상태가 다르면 현재 상태를 확인한다. 검증은 `make verify`를 사용하고, 운영 이미지는
불변 태그와 digest로 고정한다. 공용 백엔드 이미지가 바뀌면 서비스와 6개 스케줄을
함께 갱신한다. RUM 빌드 설정을 확인하고 작업과 무관한 로컬 파일은 보존한다.
