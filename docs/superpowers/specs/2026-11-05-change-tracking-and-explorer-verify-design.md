# Design: 비용 단가 런 대비 변경 표시 + 모델 탐색 일일 검증 런 (v2.40.0)

- **Date**: 2026-11-05
- **Branch**: `feat/v2-40-change-tracking-explorer-verify` (main `c96a592`, v2.39.0 배포본 기준)
- **Version**: v2.40.0
- **Status**: Approved (design) — 2026-11-05 사용자 요청과 결정 반영
- **Related**: ADR-026(Claude API Features 검증, 런 대비 변경 배너의 원형), ADR-030(단가 자동 동기화), ADR-011(Scheduler RunTask 와일드카드). 이 작업은 ADR-035로 기록한다.

## 사용자 요청 (2026-11-05)

1. 비용 단가에 이전 런 대비 변경이 있으면 표기한다. Claude API 기능 검증처럼.
2. 모델 탐색도 1일 1회 런으로 검증하고, 이전 런 대비 변경이 있으면 표기한다. Claude API 기능 검증처럼.

## 사용자 결정

| 질문 | 결정 |
|---|---|
| 모델 탐색 검증 범위 | **코드 예제 실행.** 화면의 코드 예제(Converse, InvokeModel, Messages, Responses)를 모델마다 실제로 실행해 통과/실패를 기록한다. 연결 링크 확인은 하지 않는다 |
| 비용 단가 "변경"의 기준 | **화면 값 + 검토 대기 표시.** 표에 보이는 9필드 단가의 변경을 변경으로 보고, 승인 대기로 들어간 관측값도 "검토 대기" 태그로 함께 표시한다. 새 채널, 빠진 채널, 출처 확인 실패도 각자 태그로 표시한다 |
| 코드 예제의 출처 | **A안: 예제 생성을 백엔드로 옮겨 단일 출처로.** 화면에 보이는 코드와 러너가 실행하는 코드를 같은 Python 함수가 만든다 |

검토하고 버린 안:

- B안(TS 유지 + 생성 JSON 커밋): 모델 추가와 템플릿 수정마다 재생성 단계가 늘고, 런타임 등록 모델(CP)과 덤프 목록이 어긋날 수 있다.
- C안(백엔드가 동등한 호출을 따로 구현, 패리티 방식): 예제 텍스트 자체를 실행하지 않는다. 2026-10-19에 찾은 결함(CP 헤더 `anthropic-workspace`, `content[0]["text"]` KeyError, `us.*` 리전)은 모두 예제 텍스트의 결함이라 다시 놓친다.
- 러너가 배포된 프런트에서 예제를 받아 실행: 네트워크로 받은 코드를 비밀 값이 있는 태스크에서 실행하는 구조라 제외했다.

## 범위 밖

- 연결 링크(HTTP) 확인
- 단가 변경의 내보내기(CSV, Markdown, JSON) 반영 — 내보내기 출력은 바뀌지 않는다
- 기존 단가 동기화 런의 소급 스냅샷 — 배포 뒤 수동 런 두 번으로 기준선을 만든다
- 변경 알림(이메일, Slack)
- 모델 탐색 변경 목록의 "직전 런에만 있던 셀"(모니터링에서 뺀 모델) — Claude API 기능 검증, 패리티와 같이 무시한다

---

## Part A. 모델 탐색 일일 검증

### A1. 예제 생성 이전 — `backend/model_explorer/examples.py`

- 프런트 `frontend/src/lib/modelExplorer.ts`의 `codeExamples()`를 Python으로 옮긴다. 순수 함수이고 DB, 네트워크를 쓰지 않는다.
- `code_examples(model_id) -> list[CodeExample]`. 한 예제는 언어별 두 벌을 함께 가진다.

```python
{"api_id": "invoke_model",            # 고정 키 converse | invoke_model | messages | responses
 "api": "InvokeModel API",            # 탭 표시 이름
 "label": "Python (boto3)",
 "language": "python",
 "description": {"ko": "...", "en": "..."},
 "code": {"ko": "...", "en": "..."},
 "code_sha": "<sha256(code['en'])>"}
```

