# Runbook — 트러블슈팅

증상별 확인과 조치. 배포 절차는 [deploy.md](deploy.md), 되돌리기는 [rollback.md](rollback.md)를 본다.

## Claude Platform on AWS 채널 전부 429 — 월간 사용량 상한 (2026-09-23, v2.29.0에서 재시도 제거)

**배경**: 2026-09-23 19:52 UTC부터 CP on AWS 호출이 전부 429로 거부됐다. 조직이 API 등급(tier)에 따라 정해진 월간
사용량 상한을 넘겼기 때문이며, 상한은 2026-10-01 00:00 UTC에 풀린다. v2.28.2까지는 이 429를 일시 rate limit으로 보고
prober 루프(4회 시도)와 anthropic SDK(시도마다 2회 더)가 재시도해 프로브 하나가 최대 12요청이 됐고, `/ecs/autoprober`에
시간당 1,600~1,700줄이 쌓였다. v2.29.0부터는 재시도 없이 프로브당 요청 1회, 오류 행 1개로 끝난다. v2.29.0은 CP 채널을 10분 주기로 늘려 호출 수도
절반(시간당 54회)이었지만, v2.29.1에서 기본값을 다시 매 사이클(시간당 108회)로 되돌렸다(2026-09-26 사용자 결정).
재시도 제거는 그대로이고, 10분 주기는 `ANTHROPIC_CP_PROBE_INTERVAL_S=600` 운영 레버로 남아 있다(아래 조치).

### 증상

- 대시보드 CP 카드 9장(`Anthropic Claude … (US)`)이 모두 "오류", 이상 징후 박스에 CP 채널이 나란히 뜬다. Bedrock Claude
  (`Bedrock Claude …`)와 OpenAI 채널은 정상이다.
- 오류 행 `error_message`(서명):
  `Unexpected: Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': "You have reached your API usage limits: your organization has crossed its monthly API usage threshold, set based on your organization's API tier. You will regain access on 2026-10-01 at 00:00 UTC.", 'details': {'error_code': 'enforced_spend_limit_reached'}}, …}`
- v2.29.0 이후 로그: CP 프로브마다 `Probe error for anthropic:<id> (iter 1): usage cap reached, not retried: …` 경고 한 줄.
  v2.28.2 이하 이미지는 프로브마다 `Retryable error for anthropic:<id> (attempt 1/4 … 3/4)` 세 줄 + `Probe error` traceback.
- 일시 rate limit(메시지에 "rate limit", 예: "per-minute rate limit")은 이 항목이 아니다 — 계속 2/4/8초 backoff로 재시도된다.

### 확인

```bash
REGION=ap-northeast-2
CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
# 1. 상한 429 서명과 재시도 흔적 (최근 1시간)
aws logs filter-log-events --region $REGION --log-group-name /ecs/autoprober \
  --start-time $(( ($(date +%s) - 3600) * 1000 )) --filter-pattern '"usage cap reached"' --query 'length(events)'
aws logs filter-log-events --region $REGION --log-group-name /ecs/autoprober \
  --start-time $(( ($(date +%s) - 3600) * 1000 )) --filter-pattern '"Retryable error for anthropic:"' --query 'length(events)'
# 기댓값(v2.29.1 기본값): 첫 번째 ≈ 108(9채널 × 12회/시간, ANTHROPIC_CP_PROBE_INTERVAL_S=600이면 ≈ 54), 두 번째 0

# 2. 대시보드에 보이는 마지막 오류 — "regain access on <날짜>"가 상한 해제 시각
curl -s "https://$CF_DOMAIN/api/auto-probe/anomalies?hours=1" \
  | jq '.models[] | select(.model_name|startswith("Anthropic")) | {model_name, failures, total, last_error}'
```

### 조치

- 모니터 쪽에서 할 일은 없다. 상한 해제 시각(메시지의 "regain access on …", 이번에는 2026-10-01 00:00 UTC)까지 CP 카드는
  오류로 남는 것이 정상이며, 해제 뒤 첫 CP 사이클(기본 최대 5분, 600 설정이면 최대 10분)에 자동으로 정상으로 돌아온다.
- 더 빨리 복구하려면 Anthropic Console에서 조직의 API 등급 또는 사용량 한도를 올린다(조직 관리자 권한). 키 교체나 재배포는
  필요 없다.
- CP 채널을 끄지 않는다 — 오류 행이 상한 기간을 기록하는 증거이고, 재시도가 없어 기본 주기에서도 호출은 시간당 108회다.
  상한 기간에 호출을 줄여야 하면 AutoProber task env `ANTHROPIC_CP_PROBE_INTERVAL_S=600`(초, 5분 단위로 반올림)을 CDK에서
  넣고 backend 서비스에도 같은 값을 넣은 뒤(`/api/auto-probe/status` `channel_intervals` 표시용) digest 고정
  AppServices + Scheduler 경로로 배포한다. 그러면 v2.29.0처럼 CP만 두 사이클에 한 번, 카테고리를 따로 순환하며 시간당
  54회가 된다(확인은 `deploy.md` §5-2의 3~4번). 상한이 풀리면 300으로 되돌린다. 600 모드에서는 대시보드가 `/status`를
  받기 전에(첫 `/status` 요청이 실패하면 다음 새로고침에서 성공할 때까지) 10분을 넘긴 CP 카드를 잠시 "수집 지연"으로 표시할
  수 있다. v2.29.1 대시보드는 `/status` 전에 600을 가정하지 않기 때문이며, `/status`가 오면 600 기준으로 돌아온다.
