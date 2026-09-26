# Runbook — 트러블슈팅

증상별 확인과 조치. 배포 절차는 [deploy.md](deploy.md), 되돌리기는 [rollback.md](rollback.md)를 본다.

## 비용 단가 동기화 실패 — "자동 확인 안 됨" 배지 (v2.30.0, ADR-030)

**배경**: PricingSync 태스크(`python -m pricing_sync_runner --once`, `rate(12 hours)`)가 공식 출처 3개에서 활성 55채널의 단가를
읽는다. Bedrock agreement offer rate card(Bedrock Claude 20 + OpenAI 25, FM 18개를 순차 호출), AWS Price List API(Nova 2.0 Lite),
Anthropic `https://platform.claude.com/docs/en/about-claude/pricing.md`(Claude Platform on AWS 9)다. 공식 값을 구하지 못한 채널은
기존 단가를 그대로 두고(`skipped:<reason>`) 화면에 "자동 확인 안 됨"으로 드러난다. 비용 계산은 멈추지 않는다 — 마지막 유효 단가를
계속 쓴다.

### 증상

- `/pricing` 셀에 "자동 확인 안 됨" 배지. `verification`이 `stale`(마지막 확인이 가장 최근에 끝난 런보다 이전, 배지 옆 설명
  "마지막 확인 <날짜>", `observed_at`이 없으면 "마지막 확인일 없음") 또는 `seed_only`(한 번도 확인되지 않음, 배지 옆 설명 "초기값")다.
- 한 출처만 실패하면 그 출처의 채널만 `stale`이 된다. 예: Anthropic 문서가 실패한 `partial` 런 뒤에는 Claude Platform on AWS 열 9셀만
  배지가 붙는다.
- "마지막 자동 확인" 시각이 12시간보다 오래됐으면 태스크가 돌지 않은 것이다.

### 확인

```bash
REGION=ap-northeast-2
CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
# 1. 마지막 런과 확인되지 않은 셀
curl -s "https://$CF_DOMAIN/api/pricing" | jq '{last_sync, pending_review, not_verified: [.families[] | .family as $f
  | ([(.tiers.cp, .tiers.global, .tiers.us) // empty] + .tiers.in_region)[]
  | select(.verification != "verified") | {family: $f, model_ids, verification, observed_at, pending}]}'

# 2. 최근 런 로그 (런 요약 한 줄 = 상태, 채널별 결과 수 — unchanged, changed, pending, no_baseline, rejected, skipped:<reason> — 와 오류 수.
#    요약 앞에는 런 오류마다 "pricing sync: <출처> …" WARNING 한 줄이 찍힌다(호출 실패, 파서 오류, 표에 없는 모델, 5분 상한 초과).
#    같은 문구가 런 행 price_sync_runs.summary.errors(앞 50개)에도 저장되지만, 그 값을 보여 주는 API는 없으니 이 로그로 본다.
#    출처 호출이 재시도되면 "pricing sync: … retry n/3" 경고도 찍힌다)
aws logs tail /ecs/pricingsync --since 13h --region $REGION
aws logs tail /ecs/pricingsync --since 13h --region $REGION --filter-pattern WARNING   # 오류와 재시도 경고만

# 3. 최근 태스크 종료 사유 — 컨테이너 이름은 pricingsynctaskdef (containers[0]은 GuardDuty 사이드카일 수 있다)
FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerPricingSyncTaskDef --status ACTIVE \
  --region $REGION --query 'families[0]' --output text)
for T in $(aws ecs list-tasks --cluster bedrock-monitor --family "$FAM" --desired-status STOPPED \
    --region $REGION --query 'taskArns[]' --output text); do
  aws ecs describe-tasks --cluster bedrock-monitor --tasks "$T" --region $REGION \
    --query "tasks[].[createdAt,stoppedReason,containers[?name=='pricingsynctaskdef'].exitCode|[0]]" --output text
done
```

