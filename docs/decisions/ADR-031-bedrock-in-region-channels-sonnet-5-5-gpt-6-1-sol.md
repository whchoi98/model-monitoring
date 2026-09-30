# ADR-031: Bedrock 서울 In-Region 채널(`bedrock:<region>:<fm-id>` 키), Claude Sonnet 5.5, GPT-6.1 Sol, GPT on AWS 벤치 두 갈래

- **Status**: Accepted
- **Date**: 2026-09-30
- **Related**: ADR-019 (Mantle Path 4, `openai:<region>:<id>` 키), ADR-025 (Global CRIS, 채널별 단가), ADR-026 (Claude API Features — v2.32.0 부록), ADR-027 (유사 리전 `us`), ADR-028 (CP 점 버전 가드 `_is_point_release_of`), ADR-030 (단가 자동 동기화), v2.32.0

## Context

사용자 요청(2026-09-30): "sonnet 5.5, gpt sol 6.1이 추가되었습니다. 메뉴들에 해당 내용을 포함합니다. 추가로 서울리전(In-Region)에
Opus 5.0, Sonnet 5.0이 포함되었습니다. 이것도 포함해 주세요."

2026-09-30 운영 자격증명(Bedrock 장기 API 키, CP on AWS envelope 키 + workspace)으로 호출 경로와 공식 단가를 실측했다.
`ListFoundationModels`(ap-northeast-2)에서 `anthropic.claude-opus-5`와 `anthropic.claude-sonnet-5`만 `ON_DEMAND`이고
`anthropic.claude-sonnet-5-5`는 `INFERENCE_PROFILE`만 지원한다. `list-inference-profiles`는 네 리전 어디에도
`us.anthropic.claude-sonnet-5-5`가 없고 `global.`은 있다. `global.openai.gpt-6.1-sol`, `us.openai.gpt-6.1-sol`은 있다.

1. **Claude 경로**

   | ID | 경로 | model | 결과 |
   |----|------|-------|------|
   | — | Bedrock converse_stream (Seoul) | `global.anthropic.claude-sonnet-5-5` | **200** |
   | — | converse + `temperature` | `global.anthropic.claude-sonnet-5-5` | 400 "`temperature` is deprecated for this model" |
   | — | converse_stream | `us.anthropic.claude-sonnet-5-5` | "The provided model identifier is invalid" (프로파일 없음) |
   | — | converse_stream (Seoul, 평문 id) | `anthropic.claude-sonnet-5-5` | on-demand 미지원 (추론 프로파일 전용) |
   | — | converse_stream (Seoul, 평문 id) | `anthropic.claude-opus-5`, `anthropic.claude-sonnet-5` | **200**, temperature는 400 |
   | V8 | invoke_model, invoke_model_with_response_stream (Seoul, 평문 id, max_tokens 16) | `anthropic.claude-opus-5`, `anthropic.claude-sonnet-5` | **200** (Opus 5 converse는 16토큰에서 `max_tokens` 정지, 본문 없음) |
   | V8 | CountTokens (Seoul, 평문 id) | `anthropic.claude-opus-5`, `anthropic.claude-sonnet-5` | ValidationException "The provided model doesn't support counting tokens" |
   | — | converse forced `toolChoice` tool, any, auto (Seoul, 평문 id) | `anthropic.claude-opus-5`, `anthropic.claude-sonnet-5` | 모두 **200** |
   | V1 | converse `toolChoice` tool, any | `global.anthropic.claude-sonnet-5-5` | 400 "tool_choice: type tool and any …", auto는 200 `tool_use` |
   | V2 | `thinking {type: enabled, budget_tokens: 1024}` | Sonnet 5.5 | 400 "thinking.type.enabled is not supported"(Sonnet 5도 같은 400). adaptive + effort high, low는 200 |
   | V3 | Mantle us-east-1 `/anthropic` | `anthropic.claude-sonnet-5-5` | 404 `not_found_error` 두 번. 대조군 `anthropic.claude-sonnet-5`는 200 |
   | — | CP `/v1/models` | — | 첫 항목이 `claude-sonnet-5-5`, 그다음 `claude-opus-5-5`, `claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5` … |
   | V4 | CP advisor | `claude-sonnet-5-5` + advisor `claude-opus-5-5` | supported (`server_tool_use` + `advisor_redacted_result`) |
   | V5 | CP Models API, 캐시, computer use | `claude-sonnet-5-5` | `max_input_tokens` 1,000,000, `max_tokens` 128,000. `CACHE_PAD`로 cache_creation 3103 → cache_read 3103. `computer_toolset_20260801` 지원, legacy `computer_20251124`는 400 "does not support tool types" |
   | V13 | us-east-1 OptimizePrompt | `targetModelId=anthropic.claude-sonnet-5-5` | **200** (`analyzePromptEvent` + `optimizedPromptEvent`, 16.2초) |

   CountTokens 거부는 CRIS 프로파일만의 제약이 아니다. 서울 평문 FM id에서도 같은 문구로 거부된다(관찰만, `/claude-features`
   `count_tokens` 판정은 바꾸지 않는다 — ADR-026 v2.32.0 부록).

