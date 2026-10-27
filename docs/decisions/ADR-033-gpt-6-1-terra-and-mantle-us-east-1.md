# ADR-033: OpenAI GPT 6.1 Terra 채널과 Mantle 인리전 us-east-1 일원화

- **Status**: Accepted
- **Date**: 2026-10-27
- **Related**: ADR-019 (Bedrock Mantle 경로), ADR-027 (GPT 6 Astra, US CRIS — Mantle 404 리전 제외 원칙), ADR-028 (GPT 6 Sol/Luna), ADR-030 (단가 자동 동기화), ADR-031 (GPT 6.1 Sol, 호스트별 벤치 갈래), v2.38.0

## Context

사용자 요청(2026-10-27): "terra 6.1을 추가합니다." 작업 도중 같은 날 추가 지시: "gpt mantle은 모두 us-east-1 으로 변경."
벤치 포함 여부는 사용자가 "벤치에 포함"을 골랐다.

2026-10-27 운영 자격증명(Bedrock 장기 키 `ABSK-…`, Responses API 스트리밍)으로 실측했다.

| 경로 | model | 결과 |
|------|-------|------|
| `list-foundation-models` (서울, us-east-1, us-east-2, us-west-2) | `openai.gpt-6.1-terra` | 네 리전 ACTIVE, `INFERENCE_PROFILE`만 |
| `list-inference-profiles` | `global.`/`us.openai.gpt-6.1-terra` | 서울은 `global.`, US 세 리전은 둘 다 ACTIVE |
| Global CRIS (서울 bedrock-runtime `/openai/v1`) | `global.openai.gpt-6.1-terra` | **200**, TTFB 597ms, TTFT 965ms |
| US CRIS (us-east-1 bedrock-runtime) | `us.openai.gpt-6.1-terra` | **200**, TTFB 937ms, TTFT 1351ms |
| Mantle us-east-1 | `openai.gpt-6.1-terra` | 첫 호출 401 "Your subscription to the model is being set up", 약 2분 뒤 **200**(TTFB 938ms, TTFT 1373ms) |
| Mantle us-east-2, us-west-2 | `openai.gpt-6.1-terra` | 404 `not_found_error` "The model 'openai.gpt-6.1-terra' does not exist" |
| 벤치 요청 형태(verbosity low, reasoning medium, encrypted_content, store false, 24h 캐시) | 위 3채널 | 모두 200 |
| 패리티 reasoning 형태(effort low, "17 x 23은?") Responses, Chat Completions 각 3회 | `global.openai.gpt-6.1-terra` | `reasoning_tokens` 0(effort 기본값에서는 12~21). 6.1 Sol도 0 |
| Mantle us-east-1 Responses 1회씩 | GPT 6.1 Terra, 6.1 Sol, 6 Astra, 6 Sol, 6 Luna, 5.6 Sol, 5.6 Terra, 5.6 Luna, 5.5, 5.4 | **10개 모두 200**(GPT 6 Astra는 2026-09-09, 09-23 404였다) |

단가 출처:

- Bedrock agreement offer `offer-34pzbdgg26ley`(GPT 6.1 Terra): `*_standard`(In-Region, Geo CRIS) 1.1 / 5.5, 캐시 읽기 0.055,
  30분 캐시 쓰기 1.375, 긴 컨텍스트 2.2 / 8.25(캐시 0.11, 쓰기 2.75). `*_global_standard` 1 / 5, 0.05, 1.25, 긴 컨텍스트 2 / 7.5
  (0.1, 2.5). 긴 컨텍스트 출력이 짧은 컨텍스트 출력보다 높다 — 6.1 Sol 오퍼(2.2 / 2)와 달리 정상값이다.
- OpenAI `pricing.md` "### Standard pricing data": `gpt-6.1-terra` $1 / $5, cached input 0.05, 30m write 1.25, 12h write 2.50,
  긴 컨텍스트 $2 / $7.50, cached 0.10, 30m write 2.50.

GPT on AWS 벤치의 직전 24시간(2026-10-26~27, 96사이클) 갈래 소요: cris 9채널 p50 228초, p90 244초, mantle-us-east-1 6채널 p50 126초,
p90 138초, mantle-us-east-2 p90 64초, mantle-us-west-2 p90 119초. 데드라인 780초.

