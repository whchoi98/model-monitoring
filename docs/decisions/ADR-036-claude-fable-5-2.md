# ADR-036: Claude Fable 5.2 (Global, US, Claude Platform on AWS)

- **Status**: Accepted
- **Date**: 2026-11-09
- **Related**: ADR-026 (Claude API Features — 대표 모델), ADR-028 (CP 점 버전 가드 `_is_point_release_of`), ADR-030 (단가 자동 동기화), ADR-032 (Haiku 5.5 — 같은 편입 절차), ADR-035 (모델 탐색 일일 검증 런), v2.41.0

## Context

사용자 요청(2026-11-09): "fable 5.2 가 출시되었습니다. 기능을 추가해주세요."

같은 날 운영 자격증명(Bedrock, CP on AWS envelope 키 + workspace, Bedrock 장기 키)으로 실측했다.

| 경로 | model | 결과 |
|------|-------|------|
| `list-inference-profiles` (서울, us-east-1) | `global.`/`us.anthropic.claude-fable-5-2` | 서울은 `global.`, us-east-1은 둘 다 ACTIVE |
| `list-foundation-models` (서울, us-east-1) | `anthropic.claude-fable-5-2` | `INFERENCE_PROFILE`만 — in-region 채널 없음 |
| Bedrock converse_stream (서울 Global, us-east-1 US) | Fable 5.2 | **200**, TTFT 약 2.1초(Global), 2.6초(US) |
| converse + `temperature` | Fable 5.2 Global, US | 400 "`temperature` is deprecated for this model" |
| converse forced `toolChoice` tool, any | Fable 5.2 Global, US | 400 "tool_choice: type "tool" and "any" are not supported for this model", auto는 200(`tool_use`) |
| InvokeModel `thinking.type.enabled` | Fable 5.2 | 400 "Use thinking.type.adaptive and output_config.effort" |
| InvokeModel `thinking.type.adaptive` + effort | Fable 5.2 | **200** |
| CountTokens (평문 FM id) | `anthropic.claude-fable-5-2` | "The provided model doesn't support counting tokens" |
| CP `/v1/models` | — | 첫 항목 `claude-fable-5-2`(이후 haiku-5-5, sonnet-5-5, opus-5-5, fable-5-1 …) |
| CP `/v1/models/claude-fable-5-2` | — | max_input_tokens 1,000,000, max_tokens 128,000 |
| CP `/v1/messages` | `claude-fable-5-2` | **200**, temperature 400, forced `tool_choice` tool 400 |
| Mantle us-east-1 `/anthropic` | `anthropic.claude-fable-5-2`, `anthropic.claude-fable-5-1` | 둘 다 404 `not_found_error` |
| OptimizePrompt (us-east-1) | `anthropic.claude-fable-5-2` | analyzePromptEvent, optimizedPromptEvent |
| 운영 `/api/auto-probe/latest` | CP Fable 5, 5.1 | 라벨 정상 — 타깃이 없어도 `_is_point_release_of`가 5.2 id를 Fable 5, 5.1 후보에서 뺐다 |

단가 출처:

- Bedrock agreement offer `offer-agsprgw6z3dg6`: `*_global_standard` 8 / 40, 캐시 읽기 0.2, 5분 쓰기 10, 1시간 쓰기 16,
  `USE1_*_standard`(US) 8.8 / 44, 0.22 / 11 / 17.6. `_long_ctx` 차원은 없다.
- Anthropic `pricing.md`: "Claude Fable 5.2" $8 / $40, 5분 쓰기 $10, 1시간 쓰기 $16, 캐시 히트 $0.20 — 각주는 Fable 5.2, 5.1의 캐시 히트를
  입력의 0.025배로 적는다. 같은 날 표의 Sonnet 5.5 캐시 히트도 $0.10으로 바뀌어 본문과 같아졌다(ADR-032의 `doc_conflict` 메모 해소 조건).

Fable 5.2는 Fable 5, 5.1과 같은 Covered Model이다. 서울과 us-east-1의 기존 `provider_data_share` 옵트인으로 converse가 200이라 추가 설정은 없다.

## Decision

1. **채널 3개 추가(활성 49 → 52, 카탈로그 53 → 56)** — `global.anthropic.claude-fable-5-2`, `us.anthropic.claude-fable-5-2`(각 블록 맨 앞,
   Fable 5.1 바로 앞), CP `anthropic:claude-fable-5-2`(타깃 `fable-5-2`가 `_ANTHROPIC_TARGETS` 첫 항목, `pricing_sources._CP_TARGETS`도 같은 순서).
