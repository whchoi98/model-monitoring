# ADR-026: Claude API Features 검증 매트릭스 — 문서 기대치 vs 실측 드리프트 (별도 메뉴)

- **Status**: Accepted
- **Date**: 2026-09-05
- **Related**: ADR-021 (실행-증거), ADR-022 (Mantle bearer + IAM 체인), ADR-023 (정직한 제외), v2.23.0
- **Spec**: docs/superpowers/specs/2026-09-05-claude-features-verify-design.md

## Context

platform.claude.com "Build with Claude" 개요는 33개 피처를 플랫폼별 가용성(GA/Beta/미제공)과 함께 나열한다.
운영자는 이 목록이 Claude Platform on AWS · Bedrock Mantle `/anthropic` · Bedrock runtime(Messages API/InvokeModel/Converse)에서
오늘 실제로 동작하는지 알아야 한다. 기존 `/parity`는 모델 중심(43모델 × 6 surface × 19피처)이라 "문서 기대치"
차원이 없고, 피처 12개가 acceptance 수준이며 도구 타입 문자열이 낡았다.

## Decision

1. **형제 패키지 `backend/claude_features/`** — 패리티는 그대로 두고 순수 함수만 공유. 카탈로그는
   39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1, 행마다
   `documented{cp,mantle,bedrock_messages,bedrock_invoke,bedrock_converse}`와 검증 강도(`evidence|acceptance|capability|negative`)를 명시.
2. **전송기 5개, 본문 1개** — Anthropic Messages JSON을 raw httpx(CP: x-api-key+workspace, Mantle: SigV4 파생 bearer,
   bedrock-runtime Messages API: 같은 파생 bearer) / boto3 InvokeModel(`anthropic_version`+body `anthropic_beta`) /
   boto3 Converse(프로브가 넘긴 Converse 매핑만)로 흘린다.
   SDK 미사용 — `anthropic>=0.40.0` 미고정으로 빌드 시 1.x 메이저 업이 들어오기 때문.
3. **대표 모델 4종 고정**(Fable 5.1·Fable 5·Opus 5·Sonnet 5, Haiku 제외). Mantle은 Fable 5.1 제외 — US GovCloud 전용 → `not_applicable`.
4. **상태 6종 + 판정 4종** — `supported|unsupported|broken|inconclusive|skipped|not_applicable` × `match|drift|undocumented|none`.
   `inconclusive`(정의 수락, 미호출)와 `not_applicable`(설계상 부적용)을 unsupported와 분리해 오판을 막는다.
5. **부정 제어(negative)** — effort/inference_geo처럼 응답에 신호가 없는 파라미터는 잘못된 값이 그 파라미터를 지목하는 400으로
   거부되는지를 함께 확인해 "조용히 무시"와 "검증됨"을 구분한다.
6. **일 1회 Fargate + JWT 수동 트리거**, 별도 테이블 `feature_runs/feature_results`(60런 보존), `/api/features/*`, `/claude-features` 메뉴.
7. **고비용 프로브도 실행**(web search·code execution·advisor·batches·files·skills; 생성물은 즉시 취소/삭제). 1M 컨텍스트만 capability 검사.
8. **Mantle `/anthropic` 리전은 `us-east-1`** (`MANTLE_ANTHROPIC_REGION`, CDK 명시 주입 — 사용자 결정 2026-09-05). 실측(§ 아래)에서
   `ap-northeast-1`이 이 계정의 대표 4모델 중 Opus 4.8 하나만 서빙한다고 확인돼, `sonnet-5`가 200으로 서빙되는 `us-east-1`로
   고정했다. 이 env는 패리티 런 `messages_mantle` surface와 공유되므로 두 매트릭스가 함께 영향을 받는다(코드 자체 폴백은
   `backend/parity/runner.py`에서 여전히 `ap-northeast-1` — CDK가 모든 스케줄 태스크·backend 서비스에 값을 명시 주입해 override).
9. **5번째 surface `bedrock_messages` — bedrock-runtime이 직접 호스팅하는 Anthropic Messages API** (2026-09-05 추가).
   `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/messages`(서울). AWS Build 가이드와 Endpoints 페이지가
   신규 애플리케이션과 "Migrating from Anthropic APIs"에 권장하는 경로여서, InvokeModel/Converse와 별개 열로 실측한다.
   크로스리전 추론 프로파일 id(`global.anthropic.claude-*`) + SigV4 또는 `aws-bedrock-token-generator` 단기 토큰(`x-api-key`)
   + `anthropic-version`/`anthropic-beta` 헤더. Bedrock 열은 3 서브열(Messages API·InvokeModel·Converse)이 되고 1런은
   624셀 → 780셀. 문서 기대치는 InvokeModel 행을 상속하되 실측이 갈라지는 4개만 override
   (`structured_outputs`/`strict_tool_use`/`token_counting` = `no`, `tool_search` = `unknown`).
   미지원 라우트는 coral `UnknownOperationException`으로 답하므로(HTTP 200 본문 포함) 전송기가 `404`로 정규화해
   false-supported를 막고, `/v1/messages` 이외 경로의 403 "Authorization header is missing"도 라우트 부재로 정규화한다
   (x-api-key와 `Authorization` 두 스킴은 배타적이라 헤더를 추가해 재측정할 수 없다 — 실측 2026-09-05).
   참조: <https://docs.aws.amazon.com/bedrock/latest/userguide/build.html> ·
   <https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html> ·
   <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html>

