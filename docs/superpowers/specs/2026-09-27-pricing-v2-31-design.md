# Design: 비용 단가 메뉴 v2.31.0 — 열 이름 정리, OpenAI 공식 가격, 프롬프트 캐싱 단가, GPT 긴 컨텍스트 요금

- **Date**: 2026-09-27
- **Branch**: `feat/v2-31-pricing-columns-cache` (main `15600eb`, v2.30.0 배포본 기준)
- **Version**: v2.31.0
- **Status**: Approved (design) — 2026-09-27 사용자 요청과 결정 반영
- **Base design**: `docs/superpowers/specs/2026-09-26-pricing-menu-design.md` (v2.30.0). 이 문서는 그 위의 변경만 적는다. 규칙이 겹치면 이 문서가 우선한다.
- **Related**: ADR-030 (자동 동기화, 시점 단가). ADR-030에 v2.31.0 부록을 붙인다.

## 사용자 요청 (2026-09-27)

1. Anthropic Claude 표: "Global" → **AWS Bedrock - Global CRIS**, "US" → **AWS Bedrock - US CRIS**.
2. Anthropic Claude 다음 표는 **OpenAI**. 순서는 Anthropic Claude → OpenAI → Amazon Nova.
3. OpenAI 표: "Claude Platform on AWS" 열을 없애고 **OpenAI 공식 가격**으로 대체. Global, US 열 이름은 1과 같다.
4. 모든 표의 "In-Region" → **AWS Bedrock - In Region**.
5. **프롬프트 캐싱 단가**도 포함한다. 결정: 셀 안 둘째 줄에 항상 표시.
6. **GPT는 짧은 컨텍스트와 긴 컨텍스트 요금이 다르다** — 둘 다 표시한다.
7. Amazon Nova 표의 첫 열: **빈칸**(머리글과 칸 모두 비움, 세 표의 열 위치는 그대로 맞춤).
8. 진행 범위: CI 통과 시 머지와 배포.

## 공식 출처 (v2.30.0의 3곳 + OpenAI 공식 문서)

| 출처 | 새로 읽는 값 |
|---|---|
| Bedrock agreement offer rate card | 캐시 읽기, 캐시 쓰기, 1시간 캐시 쓰기(Claude), GPT 긴 컨텍스트 입력, 출력, 캐시 읽기, 캐시 쓰기 |
| AWS Price List (Nova) | 캐시 읽기, 캐시 쓰기 usagetype |
| Anthropic `pricing.md` (CP) | "5m cache writes", "1h cache writes", "Cache hits and refreshes" 열 |
| **OpenAI `https://developers.openai.com/api/docs/pricing.md`** (신규, 비인증 text/markdown, robots `Allow: /`) | "### Standard pricing data" 첫 표: Short context input, cached input, cache writes, output, Long context input, cached input, cache writes, output |

OpenAI 문서는 "Bedrock pricing in commercial regions matches OpenAI direct pricing for equivalent services"와
"GPT-5.6 Sol’s promotional pricing is available at least through November 21, 2026"를 명시한다. 그래서 GPT-5.6 Sol 프로모션
메모는 수동 메모가 아니라 **OpenAI 공식 문서를 출처로 인용**한다(`PRICE_NOTES` 근거 교체, 참고 자료 kind `openai_doc`).

### 정규화된 단가 필드

모든 셀(채널)은 다음 필드를 가진다. 출처에 없으면 `null`(화면 생략, CSV 빈칸).

| 필드 | 뜻 |
|---|---|
| `input`, `output` | 기존 (짧은 컨텍스트 표준 입력, 출력) |
| `cache_read` | 캐시 읽기(cache hit, cached input) |
| `cache_write` | 캐시 쓰기 — Claude는 5분 TTL, OpenAI는 문서의 "cache writes"(offer `cache_write_tokens_30m`), Nova는 cache write |
| `cache_write_1h` | 1시간 캐시 쓰기 (Claude만) |
| `long` | GPT 긴 컨텍스트 요금 객체 `{input, output, cache_read, cache_write}` 또는 `null` (OpenAI 패밀리만) |

