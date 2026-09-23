# ADR-028: Claude Opus 5.5 3채널 + OpenAI GPT-6 Sol/Luna 6채널 — CP 점 버전 가드, Sol/Luna Mantle은 us-east-1만

- **Status**: Accepted
- **Date**: 2026-09-23
- **Related**: ADR-019 (Mantle Path 4), ADR-025 (Global CRIS + 채널별 단가 분리), ADR-027 (GPT-6 Astra, 유사 리전 `us`), v2.22.0/v2.22.1 (Fable 5.1 substring 오등록), v2.27.0, v2.28.0 후속 (Sol/Luna 단가, 벤치, `/claude-features` Opus 5.5)

## Context

2026-09-22 Claude Opus 5.5와 OpenAI GPT-6 Sol, GPT-6 Luna가 Bedrock에 동시에 출시됐다. 2026-09-23
운영 자격증명(Bedrock 장기 API 키, CP on AWS envelope 키 + workspace)으로 호출 경로를 전수 실측했다.

1. **Claude Opus 5.5** ([AWS 모델 카드](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html)):
   Seoul(ap-northeast-2)은 Global CRIS만 제공하고 Geo는 없다. us-east-1은 Geo(`us.`)와 Global 모두 제공.

   | 경로 | model | 결과 |
   |------|-------|------|
   | Bedrock converse_stream (Seoul) | `global.anthropic.claude-opus-5-5` | **200** `end_turn`, TTFT ~2.8s |
   | Bedrock converse_stream (us-east-1) | `us.anthropic.claude-opus-5-5` | **200** `end_turn`, TTFT ~2.8s |
   | CP on AWS `/v1/messages` | `claude-opus-5-5` | **200** `end_turn` |
   | Mantle `/anthropic` (us-east-1) | `anthropic.claude-opus-5-5` | **200** (첫 호출은 Marketplace 구독 개시 중 타임아웃) |
   | converse + `temperature: 0.5` | `us.anthropic.claude-opus-5-5` | 400 "`temperature` is deprecated for this model" |
   | converse + forced `toolChoice: {tool}` | `us.anthropic.claude-opus-5-5` | 400 'tool_choice: type "tool" and "any" are not supported for this model.' |

2. **CP 오등록 실사고**. CP `/v1/models`가 `claude-opus-5-5`를 `claude-opus-5`보다 **먼저** 돌려준다.
   기존 `_match_anthropic_model("opus-5", …)`는 *등록된* 더 긴 타깃만 후보에서 제외했으므로, `opus-5-5`
   타깃이 없던 운영 코드는 5.5 id를 Opus 5 라벨로 등록했다(`/ecs/autoprober` 첫 오등록 2026-09-22 16:27 UTC,
   이후 5분 주기 약 150사이클). `/api/auto-probe/latest`(2026-09-23 05:02 UTC)에서
   `anthropic:claude-opus-5-5 | Anthropic Claude Opus 5 (US)`로 확인 — 실제 Opus 5 CP 채널은 측정되지 않고
   5.5 측정값이 Opus 5 이력에 섞였다. v2.22.1 Fable 5.1(`fable-5` ⊂ `fable-5-1`)과 같은 패턴의 두 번째 사고다.

3. **GPT-6 Sol / GPT-6 Luna**: AWS 모델 카드가 아직 없다(`model-cards-openai.html`에는 Astra만 게재).
   `list-inference-profiles`는 Seoul `global.openai.gpt-6-{sol,luna}`, us-east-1 `us.`/`global.`
   모두 ACTIVE. Responses API 실측:

   | 경로 | 엔드포인트 | model | 결과 |
   |------|-----------|-------|------|
   | Global CRIS | Seoul `bedrock-runtime` `/openai/v1` | `global.openai.gpt-6-{sol,luna}` | **200** (Sol TTFB 559 / TTFT 856ms, Luna 591 / 857ms) |
   | US CRIS | us-east-1 `bedrock-runtime` `/openai/v1` | `us.openai.gpt-6-{sol,luna}` | **200** (Sol 927 / 2059ms, Luna 919 / 1064ms) |
   | Mantle 인리전 us-east-1 | `bedrock-mantle.us-east-1.api.aws/openai/v1` | `openai.gpt-6-{sol,luna}` | 첫 호출 401 `permission_denied` "Your subscription to the model is being set up" → 수 분 뒤 **200** |
   | Mantle 인리전 us-east-2 | `bedrock-mantle.us-east-2.api.aws/openai/v1` | 〃 | 404 `not_found_error` "The model 'openai.gpt-6-sol' does not exist" |
   | Mantle 인리전 us-west-2 | `bedrock-mantle.us-west-2.api.aws/openai/v1` | 〃 | 404 `not_found_error` |

   Astra(Mantle us-west-2만 서빙)와 **정반대의 리전 분포**다. 같은 날 Astra의 Mantle us-east-1/us-east-2도
   재확인했으나 여전히 404였다.

