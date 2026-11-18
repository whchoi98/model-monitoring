# ADR-039: OpenAI GPT 6.2 Astra, GPT 6.2 Sol 채널

- **Status**: Accepted
- **Date**: 2026-11-17
- **Related**: ADR-019 (Bedrock Mantle 경로), ADR-027 (GPT 6 Astra, US CRIS), ADR-030 (단가 자동 동기화), ADR-031 (GPT 6.1 Sol, 호스트별 벤치 갈래), ADR-033 (GPT 6.1 Terra, Mantle 인리전 us-east-1 일원화), ADR-035 (모델 탐색 일일 검증 런), ADR-038 (GPT 5.x 제외), v2.44.0(예정)

## Context

사용자 요청(2026-11-17): "astra 6.2, sol 6.2 확인", "현재 모니터링 중인 리전에서 확인." 확인 결과를 본 뒤 같은 날
"메뉴에 모두 추가해주세요. GPT 6.2 Astra , GPT 6.2 Sol".

2026-11-17에 호스트 IAM 자격으로 만든 단기 Bedrock 토큰(`aws_bedrock_token_generator.provide_token`, Bearer)과 Responses API
스트리밍으로 실측했다. 운영 장기 키(`OPENAI_API_KEY`, `ABSK-…`)로는 호출하지 않았다.

| 경로 | model | 결과 |
|------|-------|------|
| `list-foundation-models` (서울, us-east-1, us-east-2, us-west-2) | `openai.gpt-6.2-astra`, `openai.gpt-6.2-sol` | 네 리전 ACTIVE, `INFERENCE_PROFILE`만 |
| `list-inference-profiles` (서울, us-east-1) | `global.`/`us.openai.gpt-6.2-{astra,sol}` | 서울은 `global.`만, us-east-1은 `us.`와 `global.` 둘 다 ACTIVE |
| Global CRIS (서울 bedrock-runtime `/openai/v1`) | `global.openai.gpt-6.2-astra` | **200**, TTFB 385ms, TTFT 1082ms |
| US CRIS (us-east-1 bedrock-runtime) | `us.openai.gpt-6.2-astra` | **200**, TTFB 744ms, TTFT 1281ms |
| Mantle us-east-1 | `openai.gpt-6.2-astra` | **200**, TTFB 848ms, TTFT 1399ms |
| Global CRIS (서울 bedrock-runtime) | `global.openai.gpt-6.2-sol` | **200**, TTFB 420ms, TTFT 685ms |
| US CRIS (us-east-1 bedrock-runtime) | `us.openai.gpt-6.2-sol` | **200**, TTFB 373ms, TTFT 608ms |
| Mantle us-east-1 | `openai.gpt-6.2-sol` | **200**, TTFB 303ms, TTFT 513ms |
| Mantle us-east-2, us-west-2 | 두 모델 | 호출하지 않았다(Mantle 인리전은 us-east-1만 쓴다, ADR-033) |
| 벤치 요청 형태(verbosity low, reasoning medium, encrypted_content, store false, 24h 캐시) | 위 6채널 | 모두 200, 둘째 호출 `cached_tokens` 55839 |
| 패리티 reasoning 형태("17 x 23은?") effort low 각 3회, effort high 각 1회, Responses와 Chat Completions | `global.openai.gpt-6.2-{astra,sol}` | 모두 `reasoning_tokens` 0 |
| Mantle us-east-1 `GET /v1/models` | — | 목록 61개에 두 모델이 아직 없다. 단건 조회 `/v1/models/openai.gpt-6.2-*`는 503 |

여섯 채널 모두 첫 호출부터 200이었다. 이전 신모델(GPT 6 Sol/Luna, 6.1 Sol, 6.1 Terra)의 Mantle us-east-1 첫 호출 401
"subscription is being set up" 과도 상태는 없었다. 지연 시간은 단건 값이다.

Mantle이 추론은 처리하면서 모델 조회에는 두 모델을 올리지 않아, 모델별 데이터 보존 `allowed_modes`는 이 시점에 조회되지 않는다.

단가 출처:

- Bedrock agreement offer `offer-i5wczxyjg7weu`(GPT 6.2 Astra): `*_standard`(In-Region, Geo CRIS) 8.8 / 44, 캐시 읽기 0.44,
  30분 캐시 쓰기 11, 긴 컨텍스트 17.6 / 66(캐시 0.88, 쓰기 22). `*_global_standard` 8 / 40, 0.4, 10, 긴 컨텍스트 16 / 60(0.8, 20).
  이 오퍼에는 `_ultrafast` 차원 16개가 더 있다(Standard의 3배). 파서는 `_standard`로 끝나는 차원만 읽는다.
- Bedrock agreement offer `offer-7vsvjk6xmsl7c`(GPT 6.2 Sol): `*_standard` 2.2 / 11, 0.11, 2.75, 긴 컨텍스트 4.4 / 16.5(0.22, 5.5).
  `*_global_standard` 2 / 10, 0.1, 2.5, 긴 컨텍스트 4 / 15(0.2, 5).
- 두 오퍼 모두 긴 컨텍스트 출력이 짧은 컨텍스트 출력보다 높다. GPT 6.1 Sol 오퍼와 달리 정상값이라 `pricing_sync._plausible_long`이 버리지 않는다.
- OpenAI `pricing.md` "### Standard pricing data"(2026-11-17): `gpt-6.2-astra` $8 / $40, cached input 0.40, 30m write 10, 긴 컨텍스트
  $16 / $60, cached 0.80, 30m write 20. `gpt-6.2-sol` $2 / $10, 0.10, 2.50, 긴 컨텍스트 $4 / $15, 0.20, 5.

## Decision

1. **채널 6개 추가(활성 39 → 45)** — 모델마다 `openai:global:global.openai.gpt-6.2-{astra,sol}`, `openai:us:us.openai.gpt-6.2-{astra,sol}`,
   `openai:us-east-1:openai.gpt-6.2-{astra,sol}`(라벨 `OpenAI GPT 6.2 Astra (Global|US|us-east-1)`, `OpenAI GPT 6.2 Sol (…)`).
   `prober._OPENAI_MODEL_SPECS`의 첫 두 항목(6.2 Astra, 6.2 Sol 순)이다. env는 `BEDROCK_OPENAI_GPT_62_ASTRA_MODEL_ID=openai.gpt-6.2-astra`,
   `BEDROCK_OPENAI_GPT_62_SOL_MODEL_ID=openai.gpt-6.2-sol` 두 개이고(AppServices `backendEnv`, Scheduler `buildTaskDef`, jest 고정)
   Global, US 프로파일 id는 prober가 파생한다. 1P 스펙은 추가하지 않는다.
   활성 45 = Bedrock 17(Global 7, Nova 포함 US 8, 서울 in-region 2) + Claude Platform on AWS 7 + OpenAI 21(Mantle us-east-1 7, Global 7, US 7).
2. **이름 충돌 없음** — `"gpt-6.2-astra"`는 `"gpt-6-astra"`를, `"gpt-6.2-sol"`은 `"gpt-6-sol"`, `"gpt-6.1-sol"`을 포함하지 않는다.
   라벨 `"GPT 6.2 Astra"`, `"GPT 6.2 Sol"`도 `"GPT 6 Astra"`, `"GPT 6 Sol"`을 포함하지 않아 `FAMILY_ORDER`와 `FAMILY_FALLBACK`의 includes
   매칭이 겹치지 않는다. 기본 숨김 패턴(`GPT 5.6`, `GPT 5.5` 등)에도 걸리지 않는다.
3. **`FAMILY_ORDER` 15개** — "Nova 2.0 Lite" 다음, "GPT 6.1 Sol" 앞에 "GPT 6.2 Astra", "GPT 6.2 Sol"(백엔드 `pricing_sources`, 프런트 `sortModels`
   바이트 동일).
4. **단가** — `SEED`(CP 제외 32 → 38), `OPENAI_LIST_SEED` + `openai-list:gpt-6.2-astra`, `openai-list:gpt-6.2-sol`(5 → 7), `_OPENAI_EXTRA`,
   `_OPENAI_LIST_EXTRA`, `SEED_SOURCE_DATES`에 두 오퍼 확인일 2026-11-17. 오퍼 FM 12 → 14, 단가 채널 44 → 52(활성 45 + OpenAI 공식 가격 7),
   `/pricing` 패밀리 13 → 15, 참고 자료 15 → 17(오퍼 14).