| 원인 | 표지 | 조치 |
|------|------|------|
| 스케줄이 태스크를 실행하지 못함 | `last_sync.started_at`이 12시간보다 오래됨, `/ecs/pricingsync`에 새 로그 없음 | Scheduler 역할의 `RunTaskFamilyWildcard`에 PricingSync family `:*`, `PassTaskRoles`에 `PricingSyncTaskRole`이 있는지 확인(ADR-011). 없으면 digest 고정 CDK로 Scheduler 스택을 다시 배포 |
| 출처 권한 거부 | 로그에 `AccessDeniedException` (`ListFoundationModelAgreementOffers` 또는 `GetProducts`) | `PricingSyncTaskRole` 인라인 정책의 두 액션 확인. 다른 권한은 필요 없다(모델 호출 권한은 의도적으로 없음) |
| Anthropic 문서 형식 변경 | CP 9셀만 `stale`, 채널 결과 `skipped:parse_failed`, 로그에 `pricing sync: anthropic_doc: <파서 메시지>` 경고 한 줄. 메시지는 `'## Model pricing' heading not found`, `no pricing table under '## Model pricing'`, `pricing table headers not recognised: [...]`(헤더 "Model", "Base input tokens", "Output tokens" 중 하나가 없음), `pricing table has no parseable rows`, 그 밖의 예외면 `<예외 타입>: <문구>`다. 파서 예외는 종류와 상관없이 그 출처 채널만 건너뛰고, 다른 출처가 성공했으면 런은 `partial`로 끝난다. 표는 읽혔는데 모델명만 없으면 그 채널만 `skipped:not_found`이고 경고는 `pricing sync: anthropic_doc: model '<이름>' not in the table`이다 | 문서를 열어 표 구조를 확인하고 `backend/pricing_parsers.py` `parse_anthropic_pricing_md`와 fixture를 고친다. 모델명이 바뀌었으면(`not in the table`) `pricing_sources.ANTHROPIC_DOC_NAMES`도 고친다 |
| 오퍼 형식 변경 | 특정 모델 채널만 `skipped:<reason>`(오퍼 수 ≠ 1, 필수 차원 없음) | `aws bedrock list-foundation-model-agreement-offers --model-id <FM id> --offer-type PUBLIC --region us-east-1 --query 'offers[].termDetails.usageBasedPricingTerm.rateCard[].[dimension, price, unit]' --output table`로 차원 이름을 보고 `pricing_parsers.DIMENSION_RE`와 선택 순서를 고친다(출력에 `offerToken`과 `legalTerm.url`이 나오지 않도록 `--query`를 유지한다) |
| Price List 단위 변경 | Nova 1셀만 `stale` | `unit`이 `1K tokens`가 아니면 파서가 변경 없음으로 둔다. 새 단위를 확인하고 `parse_pricelist`를 고친다 |
| 5분 상한 초과 | 런 `partial`, 채널 결과 `skipped:deadline`, 로그에 `pricing sync: deadline: 300s exceeded before <출처> <호출>` 경고 한 줄(예: `before offers openai.gpt-5.6-sol`). 적힌 호출은 상한을 넘긴 뒤 처음 건너뛴 호출이고, 호출 순서가 Anthropic 문서 → Price List → 오퍼(FM id 사전순)라 그 호출과 뒤의 호출이 모두 `skipped:deadline`이다 | 대개 출처 응답 지연이다. 다음 런에서 회복하는지 본다. 상한은 호출 직전에만 검사한다. 재시도된 호출은 `retry n/3` 경고를 남기지만, 재시도 없이 느리게 성공한 호출(시도 1회에 연결 10초, 읽기 대기 30초 상한)은 로그를 남기지 않고 호출별 소요 시간도 기록하지 않는다. 그래서 반복되는데 재시도 경고가 없으면 특정 출처가 아니라 호출들이 고르게 느린 것이다. 태스크의 외부 경로(NAT 게이트웨이 경유 us-east-1, `platform.claude.com`)를 확인한다 |
| 다른 런이 실행 중 | 로그에 잠금을 못 잡아 종료했다는 한 줄(`lock 917350004 held by another sync`), 새 런 행 없음, exit code 1 | 정상이다(`pg_try_advisory_lock(917350004)`로 수동 실행과 스케줄 실행이 겹치지 않게 한다. 기다리지 않는 잠금이라 두 번째 런은 즉시 끝난다). 앞 런이 끝난 뒤 다시 실행한다 |
| CP 디스커버리 실패 | CP 9셀만 `stale`, 런 `partial` | Claude Platform on AWS `/v1/models` 호출이 실패한 것이다(키, workspace, 조직 상태). 표는 최근 30일에 관측된 CP model_id로 계속 채워진다 |

### 조치

- 원인을 고친 뒤 `deploy.md` §5-4의 2번(수동 `run-task`)으로 한 번 더 돌리고 1번으로 `verified`가 돌아왔는지 본다.
- DB를 직접 고치지 않는다. 단가를 바꿔야 하면 동기화가 새 값을 관측하게 하거나, 검토 대기 행을 아래 절차로 승인한다.
- 동기화가 실패해도 비용 화면은 마지막 유효 단가로 계속 계산된다. 공식 값이 실제로 바뀌었는데 동기화가 못 읽는 동안에는 그 차이가
  비용에 반영되지 않는다.

## 검토 대기 단가 승인 — "검토 대기" 배지 (v2.30.0, ADR-030)

**배경**: 동기화가 관측한 새 공식 값이 현재 유효 단가보다 입력이나 출력 어느 쪽이든 50%를 넘게 다르면(정확히 50%는 자동 적용)
자동으로 적용하지 않고 `pending_review` 행으로 남긴다. 단위 오류(1000배)나 파서 오류가 비용에 그대로 들어가는 것을 막는 안전장치다.
seed에도 없는 새 model_id(`no_baseline`)도 같은 대기열에 들어간다. 승인 전까지 비용은 기존 단가로 계산된다.

### 확인