2. **GPT-6.1 Sol 경로** (Responses API)

   | ID | 경로 | model | 결과 |
   |----|------|-------|------|
   | — | Global CRIS, Seoul `bedrock-runtime` `/openai/v1` | `global.openai.gpt-6.1-sol` | **200** (TTFB 592ms), `reasoning_tokens` 0 |
   | — | US CRIS, us-east-1 `bedrock-runtime` `/openai/v1` | `us.openai.gpt-6.1-sol` | **200** (TTFB 950ms) |
   | V6 | Mantle us-east-1 | `openai.gpt-6.1-sol` | 첫 호출 401 "subscription is being set up"(Marketplace 구독 개시) 뒤 **200** (TTFB 930ms, TTFT 1384ms, `reasoning_tokens` 0) |
   | — | Mantle us-east-2, us-west-2 | `openai.gpt-6.1-sol` | 404 |
   | V7 | 벤치 요청 형태(약 55.8k 토큰, effort medium, `include` encrypted_content, `store` false, `prompt_cache_retention` 24h, verbosity low), 채널마다 2회 | 3채널 | 모두 200/200. Global TTFB 1225/1001ms, TTFT 3778/2633ms, cached 0 → 55837. US 1699/1547ms, 3847/3510ms, cached 55837 두 번. Mantle us-east-1 1620/1084ms, 7948/4028ms, cached 55837 두 번 |

3. **공식 단가** (`ListFoundationModelAgreementOffers`, us-east-1, 읽기 전용, USD per MTok, Standard)

   | FM | offer | 차원 | 입력 / 출력 |
   |----|-------|------|-------------|
   | `anthropic.claude-opus-5` | `offer-f3u6lgbrem3zs` | `APN2_*_standard` (서울 in-region) | 5.5 / 27.5 (US `USE1_*_standard`와 같다) |
   | `anthropic.claude-sonnet-5` | `offer-2ykemehpsyf7g` | `APN2_*_standard` | 2.2 / 11 |
   | `anthropic.claude-sonnet-5-5` | `offer-5fu2rhus3byrs` | `APN2_*_global_standard` | 2 / 10 (`APN2_*_standard`는 없다) |
   | `openai.gpt-6.1-sol` | `offer-wbhj4kycntgkk` | `*_standard` / `*_global_standard` | 2.2 / 11, 2 / 10 |

   **GPT-6.1 Sol offer의 긴 컨텍스트 이상값**: `output_tokens_long_ctx_standard` 2.2와 `output_tokens_long_ctx_global_standard` 2가
   짧은 컨텍스트 출력(11 / 10)보다 낮다. 같은 offer의 flex 긴 컨텍스트 출력은 16.5 / 15이고, OpenAI 요금 문서의 `gpt-6.1-sol` 긴 컨텍스트
   출력은 15다. 긴 컨텍스트 입력(4.4 / 4)은 짧은 컨텍스트 입력의 2배로 정상이다. 출처 데이터 오류로 본다.
   Anthropic 문서 "Claude Sonnet 5.5"(2 / 10, 캐시 읽기 0.2, 5분 쓰기 2.5, 1시간 쓰기 4)와 OpenAI 문서 `gpt-6.1-sol`(2 / 10, 캐시 읽기 0.1,
   긴 컨텍스트 4 / 15) 행은 모델 이름 정확 일치로 확인했다.