### offer 차원 규칙 (기존 입력/출력 규칙에 추가)

리전 접두 허용 목록(APN2/USE1/USE2/USW2)과 채널별 선택 순서(global → APN2… , us → USE1…, inregion → 리전 접두 → 평면)는 입력/출력과 같다.
batch, flex, priority, fast, Reserved, GovCloud, 기타 접두, `price <= 0`은 모두 제외. 캐시와 긴 컨텍스트 차원은 **허용 목록 이름만** 받는다:

- 캐시 읽기: `cache_read_tokens[_long_ctx][_global]_standard` 우선, 없으면 `cached_input_tokens[_long_ctx][_global]_standard`(GPT 5.4/5.5), 레거시 `CacheReadInputTokenCount[_Global]`(Claude 4.6).
  GPT 5.6 Terra처럼 두 이름이 서로 다른 값으로 함께 있으면 **`cache_read_tokens`를 쓴다**(OpenAI 공식 문서 값과 일치: Terra Global 0.20).
- 캐시 쓰기: Claude `cache_write_tokens[_global]_standard`(5분), 레거시 `CacheWriteInputTokenCount[_Global]`. OpenAI `cache_write_tokens_30m[_long_ctx][_global]_standard`.
  `cache_writes_tokens*`(Terra에 있는 다른 값 3.125)는 쓰지 않는다(공식 문서 2.50과 불일치).
- 1시간 캐시 쓰기(Claude): `cache_write_tokens_1h[_global]_standard`, 레거시 `CacheWrite1hInputTokenCount[_Global]`.
- 긴 컨텍스트(OpenAI만): `input_tokens_long_ctx[_global]_standard`, `output_tokens_long_ctx[_global]_standard`, 위 캐시 규칙의 `_long_ctx` 변형.
  Claude의 `_LCtx` 차원은 기본값과 같으므로 무시한다(Claude는 `long = null`).

실측 예(us-east-1 offers, 2026-09-26): Opus 5.5 Global 캐시 읽기 0.2, 쓰기 5, 1시간 쓰기 8 / US 0.22, 5.5, 8.8. GPT 6 Sol Global 캐시 읽기 0.2, 쓰기 2.5, 긴 컨텍스트 4/15(캐시 0.4, 쓰기 5).
GPT 5.4 Global 캐시 읽기 0.25(`cached_input_tokens`), 쓰기 없음, 긴 컨텍스트 5/22.5.

### 문서 표 규칙

- Anthropic: 헤더 이름 "5m cache writes" → `cache_write`, "1h cache writes" → `cache_write_1h`, "Cache hits and refreshes" → `cache_read`. 값 셀 `<sup>` 제거 후 `$x / MTok`.
- OpenAI: "### Standard pricing data" 아래 첫 표만 읽는다. 헤더 이름으로 열을 찾는다(Short context input / cached input / cache writes / output, Long context input / cached input / cache writes / output). 모델 이름 셀은 괄호 부분(예 `(<272K context length)`)을 지우고 **정확 일치**(`gpt-5.4` ≠ `gpt-5.4-mini`, `gpt-5.4-pro`). `-`는 `null`, 값은 `$x.xx`. 헤더나 표가 없으면 파싱 실패(해당 출처 채널만 skipped).
- Nova Price List: `USE1-Nova2.0Lite-cache-read-input-token-count`, `USE1-Nova2.0Lite-cache-write-input-token-count`(구현 시 실제 usagetype 이름을 조회로 확인, `1K tokens` ×1000).

## OpenAI 공식 가격 열 (`openai_list` 티어)

- OpenAI 1P 채널은 휴면이므로 이 열은 **표시용 참고 가격**이다. 비용 계산에 쓰이지 않는다(해당 model_id의 프로브 행이 없다).
- 저장: `price_history`에 합성 model_id `openai-list:<family_key>`(예 `openai-list:gpt-6-astra`), `channel = "openai_list"`, `source_id = "openai-pricing"`.
  `price_identity`는 이 id를 `provider openai`, `source_kind "openai_doc"`, `source_ref`(문서 모델 이름, 예 `gpt-6-astra`)로 분류한다.