## Decision

1. **GPT 6.1 Terra 3채널** — `openai:global:global.openai.gpt-6.1-terra`, `openai:us:us.openai.gpt-6.1-terra`,
   `openai:us-east-1:openai.gpt-6.1-terra`(라벨 `OpenAI GPT 6.1 Terra (Global|US|us-east-1)`). `prober._OPENAI_MODEL_SPECS`의 둘째
   항목(6.1 Sol 바로 뒤), env `BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID=openai.gpt-6.1-terra`(AppServices `backendEnv`, Scheduler
   `buildTaskDef`, jest 고정). `FAMILY_ORDER`(백엔드 `pricing_sources`, 프런트 `sortModels`)에서 `"GPT 6.1 Sol"` 바로 뒤, 23개.
   `"GPT 6.1 Terra"`는 다른 family의 부분 문자열이 아니고 `"gpt-6.1-terra"`도 `"gpt-5"`, `"gpt-6.1-sol"`, `"gpt-5.6-terra"`에 걸리지 않는다.
2. **Mantle 인리전 us-east-1 일원화(사용자 결정)** — 모든 GPT 모델의 Mantle 인리전 채널은 us-east-1 하나다. us-east-2, us-west-2 채널
   8개(GPT 5.4 두 리전, 5.5 us-east-2, 5.6 Sol us-east-2, 5.6 Terra 두 리전, 5.6 Luna 두 리전)는 등록하지 않고, GPT 6 Astra의 인리전
   채널은 us-west-2에서 us-east-1로 옮긴다. 활성 66 → 61(OpenAI 28 → 23 = Mantle us-east-1 10 + Global 8 + US 5), 카탈로그 71 → 66.
   `prober._OPENAI_MODEL_SPECS`, `gptbench._BENCH_SPECS`, `pricing_seed._OPENAI`의 리전 튜플을 함께 고친다(테스트가 셋을 맞춰 본다).
   `OPENAI_US_EAST_2_BASE_URL`, `OPENAI_US_WEST_2_BASE_URL` 주입은 남긴다 — 리전을 되살릴 때 스펙 튜플만 고치면 된다.
3. **단가** — `SEED`(CP 제외 55 → 50), `OPENAI_LIST_SEED` + `openai-list:gpt-6.1-terra`(9 → 10), `_OPENAI_EXTRA`, `_OPENAI_LIST_EXTRA`,
   `SEED_SOURCE_DATES`에 새 오퍼 확인일 2026-10-27. 오퍼 FM 21 → 22, 단가 채널 75 → 71, `/api/pricing` 참고 자료 24 → 25(오퍼 22).
   빠진 채널의 `price_history` 행은 지우지 않는다(그 채널의 과거 비용 계산에 쓰인다).
4. **패리티** — `_REASONING_MARKERS`에 넣지 않는다(effort low `reasoning_tokens` 0, ADR-027과 같은 근거). OpenAI 채널은 카탈로그에서
   자동으로 패리티에 들어오므로 그 밖의 변경은 없다.
5. **GPT on AWS 벤치** — 6.1 Terra 3채널을 `_BENCH_SPECS` 끝에 넣고 Mantle 인리전을 us-east-1로 모은다. 21 → 19채널(Mantle us-east-1 8 +
   CRIS 11 = Global 6 + US 5), 갈래 넷 → 둘(`cris` 11, `mantle-us-east-1` 8, 로그 `GPT bench lanes: cris=11 mantle-us-east-1=8`).
   `routers/gptbench.fam_rank`는 6.1 Sol 0, 6.1 Terra 1, Astra 2, Sol 3, Luna 4, 5.6 Terra 5, 5.5 6, 5.4 7. 갈래 동작 테스트(여러 Mantle
   리전 갈래 병렬, 느린 호스트 격리, 대기 상한)는 v2.37.x의 네 갈래 스펙(`tests/test_gptbench.py` `FOUR_LANE_SPECS`, `lane_env`)으로 계속 검증한다.