- 채널 판별(`global.`/`us.` 프로파일, `bedrock:<region>:`, `anthropic:`, `openai:<region>:`, `openai:global:`, `openai:us:`, `openai:1p:`), 호출 리전(`us.*` → us-east-1, 나머지 프로파일 → ap-northeast-2, in-region은 키의 리전), 호출 모델 ID는 TS와 같은 규칙이다. Python 쪽에는 예제에 필요한 만큼만 둔다(`_channel`, `_native_id`).
- 프런트의 `channelOf`, `nativeId`, `modelLinks`는 배지, 필터, 호출 ID 표시, 링크에 계속 쓰므로 그대로 둔다. `codeExamples`만 지운다.
- **이전 무손실**: 옮기기 전에 현재 TS가 만드는 예제를 골든 `backend/tests/fixtures/explorer_examples_v2390.json`으로 덤프한다. 대표 id 9개(Global Claude, US Claude, Nova, 서울 In-Region, CP, Mantle 리전, OpenAI Global, OpenAI US, 1P) × KO/EN. pytest가 Python 출력과 바이트 단위로 같음을 고정한다. 덤프는 node가 `modelExplorer.ts`를 직접 import하는 방법을 쓴다(2026-10-19 점검과 같은 기법).
- **KO/EN은 주석만 다르다**: `#`로 시작하는 줄(앞 공백 제외)을 지운 두 코드가 같아야 한다(pytest). 그래서 러너는 EN 코드 하나만 실행하고, `code_sha`는 EN 코드(치환 전 원문)의 SHA-256이다.

### A2. 예제 1건 실행 — `backend/model_explorer/execute.py`

**플레이스홀더 치환** (문자열 리터럴 전체를 식으로 바꾼다. 비밀 값 자체는 코드 텍스트에 들어가지 않는다)

| 예제 속 리터럴 | 치환 결과 |
|---|---|
| `"<ANTHROPIC_API_KEY>"` | `os.environ["ANTHROPIC_API_KEY"]` |
| `"<ANTHROPIC_WORKSPACE_ID>"` | `os.environ["ANTHROPIC_WORKSPACE_ID"]` |
| `"<ABSK-...>"` | `os.environ["OPENAI_API_KEY"]` |
| `"<OPENAI_API_KEY>"` (1P 예제) | `os.environ["OPENAI_1P_API_KEY"]` |

- 코드 맨 앞에 `import os`를 붙인다.
- 치환 뒤에도 `"<...>"` 형태의 리터럴이 남으면 실행하지 않고 `skipped`(사유 "알 수 없는 플레이스홀더")다. 예제가 쓰는 env가 비어 있으면 `skipped`(사유 "자격 증명 미주입: <이름>").

**실행**

