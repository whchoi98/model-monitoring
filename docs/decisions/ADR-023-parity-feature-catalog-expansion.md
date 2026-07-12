# ADR-023: 패리티 피처 카탈로그 확장 (7 → 19) — 적용 맵과 정직한 제외 원칙

- **Status**: Accepted
- **Date**: 2026-07-12
- **Related**: ADR-021 (실행-증거 원칙), ADR-022 (messages_mantle surface)

## Context

참조 내부 도구 수준의 피처 커버리지가 요구됐다 (v2.14: adaptive_thinking, count_tokens,
batches, web_search, computer_use / v2.15: reasoning_effort, json_schema, url_sources,
memory_tool, code_execution, files_api, models_api). 피처마다 검사 가능한 surface가 달라
일괄 팬아웃은 무의미한 셀을 양산한다.

## Decision

1. **`_FEATURE_SURFACES` 적용 맵**: 피처별로 증거 검사를 구현한 surface만 프로빙.
   미구현 조합은 `skipped`로 기록 — **skipped ≠ unsupported** (프로브가 없다는 뜻이지
   기능이 없다는 뜻이 아님).
2. **정직한 제외**: Admin/Usage API(관리자 키 필요), MCP connector(실 MCP 서버 필요)는
   현 자격으로 정직한 판정이 불가능해 카탈로그에서 의도적으로 제외.
3. **요청 스냅샷 증거**: 모든 프로브가 `_req_snapshot`(장문 절단)을 evidence에 저장 —
   Broken 판정 시 셀 클릭만으로 프로브/모델 어느 쪽 결함인지 판별 가능.

## Consequences

- (+) 런당 ~810셀(프로브 ~747)로 참조 도구 수준 커버리지, 12시간 주기 유지
- (+) 오류 분류 마커가 실측으로 축적됨 ("request is not valid", "does not match any of the
  expected", "not yet available/supported", "error code: 404" → 모두 깨끗한 미지원)
- (−) 신규 피처 추가 시 3단 체크리스트 필수: 카탈로그 정의 + surface별 프로브 + (bearer
  경로면) IAM 액션 — run #7~#10의 false-Broken 이력이 이 체크리스트의 근거
