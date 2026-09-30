# ADR-030: 공식 단가 12시간 자동 동기화 + 프로브 시각 단가로 비용 계산 — model_id 단위 단가 이력, 50% 안전장치와 관리자 승인

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: ADR-025의 "비용은 조회 시점 계산이라 단가를 바꾸면 과거 행도 소급 재계산된다" 정책(ADR-027, ADR-028이 같은 정책을 인용한 문장 포함)
- **Related**: ADR-011 (Scheduler IAM family `:*`), ADR-018 (digest 고정 배포), ADR-019, ADR-020 (OpenAI Mantle, 1P), ADR-025 (채널별 단가), ADR-027, ADR-028 (agreement offer 단가 출처), v2.30.0, v2.31.0, 설계 문서 `docs/superpowers/specs/2026-09-26-pricing-menu-design.md`(v2.31.0 부록은 `docs/superpowers/specs/2026-09-27-pricing-v2-31-design.md`)
- **Code**: `backend/pricing_sources.py`, `backend/pricing_seed.py`, `backend/pricing_parsers.py`, `backend/pricing_sync.py`, `backend/pricing_sync_runner.py`, `backend/price_history.py`, `backend/pricing_payload.py`, `backend/pricing_export.py`, `backend/routers/pricing.py`, `backend/models.py`(`PriceHistory`, `PriceSyncRun`), `backend/routers/cost.py`, `backend/routers/efficiency.py`, `frontend/src/components/PricingPanel.tsx`, `frontend/src/lib/pricingTable.ts`, `cdk/lib/stacks/scheduler-stack.ts`(`PricingSync*`), `backend/main.py`(v2.31.0 `_ensure_price_schema`, `_retry_price_schema`)

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
   `summary`에는 출처별 호출, ok, failed 수와 채널별 결과, 오류(최대 50개)를 싣고, `changes`는 새 verified 행 수, `pending`은 이
   런이 검토 대기로 분류한 채널 수다. 결과가 `pending` 또는 `no_baseline`인 채널, 즉 새 `pending_review` 행을 넣었거나 같은 값의
   대기 행을 다시 관측한 채널이다(같은 값의 `rejected` 행이 있는 채널은 `rejected`라 빠진다). 앞선 런이 남긴 대기 행이 있어도 이
   런의 결과가 건너뜀, 변경 없음, 자동 적용이면 세지 않는다(Decision 6의 `pending_review`와 다른 기준). 출처와 파서 오류는 채널
   결과로만 남고, DB 오류 같은 내부 오류만 런을 `failed`(오류 `internal: …`)로 닫은 뒤 예외를 다시 던진다. 러너는 `completed`, `partial`이면 exit 0, `failed`나 내부 오류면 exit 1이고 `os._exit`로 끝난다.

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
  안 됨" 배지로 드러난다. 배지 옆 설명(툴팁이 아니라 화면 글자라 터치, 키보드 사용자도 본다)은 `stale`이면 "공식 출처 확인
  <날짜>"(`observed_at`이 없으면 "공식 출처 확인일 없음"), `seed_only`면 "초기값"이다.
- 응답의 `pending_review`는 `pending_review` 행이 하나라도 있는 활성 채널 전부의 수(`model_id` 중복 제거)다. 어느 런이 남긴
  행인지 가리지 않는다. `price_sync_runs.pending`은 한 런이 검토 대기로 분류한 채널만 세므로(Decision 3의 7번), 앞선 런의 대기 행을
  그 런이 다시 관측하지 못한 채널이 빠져 이 수보다 작을 수 있다.
- 면책 문구는 `pricing_sources.DISCLAIMER` 한 곳에만 둔다. KO "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며,
  AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.", EN "This price list is compiled automatically from
  public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing
  pages." 화면 상단 안내 상자, 참고 자료 끝, CSV 첫 줄, Markdown 처음과 끝, JSON 본문에 모두 들어간다. CSV 첫 줄은 BOM 뒤
  `"# <면책 문구>"`를 따옴표로 감싼 필드 하나로 쓴다(`csv.writer`, 문구의 쉼표가 열을 나누지 않는다).
- GPT-5.6 Sol 프로모션(In-Region, Geo $4.40 / $22, Global $4 / $20)의 "최소 2026-11-21까지"는 현재 공식 출처 어디에도 없다.
  그래서 공식 출처가 아닌 **수동 메모**(`PRICE_NOTES`, 근거는 2026-09-23 AWS 모델 카드 기재와 CHANGELOG v2.28.1)로 두고 참고
  자료에 `manual_note`로 구분해 싣는다. 참고 자료 제목은 패밀리 이름(`FAMILY_ORDER` 문자열) 뒤에 종류와 근거를 붙인
  "GPT 5.6 Sol 프로모션 (수동 메모, 2026-09-23 AWS 모델 카드 기준)"이다. 동기화가 이전 단가(`prior_price`)를 관측하면 메모는
  응답에서 빠진다.
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
- ADR-025, ADR-027, ADR-028의 "비용은 조회 시점 계산이라 소급 재계산된다" 문장은 당시 기록으로 남기고, 세 ADR에 이 ADR을 가리키는
  후속 절을 붙였다.
  1. ADR-025 "후속 (v2.30.0, 2026-09-26) — 소급 정책 대체": `PRICE_TABLE`, `-global` / `-us` 키 삭제, Bedrock Claude US 10채널 교정.
  2. ADR-027 "후속 (v2.30.0, 2026-09-26) — 소급 정책 대체": GPT-6 Astra 3채널 단가의 `price_history` 이전, "3키를 항상 함께 둔다"
     규칙 폐지.
  3. ADR-028 "후속 (v2.30.0, 2026-09-26)": GPT-6 Sol, Luna 모델 카드 재대조 완료, Opus 5.5 US 교정, GPT-5.6 Sol 프로모션 수동 메모.