2. **Fable 5.1과 같은 규칙** — temperature 억제는 기존 `"fable-5"` 패턴이 덮고, 패리티 `_REASONING_MARKERS`도 `"fable-5"`가 덮는다.
   `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"fable-5-2"`를 넣는다. `"fable-5"`를 넣으면 forced를 받는 Fable 5까지 auto로 바뀌므로 점 버전 문자열로만 넣는다.
3. **`/claude-features` 첫 대표 모델 Fable 5.2(8종)** — Fable 5.1을 대표로 두는 이유(최신 Fable 세대)가 그대로 적용된다. `mantle: None` + 404 사유,
   advisor는 Fable 5.1처럼 자기 페어링(`claude-fable-5-2`), 1런 1560셀(프로브 1212 + 사전판정 348), `CATALOG_VERSION` `2026-11-09`.
   스모크로 Fable 5.2 195셀을 모두 돌린 결과가 운영 Fable 5.1 셀(런 70)과 상태가 셀마다 같았다(supported 100, unsupported 29, 해당 없음 63, skipped 3).
4. **`/prompts` OptimizePrompt 대상** — Fable 5.2 Global, US(Bedrock 대상 17 → 19).
5. **모델 탐색** — 예제는 백엔드가 채널에서 만든다(ADR-035). 새 예제 7건(Global 3, US 3, CP 1)을 스모크로 실행해 첫 시도에 모두 통과했다. 일일 런은 92건이다.
6. **단가** — `SEED`(Global 8 / 40, US 8.8 / 44), `CP_SEED`(8 / 40), 캐시 seed(`_CLAUDE_CACHE`, `_CP_CACHE`), `SEED_SOURCE_DATES`에 오퍼 확인일 2026-11-09.
   긴 컨텍스트는 없다(`CLAUDE_LONG_CONTEXT_FAMILIES` 그대로). `FAMILY_ORDER` 첫 항목 "Claude Fable 5.2"(19개, 프런트와 백엔드 바이트 동일).
7. **추세 차트 색** — 청록 계열: Global `#245860`(실선), US `#aed3e0`(파선), CP `#47def5`(점선). 같은 패턴 최근접 ΔE 15 이상과 카드 대비 하한
   (다크 4.5:1, 라이트 3:1)을 두 테마에서 지킨다. CP 점선은 계열 기본 선택이라 CP Sonnet 5.5와도 ΔE 15 이상 떨어진다.

## Alternatives

- **세 채널을 Lab 한 색조(10° 안)로 묶기** — GPT 6.1 Sol, Terra처럼 한 색조 세 단계를 찾았지만, 실선 자리는 밝은 청록이 Fable 5, 5.1과
  ΔE 15 안쪽이고 짙은 청록과 같은 색조의 점선은 Fable 5.1 CP와 겹쳤다. 채도가 거의 없는 회색 쪽만 남아 계열로 읽히지 않는다. 색조는 HSL 188~196°로만 맞춘다.
- **Fable 5.2를 `/claude-features`에 넣지 않기** — 1런 195셀(Fable 5.2 몫 CP와 Bedrock 프로브 133) 비용이 늘지만, 최신 Fable 세대를 빼면
  대표 모델의 의미가 흐려진다. 넣는다.
- **패리티 마커를 `"fable-5"`로 일반화** — Fable 5가 forced `tool_choice`를 받으므로 Fable 5 행의 `tool_use` 검증 강도가 떨어진다. 기각.

## Consequences

- 시간당 CP 호출 96 → 108회(9채널 × 12), FeaturesVerify 1런 195셀 증가, ExplorerVerify 1런 7건 증가.
- 새 env, IAM, CDK 변경 없음. 이미지 + AppServices, Scheduler 스택 배포. v2.40.0 브랜치 위에서 만들었으므로 v2.40.0과 함께 또는 그 뒤에 배포한다.
- 배포 뒤 첫 PricingSync는 Fable 5.2 세 채널을 seed 값 그대로 확인하고(변경 없음), 같은 런에서 CP Sonnet 5.5 캐시 읽기 0.2 → 0.1(정확히 50%,
  자동 적용)을 관측해 `doc_conflict` 메모가 빠질 것으로 보인다.
- 다음 점 버전(예: fable-5-3)도 같은 절차다 — 타깃을 선등록하지 않아도 점 버전 가드가 기존 라벨을 지킨다.
