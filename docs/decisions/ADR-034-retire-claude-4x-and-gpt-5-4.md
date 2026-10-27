# ADR-034: Claude Opus 4.7, Opus 4.6, Sonnet 4.6, Haiku 4.5와 GPT 5.4 모니터링 제외

- **Status**: Accepted
- **Date**: 2026-10-27
- **Related**: ADR-017 (Opus 4.5, Sonnet 4.5 제외), ADR-019 (Bedrock Mantle 경로), ADR-020 (OpenAI 1P direct, 휴면), ADR-030 (단가 자동 동기화), ADR-031 (호스트별 벤치 갈래), ADR-033 (Mantle 인리전 us-east-1 일원화), v2.39.0

## Context

사용자 지시(2026-10-27, v2.38.0 배포 직후 두 메시지): "opus 4.6, 4.7, sonnet 4.6, haiku 4.5 , gpt 5.4 계열은 더이상 모니터링하지 않습니다."
이어서 "화면 메뉴들에서도 제거합니다."

v2.38.0 카탈로그에서 이 다섯 패밀리는 활성 12채널이었다.

| 패밀리 | 채널 |
| --- | --- |
| Claude Opus 4.7 | Bedrock Global, Bedrock US, Claude Platform on AWS |
| Claude Opus 4.6 | Bedrock Global, Bedrock US (CP 채널 없음) |
| Claude Sonnet 4.6 | Bedrock Global, Bedrock US, Claude Platform on AWS |
| Claude Haiku 4.5 | Bedrock Global, Bedrock US, Claude Platform on AWS |
| GPT 5.4 | Mantle us-east-1 (us-east-2, us-west-2는 v2.38.0에 이미 제외), 휴면 1P 스펙 |

수집만 멈추면 저장된 측정이 신뢰성(7일), 비용(30일), 효율성, 분석, 이력, AI 인사이트, 챗봇, GPT on AWS 추세(7일), 패리티 매트릭스(다음
12시간 런까지)에 기간이 지날 때까지 남는다. 둘째 지시는 그 화면들에서도 바로 지우라는 뜻이다. 앞선 사례는 둘이다.

- 2026-05-20 Opus 4.5, Sonnet 4.5 제외: 기동 마이그레이션이 `probe_results` 행을 DELETE했고, 프런트 `EXCLUDED_FAMILIES`가 이중 방어였다.
- 2026-07-31 OpenAI 1P 비노출(v2.19.1): 행은 남기고 backend `visibility.py` 숨김 패턴 `(1P)`과 프런트 `EXCLUDED_FAMILIES`로 가렸다.

## Decision

1. **카탈로그에서 뺀다** — `prober.AVAILABLE_MODELS`의 Bedrock 8개(`global.`, `us.` × `anthropic.claude-opus-4-7`, `-opus-4-6-v1`, `-sonnet-4-6`,
   `-haiku-4-5-20251001-v1:0`), `_ANTHROPIC_TARGETS`의 `opus-4-7`, `sonnet-4-6`, `haiku-4-5`(`pricing_sources._CP_TARGETS`가 같은 순서로 따른다),
   `_OPENAI_MODEL_SPECS`와 `_OPENAI_1P_MODEL_SPECS`의 GPT 5.4, `gptbench._BENCH_SPECS`의 GPT 5.4. 활성 61 → 49(Bedrock 27 → 19 = Global 8 + US 9 +
   서울 in-region 2, CP 11 → 8, OpenAI 23 → 22 = Mantle us-east-1 9 + Global 8 + US 5), 카탈로그 66 → 53(휴면 1P 5 → 4).
2. **행은 지우지 않고 숨긴다(1P 방식)** — backend `visibility._DEFAULT_HIDDEN`을
   `(1P),Claude Opus 4.7,Claude Opus 4.6,Claude Sonnet 4.6,Claude Haiku 4.5,GPT 5.4`로 넓혔다. 이 기본값을 이미 쓰던 조회(결과, 신뢰성, 효율성,
   비용, 분석, auto-probe, 인사이트 잡, 챗봇 도구, 단가 활성 집합)에 더해 `routers/gptbench.py`의 `/latest`, `/trend`와 `routers/parity.py`의
   `/latest`(현재 런 셀 — 직전 런에만 있는 셀은 `diff_statuses`가 원래 무시한다)에도 `visible_only`를 건다. 프런트 `EXCLUDED_FAMILIES`에
   `Opus 4.7`, `Opus 4.6`, `Sonnet 4.6`, `Haiku 4.5`, `GPT 5.4`를 더했다. 활성 49채널의 라벨과 `FAMILY_ORDER` 18개는 이 패턴에 걸리지 않는다
   (`tests/test_visibility.py`, `sortModels.test.ts`가 고정). env `HIDDEN_MODEL_PATTERNS`는 기본값 전체를 대신하므로 1P만 다시 보이려면
   나머지 다섯 패턴을 그대로 적는다.
