# ADR-035: 비용 단가 런 대비 변경 표시와 모델 탐색 일일 검증 런

- **Status**: Accepted
- **Date**: 2026-11-05
- **Related**: ADR-011 (Scheduler RunTask family 와일드카드), ADR-026 (Claude API Features 검증, 런 대비 변경 배너의 원형), ADR-030 (단가 자동 동기화), v2.40.0
- **Design**: [`docs/superpowers/specs/2026-11-05-change-tracking-and-explorer-verify-design.md`](../superpowers/specs/2026-11-05-change-tracking-and-explorer-verify-design.md)

## Context

사용자 요청(2026-11-05):

1. "비용 단가에 이전 런 대비 변경이 있으면 표기한다. Claude API 기능 검증처럼."
2. "모델 탐색도 1일 1회 런으로 검증하고, 이전 런 대비 변경이 있으면 표기한다. Claude API 기능 검증처럼."

`/pricing`은 12시간마다 공식 출처와 동기화되지만, 무엇이 바뀌었는지는 `price_history` 행을 직접 봐야 알 수 있었다. `price_sync_runs.summary`에는
채널별 분류(`unchanged`, `changed`, `pending` …)만 있고, 관리자 승인과 거부는 런과 무관하게 일어나 런 사이의 표 변화를 그대로 비교할 수 없었다.

`/models`의 코드 예제는 2026-10-19 점검에서 118개 중 48개가 실제로는 실패했다(`us.*` 리전, CP 헤더 `anthropic-workspace`, thinking 블록의
`content[0]["text"]` KeyError). 모두 예제 텍스트의 결함이었고 UI 테스트로는 보이지 않았다. 예제는 프런트(`modelExplorer.ts` `codeExamples`)에만
있어 백엔드가 실행할 수 없었다.

## Decision