4. **추론 토큰 보고**. 패리티 `reasoning` 프로브와 동일한 요청(effort `low`, "17 x 23은?", 2048 토큰)을
   chat_completions, responses 양쪽에서 재현하면 Sol/Luna 모두 `reasoning_tokens=0`이다. effort `high`
   에서만 Sol 13, Luna 18 토큰이 보고된다.

5. **단가**: GPT-6 Astra 모델 카드에는 이제 공식 단가가 게재돼 있다(Standard, 입력 272K 이하):
   In-Region, Geo CRIS $11 / $55, Global CRIS $10 / $50 (30분 캐시 쓰기 $13.75 / $12.50, 캐시 읽기
   $1.10 / $1.00, 272K 초과 시 입력 2배). Sol/Luna는 카드가 없고 Price List API에도 항목이 없다.
   (→ v2.28.0: Bedrock `ListFoundationModelAgreementOffers` rate card에서 단가를 읽어 반영 — 아래 "v2.28.0 후속".)
   Opus 5.5는 Anthropic 정가 $4 / $20이다(Bedrock 가격 페이지는 동적 렌더링이라 수치 미추출 — Opus 5,
   Fable 5.1과 동일하게 정가를 적용).

## Decision

- **Claude Opus 5.5 — 3채널** (표준 Claude 모델 추가 체크리스트):

  | 키 | 라벨 |
  |----|------|
  | `global.anthropic.claude-opus-5-5` | `Bedrock Claude Opus 5.5 (Global)` |
  | `us.anthropic.claude-opus-5-5` | `Bedrock Claude Opus 5.5 (US)` |
  | `anthropic:claude-opus-5-5` (CP 자동 발견, 타깃 `("opus-5-5", …)`를 `opus-5`보다 앞에) | `Anthropic Claude Opus 5.5 (US)` |

  - temperature 거부 → `_REASONING_MODEL_PATTERNS`의 `"opus-5"`가 substring으로 자연 포함(주석만 갱신).
  - forced `tool_choice` 거부 → 패리티 `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"opus-5-5"` 추가(tool_use 프로브는
    `auto` + 프롬프트 지시로 대체). `"opus-5"`를 넣으면 Opus 5까지 `auto`로 바뀌므로 반드시 점 버전 문자열을 쓴다.
  - 패리티 `_REASONING_MARKERS`, `adaptive_thinking` 규칙은 Opus 5와 동일(비적용) — Opus 5.5만 다르게 둘 근거가 없다.

- **CP 점 버전 가드 (`_is_point_release_of`)**. 타깃 추가만으로는 다음 점 버전(예: `sonnet-5-5`)이 출시되는
  날 같은 사고가 반복된다. `_match_anthropic_model`은 이제 "substring 바로 뒤에 `-<1~2자리 숫자>`가 오고 그 뒤가
  숫자가 아닌" id를 점 버전으로 보고 후보에서 제외한다. 8자리 날짜 서픽스(`claude-haiku-4-5-20251001`)는
  해당하지 않아 기존대로 매칭된다. 점 버전만 서빙되면 base 라벨은 등록되지 않는다(`None` → warning 후 skip) —
  **틀린 라벨로 측정하는 것보다 미등록이 안전하다**. 기존 "등록된 더 긴 타깃 제외" 규칙은 그대로 둔다.
  이미 오기록된 행은 `label_repair.py`가 backend 기동 시(discovery 직후) 카탈로그 라벨로 정정한다.

- **GPT-6 Sol / Luna — 모델마다 3채널** (ADR-027 Astra와 같은 구성 원칙 "Global + US CRIS + Mantle 인리전"):

  | 키 | 라벨 |
  |----|------|
  | `openai:global:global.openai.gpt-6-{sol,luna}` | `OpenAI GPT 6 {Sol,Luna} (Global)` |
  | `openai:us:us.openai.gpt-6-{sol,luna}` | `OpenAI GPT 6 {Sol,Luna} (US)` |
  | `openai:us-east-1:openai.gpt-6-{sol,luna}` | `OpenAI GPT 6 {Sol,Luna} (us-east-1)` |

  `_OPENAI_MODEL_SPECS`에 `("BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID", "GPT 6 Sol", ("global", "us", "us-east-1"))`와
  Luna 한 줄씩. Mantle us-east-2/us-west-2는 404라 스펙에서 제외한다(오류 행 누적 방지, ADR-027과 동일 판단).