6. **화면**
   - GPT on AWS: `FAMILY_GROUPS` GPT 6.x 세대가 다섯 열(6.1 Sol, 6.1 Terra, Astra, Sol, Luna)이라 md 2열, lg 3열(3 + 2 두 줄,
     1799px까지), 1800px부터 5열(`min-[1800px]:grid-cols-5`)로 놓는다. xl 4열이면 마지막 열만 둘째 줄에 남고, 1600px 5열은 카드 폭이
     약 266px라 지표 숫자가 붐볐다(1800px에서 약 300px). e2e가 1100, 1440, 1600px 두 줄, 1800px 한 줄을 고정한다.
   - 선 패턴은 8종이고 6.1 Terra는 `"16 4 4 4 4 4"`(주기 36px, 범례 선 38px 안)다.
   - `familyOf`가 `GPT 6.1 Terra`를 읽는다.
   - `REGION_COLORS`는 지난 사이클이 7일 추세에 남으므로 us-east-2, us-west-2 색을 유지한다.
7. **추세 차트 색**
   - GPT 6.1 Terra는 보라 계열 한 패밀리다(Global `#d633ff`, US `#5f4266`, us-east-1 `#9b3eb2`, 같은 패턴 최근접 ΔE 19.3).
   - GPT 6 Astra (us-east-1)는 세룰리안 `#1898c0`(최근접 ΔE 22.7)이다. 일점쇄선 초록은 다른 OpenAI 인리전 선과 겹쳐 초록 안에서는 13.7이 한계였다.
   - 수집을 멈춘 us-east-2, us-west-2 라벨은 지난 데이터를 그리도록 색을 유지한다.
   - `TrendChart.test.ts`가 새 4개 시리즈의 ΔE 15 이상, 대비 하한, 6.1 Terra 패밀리 일관성을 고정한다.

## Alternatives

- **Mantle us-east-2, us-west-2 채널 유지** — 사용자 지시("모두 us-east-1")와 맞지 않는다. 기각.
- **빠진 채널의 저장 행과 단가 행 삭제 또는 숨김** — 행은 실제 측정이라 남긴다. 화면에서 바로 숨기려면 코드 수정 없이
  `HIDDEN_MODEL_PATTERNS="(1P),(us-east-2),(us-west-2)"`를 backend와 스케줄 태스크에 주입하면 된다(적용하지 않음).
- **벤치에서 6.1 Terra 제외** — 사용자가 "벤치에 포함"을 골랐다. 갈래 여유가 충분하다(cris 11채널 추정 약 300초,
  mantle-us-east-1 8채널 약 185초, 데드라인 780초).

## Consequences

- AutoProber 한 사이클의 OpenAI 호출이 28 → 23회로 준다. 벤치는 사이클당 21 → 19채널 × 11호출이다.
  6.1 Terra 몫은 하루 약 $10이고 대부분 캐시 읽기($0.05~0.055/MTok)다.
- 새 env가 있으므로 이미지와 함께 AppServices, Scheduler 두 스택을 digest 고정으로 배포한다. 이미지만 배포하면 6.1 Terra 3채널이 조용히 빠진다.
- 배포 뒤 확인할 것:
  - `/api/auto-probe/latest`의 `openai:` 행은 23개여야 한다.
  - 6.1 Terra 3채널이 success여야 한다. Mantle us-east-1 첫 호출은 401 과도 상태일 수 있다.
  - 벤치 로그는 `cris=11 mantle-us-east-1=8`, rows 190(`GPT_BENCH_RUNS` 10)이어야 한다.
- 빠진 채널은 대시보드 `/latest`에서 15분 안에 사라진다. 신뢰성(7일), 비용(30일), 벤치 추세(7일)에는 지난 측정이 기간이 지날 때까지 남는다.
- 후속(미수정): 라이브 OpenAI `pricing.md` Standard 표가 "cache writes" 열을 "30m write"와 "12h write"로 바꿨다.
  - 그래서 `parse_openai_pricing_md`는 라이브 문서에서 `cache_write`, `long_cache_write`를 None으로 읽는다.
  - None 관측은 변경이 아니므로 저장된 seed 값이 남지만, 그 두 필드는 동기화로 다시 확인되지 않는다.
  - `tests/fixtures/pricing/openai_pricing_20261027.md`가 현재 동작을 고정한다.
  - 파서에 "30m write" 열 이름을 더할지 결정이 필요하다.