5. **패리티** — `_REASONING_MARKERS`에 넣지 않는다(effort low와 high 모두 `reasoning_tokens` 0, `gpt-6` 미포함 규칙 그대로).
   `_NO_FORCED_TOOL_CHOICE_MARKERS`도 그대로다. OpenAI 채널은 카탈로그에서 자동으로 패리티에 들어온다.
6. **GPT on AWS 벤치** — 사용자 요청이 "메뉴에 모두"라 벤치에도 넣는다. `_BENCH_SPECS` 끝에 6.2 Astra, 6.2 Sol 순으로 둔다(데드라인 컷이
   신규 채널부터 떨어진다). 15 → 21채널(Mantle us-east-1 7 + CRIS 14 = Global 7 + US 7), 로그 `GPT bench lanes: cris=14 mantle-us-east-1=7`,
   사이클당 210행. `routers/gptbench.fam_rank`는 6.2 Astra 0, 6.2 Sol 1, 6.1 Sol 2, 6.1 Terra 3, Astra 4, Sol 5, Luna 6.
7. **모델 탐색** — 예제는 백엔드가 채널에서 만든다(ADR-035). 채널마다 Responses 예제 1건이라 일일 런은 71 → 77건이다.
8. **화면**
   - GPT on AWS: `FAMILY_GROUPS` GPT 6.x 세대가 일곱 열(6.2 Astra, 6.2 Sol, 6.1 Sol, 6.1 Terra, Astra, Sol, Luna)이다. 열이 6개 이상인 묶음은
     md 2열, lg 3열, 1480px부터 4열(`min-[1480px]:grid-cols-4`)로 놓는다. 7열이 4 + 3 두 줄이 되어 첫 줄이 GPT 6.2와 6.1, 둘째 줄이 GPT 6
     세대다. e2e가 1100px과 1479px 3 + 3 + 1, 1480px과 1800px 4 + 3, 1480px 카드 폭 300px 이상을 고정한다.
   - 선 패턴은 7종이다. 6.2 Astra는 실선(v2.43.0에 GPT 5.6 Terra가 빠지며 비어 있던 패턴), 6.2 Sol은 점선 `"2 4"`(v2.39.0에 GPT 5.4와 함께 빠진 패턴).
   - `familyOf`의 정규식에 `6\.2 (?:Astra|Sol)`을 더했다. "GPT 6.2 Luna", "GPT 6.2 Solar", "GPT 6.21 Sol"은 모르는 family다.
   - `StreamingView` 배지는 6.2 Astra pink-600, pink-800, pink-950, 6.2 Sol orange-700, orange-900, orange-950이고 `extractModelName`은
     `gpt-6.2-astra`, `gpt-6.2-sol` 분기가 맨 앞이다.
9. **추세 차트 색**
   - GPT 6.2 Astra는 분홍 계열이다(Global `#ff1fa5` 실선, US `#f4a6c6` 파선, us-east-1 `#6a394e` 일점쇄선, 같은 패턴 최근접 ΔE 16.6, 17.1, 17.2).
   - GPT 6.2 Sol은 주황 계열이다(Global `#ff5500`, US `#7d4b36`, us-east-1 `#f5c09a`, 최근접 ΔE 17.0, 17.5, 16.2).
   - `FAMILY_FALLBACK`에 `["GPT 6.2 Astra", "#ff1fa5"]`, `["GPT 6.2 Sol", "#ff5500"]`.
   - `TrendChart.test.ts`가 새 6개 시리즈의 같은 패턴 ΔE 15 이상(서로도 다른 모델로 센다), 카드 대비 하한, Global 실선(계열 기본 선택)과
     CP Sonnet 5.5의 거리, 패밀리 안 세 단계(ΔE 12 이상)를 고정한다.

## Alternatives

- **벤치 카드 한 묶음 7열의 배치**
  - 1800px 5열(v2.38.0 규칙 그대로): 5 + 2가 되어 GPT 6 세대가 두 줄에 갈린다. 기각.
  - 1400px부터 4열: 카드 폭이 286px라 지표 숫자가 붙는다. 1480px(약 306px)로 정했다.
  - 세대별 세 묶음(GPT 6.2, 6.1, 6)으로 나누기: 묶음 제목 구조가 바뀐다. 요청 범위가 모델 추가라 기존 "GPT 6.x 세대" 한 묶음을 유지했다.