- 예제마다 새 임시 디렉터리(`tempfile.mkdtemp`)에 `example.py`를 쓰고 그 디렉터리를 cwd로 `sys.executable -I example.py`를 서브프로세스로 실행한다. `-I`는 `PYTHON*` env와 사용자 site, 스크립트 디렉터리의 `sys.path` 추가를 끈다. 끝나면 디렉터리를 지운다.
- **자식 env는 허용 목록만**: 이름이 `AWS_`로 시작하는 변수(Fargate 태스크 역할의 `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` 포함), `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, `OPENAI_API_KEY`, `OPENAI_1P_API_KEY`, `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`. 스케줄 태스크에 있는 `DB_*`, `JWT_SECRET_KEY`, `SEED_ADMIN_PASSWORD`, `AGENTCORE_MEMORY_ID`는 자식에 가지 않는다.
- 호출당 상한 `EXPLORER_CALL_TIMEOUT_S`(기본 90초). 넘으면 `subprocess.run(timeout=…)`이 자식을 죽인다.

**판정**

| 결과 | 상태 |
|---|---|
| 종료 코드 0, stdout이 공백이 아님 | `passed` |
| 종료 코드 0, stdout이 비어 있음 | `failed` ("출력 없음" — thinking 블록만 받아 text를 못 찍은 경우가 여기 걸린다) |
| 종료 코드 ≠ 0 | `failed` (stderr 마지막 비어 있지 않은 줄 = 예외 한 줄 + stderr 꼬리 1,500자) |
| 상한 초과 | `failed` ("시간 초과 90초") |
| 위 플레이스홀더, env 사유 | `skipped` |

- `failed`면 한 번 다시 실행한다(서비스 플랩 완화). `attempts`에 1 또는 2를 남기고, 두 번째 결과로 판정한다.
- 저장 전 stdout, stderr에서 비밀 값 문자열(위 키 4개와 `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_CONTAINER_AUTHORIZATION_TOKEN` 중 값이 8자 이상인 것)을 `***`로 바꾼다. 결과는 공개 API로 나간다.
- `output_excerpt`는 가린 뒤 stdout 앞 300자다.

### A3. 러너 — `backend/model_explorer/runner.py`, `backend/explorer_runner.py`

- `run_explorer(model_ids=None) -> run_id`
  1. `explorer_runs`에 `running` 행을 넣고 바로 커밋한다(긴 트랜잭션 금지).
  2. 대상 모델: `prober.AVAILABLE_MODELS` 중 `visibility`의 숨김 패턴에 걸리지 않는 것. CLI는 먼저 `_discover_anthropic_models()`, `_register_openai_models()`를 부른다(`pricing_sync_runner`와 같은 순서). 1P 키가 주입되지 않으면 1P 채널은 등록되지 않으므로 대상에서도 빠진다.
  3. 잡 = 모델 × 그 모델의 예제. 2026-11-05 기준 49모델 → **85건**(Bedrock Claude 18 × 3, Nova 1 × 1, CP 8 × 1, OpenAI 22 × 1).
  4. `ThreadPoolExecutor(4)`로 실행하고, 결과 행은 메인 스레드에서 모아 한 번에 저장한다(스레드별 DB 세션 금지).
  5. 런 전체 상한 `EXPLORER_RUN_DEADLINE_S`(기본 1200초). 넘으면 시작하지 못한 잡은 `skipped`(사유 "런 시간 상한")로 기록한다.
  6. 끝나면 `completed` + totals. 예외면 `failed` + `error_message`(원 예외는 다시 올린다).
  7. 보존: 최근 `KEEP_RUNS = 60`런. 정리 실패는 로그만 남기고 완료된 런을 덮어쓰지 않는다.
- CLI: `python -m explorer_runner --once`(DB 기록), `python -m explorer_runner --smoke [--models id,id] [--json]`(DB 없이 표 출력). `--once`는 `create_tables()`를 먼저 부르고, 끝은 `os._exit`(`auto_prober_runner`와 같은 이유 — 남은 스레드가 태스크를 RUNNING으로 붙잡지 않게).

### A4. 테이블 (ORM + `create_all`, lifespan ALTER 없음)

```text
explorer_runs:    id, started_at, finished_at, status(running|completed|failed),
                  totals JSON {passed, failed, skipped}, error_message
explorer_results: id, run_id(FK), model_id, model_name, api_id, status(passed|failed|skipped),
                  latency_ms, attempts, code_sha, output_excerpt, error_message
                  INDEX ix_explorer_results_run_id(run_id)