4. **GPT on AWS 벤치 사이클 시간**: v2.31.2(18채널을 한 줄로 순차 측정) 2026-09-30 24시간 실측은 96사이클, 중앙값 623초,
   p90 750초, 최대 790초이고 9사이클이 데드라인(780초)에 걸려 끝 채널을 건너뛰었다. 같은 방식으로 21채널을 돌리면 p50 약 760초,
   p90 약 855초로 추정돼 사이클의 30~50%에서 GPT 6.1 Sol 카드가 빈다.

## Options

### 서울 in-region 채널 키

- **(a) `bedrock:<aws-region>:<Bedrock FM id>` — 채택.** `openai:<region>:<id>`(ADR-019)와 같은 모양이고 리전이 키에 있다.
  `split(":", 2)`로 나누므로 FM id 안의 `:`(`…-v1:0`)는 보존된다. 첫 `:` 앞(`bedrock`)이 채널 키라 `probe_cadence`와 프런트
  `channelKey`가 코드 변경 없이 기본 주기를 쓴다.
- (b) 평문 `anthropic.claude-opus-5` — 기각. 키에 리전이 없어 `_REGION_MAP`이 us-east-1로 폴백하고, us-east-1이 온디맨드를 지원하면
  잘못된 리전을 서울 라벨로 조용히 측정한다. Mantle과 `/claude-features`가 쓰는 FM id와 구분되지 않고, `price_identity`의
  `partition(".")` 분류도 깨진다.
- (c) 가짜 접두 `apne2.` — 기각. 실제 추론 프로파일(`global.`, `us.`)처럼 보여 혼동을 부른다.

### 21채널 벤치 데드라인

- (a) 순차 유지, 컷 감수(계획 기본값) — 기각(2026-09-30 사용자 결정).
- (b) `GPT_BENCH_RUNS=8`(약 −125초) — 기각. 전 채널의 표본 수, 즉 방법론이 바뀐다.
- (c) 스케줄 20분 — 기각. `STALE_AFTER_MS`, `_CYCLE_COMPLETE_AFTER`, UI "15분마다" 문구를 함께 바꿔야 한다.
- (d) 데드라인 상향 — 불가. 15분 스케줄과 겹친다.
- **(e) 호스트별 두 갈래 병렬 — 채택(사용자 결정 2026-09-30).**

### 긴 컨텍스트 이상값

- (a) 그대로 저장 — 기각. `/pricing`이 짧은 컨텍스트보다 싼 긴 컨텍스트 단가를 보여 준다.
- (b) 관측 전체 거부(`skipped:parse_failed`) — 기각. 짧은 컨텍스트 입력, 출력, 캐시 단가는 정상이다.
- **(c) 그 관측의 long_* 4필드만 버리고 WARNING 로그 — 채택.**
- (d) 화면 고정 안내 추가 — 채택하지 않음. 골든 Markdown과 CSV, 안내 번호, `PricingPanel` NOTES, e2e 안내 9개 고정이 모두 바뀐다.

## Decision

