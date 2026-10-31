# 이력 조회 채널 목록 — 2026-10-31

사용자 요청(2026-10-29) "이력조회에서도 모델 모니터링과 동일하게 모델을 줄여주세요."를 반영해 배포했다. 앱 버전은 `v2.39.0` 그대로이고
변경은 CHANGELOG `Unreleased`에 있다. 배포 03:31:59–03:36:50 UTC, 확인 03:37–03:47.

## 원인

이력 조회(`HistoryPanel`)는 `GET /api/results/stats`로 조회 기간 안의 모든 노출 행을 채널별로 묶는다. v2.38.0(2026-10-27)에서 수집을 멈춘
OpenAI Mantle us-east-2, us-west-2 7채널은 라벨이 숨김 패턴에 걸리지 않으므로, 그 행이 창 안에 남은 7일과 30일 범위에서 56개가 보였다.
대시보드 모델 모니터링(`/api/models`)은 49개다. 24시간 범위는 이미 49개였다.

- GPT 5.5 (us-east-2)
- GPT 5.6 Sol (us-east-2)
- GPT 5.6 Terra (us-east-2), (us-west-2)
- GPT 5.6 Luna (us-east-2), (us-west-2)
- GPT 6 Astra (us-west-2)

## 수정 (`e5e8121`)

- `routers/results.py`: `get_stats`에 `active_only`(기본 false)를 더했다. true면 `ProbeResult.model_id`가 요청 시점의 `AVAILABLE_MODELS`에 있는
  행만 집계한다. Claude Platform on AWS와 OpenAI 채널은 기동 뒤 등록되므로 목록을 미리 복사하지 않는다.
- `HistoryPanel.tsx`, `lib/api.ts`: 이력 조회만 `active_only=true`를 보낸다. 파라미터가 없으면 응답은 예전과 같다.
- `(us-east-2)`, `(us-west-2)` 숨김 패턴은 넣지 않았다. Mantle 리전을 되살리면(ADR-033) 그 패턴이 새 채널까지 가린다. 저장 행은 지우지 않았다.

## 검증

| 검사 | 결과 |
| --- | --- |
| 백엔드 pytest (Python 3.12) | 1,640개 통과, 18개 건너뜀. 새 `test_results_stats_active.py` 3개 중 2개는 라우터 수정을 빼면 실패한다 |
| 운영 이미지 pytest (Python 3.11) | 1,638개 통과, 2개 실패 — 이미지에 없는 프런트엔드 소스를 대조하는 `test_pricing_sources.py` 2개로 이전 이미지와 같다 |
| Ruff, 프런트엔드 | Ruff 통과, 타입 검사 통과, vitest 388개 통과, e2e(프로덕션 빌드, Chromium) 141개 통과 |
| 이미지 내용 | 백엔드 `routers/results.py`에 `active_only`, `main.py` `2.39.0`. 프런트엔드 번들에 `active_only`, RUM 엔드포인트, `v2.39.0` |
| `cdk diff` | 작업 정의 8개(백엔드 7, 프런트엔드 1)의 이미지 URI만 바뀐다. env, IAM, 보안 그룹 변경 없음 |
| 스택 | 두 스택 `UPDATE_COMPLETE`(AppServices 222초, Scheduler 41초) |
| 서비스 | 백엔드 `:95`, 프런트엔드 `:100` 롤아웃 `COMPLETED`, 실행 컨테이너 digest가 배포값과 같다 |

배포 전후 `/api/results/stats` 채널 수(배포 전 운영은 `active_only`를 모르는 코드라 무시했다):

| 범위 | 배포 전 (파라미터 무관) | 배포 후, 파라미터 없음 또는 `false` | 배포 후, `active_only=true` |
| --- | --- | --- | --- |
| 24시간 | 49 | 49 | 49 |
| 7일 | 56 | 56 | 49 |
| 30일 | 56 | 56 | 49 |

- 30일 `active_only=true` 응답의 `model_id` 집합이 `/api/models` 49개와 같다.
- 운영 화면(헤드리스 Chromium, `llm-monitor.whchoi.net`): 이력 조회 24시간, 7일, 30일 모두 카드 49개, us-east-2와 us-west-2 채널 0개.
  통계 요청 3번 모두 `active_only=true`, 200. 헤더 `v2.39.0`, JS 오류 없음. 대시보드, 신뢰성, 비용 페이지에서 RUM 수집 POST 7건 모두 200.

## 예약 작업

- Scheduler 갱신이 03:36:51 회차 전에 끝나 빠진 회차가 없었다. 03:36:51 Insights `:74`, 03:36:56 AutoProber `:81`이 새 digest로 종료 코드 0.
- AutoProber run 44860은 49행(Anthropic 8, Bedrock 19, OpenAI 22) 모두 `success`.
- 03:41:21 GptBench `:43` 종료 코드 0. `cycle start: 18 channels x 10 runs`, `GPT bench lanes: cris=11 mantle-us-east-1=7`,
  `cycle done: rows=180 errors=0 skipped=none elapsed=255s`.

## 남은 것

비용(30일, 2026-11-26까지)과 신뢰성(7일, 2026-11-03까지) 화면에는 같은 7채널이 창에서 빠질 때까지 보인다. 이번 요청 범위 밖이라 그대로 두었다.
같은 요청이 오면 그 라우터에도 같은 방식(현행 카탈로그 필터)을 쓴다.

| 대상 | 태그 | 작업 정의 리비전 |
| --- | --- | --- |
| 백엔드 | `ve5e8121` | 95 |
| 프런트엔드 | `ve5e8121` | 100 |
| AutoProber | `ve5e8121` | 81 |
| FeaturesVerify | `ve5e8121` | 32 |
| GptBench | `ve5e8121` | 43 |
| Insights | `ve5e8121` | 74 |
| ParityRun | `ve5e8121` | 54 |
| PricingSync | `ve5e8121` | 20 |

```text
Backend: 061525506239.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:ve5e8121@sha256:f0107522391adc980f63c4c65b0aac6c633d845fd1d1cf096c677e250857686e
Frontend: 061525506239.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-frontend:ve5e8121@sha256:2ab26e93cfb3393a0b46c01e118b03a66e140bd014828309ff5f07dd05ba5b9d
```

롤백 지점은 v2.39.0(`v4dc439a`, digest는 [2026-10-27-v239-deployment.md](2026-10-27-v239-deployment.md))이다. 스키마와 env 변경이 없으므로
그 digest로 두 스택을 digest 고정 CDK 배포하면 된다.
