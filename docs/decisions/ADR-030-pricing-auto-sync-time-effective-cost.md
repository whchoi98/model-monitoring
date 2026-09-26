# ADR-030: 공식 단가 12시간 자동 동기화 + 프로브 시각 단가로 비용 계산 — model_id 단위 단가 이력, 50% 안전장치와 관리자 승인

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: ADR-025의 "비용은 조회 시점 계산이라 단가를 바꾸면 과거 행도 소급 재계산된다" 정책(ADR-027, ADR-028이 같은 정책을 인용한 문장 포함)
- **Related**: ADR-011 (Scheduler IAM family `:*`), ADR-018 (digest 고정 배포), ADR-019, ADR-020 (OpenAI Mantle, 1P), ADR-025 (채널별 단가), ADR-027, ADR-028 (agreement offer 단가 출처), v2.30.0, 설계 문서 `docs/superpowers/specs/2026-09-26-pricing-menu-design.md`
- **Code**: `backend/pricing_sources.py`, `backend/pricing_seed.py`, `backend/pricing_parsers.py`, `backend/pricing_sync.py`, `backend/pricing_sync_runner.py`, `backend/price_history.py`, `backend/pricing_payload.py`, `backend/pricing_export.py`, `backend/routers/pricing.py`, `backend/models.py`(`PriceHistory`, `PriceSyncRun`), `backend/routers/cost.py`, `backend/routers/efficiency.py`, `frontend/src/components/PricingPanel.tsx`, `frontend/src/lib/pricingTable.ts`, `cdk/lib/stacks/scheduler-stack.ts`(`PricingSync*`)

## Context

v2.29.1까지 모델 단가는 `backend/pricing.py` `PRICE_TABLE`에 코드로 고정돼 있었고, `frontend/src/lib/pricing.ts`가 같은 표를
복사해 들고 있었다. 비용 화면과 효율성 점수는 조회할 때마다 그 표로 계산했다(ADR-025의 소급 정책). 그 결과 세 가지 문제가
있었다.

1. 단가가 바뀌면 사람이 모델 카드를 보고 두 파일을 함께 고쳐야 했다. 두 표를 비교하는 테스트는 없었다.
2. 키 정규화(`_normalize_key`)와 prefix fallback 때문에 정확한 키가 빠지면 형제 모델의 단가가 조용히 붙었다. Opus 5.5 키가
   없으면 Opus 5의 $5 / $25가 붙었고, GPT-6은 "3키를 항상 함께 둔다"는 규칙으로 막아야 했다.
3. 단가를 고치면 과거 전체가 새 단가로 다시 계산됐다. 2026-07-30 GPT-5.6 Luna −80%, Terra −20% 인하와 2026-09-23 Sol 프로모션
   반영 때 그 이전 프로브도 새 단가로 보였다.

2026-09-26 스파이크(읽기 전용, 설계 검토에서 재검증)에서 공식 출처 3개를 조합하면 활성 55채널 전부의 Standard 단가를
기계적으로 읽을 수 있음을 확인했다. 같은 조사에서 코드 단가 오류 11채널을 찾았다(Decision 2의 표).

| 출처 | 대상 채널 | 호출 |
|------|-----------|------|
| Bedrock agreement offer rate card | Bedrock Claude 20 + OpenAI 25 (파운데이션 모델 18개 = Claude 10 + OpenAI 8) | `bedrock.list_foundation_model_agreement_offers(modelId=<FM id>, offerType="PUBLIC")`, 리전 무관(us-east-1과 ap-northeast-2가 같은 offerId, rateCard), 18개 합계 약 25초 |
| AWS Price List API | Nova 2.0 Lite | `pricing.get_products(ServiceCode="AmazonBedrock")`, usagetype 정확 일치 `USE1-Nova2.0Lite-input-tokens` / `USE1-Nova2.0Lite-output-tokens`, 단위 `1K tokens` → ×1000 |
| Anthropic 공식 단가 문서 | Claude Platform on AWS 9 | `GET https://platform.claude.com/docs/en/about-claude/pricing.md`, "## Model pricing" 첫 표. 문서가 Claude Platform on AWS는 Claude API와 같은 표준 단가라고 명시 |