1. **단가: 런 스냅샷과 비교** — `pricing_sync.run_sync`가 같은 트랜잭션 안에서(커밋 전, `db.flush()` 뒤) 활성 채널마다 `/pricing`이 보여 줄 값을
   `price_sync_runs.summary["snapshot"]`에 저장한다: 9필드 `shown`(`price_history.current_rows`), `shown`과 다른 대기 필드만 담은 `pending`
   (`no_baseline`이면 대기 행의 값 전부), 그 런의 채널 결과 `result`, 이름 표시용 `family_key`, `family`, `provider`, `tier`, `region`. JSON 열에
   키를 더할 뿐이라 스키마 변경은 없다. `pricing_changes.py`가 스냅샷이 있는 최근 `completed`/`partial` 런과 그 앞 런을 비교해 `channel`, `price`,
   `pending`, `check` 네 종류 항목을 만들고 `/api/pricing` `changes`로 내보낸다. 승인과 거부도 다음 스냅샷에 반영되므로 화면 문구는 "이전
   동기화(#N) 대비 변경"이고 경로(동기화 적용인지 승인인지)는 구분하지 않는다. 내보내기(CSV, Markdown, JSON)는 바뀌지 않는다.
2. **모델 탐색: 예제 생성을 백엔드로 옮겨 단일 출처로**(사용자 결정 A안) — `backend/model_explorer/examples.py`가 TS `codeExamples()`를 바이트
   단위로 옮긴다(골든 `tests/fixtures/explorer_examples_v2390.json`, 채널 유형별 대표 9개 × KO/EN). `/api/explorer/latest`가 이 함수로 예제를
   만들고, 매일 검증 런이 같은 함수의 EN 코드를 실행한다. 프런트 `codeExamples`는 지웠다(`channelOf`, `nativeId`, `modelLinks`는 남김).
3. **실행 방식** — 예제마다 새 임시 디렉터리에서 `sys.executable -I example.py`로 실행한다. 키 플레이스홀더는 `os.environ[...]` 식으로 바꿔 비밀
   값이 코드 텍스트에 들어가지 않고, 자식 env는 허용 목록(`AWS_*`, 키 4개, `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`)이라 스케줄 태스크의
   `DB_*`, `JWT_SECRET_KEY`, `SEED_ADMIN_PASSWORD`는 넘어가지 않는다. 호출당 90초, 실패는 1회 재시도, 출력은 저장 전에 비밀 값을 `***`로 가린다.
   종료 코드 0과 비어 있지 않은 stdout만 통과다.
4. **스케줄** — `ExplorerVerifyTaskDef`(autoprober 역할, 기본 env와 secret, 로그 그룹 `/ecs/explorer`)와 `ExplorerVerifySchedule`
   `cron(0 18 * * ? *)` Etc/UTC(03:00 KST, FeaturesVerify 17:30 뒤). Scheduler 역할 RunTask family `:*` 목록에 더했다(ADR-011). 새 IAM 정책,
   새 env는 없다.
5. **변경 표시** — `explorer_runs`, `explorer_results`(ORM + `create_all`). 셀 `(model_id, api_id)`의 상태나 `code_sha`가 직전 완료 런과 다르면
   변경이다: `catalog`(새 셀), `example`(코드가 바뀜 — 상태가 같아도), `measured`(같은 코드, 다른 상태). `stale_code`는 결과가 지금 예제보다 오래된
   코드로 측정됐다는 표시다. 실행 중 판정은 DB 기준(30분 안의 `running` 행)이다 — 스케줄 런은 별도 Fargate 태스크라 백엔드 프로세스가 모른다.

## Alternatives

- **B안: TS 유지 + 생성 JSON 커밋** — 모델 추가와 템플릿 수정마다 재생성 단계가 늘고, 런타임 등록 모델(CP)과 덤프 목록이 어긋날 수 있다. 기각.
- **C안: 백엔드가 같은 호출을 따로 구현(패리티 방식)** — 예제 텍스트 자체를 실행하지 않는다. 2026-10-19의 결함 3종은 모두 텍스트 결함이라 다시
  놓친다. 기각.
- **러너가 배포된 프런트에서 예제를 받아 실행** — 네트워크로 받은 코드를 비밀 값이 있는 태스크에서 실행하는 구조다. 기각.
- **단가 변경을 `price_history` 행에서 재구성** — 승인, 거부, `enriched` 채우기는 새 행을 만들지 않아 런 사이의 화면 변화를 정확히 되살릴 수 없다.
  스냅샷을 택했다.

## Consequences

- `/pricing`: 마지막 동기화 상자 아래 변경 배너(스냅샷 런이 둘이 되기 전에는 "변경 비교는 다음 동기화부터 표시됩니다."), 항목 → 셀 스크롤과 1.5초
  강조, 바뀐 셀에 "이전 대비 변경" 배지. 배포 직후 PricingSync를 두 번 돌려 기준선을 만든다.
- `/models`: 머리글에 최근 검증 런, 카드마다 검증 배지와 "변경" 표지, "검증 실패만" 필터, 변경 배너(항목 → 그 API 탭으로 모달), 모달의 검증 상자.
  모달 코드가 백엔드에서 오므로 `/api/explorer/latest`가 실패하면 모달 코드 영역에 재시도가 보이고, 카드는 `/api/models`만으로 그린다.
- 예제를 고칠 때는 `examples.py`만 고치고, 의도한 변경이면 골든 파일을 함께 바꾼다. 새 플레이스홀더는 `execute.PLACEHOLDERS`에 먼저 넣는다
  (테스트가 모르는 플레이스홀더를 잡는다).
- 하루 85건, "Hello!" + `max_tokens` 512라 토큰 비용은 하루 $1 미만으로 예상한다(첫 운영 런에서 실측해 기록한다).
- 로컬 스모크(`python -m explorer_runner --smoke`)는 `-I`가 사용자 site-packages를 끄므로 anthropic, openai, boto3가 설치된 venv에서 돌린다.
- 수동 실행(`POST /api/explorer/trigger`)은 1 GiB backend 서비스 태스크 안에서 돌아 예제를 동시에 2건씩 실행하고, 스케줄 태스크는 4건씩 실행한다.