- 로그에 `usage cap reached` 대신 `Retryable error for anthropic:`가 계속 보이면 상한 메시지 문구가 바뀐 것이다 —
  `backend/prober.py` `_USAGE_CAP_MARKERS`에 새 문구를 추가한다.

## 대시보드 동결 / "skipping overlapping cycle" (2026-09-23 장애, v2.28.2에서 수정)

**배경**: 모델 하나의 스트림이 200 뒤 멈추거나 드문드문 흐르면(2026-09-23 Mantle us-east-1 GPT-5.6 Sol)
청크 간 read timeout이 발동하지 않는다. v2.28.1까지는 그 스레드 하나가 run 전체를 failed로 만들고,
`with ThreadPoolExecutor` 종료가 멈춘 스레드를 join해 autoprober 태스크가 30~46분 RUNNING으로 남았다.
그동안 running 예약(900초) 때문에 다음 스케줄 태스크가 빠지고, `/api/auto-probe/latest`는 마지막 **완료**
run만 보여 주므로 대시보드가 동결됐다. v2.28.2부터는 프로브 wall-clock watchdog(`PROBE_WALL_CLOCK_S`,
기본 90초)과 모델별 사이클 타임아웃(120초)이 그 모델만 오류 행으로 기록하고 run을 완료한다.

### 증상

- 대시보드 카드와 트렌드가 갱신되지 않는다. `/api/auto-probe/status`의 `last_completed_time`이 10분 넘게 전이고
  `cycle_state`가 `running`에 머문다(같은 `last_run_id`).
- `/ecs/autoprober` 로그에 5분마다 같은 run_id로 `AutoProber: skipping overlapping cycle (run_id=N)`.
- v2.28.1 이하 이미지의 로그: `AutoProber: model probe failed` + `TimeoutError` traceback, 수십 분 뒤
  `RuntimeError: 1 model probes did not finish normally`.
- v2.28.2 이후에는 동결 대신 아래 경고가 남고 사이클은 `AutoProber: cycle completed`로 끝나야 정상이다.
  - `Probe error for <model> (iter 1): WallClockTimeout: probe exceeded 90s wall-clock` — watchdog이 스트림을 끊음
  - `AutoProber: <model> — probe did not finish within 120s (cycle timeout); recording an error row` — watchdog이
    끊지 못한 구간(응답 헤더 대기 등)까지 넘김
  - `AutoProber: N model probe(s) timed out — recorded as error rows, run completes`
  - `AutoProber: discarded late result for <model> …` — 포기한 워커가 늦게 끝남(행 중복 없음, 정상)

### 확인

```bash
REGION=ap-northeast-2
CF_DOMAIN=d36s7ml54xwemr.cloudfront.net

# 1. 마지막 run과 마지막 완료 run
curl -s "https://$CF_DOMAIN/api/auto-probe/status" | jq '{cycle_state, last_run_id, last_run_status, last_run_time,
  last_completed_run_id, last_completed_time}'

# 2. 최근 사이클 로그 — 시작/완료/겹침 skip/타임아웃
aws logs tail /ecs/autoprober --since 1h --region $REGION \
  | grep -E "starting probe cycle|cycle completed|skipping overlapping|model probe failed|did not finish|WallClockTimeout|timed out"

# 3. 실행 중인 autoprober 태스크와 시작 시각 — 정상 사이클은 1~4분, 10분 넘게 RUNNING이면 멈춘 태스크
FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerAutoProberTaskDef \
  --status ACTIVE --region $REGION --query 'families[0]' --output text)
for T in $(aws ecs list-tasks --cluster bedrock-monitor --family "$FAM" --desired-status RUNNING \
    --region $REGION --query 'taskArns[]' --output text); do
  aws ecs describe-tasks --cluster bedrock-monitor --tasks "$T" --region $REGION \
    --query 'tasks[].[taskArn,startedAt,lastStatus,containers[0].image]' --output text
done

# 4. 어느 모델이 문제인지 — 이상 징후 박스와 같은 데이터(최근 N시간 실패 요약)
curl -s "https://$CF_DOMAIN/api/auto-probe/anomalies?hours=2" | jq '.models[] | {model_name, failures, total, last_error}'
```

- 3번 이미지 digest가 v2.28.1 이하이면 수정 전 동작이다 — 아래 조치 후 v2.28.2 이상으로 배포한다.
- v2.28.2 이상인데도 10분 넘게 RUNNING이면 새 유형이다. 태스크를 멈추기 전에 로그 스트림 전체를 보관한다.

### 조치

```bash
# 멈춘 태스크 정지 — 로그와 DB 행은 남는다(이미 쓴 결과 행은 그대로).
aws ecs stop-task --cluster bedrock-monitor --task <taskArn> --region $REGION \
  --reason "hung autoprober cycle (stream stall), see docs/runbooks/troubleshooting.md"
```

- 정지해도 그 run의 `probe_runs.status`는 `running`으로 남고, 예약은 run 생성 **900초 뒤** 만료된다. 그 뒤 첫
  5분 스케줄이 새 사이클을 시작한다(그 전의 수동 `POST /api/auto-probe/trigger`는 409). DB를 직접 고치지 않는다.
- 새 사이클이 `cycle completed`로 끝나고 `last_completed_time`이 전진하는지 2번, 1번으로 확인한다.
- 같은 모델이 매 사이클 `WallClockTimeout`이면 그 채널 쪽 문제다(대시보드는 동결되지 않는다). 이상 징후 박스와
  신뢰성 화면(`network` 버킷)에 오류로 보이는 것이 의도한 동작이다. 상한 조정이 필요하면 `PROBE_WALL_CLOCK_S`
  env를 바꾼다(모델별 사이클 타임아웃은 max(120초, 상한 + 30초)로 따라간다).