`amazon.nova-2-lite-v1:0`은 agreement offer가 `ValidationException: Agreement not supported for this model`이라 Price List로 읽는다.

사용자 요청(2026-09-26): 모델별 단가를 한 화면에서 보는 새 메뉴 `/pricing`("비용 단가" / "Unit Prices"), 공식 출처에서
12시간마다 자동 갱신, CSV, Markdown, JSON 다운로드, 출처 각주, "참고용이며 AWS 공식 입장이 아님" 면책 문구, 비용은 각 프로브
시각에 유효했던 단가로 계산.

## 검토한 선택지

| 결정 | 선택지 | 판단 |
|------|--------|------|
| 단가 원천 | **A. 백엔드 단일 출처 `GET /api/pricing`, 프런트 미러 삭제** | 채택(사용자 결정). 두 표 불일치가 구조적으로 사라진다 |
| | B. 프런트 미러 유지, 동기화 결과만 백엔드 반영 | 기각. 두 표를 맞추는 수작업과 불일치 위험이 그대로다 |
| 비용 시점 | A. 조회 시점 소급 계산(ADR-025) | 기각. 단가가 바뀔 때마다 과거 비용이 바뀐다 |
| | **B. 시점 단가(각 프로브 시각에 유효했던 단가)** | 채택(사용자 결정). 단가 이력을 보존한다 |
| v2.30.0 이전 변경 | **A. 재구성하지 않음, seed가 과거 전체에 적용** | 채택(설계 검토 권장안 A, 사용자 결정). 결과가 기존 소급 계산과 같다 |
| | B. 알려진 변경(2026-07-30 Luna, Terra 인하, Sol 프로모션 시작)을 이력으로 재구성 | 기각. 공식 출처가 이력과 정확한 시작 시각을 주지 않아 추정이 섞인다 |
| 코드 단가 오류 11채널 | **A. 과거까지 교정** | 채택(사용자 결정). 단가 변경이 아니라 처음부터 틀린 값이다 |
| | B. 첫 동기화부터만 교정 | 기각. 틀린 값이 과거 비용에 남는다 |
| 변경 적용 | A. 관측한 값을 모두 자동 적용 | 기각. 단위 오류(1000배)나 파서 오류가 비용에 그대로 들어간다 |
| | **B. 변화율 50% 이하 자동 적용, 초과는 관리자 승인** | 채택 |
| | C. 모든 변경을 관리자 승인 | 기각. 12시간마다 사람이 봐야 해 자동 갱신의 의미가 없다 |
| 저장 단위 | A. 패밀리 키(`claude-opus-5-5`, `gpt-6-sol-global`) 단위 | 기각. prefix fallback과 키 정규화 오류(US = Global 오류의 원인)가 남는다 |
| | **B. `model_id` 단위**(`probe_results.model_id`와 같은 값) | 채택. 비용 조인이 정확 일치라 prefix fallback이 구조적으로 사라진다 |

## Decision

### 1. 단가 이력 — `price_history`, `price_sync_runs`

- 두 테이블은 `backend/models.py` ORM(`PriceHistory`, `PriceSyncRun`)과 `create_all`로 만든다. lifespan ALTER 블록에는 넣지 않는다.
- `price_history` 행 하나는 `model_id`, `family_key`, `channel`(`cp`, `global`, `us`, `inregion:<region>`), `input_per_mtok`,
  `output_per_mtok`(USD per 1M tokens), `effective_from`, `source_id`, `status`(`seed`, `verified`, `pending_review`, `rejected`),
  `observed_at`(출처에서 마지막으로 확인한 시각, seed는 NULL), `run_id`다. 인덱스 `ix_price_history_model_eff(model_id, effective_from)`.
- **유효 행**은 같은 `model_id`에서 `status`가 `seed` 또는 `verified`이고 `effective_from <= t`인 행 중 `(effective_from, id)`가 가장
  늦은 행이다.
- 저장과 비용 계산은 float다. 동기화 비교에만 `Decimal(str(round(v, 6)))`를 쓴다(PostgreSQL `numeric`이 `Decimal`로 돌아와
  float 누적에서 `TypeError`가 나는 문제를 피한다). 출처에서 읽은 값은 비교와 저장 전에 소수 6자리로 정규화한다
  (`pricing_sync.PRICE_QUANTUM`, `price_number` 표시 정밀도와 같음). 그래서 저장 값과 표시 값이 같고, 7자리 이하 잡음이 변경으로
  잡히지 않는다.
