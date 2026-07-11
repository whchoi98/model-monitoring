# Backend Parity — 실행-증거 패리티 런 엔진 (v2.11.0)

## Role
모니터링 카탈로그의 모델 × API surface × 피처 매트릭스를 실제 API 호출로 검증한다.
**HTTP 200은 증거가 아니다** — 응답 내용이 증거 검사를 통과해야 `supported`.
결과는 `parity_runs` / `parity_results` 테이블에 저장되고 `/parity` 페이지가 렌더링한다.

## Files
- `catalog.py` — `SURFACES` 6개 (converse / invoke_model / messages / messages_mantle / chat_completions / responses), `FEATURES` 7개 (basic, streaming, system_instructions, tool_use, structured_output, reasoning, caching). `surfaces_for(model_id)` — model_id 접두사로 surface 결정 (Bedrock Claude는 messages_mantle 포함), `mantle_fm_id()` — 프로파일 접두사 제거, `is_applicable()` — reasoning은 `_REASONING_MARKERS` 모델만
- **messages_mantle** (v2.13.0): Bedrock Mantle `/anthropic` 엔드포인트 시험 — `aws-bedrock-token-generator`의 SigV4 파생 bearer + FM id, 리전 `MANTLE_ANTHROPIC_REGION`(기본 ap-northeast-1). 2026-07-11 실측: 엔드포인트는 실존하나 ap-northeast-1에 서빙 모델 없음 → 전량 "깨끗한 미지원"(`does not exist` → unsupported)
- `engine.py` — 순수 판정 로직 (외부 의존 없음, 단위 테스트 대상): `classify_error()` (`_UNSUPPORTED_MARKERS` 시그니처 → unsupported, 그 외 → broken), `check_canary` / `check_json_object` / `check_tool_roundtrip` / `check_cached_tokens` / `check_stream_events`
- `probes.py` — surface별 실행기 5개. `CANARY`, `max_tokens_for(feature)` (structured_output 512 / 기본 256 / reasoning 2048), `_CACHE_PAD` (최소 캐시 토큰 초과용 장문 패딩). 클라이언트는 `prober.py` 헬퍼 재사용
- `runner.py` — `run_parity()`: ParityRun row 생성 → job 팬아웃 (skipped는 프로브 없이 기록) → ThreadPoolExecutor(4) → 결과 메인 스레드 일괄 저장 (스레드별 DB 세션 금지)

## Entry Points
- 스케줄: EventBridge 12시간 주기(rate 12 hours) → Fargate `python -m parity_runner --once` (모델 discovery 후 `run_parity()`)
- 수동: `POST /api/parity/trigger` (JWT) — backend 프로세스 내 백그라운드 스레드 (Fargate 아님)

## Gotchas
- **판정이 이상하면 프로브 결함부터 의심**: run #1에서 `max_tokens=64` 절단으로 Claude 전 모델 structured_output이 false-Broken (v2.11.1 수정). Broken 셀은 `/api/parity/evidence`의 `response_snippet`으로 원인 확인
- 피처 추가 시: `catalog.py` FEATURES + `probes.py` 5개 실행기 모두 + `is_applicable()` 규칙. 모델 추가는 자동 반영 (`prober.AVAILABLE_MODELS` 순회)
- 알려진 지속 이슈 (모델측): Fable 5 캐싱이 Converse/CP-Messages에서 cacheRead 0 (InvokeModel은 정상), GPT 5.4는 reasoning_tokens 미보고
- 테스트: `backend/tests/test_parity_logic.py` (catalog + engine 순수 로직, python3.12 필수)
