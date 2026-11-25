# ADR-040: GPT 5.6(Sol, Terra, Luna) 모니터링 복귀

- **Status**: Accepted
- **Date**: 2026-11-25
- **Related**: ADR-038 (Claude Opus 4.8, GPT 5.5, GPT 5.6 제외 — 이 결정이 그중 GPT 5.6을 되돌린다), ADR-020 (OpenAI 1P direct, 휴면), ADR-025 (OpenAI Global CRIS), ADR-030 (단가 자동 동기화), ADR-031 (호스트별 벤치 갈래), ADR-033 (Mantle 인리전 us-east-1 일원화), ADR-039 (GPT 6.2 Astra, GPT 6.2 Sol), v2.45.0

## Context

사용자 요청(2026-11-25): "gpt 5.6을 다시 활성화해주세요."

GPT 5.6 Sol, Terra, Luna는 v2.43.0(2026-11-10, ADR-038)에 Claude Opus 4.8, GPT 5.5와 함께 모니터링에서 뺐다. 이번 요청은 그중 GPT 5.6만이다.
"다시 활성화"를 v2.42.x의 구성 그대로로 읽었다.

| 대상 | v2.42.x 구성 (되살리는 범위) |
| --- | --- |
| 대시보드 프로브 | 모델마다 Global CRIS `openai:global:global.openai.gpt-5.6-*`와 Mantle `openai:us-east-1:openai.gpt-5.6-*` — 6채널 |
| GPT on AWS 벤치 | GPT 5.6 Terra만 Global, us-east-1 — 2채널 (Sol, Luna는 처음부터 벤치 대상이 아니다) |
| 단가 | 오퍼 3개, OpenAI 공식 가격 `openai-list:gpt-5.6-sol`, `-terra`, `-luna`, GPT-5.6 Sol 프로모션 메모 |

2026-11-25 실측(호스트 IAM 자격의 단기 Bedrock 토큰, Responses API 스트리밍 — 운영 장기 키로는 호출하지 않았다):

- FM `openai.gpt-5.6-sol`, `-terra`, `-luna`는 서울과 us-east-1에서 ACTIVE이고 `INFERENCE_PROFILE` 전용이다. `global.` 프로파일은 두 리전 모두 ACTIVE다.
  us-east-1에는 `us.openai.gpt-5.6-*` 프로파일도 있다(v2.42.x에 재지 않던 경로).
- 여섯 채널 모두 첫 호출부터 200이다. 단건 TTFB/TTFT는 Sol Global 369/621ms, Mantle us-east-1 832/1106ms, Terra 391/575ms, 272/446ms,
  Luna 364/446ms, 274/370ms.
- 벤치 요청 형태(약 55.8k 토큰 고정 컨텍스트)로 GPT 5.6 Terra 두 채널 200, 둘째 호출 `cached_tokens` 55837.
- 오퍼는 v2.42.x seed와 같다. Sol `offer-gnqokrqqvdbgw`(In-Region $4.40/$22, Global $4/$20), Terra `offer-3dvyrx3okd4lq`($2.20/$13.20, $2/$12),
  Luna `offer-bklbyf2ewuawu`($0.22/$1.32, $0.20/$1.20). 캐시와 긴 컨텍스트 차원도 같다.
- OpenAI 요금 문서의 Standard 행도 같다(gpt-5.6-sol $4/$20, terra $2/$12, luna $0.20/$1.20). 프로모션 문장은 바뀌었다 — 2026-09-27에는
  "available at least through November 21, 2026"였고 2026-11-17 문서부터 "GPT-5.6 Sol's promotional pricing is available until November 30, 2026"다.
- 직전 24시간 벤치 갈래 소요는 `cris` 중앙값 381초(최대 539초), `mantle-us-east-1` 152초(최대 191초)다(데드라인 780초).

## Decision