1. **Bedrock 서울 In-Region 채널 2개** — `bedrock:ap-northeast-2:anthropic.claude-opus-5` → `Bedrock Claude Opus 5 (ap-northeast-2)`,
   `bedrock:ap-northeast-2:anthropic.claude-sonnet-5` → `Bedrock Claude Sonnet 5 (ap-northeast-2)`(`AVAILABLE_MODELS` 정적 등록, US 블록 뒤,
   Nova 앞). 라벨 괄호는 OpenAI 인리전처럼 소문자 리전 코드다.
   - `prober.BEDROCK_INREGION_PREFIX = "bedrock:"`, `_is_bedrock_inregion()`, `_bedrock_target(model_id) -> (client 리전, 호출용 modelId)`.
     `bedrock:<r>:<id>` → `(r, id)`, `global.*`/`us.*` → `(_REGION_MAP[접두], model_id)`, 그 밖의 키와 깨진 `bedrock:` 키 → `("us-east-1",
     model_id)`. 예외를 던지지 않는다(제출 루프에서 던지면 사이클 전체가 failed가 된다). `_get_region_for_model`은 이름을 유지하고
     `_bedrock_target(...)[0]`을 돌려준다(auto_prober, stream_probe_events, 테스트 monkeypatch가 쓴다).
   - 리전과 modelId를 **한 커밋에** 고치고 테스트로 고정했다. 리전만 고치면 키 문자열이 modelId로 가서 ValidationException이 나고,
     modelId만 고치면 us-east-1에서 FM id를 호출한다.
   - `ProbeResult.model_id`, SSE 이벤트, `ParityResult.model_id`에는 키를 그대로 기록한다. 대시보드 수동 프로브와 Comparison Lab은
     접두를 벗긴 FM id를 보낸다. OptimizePrompt 대상도 FM id로 정규화한다.
   - temperature 억제는 `_REASONING_MODEL_PATTERNS`의 `"opus-5"`, `"sonnet-5"`가 substring으로 키 전체에 걸려 그대로 동작한다. forced
     `tool_choice`는 서울에서 200이라 유지한다.
   - 정렬과 분석 채널: 프런트 `channelRank`가 소문자 AWS 리전 서픽스(`/\([a-z]{2}(?:-[a-z]+)+-\d+\)$/`)를 rank 3(Bedrock US 뒤)으로 둔다.
     `routers/reliability._parse_label`은 괄호가 리전 코드(`_AWS_REGION_RE`)면 `"Bedrock <region>"`, `routers/cost._channel`은
     `bedrock:<region>:*`를 `f"Bedrock {region}"`(깨진 키는 `"Other"`)로 분류한다. 채널 이름은 `Bedrock ap-northeast-2`이고
     `ReliabilityPanel.CHANNEL_BG`, `CostDashboardPanel.CHANNEL_COLORS`가 같은 키를 쓴다. 과거의 비정형 Bedrock 라벨은 지금처럼
     `Bedrock US`에 남는다.
   - 단가 채널 `inregion:ap-northeast-2`(`pricing_sources._BEDROCK_INREGION_REGIONS`, 파서의 APN2 리전 코드, offer `APN2_*_standard`).
     서울 in-region은 기존 Opus 5, Sonnet 5 offer를 재사용하므로 offer 호출이 늘지 않는다(Global, US 채널과 한 호출).
   - 패리티는 converse + invoke_model만 돈다(`parity/catalog.surfaces_for`). `messages_mantle`은 us-east-1에 같은 FM id를 보내므로 Global
     행과 똑같은 호출이고 서울 측정도 아니다. 패리티 runner `_execute`도 `_bedrock_target`으로 리전과 FM id를 푼다.
   - env는 없다(리전이 키에 있다). IAM은 바뀌지 않는다 — backend와 스케줄 태스크 역할 모두 `arn:aws:bedrock:*::foundation-model/*`를
     허용한다. 리전별로 좁히면 이 채널이 깨진다.
   - Model Explorer: 7번째 키 스킴(type `bedrock`, 라벨 `Bedrock (In-Region, <region>)`, 엔드포인트
     `https://bedrock-runtime.<region>.amazonaws.com`), 코드 예제와 콘솔 링크가 키의 리전을 쓴다. 카드 배지는 `ChannelInfo.badge`
     (`In-Region`)다.

2. **Claude Sonnet 5.5 — 2채널** (Global + CP):
   - `global.anthropic.claude-sonnet-5-5` → `Bedrock Claude Sonnet 5.5 (Global)`(`global.anthropic.claude-sonnet-5` 바로 앞).
   - `anthropic:claude-sonnet-5-5` → `Anthropic Claude Sonnet 5.5 (US)`. `_ANTHROPIC_TARGETS`에 `("sonnet-5-5", …)`를 `("sonnet-5", …)`
     바로 앞에 두고, `pricing_sources._CP_TARGETS`도 같은 순서다(pytest가 두 목록을 대조한다). CP `/v1/models`가 `claude-sonnet-5-5`를
     먼저 돌려줘도 ADR-028의 점 버전 가드가 Sonnet 5 오등록을 막는다. 타깃이 없던 상태에서는 5.5가 등록되지 않을 뿐이다(fail-closed).
   - US 채널과 서울 in-region 채널은 두지 않는다(프로파일 없음, 추론 프로파일 전용).
   - 패리티 `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"sonnet-5-5"`를 넣는다(V1). `"sonnet-5"`는 넣지 않는다 — substring이라 Sonnet 5 채널
     전부가 auto로 바뀐다. V2는 Sonnet 5와 동작이 같아 바꿀 것이 없다.
   - `FAMILY_ORDER`에서 `"Claude Sonnet 5.5"`는 `"Claude Sonnet 5"`보다 앞이다(`includes` 매칭). 백엔드 튜플과 프런트 배열은 바이트 단위로
     같다(21개, pytest).
   - `/prompts` OptimizePrompt 대상에 `Bedrock Claude Sonnet 5.5 (Global)`을 둔다(V13).
   - 단가 $2 / $10(Global offer, CP는 Anthropic 문서).