- 대상: 활성 채널에 있는 OpenAI 패밀리 8개(GPT 6 Astra, Sol, Luna, GPT 5.6 Sol, Terra, Luna, GPT 5.5, GPT 5.4). 활성 집합 구성 함수가 이 합성 id를 자동으로 덧붙인다.
- seed(`pricing_seed`)에 2026-09-27 문서 값을 넣고, 동기화, 50% 안전장치, verification, 이력은 다른 채널과 같다.
- 참고 자료: `openai-pricing` — "OpenAI API pricing (Standard)" / "OpenAI API 요금 (Standard)", URL `https://developers.openai.com/api/docs/pricing`.

## 저장과 마이그레이션

- `price_history`에 nullable Float 열 7개를 추가한다: `cache_read_per_mtok`, `cache_write_per_mtok`, `cache_write_1h_per_mtok`, `long_input_per_mtok`, `long_output_per_mtok`, `long_cache_read_per_mtok`, `long_cache_write_per_mtok`.
  운영에는 테이블이 이미 있으므로 **lifespan 마이그레이션 블록에 `ALTER TABLE price_history ADD COLUMN IF NOT EXISTS …`**를 추가하고 ORM에도 선언한다(새 DB는 `create_all`).
- **빈 필드 채우기(enrich)**: 동기화에서 유효 행의 확장 필드가 `NULL`이고 출처가 값을 주면, 새 이력 행을 만들지 않고 그 행을 그대로 채운다(결과 `enriched`, observed_at 갱신). 값이 이전에 알려지지 않았던 것이지 바뀐 것이 아니고, 확장 필드는 비용 계산에 쓰이지 않기 때문이다.
- **값 변경**: 입력/출력 또는 이미 값이 있는 확장 필드가 바뀌면 기존 규칙과 같다. 모든 필드의 변화율이 0.5 이하이면 모든 필드를 담은 새 verified 행, 하나라도 0.5를 넘으면 pending_review.
- `ensure_seed`: 새로 넣는 seed 행에 확장 필드를 포함한다. 이미 있는 `status='seed'` 행의 `NULL` 확장 필드는 seed 값으로 채운다(멱등, 동기화 실패 시 대비).

## API와 다운로드

- `/api/pricing` 셀(티어 객체와 `in_region` 원소)에 `cache_read`, `cache_write`, `cache_write_1h`, `long` 필드를 추가한다. `tiers`에 `openai_list` 키를 추가한다(OpenAI 패밀리만 객체, 나머지 `null`).
- `families` 순서: `PROVIDER_ORDER = ("anthropic", "openai", "amazon")`.
- 셀의 pending 비교와 in_region 묶음(같은 값끼리)은 확장 필드까지 포함한 전체 값으로 한다.
- CSV 열 추가: `cache_read_usd_per_1m,cache_write_usd_per_1m,cache_write_1h_usd_per_1m,long_input_usd_per_1m,long_output_usd_per_1m,long_cache_read_usd_per_1m,long_cache_write_usd_per_1m`; `channel` 값에 `openai_list`.
- Markdown: 셀 안 줄바꿈 `<br>`로 둘째 줄(캐시), 셋째 줄(긴 컨텍스트). 표 머리글은 화면과 같은 이름.

## 화면

- 표 순서: Anthropic Claude → OpenAI → Amazon Nova.
- 열 머리글(KO, EN 같음, 제품명):
  - Anthropic Claude: Claude Platform on AWS | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region
  - OpenAI: OpenAI 공식 가격 (EN "OpenAI official price") | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region
  - Amazon Nova: (빈 머리글, 빈 칸) | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region