- 모든 시각은 timezone-aware datetime을 ORM/Core 바인드 파라미터로 넣는다(SQLite는 DateTime을 문자열로 비교한다).
- `pricing_sources.price_identity(model_id)`가 활성 채널을 모두 분류한다(`family_key`, `family`, `provider`, `channel`,
  `source_kind`, `source_ref`). 분류할 수 없는 id는 예외가 아니라 `None`이고 그 채널은 단가 없음("-")이 된다. Claude Platform on AWS
  id는 런타임 디스커버리로 정해지고 날짜 접미사가 붙을 수 있어 prober `_ANTHROPIC_TARGETS`와 같은 substring 규칙과
  `_is_point_release_of`로 분류한다. `family` 문자열은 프런트 `lib/sortModels.ts` `FAMILY_ORDER`와 바이트 단위로 같고, pytest가
  두 목록의 동등성을 고정한다.

### 2. seed와 과거 교정

- `pricing_seed.SEED`는 활성 55채널 중 CP를 뺀 46채널의 공식 단가를 `model_id` 단위로, `CP_SEED`는 CP 9패밀리를 `family_key`
  단위로 둔다(CP id가 바뀔 수 있으므로 `ensure_seed`가 현재 활성 CP model_id로 풀어 넣는다).
- `ensure_seed(engine, active)`는 **model_id 단위 멱등 삽입**이다. 그 model_id 행이 하나도 없을 때만 `effective_from`
  1970-01-01T00:00:00Z, `status='seed'`, `observed_at` NULL로 넣는다. 마이그레이션과 분리된 자체 트랜잭션에서
  `SET LOCAL statement_timeout = '30000'`, `SET LOCAL lock_timeout = '5000'`을 먼저 걸고 `pg_advisory_xact_lock(917350003)` 아래
  실행한다(SQLite는 둘 다 생략). 잠금 대기나 느린 쿼리가 lifespan과 러너를 붙잡지 않고 예외로 끝난다. 호출 위치는 backend lifespan(모델 등록 다음, 실패해도 기동
  계속)과 `pricing_sync_runner`(모델 등록 → seed → 동기화)다. 그래서 동기화가 먼저 돌아도 seed가 빠지지 않는다.
- seed가 1970년부터 유효하므로 첫 동기화 이전 구간은 seed로 계산한다. 44채널은 v2.29.1 코드 값과 같아 비용이 변하지 않고,
  아래 11채널만 과거 전체가 교정된다.

| 채널 | model_id | v2.29.1 코드 (입력 / 출력) | 공식 = seed (입력 / 출력) |
|------|----------|----------------------------|---------------------------|
| Bedrock Claude Fable 5.1 (US) | `us.anthropic.claude-fable-5-1` | $10 / $50 | $11 / $55 |
| Bedrock Claude Fable 5 (US) | `us.anthropic.claude-fable-5` | $10 / $50 | $11 / $55 |
| Bedrock Claude Opus 5.5 (US) | `us.anthropic.claude-opus-5-5` | $4 / $20 | $4.40 / $22 |
| Bedrock Claude Opus 5 (US) | `us.anthropic.claude-opus-5` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Opus 4.8 (US) | `us.anthropic.claude-opus-4-8` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Opus 4.7 (US) | `us.anthropic.claude-opus-4-7` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Opus 4.6 (US) | `us.anthropic.claude-opus-4-6-v1` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Sonnet 5 (US) | `us.anthropic.claude-sonnet-5` | $2 / $10 | $2.20 / $11 |
| Bedrock Claude Sonnet 4.6 (US) | `us.anthropic.claude-sonnet-4-6` | $3 / $15 | $3.30 / $16.50 |
| Bedrock Claude Haiku 4.5 (US) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | $1 / $5 | $1.10 / $5.50 |
| Bedrock Nova 2.0 Lite (US) | `us.amazon.nova-2-lite-v1:0` | $0.06 / $0.24 | $0.33 / $2.75 |