3. **GPT-6.1 Sol — 3채널**: `prober._OPENAI_MODEL_SPECS`의 첫 항목 `("BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", "GPT 6.1 Sol", ("global", "us",
   "us-east-1"))`.

   | 키 | 라벨 |
   |----|------|
   | `openai:global:global.openai.gpt-6.1-sol` | `OpenAI GPT 6.1 Sol (Global)` |
   | `openai:us:us.openai.gpt-6.1-sol` | `OpenAI GPT 6.1 Sol (US)` |
   | `openai:us-east-1:openai.gpt-6.1-sol` | `OpenAI GPT 6.1 Sol (us-east-1)` |

   - env는 `BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID=openai.gpt-6.1-sol` 하나다. AppServices `backendEnv`와 Scheduler `buildTaskDef` 공용
     environment(스케줄 태스크 전부)에 넣고 두 스택을 모두 배포한다(CDK jest 85 → 87). 빠지면 prober와 gptbench가 3채널을 조용히 건너뛴다.
     Global, US base URL은 기존 `OPENAI_GLOBAL_BASE_URL`, `OPENAI_US_BASE_URL`을 재사용한다(ADR-027).
   - Mantle us-east-2, us-west-2는 404라 스펙에 넣지 않는다(ADR-027, ADR-028과 같은 판단). 1P 스펙은 추가하지 않는다.
   - `reasoning_tokens`가 0이라 패리티 `_REASONING_MARKERS`에 넣지 않는다(`gpt-6` 미포함 규칙 그대로).
   - `FAMILY_ORDER`에서 `"GPT 6.1 Sol"`은 `"GPT 6 Astra"` 앞이다. `"GPT 6 Sol"`은 `"GPT 6.1 Sol"`의 부분 문자열이 아니라 충돌이 없다.
   - 단가: in-region(us-east-1)과 US CRIS $2.20 / $11, Global $2 / $10. OpenAI 공식 가격 `openai-list:gpt-6.1-sol` $2 / $10(긴 컨텍스트 4 / 15).

4. **`pricing_sync._plausible_long`** — 긴 컨텍스트 입력이나 출력이 짧은 컨텍스트 단가보다 낮으면(`_implausible_long`) 그 관측의 long_*
   4필드를 None으로 만들고 WARNING 한 줄(`pricing sync: <where>: long-context price below the short-context price, long prices dropped`)을
   남긴다. run errors에는 넣지 않는다. offer 경로와 문서 경로 모두 적용한다. 비교는 None 필드를 무시하므로 저장된 long 값은 그대로
   남고, 없던 값은 계속 없다. 같은 값은 정상으로 본다. seed도 GPT-6.1 Sol Bedrock 3채널의 긴 컨텍스트를 None으로 둔다.

