# Runbook — 트러블슈팅

증상별 확인과 조치. 배포 절차는 [deploy.md](deploy.md), 되돌리기는 [rollback.md](rollback.md)를 본다.

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