- Bedrock Claude US 10채널: `_normalize_key`가 `us.`와 `global.`을 같은 키로 합쳐 Global 단가가 붙었다. 오퍼 rate card의 US(Geo)
  단가는 Global × 1.1이므로 약 9.1% 과소 산정이었다.
- Nova 2.0 Lite: 1세대 Nova Lite 단가가 들어가 있었다. 입력 5.5배, 출력 11.5배 과소 산정이었다.

### 3. 12시간 동기화 (`pricing_sync.py`, `pricing_sync_runner.py`)

1. 러너는 `create_tables()` → `prober._discover_anthropic_models()`, `prober._register_openai_models()`(AutoProber와 같은 env,
   secret) → `ensure_seed` 순서로 준비한다. 활성 채널은 `AVAILABLE_MODELS`에서 숨김 라벨(`HIDDEN_MODEL_PATTERNS`, 기본 `(1P)`)을
   빼고 `price_identity`로 분류한 것이다. CP 디스커버리가 실패하면 CP 9채널은 변경 없음, 런은 `partial`이다.
2. 런 전체 동안 `pg_try_advisory_lock(917350004)`를 쥐어 런이 겹치지 않게 한다. 기다리지 않는 잠금이라, 잠금을 못 잡으면 경고 로그를 남기고 즉시 exit 1로 끝낸다(런 행 없음). `ensure_seed`가
   실패해도 동기화하지 않고 exit 1이다 — seed 없이 돌면 `no_baseline` 행이 생기고, model_id 단위 멱등 규칙 때문에 그 채널의 seed가
   영구히 빠진다.
3. 출처별로 한 번씩, Anthropic 문서 → Price List → offers 순서로 가져온다(느린 offers가 싼 출처를 `skipped:deadline`으로 밀어내지
   않게). offers는 FM 18개를 중복 없이 순차 호출하고, 각 호출은 `ThrottlingException` 계열, 5xx, HTTP 429, 연결 오류에 1초, 2초,
   4초 간격으로 최대 3회 재시도한다(botocore 자체 재시도는 끈다). 300초 상한은 호출 직전에만 검사하고 진행 중인 호출은 끊지 않는다. 오퍼 응답의 `offerToken`과 `legalTerm.url`(presigned URL)은 저장하거나 로그에 남기지 않는다.
   호출 실패, 파서 오류, 상한 초과 같은 런 오류는 문구마다 `pricing sync: …` 경고 로그로 남기고 런 요약 `summary.errors`(앞 50개)에도
   저장한다. 요약을 보여 주는 API가 없어서 운영 진단은 로그로 한다.
4. 오퍼 차원 이름은 허용 목록 정규식에 **완전 일치**할 때만 후보다.
   `^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?(?:(?P<io>input|output)_tokens(?P<g>_global)?_standard|(?P<IO>Input|Output)TokenCount(?P<G>_Global)?)$`
   그래서 batch, flex, priority, long-context, cache, reserved, GovCloud, 그 밖의 리전 접두는 후보가 되지 않는다. 오퍼가 정확히
   1개가 아니면 그 FM의 채널은 변경 없음이다. 채널별 선택 순서는 `global`이 `APN2_*_global_standard` → `USE1_*_global_standard` →
   평면 `*_global_standard` → 레거시 `APN2_*TokenCount_Global` → `USE1_*TokenCount_Global`, `us`가 `USE1_*_standard` → 평면
   `*_standard` → 레거시 `USE1_*TokenCount`, `inregion:<region>`이 리전 접두 → 평면 `*_standard`다. 단위는 USD per 1M tokens로
   해석하고 GPT-6 Astra 카드 값(standard 11 / 55, global 10 / 50)으로 fixture에서 고정한다.
5. Anthropic 문서는 헤더 이름("Model", "Base input tokens", "Output tokens")으로 열을 찾고, 모델명과 값 셀에서 `<sup>…</sup>`를
   지우고, 모델명 끝 괄호 그룹(마크다운 링크 포함)을 지운 뒤 매핑 표와 **정확 일치**로만 연결한다. 표에서 "Claude Opus 5.5"가
   "Claude Opus 5"보다, "Claude Fable 5.1"이 "Claude Fable 5"보다 먼저 나오므로 접두 일치는 금지다(prober `_is_point_release_of`
   실사고와 같은 유형).