3. **화면 목록에서 뺀다** — `FAMILY_ORDER` 23 → 18(백엔드 `pricing_sources`와 프런트 `sortModels` 바이트 동일), `TrendChart` `MODEL_COLORS`와
   `FAMILY_FALLBACK`의 다섯 패밀리 색(GPT 5.4 us-east-2, us-west-2, 1P 포함), `StreamingView` 색과 `extractModelName` 분기, `/prompts`
   OptimizePrompt 대상 8개(Bedrock 25 → 17), `/gpt-on-aws` `FAMILY_GROUPS` GPT 5.x 세대(5.6 Terra, 5.5 두 열), `FAMILY_DASH` 7종, `FAMILY_RE`.
   `/pricing`과 내보내기의 고정 안내 다섯째 줄은 "272K for GPT 5.5" / "(GPT 5.5는 272K)"다. 그 밖의 화면(대시보드 카드, 모델 탐색, 수동 프로브,
   신뢰성 등)은 `/api/models`와 숨김 필터를 따르므로 따로 고치지 않는다.
4. **단가** — `pricing_sources`의 `_BEDROCK_CLAUDE_FM`, `_OPENAI_FM`에서 빼 `price_identity`가 None이다. `pricing_seed`의 `SEED` 50 → 41(CP 제외),
   `CP_SEED` 11 → 8, `OPENAI_LIST_SEED` 10 → 9, 캐시와 확장 seed. 오퍼 FM 22 → 17, PricingSync 활성 71 → 58(로그 `58 active channels`),
   `/api/pricing` 패밀리 23 → 18, 모델 61 → 49, 참고 자료 25 → 20(오퍼 17). 운영 `price_history` 행은 지우지 않는다(지난 비용 계산에 쓰였다).
5. **벤치** — 19 → 18채널, `mantle-us-east-1` 8 → 7(GPT 5.4가 첫 채널이었다), 사이클당 190 → 180행, 로그 `GPT bench lanes: cris=11 mantle-us-east-1=7`.
   `routers/gptbench.fam_rank`에서 `GPT 5.4`를 뺐다. 갈래 동작 테스트는 계속 v2.37.x 네 갈래 스펙(`FOUR_LANE_SPECS`)으로 돈다.
6. **CDK** — `BEDROCK_OPENAI_GPT_54_MODEL_ID`와 `OPENAI_1P_GPT_54_MODEL_ID`를 AppServices `backendEnv`와 Scheduler `buildTaskDef`에서 뺐다(주석만
   남김). jest가 backend와 스케줄 작업 정의 6개에 두 env가 없음을 고정한다. IAM, DB 스키마 변경은 없다.
7. **모델 동작 기록은 남긴다** — `prober._REASONING_MODEL_PATTERNS`와 패리티 `_REASONING_MARKERS`의 `"opus-4-7"`은 카탈로그 소속이 아니라
   모델 동작(temperature 400, reasoning)의 기록이다. 남은 모델에는 영향이 없고, 다시 넣을 때 그대로 쓴다. `main.py` `_label_renames`도 그대로 둔다.

## Alternatives

- **2026-05-20처럼 행 삭제** — 기동 때 DELETE하면 즉시 사라지지만 되돌릴 수 없고, 비용과 신뢰성 이력의 근거가 없어진다. 숨김 패턴은 env 하나로
  되돌릴 수 있다. 기각.
- **수집만 멈추고 기간이 지나기를 기다림(v2.38.0 리전 제외 방식)** — 둘째 지시("화면 메뉴들에서도 제거")와 맞지 않는다. 기각.
- **CDK env를 남김** — 리전 base URL(ADR-033)과 달리 모델 id env는 읽는 스펙이 없어지면 쓰임이 없고, 남기면 왜 있는지 헷갈린다. 뺐다.
  이미지만 배포해도 남은 env는 읽히지 않아 해롭지 않다.
- **동작 패턴 정리** — `"opus-4-7"` 패턴을 지워도 결과는 같지만, 모델 동작 지식을 지우게 된다. 남겼다.

## Consequences

- AutoProber 한 사이클의 호출이 61 → 49회, CP 호출은 시간당 132 → 96회(8채널 × 12)로 준다. 벤치는 사이클당 19 → 18채널 × 11호출이다.
- 배포 직후 모든 화면에서 다섯 패밀리가 사라진다. 옛 리비전으로 시작한 마지막 AutoProber 회차(v2.38.0 배포 때 관찰)가 있어도 숨김 패턴이 가린다.
  배포 전에 만든 인사이트 본문에는 이름이 남을 수 있다.
- 새 패밀리 이름이 숨김 패턴을 포함하면 조용히 숨는다(예: 미래의 "GPT 5.45"). 활성 라벨과 `FAMILY_ORDER`를 검사하는 테스트가 그때 실패한다.
- 배포는 digest 고정 CDK로 AppServices, Scheduler 두 스택(§5-11). 롤백 지점은 v2.38.0(`v2d64a44`)이고, v2.38.0 tag의 `cdk/`로 되돌리면 다섯 패밀리가
  다시 등록되며 숨겼던 지난 행도 다시 보인다(제외 기간은 측정 공백).
- 테스트: backend 1,637개 통과(18개 건너뜀), vitest 388개, CDK jest 95개. 단가 골든 데이터셋(`tests/_pricing_dataset.py`)은 순서와 각주 번호를
  지키려고 패밀리 이름을 한 칸씩 당겼다(옛 GPT 5.5 행 → GPT 5.6 Luna, 옛 GPT 5.4 행 → GPT 5.5). e2e 단가 고정 데이터(`frontend/e2e/fixtures.ts`)에는
  GPT 5.5가 없어 GPT 5.4 행을 GPT 5.5로 바꿨다.
