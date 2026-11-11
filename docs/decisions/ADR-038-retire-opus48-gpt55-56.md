# ADR-038: Claude Opus 4.8, GPT 5.5와 GPT 5.6(Sol, Terra, Luna) 모니터링 제외

- **Status**: Accepted
- **Date**: 2026-11-10
- **Related**: ADR-020 (OpenAI 1P direct, 휴면), ADR-030 (단가 자동 동기화), ADR-031 (호스트별 벤치 갈래), ADR-033 (Mantle 인리전 us-east-1 일원화), ADR-034 (Claude 4.x, GPT 5.4 제외 — 같은 절차), ADR-035 (단가 변경 목록), ADR-037 (Claude Fable 5 제외), v2.43.0

## Context

사용자 지시(2026-11-10, v2.42.0 배포 직후): "fable 5.0, opus 4.8, gpt 5.5, gpt 5.6 을 deprecate 합니다."
Claude Fable 5는 같은 날 v2.42.0에서 이미 뺐으므로(ADR-037) 이번 범위는 나머지 셋이다. "gpt 5.6"은 GPT-5.6 세대 세 모델 모두(Sol, Terra, Luna)로 읽었다.

v2.42.0 카탈로그에서 이 패밀리들은 활성 10채널이었다.

| 패밀리 | 채널 |
| --- | --- |
| Claude Opus 4.8 | Bedrock Global `global.anthropic.claude-opus-4-8`, Bedrock US `us.anthropic.claude-opus-4-8`, Claude Platform on AWS `anthropic:claude-opus-4-8` |
| GPT 5.6 Sol, Terra, Luna | Global CRIS `openai:global:global.openai.gpt-5.6-*`, Mantle `openai:us-east-1:openai.gpt-5.6-*` (모델마다 2채널) |
| GPT 5.5 | Mantle `openai:us-east-1:openai.gpt-5.5` |

함께 걸린 것: GPT on AWS 벤치의 GPT 5.6 Terra(Global, us-east-1)와 GPT 5.5(us-east-1) 3채널(그래서 `/gpt-on-aws`의 GPT 5.x 세대 묶음 전체),
OpenAI 공식 가격 채널 4개(`openai-list:gpt-5.6-sol`, `-terra`, `-luna`, `openai-list:gpt-5.5`), GPT-5.6 Sol 프로모션 메모(`PRICE_NOTES` `promo`),
CDK의 모델 id env, 그리고 휴면 1P 스펙 4개 전부(GPT 5.5, 5.6 Sol, Terra, Luna).

2026-11-10 `aws bedrock list-foundation-models`로 확인했을 때 서울과 us-east-1 모두에서 `anthropic.claude-opus-4-8`, `openai.gpt-5.5`,
`openai.gpt-5.6-sol`, `openai.gpt-5.6-terra`, `openai.gpt-5.6-luna`가 ACTIVE다. 그래서 이 결정은 플랫폼의 지원 종료가 아니라 모니터링 범위 결정이다
(ADR-037의 Fable 5와 같다).

## Decision

1. **카탈로그에서 뺀다(ADR-034, ADR-037과 같은 방식)** — `prober.AVAILABLE_MODELS`의 Opus 4.8 Global, US, `_ANTHROPIC_TARGETS`의 `opus-4-8`
   (`pricing_sources._CP_TARGETS`가 같은 순서로 따른다 — CP가 아직 서빙하는 `claude-opus-4-8`은 어느 타깃에도 걸리지 않아 등록되지 않는다),
   `_OPENAI_MODEL_SPECS`의 GPT 5.6 Sol, Terra, Luna와 GPT 5.5, `_OPENAI_1P_MODEL_SPECS`의 같은 네 모델(목록이 빈다 — 1P 경로와 CDK
   `ENABLE_OPENAI_1P=false`는 남는다), `gptbench._BENCH_SPECS`의 GPT 5.5, GPT 5.6 Terra와 `routers/gptbench.py` `fam_rank`, 단가의 출처 분류와 seed
   (`pricing_sources`, `pricing_seed` — Bedrock offer, CP 문서 이름, OpenAI offer, OpenAI 공식 가격, 캐시와 긴 컨텍스트 seed), GPT-5.6 Sol 프로모션 메모,
   화면 목록(`FAMILY_ORDER` 18 → 13, `TrendChart` 색과 대체 색 — 수집을 멈춘 us-east-2, us-west-2와 1P 라벨까지, `StreamingView` 분기와 색, `/prompts`의
   Opus 4.8 Global, US 대상, `GptOnAwsPanel`의 GPT 5.x 세대 묶음과 선 패턴).
2. **CDK에서 모델 id env를 뺀다** — `BEDROCK_OPENAI_GPT_55_MODEL_ID`, `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`와 휴면
   `OPENAI_1P_GPT_55_MODEL_ID`, `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`를 AppServices `backendEnv`와 Scheduler `buildTaskDef`에서 지웠다
   (jest가 없음을 고정한다). 그래서 이미지-only가 아니라 digest 고정 CDK로 두 스택을 배포한다.