1. **카탈로그에 되살린다** — `prober._OPENAI_MODEL_SPECS` 끝(GPT 6 Luna 뒤)에 GPT 5.6 Sol, Terra, Luna를 `("global", "us-east-1")`로,
   단가의 출처 분류와 seed(`pricing_sources._OPENAI_FM`, `FAMILY_ORDER` 끝 세 자리, `pricing_seed._OPENAI`, `OPENAI_LIST_SEED`, 캐시와 긴 컨텍스트 seed,
   `SEED_SOURCE_DATES` 2026-11-25), 화면 목록(`FAMILY_ORDER` 15 → 18, `TrendChart` 색과 대체 색, `StreamingView` 분기와 배지 색).
2. **CDK 모델 id env를 되살린다** — `BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID`, `_TERRA_`, `_LUNA_`를 AppServices `backendEnv`와 Scheduler `buildTaskDef`에
   다시 넣었다(jest 고정). 없으면 prober와 gptbench가 채널을 조용히 건너뛰므로 이미지-only가 아니라 digest 고정 CDK로 두 스택을 배포한다.
3. **숨김을 푼다** — backend `visibility._DEFAULT_HIDDEN`과 프런트 `EXCLUDED_FAMILIES`에서 `GPT 5.6`을 뺐다. 저장 행은 지운 적이 없으므로
   v2.42.x까지 쌓인 GPT 5.6 행이 조회에 다시 잡힌다. 1P 라벨은 `(1P)` 패턴이 계속 숨긴다.
4. **벤치는 GPT 5.6 Terra를 목록 끝에 둔다** — v2.42.x에는 `_BENCH_SPECS`의 앞자리였지만, "새 채널은 끝에" 규칙(데드라인 컷이 뒤쪽 채널부터 떨어진다)을
   따라 끝에 둔다. 그동안 재 온 21채널의 시계열이 끊기지 않는다. `routers/gptbench.py` `fam_rank`는 GPT 6 Luna 뒤(7)다.
5. **프로모션 메모를 되살린다** — `PRICE_NOTES`의 GPT-5.6 Sol `promo` 메모를 `min_until` 2026-11-30, 문구의 확인일 2026-11-25로 넣었다.
   `prior_price`(OpenAI 공식 가격과 Global $5/$30, In Region $5.50/$33)는 그대로다.
6. **추세 차트 색은 새로 고른다** — v2.42.x의 초록 계열은 그 뒤 자리를 잡은 GPT 6 계열과 같은 선 패턴에서 거의 겹친다(GPT 5.6 Luna Global 대
   GPT 6 Luna Global ΔE 5.0, GPT 5.6 Sol Global 대 GPT 6 Astra Global 4.9). GPT 5.6 Sol us-east-1(`#22c55e`)은 라이트 카드 대비가 2.2:1이었다.
   v2.32.0부터 새 채널에 적용해 온 기준(같은 패턴 최근접 ΔE 15 이상, 다크 4.5:1과 라이트 3:1 대비)으로 다시 골랐다: Sol 남보라 `#594077`과 파랑
   `#0038e0`, Terra 짙은 올리브 `#3c5214`와 라임 `#d0f500`, Luna 모래색 `#dbc6bd`와 주홍 `#ff3b0a`(Global 실선, us-east-1 일점쇄선 순, 최근접 ΔE 18.5).
   수집을 멈춘 us-east-2, us-west-2 라벨은 추세 최대 범위(7일) 밖이라 색 항목을 두지 않는다.
7. **`/gpt-on-aws`** — GPT 5.x 세대 묶음이 GPT 5.6 Terra 한 열로 다시 생긴다. 선 패턴은 v2.42.x의 실선을 v2.44.0부터 GPT 6.2 Astra가 쓰므로
   비어 있던 파선 `"7 4"`다.
8. **되살리지 않는 것** — GPT 5.5와 Claude Opus 4.8(요청 범위 밖), 휴면 1P 스펙과 `OPENAI_1P_GPT_56_*` env(1P는 2026-07-31부터 비교에서 뺀 경로다),
   US CRIS 채널 `us.openai.gpt-5.6-*`(v2.42.x에 없던 채널).

## Alternatives