```

### A5. 변경 비교 — `backend/model_explorer/diff.py`

- 셀 키 `(model_id, api_id)`. 현재 런의 셀마다 직전 완료 런과 비교한다.
- 상태가 다르거나 `code_sha`가 다르면 변경이다.

| kind | 조건 | 화면 태그 |
|---|---|---|
| `catalog` | 직전 런에 없던 셀(새 모델, 새 API) | 신규 |
| `example` | `code_sha`가 다름(상태가 같아도 포함 — 릴리스로 바뀐 예제가 계속 통과하는지 보여 준다) | 예제 변경 |
| `measured` | 같은 코드, 상태만 다름 | 실측 |

- 직전 런에만 있던 셀은 무시한다.
- 순서: 프런트 정렬과 같은 모델 순서는 프런트가 맡고, 백엔드는 `(model_id, api_id)` 순으로 보낸다.

### A6. API — `backend/routers/explorer.py` (새 라우터, `main.py`에 등록)

**`GET /api/explorer/latest`** (공개, `Cache-Control: public, max-age=0, s-maxage=60`)

- `lang` 파라미터는 두지 않는다. 설명과 코드를 KO/EN 두 벌 모두 보낸다. 언어 토글이 다시 요청하지 않아도 되고, CloudFront 캐시 키에 쿼리 문자열이 들어가는지와 상관없이 안전하다.

```json
{
  "run": {"id": 12, "started_at": "…Z", "finished_at": "…Z",
          "totals": {"passed": 83, "failed": 1, "skipped": 1}},
  "running": false,
  "previous_run_id": 11,
  "changes": [{"model_id": "...", "model_name": "...", "api_id": "invoke_model", "api": "InvokeModel API",
               "before": "passed", "after": "failed", "kind": "measured"}],
  "models": {
    "<model_id>": {"examples": [{"api_id": "...", "api": "...", "label": "...", "language": "python",
                                 "description": {"ko": "...", "en": "..."}, "code": {"ko": "...", "en": "..."},
                                 "code_sha": "...",
                                 "result": {"status": "passed", "latency_ms": 1180, "attempts": 1,
                                            "error_message": null, "output_excerpt": "Hello! ...",
                                            "run_id": 12, "verified_at": "…Z", "stale_code": false}}]}
  }
}
```

- `models`는 요청 시점의 `AVAILABLE_MODELS`(숨김 제외)와 `examples.py`로 만든다. `result`는 최근 완료 런의 같은 셀이고 없으면 null(검증 전).
- `stale_code`: 그 셀의 저장된 `code_sha`가 지금 예제의 `code_sha`와 다르면 true.
- `run`은 최근 **완료** 런, 없으면 null. `running`은 DB 기준이다 — 시작한 지 30분이 안 된 `running` 행이 있으면 true(Fargate 태스크와 백엔드 프로세스가 분리돼 있어 프로세스 안 플래그로는 모른다. `/api/auto-probe/status`와 같은 원칙).
- 숨김 모델(`visibility.visible_only`)은 `models`와 `changes`에서 모두 뺀다.

**`POST /api/explorer/trigger`** (JWT)

- 백엔드 안 데몬 스레드로 `run_explorer()`를 돌린다. 프로세스 안 잠금이 잡혀 있거나 DB에 30분 안의 `running` 행이 있으면 `{"triggered": false, "message": "이미 실행 중입니다"}`.
- 응답 문구: "모델 탐색 검증 런을 시작했습니다 (약 2분 소요)".

### A7. 화면 — `/models` (`ModelExplorer.tsx`, 새 `lib/explorerVerify.ts`)

- 데이터: 기존 `/api/models`(카드 목록), `/api/pricing`(단가)에 더해 `/api/explorer/latest`를 `useAsyncResource`로 받는다.
- **머리글 맥락 줄**: "최근 검증 런 #N, 시각, 소요, 통과 a, 실패 b, 건너뜀 c". `running`이면 "● 런 실행 중…". 액션 자리에 **"검증 런 실행"** 버튼(비로그인이면 공용 로그인 대화상자, 응답 메시지 표시 — `ClaudeFeaturesPanel.handleTrigger`와 같은 흐름).
- 마지막 완료 런이 26시간을 넘으면 amber 경고 줄 "마지막 완료된 검증이 26시간 이상 지났습니다. 현재 상태와 다를 수 있습니다."
- **이전 런 대비 변경 배너** (Claude API 기능 검증과 같은 모양)
  - `previous_run_id`가 있고 변경 0건: "이전 런(#N) 대비 변경 없음." 카드
  - 변경이 있으면 amber `<details>`: "이전 런(#N) 대비 변경 K건", 요약 줄 "신규 a건, 예제 변경 b건, 실측 변경 c건", 항목 "[실측] Claude Opus 5 (Global), InvokeModel API: 통과 → 실패". 10건이 넘으면 "외 N건".
  - 항목을 누르면 그 모델의 상세 모달이 **해당 API 탭으로** 열린다. 모델이 지금 카드 목록에 없으면 버튼을 비활성화한다.
- **카드**: 기존 채널 배지 옆에 검증 배지 — 전부 통과 "✓ 3/3 통과"(emerald), 실패가 있으면 "✗ 1/3 실패"(rose), 실행된 셀이 없으면 "검증 전"(gray), 통과와 건너뜀만 있으면 "✓ 2/3 통과, 1 건너뜀". 변경 셀이 있으면 amber "변경" 표지.
- **필터**: 채널 필터 옆에 "검증 실패만" `aria-pressed` 토글. 필터 초기화에 포함한다.
- **상세 모달**의 각 API 탭: 설명 아래 검증 상자
  - 통과: "검증 통과, 1.2초, 2026-11-05 03:01 (런 #12)" + 출력 앞부분(mono)
  - 실패: 예외 한 줄 + `<details>`로 펼치는 stderr 꼬리, 시도 2회면 "다시 시도 뒤에도 실패"
  - 건너뜀: 사유
  - `stale_code`: "이 예제는 마지막 검증(런 #12) 뒤에 바뀌었습니다. 다음 런에서 다시 검증합니다."
  - 검증 전: "아직 검증하지 않았습니다."
- 예제 코드는 explorer API에서 오므로, 이 API가 실패하면 모달 코드 영역에 `DataError`(재시도)를 보여 준다. 카드 그리드는 `/api/models`만으로 계속 그린다. explorer 응답에 그 모델이 없으면 "이 모델의 코드 예제를 불러오지 못했습니다."
- `lib/explorerVerify.ts`(순수 함수, vitest): `summarizeModel(examples)`(통과, 실패, 건너뜀, 합계, 배지 등급), `changeKindLabel`, `statusLabel`, `hasFailure`, `changedModelIds`.
- 문구는 이 패널의 기존 방식대로 인라인 `L(en, ko)`이고, 한글 문장은 쉼표 열거와 단정형을 쓴다.

---

## Part B. 비용 단가 런 대비 변경

### B1. 런 스냅샷 — `backend/pricing_sync.py`

- `run_sync`의 `_apply` 루프 뒤, 같은 트랜잭션 안에서(커밋 전, autoflush로 새 행 반영) 활성 채널 전부의 화면 상태를 `price_sync_runs.summary["snapshot"]`에 넣는다. JSON 열에 키를 더하는 것이라 스키마 변경이 없다.

```json
"snapshot": {
  "version": 1,
  "channels": {
    "<model_id>": {"family_key": "claude-sonnet-5-5", "family": "Claude Sonnet 5.5", "provider": "anthropic",
                   "tier": "global",
                   "shown":   {"input": 2.0, "output": 10.0, "cache_read": 0.1, "...": null},
                   "pending": {"cache_read": 0.05},
                   "result": "unchanged"}
  }
}
```

- `shown`: `price_history.current_rows(db, active, now=finished_at)`의 9필드(`pricing_sync.PRICE_FIELDS` 순). 현재 행이 없으면 null.
- `pending`: `price_history.pending_rows`의 대기 행 중 **`shown`과 값이 다른 필드만**(대기 행은 저장 값과 합친 9필드 전체를 갖고 있어 그대로 두면 바뀌지 않은 필드까지 변경으로 잡힌다). 대기 행이 없거나 다른 필드가 없으면 null. `shown`이 null(`no_baseline` — 현재 행 없이 대기 행만 있는 채널)이면 대기 행의 null이 아닌 필드 전부를 담는다.
- `result`: 이번 런의 채널 분류(`channels[model_id]` — `unchanged`, `changed`, `enriched`, `pending`, `no_baseline`, `rejected`, `skipped:*`).
- `family`, `provider`, `tier`를 스냅샷에 함께 담아, 나중에 카탈로그에서 빠진 채널도 이름을 보여 줄 수 있게 한다.
- 내부 오류로 `failed`가 된 런은 스냅샷이 없다.

### B2. 비교 — `backend/pricing_changes.py` (새 파일, 순수 함수)

- 대상 런: `finished_at`이 있고 status가 `completed` 또는 `partial`이며 스냅샷이 있는 가장 최근 런 R, 그리고 그보다 앞선 `completed`/`partial` 런 중 가장 최근 런 P. P에 스냅샷이 없으면 `available: false`(v2.40.0 배포 직후). `failed` 런은 건너뛴다.
- 모든 값은 이미 소수 6자리로 정규화돼 있으므로 그대로 비교한다.

| kind | 조건 | before / after | 화면 태그 |
|---|---|---|---|
| `channel` | 한쪽 스냅샷에만 있는 채널 | `null` → `"present"`(신규) / `"present"` → `null`(제외) | 신규 채널, 제외 채널 |
| `price` | 양쪽에 있는 채널의 `shown[field]`가 다름 (동기화 적용, 관리자 승인, 빈 필드 첫 관측 포함 — 첫 관측은 before null) | 숫자 또는 null | 적용 |
| `pending` | `pending[field]`가 다름 (null → 값 = 대기 시작, 값 → null = 승인이나 거부로 해제) | 숫자 또는 null | 검토 대기, 검토 해제 |
| `check` | 확인 범주가 다름. 범주 = `result`가 `skipped:`로 시작하면 그 문자열, 아니면 `"ok"` | `"ok"` ↔ `"skipped:<사유>"` | 확인 실패, 확인 복구 |

- 신규, 제외 채널은 `channel` 항목 하나만 낸다(그 채널의 필드별 항목은 내지 않는다).
- 항목 순서: `PROVIDER_ORDER` → `FAMILY_ORDER` → tier(`cp`, `openai_list`, `global`, `us`, `in_region`) → kind(`channel`, `price`, `pending`, `check`) → 필드(`PRICE_FIELDS` 순).
- 직전 런과 현재 런 사이의 관리자 승인, 거부도 현재 런 스냅샷에 반영되므로, 화면 문구는 "이전 동기화(#N) 이후 바뀐 표 값"이다. 바뀐 경로(동기화 적용인지 승인인지)는 구분하지 않는다.

### B3. API — `GET /api/pricing` 응답에 `changes` 추가

```json
"changes": {
  "available": true,
  "run_id": 141, "finished_at": "…Z",
  "previous_run_id": 140, "previous_finished_at": "…Z",
  "items": [{"model_id": "global.anthropic.claude-sonnet-5-5", "family_key": "claude-sonnet-5-5",
             "family": "Claude Sonnet 5.5", "provider": "anthropic", "tier": "global",
             "kind": "price", "field": "cache_read", "before": 0.2, "after": 0.1}]
}
```

- 비교 기준이 없으면 `{"available": false, "run_id": <R 또는 null>}`.
- 60초 프로세스 캐시와 `invalidate_cache()`(관리자 승인, 거부 뒤)는 그대로 적용된다.
- `pricing_export`(CSV, Markdown, JSON 내보내기)는 바뀌지 않는다.

### B4. 화면 — `/pricing` (`PricingPanel.tsx`, `lib/pricingTable.ts`)

- "마지막 공식 단가 동기화" 상자 바로 아래에 변경 배너
  - `available: false`: 회색 안내 카드 "변경 비교는 다음 동기화부터 표시됩니다."
  - 0건: "이전 동기화(#140, 2026-11-04 15:00) 대비 변경 없음." 카드
  - 있으면 amber `<details>`: "이전 동기화(#140, 2026-11-04 15:00) 대비 변경 K건". 항목 예
    - "[적용] Claude Sonnet 5.5, AWS Bedrock - Global CRIS, 캐시 읽기 $0.20 → $0.10"
    - "[검토 대기] GPT 6 Sol, AWS Bedrock - US CRIS, 입력 — → $3.30"
    - "[확인 실패] Claude Opus 5, Claude Platform on AWS, 문서 파싱 실패"
    - "[신규 채널] GPT 6.1 Terra, AWS Bedrock - Global CRIS"
  - 10건이 넘으면 "외 N건". 금액은 기존 `formatUnitPrice`, 열 이름은 `tierLabel`, 필드 이름은 기존 캐시와 긴 컨텍스트 줄의 용어(입력, 출력, 캐시 읽기, 쓰기, 1시간 쓰기, 긴 컨텍스트 입력 …)를 쓴다.
- 항목을 누르면 표의 해당 셀로 스크롤하고 1.5초 강조한다. 셀에 `id="price-<family_key>-<tier>"`를 둔다(기존 각주 `#ref-n` 강조와 같은 타이머 방식). 제외 채널처럼 표에 셀이 없으면 버튼이 아니라 글자로 둔다.
- **셀 배지**: 이번 비교의 `price`, `pending`, `check` 항목이 걸린 셀에 `tierBadges` 체계로 amber **"이전 대비 변경"** 배지 + 회색 상세 글자(첫 항목, 예 "캐시 읽기 $0.20 → $0.10", 둘 이상이면 "외 N건"). `title`만 쓰는 툴팁은 만들지 않는다(기존 규칙). 신규 채널 셀에는 "신규 채널" 배지.
- 순수 함수(`lib/pricingTable.ts`, vitest): `changeItemText(item, lang)`, `changeKindTag(item)`, `priceCellId(family_key, tier)`, `cellChangeBadge(items, family_key, tier, lang)`.

