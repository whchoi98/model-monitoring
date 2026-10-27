# 챗봇 답변 출력 한도 — 2026-10-26

공개 챗봇에 "이번 주 가장 비용 효율적인 모델 추천해줘"를 물으면 응답이 없다는 신고를 조사해 수정하고 배포했다. 배포 당시 앱 버전은 `v2.37.0`이었고, 같은 날 이 수정을 `v2.37.1` 패치 릴리스로 정리했다(버전 문자열과 CHANGELOG만 바뀌었다).

## 원인

2026-10-25 운영에서 같은 질문을 재현했다. 첫 문장과 `compare_models(168h)` 호출 세 번까지 나온 뒤 본문 없이 `final ok: true`로 끝났다.

- 도구 결과를 받은 두 번째 호출(입력 16,742토큰)에서 Haiku 5.5의 기본 적응형 추론이 출력 한도 1,024토큰을 다 썼다. 출력 1,024토큰, 본문 0자, `stopReason=max_tokens`였다.
- 챗봇 루프는 `max_tokens` 종료를 알리지 않아 브라우저에는 첫 문장만 남고 오류 표시도 없었다.
- 인사이트는 2026-10-21에 같은 원인을 고쳤지만 그 설정은 챗봇에 적용되지 않았다.

같은 두 번째 호출을 서울 Bedrock에 다시 보내 비교했다.

| 설정 | 종료 | 출력 |
| --- | --- | --- |
| 기본 추론, 1,024토큰 | `max_tokens` | 본문 56자 |
| 추론 끔, 1,024토큰 | `end_turn` | 879토큰 (한도에 근접) |
| 기본 추론, 4,096토큰 | `end_turn` | 1,422토큰 |
| 추론 끔, 4,096토큰 | `end_turn` | 1,041토큰 |

## 수정 (`9b9149b`)

- `agent/bedrock.py`: 챗봇 요청(`converse_stream_chat`)은 Haiku 5.5에 `thinking.type="disabled"`를 보내고 기본 출력 한도는 `CHAT_MAX_TOKENS=4096`이다. 도구 루프가 추론 블록을 다시 보내지 않으므로 추론을 끄는 편이 구조에도 맞다.
- `routers/chat.py`: 마지막 호출이 `max_tokens`로 끝나면 한국어와 영어로 된 `warning` 이벤트를 보낸다. 프런트엔드는 이 이벤트를 오류 문구로 보여 준다.
- 후속 질문 생성은 그대로다. 실제 호출 5번이 모두 추론 없이 약 160토큰에서 `end_turn`으로 끝났다.

## 검증

| 검사 | 결과 |
| --- | --- |
| 백엔드 Ruff | 통과 |
| 백엔드 pytest (Python 3.12) | 1,653개 통과, PostgreSQL 조건부 18개 건너뜀 |
| 운영 이미지 pytest (Python 3.11) | 1,651개 통과, 2개 실패 — 이미지에 없는 프런트엔드 소스를 대조하는 `test_pricing_sources.py` 2개로 이전 이미지와 같다 |
| 고친 함수로 서울 Bedrock 실제 호출 3번 | 모두 `end_turn`, 두 번째 호출 출력 1,070~1,169토큰, 본문 1,336~1,430자 |

`test_insights_bedrock.py::test_each_language_logs_duration_output_tokens_and_stop_reason`은 운영 이미지의 전체 실행에서 가끔 실패한다. 가짜 Bedrock 연결이 응답 전에 닫히는(`ConnectionClosedError`) 경우다. 새 이미지와 이전 운영 이미지 `vb908a9e`가 각각 5번 중 2번 실패했고, 단독 40번과 파일 단위 12번은 모두 통과했다. 이번 변경 전부터 있던 테스트 불안정이다.

배포 후 운영 사이트(`llm-monitor.whchoi.net`)에 비회원으로 질문 4개를 보냈다.

| 질문 | 두 번째 호출 출력 | 결과 |
| --- | --- | --- |
| 이번 주 가장 비용 효율적인 모델 추천해줘 | 1,199토큰 | 답변 1,795자, 경고 없음, 24.1초 |
| 같은 질문 다시 | 1,176토큰 | 경고 없음, 31.8초 |
| 지금 가장 빠른 모델은? | 594토큰 | 경고 없음, 8.7초 |
| 최근 24시간 Haiku 5.5 채널끼리 비교해줘 | 999토큰 | 경고 없음, 9.3초 |

네 번 모두 `final ok: true`였다. 첫 질문과 세 번째 질문은 예전 한도 1,024토큰이었다면 잘렸을 길이다. 첫 답변은 첫 두 문장이 영어였고 나머지 세 번은 처음부터 한국어였다. 시스템 프롬프트는 한국어 답변을 요구한다.

## 남은 과제

- 챗봇 도구 4개에는 단가와 비용 데이터가 없어 비용 질문에는 "단가 정보가 없다"고 답한다. `/api/efficiency/score`, `/api/cost/summary` 같은 비용 도구를 넣으려면 4개 도구 계약(`tests/test_tools.py`)을 바꿔야 한다.
- DB 도구는 동기 조회라 비동기 생성기 안에서 이벤트 루프를 막는다. 7일 범위 `compare_models` 한 번에 7~8초가 걸려, 이번 질문 하나로 같은 태스크의 다른 요청이 약 20초 기다렸다.

