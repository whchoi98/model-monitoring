# ADR-027: OpenAI GPT-6 Astra 채널 3개 — 추론 프로파일 전용, US CRIS 유사 리전 `us`, Mantle 인리전은 us-west-2만

- **Status**: Accepted
- **Date**: 2026-09-09
- **Related**: ADR-019 (Mantle Path 4), ADR-020 (1P direct Path 5), ADR-025 (Global CRIS + 채널별 단가 분리), v2.25.0

## Context

OpenAI GPT-6 Astra가 Bedrock에 올라왔다. 2026-09-09 운영 Bedrock 장기 API 키
(Responses API)로 호출 경로를 전수 실측한 결과, 기존 GPT-5.x 채널과 다른 두 가지가
확인됐다.

1. **추론 프로파일 전용**. 접두사 없는 평문 id(`openai.gpt-6-astra`)는 온디맨드로
   호출되지 않는다(추론 프로파일 필요). 반면 프로파일 id는 두 경로에서 200:

   | 경로 | 엔드포인트 | model | 결과 |
   |------|-----------|-------|------|
   | Global CRIS (기존 경로) | `https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1/responses` | `global.openai.gpt-6-astra` | **200** (usage in 13 / out 5) |
   | **US CRIS (신규 경로)** | `https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1/responses` | `us.openai.gpt-6-astra` | **200** |

2. **Mantle 인리전은 us-west-2만 서빙**. 기존 in-region 경로
   (`bedrock-mantle.<region>.api.aws/openai/v1`, model `openai.gpt-6-astra`) 실측:

   | 리전 | 결과 |
   |------|------|
   | us-west-2 | **200** |
   | us-east-1 | 404 `not_found_error` "The model does not exist" |
   | us-east-2 | 404 `not_found_error` "The model does not exist" |

   같은 계정의 Bedrock 모델 액세스는 세 리전 모두 AVAILABLE/AUTHORIZED다. 즉 엔티틀먼트
   문제가 아니라 **Mantle 호스트 쪽 온보딩이 아직 끝나지 않은 상태**다.

Price List API에는 GPT-6 항목이 아직 없다.

## Decision

- **채널 3개만 등록** (사용자 결정: "서울은 global로 구현하고, mantle in region, us cris 추가"):

  | 키 | 라벨 | 경로 |
  |----|------|------|
  | `openai:global:global.openai.gpt-6-astra` | `OpenAI GPT 6 Astra (Global)` | `OPENAI_GLOBAL_BASE_URL` (Seoul bedrock-runtime) |
  | `openai:us:us.openai.gpt-6-astra` | `OpenAI GPT 6 Astra (US)` | `OPENAI_US_BASE_URL` (us-east-1 bedrock-runtime) |
  | `openai:us-west-2:openai.gpt-6-astra` | `OpenAI GPT 6 Astra (us-west-2)` | `OPENAI_US_WEST_2_BASE_URL` (Mantle 인리전) |

- **신규 유사 리전 `us`**. `global`(ADR-025), `1p`(ADR-020)와 같은 패턴으로 `_OPENAI_REGION_ENV`에
  `"us": "OPENAI_US_BASE_URL"`을 추가한다. 등록 루프는 `global`에서 하던 것과 동일하게 인리전 id에
  `us.` 접두를 붙여 프로파일 id를 파생하고 라벨 서픽스는 `(US)`를 쓴다 — 별도 model-id env는 없다.
  `_OPENAI_MODEL_SPECS`에 `("BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", "GPT 6 Astra", ("global", "us", "us-west-2"))`
  한 줄만 추가된다.

- **us-east-1 / us-east-2 Mantle 채널은 등록하지 않는다.** 404가 나는 리전을 스펙에 넣으면
  5분마다 오류 행만 쌓여 신뢰성, 이상 징후 지표를 오염시킨다. Mantle 온보딩 재확인은 후속 과제.

- **라우팅 env**: 신규 `OPENAI_US_BASE_URL`
  (`https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1`) + 기존 `OPENAI_API_KEY` bearer 재사용.
  CDK AppServices(backend)와 Scheduler `buildTaskDef`(autoprober/insights/parityrun/gptbench/
  featuresverify 공용 빌더) **양쪽 주입**. IAM 변경 없음(bearer 경로, Fargate egress는 이미 us-east-1,
  us-west-2 호스트에 도달).