---

## 스케줄과 배포

### CDK — `cdk/lib/stacks/scheduler-stack.ts`

- `ExplorerVerifyTaskDef` = `buildTaskDef("ExplorerVerifyTaskDef", autoProberTaskRole, ["python", "-m", "explorer_runner", "--once"], "/ecs/explorer")`. 기존 env와 secret을 그대로 받는다. 새 env, 새 IAM 정책은 없다(autoProber 역할에 Bedrock 프로파일과 FM 호출 권한이 있고, CP와 ABSK 키는 secret으로 이미 주입된다).
- `ExplorerVerifySchedule`: `cron(0 18 * * ? *)` Etc/UTC = 매일 03:00 KST 고정. FeaturesVerify(17:30 UTC, 약 13분) 뒤라 같은 모델 호출이 겹치지 않는다. `rate(24 hours)`는 쓰지 않는다(생성 시각에 묶인다).
- `schedulerInvokeRole`의 `RunTaskFamilyWildcard`에 새 family `:*`를 더한다(ADR-011).
- jest: 스케줄 개수, cron 식, RunTask 리소스 목록, 새 task def 명령과 로그 그룹.

### 실행 시간과 비용 예상

- 85건 ÷ 동시 4 → 1~2분(서브프로세스 기동 약 1초 + 호출 1초 안팎). 메모리는 부모 + 자식 4개로 1 GiB 안쪽.
- 프롬프트 "Hello!", `max_tokens` 512라 토큰 비용은 하루 $1 미만으로 예상한다. 첫 라이브 런에서 실측해 보고한다.