## v2.31.0 부록 (2026-09-27) — 프롬프트 캐싱 단가, GPT 긴 컨텍스트 단가, OpenAI 공식 가격

사용자 요청(2026-09-27): `/pricing` 열 이름을 "AWS Bedrock - Global CRIS", "AWS Bedrock - US CRIS", "AWS Bedrock - In Region"으로
바꾸고, 표 순서를 Anthropic Claude → OpenAI → Amazon Nova로 하고, OpenAI 표의 Claude Platform on AWS 열을 OpenAI 공식 가격으로
바꾸고, 프롬프트 캐싱 단가(모든 채널)와 GPT 긴 컨텍스트 단가를 함께 보여 준다. 설계 문서는
`docs/superpowers/specs/2026-09-27-pricing-v2-31-design.md`다(구현이 설계 문서와 다른 점은 그 문서 끝 "구현 계획과의 차이"에 있다). 이 부록은
Decision 1, 2, 3, 4, 6의 해당 규칙을 보충하거나 대체한다. Decision 1은 §6(열 추가), Decision 2는 §1과 §5(`OPENAI_LIST_SEED`, 기존
seed 행의 빈 확장 열 채우기), Decision 3은 §1, §2, §5(네 번째 출처, 확장 필드, `enriched`와 필드별 50% 안전장치), Decision 4는 §5(관리자
검토 대기 목록의 확장 필드와 필드별 변화율), Decision 6은 §7, §8(표시, 다운로드, 프로모션 메모)이다. 시점 단가 비용, 50% 안전장치와 관리자
승인, model_id 단위 seed 멱등 삽입(그 model_id 행이 없을 때만 새 행)은 그대로다.

### 1. 네 번째 출처 — OpenAI 공식 요금 문서와 표시 전용 `openai_list` 채널

- 출처는 `GET https://developers.openai.com/api/docs/pricing.md`(`pricing_sources.OPENAI_PRICING_URL`, 비인증 text/markdown,
  robots `Allow: /`)다. Anthropic 문서와 같은 httpx 클라이언트, `User-Agent`, 재시도를 쓴다. 가져오는 순서는 Anthropic 문서 →
  OpenAI 문서 → Price List → offers다(느린 offers가 싼 출처를 `skipped:deadline`으로 밀어내지 않게).
- `parse_openai_pricing_md`는 `### Standard pricing data` 제목 아래 첫 표만 읽는다. 그 아래 Batch, Flex, Fast 표는 읽지 않는다. 열은
  헤더 이름으로 찾고("Model", "Short context input", "Short context output"은 필수), 값 셀은 `$<n>` 완전 일치만 받고 `-`는 값 없음이다.
  모델 이름은 `<sup>`와 끝 괄호 그룹을 지운 뒤 정확 일치로만 찾는다(`gpt-5.5 (<272K context length)` → `gpt-5.5`, `gpt-5.4` ≠
  `gpt-5.4-mini`).
- 두 문서 표 모두, 같은 모델 이름이 두 번 나오면 입력이나 출력이 다를 때만 그 이름을 버린다(그 모델을 찾는 채널은 `skipped:not_found`).
  입력과 출력이 같으면 행을 남기고, 두 행에서 값이 다른 확장 필드(한쪽만 값이 있는 경우 포함)만 `None`으로 둔다
  (`pricing_parsers._unambiguous`). 캐시 값 하나가 엇갈려도 입력과 출력은 계속 확인된다.
- 문서 표의 값은 활성 채널이 찾는 모델 행만 하나씩 정규화한다(Anthropic 문서도 같다). Standard 표에는 모델이 약 40개 있으므로, 추적하지
  않는 행의 `$0.00` 입력이나 0으로 반올림되는 캐시 값이 추적 채널을 `skipped:parse_failed`로 만들지 않는다. 추적하는 모델의 값이
  정규화에 실패하면 그 모델의 채널만 `skipped:parse_failed`가 되고, 오류는 `<출처> <문서 모델 이름>: <메시지>`로 남는다
  (`pricing_sync._fetch_all`의 `settle_doc`). 제목이나 표가 없는 파싱 실패는 전과 같이 그 출처의 채널 전부를 건너뛴다.
- 문서 값은 표시 전용 채널 `openai_list`로 저장한다. 합성 model_id는 `openai-list:<family_key>`(예 `openai-list:gpt-6-astra`),
  `source_kind`는 `openai_doc`, `source_id`는 `openai-pricing`이다. `active_channels`가 활성 OpenAI 패밀리 8개(GPT 6 Astra, Sol, Luna,
  GPT 5.6 Sol, Terra, Luna, GPT 5.5, GPT 5.4)마다 이 id를 덧붙이므로 동기화 대상은 63채널(55 + 8)이다.