- **추세 차트 색**
  - 초록과 청록은 GPT 6 세대, 금색은 6.1 Sol, 보라는 6.1 Terra가 쓴다. 남은 색조 가운데 세 채널 모두 같은 패턴 ΔE 15 이상이 나오는 것이
    분홍과 주황이었다.
  - GPT 6.2 Sol의 us-east-1을 주황과 같은 Lab 색조의 옅은 단계로 두면 채도가 8이라 거의 회색이다. 살구색 `#f5c09a`는 Lab 색조가 주황과
    13.7° 벌어지지만 주황 계열로 읽힌다. 그래서 Sol의 색조 범위 검사는 15° 미만이고, Astra는 6.1 Sol, 6.1 Terra처럼 10° 미만이다.
  - 같은 색조의 짙은 주황 적색(`#b81800` 부근)은 Opus 계열의 장미색과 헷갈릴 수 있어 쓰지 않았다.
- **벤치에서 제외** — 사용자 요청이 "메뉴에 모두 추가"라 넣었다. 추가 비용은 캐시 읽기 단가 기준 추정으로 하루 약 $100이다(6.2 Astra 약 $79,
  6.2 Sol 약 $20 — 채널당 11호출 × 96사이클 × 약 55.8k 캐시 토큰). 비용을 줄이려면 `_BENCH_SPECS`의 두 줄을 빼거나 `GPT_BENCH_RUNS`를 낮춘다.

## Consequences

- AutoProber 한 사이클의 OpenAI 호출이 15 → 21회, 벤치는 사이클당 15 → 21채널 × 11호출, ExplorerVerify 1런 6건, 패리티 런 6행이 는다.
  Claude 쪽(CP 호출 수, `/claude-features`, `/prompts`)은 변하지 않는다.
- 새 env가 두 개라 이미지와 함께 AppServices, Scheduler 두 스택을 digest 고정 CDK로 배포한다. 이미지만 배포하면 6채널이 조용히 빠진다.
  IAM 변경은 없다.
- 배포 뒤 확인할 것(이 ADR을 쓴 시점에는 배포하지 않았다 — 결과는 아래 "배포 결과"):
  - `/api/models`는 45개, `/api/auto-probe/latest`의 `openai:` 행은 21개여야 한다.
  - 벤치 로그는 `GPT bench lanes: cris=14 mantle-us-east-1=7`, rows 210(`GPT_BENCH_RUNS` 10)이어야 한다.
  - PricingSync 로그는 `52 active channels`여야 한다. 첫 동기화는 새 채널이 없던 스냅샷과 비교하므로 `/pricing` 변경 목록에 신규 채널 8건
    (6채널 + OpenAI 공식 가격 2)이 한 번 나온다.
  - 운영 장기 키(`OPENAI_API_KEY`)로는 호출해 보지 않았으므로 첫 사이클에서 여섯 채널이 success인지 본다.
- 배포 결과(2026-11-18 01:58–02:03 UTC, 이미지 `vb4d374e`, 기록 `docs/reviews/2026-11-18-v244-deployment.md`): 위 네 항목이 모두 맞았다.
  운영 장기 키의 첫 회차(run 50026)에서는 Mantle us-east-1 두 채널이 오류였고(GPT 6.2 Sol 401 "Your subscription to the model is being set up",
  GPT 6.2 Astra 61초 뒤 "Request timed out") 다음 회차(run 50027)부터 여섯 채널 모두 success였다. 전날 단기 토큰으로는 첫 호출부터 200이었으므로,
  Marketplace 구독 개시 과도 상태는 호출하는 키마다 따로 생기는 것으로 보인다(원인은 확인하지 못했다).
- 남은 일:
  - Mantle us-east-1 `GET /v1/models`에 두 모델이 올라오면 `allowed_modes`를 조회할 수 있다(지금은 목록에 없고 단건 조회 503).
  - OpenAI `pricing.md`의 "30m write" 열 이름 드리프트(ADR-033 후속)는 그대로다. `tests/fixtures/pricing/openai_pricing_20261117.md`도 두 모델의
    `cache_write`, `long_cache_write`를 None으로 읽는 현재 동작을 고정한다. 저장된 seed 값(문서의 30m write)은 남는다.
  - 대시보드 카드 등급 임계치(ADR-029)는 2026-09-23 분포 기준이라 새 모델의 분포를 반영하지 않는다.