### 릴리스 v2.40.0

- 버전 표기: `frontend/src/lib/version.ts`, `backend/main.py` `FastAPI(version=…)`, `frontend/package.json`과 `package-lock.json` 2곳, README 배지, `CLAUDE.md` 개요, `CHANGELOG.md` + 태그 `v2.40.0`.
- 문서: ADR-035, `docs/architecture.md`, `docs/api-reference.md`(`/api/explorer/*`, `/api/pricing` `changes`), 루트, `backend/`, `backend/routers/`, `frontend/src/components/` CLAUDE.md, `docs/runbooks/`(수동 ExplorerVerify run-task 명령).

### 배포 순서

1. backend, frontend 이미지 빌드(불변 태그 + digest, frontend RUM build args 포함)
2. `cdk deploy BedrockMonitor-AppServices BedrockMonitor-Scheduler -c backendImage=<전체 URI>:<tag>@sha256:… -c frontendImage=…`
3. 서비스와 스케줄 task def digest 확인(2026-07-09 되돌림 사고 방지)
4. ExplorerVerify 수동 run-task 1회 → 첫 런 생성
5. PricingSync 수동 run-task **2회**(앞 런이 끝난 뒤) → 두 번째 런에서 "변경 없음"이 나와야 정상
6. 운영 `/models`, `/pricing`을 Playwright로 확인(KO/EN, 390px)