- 합성 id는 `AVAILABLE_MODELS`와 `probe_results`에 없어서 비용 조인에 걸리지 않고, `/api/pricing` `models`(비용 맵)에서도 빠진다.
  seed(`pricing_seed.OPENAI_LIST_SEED`, 2026-09-27 문서 값), 동기화, 50% 안전장치, verification, 이력은 다른 채널과 같다.
- 휴면 1P 채널(`openai:1p:*`)과는 별개다. 1P 채널은 여전히 분류하지 않고(비용 "-"), `openai_list`는 프로브 채널이 아니라 참고 가격
  열이다.
- 참고 자료 `openai-pricing`(kind `openai_doc`)의 제목은 "OpenAI API pricing (Standard)" / "OpenAI API 요금 (Standard)", URL은
  `https://developers.openai.com/api/docs/pricing`이다. 화면 상단 안내 상자에 "OpenAI 요금" / "OpenAI pricing" 링크가 붙는다.
- 문서는 "Bedrock pricing in commercial regions matches OpenAI direct pricing for equivalent services"라고 적는다. 2026-09-27
  fixture에서 Global CRIS 단가는 문서 값과 같고 US CRIS와 In Region 단가는 10% 높다(GPT 6 Astra 문서 10 / 50, Global 10 / 50, US와
  us-west-2 11 / 55).

### 2. 확장 단가 필드 7개 — 표시 전용

| 필드 | `price_history` 열 | 뜻 |
|------|--------------------|----|
| `cache_read` | `cache_read_per_mtok` | 캐시 읽기(cache hit, cached input) |
| `cache_write` | `cache_write_per_mtok` | 캐시 쓰기. Claude는 5분 캐시, OpenAI는 문서의 "cache writes", Nova는 cache write |
| `cache_write_1h` | `cache_write_1h_per_mtok` | Claude 1시간 캐시 쓰기 |
| `long_input`, `long_output` | `long_input_per_mtok`, `long_output_per_mtok` | GPT 긴 컨텍스트 입력, 출력(OpenAI 짧은 컨텍스트 한도를 넘는 요청, GPT 5.4와 5.5는 272K) |
| `long_cache_read`, `long_cache_write` | `long_cache_read_per_mtok`, `long_cache_write_per_mtok` | GPT 긴 컨텍스트 캐시 읽기, 쓰기 |

- 모두 nullable Float다. 출처에 없는 값은 `NULL`이고 화면에서 생략, CSV에서 빈칸이다. 입력과 출력은 계속 0보다 커야 하고, 확장
  필드는 정확히 0을 받으며 음수는 받지 않는다.
- **비용 계산은 바뀌지 않는다.** `with_row_cost`는 입력과 출력만 쓴다. 프로브는 프롬프트 캐싱을 쓰지 않고 입력이 짧으며,
  `probe_results`에는 캐시 토큰 열이 없다. 확장 필드는 `/pricing` 표와 다운로드에만 나온다.
- 출처별 읽기 규칙은 다음과 같다.
  1. agreement offer: 허용 목록 정규식 `pricing_parsers.DIMENSION_RE`에 `cache_read_tokens`, `cached_input_tokens`,
     `cache_write_tokens`, `cache_write_tokens_1h`, `cache_write_tokens_30m`(`_long_ctx` 변형 포함)과 레거시 `CacheReadInputTokenCount`,
     `CacheWriteInputTokenCount`, `CacheWrite1hInputTokenCount`를 더했다. 확장 필드는 입력과 출력을 준 **같은 후보 키**(스킴, 리전
     접두, global 여부)에서만 가져온다. batch, flex, priority, fast, Reserved, 그 밖의 리전 접두는 여전히 후보가 아니다. Claude의
     `_LCtx` 차원은 기본값과 같으므로(Sonnet 4.6 `APN2_InputTokenCount_LCtx_Global` 3 = 기본 3) 읽지 않고, Claude의 `long`은 항상
     `null`이다. 허용 목록은 `_long_ctx` 이름을 모든 offer에서 받으므로, 동기화가 OpenAI가 아닌 채널의 긴 컨텍스트 필드를 비교 전에
     버린다(`pricing_sync._gpt_long_only`). Claude offer에 `_long_ctx` 차원이 새로 생겨도 Claude 셀에 긴 컨텍스트 줄이 나타나지 않는다.
  2. AWS Price List(Nova): usagetype `USE1-Nova2.0Lite-cache-read-input-token-count`,
     `USE1-Nova2.0Lite-cache-write-input-token-count`(`pricing_sources.NOVA_CACHE_USAGETYPES`). 캐시 값은 fail-soft다. 상품이 없거나
     여러 개이거나, 단위가 다르거나, 가격이 없거나 음수이면 그 필드만 `None`이고 입력과 출력은 기존의 엄격한 규칙 그대로다.
  3. Anthropic 문서: 선택 헤더 "Cache hits and refreshes" → `cache_read`, "5m cache writes" → `cache_write`, "1h cache writes" →
     `cache_write_1h`.
  4. OpenAI 문서: "Short context cached input", "Short context cache writes", "Long context input", "Long context output",
     "Long context cached input", "Long context cache writes".