5. **GPT on AWS 벤치 21채널, 두 갈래 병렬** (`backend/gptbench.py`):
   - 갈래 `cris` = 유사 리전 `global`, `us` 채널 9개(bedrock-runtime OpenAI 호환 호스트), 갈래 `mantle` = 인리전 채널 12개
     (`bedrock-mantle.<region>` 호스트). 두 갈래는 동시에 돌고, 갈래 안은 `_BENCH_SPECS` 순서대로 채널 하나씩 순차다(워밍업 1 +
     `GPT_BENCH_RUNS`회). 같은 호스트 호출을 겹치지 않으므로 측정 방법과 요청 형태는 바뀌지 않는다.
   - GPT 6.1 Sol은 `_BENCH_SPECS`의 마지막 항목이라 두 갈래 각각의 끝이다. 데드라인 컷은 갈래마다 신규 채널부터 떨어진다.
   - 사이클 데드라인 `GPT_BENCH_DEADLINE`(780초)은 두 갈래가 공유하는 같은 시각이고, 넘긴 갈래는 자기 남은 채널만 건너뛴다(기존 skip 표기
     `라벨`, `라벨 (run N+)`). `skipped_channels`는 채널 순서로 보고한다.
   - 갈래는 DB를 만지지 않는다. 진행을 회차(run) 단위 이벤트(start, run, done, exit)로 큐에 넘기고, 메인 스레드가 진행 중 채널의 회차를 모아 채널 단위로 저장하고 커밋한다. OpenAI 클라이언트 캐시는 잠금으로
     보호한다.
   - 데드라인 + 호출 상한 + `LANE_JOIN_GRACE_S`(15초) = 기본 885초가 지나도 끝나지 않는 갈래는 기다리지 않는다(15분 스케줄 안). 메인 스레드는
     이미 큐에 도착한 진행을 모두 저장하고, 갈래는 회차마다 진행을 보고하므로 진행 중 채널은 끝난 회차를 저장해 `라벨 (run N+)`, 시작하지 못한
     채널은 `라벨`로 보고한다. 예외로 멈춘 갈래의 진행 중 채널도 같다. 여유 15초는 최선의 상한이다 — watchdog은 스트림이 붙은 뒤에만 끊을 수
     있어 연결, 요청 쓰기, 응답 헤더 대기 구간은 클라이언트 timeout이 상한이다. 예외로 멈춘 갈래가 있으면 다른 갈래를 끝까지 저장하고 사이클 로그를 남긴 뒤 그 예외를 다시 던진다.
   - 로그: `GPT bench lanes: cris=9 mantle=12`, 갈래마다 `GPT bench lane done: <lane> channels=N elapsed=Ns`. 행, 요약, 기존 로그 형식은
     그대로다.
   - `/api/gptbench/latest`의 완료 판정(시작 후 14분, `_CYCLE_COMPLETE_AFTER`)은 바꾸지 않는다. 15분으로 늘리면 화면에 보이는 사이클
     나이가 최대 "15분 + 15분 + 기동 지연"이 되어 프런트 `STALE_AFTER_MS`(30분)를 넘는 순간이 사이클마다 생긴다.
   - `routers/gptbench.fam_rank`는 GPT 6.1 Sol이 0이다. 프런트 `GptOnAwsPanel`은 "GPT 6.x 세대" 그룹 첫 열에 GPT 6.1 Sol을 두고 선 패턴
     `"16 4 4 4"`(7개 모두 다름)를 쓴다.

6. **`/claude-features` 6번째 대표 모델 Sonnet 5.5** (`sonnet-5` 앞, 카탈로그 `MODELS` 순서 `fable-5-1, fable-5, opus-5-5, opus-5, sonnet-5-5,
   sonnet-5`) — `mantle: None`(V3 404), 사유 `mantle_reason`(KO)과 `mantle_reason_en`(EN)을 카탈로그가 싣고 프런트가 그대로 표시한다
   (이전의 US GovCloud 하드코딩 제거). 런 형태가 바뀌므로 `CATALOG_VERSION`을 `2026-09-30`으로 범프했다. 자세히는 ADR-026 v2.32.0 부록.

7. **하지 않은 것**: 인사이트와 챗봇 프롬프트 해설 갱신(LLM 출력이 바뀐다), `/claude-features` 서울 in-region 변형(런 형태와 카탈로그
   버전이 바뀐다), Model Explorer의 기존 `us.*` 예제 리전 표기 정정(범위 밖, in-region 키에만 키의 리전을 쓴다), 긴 컨텍스트 이상값
   고정 안내.

## Consequences