3. **행은 지우지 않고 숨긴다** — backend `visibility._DEFAULT_HIDDEN`에 `Claude Opus 4.8`, `GPT 5.6`, `GPT 5.5`를, 프런트 `EXCLUDED_FAMILIES`에
   `Opus 4.8`, `GPT 5.6`, `GPT 5.5`를 더했다. 남은 39채널의 라벨과 `FAMILY_ORDER` 13개 어느 것도 이 패턴에 걸리지 않는다(GPT는 6.x 세대만 남는다 —
   `tests/test_retire_opus48_gpt55_56.py`, `sortModels.test.ts`가 고정). 숨김은 기존과 같은 모든 조회(결과, 신뢰성, 효율성, 비용, 분석, auto-probe,
   인사이트 잡, 챗봇 도구, 단가 활성 집합, GPT on AWS 벤치, 패리티)에 걸린다.
4. **단가 안내 문구** — 긴 컨텍스트 안내의 예시 "(GPT 5.5는 272K)" / "(272K for GPT 5.5)"를 뺐다. OpenAI 요금 문서는 GPT 6.x 행에 짧은 컨텍스트 한도를
   적지 않는다. 화면(`PricingPanel.tsx`)과 내보내기(`pricing_export.py`)가 같은 문장을 쓴다.
5. **테스트 데이터** — 2026-09-27 출처 fixture와 내보내기 골든은 GPT 5.5, 5.6 행을 담고 있다. v2.39.0처럼 패밀리 이름을 한 칸씩 당길 남은 GPT 5.x가
   없어서, 테스트 도우미 `backend/tests/_legacy_families.py`가 단가 메커니즘 테스트(sync, payload, export, router) 하나 동안만 빠진 패밀리를 v2.42.0 표대로
   다시 분류한다. 덕분에 fixture와 골든의 숫자, 각주 번호가 그대로다. 운영 seed 기반 테스트는 실제 카탈로그를 따른다. `/pricing` e2e 가짜 데이터의
   GPT 5.6 Sol, GPT 5.5도 그대로 둔다(화면 렌더링만 시험하고, 바꾸면 각주 번호를 다시 매겨야 한다).

## Alternatives

- **행을 지운다(2026-05-20 Opus 4.5, Sonnet 4.5 방식)** — 되돌릴 수 없고, 비용과 신뢰성의 과거 계산 근거가 사라진다. 기각.
- **GPT on AWS의 GPT 5.x 세대 묶음을 기록으로 남긴다** — 지시가 "deprecate"이고 v2.39.0의 "화면 메뉴들에서도 제거"와 같은 범위로 읽었다. 메뉴에서
  지운다. 지난 벤치 행은 저장소에 남는다.
- **패턴을 "GPT 5"로 묶는다** — GPT 5.4(v2.39.0)까지 한 번에 덮지만, 앞으로 다시 들일 수 있는 GPT 5.x 점 버전을 미리 숨긴다. 패밀리 이름 그대로
  `GPT 5.6`, `GPT 5.5`로 둔다.
- **1P 경로를 지운다** — 휴면 스펙이 비었지만 경로 자체(ADR-020)는 새 모델로 다시 쓸 수 있다. 코드와 `ENABLE_OPENAI_1P` 스위치는 남긴다.

## Consequences

- 활성 49 → 39(Bedrock 19 → 17 = Global 7 + Nova 포함 US 8 + 서울 in-region 2, CP 8 → 7, OpenAI 22 → 15 = Mantle us-east-1 5 + Global 5 + US 5).
  카탈로그도 39다(휴면 1P 스펙 없음). `FAMILY_ORDER` 13, 약정 오퍼 FM 17 → 12, `/pricing` 참고 자료 20 → 15(약정 오퍼 12), OpenAI 공식 가격 9 → 5,
  PricingSync 로그 `44 active channels`, 시간당 CP 호출 96 → 84회, `/prompts` Bedrock 대상 17 → 15, 모델 탐색 예제 85 → 71.
- GPT on AWS 벤치 18 → 15채널(Mantle us-east-1 5 + CRIS 10), 로그 `GPT bench lanes: cris=10 mantle-us-east-1=5`, 사이클당 150행. `/gpt-on-aws`는 GPT 6.x
  세대 묶음 하나만 보인다.
- Claude API Features는 그대로다(1365셀 — 대표 모델이 아니다).
- 배포 뒤 첫 PricingSync는 이 채널들이 있던 스냅샷과 비교하므로 `/pricing` 변경 목록에 채널 제외 14건(10채널 + OpenAI 공식 가격 4)이 한 번 나온다.
  `price_history` 행은 남는다.
- `prober._REASONING_MODEL_PATTERNS`의 `"opus-4-8"`과 패리티 `_REASONING_MARKERS`의 `"gpt-5"`는 모델 동작 기록이라 남긴다. Mantle `ap-northeast-1`이
  `/anthropic`에서 Opus 4.8만 서빙했다는 2026-09-05 실측 기록도 남긴다.
- 다시 노출하려면 카탈로그(`prober`, `gptbench`, `pricing_sources`, `pricing_seed`)와 CDK env를 되살리고, 세 숨김 패턴과 프런트 `EXCLUDED_FAMILIES` 항목을
  지운다. 1P를 다시 노출할 때는 새 모델의 1P 스펙과 1P 단가 출처부터 만든다(ADR-020, ADR-030).
- 롤백 지점은 v2.42.0 이미지 `vd626eb9`다. 되돌리면 10채널과 env가 다시 생기고 저장 행이 다시 보인다.