배포 전에 로컬에서 `python -m explorer_runner --smoke`로 85건 전부를 SSM 자격 증명으로 돌린다. 실패 건은 예제 결함인지 서비스 쪽 문제인지 먼저 가리고 보고한다.

---

## 테스트

**backend pytest (오프라인)**

- `test_explorer_examples.py`: 골든 바이트 일치(대표 id 9 × KO/EN), KO/EN 주석 외 동일, 채널 유형별 `api_id` 집합, 활성 모델 전부가 예제 1개 이상, 모든 플레이스홀더가 치환 표에 있음, `code_sha`가 EN 원문 해시
- `test_explorer_execute.py`: 가짜 스크립트를 실제 서브프로세스로 실행 — 통과, 예외, 빈 출력, 시간 초과(짧은 상한), 재시도 1회, env 누락 → skipped, 모르는 플레이스홀더 → skipped, 자식 env에 `DB_PASSWORD`, `JWT_SECRET_KEY` 없음, 치환된 코드 텍스트에 비밀 값 없음, stdout/stderr 비밀 값 가림
- `test_explorer_runner.py`: 가짜 실행기 + SQLite — 행 저장, totals, 숨김 모델 제외, 런 상한 → skipped, 예외 시 `failed`, 60런 정리, 정리 실패가 런을 덮어쓰지 않음
- `test_explorer_router.py`: latest(런 없음, 직전 런 없음, kind 3종, `stale_code`, 숨김 모델 필터, DB 기준 `running`), trigger 401과 중복 실행
- `test_pricing_changes.py`: kind 4종, 첫 관측 before null, 대기 시작과 해제, 확인 실패와 복구, 채널 추가와 제외(필드 항목 없음), 직전 스냅샷 없음 → `available: false`, `failed` 런 건너뜀, 항목 순서
- 기존 단가 동기화 테스트 확장: `run_sync`가 스냅샷을 남기고 `shown`이 `current_rows`와 같음, 대기 필드는 `shown`과 다른 것만, `/api/pricing` `changes` 블록, 내보내기 골든 불변