- **단가는 미확정으로 남긴다 (후속 업데이트)**. Price List API에 GPT-6 항목이 없고 공식 모델 카드
  단가도 확정 전이라 `PRICE_TABLE`에 키를 넣지 않는다. `pricing._normalize_key`는 `us` 세그먼트를
  기존 `parts[0] in ("global","us","eu","apac")` 규칙으로 처리해 `us.` 접두를 벗기고 `-us` 서픽스를
  붙인다(`gpt-6-astra-us` — `-global`과 대칭). 인리전 us-west-2 키는 `gpt-6-astra`. 세 키 모두
  `get_pricing`이 `None`을 반환해야 하며(접두 fallback 오매칭 금지 — 회귀 테스트로 고정), 비용 화면은
  "-"로 표시된다. **잘못된 단가로 비용을 그리는 것보다 공백이 안전하다**는 판단.

- **gptbench `_BENCH_SPECS` 미포함, 1P 스펙 미추가.** gptbench는 별도 카탈로그이며 15분 주기라
  채널 추가는 비용 결정 사항(ADR-025 선례). 1P는 v2.19.1부터 휴면.

활성 카탈로그 **43 → 46** (OpenAI 16 → 19 = Mantle 인리전 14 + Global CRIS 4 + US CRIS 1;
휴면 1P 5 포함 총계 48 → 51). reliability/cost/analysis/efficiency/anomalies/챗봇 tools/parity는
전부 `AVAILABLE_MODELS` 기반 동적이라 무변경 자동 편입 — 패리티 런은 12h당 3채널 × 2 surface
(`chat_completions`, `responses`) × 19 피처 = 114셀이 늘어난다(`is_applicable` 실측: 프로브 48 +
사전 skipped 66, 그중 `reasoning`/`reasoning_effort` 12셀은 아래 판단으로 skipped).

- **`_REASONING_MARKERS`에 `gpt-6`을 넣지 않는다 (2026-09-09 라이브 확인 근거).** Global 경로
  Responses API `reasoning: {"effort": "low"}`("17 x 23은?", max_output_tokens 2048)와 US CRIS
  `effort: "high"`, Mantle us-west-2 chat completions `reasoning_effort: "low"` 세 호출 모두 200으로
  **파라미터는 수락**되지만 usage의 `reasoning_tokens`가 전부 **0**이었다. 패리티 `reasoning` 프로브는
  `reasoning_tokens > 0`을 지원 판정 근거로 쓰므로(`parity/probes.py`), 마커를 넣으면 12셀이 "지원
  안 함"으로 찍힌다 — 실제로는 "수락하나 추론 토큰을 보고하지 않음"이라 판정 근거가 불충분하다. GPT-5.x
  계열은 같은 호출에서 reasoning_tokens가 양수라 마커에 포함돼 있다. 후속: Astra의 추론 노출 방식이
  문서화되거나 reasoning_tokens가 보고되기 시작하면 `"gpt-6"`을 마커에 추가한다(+12셀, 12h당 프로브 +4).

## Consequences

- (+) Seoul 기준 Global CRIS vs US CRIS vs Mantle 인리전(us-west-2) 세 경로의 레이턴시를 같은
  모델로 직접 비교할 수 있다 — 유사 리전 `us`가 붙은 첫 채널.
- (+) `us` 유사 리전이 프로버, pricing, 정렬, 모델 탐색기에 일반화돼, 앞으로 US CRIS만 제공되는
  OpenAI 모델은 스펙 한 줄로 추가된다.
- (−) **비용 화면에서 GPT-6 Astra 3채널은 "-"** — 30일 예측, 채널 비교 합계에 기여하지 않는다.
  단가 확정 시 `PRICE_TABLE`에 `gpt-6-astra`(인리전), `gpt-6-astra-global`, `gpt-6-astra-us` 3키를
  넣으면 비용은 조회 시점 계산이라 소급 재계산된다(ADR-025와 동일 정책).
- (−) **Mantle us-east-1/us-east-2 공백** — 표에는 "Mantle 미온보딩(404) — 재확인"으로 남는다.
  재확인 후 404가 풀리면 스펙 튜플의 리전 목록에 두 리전을 추가하는 것만으로 편입된다.
- (−) gptbench `/gpt-on-aws` 벤치에는 GPT-6 Astra가 보이지 않는다(별도 결정 필요).
- 배포 검증: autoprober 로그/`/api/auto-probe/latest`에서 OpenAI 19행 + 신규 3채널 첫 `success`
  확인 필수. env 주입 누락 시 prober가 **조용히 skip**하므로 한쪽 스택만 배포하면 대시보드와 스케줄
  태스크의 카탈로그가 어긋난다(1P, v2.20.0과 동일 메커니즘 — deploy.md 체크리스트 준수).