- 수치(전 → 후):

  | 항목 | 전 | 후 |
  |------|----|----|
  | 활성 채널(`expected_model_count`) | 55 | **62** |
  | 카탈로그(1P 휴면 5 포함) | 60 | 67 |
  | Bedrock 채널 | 21 | 24 (Global 11 + US 11(Nova 포함) + 서울 in-region 2) |
  | Claude Platform on AWS 채널 | 9 | 10 |
  | OpenAI 채널 | 25 | 28 (Mantle 인리전 17 + Global CRIS 7 + US CRIS 4) |
  | 단가 활성 채널(+ openai-list) | 63 (55 + 8) | 71 (62 + 9) |
  | `SEED` / `CP_SEED` / `OPENAI_LIST_SEED` | 46 / 9 / 8 | 52 / 10 / 9 |
  | offer FM / `/api/pricing` references | 18 / 21 | 20 / 23 |
  | `ANTHROPIC_DOC_NAMES` / `FAMILY_ORDER` | 9 / 19 | 10 / 21 |
  | GPT 벤치 채널 | 18 (Mantle 11 + CRIS 7) | 21 (Mantle 12 + CRIS 9 = Global 5 + US 4) |
  | Claude API Features 대표 모델 / 셀 | 5 / 975 (813 + 162) | 6 / 1170 (946 + 224) |
  | `CATALOG_VERSION` | `2026-09-23` | `2026-09-30` |
  | CP 호출/시간(기본 300) | 108 | 120 (600이면 54 → 60) |
  | AutoProber 행/사이클(600 모드) | 55 (46/55) | 62 (52/62) |
  | CDK jest | 85 | 87 |

- (+) Opus 5와 Sonnet 5를 Bedrock Global, Bedrock US, CP, 서울 in-region 네 경로로 비교할 수 있다. 서울 in-region은 CRIS 라우팅이 없는
  서울 리전 자체의 응답 속도와 성공률이다.
- (+) 채널 키에 리전이 들어가 리전 오라우팅이 구조적으로 막힌다. 다른 리전의 온디맨드 FM도 `AVAILABLE_MODELS` 한 줄과 단가 분류
  (`_BEDROCK_INREGION_REGIONS`)로 추가할 수 있다.
- (+) 두 갈래 병렬로 벤치 사이클이 대략 절반으로 줄어들 것으로 예상하고, 21채널에서도 데드라인 컷이 드물 것으로 본다(배포 뒤 24시간
  `/ecs/gptbench` `skipped=` 빈도로 확인).
- (+) offer의 긴 컨텍스트 이상값이 `/pricing`에 드러나지 않는다.
- (−) **Sonnet 5.5 Mantle `None`은 서빙 시작을 감지하지 못한다.** Fable 5.1(GovCloud 전용)과 달리 온보딩 미완일 수 있으므로 Mantle
  us-east-1 `/anthropic`을 수동으로 다시 확인한다(ADR-026 부록).
- (−) `_plausible_long`은 로그만 남긴다. AWS가 요금표를 고치면 다음 동기화에서 long_*가 50% 게이트 없이 `enriched`로 채워지고, 기존
  패밀리의 long 값이 나중에 이상값이 되면 옛 값이 그대로 남는다(신호는 WARNING 로그뿐).
- (−) env 누락이면 채널이 조용히 사라진다. 이미지만 배포하거나 한쪽 스택만 배포하면 GPT-6.1 Sol 3채널이 오류 없이 빠진다.
- (−) 비용: CP 호출 시간당 108 → 120회(월간 사용량 상한 재발 시 `ANTHROPIC_CP_PROBE_INTERVAL_S=600`, AutoProber와 backend 둘 다). GPT 벤치
  GPT-6.1 Sol 3채널 × 11호출 × 96사이클 = 3,168호출/일, 호출당 입력 약 55.8k 토큰은 대부분 캐시 히트라 캐시 읽기 단가($0.11, Global
  $0.10)로 약 $20/일이다. `/claude-features` 런은 약 9분에서 약 11분이 되고, 배포 뒤 첫 런의 변경 배너에 catalog 195건(Sonnet 5.5 셀)이 한 번
  뜬다. 패리티 12시간 스윕에 Sonnet 5.5 Global(3 surface), Sonnet 5.5 CP(1), 서울 2행(각 2), GPT-6.1 Sol 3행(각 2) 셀이 더해진다.
- (−) AutoProber 사이클당 7행이 늘어난다(worker 3, DB 풀 5 + 5). 배포 뒤 `/ecs/autoprober` 사이클 소요가 300초에 가까우면
  `CycleAlreadyRunning` 위험이 있다.
- 배포 검증은 `docs/runbooks/deploy.md` §5-6(`/api/models` 62, 새 7개 model_id와 라벨, `/api/pricing` 71채널 동기화와 references 23,
  GPT-6.1 Sol Bedrock 셀 `long` null, `/api/gptbench/latest` 21채널, FeaturesVerify 1170셀)을 따른다.