- **단가 정책**:
  - Opus 5.5: `claude-opus-5-5` $4 / $20 **정확 키 필수** — 없으면 `get_pricing` prefix fallback이
    `claude-opus-5`($5 / $25)로 조용히 매칭한다.
  - GPT-6 Astra: 공식 카드 단가를 3키로 반영 — `gpt-6-astra`(인리전) $11 / $55, `gpt-6-astra-us` $11 / $55,
    `gpt-6-astra-global` $10 / $50. 비용은 조회 시점 계산이라 과거 Astra 행도 소급 재계산된다(ADR-025 정책).
    프로브는 항상 272K 이하 구간이라 short-context 단가만 둔다.
  - GPT-6 Sol/Luna: **미기재 유지**(추정값 금지). 6채널 모두 `get_pricing`이 `None` → 비용 "-".
    `gpt-6-sol`은 `gpt-6-astra*` 어느 키와도 접두 관계가 아니어서 fallback 오매칭이 없다(회귀 테스트로 고정).
    확정 시 모델마다 인리전, `-global`, `-us` 3키를 **한 커밋에** 추가한다.
    → **v2.28.0에서 반영**: AWS 소유 1차 출처인 agreement offer rate card로 6키를 한 커밋에 추가했다(아래 "v2.28.0 후속").

- **패리티 `_REASONING_MARKERS`에 `gpt-6`을 넣지 않는다**. Astra(ADR-027)와 같은 이유다 — 프로브 판정 근거인
  `reasoning_tokens > 0`이 effort `low`에서 0이라 마커를 넣으면 "미지원"으로 오판한다. effort `high`에서는
  양수가 나오므로, 후속으로 프로브를 effort `high`로 바꾸는 방안은 Astra(`high`에서도 0)와 함께 재검토한다.

- **범위 밖(별도 결정)**: gptbench `_BENCH_SPECS` 미포함(15분 주기 벤치 채널 추가는 비용 결정 — ADR-025,
  v2.25.1 선례), `/claude-features` 대표 모델 미포함(사용자 결정 세트 Fable 5.1·Fable 5·Opus 5·Sonnet 5),
  1P 스펙 미추가(v2.19.1부터 휴면, Astra 선례).
  → v2.28.0(2026-09-23 사용자 결정): 벤치에 Sol/Luna 6채널 편입(12 → 18채널), `/claude-features` 대표 모델에
  Opus 5.5 편입(4 → 5모델). 1P는 여전히 미추가. 아래 "v2.28.0 후속"과 ADR-026 부록 참조.

- **배포 경로**: 신규 env `BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID=openai.gpt-6-sol`,
  `BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID=openai.gpt-6-luna`를 CDK AppServices(backend)와 Scheduler
  `buildTaskDef`(autoprober/insights/parityrun/gptbench/featuresverify) **양쪽**에 주입한다. env 추가
  릴리스이므로 이미지만 교체하는 경로(runbook §6)는 금지 — prober가 env 없는 채널을 조용히 skip해 Sol/Luna
  6채널이 빠진다. IAM 변경 없음(Opus 5.5는 `foundation-model/*` 와일드카드, GPT는 bearer 경로).

활성 카탈로그 **46 → 55** (Bedrock 19 → 21, CP 8 → 9, OpenAI 19 → 25 = Mantle 인리전 16 + Global CRIS 6 +
US CRIS 3; 휴면 1P 5 포함 총계 51 → 60). reliability/cost/analysis/efficiency/anomalies/챗봇 tools는
`AVAILABLE_MODELS` 기반 동적이라 무변경 자동 편입. 패리티 런은 12h당 9채널 × `surfaces_for` × 19 피처 =
361셀이 늘어난다(`is_applicable` 기준 프로브 184 + 사전 skipped 177).

## Consequences

- (+) Claude Opus 계열 최신 세대를 Bedrock Global, Bedrock US, CP 세 경로로 비교할 수 있고, Opus 5 CP 채널이
  다시 실제 `claude-opus-5`를 측정한다.
- (+) CP 자동 발견이 **미래 점 버전에 대해 fail-closed**가 됐다 — 타깃을 먼저 추가하지 않아도 base 라벨이
  오염되지 않는다.
- (+) GPT-6 세대 3모델(Astra, Sol, Luna)이 모두 Global CRIS, US CRIS, Mantle 인리전 각 1채널을 가진다
  (인리전 리전만 모델별로 다름).