6. 채널별 판정. 관측 값은 비교 전에 소수 6자리로 정규화하고(0으로 반올림되는 양수 값은 파싱 실패다, 0 단가는 저장하지 않는다),
   변화율은 입력과 출력 각각 `|new − old| / old`(`Decimal`)다. 파서 예외는 `PriceParseError`가 아니어도(예상하지 못한 응답 형태의
   `KeyError`, `TypeError` 등) 그 출처(offers는 그 FM id)의 채널만 `skipped:parse_failed`로 두고 런을 실패시키지 않는다. Price List의
   중첩 필드(`product`, `terms`, `priceDimensions`, `pricePerUnit`)는 객체인지 검사해 형식이 다르면 `PriceParseError`로 끝낸다.

| 결과 | 조건 | 기록 |
|------|------|------|
| `unchanged` | 새 값 = 현재 유효 값 | 유효 행의 `observed_at`, `run_id`, `source_id`만 갱신(offerId가 재발급돼도 참고 자료가 현재 오퍼를 가리킨다) |
| `changed` | 다르고 두 변화율 모두 0.5 이하(경계 포함) | 새 행 `verified`, `effective_from = observed_at =` 런 시작 시각 |
| `pending` | 어느 쪽이든 0.5 초과 | 같은 값의 `pending_review` 또는 `rejected` 행이 있으면 그 행의 `observed_at`만 갱신(거부한 값은 값이 달라질 때까지 다시 올라오지 않는다), 없으면 새 행 `pending_review`, `effective_from = observed_at =` 런 시작 시각 |
| `no_baseline` | 유효 행이 없음(seed에도 없는 새 model_id) | 같은 값의 `pending_review` 또는 `rejected` 행이 있으면 그 행의 `observed_at`만 갱신, 없으면 새 행 `pending_review`, `effective_from` 1970-01-01, `observed_at` 런 시작 시각 |
| `rejected` | `pending` 또는 `no_baseline` 조건이지만 같은 값의 `rejected` 행이 있음 | 그 행의 `observed_at`만 갱신(관측 성공이며 검토 대기 수에 넣지 않는다) |
| `skipped:<reason>` | 공식 값을 구하지 못함(출처 실패, 오퍼 수 ≠ 1, 필수 차원 없음, 매핑 없음, 파싱 실패, `deadline`) | 변경 없음 |

7. 런 행은 시작할 때 `running`으로 넣고 커밋한다. 끝날 때 공식 값을 얻은 채널이 하나도 없으면(모든 출처 실패, 첫 호출 전 상한 초과
   포함) `failed`, `skipped:<reason>` 채널이 하나라도 있거나 활성 채널이 없는 출처가 있으면(CP 디스커버리 실패 →
   `anthropic_doc: no active channels`) `partial`(상한을 넘긴 뒤 남은 채널은 `skipped:deadline`), 그 밖에는 `completed`다.
   `summary`에는 출처별 호출, ok, failed 수와 채널별 결과, 오류(최대 50개)를 싣고, `changes`는 새 verified 행 수, `pending`은 런 뒤
   검토 대기 중인 채널 수다. 출처와 파서 오류는 채널 결과로만 남고, DB 오류 같은 내부 오류만 런을 `failed`(오류 `internal: …`)로
   닫은 뒤 예외를 다시 던진다. 러너는 `completed`, `partial`이면 exit 0, `failed`나 내부 오류면 exit 1이고 `os._exit`로 끝난다.

### 4. 검토 대기 승인 (관리자)

- `GET /api/admin/pricing/pending`은 대기 행마다 현재 유효 값, 새 값, 변화율, 출처, 사유(`changed`, `no_baseline`)를 준다.
- `POST /api/admin/pricing/pending/{id}/approve`는 `status`만 `verified`로 바꾼다. `effective_from`은 삽입 때 값(관측 런의 시작
  시각, `no_baseline`이면 1970-01-01) 그대로이며, 단가 조회 순서 `(effective_from, id)`에서 그 행보다 뒤에 오는 verified 행(더 늦은
  시작, 또는 같은 시작에 더 큰 id)이 이미 있으면 응답 `warnings`에 싣는다. 그 구간은 뒤의 행이 계속 우선한다.
  `POST …/reject`는 `rejected`로 바꾼다. 없는 id는 404(`단가 행 <id>을(를) 찾을 수 없습니다`), `pending_review`가 아닌 행은
  409(`단가 행 <id>는 검토 대기 상태가 아닙니다 (현재: <status>)`)이고 `detail`은 한국어다.