## 실측 (2026-09-05)

로컬 라이브 스모크(`sonnet-5` 전체 39피처 × 4 surface 스윕 + `bedrock_messages` 스윕, task-7-report·task-13-report 참조)에서
확인된 드리프트와 미문서화 동작. **두 스윕 모두 `broken` 0 / `inconclusive` 0** — 모든 셀이 판정 가능한 상태로 수렴한다
(4 surface는 Task 7 프로브 결함 4건 수정 + 증거 강화 1건 후, `bedrock_messages`는 라우트 403 정규화 후):

- **Mantle `/anthropic` 리전 서빙 갭** — `ap-northeast-1`은 이 계정에서 `anthropic.claude-opus-4-8`만 서빙한다.
  `anthropic.claude-{fable-5,opus-5,sonnet-5}` 호출은 전부 `not_found_error`. `us-east-1`은 `sonnet-5`를 200으로 서빙
  (실측 확인) — 이 발견이 위 Decision §8의 리전 전환을 이끌었다. 전환 전 스모크는 `ap-northeast-1` 기준이라 Mantle 열
  드리프트 23건이 전부 "모델 미서빙"으로 수렴했었다(수정 대상 아님, 리전 전환으로 대부분 해소 예상).
- **Bedrock 세 열(Messages API·InvokeModel·Converse)이 Claude 5 세대에서 structured outputs·strict tool use를 거부** — `output_config.format`,
  `tools[].custom.strict: true` 모두 `Extra inputs are not permitted` 400. Anthropic의 "Claude in Amazon Bedrock
  (Opus 4.7+)" 페이지는 미지원으로 정확히 기재하지만, AWS InvokeModel 문서의 지원 표기는 4.6 이하 세대를 대상으로 한
  낙관적 서술이었다 — 카탈로그 `documented`를 Bedrock 세 열 모두 `no`로 낮춰 `match`로 정정.
- **Bedrock `CountTokens`가 CRIS 전용(`global.*`) Claude 5 모델을 지원하지 않음** — 프로파일 형태(`global.` 접두) 문제가
  아니라 모델 지원 문제(직접 boto3 매트릭스로 확인, Seoul 리전). Mantle `/anthropic`의 `count_tokens`만 유일한 경로 —
  카탈로그를 `{cp: ga, mantle: ga, bedrock_messages: no, bedrock_invoke: no, bedrock_converse: no}`로 정정
  (`bedrock_messages`는 count_tokens 라우트 자체가 없다 — coral `UnknownOperationException`, 실측 2026-09-05).
- **`browser_toolset_20260801`이 문서에 없는데 동작** — CP on AWS·Bedrock InvokeModel·bedrock-runtime Messages API 모두 toolset을 수락하고
  `tool_use{toolset: browser}`를 방출한다. `documented`는 그대로 전부 `no` 유지, `undocumented` 판정으로 기록(문서
  갱신 여부는 컨트롤러 후속 판단 대상으로 남김).
- **Files API·Agent Skills가 CP on AWS에서 베타 헤더 없이 동작** (Ruling H, task-7 확인) — 두 피처 모두 `anthropic-beta`
  헤더를 붙이지 않고도 CP on AWS에서 정상 왕복.
- **`bedrock_messages`(5번째 surface) 실측** — supported 22 / unsupported 15 / skipped 1(1M 컨텍스트) /
  not_applicable 1(`extended_thinking`, adaptive 전용 모델), 판정 `match` 35 · `undocumented` 1 · 드리프트 0.
  코어 4종·스트리밍·적응형 추론·인용·PDF·search_results·effort·fallback 크레딧·캐싱 3종·compaction·context_editing·
  세분화 도구 스트리밍·클라이언트 도구 4종이 모두 동작한다. `structured_outputs`(`output_config.format`)·
  `strict_tool_use`·`data_residency`(`inference_geo`)·`server_side_fallback`(`fallbacks`)은
  `Extra inputs are not permitted` 400, 서버측 도구·MCP·코드 실행·Agent Skills는 `tool type '…' is not supported` 400으로
  깨끗하게 거부된다. 엔드포인트 라우트는 `/v1/messages`만 있어 `token_counting`·`models_api`·`files_api`는 coral
  `UnknownOperationException`, `/v1/messages/batches`는 403 "Authorization header is missing"(SigV4 프론트도어)으로
  부재가 확인됐다. **`tool_search`는 AWS 문서가 InvokeModel만 명시하는데도 이 경로에서 동작** — 기대치는 `unknown`으로 두고
  실측으로 판정한다. `browser_use`는 CP·InvokeModel에 이어 이 경로에서도 동작(문서상 전 열 `no` → `undocumented`).