## 최종 운영 반영

- `BedrockMonitor-AppServices`와 `BedrockMonitor-Scheduler`는 `UPDATE_COMPLETE`이고 변경은 백엔드 이미지 digest뿐이다(`cdk diff`로 확인). 백엔드 서비스 컨테이너의 실행 digest가 배포값과 같다.
- 배포 뒤 첫 회차인 01:11 UTC에 Insights `:70`과 AutoProber `:77`이 종료 코드 0으로 끝났다. 인사이트 `42266`은 한국어 8,436자, 영어 9,435자가 모두 `end_turn`이었다.
- 01:06:56 AutoProber 회차는 실행되지 않았다. Scheduler가 아직 이전 리비전 `:76`으로 `RunTask`를 호출했는데, CloudFormation 정리 단계가 2초 전에 그 리비전을 INACTIVE로 해제해 `InvalidParameterException: TaskDefinition is inactive`가 났다(CloudTrail). 자동 프로브 한 회차(5분)만 빠졌고 다음 회차는 정상이었다.

| 대상 | 태그 | 작업 정의 리비전 |
| --- | --- | --- |
| 백엔드 | `v9b9149b` | 91 |
| 프런트엔드 | `v6d662bf` (변경 없음) | 96 |
| AutoProber | `v9b9149b` | 77 |
| FeaturesVerify | `v9b9149b` | 28 |
| GptBench | `v9b9149b` | 39 |
| Insights | `v9b9149b` | 70 |
| ParityRun | `v9b9149b` | 50 |
| PricingSync | `v9b9149b` | 16 |

```text
Backend: 061525506239.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:v9b9149b@sha256:5e35a277281c5cbc437579fec432973156aab970534612e64427f4268c7d6d35
Frontend: 061525506239.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-frontend:v6d662bf@sha256:46ee9b5895aa0266c1ccf63fc563a818c9c201f4565a30faf7066ba305421bd1
```

## v2.37.1 운영 반영 (06:12–06:17 UTC)

릴리스 커밋 `705c6ea`로 백엔드와 프런트엔드 이미지를 다시 만들어 배포했다. `9b9149b` 이후 바뀐 것은 버전 문자열뿐이다(`backend/main.py`, `frontend/src/lib/version.ts`, `frontend/package.json`, `frontend/package-lock.json`).

| 검사 | 결과 |
| --- | --- |
| 백엔드 pytest (Python 3.12) | 1,653개 통과, 18개 건너뜀 |
| 프런트엔드 vitest, 타입 검사 | 378개 통과, 타입 검사 통과 |
| 이미지 내용 | 프런트엔드 번들에 `v2.37.1`과 RUM 엔드포인트가 있고 `v2.37.0`은 없다. 백엔드 `main.py`는 `2.37.1` |
| `cdk diff` | 작업 정의 8개(백엔드 7, 프런트엔드 1)의 이미지 URI만 바뀐다 |
| 서비스 | 백엔드 `:92`, 프런트엔드 `:97` 롤아웃 `COMPLETED`, 실행 컨테이너 digest가 배포값과 같다 |
| 운영 화면 (헤드리스 Chromium) | 헤더 `v2.37.1`, RUM SDK 로드, 수집 POST 5건 모두 200, JS 오류 없음 |
| 챗봇 비회원 질문 "지금 가장 빠른 모델은?" | 두 번째 호출 출력 722토큰, 답변 1,000자, 경고 없음, `final ok: true`, 9.7초 |
| 예약 작업 | 06:21 Insights `:71`, AutoProber `:78`이 새 digest로 종료 코드 0, 06:26 GptBench `:40` 실행 |

06:16:56 AutoProber 회차는 01:06:56과 같은 이유로 실행되지 않았다(이전 리비전 `:77`, `TaskDefinition is inactive`). 같은 날 Scheduler 스택을 갱신한 두 번 모두 한 회차가 빠졌으므로 일회성 경합이 아니라 매번 생길 수 있는 동작으로 본다.

배포 뒤 인사이트 두 건(42328, 42329)의 한국어 요약은 3,395자와 2,950자로 짧았지만 모두 `end_turn`이었다. 배포 전 3시간의 한국어 요약 40건도 모두 `end_turn`이었고 길이는 1,733~8,261자(중앙값 6,502자)였다. 원래 있던 편차 안이므로 회귀가 아니다.

| 대상 | 태그 | 작업 정의 리비전 |
| --- | --- | --- |
| 백엔드 | `v705c6ea` | 92 |
| 프런트엔드 | `v705c6ea` | 97 |
| AutoProber | `v705c6ea` | 78 |
| FeaturesVerify | `v705c6ea` | 29 |
| GptBench | `v705c6ea` | 40 |
| Insights | `v705c6ea` | 71 |
| ParityRun | `v705c6ea` | 51 |
| PricingSync | `v705c6ea` | 17 |

```text
Backend: 061525506239.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:v705c6ea@sha256:3edd8a24b57aa197614425824cdaabfc92b96f2dcfadf5d8ad3869b12f4ccec6
Frontend: 061525506239.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-frontend:v705c6ea@sha256:bf480d29f286a3d0e71a33d3bb9f2c1d2e6e03a67233b851ebead7fb322efd7c
```