- (+) Astra 비용이 "-"에서 실금액으로 바뀌어 30일 예측, 채널 비교 합계에 반영된다.
- (−) **Sol/Luna 6채널은 비용 "-"** — AWS 모델 카드 게재 후 3키씩 추가 필요.
  → 해소(v2.28.0): agreement offer rate card 단가 반영. 모델 카드가 게재되면 카드와 재대조만 남는다.
- (−) **Opus 5 CP 이력 공백** — 오등록 기간(CP가 5.5를 서빙하기 시작한 뒤부터 이번 배포까지) 동안 실제
  `claude-opus-5` CP 측정값이 없다. 그 기간 행은 `label_repair`로 Opus 5.5 이력으로 옮겨지며 복원은 불가.
- (−) Sol/Luna Mantle us-east-2/us-west-2, Astra Mantle us-east-1/us-east-2 공백 — 재확인 후 스펙 튜플에
  리전만 추가하면 편입된다.
  → v2.28.0 정정: **Astra Mantle us-east-1/us-east-2는 "현재 미지원 — 2026-09-23 사용자 결정으로 제외"**이며 정기
  재확인 대상이 아니다(ADR-027 정정). Sol/Luna Mantle us-east-2/us-west-2도 v2.28.1에서 같은 결정(아래 후속 v2.28.1).
- 배포 검증: `/api/auto-probe/latest` 55행, CP 9행에서 `anthropic:claude-opus-5` → `Anthropic Claude Opus 5 (US)`,
  `anthropic:claude-opus-5-5` → `Anthropic Claude Opus 5.5 (US)` 매핑, OpenAI 25행 + 신규 6채널 첫 `success` 확인.
  backend 기동 로그에서 `Label repair: … anthropic:claude-opus-5-5 'Anthropic Claude Opus 5 (US)' -> 'Anthropic Claude Opus 5.5 (US)'`
  확인.

## v2.28.0 후속 (2026-09-23)

- **GPT-6 Sol/Luna 단가 반영 — 출처: Bedrock `ListFoundationModelAgreementOffers` rate card.** AWS 모델 카드와 Price
  List API에는 여전히 항목이 없지만, `aws bedrock list-foundation-model-agreement-offers --model-id openai.gpt-6-{sol,luna}`
  (읽기 전용, us-east-1, us-west-2, ap-northeast-2 모두 같은 값)가 offer의 `termDetails.usageBasedPricingTerm.rateCard[]`
  (per MTok)를 돌려준다. offer id: Sol `offer-pycji3sz5gpcc`, Luna `offer-gmo53nkzc5or6`.
  - **차원 매핑**: `input_tokens_standard` / `output_tokens_standard` = In-Region(Mantle) + Geo CRIS(US) → base 키와
    `-us` 키, `input_tokens_global_standard` / `output_tokens_global_standard` = Global CRIS → `-global` 키.
    priority, flex, long-context(272K 초과) 차원은 쓰지 않는다(프로브는 항상 standard, short-context — Astra와 동일).

    | 키 | input | output | 출처 차원 |
    |----|-------|--------|-----------|
    | `gpt-6-sol`, `gpt-6-sol-us` | $2.20 | $11.00 | `*_standard` |
    | `gpt-6-sol-global` | $2.00 | $10.00 | `*_global_standard` |
    | `gpt-6-luna`, `gpt-6-luna-us` | $0.11 | $0.55 | `*_standard` |
    | `gpt-6-luna-global` | $0.10 | $0.50 | `*_global_standard` |

    rate card의 캐시 읽기 단가(Sol $0.22 / Global $0.20, Luna $0.011 / Global $0.01)와 30분 캐시 쓰기 단가(Sol
    $2.75 / $2.50, Luna $0.1375 / $0.125)도 있으나 `PRICE_TABLE`은 input/output만 둔다(기존 정책).
  - **교차 검증**: 같은 API로 읽은 Astra offer(`offer-7epta7rbw5aws`, standard $11 / $55, global_standard $10 / $50)가
    Astra 공식 모델 카드와 정확히 일치한다. Sol/Luna 값은 OpenAI 정가(Sol $2 / $10, Luna $0.10 / $0.50)에 AWS 카드가
    문서화한 In-Region, Geo +10%를 더한 값과도 같다.
  - **정책**: 6키를 `backend/pricing.py`와 `frontend/src/lib/pricing.ts`에 한 커밋(d6bf474)으로 추가했고, 테스트가 6채널
    id의 정확한 채널별 단가와 Astra 키로의 prefix fallback 부재를 고정한다. 비용은 조회 시점 계산이라 v2.27.0 이후
    Sol/Luna 행도 소급 산정된다(ADR-025 정책). **모델 카드가 게재되면 카드와 다시 대조한다** — 다르면 카드가 우선이다.