### 3. `cache_read_tokens`가 `cached_input_tokens`보다 우선한다 — 2026-09-27 offer 근거

GPT 5.6 offer에는 캐시 읽기 차원이 두 이름으로 있고 값이 다르다. `cache_read_tokens`가 현재 단가이고, `cached_input_tokens`는
2026-07-30 인하(Luna −80%, Terra −20%) 이전 입력 단가의 10%다.

| 모델, 채널 | `cache_read_tokens` | `cached_input_tokens` | OpenAI 문서 cached input | 해석 |
|------------|---------------------|-----------------------|--------------------------|------|
| GPT 5.6 Luna Global | 0.02 | 0.1 | $0.02 | 0.1 = 인하 전 Global 입력 1.0(현재 0.2) × 10% |
| GPT 5.6 Luna US, In Region | 0.022 | 0.11 | 해당 없음 | 0.11 = 인하 전 입력 1.1(현재 0.22) × 10% |
| GPT 5.6 Terra Global | 0.2 | 0.25 | $0.20 | 0.25 = 인하 전 Global 입력 2.5(현재 2) × 10% |

- 그래서 한 후보 키 안에서는 `cache_read_tokens`(우선순위 1)를 쓰고, 없을 때만 `cached_input_tokens`(우선순위 2)를 쓴다. GPT 5.4,
  5.5의 `APN2_` 키에는 `cached_input_tokens`만 있고, `USE1_`, `USE2_`, `USW2_` 키에는 두 이름이 같은 값으로 있다(GPT 5.4 0.275,
  GPT 5.5 0.55).
- 같은 이유로 `cache_writes_tokens*`는 읽지 않는다. 이 값도 인하 전 입력 기준이다(Luna Global 1.25 = 1.0 × 1.25, Terra Global 3.125 =
  2.5 × 1.25). OpenAI 캐시 쓰기는 `cache_write_tokens_30m`이고 문서 값과 같다(Luna Global 0.25, Terra Global 2.5).
- 이 규칙은 fixture(`backend/tests/fixtures/pricing/offers_gpt-5.6-terra.json`, `offers_gpt-5.6-luna.json`, 2026-09-27 재생성)로
  고정한다.

### 4. Nova 캐시 쓰기 $0

Price List의 `USE1-Nova2.0Lite-cache-write-input-token-count`는 `pricePerUnit.USD` `0.0000000000`(1K tokens)이고
`USE1-Nova2.0Lite-cache-read-input-token-count`는 `0.0000825000`이다. 그래서 Nova 2.0 Lite는 1M 토큰당 캐시 읽기 $0.0825, 캐시 쓰기
$0이다. 정확한 0은 공식 값이므로 확장 필드에서만 받는다. 관측 값 정규화(`_quantized`)는 확장 필드의 음수와 0으로 반올림되는 양수를
파싱 실패로 보고, 정확한 0은 그대로 둔다.

### 5. 빈 필드 채우기(`enriched`)와 필드별 50% 안전장치

- `classify_change`는 `PRICE_FIELDS` 9개(입력, 출력, 확장 7개)를 필드마다 비교한다. 저장 값이 `NULL`이고 관측 값이 있으면 채움,
  둘 다 있고 다르면 변경, 변경 중 `old <= 0`이거나 변화율이 0.5를 넘으면 대기다. 저장 값이 있는데 관측 값이 없으면(출처에서
  빠짐) 무시하고 저장 값을 유지한다.
- 결과는 대기가 하나라도 있으면 `pending`, 아니면 변경이 있으면 `changed`, 아니면 채움이 있으면 **`enriched`**, 아니면 `unchanged`다.
- `enriched`는 **새 이력 행을 만들지 않고 현재 유효 행의 빈 열을 그 자리에서 채운다.** `observed_at`, `run_id`, `source_id` 갱신은
  `unchanged`와 같다. 값이 바뀐 것이 아니라 처음 알려진 것이고, 확장 필드는 비용에 쓰이지 않으므로 `effective_from`을 옮길 이유가
  없다. 그래서 처음 관측한 값이 그 행의 유효 구간 전체에 표시된다.
- `changed`와 `pending`이 만드는 새 행은 관측 값과 현재 행 값을 합친 값을 담는다(관측 값이 없는 필드는 현재 값). 확장 필드 하나만
  0.5를 넘게 바뀌어도 그 채널은 `pending_review`로 간다. 이때 입력과 출력은 승인 전까지 현재 행 그대로라 비용은 바뀌지 않는다.
- `price_sync_runs.changes`는 `changed`만, `pending`은 `pending`과 `no_baseline`만 센다. `enriched`는 런 요약 `summary.channels`에만
  나온다.
- 보류 행(`pending_review`, `rejected`) 비교: 확장 열 7개가 모두 `NULL`인 보류 행은 v2.30.0에서 확장 열이 생기기 전에 보류된 행이므로
  입력과 출력만 비교한다. 그래서 v2.30.0의 검토 대기 행이 같은 값으로 하나 더 생기지 않고, 관리자가 거부한 값이 확장 필드가 채워진 새
  검토 대기 행으로 다시 올라오지 않는다. 그 행의 빈 확장 열은 그대로 두고, 승인되면 다음 동기화가 `enriched`로 채운다.