- 모두 admin 전용(`username == "admin"`)이다. 처리한 backend 태스크는 `/api/pricing` 캐시를 바로 비우고, 다른 backend 태스크는
  최대 60초 늦을 수 있다. 캐시에는 세대 카운터가 있어, 비우기와 겹쳐 만든 표는 응답으로만 쓰고 캐시에 넣지 않는다.

### 5. 비용 계산

- `price_history.effective_prices_subquery()`는 `seed`, `verified` 행에 `effective_to = LEAD(effective_from) OVER (PARTITION BY
  model_id ORDER BY effective_from, id)`를 붙인다. `with_row_cost(query)`는 `probe_results`를 `model_id` 일치와 `timestamp >=
  effective_from AND (effective_to IS NULL OR timestamp < effective_to)`로 **LEFT JOIN**하고
  `row_cost = (COALESCE(input_tokens, 0) × input_per_mtok + COALESCE(output_tokens, 0) × output_per_mtok) / 1,000,000`(float
  캐스트)을 만든다. 단가 행이 없으면 NULL이다.
- `/api/cost/summary`, `/api/cost/channel-compare`는 `row_cost`를 모델(또는 채널)별로 합산한다. 단가가 없는 모델은 비용 NULL
  (화면 "-")이고 토큰은 합계에 들어가며, 채널 비교는 NULL을 0으로 더하던 동작을 유지한다. `/api/cost/trend`와
  `/api/efficiency/score`는 기존 Python 순회에 행 단위 `row_cost`를 쓴다(efficiency는 단가가 있는 success 행만 평균). 필터와
  응답 형태는 그대로다.
- v2.29.1 `PRICE_TABLE`, `estimate_cost_usd` 고정 사본을 테스트에 두고, 단가 변경이 없는 구간에서 새 계산이 사본 계산과
  같음(교정 11채널 제외)과 반환형이 float임을 고정한다.

### 6. 표시와 다운로드

- `GET /api/pricing`(공개, 60초 인메모리 캐시)이 표 전체를 내려준다. 표시 순서(`PROVIDER_ORDER` Anthropic Claude → Amazon Nova →
  OpenAI, 그 안은 `FAMILY_ORDER`)와 각주 번호는 백엔드가 정하고, 프런트와 export 3형식은 받은 순서와 번호를 그대로 쓴다.
- 셀별 계산 상태 `verification`: `seed_only`(유효 행이 seed이고 한 번도 확인되지 않음), `verified`(유효 행의 `observed_at`이 가장
  최근에 끝난 런의 시작 시각 이후 — 런 상태 무관), `stale`(그 밖). 한 출처가 계속 실패하면 그 채널은 곧 `stale`이 되어 "자동 확인
  안 됨" 배지로 드러난다. 배지 툴팁은 `stale`이면 "마지막 확인 <날짜>"(`observed_at`이 없으면 "마지막 확인일 없음"), `seed_only`면
  "초기값"이다.
- 응답의 `pending_review`는 검토 대기 행이 있는 활성 채널 수(`model_id` 중복 제거)로, `price_sync_runs.pending`과 같은 기준이다.
- 면책 문구는 `pricing_sources.DISCLAIMER` 한 곳에만 둔다. KO "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며,
  AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.", EN "This price list is compiled automatically from
  public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing
  pages." 화면 상단 안내 상자, 참고 자료 끝, CSV 첫 줄, Markdown 처음과 끝, JSON 본문에 모두 들어간다. CSV 첫 줄은 BOM 뒤
  `"# <면책 문구>"`를 따옴표로 감싼 필드 하나로 쓴다(`csv.writer`, 문구의 쉼표가 열을 나누지 않는다).