- 셀:
  1. 첫 줄: `$4.00 / $20.00 [n]` (기존)
  2. 둘째 줄(작은 글씨, 값이 하나라도 있을 때): KO "캐시 읽기 $0.20, 쓰기 $5.00, 1시간 쓰기 $8.00" / EN "Cache read $0.20, write $5.00, 1h write $8.00" — 없는 항목은 뺀다.
  3. 셋째 줄(GPT, `long`이 있을 때): KO "긴 컨텍스트 $20.00 / $75.00, 캐시 읽기 $2.00, 쓰기 $25.00" / EN "Long context $20.00 / $75.00, cache read $2.00, write $25.00".
  4. 배지와 상세 줄은 그 아래(기존).
- 단위 범례: KO "각 단가 셀: 입력 / 출력, 1M 토큰당 USD. 둘째 줄은 프롬프트 캐싱, GPT 셋째 줄은 긴 컨텍스트 요금" / EN 대응.
- 참고 사항(번호 목록) 갱신:
  1. 단가는 USD, 1M 토큰당, Standard 등급 기준이다
  2. Global 채널 단가는 같은 모델의 US, In Region 채널과 다를 수 있다
  3. GPT의 긴 컨텍스트 요금은 OpenAI 기준 긴 입력(짧은 컨텍스트 한도 초과)에 적용된다
  4. 캐시와 긴 컨텍스트 단가는 표시만 하며, 비용 화면은 입력과 출력 단가로 계산한다(프로브는 캐시를 쓰지 않고 입력이 짧다)
  5. batch, flex, priority(fast) 단가는 포함하지 않는다
  6. 비용 화면은 각 프로브 시각의 단가로 계산한다
- OpenAI 공식 가격 열은 비용 계산에 쓰이지 않는다는 점을 머리글 툴팁이 아니라 참고 사항 문장으로 밝힌다(3번 또는 별도 항목).
- 모델 탐색(`/models`), Comparison Lab, 비용 화면은 바뀌지 않는다(입력/출력만).

## 테스트

- 파서: offer 캐시/긴 컨텍스트 차원(신규, 평면, 레거시 스킴), Terra의 `cache_read` 대 `cached_input` 충돌 규칙, `cache_writes_tokens` 무시, Claude `_LCtx` 무시, OpenAI 문서 표(헤더 이름, 모델 정확 일치, `-` → null, 괄호 제거, Batch 표 무시), Anthropic 캐시 열, Nova 캐시 usagetype.
- 동기화: enrich(NULL → 값, 새 행 없음), 확장 필드 변경 50% 규칙, openai_list 채널, OpenAI 문서 출처 실패 시 해당 채널만 skipped.
- 마이그레이션: ALTER ADD COLUMN IF NOT EXISTS 멱등, 기존 seed 행 확장 필드 채우기.
- payload/export golden: 새 필드, `openai_list`, 새 PROVIDER_ORDER, CSV 열, Markdown `<br>`.
- 프런트: 열 머리글(표별), 표 순서, 셀 둘째/셋째 줄, Nova 첫 열 빈칸, 열 위치 동일, 390 px 가로 넘침 없음, e2e fixture 갱신.

## 배포와 확인

- 백엔드 기동 시 ALTER로 열 추가 → 첫 수동 PricingSync에서 55채널 + OpenAI 공식 가격 8채널 `verified`, 확장 필드 `enriched`, pending 0 기대.
- Docker 빌드를 릴리스 전에 로컬로 확인한다(v2.30.0 `.dockerignore` 사고).
- README 스크린샷(`pricing-{en,ko}.png`) 갱신, ADR-030 부록, api-reference, CHANGELOG v2.31.0, 버전 6곳.

## 구현 계획과의 차이 (2026-09-27 계획 기준)

구현은 `docs/superpowers/plans/2026-09-27-pricing-v2-31.md`의 Interface Contract를 따른다. 계획은 2026-09-27 출처 데이터로 규칙을 다시
정했고, 이 문서와 다른 점은 아래와 같다. 위 본문은 결정 기록으로 그대로 둔다.

