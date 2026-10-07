# ADR-032: Claude Haiku 5.5, Claude Sonnet 5.5 US 채널, Claude 긴 컨텍스트 단가, 문서 불일치 메모

- **Status**: Accepted
- **Date**: 2026-10-07
- **Related**: ADR-026 (Claude API Features — 대표 모델), ADR-028 (CP 점 버전 가드 `_is_point_release_of`), ADR-030 (단가 자동 동기화, 50% 게이트), ADR-031 (Sonnet 5.5, 서울 In-Region), v2.33.0

## Context

사용자 요청(2026-10-07): "https://www.anthropic.com/claude-haiku-5-5#further-updates, haiku 5.5 추가, Sonnet 5.5 cache 가격
변동 업데이트 전체 메뉴에 내용 확인 하고 업데이트."

발표 페이지(2026-10-07): Claude Haiku 5.5(`claude-haiku-5-5`) 출시, 단가는 100K 토큰 이하 프롬프트 $0.10 / $0.50, 캐시 읽기 $0.01,
캐시 쓰기 $0.125이고 100K 토큰 초과 프롬프트는 모두 5배다. "Further updates"에서 Sonnet 5.5 캐시 읽기를 $0.20에서 $0.10으로 50% 내렸다.

2026-10-07 운영 자격증명(Bedrock, CP on AWS envelope 키 + workspace)으로 실측했다.

| 경로 | model | 결과 |
|------|-------|------|
| `list-inference-profiles` (서울, us-east-1, us-east-2, us-west-2) | `global.`/`us.anthropic.claude-haiku-5-5` | 서울은 `global.`만, US 세 리전은 둘 다 ACTIVE |
| `list-foundation-models` (네 리전) | `anthropic.claude-haiku-5-5` | `INFERENCE_PROFILE`만 — 서울 in-region 채널 없음 |
| Bedrock converse (서울 Global, us-east-1 US) | Haiku 5.5 | **200** |
| converse + `temperature` | Haiku 5.5 | 400 "`temperature` is deprecated for this model" |
| converse forced `toolChoice` any | Haiku 5.5 Global, US | **200** (`tool_use`) |
| CP `/v1/messages` forced `tool_choice` any | `claude-haiku-5-5` | **200** |
| `thinking.type.enabled` (CP, Bedrock) | Haiku 5.5 | 400 "Use thinking.type.adaptive and output_config.effort" |
| `thinking.type.adaptive` + effort high (CP) | Haiku 5.5 | **200**, thinking 블록 |
| CP `/v1/models` | — | 첫 항목 `claude-haiku-5-5`(이후 sonnet-5-5, opus-5-5 …) |
| CP `/v1/models/claude-haiku-5-5` | — | max_input_tokens 1,000,000, max_tokens 128,000 |
| CP advisor (`advisor_20260301`) | Haiku 5.5 + Opus 5.5 / Sonnet 5.5 / Haiku 5.5 | 모두 `advisor_redacted_result` |
| Mantle us-east-1 `/anthropic` | `anthropic.claude-haiku-5-5`, `anthropic.claude-sonnet-5-5` | 404 `not_found_error` (sonnet-5는 200) |
| CountTokens (us-east-1) | `anthropic.claude-haiku-5-5` | "The provided model doesn't support counting tokens" |
| OptimizePrompt (us-east-1) | `anthropic.claude-haiku-5-5`, `anthropic.claude-sonnet-5-5` | optimizedPromptEvent |
| `list-inference-profiles` | `us.anthropic.claude-sonnet-5-5` | **새로 생김**(us-east-1, us-east-2, us-west-2), converse 200, forced `tool_choice` 400 그대로 |

단가 출처:

- Bedrock agreement offer `offer-u3aih6zr7uw5u`(Haiku 5.5): `*_global_standard` 0.1 / 0.5, 캐시 0.01 / 0.125 / 0.2,
  `USE1_*_standard`(US) 0.11 / 0.55, 0.011 / 0.1375 / 0.22, 그리고 `_long_ctx` 차원(Global 0.5 / 2.5, 캐시 읽기 0.05, 쓰기 0.625,
  US는 × 1.1). `AFS1_` 같은 미지원 리전 접두는 파서 허용 목록 밖이라 무시된다.
- Bedrock offer `offer-5fu2rhus3byrs`(Sonnet 5.5): 캐시 읽기 Global 0.2 → **0.1**, `USE1_*_standard` 2.2 / 11(캐시 0.11 / 2.75 / 4.4).
- Anthropic `pricing.md`: Haiku 5.5는 두 행 "Claude Haiku 5.5 (for prompts up to 100,000 tokens)"와 "(for prompts over 100,000 tokens)".
  Sonnet 5.5는 **본문**("a cache hit costs 5% … $0.10 USD on Claude Sonnet 5.5")과 **표**("Cache hits and refreshes" $0.20)가 다르다.

## Decision

1. **채널 4개 추가(활성 62 → 66, 카탈로그 67 → 71)** — `global.anthropic.claude-haiku-5-5`, `us.anthropic.claude-haiku-5-5`,
   CP `anthropic:claude-haiku-5-5`(타깃 `haiku-5-5`를 `haiku-4-5` 바로 앞에, `pricing_sources._CP_TARGETS`도 같은 순서),
   `us.anthropic.claude-sonnet-5-5`(사용자 결정 "함께 추가"). 서울 in-region은 둘 다 없다.