- **GPT on AWS 벤치 편입 (사용자 결정 2026-09-23)**: `gptbench._BENCH_SPECS` 끝에 `("GPT 6 Sol", …, ("global", "us",
  "us-east-1"))`와 Luna 한 줄씩 → 벤치 **12 → 18채널**(Mantle 인리전 11 + CRIS 7). 목록 끝에 둔 이유는 사이클이
  데드라인(780초)에 걸리면 뒤 채널부터 skip되므로 컷이 신규 채널에 떨어져 기존 12채널 시계열이 끊기지 않기 때문이다.
  - 벤치 요청 형태 그대로(Responses 스트림, 고정 입력 55,839토큰, `max_output_tokens` 4096, verbosity low, reasoning
    effort medium, `include: reasoning.encrypted_content`, `store: false`, `prompt_cache_retention: 24h`)의 6채널 라이브
    확인: 전부 HTTP 200 `response.completed`. Sol은 `reasoning_tokens` 0(출력 31~35토큰), Luna는 34~47(출력 64~82토큰) —
    벤치 카드의 Sol reasoning 0은 결함이 아니다(위 Decision의 패리티 판단과 같은 관찰). US, us-east-1은 첫 호출부터
    캐시 히트 55,837 / 55,839, Global은 첫 호출이 콜드(0)였다.
  - 사이클 시간: 12채널 실측(2026-09-22, 96사이클) p50 386초, p95 508초, 최대 682초에서 외삽한 18채널 예측은 p50 약
    10분, p90 약 12분, p95 약 775초로 데드라인 780초에 근접한다 — 초과분은 신규 채널에서 먼저 잘린다.
  - 비용 추정(신규 6채널): 채널당 사이클 11호출(워밍업 1 + 측정 10) × 96사이클/일 = 1,056호출, 호출당 입력 55,839토큰
    중 55,837이 캐시 히트 → 채널당 약 59M 캐시 읽기 토큰/일. 위 rate card 캐시 읽기 단가를 곱하면 Sol 3채널 약 $37.7,
    Luna 3채널 약 $1.9, 출력(Sol 호출당 약 33토큰, Luna 약 64~82토큰) 약 $1.2 → **약 $41/일**(Sol 약 $39, Luna 약 $2).
    콜드 캐시 호출(Sol 1회 약 $0.12~0.15)은 드물어 제외했다. 캐시가 전혀 없다면 약 $396/일이다.
  - 같은 릴리스에서 벤치를 하드닝했다: OpenAI 클라이언트 `max_retries=0`, 호출당 wall-clock watchdog(`CALL_TIMEOUT_S`)
    — 2026-09-16~17 GPT 5.4 us-east-2 워밍업 1회가 약 3,540초 걸린 사고 대응(CHANGELOG v2.28.0).
- **`/claude-features` 편입**: Claude Opus 5.5를 5번째 대표 모델로 추가 — 975셀, 자세히는 ADR-026 부록(v2.28.0).
- **Astra Mantle us-east-1/us-east-2**: 2026-09-23 사용자 결정으로 "현재 미지원 — 제외" 확정, 정기 재확인 대상 아님
  (ADR-027 정정). Sol/Luna Mantle us-east-2/us-west-2(404)는 v2.28.1에서 같은 결정(아래).

## 후속 (v2.28.1, 2026-09-23)

- **GPT-6 Sol/Luna Mantle us-east-2/us-west-2 — "현재 미지원, 제외" (사용자 결정)**: 2026-09-23 실측 404
  `not_found_error`. Astra Mantle us-east-1/us-east-2와 같은 처리로, 스펙 튜플에 넣지 않고 정기 재확인 대상에서도
  뺀다. AWS가 지원을 발표하면 `prober._OPENAI_MODEL_SPECS`(와 벤치 `_BENCH_SPECS`)에 리전만 추가한다. 코드 동작 변경 없음.
- **GPT-5.6 Sol 단가를 프로모션 단가로 교정 (사용자 결정)**: AWS 모델 카드와 `ListFoundationModelAgreementOffers`
  (offer-gnqokrqqvdbgw)가 모두 In-Region·Geo $4.40/$22, Global $4/$20을 표시한다(구 $5.50/$33, $5/$30). 카드는
  "최소 2026-11-21까지" 프로모션이라고 밝히므로 종료 후 재확인이 필요하다. 비용은 조회 시점에 계산되므로 과거 행도
  새 단가로 소급 산정된다(사용자 승인). Terra, Luna는 카드와 저장소가 일치해 변경 없음.