1. 마이그레이션 위치: 위 "저장과 마이그레이션"은 lifespan 마이그레이션 블록에 `ALTER TABLE`을 넣는다고 적었다. 구현은
   `pricing_seed.ensure_price_columns`가 lifespan의 price seed 바로 앞 자체 `try` 블록과 PricingSync 러너(`create_tables()` 바로 뒤)에서
   빠진 열만 추가한다. 빠진 열이 없으면 DDL을 실행하지 않는다. ADR-030 Decision 1의 "lifespan ALTER 블록에는 넣지 않는다"를 지킨다.
2. 단위 범례: 화면은 "각 단가 셀: 입력 / 출력, 1M 토큰당 USD. 둘째 줄: 프롬프트 캐싱. GPT 셋째 줄: 긴 컨텍스트"이고, 다운로드 머리말은
   "통화와 단위: USD, 1M 토큰당, 입력 / 출력. 둘째 줄은 프롬프트 캐싱, GPT 셋째 줄은 긴 컨텍스트 단가다"다.
3. 참고 사항: 6항목이 아니라 8항목이다. 캐시 쓰기와 1시간 쓰기의 뜻(Claude, OpenAI, Nova), OpenAI 공식 가격은 비용 계산에 쓰지
   않는다는 항목이 따로 있고, 4번의 괄호 "(프로브는 캐시를 쓰지 않고 입력이 짧다)"는 넣지 않았다. 열 이름을 따라 "Global 채널"은
   "AWS Bedrock - Global CRIS"로 쓴다.
4. seed 채우기: 기존 `status='seed'` 행의 빈 확장 열은 입력과 출력이 seed 값과 같은 행만 채운다(값이 바뀐 행에 옛 확장 값을 붙이지 않는다).
5. Markdown 다운로드: 표마다 독립이므로 Amazon Nova 표에는 빈 첫 열이 없다(화면만 세 표의 열 위치를 맞추려고 빈 열을 둔다).
6. 첫 수동 PricingSync 기댓값: 기동 시 seed가 기존 seed 행의 빈 확장 열을 먼저 채우므로 대부분 `unchanged`이고
   (`results={'unchanged': 63}`), v2.30.0 동기화가 만든 verified 행처럼 빈 확장 열이 남은 채널만 `enriched`다. changes와 pending은 0이다.
7. 계획이 더한 규칙: 긴 컨텍스트 필드는 동기화가 OpenAI 채널에만 남긴다. 문서 표는 활성 채널이 찾는 모델 행만 정규화한다. 확장 열이 모두
   비어 있는 v2.30.0 보류 행은 입력과 출력만 비교한다. 검토 대기 표기(화면 배지, Markdown)는 바뀐 항목만 보여 준다.
8. 계획 뒤 구현 검토에서 정한 규칙(계획 Interface Contract의 해당 문장도 대체한다): 문서 표(Anthropic, OpenAI)에서 같은 모델 이름이
   두 번 나오면 입력이나 출력이 다를 때만 그 이름을 버리고, 같으면 행을 남기되 두 행에서 값이 다른 확장 필드(한쪽만 값이 있는 경우
   포함)만 `None`으로 둔다(계획 C4, C5는 `UnitPrice` 전체를 비교했다). seed 채우기는 열마다 `COALESCE(열, seed 값)`으로 써서 seed가
   행을 읽은 뒤 동시 동기화가 커밋한 값을 덮어쓰지 않는다. 동기화의 문서 표 정규화는 찾는 모델 행마다 따로 하고(`settle_doc`),
   추적하는 모델의 값이 정규화에 실패하면 그 모델의 채널만 `skipped:parse_failed`다. 화면의 `formatUnitPrice`는 예외를 던지지
   않는다(NaN, ±Infinity, 절댓값 1e21 이상은 `$<값>` 그대로 표시). 프런트가 모르는 제공사는 기본 열(빈 첫 열과 AWS Bedrock 세 열,
   `pricingTable.columnsFor`)로 그리고 섹션 이름은 제공사 문자열이다.