- `ensure_seed`도 같은 원칙이다. 새 seed 행에 확장 필드를 넣고, 입력과 출력이 seed 값과 같은 기존 `status='seed'` 행의 `NULL` 확장
  열을 seed 값으로 채운다(멱등, 동기화가 실패해도 표가 비지 않는다). 열마다 `COALESCE(열, seed 값)`으로 쓰므로, seed가 행을 읽은
  뒤 동시 동기화가 커밋한 값은 덮어쓰지 않는다. Decision 2의 새 행 삽입 규칙(그 model_id 행이 하나도 없을 때만)은
  그대로이고, 이 채우기와 OpenAI 공식 가격 seed(`OPENAI_LIST_SEED`, §1)가 더해진다.
- Decision 4의 관리자 검토 대기 목록(`GET /api/admin/pricing/pending`)은 `current`와 `new`에 확장 필드 7개(선택, 없으면 `null`)를 싣고,
  `change`는 양쪽에 값이 있는 필드마다 변화율을 준다(현재 값이 있으면 입력과 출력 변화율은 항상 있다). 화면 배지와 Markdown 다운로드의
  검토 대기 표기는 바뀐 항목만 보여 준다(입력이나 출력이 바뀌면 쌍, 이어서 바뀐 캐시 항목과 긴 컨텍스트 줄). 바뀐 캐시 항목에 캐시
  읽기가 없으면 첫 항목에 "캐시"를 붙인다. 캐시 1시간 쓰기만 바뀌면 "새 값 캐시 1시간 쓰기 $17.60"(EN "New value cache 1h write
  $17.60"), 쓰기와 1시간 쓰기가 바뀌면 "새 값 캐시 쓰기 $11.00, 1시간 쓰기 $17.60"이다. 배지 설명만 읽어도 캐시 단가라는 것이 드러나고,
  출력 단가로 읽히지 않는다. 셀의 캐시 줄은 "캐시 읽기 $0.55, 쓰기 $6.875"처럼 그대로다.

### 6. 저장과 마이그레이션

- 운영에는 `price_history`가 이미 있으므로 `create_all`만으로는 새 열이 생기지 않는다. `pricing_seed.ensure_price_columns(engine)`이
  `sqlalchemy.inspect`로 빠진 열을 먼저 확인하고, 빠진 열이 없으면 DDL을 하나도 실행하지 않는다(기동마다 ACCESS EXCLUSIVE 잠금을
  요청하지 않는다). 빠진 열이 있으면 한 트랜잭션에서 `SET LOCAL statement_timeout = '30000'`, `SET LOCAL lock_timeout = '5000'` 뒤
  `ALTER TABLE price_history ADD COLUMN IF NOT EXISTS <col> DOUBLE PRECISION`을 실행한다.
- 호출 위치는 두 곳이다.
  1. backend lifespan(`_ensure_price_schema`): price seed 바로 앞의 자체 `try` 블록. 실패하면 `Price column migration failed (non-fatal,
     backend continues)`를 남기고 기동을 계속한다. 열 추가나 seed가 실패하면 데몬 스레드 `price-schema-retry`가 30초 간격으로 최대 3번
     `ensure_price_columns` → `ensure_seed`(같은 활성 채널 집합)를 다시 하고 처음 성공하면 멈춘다(롤링 배포 중 다른 태스크의
     `price_history` 조회가 ALTER 잠금을 막는 경우 대비, 기동은 기다리지 않는다).
  2. `pricing_sync_runner`: `create_tables()` 바로 뒤. 실패하면 동기화하지 않고 exit 1이다.
- Decision 1의 "lifespan ALTER 블록에는 넣지 않는다"는 그대로다. 이 ALTER는 lifespan 마이그레이션 블록(`pg_advisory_lock(917350001)`)
  밖의 자체 트랜잭션이다.
- 새 열이 없는 DB에서 v2.31.0 코드는 `/api/pricing`, 관리자 검토 대기 목록, seed, 동기화가 `UndefinedColumn`으로 실패한다. 비용
  조인(`effective_prices_subquery`)은 입력과 출력 열만 고르므로 영향이 없다. v2.30.0 코드는 새 열을 모르지만 모두 nullable이라,
  롤아웃이나 롤백 중에 두 버전이 함께 돌아도 문제가 없다.

### 7. 표시와 다운로드

- `PROVIDER_ORDER`는 `("anthropic", "openai", "amazon")`이다. Decision 6의 Anthropic Claude → Amazon Nova → OpenAI 순서를 대체한다.
- `/api/pricing` `tiers`는 항상 다섯 키 `cp`, `openai_list`, `global`, `us`, `in_region` 순서다. 셀마다 `cache_read`, `cache_write`,
  `cache_write_1h`, `long`(`{input, output, cache_read, cache_write}` 또는 `null`)이 붙고, `pending`에도 같은 네 키가 붙는다. 같은
  값끼리 한 원소로 묶는 규칙은 9개 값 전체, verification, pending 값 전체를 비교한다.
- 화면 열 머리글은 Anthropic Claude 표가 Claude Platform on AWS, AWS Bedrock - Global CRIS, AWS Bedrock - US CRIS, AWS Bedrock - In
  Region이고, OpenAI 표는 첫 열이 OpenAI 공식 가격(EN "OpenAI official price")이다. Amazon Nova 표는 첫 열의 머리글과 칸을 모두 비워
  세 표의 열 위치를 맞춘다. 셀 둘째 줄은 캐시 단가, GPT 셋째 줄은 긴 컨텍스트 단가다.
- 두 조각 머리글("AWS Bedrock -" / "Global CRIS")은 두 조각 사이에서만 줄이 바뀐다. " - "가 없는 머리글(Claude Platform on AWS,
  OpenAI 공식 가격)은 v2.30.0처럼 단어 사이에서 줄이 바뀐다. 이 이름을 한 덩어리로 묶으면 표가 최소 폭 800px로 그려지는 화면에서
  글꼴 크기만 키울 때(루트 110%) 옆 열 머리글로 넘친다. e2e가 390px, 루트 글꼴 110%에서 `main thead th` 넘침이 없음을 확인한다.
- CSV에 `cache_read_usd_per_1m`부터 `long_cache_write_usd_per_1m`까지 7열이 붙고 `channel`에 `openai_list`가 생긴다. Markdown은 제공사
  표마다 자기 열 머리글을 쓰고, 셀 안에서 `<br>`로 둘째 줄과 셋째 줄을 잇는다. Markdown 머리 줄은 화면과 같은 이름 "마지막 공식 단가
  동기화" / "Last official price sync"와 화면과 같은 상태 번역(완료, 일부 출처 실패, 실패, 진행 중, 모르는 상태는 그대로)을 쓴다.
- 범위는 USD, Standard 등급이다. batch, flex, priority(fast) 단가는 여전히 넣지 않는다. Decision 6 범위 문장 "Standard 입력과
  출력만(캐시, batch, long-context, priority, flex 제외)"에서 캐시와 long-context 제외는 이 절이 대체한다.

### 8. GPT-5.6 Sol 프로모션 — 수동 메모에서 OpenAI 문서 인용으로

- OpenAI 문서가 "GPT-5.6 Sol’s promotional pricing is available at least through November 21, 2026."라고 적는다. 그래서 `PRICE_NOTES`의
  Sol 메모는 수동 메모가 아니라 이 문서를 출처로 인용한다(`source` `openai_doc`, `source_id` `openai-pricing`, `basis_*` 없음). 문구는
  KO "프로모션 단가다. 2026-09-27 기준 OpenAI 공식 요금 문서에 최소 2026-11-21까지 적용한다고 기재돼 있다.", EN "Promotional price. As
  of 2026-09-27, the OpenAI pricing page states that it applies at least through 2026-11-21."이다.
- 동기화(`parse_openai_pricing_md`)는 Standard 표만 읽고 이 문장은 다시 읽지 않는다. 각주 참고 자료의 확인일은 단가 행의 최신 관측일이라
  문장까지 확인한 것처럼 보일 수 있으므로, 문구에 문장을 확인한 날짜(2026-09-27)를 넣는다. OpenAI가 표 단가는 그대로 두고 문장만 바꾸면
  메모는 바뀌지 않는다. `min_until`(2026-11-21)이 지나면 화면 배지가 "프로모션 종료 여부 확인 필요"로 바뀐다.
- `prior_price`에 `openai_list` 5 / 30이 더해진다(Global 5 / 30, In Region 5.5 / 33은 그대로). 동기화가 어느 티어에서든 이전 단가를
  관측하면 메모는 응답에서 빠진다.
- 메모의 각주는 그 패밀리 셀 바로 뒤에 같은 번호 매기기(`cite`)로 OpenAI 참고 자료 번호를 받으므로 `manual_note` 참고 자료는 생기지
  않는다. `manual_note` 형식(`basis_ko`, `basis_en`, `note_source_id`)은 다음 수동 메모를 위해 남긴다.
- Decision 6의 "현재 공식 출처 어디에도 없다"와 Sol 프로모션을 수동 메모(`manual_note`)로 둔다는 문장은 2026-09-26 기준 기록으로
  남기고 이 절이 대체한다.

### Consequences (v2.31.0)

- (+) 캐시 단가(모든 채널)와 GPT 긴 컨텍스트 단가가 공식 출처에서 12시간마다 갱신된다. OpenAI 공식 가격과 AWS Bedrock 채널 단가를 한
  표에서 비교한다.
- (+) GPT-5.6 Sol 프로모션 기한의 근거가 수동 메모에서 공식 출처 인용으로 바뀌었다.
- (−) 확장 필드는 표시 전용이다. 캐시를 쓰는 실제 호출의 비용은 이 모니터가 계산하지 않는다.
- (−) OpenAI 문서는 사람이 읽는 페이지라 구조가 바뀔 수 있다. 파싱이 실패하면 `openai_list` 8채널만 `skipped:parse_failed`("자동
  확인 안 됨")가 되고 다른 출처와 비용은 영향을 받지 않는다.
- (−) `enriched`는 이력을 남기지 않는다. 확장 필드가 처음 관측되기 전의 값은 재구성하지 않는다.
- (−) 모델을 추가할 때 `pricing_seed.py`의 확장 필드 seed도 고쳐야 하고, 새 OpenAI 패밀리면 `OPENAI_LIST_SEED`도 고친다.

## v2.31.1 후속 (2026-09-27)

사용자 요청(2026-09-27): 참고 자료는 "인용되지 않으면 삭제", 그리고 "GPT AWS Bedrock - US CRIS 와 AWS Bedrock In Region이 가격이 같아
보입니다. 다시 확인합니다." 이 절은 Decision 6과 v2.31.0 부록 §7(표시와 다운로드)의 참고 자료, Markdown 규칙을 보충한다. 단가 값,
동기화, 비용 계산은 바뀌지 않는다.

### 1. 인용되지 않는 참고 자료 삭제

- v2.31.0까지 `references`는 셀 각주와 패밀리 메모가 인용한 출처 뒤에 고정 안내 항목 9개(`pricing_sources.OFFICIAL_PAGES`, kind
  `official_page`, Amazon Bedrock 요금 페이지와 OpenAI 모델 카드 8개)를 덧붙였다. 어느 셀도 이 번호를 인용하지 않았다. 운영 참고 자료
  30개 중 9개가 본문에서 가리키는 곳이 없는 번호였다.
- `OFFICIAL_PAGES`, `official_source_id`, `build_pricing_payload`의 덧붙이기 반복문을 지운다. `references`에는 셀 각주나 패밀리 메모가
  인용한 출처만 들어간다. 운영은 21개다(오퍼 18, Price List 1, Anthropic 문서 1, OpenAI 문서 1).
- 수동 메모(`manual_note`)는 메모 항목이 자기 참고 자료를 인용하므로 남는다. 번호는 인용된 출처 바로 뒤에 붙는다(전에는 고정 안내 항목
  뒤).
- 모르는 형식의 `source_id`를 위한 `_source_reference` 대체 항목(제목은 id, `url` 없음)은 셀이 인용하므로 남기고 kind `official_page`도
  그대로 둔다. `official_page`는 이제 이 경우에만 나온다.
- 불변식: 참고 자료 번호 집합은 셀 `footnotes` 번호와 메모 참고 자료 번호의 합집합과 같고, 번호는 1부터 N까지 빈칸이 없다. pytest가
  실제 seed(`tests/pricing_catalog.py` 활성 55채널과 OpenAI 공식 가격 8채널)로 만든 운영 형태 응답에서 이 불변식과 21개를 고정한다.

### 2. 공식 요금 페이지는 Markdown 머리말 링크로

- Markdown 참고 사항의 "최종 가격은 공식 요금 페이지에서 확인한다[^n]…" 항목(고정 안내 항목의 각주를 모아 인용하던 항목)과 `_TEXT`의
  `official` 키를 지운다.
- 대신 머리말의 동기화 줄(검토 대기가 있으면 그 줄) 뒤에 각주 없는 링크 한 줄을 넣는다. KO "- 공식 요금 페이지: [Amazon Bedrock
  요금](https://aws.amazon.com/bedrock/pricing/), [Anthropic 요금](https://platform.claude.com/docs/en/about-claude/pricing), [OpenAI
  요금](https://developers.openai.com/api/docs/pricing)", EN "- Official pricing pages: [Amazon Bedrock pricing](…), [Anthropic
  pricing](…), [OpenAI pricing](…)".
- 세 링크는 `pricing_sources.OFFICIAL_LINKS`(`title_en`, `title_ko`, `url`)에 둔다. 화면 상단 안내 상자
  (`frontend/src/components/PricingPanel.tsx` `OFFICIAL_LINKS`)와 같은 세 개, 같은 순서이고, pytest가 TS 파일을 읽어 고정한다
  (`FAMILY_ORDER` 테스트와 같은 방식).
- CSV와 JSON은 응답을 그대로 따르므로 링크를 넣지 않는다.
- OpenAI 모델 카드 8개 링크는 어디에도 남지 않는다. GPT 단가의 근거는 셀이 인용하는 오퍼 요금표와 OpenAI 공식 요금 문서다.

### 3. GPT의 US CRIS와 In Region 단가는 같다 — 고정 안내 추가

- 다시 확인한 결과 GPT 표의 US CRIS와 In Region 값이 같은 것이 맞다. 근거는 다음과 같다.
  1. AWS 모델 카드 GPT-6 Sol: "Mantle in-Region and US geographic cross-Region inference include a 10% premium … Global
     cross-Region inference uses those rates with no premium".
  2. AWS 모델 카드 GPT-6 Astra 표: In-Region $11 / $55 = Geo CRIS $11 / $55, Global $10 / $50.
  3. offer rate card에는 In Region과 US CRIS 공용 차원 `input_tokens_standard` 하나만 있고(Global CRIS는 `input_tokens_global_standard`),
     GPT 오퍼에는 리전 접두 차원이 없어 동기화가 두 채널에 같은 값을 쓴다(`pricing_parsers.select_offer_price`).
  4. 2026-09-27 seed에서 US CRIS 채널이 있는 GPT 6 Astra, Sol, Luna는 US CRIS와 In Region의 9개 단가가 모두 같다. 8개 GPT 패밀리 모두
     In Region 입력과 출력이 OpenAI 공식 가격의 1.1배이고, Global CRIS가 있는 6개 패밀리는 Global CRIS가 OpenAI 공식 가격과 같다(pytest
     고정).
- export 고정 안내(`_TEXT[..]['fixed_notes']`)에 3번째 항목을 넣어 9개가 된다. 위치는 "AWS Bedrock - Global CRIS 단가는 같은 모델의 US CRIS,
  In Region 단가와 다를 수 있다." 바로 뒤다. KO "GPT의 AWS Bedrock - US CRIS와 In Region 단가는 같다. AWS가 두 채널 모두 OpenAI 공식 가격에
  10%를 더하고, Global CRIS는 OpenAI 공식 가격과 같다.", EN "GPT prices on AWS Bedrock - US CRIS and In Region are the same: AWS adds 10% to
  the OpenAI official price on both, and Global CRIS equals the OpenAI official price." export는 끝 마침표를 두고, 화면(프런트 번들)은 같은
  문장을 마침표 없이 참고 사항에 넣는다.

### Consequences (v2.31.1)

- (+) 참고 자료의 모든 번호를 본문 각주가 가리킨다. 운영 목록이 30개에서 21개로 준다.
- (+) GPT 표에서 US CRIS와 In Region 값이 같은 이유가 화면과 Markdown에 적힌다.
- (−) 앞으로 AWS가 GPT의 US CRIS와 In Region에 다른 단가를 매기면 고정 안내가 틀린다. seed를 고치면 seed 테스트가 드러내지만, 동기화가
  관측한 값만 달라지는 경우는 테스트가 잡지 못하므로 그때는 문구를 사람이 고친다.

## v2.32.0 후속 (2026-09-30)

- **Claude의 첫 in-region 채널**: 서울 in-region Opus 5, Sonnet 5(`bedrock:ap-northeast-2:anthropic.claude-*`, ADR-031)를 `price_identity`가
  `PriceIdentity(<family_key>, <family>, "anthropic", "inregion:ap-northeast-2", "offer", <FM id>)`로 분류한다(`BEDROCK_INREGION_PREFIX`,
  `_BEDROCK_INREGION_REGIONS = ("ap-northeast-2",)`, 목록 밖 리전과 Claude가 아닌 FM은 분류하지 않는다 — fail-closed). 파서는 리전 코드 APN2를
  알아 `inregion:ap-northeast-2`에 `APN2_*_standard`(입력, 출력, 캐시)를 읽는다. 값은 US `USE1_*_standard`와 같다(Opus 5 5.5 / 27.5, Sonnet 5
  2.2 / 11). seed의 `_CLAUDE`는 FM마다 채널 튜플을 갖고(`_claude_channel_id` — `global`/`us`는 `<channel>.<fm>`, 그 밖은
  `bedrock:<channel>:<fm>`), 서울 채널은 Global, US 채널과 같은 offer 호출 하나를 쓴다. `/api/pricing`의 Claude `in_region` 셀이 처음 생겼다.
- **수치**: offer FM 18 → 20(`anthropic.claude-sonnet-5-5` `offer-5fu2rhus3byrs`, `openai.gpt-6.1-sol` `offer-wbhj4kycntgkk`), references 21 → 23,
  활성 채널 63 → 71(62 + OpenAI 공식 가격 9), `FAMILY_ORDER` 19 → 21(`Claude Sonnet 5.5`는 `Claude Sonnet 5` 앞, `GPT 6.1 Sol`은 `GPT 6 Astra`
  앞), `ANTHROPIC_DOC_NAMES` 9 → 10, `SEED` 46 → 52, `CP_SEED` 9 → 10, `OPENAI_LIST_SEED` 8 → 9. 오프라인 첫 동기화 리허설(fixture 기준):
  빈 DB에서 `ensure_seed` 71 → `run_sync` 71 unchanged, v2.31.2 상태(63채널)에서 올리면 `ensure_seed`가 8행을 넣고 71 unchanged, pending 0.
- **`_plausible_long` 규칙**: 2026-09-30 GPT-6.1 Sol offer의 긴 컨텍스트 출력(`output_tokens_long_ctx_standard` 2.2,
  `output_tokens_long_ctx_global_standard` 2)이 짧은 컨텍스트 출력(11 / 10)보다 낮다. 같은 offer의 flex 긴 컨텍스트 출력은 16.5 / 15이고
  OpenAI 요금 문서는 15다. 긴 컨텍스트 입력이나 출력이 짧은 컨텍스트 단가보다 낮으면(`_implausible_long`) 동기화가 그 관측의 long_* 4필드를
  None으로 만들고 WARNING 한 줄(`pricing sync: <where>: long-context price below the short-context price, long prices dropped`)을 남긴다. offer와
  문서 경로 모두 적용하고 run errors에는 넣지 않는다(채널은 unchanged). 비교가 None 필드를 무시하므로 저장된 long 값은 그대로, 없던 값은 계속
  없다. 같은 값은 정상이다. seed도 GPT-6.1 Sol Bedrock 3채널의 long을 None으로 두고, `openai-list:gpt-6.1-sol`은 문서 값 4 / 15를 쓴다.
  - 한계: 신호는 로그뿐이다. AWS가 요금표를 고치면 다음 동기화에서 long_*가 50% 게이트 없이 `enriched`로 채워진다(처음 알려진 값이라
    게이트 대상이 아니다). 기존 패밀리의 long 값이 나중에 이상값이 되면 옛 값이 그대로 남는다.
  - 화면 고정 안내는 추가하지 않았다(골든 Markdown, CSV, 안내 번호, e2e 9개 고정이 모두 바뀐다).
