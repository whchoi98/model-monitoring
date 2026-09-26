# Backend Parity — 실행-증거 패리티 런 엔진 (v2.11.0)

## Role
모니터링 카탈로그의 모델 × API surface × 피처 매트릭스를 실제 API 호출로 검증한다.
**HTTP 200은 증거가 아니다** — 응답 내용이 증거 검사를 통과해야 `supported`.
결과는 `parity_runs` / `parity_results` 테이블에 저장되고 `/parity` 페이지가 렌더링한다.

## Files
- `catalog.py` — `SURFACES` 6개 (converse / invoke_model / messages / messages_mantle / chat_completions / responses), `FEATURES` 19개 (각 항목 label_ko/desc_ko + label_en/desc_en — 프론트 현지화용, v2.16.2) (기본 7 + v2.14.0: adaptive_thinking, count_tokens, batches, web_search, computer_use + v2.15.0: reasoning_effort, json_schema, url_sources, memory_tool, code_execution, files_api, models_api — `_FEATURE_SURFACES` 맵으로 surface 제한). Admin/Usage API·MCP connector는 정직한 판정 불가로 의도적 제외. `surfaces_for(model_id)` — model_id 접두사로 surface 결정 (Bedrock Claude는 messages_mantle 포함), `mantle_fm_id()` — 프로파일 접두사 제거, `is_applicable()` — reasoning은 `_REASONING_MARKERS` 모델만
- **messages_mantle** (v2.13.0): Bedrock Mantle `/anthropic` 엔드포인트 시험 — `aws-bedrock-token-generator`의 SigV4 파생 bearer + FM id, 리전 `MANTLE_ANTHROPIC_REGION` — env 미주입 시 코드 폴백은 `ap-northeast-1`이지만, CDK가 backend와 모든 스케줄 태스크에 `us-east-1`을 명시 주입한다(2026-09-05 결정 — `ap-northeast-1`은 `/anthropic`에서 Opus 4.8만 서빙). 따라서 배포 환경의 `messages_mantle`과 Claude API Features Mantle 열은 둘 다 `us-east-1`을 프로빙한다. 리전이 서빙하지 않는 FM id는 `does not exist` 오류로 오고, `engine.classify_error`가 unsupported(명시적 미지원)로 판정한다
- `engine.py` — 순수 판정 로직 (외부 의존 없음, 단위 테스트 대상): `classify_error()` (`_UNSUPPORTED_MARKERS` 시그니처 → unsupported, 그 외 → broken), `check_canary` / `check_json_object` / `check_tool_roundtrip` / `check_cached_tokens` / `check_stream_events`
- `probes.py` — surface별 실행기 5개. `CANARY`, `max_tokens_for(feature)` (structured_output 512 / 기본 256 / reasoning 2048), adaptive_thinking 프로브는 `max_tokens_for`를 거치지 않고 `_ADAPTIVE_MAX_TOKENS` 8000을 직접 쓴다(2048이면 adaptive가 thinking을 생략 — run #8), `_CACHE_PAD` (최소 캐시 토큰 초과용 장문 패딩). 클라이언트는 `prober.py` 헬퍼 재사용
- `runner.py` — `run_parity()`: ParityRun row 생성 → job 팬아웃 (skipped는 프로브 없이 기록) → ThreadPoolExecutor(4) → 결과 메인 스레드 일괄 저장 (스레드별 DB 세션 금지)
- **OpenAI 클라이언트는 prober와 따로 둔다** (v2.28.2): `runner._parity_openai_client`가 SDK 기본값(timeout 600s, `max_retries` 2) 클라이언트를 만든다. prober `_get_openai_client`의 `max_retries=0` + read 60s는 대시보드 프로브 hang 대책이고, 패리티에 적용하면 SDK가 재시도해 주던 429/5xx/연결 오류가 `classify_error`에서 broken 셀이 된다. 공유하는 것은 자격증명 선택(`prober._openai_api_key`)뿐 (테스트: `tests/test_parity_openai_client.py`)

## Entry Points
- 스케줄: EventBridge 12시간 주기(rate 12 hours) → Fargate `python -m parity_runner --once` (모델 discovery 후 `run_parity()`)
- 수동: `POST /api/parity/trigger` (JWT) — backend 프로세스 내 백그라운드 스레드 (Fargate 아님)

## Gotchas
- **판정이 이상하면 프로브 결함부터 의심**: `max_tokens`가 모자라 출력이 잘리면 모델 문제가 아닌데도 증거 검사가 실패해 Broken이 된다(`probes.max_tokens_for`가 피처별 예산을 두는 이유). Broken 셀은 `/api/parity/evidence`의 `response_snippet`으로 원인 확인
- 피처 추가 시: `catalog.py` FEATURES + `probes.py` 5개 실행기 모두 + `is_applicable()` 규칙. 모델 목록은 자동 반영 (`prober.AVAILABLE_MODELS` 순회)이지만, 새 모델마다 `catalog.py`의 `_REASONING_MARKERS`(reasoning 적용 대상, substring 매칭)와 `_NO_FORCED_TOOL_CHOICE_MARKERS`(forced `tool_choice` 400 → tool_use를 auto + 지시로 대체)를 검토한다 — 둘 다 substring이라 짧은 마커가 형제 모델까지 잡는다(예: `"opus-5"`를 넣으면 Opus 5도 auto)
- 알려진 지속 이슈 (모델측): Fable 5 캐싱이 Converse/CP-Messages에서 cacheRead 0 (InvokeModel은 정상), GPT 5.4는 reasoning_tokens 미보고
- 테스트: `backend/tests/test_parity_logic.py` (catalog + engine 순수 로직) + `test_parity_openai_client.py` — `cd backend && python3.12 -m pytest tests/test_parity_logic.py tests/test_parity_openai_client.py -q`. Python 3.10+ 필요(CI는 3.11), 개발 호스트는 시스템 python3가 3.9라 python3.12를 쓴다
