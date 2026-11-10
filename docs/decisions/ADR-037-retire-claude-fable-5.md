# ADR-037: Claude Fable 5 모니터링 제외

- **Status**: Accepted
- **Date**: 2026-11-10
- **Related**: ADR-026 (Claude API Features), ADR-030 (단가 자동 동기화), ADR-034 (Claude 4.x, GPT 5.4 제외 — 같은 절차), ADR-035 (단가 변경 목록, 모델 탐색 검증), ADR-036 (Claude Fable 5.2), v2.42.0

## Context

사용자 지시(2026-11-10, v2.40.0 + v2.41.0 배포 직후): "Fable 5.0 는 deprecate 시킵니다."

v2.41.0 카탈로그에서 Claude Fable 5는 활성 3채널이었다.

| 채널 | model_id | 라벨 |
| --- | --- | --- |
| Bedrock Global (서울) | `global.anthropic.claude-fable-5` | `Bedrock Claude Fable 5 (Global)` |
| Bedrock US (us-east-1) | `us.anthropic.claude-fable-5` | `Bedrock Claude Fable 5 (US)` |
| Claude Platform on AWS | `anthropic:claude-fable-5` | `Anthropic Claude Fable 5 (US)` |

AWS는 `anthropic.claude-fable-5`를 아직 ACTIVE로 표시하고(서울, us-east-1, 2026-11-09 `list-foundation-models`), CP `/v1/models`도
`claude-fable-5`를 돌려준다. 그래서 이 결정은 플랫폼의 지원 종료가 아니라 모니터링 범위 결정이다. 같은 계열의 Fable 5.1(v2.22.0)과
Fable 5.2(v2.41.0)는 남는다.

Fable 5는 `/claude-features` 대표 모델이기도 했고(8종 중 셋째), Mantle us-east-1이 서빙하는 유일한 Fable이었다(Fable 5.1은 US GovCloud 전용,
Fable 5.2는 404).

## Decision

1. **ADR-034와 같은 방식으로 뺀다** — 카탈로그(`prober.AVAILABLE_MODELS`의 Global, US 2개, `_ANTHROPIC_TARGETS`의 `fable-5`), 단가
   (`pricing_sources`의 `_BEDROCK_CLAUDE_FM`, `_CP_TARGETS`, `FAMILY_ORDER`, `pricing_seed`의 `SEED`, `CP_SEED`, 캐시 seed), Claude API Features
   대표 모델(`claude_features.catalog.MODELS`, `probes._ADVISOR_FOR`, `CATALOG_VERSION` `2026-11-10`), 화면 목록(`FAMILY_ORDER`, `TrendChart`
   색 3개와 `FAMILY_FALLBACK`, `StreamingView` 색과 `extractModelName` 분기, `/prompts` OptimizePrompt 대상 2개). 활성 52 → 49(Bedrock 21 → 19,
   CP 9 → 8, OpenAI 22), 카탈로그 56 → 53. CP 타깃을 지웠으므로 CP가 서빙하는 `claude-fable-5`는 어느 타깃에도 걸리지 않아 등록되지 않는다
   (점 버전 가드와 무관하고, `fable-5-1`, `fable-5-2`는 자기 타깃에 그대로 매칭된다).
2. **행은 지우지 않고 괄호까지 넣은 패턴으로 숨긴다** — `visibility._DEFAULT_HIDDEN`에 `Claude Fable 5 (`를 더했고 프런트 `EXCLUDED_FAMILIES`에도
   같은 항목을 더했다. 매칭은 부분일치(SQL `LIKE '%…%'`, JS `includes`)라 `Claude Fable 5`만 쓰면 `Claude Fable 5.1 (…)`, `Claude Fable 5.2 (…)`
   라벨까지 숨는다. 저장된 Fable 5 라벨은 세 개 모두 `Claude Fable 5 (`를 포함하고, 5.1, 5.2 라벨은 포함하지 않는다
   (`tests/test_retire_fable5.py`가 Python과 SQL 양쪽에서 고정).