- GPT-5.6 Sol 프로모션(In-Region, Geo $4.40 / $22, Global $4 / $20)의 "최소 2026-11-21까지"는 현재 공식 출처 어디에도 없다.
  그래서 공식 출처가 아닌 **수동 메모**(`PRICE_NOTES`, 근거는 2026-09-23 AWS 모델 카드 기재와 CHANGELOG v2.28.1)로 두고 참고
  자료에 `manual_note`로 구분해 싣는다. 동기화가 이전 단가(`prior_price`)를 관측하면 메모는 응답에서 빠진다.
- 범위: USD, Standard 입력과 출력만(캐시, batch, long-context, priority, flex 제외), 휴면 1P와 숨김 채널 제외.

### 7. 인프라

- `cdk/lib/stacks/scheduler-stack.ts`: `PricingSyncTaskRole`(인라인 정책 `bedrock:ListFoundationModelAgreementOffers`,
  `pricing:GetProducts`, Resource `*`만 — 모델 호출 권한 없음), 공용 `buildTaskDef`로 만든 `PricingSyncTaskDef`(AutoProber와 같은
  env, secret, 0.5 vCPU / 1 GB, 로그 그룹 `/ecs/pricingsync` 14일), `PricingSyncSchedule` `rate(12 hours)`. Scheduler 역할의
  `RunTaskFamilyWildcard`에 새 family `:*`, `PassTaskRoles`에 새 역할을 넣는다(ADR-011).
- 공식 출처 호출은 App 서브넷 NAT egress로 나간다(us-east-1 Bedrock control plane과 Price List API, `platform.claude.com`).

## Consequences

- (+) 단가가 코드 수정 없이 12시간마다 공식 출처를 따라간다. 두 표를 맞추는 수작업과 prefix fallback 오매칭이 사라졌다.
- (+) 과거 비용이 단가 변경에 흔들리지 않는다. 첫 동기화 이후의 인하, 인상은 관측한 런의 시작 시각부터 적용된다.
- (+) 코드 단가 오류 11채널이 과거까지 교정됐다. Bedrock Claude US 채널 비용이 약 10% 늘고 Nova 2.0 Lite 비용이 크게 는다.
- (+) 형식 드리프트(차원 스킴, 문서 구조, 단위)는 허용 목록과 fail-closed로 잘못된 값 적용을 막고 "자동 확인 안 됨"으로 드러난다.
  50% 안전장치가 단위 오류(1000배)를 막는다.
- (−) **v2.30.0 이전 구간의 알려진 단가 변경은 재구성하지 않았다.** 2026-07-30 GPT-5.6 Luna, Terra 인하 이전과 GPT-5.6 Sol
  프로모션 이전의 프로브도 현재 seed 단가로 계산된다(기존 소급 계산과 같은 결과).
- (−) **정상적인 대폭 변경도 승인이 필요하다.** 2026-07-30 Luna −80% 같은 인하는 `pending_review`로 가며, 관리자가 승인하면
  관측한 런의 시작 시각부터 적용된다. 반대로 Sol 프로모션이 끝나 이전 단가로 돌아가면 입력 +25%, 출력 +50%(22 → 33, 20 → 30)라
  경계 포함 규칙으로 자동 적용된다.
- (−) 승인 직후 다른 backend 태스크는 최대 60초 동안 이전 표를 줄 수 있다.
- (−) 오퍼 rate card에는 단위 스케일 정보가 없어 "USD per 1M tokens" 해석을 fixture 대조로 고정한다. AWS가 스킴을 바꾸면 파서와
  fixture를 고쳐야 한다.
- (−) 새 모델을 추가할 때 `pricing_sources.py` 매핑과 `pricing_seed.py`도 고쳐야 한다. "활성 채널 전부가 분류되고 seed 단가가 있다"
  테스트가 CI에서 누락을 잡고, 운영에서는 `no_baseline` 검토 대기로 드러난다.
- (−) 1P direct 채널(휴면)은 분류 대상이 아니다. 재노출하려면 1P 정가 출처와 분류, seed를 새로 설계해야 한다.
- ADR-025, ADR-027, ADR-028의 "비용은 조회 시점 계산이라 소급 재계산된다" 문장은 당시 기록으로 남기고, ADR-025에 이 ADR을 가리키는
  후속 절을 붙였다.