**frontend vitest**: `explorerVerify.test.ts`(요약, 배지, 라벨, 실패 필터), `pricingTable.test.ts` 확장(변경 문구, 태그, 셀 id, 셀 배지). `modelExplorer.test.ts`에서 `codeExamples` 부분은 pytest 골든으로 옮겨 지우고 `channelOf`, `nativeId`, `modelLinks` 테스트는 유지한다.

**e2e (Playwright, fixture API)**: `/models` — 검증 배지, 변경 배너와 "변경 없음" 카드, 배너 항목 → 모달이 해당 탭으로 열림, 실패 상자, `stale_code` 안내, explorer API 실패 시 카드는 남고 모달에 재시도. `/pricing` — 배너 3상태, 항목 → 셀 강조, "이전 대비 변경" 배지, 390px 가로 넘침 없음. 기존 `pricing.spec.ts`(메뉴 순서, 표 구조)는 그대로 통과해야 한다.

**CDK jest**: 새 task def, 스케줄, cron, RunTask 와일드카드.

**라이브**: 배포 전 `explorer_runner --smoke` 85건, 배포 후 수동 ExplorerVerify 1회와 PricingSync 2회, 운영 화면 Playwright, `make verify`.

## 위험과 대응

| 위험 | 대응 |
|---|---|
| 예제가 서비스 플랩(429, 5xx)으로 하루 실패 → 다음 날 복구가 "실측 변경"으로 두 번 보임 | 실패 시 1회 재시도. 그래도 남는 플랩은 실측 변경으로 정직하게 보인다(Claude API 기능 검증과 같다) |
| 이전 과정에서 예제 텍스트가 미묘하게 바뀜 | TS 골든과 바이트 일치 테스트 |
| 자식 프로세스로 비밀 값이 새거나 결과에 찍힘 | env 허용 목록, 플레이스홀더는 `os.environ[...]` 식, 저장 전 가림, 테스트로 고정 |
| 모델 추가 시 예제가 빠짐 | "활성 모델 전부가 예제 1개 이상" 테스트. 예제 규칙이 채널 유형 단위라 보통 코드 수정이 필요 없다 |
| 단가 비교 기준선이 배포 직후 없음 | `available: false` 안내 + 배포 단계 5의 수동 런 2회 |
| 백엔드가 예제를 내려주므로 `/models` 모달이 백엔드 응답에 의존 | 카드는 `/api/models`로 계속 렌더링, 모달만 재시도 표시 |