- **v2.43.0 커밋을 `git revert`한다** — Claude Opus 4.8과 GPT 5.5까지 돌아오고 v2.44.0의 같은 줄과 충돌한다. GPT 5.6 부분만 손으로 되살렸다.
- **US CRIS 채널도 더한다** — 프로파일이 있고 GPT 6 세대는 세 경로를 모두 잰다. 그러나 요청은 "다시 활성화"이고 채널 3개와 단가 행이 새로 생긴다.
  필요하면 스펙 튜플에 `"us"`만 더하면 된다.
- **벤치의 예전 앞자리로 되돌린다** — 느린 사이클에서 컷이 GPT 6.2 Sol에 떨어진다. 끝에 두면 컷이 되살린 채널에 떨어진다.
- **예전 초록색을 그대로 쓴다** — 지난 데이터와 색이 같아지지만, 7일 추세에는 지난 GPT 5.6 행이 없고(2026-11-11부터 공백) 지금 카탈로그에서는
  구분되지 않는다.
- **GPT 5.6 Sol, Luna도 벤치에 넣는다** — v2.18.0부터 벤치 대상이 아니었고(사용자 지정) 하루 비용이 늘어난다.

## Consequences

- 활성 45 → 51(Bedrock 17 + Claude Platform on AWS 7 + OpenAI 27 = Mantle us-east-1 10 + Global 10 + US 7). `FAMILY_ORDER` 18, 약정 오퍼 FM 14 → 17,
  `/pricing` 참고 자료 17 → 20(약정 오퍼 17), OpenAI 공식 가격 7 → 10, PricingSync 로그 `61 active channels`, 모델 탐색 예제 77 → 83.
- GPT on AWS 벤치 21 → 23채널(Mantle us-east-1 8 + CRIS 15), 로그 `GPT bench lanes: cris=15 mantle-us-east-1=8`, 사이클당 230행. 갈래마다 채널이
  하나씩 늘어 약 25초씩 길어질 것으로 본다(데드라인 780초 안). 추가 비용은 캐시 읽기 단가 기준 추정 하루 약 $25다(채널당 하루 1,056호출 ×
  55.8k 토큰 ≈ 5,900만 토큰, Global $0.20, In Region $0.22 per MTok).
- Claude 채널, Claude API Features(1,365셀), `/prompts`, 시간당 CP 호출 수는 변하지 않는다. 패리티 런은 다음 12시간 런부터 GPT 5.6 여섯 채널을 다시
  잰다(`_REASONING_MARKERS`의 `"gpt-5"`는 v2.43.0에도 남겼다).
- 운영 `price_history`에는 이 채널들의 행이 남아 있어 seed는 건너뛴다. 배포 뒤 첫 PricingSync는 GPT 5.6이 없던 스냅샷과 비교하므로 `/pricing` 변경
  목록에 채널 추가 9건(6채널 + OpenAI 공식 가격 3)이 한 번 나온다.
- 비용(30일), 이력처럼 긴 창의 화면에는 2026-11-10까지의 GPT 5.6 행이 다시 잡히고 2026-11-11부터 배포까지는 공백이다. v2.37.x까지 수집한
  us-east-2, us-west-2 라벨의 행도 30일 창에 며칠 더 보인다.
- 프로모션은 문서 기준 2026-11-30까지다. 그 뒤 동기화가 이전 단가를 관측하면 입력 +25%, 출력 +50%라 관리자 승인 없이 적용되고(0.5 경계 포함) 메모가
  빠진다. 단가가 그대로면 2026-12-01(UTC)부터 배지가 "프로모션 종료 여부 확인 필요"로 바뀐다.
- 고정 테스트: `backend/tests/test_reenable_gpt56.py`(복귀), `test_retire_opus48_gpt55.py`(남은 제외 — 파일 이름에서 `_56`을 뺐다),
  `cdk/test/*-stack.test.ts`, `TrendChart.test.ts`, `GptOnAwsPanel.test.ts`, `sortModels.test.ts`.
- 다시 빼려면 ADR-038의 절차를 GPT 5.6에만 적용한다. 롤백 지점은 v2.44.2 이미지 `v4db0ea2`다.