```bash
CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
curl -s "https://$CF_DOMAIN/api/pricing" | jq '.pending_review'
TOKEN=$(curl -sX POST "https://$CF_DOMAIN/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<SEED_ADMIN_PASSWORD>"}' | jq -r .access_token)
# 행마다 현재 유효 값, 새 값, 입력과 출력 변화율, 출처, 사유(changed 또는 no_baseline)
curl -s "https://$CF_DOMAIN/api/admin/pricing/pending" -H "Authorization: Bearer $TOKEN" | jq .
```

### 판단과 조치

1. 새 값을 공식 페이지에서 직접 확인한다. Bedrock 채널은 `/pricing` 참고 자료의 모델 카드나 Amazon Bedrock 요금 페이지, Claude
   Platform on AWS는 Anthropic 요금 문서, Nova는 Amazon Bedrock 요금 페이지다.
2. 공식 값이 맞으면 승인한다. 승인한 단가는 그 값을 처음 관측한 런의 시작 시각부터 적용되고, `no_baseline`이면 과거 전체에 적용된다.
   응답의 `warnings`는 단가 조회 순서 `(effective_from, id)`에서 뒤에 오는 verified 단가(더 늦게 시작하거나, 같은 시각에 시작한 더 큰
   id의 행)가 이미 있다는 뜻이다 — 그 구간은 뒤의 단가가 계속 우선한다.

   ```bash
   curl -s -X POST "https://$CF_DOMAIN/api/admin/pricing/pending/<id>/approve" -H "Authorization: Bearer $TOKEN" | jq .
   ```

3. 오류 값이면 거부한다. 거부한 값은 공식 값이 다시 바뀔 때까지 대기열에 올라오지 않는다. 파서 오류가 원인이면 위 "비용 단가 동기화
   실패"의 표대로 코드를 고친다.

   ```bash
   curl -s -X POST "https://$CF_DOMAIN/api/admin/pricing/pending/<id>/reject" -H "Authorization: Bearer $TOKEN" | jq .
   ```

- 승인이나 거부를 처리한 backend 태스크는 `/api/pricing` 캐시를 바로 비우지만, 다른 backend 태스크(오토스케일 1~3개)는 최대 60초
  동안 이전 표를 줄 수 있다. 60초 뒤 다시 조회해서 확인한다.
- `401`은 토큰 없음이나 만료, `403`은 admin이 아닌 계정, `404`는 없는 id(`단가 행 <id>을(를) 찾을 수 없습니다`), `409`는 이미
  승인이나 거부로 처리된 행(`단가 행 <id>는 검토 대기 상태가 아닙니다 (현재: <status>)`)이다. `pending_review` 숫자는 검토 대기
  행이 있는 채널 수라, 한 채널에 대기 행이 여러 개면 관리자 목록의 행 수가 더 많다.

## GPT-5.6 Sol 프로모션 종료 확인 — 2026-11-21 이후 (v2.30.0)

**배경**: GPT-5.6 Sol 단가 In-Region, Geo $4.40 / $22, Global $4 / $20은 프로모션 단가다(v2.28.1). 2026-09-23 AWS 모델 카드에는 "최소
2026-11-21까지"가 있었지만 지금 공식 출처 어디에도 종료일이 없어서, 이 정보는 `pricing_sources.PRICE_NOTES` 수동 메모로만
관리한다. `/pricing`의 Sol 셀에는 "프로모션(최소 2026-11-21까지, 수동 메모)" 배지가 붙고, 날짜가 지나면 "프로모션 종료 여부 확인
필요"로 바뀐다.

### 확인

```bash
CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
curl -s "https://$CF_DOMAIN/api/pricing" | jq '[.families[] | select(.family_key == "gpt-5.6-sol")
  | {global: (.tiers.global | {input, output, verification, pending}),
     in_region: [.tiers.in_region[] | {regions, input, output, verification, pending}], notes}]'
# 공식 오퍼 값 직접 조회 (offerToken, legalTerm.url은 출력하지 않는다)
aws bedrock list-foundation-model-agreement-offers --model-id openai.gpt-5.6-sol --offer-type PUBLIC --region us-east-1 \
  --query "offers[].termDetails.usageBasedPricingTerm.rateCard[?dimension=='input_tokens_standard' || dimension=='output_tokens_standard' || dimension=='input_tokens_global_standard' || dimension=='output_tokens_global_standard'][].[dimension, price]" \
  --output table
```

### 해석과 조치

- 오퍼가 여전히 4.4 / 22, 4 / 20이면 프로모션이 계속되는 것이다. 모델 카드에서 새 종료일을 확인하고, 있으면
  `pricing_sources.PRICE_NOTES`의 `min_until`을 고쳐 다음 릴리스로 배포한다.
- 프로모션이 끝나 이전 단가(In-Region, Geo $5.50 / $33, Global $5 / $30)로 돌아가면 입력 +25%, 출력 +50%라 경계 포함 규칙으로 **자동
  적용**된다(`verified`, 관측한 런의 시작 시각부터). 동기화가 `prior_price`와 같은 값을 관측하면 수동 메모는 응답에서 빠진다.
- 이전 단가가 아닌 다른 값으로 바뀌어 50%를 넘으면 검토 대기로 간다. 위 "검토 대기 단가 승인"을 따른다.

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