3. **`/claude-features`는 라우터가 거른다** — 그 셀은 라벨이 아니라 `model_key`로 저장되므로 숨김 패턴이 닿지 않는다. 그래서
   `routers/features.get_latest`가 카탈로그 `MODEL_KEYS`에 없는 모델의 셀을 빼고, 뺀 셀이 있으면 `run.totals`를 남은 셀로 다시 센다(6 status +
   `drift`). 모든 셀이 카탈로그 모델이면 저장된 합계를 그대로 보낸다. 다음 런의 diff는 원래 현재 런의 셀만 보므로 제외된 셀이 변경으로 잡히지
   않는다. 1런 1560 → 1365셀(프로브 1042 + 사전판정 323). Mantle 열은 이제 Opus 5.5, Opus 5, Sonnet 5만 잰다.
4. **모델 동작 기록은 남긴다** — `prober._REASONING_MODEL_PATTERNS`와 패리티 `_REASONING_MARKERS`의 `"fable-5"`는 5.1, 5.2를 덮으므로 그대로 두고,
   패리티 `adaptive_thinking` 설명만 "Fable 5.1, 5.2 전용"으로 고쳤다. Fable 5.1, 5.2에 필요한 서울과 us-east-1의 `provider_data_share`
   옵트인도 그대로다. 모델 탐색 예제의 주석 "Opus 5 and Fable 5 return a thinking block first"는 예제 텍스트를 바꾸면 `code_sha`가 바뀌어
   모든 예제가 "예제 변경"으로 잡히므로 남긴다.

## Alternatives

- **2026-05-20처럼 행 삭제** — 기동 DELETE는 되돌릴 수 없고 비용과 신뢰성 이력의 근거가 없어진다. 숨김 패턴은 env 하나로 되돌릴 수 있다. 기각.
- **패턴 `Claude Fable 5`** — 부분일치라 Fable 5.1, 5.2 라벨까지 모든 조회에서 사라진다. 기각, 괄호까지 넣는다.
- **`/claude-features` 대표 모델로는 남김** — "deprecate"는 모니터링 전체에서 빼라는 뜻으로 읽었다(ADR-034의 "화면 메뉴들에서도 제거"와 같다).
  대표 모델로 남기면 하루 195셀의 호출이 계속된다. 기각.
- **다음 정기 런까지 `/claude-features`의 지난 셀을 그대로 둠** — 라벨 숨김이 닿지 않아 최대 하루 동안 빠진 모델이 매트릭스에 남는다. 라우터에서
  거르는 쪽이 작은 변경이고, 다음 대표 모델 제외에도 그대로 쓰인다. 채택하지 않음.

## Consequences

- AutoProber 한 사이클의 호출이 52 → 49회, CP 호출은 시간당 108 → 96회(8채널 × 12)로 준다. FeaturesVerify는 런마다 195셀, ExplorerVerify는
  예제 7건(92 → 85)이 준다. `/prompts` Bedrock 대상 19 → 17, `FAMILY_ORDER` 19 → 18, PricingSync 로그 `58 active channels`, `/pricing` 참고 자료
  21 → 20(약정 오퍼 18 → 17 — `offer-vk3fuman5qwzy`를 더 인용하지 않는다).
- 배포 뒤 첫 PricingSync는 Fable 5가 있던 스냅샷과 비교하므로 `/pricing` 변경 목록(ADR-035)에 채널 제외 3건이 한 번 나온다. `price_history` 행은 남는다.
- `HIDDEN_MODEL_PATTERNS`를 주입하면 기본값 전체를 대신하므로 그때는 `Claude Fable 5 (`도 적어야 한다.
- 다시 노출하려면 카탈로그(`prober`, `pricing_sources`, `pricing_seed`, `claude_features.catalog`와 `_ADVISOR_FOR`)를 되살리고 숨김 패턴과
  `EXCLUDED_FAMILIES` 항목을 지운다. 롤백 지점은 v2.41.0 이미지 `vd6dc431`이다.
- 배포는 새 env, IAM, CDK 변경이 없어 이미지만 바뀌지만, 작업 정의를 코드와 맞추려고 digest 고정 CDK로 AppServices, Scheduler 두 스택을
  배포한다(배포 런북 §5-14).