수정 전/후 비교, 트리아지 표, 근본 원인 5종은 `task-7-report.md`(§2~§3)에 상세 기록. 이번 ADR은 그 실측 결과 중
**카탈로그 기대치를 바꾼 4건**(token_counting/structured_outputs/strict_tool_use/browser_use notes, context_editing
파라미터명 정정)과 **인프라 결정 1건**(Mantle 리전 전환)만 반영한다.

- **전체 스윕(4모델 × 5 surface, 780셀 = 39피처 × 5 surface × 4모델, task-12-report.md 참조)** — 프로브 결함
  2건을 수정한 뒤 **broken 0 / inconclusive 0**으로 수렴한다(수정 전 최초 전체 실행은 broken 39). 드리프트 25건은
  Mantle(`us-east-1`) Fable 5가 모든 피처를 `data retention mode 'default' is not available for this model`로
  거부하는 ×23(Covered Model 데이터 보존 opt-in을 계정/프로젝트에 적용하면 해소되는 계정 단위 단일 원인 — 카탈로그
  기대치는 낮추지 않고 그대로 둔 **결정 항목**) + Mantle `fallback_credit` ×2(해당 `anthropic-beta` 헤더를 Mantle이
  수락하지 않는 **실제 surface 갭**)로 구성된다. `undocumented` 14건은 전부 `browser_use`
  (`browser_toolset_20260801`)가 cp(4모델)·mantle(opus-5/sonnet-5)·bedrock_messages(4모델)·bedrock_invoke(4모델)에서
  문서 없이 `tool_use`를 방출(Converse는 표현 필드가 없어 `not_applicable`). 프로브 결함 수정: (1) 구 `CACHE_PAD`가
  자신을 "probe"/"model"로 서술해 안전 거부를 유발했다(CP Fable 5 `refusal`/`cyber`, CP Opus 5
  `refusal`/`reasoning_extraction`, Converse Fable 5 `content_filtered`) → 무해한 백과사전식 패딩으로 교체 +
  `engine.blocked_stop_reason()`이 차단된 완료를 `broken` 대신 `inconclusive`로 분류; (2) 캐시 3프로브
  (`automatic_prompt_caching`/`prompt_caching_5m`/`prompt_caching_1h`) 판정식을 **2차 호출
  `cache_read_input_tokens > 0` 필수**로 통일(생성/`ephemeral_1h` 필드는 보조 증거로만 남김 — 종전 창작-only OR
  분기는 안전 거부 4건 + `bedrock_messages`/Fable 5 정상 캐시 미스 1건, 총 5행을 증거 없이 통과시켰다); (3) 분류
  마커에 `"is not available for this model"`을 추가해 계정 단위 모델 미제공을 `unsupported`로 정확히 판정
  (그 전엔 Mantle Fable 5 35행이 전부 `broken` 오탐).

## Consequences

- (+) 문서 드리프트가 배너로 드러남; 셀 클릭으로 요청 스냅샷·응답 신호·문서 링크까지 추적.
- (+) 문서 상충 지점(Mantle `anthropic-beta` 헤더, Mantle/InvokeModel structured outputs, P-AWS 서버측 fallback)이 실측으로 닫힘.
- (+) Mantle 리전을 `us-east-1`로 전환해 패리티 런 `messages_mantle` surface도 함께 개선(Supported 셀 증가 예상) — 별도
  코드 변경 없이 공용 env 하나로 두 매트릭스가 동시에 혜택을 받는다.
- (+) **v2.23.1 — `data_residency`는 Bedrock/Mantle에서 `not_applicable`로 사전판정**: 공식 데이터 레지던시 문서가 "Amazon Bedrock에서는 엔드포인트 URL 또는
  추론 프로파일이 추론 리전을 결정하므로 `inference_geo` 비적용"이라고 명시. 기존 `unsupported`(match) 15셀은 "Bedrock은 데이터 레지던시 미지원"으로
  읽히는 오해를 낳았다(데이터 레지던시 자체는 리전 선택으로 충족). 카탈로그 `_NOT_APPLICABLE_BY_DOC`으로 일반화.
- (−) 런당 토큰 비용 대략 $5~7(월 ~$150~210, Fable 지배) — 1런 = 프로브 643 + 사전판정 137 = 780셀(v2.23.1, 이전 658 + 122), 캐싱·부정 제어
  포함 ≈800 API 호출. MCP 프로브는 공개 MCP 서버 의존(장애는 inconclusive로 격리).
- (−) 신규 피처 추가 시 3단: 카탈로그 행(+documented) → 프로브 함수(5 surface 분기) → 테스트. Converse 표현 불가 목록(`_CONVERSE_NOT_EXPRESSIBLE`) 갱신.
- (−) `strict_tool_use`/`structured_outputs`/`token_counting` Bedrock 열 drift는 의도적으로 남김(문서 기대치는 그대로 `ga`가 아닌 실측 반영값으로 낮췄으므로 이제 `match` — Bedrock 자체의 플랫폼 갭은 여전히 존재하고 향후 AWS가 지원을 추가하면 실측이 다시 흔들릴 수 있음).
- (−) 드리프트 배너의 25건은 첫 배포 화면에 그대로 뜬다 — 해소 조건은 Mantle 계정 opt-in.