2. **호출 규칙** — `prober._REASONING_MODEL_PATTERNS`에 `"haiku-5"`(temperature 억제, haiku-4-5는 해당 없음). 패리티
   `_REASONING_MARKERS`에 `"haiku-5"`(Sonnet 5.5와 같은 adaptive 전용 판정), `_NO_FORCED_TOOL_CHOICE_MARKERS`에는 넣지 않는다
   (forced 200). Sonnet 5.5 US는 기존 `"sonnet-5-5"` 마커가 덮는다.
3. **`/claude-features` 7번째 대표 모델 Haiku 5.5**(사용자 결정 — 2026-09-05에는 Haiku를 대표에서 뺐지만 Haiku 5.5는 넣는다).
   `mantle: None` + 404 사유, advisor 페어링 `claude-opus-5-5`, 1런 1365셀(프로브 1079 + 사전판정 286), `CATALOG_VERSION` `2026-10-07`.
4. **`/prompts` OptimizePrompt 대상** — Haiku 5.5 Global, US와 Sonnet 5.5 US.
5. **Claude 긴 컨텍스트 단가** — 긴 컨텍스트 4필드는 GPT 전용이었다. Haiku 5.5는 프롬프트 길이로 단가가 갈리므로
   `pricing_sources.CLAUDE_LONG_CONTEXT_FAMILIES = {"claude-haiku-5-5"}`와 `keeps_long_context(ident)`로 허용 목록을 두고,
   `pricing_sync._long_context_gate`(구 `_gpt_long_only`)가 offer 경로와 문서, Price List settle 경로 모두에서 그 밖의 채널의 long_*를 버린다.
   다른 Claude는 1M 컨텍스트 전체가 표준 단가라 허용하지 않는다.
6. **Anthropic 문서 파서의 프롬프트 길이 구간** — `parse_anthropic_pricing_md`는 끝 괄호를 지운 이름으로 매칭하므로 Haiku 5.5 두 행이
   같은 이름이 되고, 입력이 달라 `_unambiguous`가 둘 다 버렸다(CP Haiku 5.5가 `skipped:not_found`). `_PROMPT_TIER_RE`로
   "(for prompts up to N tokens)" 행은 표준, "(for prompts over N tokens)" 행은 같은 이름의 long_input, long_output,
   long_cache_read, long_cache_write(5분 쓰기)로 합친다. up-to 행이 없는 over 행은 무시한다.
7. **Sonnet 5.5 캐시 인하** — Bedrock은 offer가 이미 0.1이고 변화율이 정확히 50%라 다음 PricingSync가 승인 없이 적용한다(0.5 경계 포함).
   seed `_CLAUDE_CACHE`도 Global 0.1, US 0.11로 고친다(기존 행은 `COALESCE`라 바뀌지 않는다). **CP는 문서 표를 따른다**(사용자 결정
   "표를 따름, 메모 추가"). 새 메모 종류 `doc_conflict`를 `PRICE_NOTES`에 둔다 — `expected: {"cp": {"cache_read": 0.1}}`,
   출처 `anthropic_doc`. `pricing_payload._note_resolved`는 동기화가 그 티어에서 기대 값을 관측하면 메모를 뺀다. 즉 Anthropic이 표를
   고치면 0.2 → 0.1(정확히 50%)이 자동 적용되고 메모도 저절로 사라진다. 화면은 CP 셀에 "문서 불일치" 배지와
   "문서 본문과 발표: 캐시 읽기 $0.10"을, Markdown 내보내기는 참고 사항에 메모 전문을 싣는다.
8. **추세 차트 색** — Haiku 5.5는 따뜻한 계열 한 패밀리(Global `#aa5533`, US `#cc6600`, CP `#ddbb11`), Sonnet 5.5 US는 `#504800`.
   보라, 남색 후보는 Sonnet 5 US 파선과 ΔE 15 안쪽이거나 다크 카드 대비 4.5:1 아래였다. `TrendChart.test.ts`가 새 4개 시리즈의
   같은 패턴 최근접 ΔE 15 이상과 대비 하한을 고정한다.

## Alternatives

- **CP Sonnet 5.5 캐시 읽기를 $0.10으로 고정** — DB를 직접 고치면 다음 동기화가 표 값 $0.20을 읽어 +100% 변화로 검토 대기가 된다.
  파서에 예외를 두면 "공식 출처의 표를 읽는다"는 ADR-030 원칙이 깨진다. 기각(사용자 결정).
- **Claude 긴 컨텍스트를 전부 허용** — Bedrock offer에는 옛 Claude의 `_long_ctx` 차원이 남아 있을 수 있고, 1M 표준 단가 모델에
  긴 컨텍스트 줄이 뜨면 오해를 부른다. 허용 목록으로 한다.
- **Haiku 5.5를 `/claude-features`에서 제외(2026-09-05 결정 유지)** — 사용자가 이번에 넣기로 했다.

## Consequences

- 시간당 CP 호출 120 → 132회(11채널 × 12), FeaturesVerify 1런 약 195셀 증가(Haiku 5.5 몫, CP와 Bedrock 프로브 133).
- 새 env와 IAM 변경 없음(두 역할 모두 `foundation-model/*`). 이미지 + AppServices, Scheduler 스택 배포(Scheduler는 FeaturesVerify 설명).
- 배포 직후 PricingSync를 한 번 수동으로 돌리면 Sonnet 5.5 Global 캐시 읽기 $0.10, Haiku 5.5 세 채널 verified가 바로 보인다.
- 후속: Anthropic이 문서 표를 고치면 메모가 자동으로 빠지는지 확인한다. 다른 Claude 모델이 프롬프트 길이 단가를 도입하면
  `CLAUDE_LONG_CONTEXT_FAMILIES`에 추가한다.
