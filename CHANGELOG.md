# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다.

작성 규칙:
- 최신 변경 사항이 위에, 과거 변경이 아래에 옵니다.
- 카테고리: `Added` / `Changed` / `Fixed` / `Removed` / `Security` / `Infra` / `Docs`
- 매 commit 시 PR 또는 작업 종료 시 한 항목 추가.

## v2.28.0 — 2026-09-23

### Added
- **Dashboard model cards grade their metric values** (user request). The TTFT, total latency and TPS value text on each card is colored by grade — normal **blue**, warning **amber** with ▲, critical **rose** with ◆ — using absolute thresholds per workload category (the user chose this over a model-own-baseline option). The Korean name of the normal grade is **양호**, not 정상, so it never reads as the channel health badge (정상) next to a critical value. Latency is graded at or above the threshold (TTFT warn/crit: chat-short 3 / 8 s, structured 3.5 / 8 s, summarize 3 / 8 s, translate 3.5 / 8 s, code-gen 5 / 12 s, reasoning 9 / 16 s; total latency: 4 / 10, 4 / 10, 5 / 10, 8 / 12, 7.5 / 14, 11 / 24 s; uncategorized 5 / 12 and 10 / 24 s). TPS is inverted and shared by all categories: warning below 40 tok/s, critical below 15. Thresholds come from 48 h of production auto-probe results (2026-09-21 06:22 to 2026-09-23 06:18 UTC, 26,544 successes): warning just above each category's p90, critical near its p99. Applied to the same data, cards come out normal 89.0%, warning 9.6%, critical 1.4% (graded at displayed precision, as the cards do; 89.2 / 9.4 / 1.4% on raw values, see ADR-029). Cards grade the value at displayed precision (`roundForDisplay`: TTFT whole ms, total latency 100 ms steps, TPS one decimal), so color, tooltip and the shown number always agree — chat-short 3,960 ms shows "4.0 s" and is a warning. Each value carries a `title` tooltip with the applied rule and a `data-grade` attribute (`normal|warning|critical|none`); warning/critical values are also described to screen readers through `aria-describedby`. Normal values carry no marker, so the legend shows Normal as a plain blue swatch rather than a glyph; the value, unit and marker are separate flex items that wrap before the marker in narrow columns (320 px), and the marker is 12 px. A legend above the grid ("Metric grades: [swatch] Normal ▲ Warning ◆ Critical — graded per workload category", label visible) expands into the full threshold table, so touch devices can see the criteria too. Theme-aware colors (`text-blue-300`, `text-amber-300`, `text-rose-400` with `light:text-rose-300` for contrast). `frontend/src/lib/metricGrade.ts` is the single source; see **ADR-029**.
- **대시보드 모델 카드 지표 값 등급** (사용자 요청). 카드의 TTFT, 총 응답시간, TPS 값 텍스트를 등급으로 칠한다 — 양호 **파랑**, 경고 **호박**(▲), 위험 **장미**(◆). `normal` 등급의 한글 이름은 채널 건강 배지("정상")와 구분되도록 **양호**로 정했다(위험 값 옆에 "✓ 정상" 배지가 같은 단어로 보이지 않게). 기준은 워크로드 카테고리별 절대 임계치다(모델 자체 기준선 방식 대신 사용자가 선택). 지연시간은 기준값 이상이면 해당 등급이다(TTFT 경고/위험: 짧은 대화 3 / 8초, JSON 추출 3.5 / 8초, 요약 3 / 8초, 번역 3.5 / 8초, 코드 생성 5 / 12초, 추론 9 / 16초, 총 응답시간: 4 / 10, 4 / 10, 5 / 10, 8 / 12, 7.5 / 14, 11 / 24초, 카테고리 미지정 5 / 12, 10 / 24초). TPS는 반대 방향이고 전 카테고리 공통이다(40 tok/s 미만 경고, 15 미만 위험). 임계치는 운영 자동 프로브 48시간치(2026-09-21 06:22 ~ 2026-09-23 06:18 UTC, 성공 26,544건)에서 경고는 카테고리 p90 바로 위, 위험은 p99 부근으로 정했고, 같은 데이터에 적용하면 카드 기준 양호 89.0%, 경고 9.6%, 위험 1.4%다(카드처럼 표시 정밀도로 판정한 값, 원값 기준은 89.2 / 9.4 / 1.4%, ADR-029 참조). 카드는 표시 정밀도로 반올림한 값(`roundForDisplay`: TTFT ms 정수, 총 응답시간 100ms 단위, TPS 소수 1자리)을 판정하므로 색, 툴팁, 화면 숫자가 항상 일치한다(짧은 대화 3,960ms는 "4.0 s"로 보이고 경고). 값마다 적용 기준을 담은 `title` 툴팁과 `data-grade` 속성(`normal|warning|critical|none`)이 있고, 경고와 위험 값은 `aria-describedby`로 스크린 리더에도 전달된다. 양호 값에는 표지가 없으므로 범례도 양호는 글자 표지 없이 파란 색 견본만 보여 주고, 값, 단위, 표지는 각각 flex 항목이라 좁은 열(320px)에서는 표지 앞에서 줄을 바꾸며 표지는 12px이다. 카드 위 범례("지표 등급: [견본] 양호 ▲ 경고 ◆ 위험 — 워크로드 카테고리별 기준", 라벨도 화면에 표시)를 펼치면 전체 기준표가 나와 터치 기기에서도 기준을 볼 수 있다. 색은 테마 대응(`text-blue-300`, `text-amber-300`, `text-rose-400`, 라이트는 대비를 위해 `light:text-rose-300`). 단일 출처는 `frontend/src/lib/metricGrade.ts`이며 자세한 내용은 **ADR-029**.
- **GPT on AWS bench: GPT-6 Sol and GPT-6 Luna join — 12 → 18 channels** (Mantle in-region 11 + CRIS 7; user decision 2026-09-23). `_BENCH_SPECS` gains Sol and Luna with Global CRIS, US CRIS and Mantle us-east-1, appended **last**: a cycle that hits the 780 s deadline skips trailing channels first, so any cut lands on the new channels and the existing 12 series stay continuous. Live check with the exact bench request (Responses stream, fixed 55,839-token input, `max_output_tokens` 4096, verbosity low, reasoning effort medium, `include: reasoning.encrypted_content`, `store: false`, `prompt_cache_retention: 24h`): all 6 channels HTTP 200 `response.completed`; Sol reports `reasoning_tokens` 0 (31–35 output tokens), Luna 34–47 (64–82 output tokens), US and us-east-1 hit the cache from the first call (55,837 / 55,839). Projected cycle from the 12-channel production cycles of 2026-09-22 (96 cycles: p50 386 s, p95 508 s, max 682 s): p50 about 10 min, p90 about 12 min, p95 about 775 s against the 780 s deadline. Cost estimate for the 6 new channels ≈ **$41/day**: 11 calls per channel per cycle (1 warm-up + 10) × 96 cycles = 1,056 calls, each 55,839 input tokens with 55,837 cache hits ≈ 59M cache-read tokens per channel per day at the rate-card cache-read price (Sol $0.22 in-region/US, $0.20 Global; Luna $0.011 / $0.01 per MTok) → Sol ≈ $37.7 + Luna ≈ $1.9, plus ≈ $1.2 of output (Sol ≈ 33, Luna ≈ 64–82 tokens per call); without the cache it would be ≈ $396/day. The panel groups cards by generation (GPT 6 / GPT 5.x, plus an "Other" column so unknown families never vanish), gives all six families distinct dash patterns with a 40 px legend swatch, shows a "↓ +N more, scroll the legend" line under each trend legend on phones (< 640 px, where the 144 px legend box fits about 6 of 18 channels; desktop unchanged), and `familyOf` is anchored so "GPT 5.6 Sol" never reads as "6 Sol". Router `fam_rank`: Astra, Sol, Luna, Terra, 5.5, 5.4.
- **GPT on AWS 벤치: GPT-6 Sol, GPT-6 Luna 합류 — 12 → 18채널**(Mantle 인리전 11 + CRIS 7, 2026-09-23 사용자 결정). `_BENCH_SPECS`에 Sol, Luna를 Global CRIS, US CRIS, Mantle us-east-1로 추가하되 목록 **끝**에 두었다. 사이클이 데드라인 780초에 걸리면 뒤 채널부터 skip되므로 컷이 신규 채널에 먼저 떨어지고 기존 12채널 시계열은 끊기지 않는다. 벤치 요청 형태 그대로(Responses 스트림, 고정 입력 55,839토큰, `max_output_tokens` 4096, verbosity low, reasoning effort medium, `include: reasoning.encrypted_content`, `store: false`, `prompt_cache_retention: 24h`) 라이브 확인한 결과 6채널 모두 HTTP 200 `response.completed`였고, Sol은 `reasoning_tokens` 0(출력 31~35토큰), Luna는 34~47(출력 64~82토큰), US와 us-east-1은 첫 호출부터 캐시 히트(55,837 / 55,839)였다. 2026-09-22 운영 12채널 사이클(96회: p50 386초, p95 508초, 최대 682초)에서 외삽한 18채널 사이클은 p50 약 10분, p90 약 12분, p95 약 775초로 데드라인 780초에 근접한다. 신규 6채널 비용 추정은 **약 $41/일**이다. 근거: 채널당 사이클 11호출(워밍업 1 + 측정 10) × 96사이클 = 1,056호출, 호출당 입력 55,839토큰 중 55,837이 캐시 히트라 채널당 하루 약 59M 캐시 읽기 토큰이고, rate card 캐시 읽기 단가(Sol 인리전/US $0.22, Global $0.20, Luna $0.011 / $0.01 per MTok)를 곱하면 Sol 약 $37.7 + Luna 약 $1.9, 출력(호출당 Sol 약 33, Luna 약 64~82토큰) 약 $1.2다. 캐시가 없다면 약 $396/일이다. 패널은 카드를 세대별(GPT 6 / GPT 5.x)로 묶고 모르는 family는 "기타" 열로 보내며(조용히 사라지지 않게), 6개 family 선 패턴을 모두 다르게 하고 범례 스와치를 40px로 넓혔다. 휴대폰 폭(640px 미만)에서는 144px 범례 상자에 18채널 중 6개 남짓만 보이므로 추세 범례마다 "↓ +N개 더 있음, 범례를 스크롤하세요" 안내 줄을 띄운다(데스크톱은 그대로). `familyOf`는 "GPT 5.6 Sol"을 "6 Sol"로 읽지 않도록 고정 정규식을 쓴다. 라우터 `fam_rank`: Astra, Sol, Luna, Terra, 5.5, 5.4.
- **Claude API Features: Claude Opus 5.5 as the 5th representative model** — Fable 5.1, Fable 5, **Opus 5.5**, Opus 5, Sonnet 5 (ids: CP `claude-opus-5-5`, Mantle `anthropic.claude-opus-5-5`, Bedrock `global.anthropic.claude-opus-5-5`). A run is now **975 cells = 813 probed + 162 pre-decided** (was 780 = 643 + 137), about 9 min instead of 7, and roughly +15–25% token cost per run. `CATALOG_VERSION` → `2026-09-23` (changing the representative `MODELS` changes the run shape). Opus 5.5 rejects forced `tool_choice`, so `tool_use` uses `auto` + instruction for all three id forms (Opus 5 stays forced); the advisor probe pairs Opus 5.5 with itself (`claude-opus-5-5`, CP live supported) and a test guards that `_ADVISOR_FOR` covers every catalog model (a missing key would turn the cell broken); computer use is toolset-only (`computer_toolset_20260801` accepted on CP, Mantle, Messages API and InvokeModel; legacy `computer_20251124` 400 on CP). Live smoke of the 195 Opus 5.5 cells: **0 broken, 0 inconclusive** (supported 116, unsupported 49, not_applicable 26, skipped 4; match 157, none 33, undocumented 4 — `browser_use`, drift 1 — the Mantle `fallback_credit` fixed below). The UI orders per-model cell lists by catalog `models` (`buildGroups(..., modelOrder)`) instead of DB completion order. **The first run after deploy shows 195 catalog changes** (new `opus-5-5` cells, `before: null`) in the change banner — expected.
- **Claude API Features: Claude Opus 5.5를 5번째 대표 모델로 추가** — Fable 5.1, Fable 5, **Opus 5.5**, Opus 5, Sonnet 5(id: CP `claude-opus-5-5`, Mantle `anthropic.claude-opus-5-5`, Bedrock `global.anthropic.claude-opus-5-5`). 1런은 **975셀 = 프로브 813 + 사전판정 162**(이전 780 = 643 + 137)이고, 소요 시간은 약 7분에서 약 9분, 토큰 비용은 런당 약 15~25% 늘어난다. 대표 `MODELS`가 바뀌면 런 형태가 달라지므로 `CATALOG_VERSION`을 `2026-09-23`으로 범프했다. Opus 5.5는 forced `tool_choice`를 거부해 `tool_use`는 세 id 형태 모두 `auto` + 지시로 보내고(Opus 5는 forced 유지), advisor 프로브는 Opus 5.5를 자기 자신(`claude-opus-5-5`, CP 실측 supported)과 페어링하며 `_ADVISOR_FOR`가 카탈로그 전 모델을 덮는지 테스트가 지킨다(키가 빠지면 셀이 broken이 된다). computer use는 toolset 전용이다(`computer_toolset_20260801`을 CP, Mantle, Messages API, InvokeModel이 수락, legacy `computer_20251124`는 CP에서 400). Opus 5.5 195셀 라이브 스모크: **broken 0, inconclusive 0**(supported 116, unsupported 49, not_applicable 26, skipped 4, 판정 match 157, none 33, undocumented 4 — `browser_use`, drift 1 — 아래에서 수정한 Mantle `fallback_credit`). UI는 셀 안 모델 목록을 DB 완료 순서가 아니라 카탈로그 `models` 순서로 정렬한다(`buildGroups(..., modelOrder)`). **배포 후 첫 런의 변경 배너에는 카탈로그 변경 195건**(신규 `opus-5-5` 셀, `before: null`)이 뜬다 — 정상이다.

### Changed
- **GPT-6 Sol/Luna pricing is filled from the Bedrock agreement-offer rate card** (`aws bedrock list-foundation-model-agreement-offers`; Sol `offer-pycji3sz5gpcc`, Luna `offer-gmo53nkzc5or6`, identical in us-east-1, us-west-2 and ap-northeast-2). `*_standard` maps to In-Region and Geo CRIS, `*_global_standard` to Global CRIS: `gpt-6-sol` / `gpt-6-sol-us` $2.20 / $11, `gpt-6-sol-global` $2 / $10, `gpt-6-luna` / `gpt-6-luna-us` $0.11 / $0.55, `gpt-6-luna-global` $0.10 / $0.50 per MTok, all six keys in one commit in `backend/pricing.py` and `frontend/src/lib/pricing.ts`. Cross-check: the same API's Astra offer (`offer-7epta7rbw5aws`, $11 / $55, Global $10 / $50) matches the official Astra model card exactly, and the Sol/Luna values equal the OpenAI list price plus the documented In-Region/Geo 10%. AWS has not published Sol/Luna model cards yet — re-verify against the cards when they appear. Costs are computed at query time, so the six channels no longer show "-" and their rows since v2.27.0 are priced retroactively.
- **GPT-6 Sol/Luna 단가를 Bedrock agreement offer rate card로 반영했다**(`aws bedrock list-foundation-model-agreement-offers`, Sol `offer-pycji3sz5gpcc`, Luna `offer-gmo53nkzc5or6`, us-east-1, us-west-2, ap-northeast-2 모두 동일). `*_standard`는 인리전과 Geo CRIS, `*_global_standard`는 Global CRIS에 대응한다: `gpt-6-sol`, `gpt-6-sol-us` $2.20 / $11, `gpt-6-sol-global` $2 / $10, `gpt-6-luna`, `gpt-6-luna-us` $0.11 / $0.55, `gpt-6-luna-global` $0.10 / $0.50 per MTok. 6키를 `backend/pricing.py`와 `frontend/src/lib/pricing.ts`에 한 커밋으로 넣었다. 교차 검증: 같은 API의 Astra offer(`offer-7epta7rbw5aws`, $11 / $55, Global $10 / $50)가 Astra 공식 모델 카드와 정확히 일치하고, Sol/Luna 값은 OpenAI 정가에 문서화된 인리전, Geo 10%를 더한 값과 같다. AWS가 아직 Sol/Luna 모델 카드를 게재하지 않았으므로 게재되면 카드와 재대조한다. 비용은 조회 시점에 계산하므로 6채널은 더 이상 "-"가 아니고 v2.27.0 이후 행도 소급 산정된다.
- **GPT-6 Astra Mantle us-east-1 / us-east-2 are "currently unsupported — excluded"** (user decision 2026-09-23, after 404 `not_found_error` on 2026-09-09 and 2026-09-23). It is no longer a re-check follow-up and not a periodic check; if AWS announces support, add the region to the spec tuple. Code comments (prober, gptbench, CDK), the CLAUDE.md table and ADR-027 now say so.
- **GPT-6 Astra Mantle us-east-1, us-east-2는 "현재 미지원 — 제외"로 확정했다**(2026-09-23 사용자 결정, 2026-09-09와 2026-09-23 모두 404 `not_found_error`). 더 이상 재확인 후속 과제가 아니며 정기 재확인 대상도 아니다. AWS가 지원을 발표하면 스펙 튜플에 리전만 추가한다. 코드 주석(prober, gptbench, CDK), CLAUDE.md 표, ADR-027을 같은 표현으로 바꿨다.

### Fixed
- **GPT on AWS bench calls now have a true wall-clock cap.** The OpenAI client `timeout` is only the httpx read timeout between chunks, so a stream that kept trickling events never timed out: on 2026-09-16~17 one GPT 5.4 us-east-2 warm-up call took ≈ 3,540 s, the cycle 3,582 s, and up to four bench tasks overlapped. Each call now runs under a watchdog (`threading.Timer`, `CALL_TIMEOUT_S` = `GPT_BENCH_CALL_TIMEOUT`, default 90 s) that shuts the stream socket down and then closes it (`close()` alone does not wake a blocked `recv` on Linux); an expired call becomes an error row `WallClockTimeout: wall-clock timeout after 90s`. A call that received `response.completed` within the cap keeps its measurement even if the late abort raises. The client uses `max_retries=0` so a failed measurement is never silently retried (the SDK default of 2 could triple one call's duration).
- **GPT on AWS 벤치 호출에 실제 wall-clock 상한을 걸었다.** OpenAI 클라이언트 `timeout`은 청크 사이의 httpx read timeout일 뿐이라 이벤트가 드문드문 계속 오는 스트림은 끝나지 않았다. 2026-09-16~17에 GPT 5.4 us-east-2 워밍업 1회가 약 3,540초, 사이클이 3,582초 걸렸고 벤치 태스크가 최대 4개 겹쳤다. 이제 호출마다 watchdog(`threading.Timer`, `CALL_TIMEOUT_S` = `GPT_BENCH_CALL_TIMEOUT`, 기본 90초)이 돌고, 만료되면 스트림 소켓을 shutdown한 뒤 close한다(Linux에서는 close만으로 블로킹된 `recv`가 깨지지 않는다). 만료된 호출은 오류 행 `WallClockTimeout: wall-clock timeout after 90s`가 된다. 상한 안에 `response.completed`를 받은 호출은 뒤늦은 abort가 예외를 던져도 측정값을 유지한다. 클라이언트는 `max_retries=0`이라 실패한 측정을 조용히 재시도하지 않는다(SDK 기본값 2는 한 호출의 경과를 최대 3배로 늘릴 수 있었다).
- **Known limitation (no code change): a slow bench cycle can still be finishing when `/api/gptbench/latest` treats it as complete.** The 780 s cycle deadline is checked before each call, so a call started just before it can still run up to the 90 s wall-clock cap (the watchdog attaches once response headers arrive, so the header wait itself is bounded only by the 90 s httpx timeout and can rarely add more), and the cycle can end about 870 s (≈ 14.5 min) after it started. `/latest` counts a cycle as complete 14 minutes after its start, so in that last half minute the final channels (GPT 6 Sol/Luna, listed last; rows are committed per channel) can be missing from the scorecards and the trend endpoint, and appear about a minute late on the next refresh.
- **알려진 제약(코드 변경 없음): 느린 벤치 사이클은 `/api/gptbench/latest`가 완료로 간주한 뒤에도 아직 끝나는 중일 수 있다.** 사이클 데드라인 780초는 호출 직전에 검사하므로, 데드라인 직전에 시작한 호출은 wall-clock 상한 90초까지 더 돌 수 있고(watchdog은 응답 헤더를 받은 뒤 붙으므로 헤더 대기 구간은 httpx timeout 90초가 상한이라 드물게 더 길어질 수 있다) 사이클은 시작 후 약 870초(약 14.5분)에 끝날 수 있다. `/latest`는 시작 후 14분이 지난 사이클을 완료로 보므로, 그 마지막 30초 남짓 동안 마지막 채널(목록 끝의 GPT 6 Sol/Luna, 행은 채널 단위 커밋)이 스코어 카드와 trend에서 빠졌다가 다음 새로고침에서 1분 정도 늦게 나타날 수 있다.
- **GPT on AWS `/api/gptbench/trend` no longer risks an OOM.** The public endpoint accepted `hours` up to 720 and loaded every `GptBenchResult` row as a full ORM object; at 18 channels a 720 h request reached about 1 GB RSS on the 1 GiB backend task (the same pattern as the 2026-09-01 `/api/results/stats` OOM). `hours` is now capped at **168** (the UI's largest range, 7 d; 169+ returns 422) and the query selects only the seven columns it aggregates (`model_id`, `model_name`, `cycle_ts`, `status`, `ttfb_ms`, `ttft_ms`, `gap_ms`) as tuples. The response is unchanged — a test pins it against the previous ORM implementation on a mixed dataset. On a synthetic 7-day, 18-channel dataset (120,960 rows, SQLite) the Python heap peak of one 168 h request drops from about 218 MB to about 77 MB (tracemalloc).
- **GPT on AWS `/api/gptbench/trend`의 OOM 위험을 없앴다.** 이 공개 엔드포인트는 `hours`를 720까지 받고 `GptBenchResult` 행을 전부 ORM 객체로 읽었다. 18채널에서 720시간 요청은 1 GiB backend 태스크에서 RSS 약 1 GB까지 올랐다(2026-09-01 `/api/results/stats` OOM과 같은 패턴). 이제 `hours` 상한은 **168**(UI 최대 범위 7일, 169 이상은 422)이고, 집계에 쓰는 7개 컬럼(`model_id`, `model_name`, `cycle_ts`, `status`, `ttfb_ms`, `ttft_ms`, `gap_ms`)만 튜플로 읽는다. 응답은 그대로이며, 혼합 데이터셋에서 이전 ORM 구현과 같은 응답을 내는지 테스트로 고정했다. 합성 7일, 18채널 데이터(120,960행, SQLite)에서 168시간 요청 1회의 Python 힙 피크는 약 218MB에서 약 77MB로 줄었다(tracemalloc).
- **Claude API Features: Mantle `fallback_credit` was a false drift.** The probe sent the CP beta name `fallback-credit-2026-07-01` to Mantle `/anthropic`, which answers 400 "Unexpected value(s) … for the `anthropic-beta` header". Mantle now gets `fallback-credit-2026-06-01` like the three Bedrock paths (CP keeps 07-01; pinned per surface including the evidence request snapshot). Live on Mantle us-east-1: opus-5-5, opus-5 and sonnet-5 are supported / match (200 `end_turn`) with 06-01 while 07-01 still returns 400. Fable 5 stays drift for the separate data-retention opt-in error, Fable 5.1 is `not_applicable` on Mantle. This corrects the v2.23.0 conclusion (ADR-026, CHANGELOG v2.23.x) that the two Mantle `fallback_credit` drifts were a real surface gap. After deploy, Mantle opus-5 and sonnet-5 flip unsupported → supported as two *measured* changes and the drift count drops by two.
- **Claude API Features: Mantle `fallback_credit` 거짓 드리프트를 고쳤다.** 프로브가 CP의 beta 이름 `fallback-credit-2026-07-01`을 Mantle `/anthropic`에 보냈고, Mantle은 400 "Unexpected value(s) … for the `anthropic-beta` header"로 거부했다. 이제 Mantle에는 Bedrock 3경로와 같은 `fallback-credit-2026-06-01`을 보낸다(CP는 07-01 유지, 증거 요청 스냅샷까지 surface별로 테스트 고정). Mantle us-east-1 라이브: opus-5-5, opus-5, sonnet-5 모두 06-01로 supported / match(200 `end_turn`)이고 07-01은 여전히 400이다. Fable 5는 별개인 데이터 보존 opt-in 오류로 드리프트가 남고, Fable 5.1은 Mantle에서 `not_applicable`이다. 이는 두 Mantle `fallback_credit` 드리프트를 실제 surface 갭으로 본 v2.23.0 결론(ADR-026, CHANGELOG v2.23.x)을 정정한다. 배포 후 Mantle opus-5, sonnet-5가 unsupported → supported로 바뀌는 *실측* 변경 2건이 뜨고 드리프트는 2건 줄어든다.

### Infra
- No new env and no IAM change. CDK edits are comments plus the `FeaturesVerifySchedule` description ("… x 5 models, daily"). Deploy `BedrockMonitor-AppServices` + `BedrockMonitor-Scheduler` with the digest-pinned CDK path so the backend service and all five scheduled task definitions (autoprober, insights, parityrun, gptbench, featuresverify) move to the new image together.
- 신규 env와 IAM 변경은 없다. CDK 변경은 주석과 `FeaturesVerifySchedule` 설명("… x 5 models, daily")뿐이다. backend 서비스와 스케줄 태스크 정의 5개(autoprober, insights, parityrun, gptbench, featuresverify)가 함께 새 이미지로 가도록 digest 고정 CDK 경로로 `BedrockMonitor-AppServices` + `BedrockMonitor-Scheduler`를 배포한다.

### Docs
- New **ADR-029** (dashboard metric grade thresholds: options, threshold table and 48 h derivation, colors and accessibility, consequences). ADR-026 gains a v2.28.0 addendum (5 representative models, 975 = 813 + 162, Opus 5.5 probe adjustments and smoke, `fallback_credit` correction), ADR-027 records the Astra Mantle us-east-1/us-east-2 user decision, ADR-028 gains a v2.28.0 follow-up (agreement-offer pricing, bench inclusion, `/claude-features` inclusion). `CLAUDE.md` (the `CATALOG_VERSION` rule now also lists a change of the representative `MODELS`), `README.md`, `docs/architecture.md`, `docs/api-reference.md`, `docs/runbooks/deploy.md` (§2-1 now lists all five scheduled task-def families including GptBench and FeaturesVerify; new §5-1 v2.28.0 checks), `docs/onboarding.md`, `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `frontend/CLAUDE.md` and `frontend/src/components/CLAUDE.md` are updated; `docs/api-reference.md` gains a GPT on AWS bench section. Ops follow-up (no code): the parity old-label check is scheduled for 12 h after the release. Tests: backend 321, frontend vitest 221 + `tsc`, CDK 77, Playwright `e2e/monitoring.spec.ts` 12 + `e2e/catalog-benchmark.spec.ts` 15 (chromium).
- **ADR-029**를 신설했다(대시보드 지표 등급 임계치: 선택지, 임계치 표와 48시간 도출, 색과 접근성, 영향). ADR-026에는 v2.28.0 부록(대표 모델 5종, 975 = 813 + 162, Opus 5.5 프로브 조정과 스모크, `fallback_credit` 정정)을, ADR-027에는 Astra Mantle us-east-1, us-east-2 사용자 결정을, ADR-028에는 v2.28.0 후속(agreement offer 단가, 벤치 편입, `/claude-features` 편입)을 덧붙였다. `CLAUDE.md`(`CATALOG_VERSION` 범프 규칙에 대표 `MODELS` 변경 추가), `README.md`, `docs/architecture.md`, `docs/api-reference.md`, `docs/runbooks/deploy.md`(§2-1에 GptBench, FeaturesVerify를 포함한 스케줄 태스크 정의 5개 전부 명시, 신규 §5-1 v2.28.0 확인), `docs/onboarding.md`, `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `frontend/CLAUDE.md`, `frontend/src/components/CLAUDE.md`를 갱신했고, `docs/api-reference.md`에 GPT on AWS 벤치 절을 추가했다. 운영 후속(코드 변경 없음): 패리티 구 라벨 확인을 릴리스 12시간 뒤로 예약했다. 테스트: backend 321, frontend vitest 221 + `tsc`, CDK 77, Playwright `e2e/monitoring.spec.ts` 12건 + `e2e/catalog-benchmark.spec.ts` 15건(chromium).
- Version bumped to **v2.28.0** (`frontend/src/lib/version.ts`, `frontend/package.json` + `package-lock.json`, `backend/main.py` FastAPI version, `README.md` badge, `CLAUDE.md` overview).
- 버전을 **v2.28.0**으로 범프했다(`frontend/src/lib/version.ts`, `frontend/package.json` + `package-lock.json`, `backend/main.py` FastAPI version, `README.md` 배지, `CLAUDE.md` 개요).

## v2.27.0 — 2026-09-23

### Added
- **Claude Opus 5.5 — 3 channels** (launched 2026-09-22): `Bedrock Claude Opus 5.5 (Global)` (`global.anthropic.claude-opus-5-5`, Seoul — Seoul offers Global CRIS only, no Geo), `Bedrock Claude Opus 5.5 (US)` (`us.anthropic.claude-opus-5-5`, us-east-1) and `Anthropic Claude Opus 5.5 (US)` (CP on AWS auto-discovery, target `opus-5-5` listed before `opus-5`). Live-verified 2026-09-23: both Bedrock profiles `converse_stream` 200 `end_turn` (TTFT ≈ 2.8 s), CP `/v1/messages` 200. `temperature` returns 400 ("`temperature` is deprecated for this model"), so the existing `"opus-5"` reasoning pattern (substring) keeps it suppressed; forced `tool_choice` returns 400 ('type "tool" and "any" are not supported for this model'), so the parity `_NO_FORCED_TOOL_CHOICE_MARKERS` gains `"opus-5-5"` (Opus 5 keeps forced tool use). Price $4 / $20 per MTok with an exact `claude-opus-5-5` key.
- **Claude Opus 5.5 — 3채널** (2026-09-22 출시): `Bedrock Claude Opus 5.5 (Global)`(`global.anthropic.claude-opus-5-5`, 서울 — 서울은 Global CRIS만 제공, Geo 없음), `Bedrock Claude Opus 5.5 (US)`(`us.anthropic.claude-opus-5-5`, us-east-1), `Anthropic Claude Opus 5.5 (US)`(CP on AWS 자동 발견, 타깃 `opus-5-5`를 `opus-5`보다 앞에 둠). 2026-09-23 라이브 검증: Bedrock 두 프로파일 `converse_stream` 200 `end_turn`(TTFT 약 2.8초), CP `/v1/messages` 200. `temperature`는 400("`temperature` is deprecated for this model")이라 기존 `"opus-5"` reasoning 패턴(substring)이 그대로 억제하고, forced `tool_choice`도 400('type "tool" and "any" are not supported for this model')이라 패리티 `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"opus-5-5"`를 추가했다(Opus 5는 forced 도구 사용 유지). 단가는 정확 키 `claude-opus-5-5`로 $4 / $20 per MTok.
- **OpenAI GPT-6 Sol and GPT-6 Luna — 3 channels each** (launched 2026-09-22): Global CRIS `openai:global:global.openai.gpt-6-{sol,luna}` (Seoul `bedrock-runtime` OpenAI-compat), US CRIS `openai:us:us.openai.gpt-6-{sol,luna}` (us-east-1 `bedrock-runtime`) and Mantle in-region `openai:us-east-1:openai.gpt-6-{sol,luna}`. Mantle us-east-2 and us-west-2 return 404 `not_found_error` ("The model 'openai.gpt-6-sol' does not exist") and are left out — the opposite of Astra, which Mantle serves only in us-west-2. The first Mantle us-east-1 call returned 401 "Your subscription to the model is being set up" (Marketplace subscription starting) and 200 a few minutes later. Single-call latency from Seoul: Sol Global TTFB 559 / TTFT 856 ms, US 927 / 2059 ms; Luna Global 591 / 857 ms, US 919 / 1064 ms. New env `BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID` / `BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID` (Global/US profile ids are derived by the prober). Not added to the gptbench `_BENCH_SPECS` (cost decision), the `/claude-features` representative models or the dormant 1P specs.
- **OpenAI GPT-6 Sol, GPT-6 Luna — 모델마다 3채널** (2026-09-22 출시): Global CRIS `openai:global:global.openai.gpt-6-{sol,luna}`(서울 `bedrock-runtime` OpenAI-compat), US CRIS `openai:us:us.openai.gpt-6-{sol,luna}`(us-east-1 `bedrock-runtime`), Mantle 인리전 `openai:us-east-1:openai.gpt-6-{sol,luna}`. Mantle us-east-2, us-west-2는 404 `not_found_error`("The model 'openai.gpt-6-sol' does not exist")라 제외했다 — Mantle이 us-west-2에서만 서빙하는 Astra와 정반대다. Mantle us-east-1 첫 호출은 401 "Your subscription to the model is being set up"(Marketplace 구독 개시)이었고 수 분 뒤 200이 됐다. 서울 기준 단건 지연: Sol Global TTFB 559 / TTFT 856 ms, US 927 / 2059 ms, Luna Global 591 / 857 ms, US 919 / 1064 ms. 신규 env `BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID`, `BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID`(Global/US 프로파일 id는 prober가 파생). gptbench `_BENCH_SPECS`(비용 결정 사항), `/claude-features` 대표 모델, 휴면 1P 스펙에는 추가하지 않았다.
- Active catalog **46 → 55** (Bedrock 19 → 21, CP 8 → 9, OpenAI 19 → 25; 60 including the 5 dormant 1P channels). The parity run gains 361 cells per 12 h (184 probed, 177 pre-skipped).
- 활성 카탈로그 **46 → 55**(Bedrock 19 → 21, CP 8 → 9, OpenAI 19 → 25, 휴면 1P 5채널 포함 60). 패리티 런은 12시간당 361셀(프로브 184, 사전 skipped 177)이 늘어난다.

### Fixed
- **CP on AWS registered Opus 5.5 under the Opus 5 label (live).** Since the CP workspace began serving Opus 5.5, `/v1/models` lists `claude-opus-5-5` before `claude-opus-5`, and the `"opus-5"` substring target matched the 5.5 id: production was probing `anthropic:claude-opus-5-5` as `Anthropic Claude Opus 5 (US)` (first mislabeled registration in `/ecs/autoprober` at 2026-09-22 16:27 UTC, still on `/api/auto-probe/latest` at 2026-09-23 05:02 UTC — about 150 five-minute cycles) and the real Opus 5 CP channel was not measured. Besides the new `opus-5-5` target, `_match_anthropic_model` now rejects **point releases without a target of their own** via `_is_point_release_of()` — a substring followed by `-<1–2 digits>` that is not followed by another digit — so a future `claude-sonnet-5-5` cannot hijack the Sonnet 5 label either; 8-digit date suffixes (`claude-haiku-4-5-20251001`) still match. The existing `label_repair` step relabels the stored rows at backend startup. Same failure pattern as v2.22.1 (Fable 5.1).
- **CP on AWS가 Opus 5.5를 Opus 5 라벨로 등록하던 문제 (운영 발생).** CP 워크스페이스가 Opus 5.5를 서빙하기 시작한 뒤 `/v1/models`가 `claude-opus-5-5`를 `claude-opus-5`보다 먼저 돌려주면서 `"opus-5"` substring 타깃이 5.5 id에 매칭됐다. 운영은 `anthropic:claude-opus-5-5`를 `Anthropic Claude Opus 5 (US)`로 프로빙하고 있었고(`/ecs/autoprober` 로그상 첫 오등록 2026-09-22 16:27 UTC, 2026-09-23 05:02 UTC `/api/auto-probe/latest`에서도 확인 — 5분 주기 약 150사이클) 실제 Opus 5 CP 채널은 측정되지 않았다. 신규 `opus-5-5` 타깃에 더해 `_match_anthropic_model`이 이제 `_is_point_release_of()`로 **자기 타깃이 없는 점 버전**(substring 뒤에 `-<1~2자리 숫자>`가 오고 그 뒤가 숫자가 아닌 id)을 제외하므로, 앞으로 `claude-sonnet-5-5` 같은 점 버전도 Sonnet 5 라벨을 가로챌 수 없다. 8자리 날짜 서픽스(`claude-haiku-4-5-20251001`)는 기존대로 매칭된다. 이미 기록된 행은 기존 `label_repair` 단계가 backend 기동 시 정정한다. v2.22.1(Fable 5.1)과 같은 실패 패턴이다.

### Changed
- **GPT-6 Astra pricing is now filled from the official AWS model card** (Standard tier, ≤ 272K input): in-region and Geo CRIS (US) $11 / $55, Global CRIS $10 / $50 per MTok — keys `gpt-6-astra`, `gpt-6-astra-us`, `gpt-6-astra-global` added together so the prefix fallback cannot cross-match channels. Costs are computed at query time, so Astra rows since v2.25.0 are priced retroactively and the v2.25.1 "bench cost not estimable" caveat is resolved.
- **GPT-6 Astra 단가를 AWS 공식 모델 카드 기준으로 반영했다**(Standard, 입력 272K 이하): 인리전과 Geo CRIS(US) $11 / $55, Global CRIS $10 / $50 per MTok. prefix fallback이 채널을 교차 매칭하지 않도록 `gpt-6-astra`, `gpt-6-astra-us`, `gpt-6-astra-global` 3키를 함께 추가했다. 비용은 조회 시점에 계산하므로 v2.25.0 이후 Astra 행도 소급 산정되고, v2.25.1의 "벤치 비용 추정 불가" 유의점이 해소됐다.
- GPT-6 Sol/Luna pricing stays unset (AWS has not published model cards and the Price List API has no entry): all six channels show "-" and a regression test pins that none of them falls back to an Astra key. Parity `_REASONING_MARKERS` still excludes `gpt-6` — the exact parity probe (effort `low`, "17 x 23은?") reports `reasoning_tokens=0` for Sol and Luna on both `chat_completions` and `responses` (13 / 18 only at effort `high`), so adding the marker would mark them unsupported.
- GPT-6 Sol/Luna 단가는 미기재로 둔다(AWS 모델 카드 미게재, Price List API 항목 없음). 6채널 모두 "-"로 표시되며, 어느 채널도 Astra 키로 fallback되지 않음을 회귀 테스트로 고정했다. 패리티 `_REASONING_MARKERS`는 여전히 `gpt-6`을 제외한다 — 패리티 프로브 그대로(effort `low`, "17 x 23은?") 호출하면 Sol, Luna 모두 `chat_completions`, `responses`에서 `reasoning_tokens=0`이고(effort `high`에서만 13 / 18) 마커를 넣으면 미지원으로 판정된다.

### Infra
- `BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID=openai.gpt-6-sol` and `BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID=openai.gpt-6-luna` are injected by both the AppServices (backend) and Scheduler (`buildTaskDef`) stacks, pinned by two new CDK tests. This is an env-adding release: deploy both stacks with the digest-pinned CDK path — the image-only path would leave the env out and the prober would silently skip the six GPT-6 Sol/Luna channels. No IAM change.
- `BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID=openai.gpt-6-sol`, `BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID=openai.gpt-6-luna`를 AppServices(backend)와 Scheduler(`buildTaskDef`) 두 스택이 모두 주입하며, CDK 테스트 2건으로 고정했다. env가 추가되는 릴리스이므로 digest 고정 CDK 경로로 두 스택을 함께 배포해야 한다 — 이미지만 교체하면 env가 빠져 prober가 GPT-6 Sol/Luna 6채널을 조용히 건너뛴다. IAM 변경 없음.

### Docs
- New **ADR-028** (channel sets, point-release guard, pricing policy, parity markers, deploy path); ADR-027 gains a v2.27.0 follow-up (Astra prices filled, Mantle us-east-1/us-east-2 still 404 on 2026-09-23). `CLAUDE.md`, `README.md`, `docs/architecture.md` and `docs/api-reference.md` now read 55 active channels. Tests: backend 299 (new `tests/test_opus55_gpt6_catalog.py`), frontend vitest 150 + `tsc`, CDK 77.
- **ADR-028**을 신설했다(채널 구성, 점 버전 가드, 단가 정책, 패리티 마커, 배포 경로). ADR-027에는 v2.27.0 후속(Astra 단가 반영, 2026-09-23 Mantle us-east-1, us-east-2 여전히 404)을 덧붙였다. `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/api-reference.md`를 활성 55채널로 갱신했다. 테스트: backend 299(신규 `tests/test_opus55_gpt6_catalog.py`), frontend vitest 150 + `tsc`, CDK 77.
- Version bumped to **v2.27.0** (`frontend/src/lib/version.ts`, `frontend/package.json`, `backend/main.py` FastAPI version, `README.md` badge, `CLAUDE.md` overview).
- 버전을 **v2.27.0**으로 범프했다(`frontend/src/lib/version.ts`, `frontend/package.json`, `backend/main.py` FastAPI version, `README.md` 배지, `CLAUDE.md` 개요).

## v2.26.1 — 2026-09-22

### Fixed
- Restore focus after a prompt deletion only after the confirmation dialog unmounts. A frame callback could run while the page was still inert, leaving keyboard focus on the document body in CI.
- 프롬프트 삭제 후 확인 대화상자가 닫힌 다음 목록으로 포커스를 복구한다. 페이지가 아직 비활성 상태일 때 프레임 콜백이 실행되어 포커스가 본문에 남을 수 있던 문제를 수정했다.

## v2.26.0 — 2026-09-22

### Added
- Monitoring overview with observed coverage, fresh success, attention counts, last-run success rate, and an accessible channel status strip. Search, health filters and sorting make failures, stale results and unmeasured channels easy to locate; filters and comparison selections remain shareable in the URL.
- 모니터링 채널·정상·확인 필요·최신 실행 성공률 요약과 채널별 상태 표시를 추가했다. 모델 검색, 상태 필터, 정렬로 오류·수집 지연·미수집 채널을 찾을 수 있으며, 필터와 비교 선택을 URL로 공유할 수 있다.
- Browser regression tests covering partial failures, request races, login, keyboard navigation, dialogs, mobile layouts, themes and languages. CI runs these against the production build; `make verify` now also runs frontend unit tests.

### Changed
- Shared navigation, authentication, language preferences, request state, refresh controls and dialogs across monitoring pages. Public dashboards render while authentication is being checked; temporary service failures preserve sessions. Manual probing has a reloadable URL (`/?view=manual`).
- 모니터링 화면의 메뉴·로그인·언어·조회 상태·새로고침·대화상자 동작을 통일했다. 로그인 확인 중에도 공개 화면을 표시하고, 일시적인 서버 오류로 로그아웃되지 않게 했다. 수동 프로브는 `/?view=manual`로 직접 열 수 있다.
- Charts use actual elapsed time, date-aware labels and explicit gaps for failed/missing measurements. Legends stay outside the plot, and functional labels and state colors remain readable in both themes.

### Fixed
- Delayed requests no longer overwrite newly selected periods or categories. Errors are distinct from empty datasets, successful companion sections remain visible, and retry is available without changing filters. Cost projections use the period of the returned data.
- Auto-probe status is based on database reservations, with overdue and crashed-run handling. Manual triggers require authentication, return `202` on acceptance and `409` for an active cycle; scheduler and manual admission share a transaction lock. Anomaly counts exclude manual probes and respect the workload filter.
- 자동 수집 상태를 DB 실행 기록과 연동하고 지연·실패를 구분했다. 수동 실행에 인증과 중복 실행 방지를 적용했으며, 이상 징후 집계는 자동 프로브와 선택한 워크로드를 기준으로 한다. 시간별 추세 평균에 실패 호출의 지연시간이 섞이지 않게 했다.
- Interrupted manual streams report failure while preserving partial results; Korean composition Enter no longer sends an unfinished chat message.

### Security
- Upgrade Next.js to 16.3.5 and refresh compatible dependencies. Migrate the shared layout to asynchronous cookies and the HTML cache guard to the `proxy.ts` convention; preserve the existing API/static-asset exclusions.
- Next.js 16.3.5와 호환 종속성 보안 패치를 적용했다. 공용 레이아웃의 쿠키 접근을 비동기로 전환하고 HTML 캐시 보호를 `proxy.ts` 규약으로 옮겼다. API·정적 자산 제외 규칙은 유지한다.

## v2.25.1 — 2026-09-11

### Added
- **GPT-6 Astra joins the `/gpt-on-aws` bench — 9 → 12 channels** — `_BENCH_SPECS` gains `("GPT 6 Astra", "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", ("global", "us", "us-west-2"))`, i.e. `OpenAI GPT 6 Astra (Global)` (Seoul `bedrock-runtime` OpenAI-compat), `OpenAI GPT 6 Astra (US)` (the `us` pseudo-region added in v2.25.0, us-east-1 `bedrock-runtime`) and `OpenAI GPT 6 Astra (us-west-2)` (Bedrock Mantle in-region). Mantle us-east-1 / us-east-2 are deliberately left out — they answer 404 `not_found_error` for Astra (2026-09-09), and a 404 region would turn every 15-minute cycle into error rows. Live-verified 2026-09-11 with the production Mantle bearer key and the exact bench request shape (`text.format` + `verbosity: low`, `reasoning.effort: medium`, `include: ["reasoning.encrypted_content"]`, `store: false`, `prompt_cache_retention: "24h"`): **no parameter was rejected** — Global TTFB 1762 ms / TTFT 3069 ms, US 1904 / 3223 ms, us-west-2 1193 / 1930 ms, input 55,839 tokens (55,837 cached on the US and us-west-2 routes; Global was a cold cache on its first call, which the per-channel warm-up call absorbs in a real cycle). `reasoning_tokens` reads 0 on all three, consistent with ADR-027 — GAP (TTFT−TTFB) is still measured, so the reasoning-token line on the card reads 0 while the latency numbers are real.
- **GPT-6 Astra를 `/gpt-on-aws` 벤치에 편입 — 9 → 12채널** — `_BENCH_SPECS`에 `("GPT 6 Astra", "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", ("global", "us", "us-west-2"))`를 추가했다. 즉 `OpenAI GPT 6 Astra (Global)`(서울 `bedrock-runtime` OpenAI-compat), `OpenAI GPT 6 Astra (US)`(v2.25.0에서 도입한 유사 리전 `us`, us-east-1 `bedrock-runtime`), `OpenAI GPT 6 Astra (us-west-2)`(Bedrock Mantle 인리전) 3채널이다. Mantle us-east-1, us-east-2는 의도적으로 제외한다 — Astra에 404 `not_found_error`를 반환하며(2026-09-09 실측) 404 리전을 넣으면 15분 사이클마다 오류 행만 쌓인다. 2026-09-11 운영 Mantle bearer 키로 벤치 요청 형태 그대로 라이브 검증(`text.format` + `verbosity: low`, `reasoning.effort: medium`, `include: ["reasoning.encrypted_content"]`, `store: false`, `prompt_cache_retention: "24h"`): **거부된 파라미터 없음** — Global TTFB 1762 ms / TTFT 3069 ms, US 1904 / 3223 ms, us-west-2 1193 / 1930 ms, 입력 55,839 토큰(US, us-west-2 경로는 55,837 캐시 히트, Global은 첫 호출이라 캐시 미스 — 실제 사이클에서는 채널별 워밍업 1회가 이를 흡수한다). `reasoning_tokens`는 세 채널 모두 0으로 ADR-027과 일치한다 — GAP(TTFT−TTFB)은 그대로 측정되므로 카드의 reasoning 토큰 줄만 0이고 지연 수치는 실측값이다.
- **Bench panel: a 4th family column and a 5th region colour** — the score-card grid becomes `grid-cols-1 md:grid-cols-2 xl:grid-cols-4` with columns GPT 6 Astra, GPT 5.6 Terra, GPT 5.5, GPT 5.4; `REGION_COLORS` gains `"US": "#db2777"` (pink-600 — 4.60:1 on white, 3.88:1 on the dark card ground) and `FAMILY_DASH` gains `"GPT 6 Astra": "10 3 2 3"` (dash-dot), so the 12 trend lines stay distinguishable by colour = region × pattern = family. `regionOf` now matches `(US)` without swallowing `(us-west-2)` and `familyOf` checks `"6 Astra"` first (its fallback is GPT 5.4, so the order matters); both are exported and pinned by 5 new vitest cases.
- **벤치 패널에 4번째 family 열과 5번째 리전 색** — 스코어 카드 그리드를 `grid-cols-1 md:grid-cols-2 xl:grid-cols-4`로 바꾸고 열을 GPT 6 Astra, GPT 5.6 Terra, GPT 5.5, GPT 5.4로 배치했다. `REGION_COLORS`에 `"US": "#db2777"`(pink-600 — 흰 배경 4.60:1, 다크 카드 배경 3.88:1), `FAMILY_DASH`에 `"GPT 6 Astra": "10 3 2 3"`(일점쇄선)을 추가해 12개 추이 선이 색 = 리전, 패턴 = family 규칙으로 계속 구분된다. `regionOf`는 `(us-west-2)`를 먹지 않고 `(US)`를 인식하며, `familyOf`는 `"6 Astra"`를 먼저 검사한다(기본값이 GPT 5.4라 순서가 중요하다). 두 함수를 export하고 vitest 회귀 5건으로 고정했다.

### Changed
- **`bench_channels` stops duplicating the channel-id derivation** — the inline region→env dict and the `region == "global"` special case are gone; the function lazy-imports `_OPENAI_REGION_ENV` and `_OPENAI_PSEUDO_REGIONS` from `prober` (the same lazy-import style as `_client_for`) and derives the `global.`/`us.` prefixes and the `(Global)`/`(US)` label suffixes from that single source. `gpt_bench_results.model_id` / `model_name` are therefore **byte-identical** to the dashboard channels that `prober._register_openai_models` registers — pinned by a new test that registers the prober catalog under the same env and asserts every bench channel key maps to the same label. A missing base-URL env still skips only that channel (`OPENAI_US_BASE_URL` unset → the US channel drops, the other 11 remain).
- **`bench_channels`의 채널 id 파생 중복 제거** — 인라인 리전→env dict와 `region == "global"` 특수 분기를 없애고 `prober`의 `_OPENAI_REGION_ENV`, `_OPENAI_PSEUDO_REGIONS`를 지연 import한다(`_client_for`와 동일한 지연 import 방식). `global.`/`us.` 접두사와 `(Global)`/`(US)` 라벨 서픽스를 그 한 곳에서만 파생하므로 `gpt_bench_results.model_id`, `model_name`이 `prober._register_openai_models`가 등록하는 대시보드 채널과 **바이트 동일**하다 — 같은 env로 prober 카탈로그를 등록해 모든 벤치 채널 키가 동일 라벨로 매핑되는지 확인하는 테스트로 고정했다. base-URL env가 없으면 여전히 해당 채널만 빠진다(`OPENAI_US_BASE_URL` 미설정 → US 채널만 제외, 나머지 11채널 유지).
- **Card order: Astra first** — the `/api/gptbench/latest` `fam_rank` becomes `{"GPT 6 Astra": 0, "GPT 5.6 Terra": 1, "GPT 5.5": 2, "GPT 5.4": 3}`, so the Astra cards head the list in region order Global, US, us-west-2 (the alphabetical region sort already yields that order). Without the rank entry Astra would fall to rank 9 and render last.
- **카드 정렬: Astra가 맨 앞** — `/api/gptbench/latest`의 `fam_rank`를 `{"GPT 6 Astra": 0, "GPT 5.6 Terra": 1, "GPT 5.5": 2, "GPT 5.4": 3}`로 바꿨다. Astra 카드가 Global, US, us-west-2 순서로 맨 앞에 온다(리전 알파벳 정렬이 이미 그 순서다). rank 항목이 없으면 Astra는 rank 9로 밀려 맨 뒤에 찍힌다.
- **Cost: not estimable in this release** — Astra pricing is still undetermined (no GPT-6 entry in the Price List API, see v2.25.0 / ADR-027), so the incremental **bench cost cannot be quantified**, only its volume: 3 channels × 10 measured calls × 96 cycles/day against the fixed ~55.8k-token prompt ≈ **160 M input tokens/day** (≈ 177 M including the per-channel warm-up call), almost all of it prompt-cache hits (55,837 of 55,839 measured), with output ~30 tokens per call. Cycle-deadline headroom was checked against production logs: the 9-channel cycle currently takes 171–197 s (one 313 s outlier) and the three Astra channels add ≈ 106 s at the measured 2.2–3.6 s per call, so a 12-channel cycle lands near **4.8 min** (≈ 7 min in the outlier case) — well inside the 13-minute `GPT_BENCH_DEADLINE`, so `GPT_BENCH_RUNS` was left at 10.
- **비용: 이번 릴리스에서는 추정 불가** — Astra 단가는 여전히 미확정이라(Price List API에 GPT-6 항목 없음, v2.25.0 및 ADR-027 참조) 벤치 **증분 비용을 금액으로 산정할 수 없고** 물량만 제시한다: 3채널 × 측정 10회 × 96사이클/일에 ~55.8k 토큰 고정 프롬프트이므로 입력 **약 1.6억 토큰/일**(채널별 워밍업 1회 포함 시 약 1.77억)이며 대부분 프롬프트 캐시 히트(실측 55,839 중 55,837), 출력은 호출당 30토큰 수준이다. 사이클 데드라인 여유는 운영 로그로 확인했다 — 9채널 사이클이 현재 171~197초(이상치 1건 313초)이고 Astra 3채널이 호출당 실측 2.2~3.6초 기준 약 106초를 더하므로 12채널 사이클은 **약 4.8분**(이상치 상황 약 7분)이며 13분 `GPT_BENCH_DEADLINE` 안에 충분히 들어간다. 그래서 `GPT_BENCH_RUNS`는 10 그대로 두었다.

### Docs
- `CLAUDE.md` (page list, scheduler block, `gptbench.py` line) and `docs/architecture.md` (KO/EN scheduler diagrams, GptBench TaskDef row) now read 12 channels; the GPT-6 Astra bullet records `gptbench _BENCH_SPECS` **inclusion** (v2.25.1) instead of the old "not included / decision pending", and the Global CRIS bullet's stale "not in gptbench" claim is corrected to "Terra Global only (v2.20.1), Sol/Luna Global excluded". **ADR-027** keeps its original decision bullet and appends the v2.25.1 follow-up (spec tuple, prober-sourced derivation, cost caveat, deadline), and its consequence "Astra is not visible in the bench" is marked resolved with the remaining caveat (cost not estimable). No CDK change was needed — `SchedulerStack` `buildTaskDef` already injects `OPENAI_US_BASE_URL` and `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID` (v2.25.0) and `GptBenchTaskDef` is built by that shared builder.
- `CLAUDE.md`(페이지 목록, 스케줄러 블록, `gptbench.py` 줄)와 `docs/architecture.md`(KO/EN 스케줄러 다이어그램, GptBench TaskDef 행)를 12채널로 갱신했다. GPT-6 Astra 불릿은 기존 "미포함, 별도 결정 필요" 대신 `gptbench _BENCH_SPECS` **포함**(v2.25.1)을 기록하고, Global CRIS 불릿의 낡은 "gptbench 미포함" 서술은 "Terra Global만 포함(v2.20.1), Sol/Luna Global은 미포함"으로 교정했다. **ADR-027**은 원래 결정 불릿을 남기고 v2.25.1 후속(스펙 튜플, prober 기반 파생, 비용 유의, 데드라인)을 덧붙였으며, "벤치에 Astra가 보이지 않는다"는 결과 항목은 해소로 표시하고 남은 유의점(비용 추정 불가)을 명시했다. CDK 변경은 필요 없었다 — `SchedulerStack` `buildTaskDef`가 이미 `OPENAI_US_BASE_URL`과 `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID`를 주입하고(v2.25.0) `GptBenchTaskDef`가 그 공용 빌더로 만들어진다.
- Version bumped to **v2.25.1** in all five touchpoints (`frontend/src/lib/version.ts`, `frontend/package.json`, `backend/main.py` FastAPI version, `README.md` badge, `CLAUDE.md` overview).
- 버전을 다섯 곳 모두 **v2.25.1**로 범프했다(`frontend/src/lib/version.ts`, `frontend/package.json`, `backend/main.py` FastAPI version, `README.md` 배지, `CLAUDE.md` 개요).

## v2.25.0 — 2026-09-09

### Added
- **OpenAI GPT-6 Astra — 3 new monitored channels** (active catalog 43 → 46, OpenAI 16 → 19): `OpenAI GPT 6 Astra (Global)` (`openai:global:global.openai.gpt-6-astra`, Seoul `bedrock-runtime` OpenAI-compat — the existing Global CRIS path), **`OpenAI GPT 6 Astra (US)`** (`openai:us:us.openai.gpt-6-astra`) over a **new pseudo-region `us`** routed by the new env `OPENAI_US_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1`, and `OpenAI GPT 6 Astra (us-west-2)` (`openai:us-west-2:openai.gpt-6-astra`, Bedrock Mantle in-region). One env carries the model (`BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID=openai.gpt-6-astra`); the prober derives the `global.`/`us.` profile ids from it. Live-verified 2026-09-09 with the production Bedrock key (Responses API): Global 200 (usage in 13 / out 5), US 200, Mantle us-west-2 200. Reliability, cost, analysis, efficiency, anomalies, chatbot tools and the parity run pick the channels up dynamically (114 extra parity cells per 12h run: 48 probed + 66 pre-skipped — `reasoning`/`reasoning_effort` stay skipped because Astra accepts the reasoning parameters but reports `reasoning_tokens: 0`, see ADR-027). See ADR-027.
- **OpenAI GPT-6 Astra 모니터링 채널 3개 추가** (활성 카탈로그 43 → 46, OpenAI 16 → 19): `OpenAI GPT 6 Astra (Global)`(`openai:global:global.openai.gpt-6-astra`, 서울 `bedrock-runtime` OpenAI-compat — 기존 Global CRIS 경로), **`OpenAI GPT 6 Astra (US)`**(`openai:us:us.openai.gpt-6-astra`) — **신규 유사 리전 `us`**를 신규 env `OPENAI_US_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1`로 라우팅, `OpenAI GPT 6 Astra (us-west-2)`(`openai:us-west-2:openai.gpt-6-astra`, Bedrock Mantle 인리전). 모델 id env는 `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID=openai.gpt-6-astra` 하나이며 `global.`/`us.` 프로파일 id는 프로버가 파생한다. 2026-09-09 운영 Bedrock 키(Responses API) 라이브 검증: Global 200(usage in 13 / out 5), US 200, Mantle us-west-2 200. 신뢰성, 비용, 분석, 효율, 이상 징후, 챗봇 tools, 패리티 런은 동적이라 자동 편입(12h 런당 114셀 증가: 프로브 48 + 사전 skipped 66 — `reasoning`/`reasoning_effort`는 Astra가 파라미터는 수락하나 `reasoning_tokens`를 0으로 보고해 skipped 유지, ADR-027 참조). ADR-027 참조.

### Changed
- **Mantle in-region is us-west-2 only for GPT-6 Astra** — `bedrock-mantle.us-east-1` and `bedrock-mantle.us-east-2` answer 404 `not_found_error` ("The model does not exist") for `openai.gpt-6-astra` while Bedrock model access reads AVAILABLE/AUTHORIZED in every region, so this is Mantle host onboarding, not entitlement. Those two channels are deliberately **not** registered — a spec region that 404s turns every 5-minute probe into an error row and poisons the reliability and anomaly views. Re-checking Mantle onboarding is a follow-up. The plain id (`openai.gpt-6-astra`, no profile prefix) is not on-demand invocable at all.
- **GPT-6 Astra의 Mantle 인리전은 us-west-2 단독** — `bedrock-mantle.us-east-1`, `bedrock-mantle.us-east-2`는 `openai.gpt-6-astra`에 404 `not_found_error`("The model does not exist")를 반환한다. 같은 계정의 Bedrock 모델 액세스는 세 리전 모두 AVAILABLE/AUTHORIZED이므로 엔티틀먼트가 아니라 Mantle 호스트 온보딩 미완이다. 404가 나는 리전을 스펙에 넣으면 5분마다 오류 행만 쌓여 신뢰성, 이상 징후 화면을 오염시키므로 두 채널은 **등록하지 않는다**. Mantle 온보딩 재확인은 후속 과제. 접두사 없는 평문 id(`openai.gpt-6-astra`)는 온디맨드 호출 자체가 불가하다(추론 프로파일 필요).
- **Pricing left unset on purpose — follow-up** — the Price List API has no GPT-6 entry, so no `PRICE_TABLE` keys were added and `get_pricing` / `getPricing` return `None` / `null` for all three ids (the prefix fallback matches nothing — pinned by regression tests both sides), which renders cost as "-" instead of a wrong number. `_normalize_key` handles the new region segment with the existing `("global","us","eu","apac")` rule: `us.openai.gpt-6-astra` → `gpt-6-astra-us` (parallel to `-global`), Mantle in-region stays `gpt-6-astra`. Once the official rate is published, adding `gpt-6-astra`, `gpt-6-astra-global` and `gpt-6-astra-us` retro-computes every stored probe (cost is calculated at query time).
- **단가는 의도적으로 미확정 — 후속 업데이트** — Price List API에 GPT-6 항목이 없어 `PRICE_TABLE`에 키를 넣지 않았고, `get_pricing`/`getPricing`은 세 id 모두 `None`/`null`을 반환한다(접두 fallback 오매칭 없음 — 양쪽 회귀 테스트로 고정). 잘못된 숫자 대신 비용이 "-"로 표시된다. `_normalize_key`는 신규 리전 세그먼트를 기존 `("global","us","eu","apac")` 규칙으로 처리한다: `us.openai.gpt-6-astra` → `gpt-6-astra-us`(`-global`과 대칭), Mantle 인리전은 `gpt-6-astra` 유지. 공식 단가가 나오면 `gpt-6-astra`, `gpt-6-astra-global`, `gpt-6-astra-us` 3키만 추가하면 비용은 조회 시점 계산이라 저장된 프로브에 소급 반영된다.
- Display order inside the OpenAI block is Global → US → regions (`channelRank`), with `GPT 6 Astra` at the top of the OpenAI family order; `MODEL_COLORS`, `StreamingView` and the Model Explorer render the three labels, the `us` pseudo-region endpoint and the `us.openai.gpt-6-astra` code examples.
- OpenAI 블록 내부 표시 순서는 Global → US → 리전(`channelRank`)이고 OpenAI 패밀리 순서 맨 앞이 `GPT 6 Astra`다. `MODEL_COLORS`, `StreamingView`, 모델 탐색기가 라벨 3종과 `us` 유사 리전 엔드포인트, `us.openai.gpt-6-astra` 코드 예제를 렌더한다.

### Infra
- **CDK: `OPENAI_US_BASE_URL` + `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID` injected in both stacks** — `AppServicesStack` `backendEnv` and `SchedulerStack` `buildTaskDef` (the shared builder for autoprober, insights, parityrun, gptbench, featuresverify). No IAM change (bearer-token path; Fargate egress already reaches the us-east-1 and us-west-2 hosts). ⚠️ This release adds env, so the image-only deploy path (deploy.md §6 / §2-1) must not be used — it copies the old task definition's env, and the prober **silently skips** a channel whose base-URL env is missing.
- **CDK: 두 스택에 `OPENAI_US_BASE_URL` + `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID` 주입** — `AppServicesStack` `backendEnv`와 `SchedulerStack` `buildTaskDef`(autoprober, insights, parityrun, gptbench, featuresverify 공용 빌더). IAM 변경 없음(bearer 경로이며 Fargate egress는 이미 us-east-1, us-west-2 호스트에 도달). ⚠️ 신규 env가 추가된 릴리스이므로 이미지-only 배포 경로(deploy.md §6 / §2-1)를 쓰면 안 된다 — 기존 task definition의 env가 복사돼 신규 env가 누락되고, prober는 base_url env가 없는 채널을 **조용히 skip**한다.

### Docs
- New **ADR-027** (GPT-6 Astra: inference-profile-only model, US CRIS pseudo-region `us`, Mantle in-region us-west-2 only, pricing follow-up) with the live 200/404 matrix; monitored-model tables in `CLAUDE.md` (new **US CRIS** column + GPT 6 Astra row + channel/env bullet), `README.md`, `docs/architecture.md` updated to 46 active / OpenAI 19; `docs/api-reference.md` `model_count` corrected to 46 (was a stale 42); `docs/runbooks/deploy.md` OpenAI verification now expects 19 rows (Mantle 14 + Global 4 + US 1) and names the new envs in the image-only-deploy warning.
- **ADR-027** 신설(GPT-6 Astra: 추론 프로파일 전용, US CRIS 유사 리전 `us`, Mantle 인리전 us-west-2 단독, 단가 후속 과제) — 라이브 200/404 매트릭스 포함. `CLAUDE.md` 모니터링 모델 표에 **US CRIS** 열과 GPT 6 Astra 행, 채널/env 설명 추가; `README.md`, `docs/architecture.md`를 활성 46개 / OpenAI 19개로 갱신; `docs/api-reference.md` `model_count`를 46으로 교정(낡은 42); `docs/runbooks/deploy.md` OpenAI 검증 기댓값을 19행(Mantle 14 + Global 4 + US 1)으로, 이미지-only 배포 경고에 신규 env 명시.

## v2.24.0 — 2026-09-07

### Added
- **Claude API Features detail parity with `/parity`** (`/claude-features`) — health cards now headline **documented health** (share of documented GA/Beta cells that measured supported — Mantle reads 63% on run #3 instead of a misleading 100%) with a 6-state distribution bar over every cell, a "{total} cells" chip, a drift pill and a counts line; clicking a card opens a **Key Findings drawer** (documentation drift by feature, probe errors, intended gaps, documentation undecided, undocumented behaviour, per-model documented health — Mantle Fable 5.1 shows its reason instead of a bar); **model chips** (All / Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5) narrow cells, cards, banners and the drawer to one model; the run meta line gains the run duration and a totals strip; cell tooltips list per-model probe wall-clock latency (sub-millisecond route-gated cells as "<1 ms") and the per-model dropdown shows ms + the mono model id; a methodology sentence and a verification-strength legend (evidence / acceptance / negative / capability) with tag tooltips.
- **Claude API Features 상세도를 `/parity` 수준으로 보강** (`/claude-features`) — 헬스 카드 헤드라인을 **문서 기준 헬스**(문서상 GA/Beta 셀 중 실측 supported 비율 — run #3 Mantle은 오독을 부르던 100% 대신 63%)로 바꾸고 전체 셀 6상태 분포 막대, "{total} 셀" 칩, 드리프트 pill, 카운트 줄을 추가; 카드 클릭 → **Key Findings 드로어**(피처별 문서 드리프트, 프로브 오류, 의도된 격차, 문서 미확정, 문서에 없는 동작, 모델별 문서 일치율 — Mantle Fable 5.1은 막대 대신 사유); **모델 칩**(전체/Fable 5.1/Fable 5/Opus 5/Sonnet 5)으로 셀, 카드, 배너, 드로어를 모델 하나로 좁힘; 런 메타 줄에 소요 시간과 합계 스트립; 셀 툴팁에 모델별 프로브 소요 시간(라우트 게이트 셀은 "<1 ms"), 드롭다운에 ms + mono model id; 방법론 문장과 검증 강도 4종 범례(evidence/acceptance/negative/capability) 및 태그 툴팁.
- **`/api/features/latest` `changes[].kind`** — `"catalog"` (the cell did not exist in the previous run, or either side is a runner pre-decided row — `latency_ms IS NULL AND error_message IS NULL`; a NULL latency *with* an error message is a failed probe and stays `"measured"`) vs `"measured"`; the changes banner tags each item and summarises "카탈로그 규칙 변경 N건, 실측 변경 M건". Run #2→#3's 15 changes were all catalog rule changes (`data_residency` → N/A on Bedrock) that the banner could not tell from measured regressions.
- **`/api/features/latest` `changes[].kind`** — `"catalog"`(직전 런에 없던 셀, 또는 어느 한쪽이 러너 사전판정 행 — `latency_ms IS NULL AND error_message IS NULL`; latency가 없어도 `error_message`가 있으면 프로브 실패이므로 `"measured"` 유지) vs `"measured"`; 변경 배너가 항목마다 태그를 붙이고 "카탈로그 규칙 변경 N건, 실측 변경 M건"으로 요약. run #2→#3의 변경 15건은 전부 카탈로그 규칙 변경(`data_residency` → Bedrock N/A)이었는데 배너가 실측 회귀와 구분하지 못했다.
- **Evidence for failed cells** — transports record the last request body per thread (`record_request`/`last_request`) and `run_probe` keeps it on `TransportError` and generic exceptions (previously only `{"model"}` — 182 of the 206 unsupported cells on run #3, including all 25 drift cells); boto `ClientError` messages keep the AWS operation name (`ValidationException (CountTokens): …`); empty error bodies name the route (`HTTP 404: (empty body) GET /v1/files`); request-snapshot meta keys unified to `api`/`note` (`count_tokens`, `messages (stream)`, `GET /v1/models/{id}`, `2 calls: effort=low, then effort=ultra as negative control`, …); thinking probes store `usage`. `engine.classify` is unchanged — 38 regression pins (24 live error strings + 14 before/after pairs) prove identical verdicts.
- **실패 셀 증거** — 전송기가 스레드별 마지막 요청 본문을 기록(`record_request`/`last_request`)하고 `run_probe`가 `TransportError`·일반 예외 경로에서 회수(종전에는 `{"model"}`만 — run #3 unsupported 206셀 중 182셀, 드리프트 25건 전부); boto `ClientError` 문구에 AWS operation 이름 유지(`ValidationException (CountTokens): …`); 빈 오류 본문은 라우트를 표기(`HTTP 404: (empty body) GET /v1/files`); 요청 스냅샷 메타 키를 `api`/`note`로 통일(`count_tokens`, `messages (stream)`, `GET /v1/models/{id}`, `2 calls: effort=low, then effort=ultra as negative control` 등); thinking 프로브는 `usage` 저장. `engine.classify`는 불변 — 회귀 핀 38건(라이브 오류 문자열 24 + 전후 형식 쌍 14)으로 동일 판정 보장.

### Changed
- **Banners** — the changes banner is always rendered when a previous run exists: the list ("외 N건" beyond 10, each item opens the evidence modal, after-status pill in the 6-state style — N/A was painted amber) or a gray "이전 런(#N) 대비 변경 없음." card; the drift banner shows a gray "문서 드리프트 없음." card when there is no drift. Drift banner, changes banner, evidence modal title and drawer use catalog labels (feature label + surface short name) with raw ids in mono as secondary text.
- **배너** — 직전 런이 있으면 변경 배너를 항상 렌더: 목록(10건 초과 "외 N건", 항목 클릭 → 증거 모달, after 상태 pill은 6상태 스타일 — N/A가 amber로 찍히던 문제 수정) 또는 회색 "이전 런(#N) 대비 변경 없음." 카드; 드리프트 0건이면 회색 "문서 드리프트 없음." 카드. 드리프트 배너, 변경 배너, 증거 모달 제목, 드로어는 카탈로그 라벨(피처 라벨 + surface 약칭)을 쓰고 원시 id는 mono 보조 표기.
- **Filter vs collapsed groups** — an active status/drift filter forces every group open (toggle disabled, chevron hidden), fixing matching rows hidden under a group collapsed earlier; "모두 펼치기 / 모두 접기" buttons appear when no filter is active. The model chip does not force groups open.
- **필터와 접힌 그룹** — 상태/드리프트 필터가 켜지면 모든 그룹을 강제로 펼침(토글 무효, chevron 숨김) — 접어 둔 그룹 아래에 매칭 행이 가려지던 결함 수정; 필터가 없을 때 "모두 펼치기 / 모두 접기" 버튼. 모델 칩은 그룹을 강제로 펼치지 않는다.
- Catalog descriptions of `server_side_fallback` and `compaction` now state why they are acceptance-only rows (a fallback fires only on a refusal; compaction only past the input-token trigger). `CATALOG_VERSION` is unchanged (wording only).
- `server_side_fallback`, `compaction`의 카탈로그 desc에 acceptance 행인 사유를 명시(fallback은 refusal 때만, 컴팩션은 입력 토큰 trigger 초과 때만 발동). `CATALOG_VERSION`은 유지(문구만 변경).

### Docs
- `docs/api-reference.md` gains a `/api/features` section (catalog, latest incl. `changes[].kind`, evidence incl. the `api`/`note` snapshot keys, trigger "약 7분") and corrects the parity trigger duration ("~3 min" → 약 5-10분); ADR-026 gets a "v2.24.0 UI 상세도 보강" addendum; `CLAUDE.md` corrects the per-run count to 643 probes + 137 pre-decided and adds the release-checklist line "catalog rule changes → bump `CATALOG_VERSION`"; `frontend/src/components/CLAUDE.md` records that `ClaudeFeaturesPanel` uses the inline `L(en, ko)` helper instead of `i18n.ts` and fixes the stale ParityPanel "도넛" wording (segment bar since v2.16.3).
- `docs/api-reference.md`에 `/api/features` 섹션 추가(catalog, `changes[].kind` 포함 latest, `api`/`note` 스냅샷 키 포함 evidence, trigger "약 7분") 및 패리티 트리거 소요 시간 교정("~3 min" → 약 5-10분); ADR-026에 "v2.24.0 UI 상세도 보강" 부록; `CLAUDE.md`의 런당 수치를 프로브 643 + 사전판정 137로 교정하고 릴리스 체크리스트에 "카탈로그 규칙 변경 시 `CATALOG_VERSION` 범프" 추가; `frontend/src/components/CLAUDE.md`에 `ClaudeFeaturesPanel`이 `i18n.ts` 대신 인라인 `L(en, ko)` 헬퍼를 쓴다는 예외를 기록하고 ParityPanel의 낡은 "도넛" 표기(v2.16.3부터 세그먼트 막대)를 수정.

### Fixed
- **`/claude-features` final-review fixes** — the sticky feature column now paints above horizontally scrolled cell badges (`z-20`/`z-10` on the sticky header/body cells — feature labels were covered whenever the matrix scrolled); the changes-banner feature link is readable in the light theme (theme-remapped `amber-200` — `amber-100` measured 1.04:1 on the banner); the Key Findings drawer keeps its header (×) sticky, closes on Escape and leaves a 2.5rem tap-out gutter on phones; with a model chip selected the drawer meta line reads "<model> only, N cells" and section 6 lists only that model (unselected models no longer appear as "no documented probed cells"); the evidence modal formats latency with the shared `formatMs` ("<1 ms" instead of "0 ms" for route-gated cells); the health-card caption reads "of documented (GA/Beta) cells measured supported" (the unit is cells, matching the chip and the drawer); the `ChangeKind` comment names the shipped discriminator (`latency_ms IS NULL AND error_message IS NULL`).
- **`/claude-features` 최종 리뷰 수정** — 고정 피처 열이 가로 스크롤된 셀 배지 위에 그려짐(고정 헤더/본문 셀 `z-20`/`z-10` — 매트릭스를 가로 스크롤하면 피처 라벨이 배지에 덮였다); 변경 배너의 피처 링크가 라이트 테마에서 읽힘(테마 리매핑되는 `amber-200` — `amber-100`은 배너 위 대비 1.04:1); Key Findings 드로어 헤더(×) sticky 고정, Escape로 닫기, 폰에서 2.5rem 탭아웃 여백; 모델 칩 선택 시 드로어 메타 줄이 "<모델> 모델의 N셀"로 표기되고 6절에 그 모델만 나열(선택되지 않은 모델이 "문서상 프로브 셀 없음"으로 나오던 필터 잔상 제거); 증거 모달 지연시간도 공용 `formatMs`(라우트 게이트 셀 "0 ms" → "<1 ms"); 헬스 카드 설명을 "문서상 제공(GA/Beta) 셀 중 실측 supported"로(단위 = 셀, 칩, 드로어와 일치); `ChangeKind` 주석에 실제 판별식(`latency_ms IS NULL AND error_message IS NULL`) 명시.
- **Backend startup no longer full-scans `probe_results` 29 times** — the lifespan migration block runs label rename/delete statements keyed by `model_name` on every boot; with no index on that column each statement was a sequential scan (~130s total on the current data volume — the root cause of the 2026-09-06 v2.23.1 rollout rollback). Added `ix_probe_results_model_name` (created `CONCURRENTLY` via `ensure_performance_indexes`), moved the index build to a daemon thread so `/api/health` opens before multi-minute index builds finish, and set `lock_timeout = 5s` on the migration session so a queued `ALTER TABLE` can no longer stall readers (the `/api/insights/latest` 30s-timeout storms seen during each deploy). The first boot after this change still runs unindexed; every later boot should start in well under a minute.
- **backend 기동이 `probe_results`를 29번 전수 스캔하지 않도록** — lifespan 마이그레이션 블록이 매 기동마다 `model_name` 조건의 라벨 rename/삭제 문장을 실행하는데 이 컬럼에 인덱스가 없어 문장마다 순차 스캔(현 데이터 기준 합계 ~130초, 2026-09-06 v2.23.1 롤아웃 롤백의 근본 원인). `ix_probe_results_model_name` 추가(`ensure_performance_indexes`가 `CONCURRENTLY`로 생성), 인덱스 빌드를 데몬 스레드로 옮겨 수 분짜리 빌드가 끝나기 전에 `/api/health`가 열리도록 했고, 마이그레이션 세션에 `lock_timeout = 5s`를 걸어 대기열의 `ALTER TABLE`이 읽기를 막는 현상(배포마다 반복된 `/api/insights/latest` 30초 타임아웃 연쇄)을 차단. 이 변경 후 첫 기동은 인덱스 없이 돌고, 그 다음 기동부터 1분 미만이 기대값.

## v2.23.1 — 2026-09-05

### Changed
- **Claude API Features UI polish** (`/claude-features`): the Mantle column header now reads "Bedrock Mantle" (was "Bedrock Mantle /anthropic"); a **Note line under the matrix** states that Fable 5.1 cannot be measured on Bedrock Mantle because Mantle serves it only in US GovCloud (us-gov-west-1) — cells stay N/A; cells that are `skipped` for lack of a verification path while the docs say GA/Beta (e.g. 1M context window on Mantle/Bedrock) now render as **"Documented"** (sky badge, explicitly not a measurement) instead of "Skipped"; surface header titles and cell contents are center-aligned; the unsupported verdict wording became "확실한 미지원 응답".
- **Claude API Features UI 다듬기** (`/claude-features`): Mantle 열 제목을 "Bedrock Mantle"로 변경(기존 "Bedrock Mantle /anthropic"); 표 하단 **참조 줄**에 Fable 5.1은 Mantle이 US GovCloud(us-gov-west-1) 리전에서만 서빙해 측정 불가임을 표기(셀은 N/A 유지); 실측 경로가 없어 `skipped`이지만 문서상 GA/Beta인 셀(예: Mantle/Bedrock의 1M 컨텍스트)은 "Skipped" 대신 **"문서상 지원"**(하늘색 배지, 측정값 아님 명시)으로 표기; surface 헤더 제목과 셀 내용을 가운데 정렬; 미지원 판정 문구를 "확실한 미지원 응답"으로 변경.
- **Punctuation**: Korean UI sentences on `/claude-features` use commas instead of middle dots (·) for enumerations; "How to read" items are numbered `1.`–`4.`; the group heading became "파일 및 엔드포인트".
- **문장 부호**: `/claude-features`의 한글 UI 문장에서 나열 구분을 가운데 점(·) 대신 쉼표로 변경; "읽는 법" 항목 번호를 `1.`~`4.` 형식으로; 그룹 제목은 "파일 및 엔드포인트"로.

### Infra (post-tag deploy fix)
- **Backend ECS health-check grace period 60s → 300s** (`FargateServiceConstruct.healthCheckGracePeriod`, backend only). The first v2.23.1 rollout (2026-09-06 00:00 UTC) was rolled back by the deployment circuit breaker: all three new backend tasks spent ~130s in the lifespan migration block (29 full-table-scan `UPDATE`/`DELETE` statements on `probe_results` that run on every boot) before `/api/health` opened, exceeding the default 60s grace. v2.23.0 had booted in 36s only because one statement hit the 30s `statement_timeout` and aborted the block early. During each attempt the queued `ALTER TABLE insights` blocked `/api/insights/latest` (30s timeouts) — the migration block itself is a follow-up item.
- **backend ECS 헬스체크 유예 60s → 300s** (`FargateServiceConstruct.healthCheckGracePeriod`, backend만). 첫 v2.23.1 롤아웃(2026-09-06 00:00 UTC)은 배포 서킷 브레이커로 롤백됨: 새 backend 태스크 3개가 모두 lifespan 마이그레이션 블록(매 기동마다 실행되는 `probe_results` 전수 스캔 `UPDATE`/`DELETE` 29문장)에 ~130초를 쓴 뒤에야 `/api/health`가 열려 기본 유예 60초를 초과. v2.23.0이 36초에 기동한 것은 한 문장이 30초 `statement_timeout`에 걸려 블록이 조기 중단된 우연. 각 시도 중 대기열에 걸린 `ALTER TABLE insights`가 `/api/insights/latest`를 막아 30초 타임아웃 발생 — 마이그레이션 블록 자체는 후속 과제.

### Fixed
- **Data residency (`inference_geo`) read as "Unsupported" on Bedrock** — the official data-residency doc states that on Amazon Bedrock the inference region is determined by the endpoint URL or inference profile, so `inference_geo` is *not applicable* there. The 15 Bedrock cells (Mantle, Messages API, InvokeModel, Converse × the measurable models) were classified `unsupported` (verdict match), which read as "Bedrock has no data residency". They are now pre-decided `not_applicable` (new catalog `_NOT_APPLICABLE_BY_DOC`) with the reason in the evidence modal; the row is labelled "데이터 레지던시 (inference_geo)" and a Note under the matrix explains it. Per run: 643 probes + 137 pre-decided (was 658 + 122). Cells update from the next FeaturesVerify run.
- **데이터 레지던시(`inference_geo`)가 Bedrock에서 "미지원"으로 읽히던 오해 수정** — 공식 데이터 레지던시 문서는 Amazon Bedrock에서는 엔드포인트 URL 또는 추론 프로파일이 추론 리전을 결정하므로 `inference_geo`가 *비적용*이라고 명시. Bedrock 15셀(Mantle, Messages API, InvokeModel, Converse × 측정 가능 모델)이 `unsupported`(match)로 분류되어 "Bedrock은 데이터 레지던시가 안 된다"로 읽혔음. 이제 사전판정 `not_applicable`(카탈로그 `_NOT_APPLICABLE_BY_DOC` 신설)로 분류하고 사유를 증거 모달에 표기, 행 라벨은 "데이터 레지던시 (inference_geo)", 표 하단 참조에 설명 추가. 런당 프로브 643 + 사전판정 137(기존 658 + 122). 셀은 다음 FeaturesVerify 런부터 반영.

## v2.23.0 — 2026-09-05

### Added
- **Claude API Features page (`/claude-features`)** — every feature on platform.claude.com "Build with Claude" (33) plus 4 core Messages checks and the Models API, executed for real against Claude Platform on AWS, Bedrock Mantle `/anthropic` (`us-east-1`) and Bedrock runtime (Messages API + InvokeModel + Converse sub-columns) with Claude Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5 (Mantle excludes Fable 5.1 — US GovCloud only). Each cell carries the documented availability (GA/Beta/—) next to the observed status; a **documentation-drift banner** lists cells documented as available but observed unsupported/broken. Evidence modal shows request snapshot, response signal, error, doc link and verification strength. New package `backend/claude_features/` (catalog 39 × 5 surfaces, raw httpx/boto3 transports, probes, pure engine, runner), tables `feature_runs`/`feature_results`, API `/api/features/{catalog,latest,evidence,trigger}`, CLI `features_runner --once|--smoke`. See ADR-026.
- **Claude API 기능 검증 페이지(`/claude-features`)** — platform.claude.com "Build with Claude"의 피처 33개 + 코어 Messages 4종 + Models API를 Claude Platform on AWS · Bedrock Mantle `/anthropic`(`us-east-1`) · Bedrock runtime(Messages API + InvokeModel + Converse 서브열)에서 Claude Fable 5.1 / Fable 5 / Opus 5 / Sonnet 5로 실제 실행(Mantle은 Fable 5.1 제외 — US GovCloud 전용). 셀마다 문서상 가용성(GA/Beta/—)과 실측 상태를 병기하고, 문서상 제공인데 미지원/오류인 셀은 **문서 드리프트 배너**로 표시. 증거 모달에 요청 스냅샷·응답 신호·오류·문서 링크·검증 강도. 신규 패키지 `backend/claude_features/`(카탈로그 39 × 5 surface, raw httpx/boto3 전송기, 프로브, 순수 엔진, 러너), 테이블 `feature_runs`/`feature_results`, API `/api/features/{catalog,latest,evidence,trigger}`, CLI `features_runner --once|--smoke`. ADR-026 참조.
- **5th surface — Bedrock runtime · Anthropic Messages API (`bedrock_messages`)** — the matrix now also probes `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/messages` (Seoul), the route AWS recommends for new applications and for migrating from the Anthropic APIs. Cross-Region inference profile ids (`global.anthropic.claude-*`), a short-term token from `aws-bedrock-token-generator` as `x-api-key`, `anthropic-version` and `anthropic-beta` headers. The Bedrock column is now three sub-columns (Messages API · InvokeModel · Converse) and one run grows from 624 to 780 cells. Unknown routes on this endpoint answer with a coral `UnknownOperationException` (sometimes under HTTP 200), which the transport normalizes to `404` so they classify as `unsupported` instead of a false success/failure. Refs: https://docs.aws.amazon.com/bedrock/latest/userguide/build.html · https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html · https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html
- **5번째 surface — Bedrock runtime · Anthropic Messages API(`bedrock_messages`)** — `https://bedrock-runtime.{region}.amazonaws.com/anthropic/v1/messages`(서울)를 매트릭스에 추가. AWS가 신규 애플리케이션과 "Migrating from Anthropic APIs"에 권장하는 경로로, 크로스리전 추론 프로파일 id(`global.anthropic.claude-*`) + `aws-bedrock-token-generator` 단기 토큰(`x-api-key`) + `anthropic-version`/`anthropic-beta` 헤더를 쓴다. Bedrock 열은 3개 서브열(Messages API · InvokeModel · Converse)이 되고 1런은 624셀 → 780셀로 늘어난다. 이 엔드포인트는 모르는 라우트에 coral `UnknownOperationException`(HTTP 200 본문으로 오는 경우도 있음)을 돌려주므로 전송기가 `404`로 정규화해 false-supported·false-broken 없이 `unsupported`로 판정한다. 참조: https://docs.aws.amazon.com/bedrock/latest/userguide/build.html · https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html · https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html

### Changed
- **Shared env `MANTLE_ANTHROPIC_REGION` now defaults to `us-east-1`** for the `FeaturesVerify`/`ParityRun`/`GptBench`/`AutoProber`/`Insights` scheduler tasks and the backend service (CDK-injected; was `ap-northeast-1`) — user decision on 2026-09-05, because `ap-northeast-1` serves only Opus 4.8 in this account while `us-east-1` serves the 4 Claude API Features representative models (`sonnet-5` verified 200). Because Parity Run's `messages_mantle` surface reads the same env, it also starts probing `us-east-1` from this release — expect more `Supported` cells there. The in-code fallback when the env is absent (`backend/parity/runner.py`) is unchanged at `ap-northeast-1`; CDK now injects the value explicitly everywhere.
- **공용 env `MANTLE_ANTHROPIC_REGION` 기본값이 `us-east-1`로 전환** — `FeaturesVerify`/`ParityRun`/`GptBench`/`AutoProber`/`Insights` 스케줄 태스크와 backend 서비스 전체(CDK 주입, 기존 `ap-northeast-1`) — 2026-09-05 사용자 결정. 이 계정에서 `ap-northeast-1`은 Opus 4.8만 서빙하고, Claude API Features 대표 4모델은 `us-east-1`에서 서빙(`sonnet-5` 200 확인)되기 때문. 패리티 런 `messages_mantle` surface도 같은 env를 읽으므로 이번 릴리스부터 `us-east-1`을 프로빙 — Supported 셀 증가 예상. env 미주입 시 코드 폴백(`backend/parity/runner.py`)은 여전히 `ap-northeast-1`이며, CDK가 모든 곳에 값을 명시적으로 주입한다.

### Infra
- New EventBridge schedule `FeaturesVerifySchedule` (`rate(24 hours)`) → Fargate `FeaturesVerifyTaskDef` (`python -m features_runner --once`, log group `/ecs/features`, autoprober task role reused). Env `MANTLE_ANTHROPIC_REGION=us-east-1` and `FEATURES_MCP_SERVER_URL` injected into all scheduler tasks and the backend service. One run = 658 probes + 122 pre-decided rows = 780 cells (39 features × 5 surfaces × 4 models); with 2-call caching probes and negative controls, ≈800 API calls. Daily cadence and the 5-surface cost estimate (≈$5–7 per run, ≈$150–210/month) approved by the user on 2026-09-05 (the earlier 4-surface estimate was $4–6). **New IAM**: `bedrock:CallWithBearerToken` added to the autoprober task role and the backend task role (alongside the pre-existing `bedrock-mantle:CallWithBearerToken`), Resource `*` — required for `BedrockMessagesTransport`'s `aws-bedrock-token-generator` short-term bearer sent as `x-api-key` to the bedrock-runtime Anthropic Messages route (`bedrock_messages` surface); AWS separates this Bedrock-endpoint action from the Mantle one, and `simulate-principal-policy` confirmed an implicit deny without it.
- 신규 EventBridge 스케줄 `FeaturesVerifySchedule`(`rate(24 hours)`) → Fargate `FeaturesVerifyTaskDef`(`python -m features_runner --once`, 로그 그룹 `/ecs/features`, autoprober 태스크 롤 재사용). env `MANTLE_ANTHROPIC_REGION=us-east-1`·`FEATURES_MCP_SERVER_URL`을 스케줄 태스크 전체와 backend 서비스에 주입. 1런 = 프로브 658 + 사전판정 122 = 780셀(39피처 × 5 surface × 4모델), 캐싱 프로브·부정 제어 포함 ≈800 API 호출. 일 1회 주기와 5 surface 기준 비용 추정(런당 ≈$5~7, 월 ≈$150~210)은 2026-09-05 사용자 승인 (4 surface 기준 초기 추정은 $4~6). **신규 IAM**: autoprober 태스크 롤과 backend 태스크 롤에 `bedrock:CallWithBearerToken`(Resource `*`) 추가 — 기존 `bedrock-mantle:CallWithBearerToken`과 별개로, `BedrockMessagesTransport`가 `aws-bedrock-token-generator` 단기 bearer를 `x-api-key`로 bedrock-runtime Anthropic Messages 라우트(`bedrock_messages` surface)에 보내는 데 필수. AWS는 이 Bedrock 엔드포인트 액션을 Mantle 액션과 별도로 구분하며, `simulate-principal-policy`로 미추가 시 implicit deny를 확인했다.

### Fixed
- `cdk/test/scheduler-stack.test.ts` was stale since v2.18.0 (expected 3 schedules/task definitions, actual 4) and failed `make verify`; counts updated to 5 with the new task.
- v2.18.0 이후 낡아 `make verify`를 깨뜨리던 `cdk/test/scheduler-stack.test.ts`(기대 3, 실제 4) 카운트를 신규 태스크 포함 5로 갱신.

### Notes
- Live smoke (2026-09-05, sonnet-5 full sweep, run against `ap-northeast-1` before the region switch above): Bedrock Mantle `/anthropic` in `ap-northeast-1` serves only Opus 4.8 in this account — `anthropic.claude-{fable-5,opus-5,sonnet-5}` return `not_found_error` (`us-east-1` serves sonnet-5) — this is the finding that drove the `MANTLE_ANTHROPIC_REGION` default switch to `us-east-1`. Bedrock InvokeModel and Converse reject `output_config.format`/`strict: true` with "Extra inputs are not permitted" for the Claude 5 generation, and Bedrock `CountTokens` does not support these CRIS-only (`global.*`) models — catalog `documented` expectations for `token_counting`/`structured_outputs`/`strict_tool_use` updated to match. `browser_toolset_20260801` works on CP on AWS and Bedrock InvokeModel although the docs list it as unavailable (recorded as `undocumented`, catalog notes updated).
- 라이브 스모크(2026-09-05, sonnet-5 전체 스윕, 위 리전 전환 전 `ap-northeast-1` 기준으로 실행): Bedrock Mantle `/anthropic`의 `ap-northeast-1`은 이 계정에서 Opus 4.8만 서빙 — `anthropic.claude-{fable-5,opus-5,sonnet-5}`는 `not_found_error`(`us-east-1`은 sonnet-5 서빙) — 이 발견이 `MANTLE_ANTHROPIC_REGION` 기본값을 `us-east-1`로 전환시킨 근거다. Bedrock InvokeModel·Converse는 Claude 5 세대에서 `output_config.format`/`strict: true`를 "Extra inputs are not permitted"로 거부하고, Bedrock `CountTokens`는 이 CRIS 전용(`global.*`) 모델들을 미지원 — 카탈로그 `documented` 기대치(`token_counting`/`structured_outputs`/`strict_tool_use`)를 실측에 맞춰 갱신. `browser_toolset_20260801`은 문서상 미제공이지만 CP on AWS·Bedrock InvokeModel에서 동작(`undocumented`로 기록, 카탈로그 notes 갱신).
- **Full sweep — 4 models × 5 surfaces, 780 cells (39 features × 5 surfaces × 4 models), 2026-09-05**: **broken 0 / inconclusive 0** after two probe fixes (the first full run recorded broken 39). Totals: supported 419 · unsupported 221 · skipped 15 · not_applicable 125; verdicts match 590 · drift 25 · undocumented 14 · none 151. `token_counting`, `models_api`, `files_api` and `batch_processing` are cleanly absent on `bedrock_messages`: the first three answer with a coral `UnknownOperationException`, and `/v1/messages/batches` falls through to the SigV4 front door (403 "Authorization header is missing") because the two auth schemes are mutually exclusive. `tool_search` works there even though AWS documents it for InvokeModel only (expectation left `unknown`). Per-surface × model breakdown and triage in ADR-026 and `task-12-report.md`.
- **전체 스윕 — 4모델 × 5 surface, 780셀(39피처 × 5 surface × 4모델), 2026-09-05**: 프로브 결함 2건 수정 후 **broken 0 / inconclusive 0**(최초 전체 실행은 broken 39). 합계: supported 419 · unsupported 221 · skipped 15 · not_applicable 125; 판정 match 590 · drift 25 · undocumented 14 · none 151. `bedrock_messages`에서 `token_counting`·`models_api`·`files_api`·`batch_processing`은 깨끗하게 부재로 확인 — 앞 3개는 coral `UnknownOperationException`, `/v1/messages/batches`는 SigV4 프론트도어로 떨어져 403 "Authorization header is missing"(두 인증 스킴이 배타적). `tool_search`는 AWS 문서가 InvokeModel만 명시하는데도 이 경로에서 동작(기대치 `unknown` 유지). surface×모델별 세부와 트리아지는 ADR-026·`task-12-report.md` 참조.
- **Drift 25 breaks into two clusters, not 25 isolated feature gaps**: 23 cells are Mantle (`us-east-1`) Fable 5 rejecting every probed feature with `data retention mode 'default' is not available for this model` (one account-level Covered-Model data-retention opt-in, not a probe defect — resolving it is an account/org decision, catalog expectations were deliberately left unchanged), plus 2 cells where Mantle rejects the `fallback_credit` beta header (a real surface gap). All 14 `undocumented` rows are `browser_use` (`browser_toolset_20260801`) working on cp (4 models) / mantle (opus-5, sonnet-5) / bedrock_messages (4 models) / bedrock_invoke (4 models) though undocumented; Converse has no field to express it. The sweep also tightened the caching verdict: all three caching probes now require the **second call's `cache_read_input_tokens > 0`** (creation/`ephemeral_1h` fields are supporting evidence only, no longer a passing condition) — the old creation-only OR branch had let 5 rows pass without proving reuse (4 safety refusals + 1 normal cache miss on `bedrock_messages`/Fable 5).
- **드리프트 25건은 개별 피처 갭이 아니라 클러스터 2개로 수렴**: 23셀은 Mantle(`us-east-1`) Fable 5가 프로브된 모든 피처를 `data retention mode 'default' is not available for this model`로 거부(계정 단위 Covered Model 데이터 보존 opt-in 미적용 하나의 원인 — 프로브 결함이 아니라 계정/조직 결정 항목, 카탈로그 기대치는 의도적으로 유지), 나머지 2셀은 Mantle이 `fallback_credit` beta 헤더를 거부(실제 surface 갭). `undocumented` 14건은 전부 `browser_use`(`browser_toolset_20260801`)가 cp(4모델)·mantle(opus-5, sonnet-5)·bedrock_messages(4모델)·bedrock_invoke(4모델)에서 문서 없이 동작(Converse는 표현 필드 없음). 이번 스윕에서 캐싱 판정식도 강화 — 캐시 3프로브 전부 **2차 호출 `cache_read_input_tokens > 0`**을 요구(생성/`ephemeral_1h` 필드는 이제 보조 증거일 뿐, 통과 조건 아님) — 종전 창작-only OR 분기는 재사용을 증명하지 않고도 5행(안전 거부 4건 + `bedrock_messages`/Fable 5 정상 캐시 미스 1건)을 통과시켰다.

## v2.22.1 — 2026-09-01

### Fixed
- **History view showed "Anthropic Claude Fable 5 (US)" twice and no Fable 5.1 CP entry.** Root cause: the CP on AWS workspace began serving `claude-fable-5-1` at 17:52 UTC on 2026-09-01, and the pre-v2.22.0 substring matcher (`"fable-5" in id`) registered that id under the Fable 5 label — 53 `probe_results` rows for `model_id=anthropic:claude-fable-5-1` carry the wrong `model_name`. `/api/results/stats` labelled each model_id group by its oldest row, so the 5.1 group surfaced as a duplicate Fable 5. Fixes: (1) stats now takes the label from the live catalog (`AVAILABLE_MODELS`, falling back to the newest row); (2) new `label_repair.py` runs at backend startup in its own transaction and rewrites stored `model_name` to the catalog label for any catalogued model_id (`probe_results` + `probe_results_hourly`), so trend/analysis/cost views heal too. The old `_label_renames` block is currently dead in production — its transaction rolls back on the `ALTER TABLE probe_runs` statement timeout at every startup since at least 2026-08-19 (pre-existing, logged as "Migration block failed").
- **이력 조회에 "Anthropic Claude Fable 5 (US)"가 두 번 보이고 Fable 5.1 CP 항목이 없던 문제.** 원인: CP on AWS 워크스페이스가 2026-09-01 17:52 UTC부터 `claude-fable-5-1`을 서빙했고, v2.22.0 이전 substring 매칭(`"fable-5" in id`)이 이 id를 Fable 5 라벨로 등록 → `model_id=anthropic:claude-fable-5-1` 행 53건의 `model_name`이 오기재. `/api/results/stats`가 model_id 그룹의 가장 오래된 행 라벨을 쓰므로 5.1 그룹이 Fable 5 중복으로 표시됨. 수정: (1) 통계 라벨을 현행 카탈로그(`AVAILABLE_MODELS`, 없으면 최신 행)에서 취득, (2) 신규 `label_repair.py`가 backend 기동 시 별도 트랜잭션으로 카탈로그 model_id의 저장 `model_name`을 카탈로그 라벨로 정정(`probe_results` + `probe_results_hourly`) → 추이/분석/비용 화면도 함께 복구. 기존 `_label_renames` 블록은 같은 트랜잭션의 `ALTER TABLE probe_runs` statement timeout으로 최소 2026-08-19부터 매 기동 롤백되는 상태(기존 문제, "Migration block failed" 로그).
- `/api/results/stats` called without `start_time`/`run_id` now defaults to the last 24h instead of loading the whole `probe_results` table into ORM objects — an unbounded call OOM-killed the backend container (1024 MB, exit 137, ~2 min outage) on 2026-09-01.
- `/api/results/stats`를 `start_time`/`run_id` 없이 호출하면 전체 `probe_results`를 ORM으로 적재하던 것을 최근 24h 기본값으로 한정 — 2026-09-01 기간 미지정 호출이 backend 컨테이너 OOM(1024MB, exit 137, 약 2분 중단)을 유발.

## v2.22.0 — 2026-09-01

### Added
- **Claude Fable 5.1** joins the monitored catalog in all 3 Claude channels (active catalog 40 → 43): Bedrock Global (`global.anthropic.claude-fable-5-1`, Seoul), Bedrock US (`us.anthropic.claude-fable-5-1`, us-east-1) and Anthropic CP on AWS (pre-registered `fable-5-1` discovery target — auto-registers as soon as the workspace serves it). Both Bedrock inference profiles verified ACTIVE and live-probed (`pong` / `end_turn`) before the change. Same Covered-Model constraints and price tier as Fable 5 ($10 / $50 per MTok). Frontend: `FAMILY_ORDER` (Fable 5.1 on top), `MODEL_COLORS` (3 sky-blue entries), Comparison Lab names, OptimizePrompt targets.
- **Claude Fable 5.1** 을 Claude 3채널 전부에 모니터링 대상으로 편입 (활성 카탈로그 40 → 43): Bedrock Global(`global.anthropic.claude-fable-5-1`, Seoul), Bedrock US(`us.anthropic.claude-fable-5-1`, us-east-1), Anthropic CP on AWS(`fable-5-1` 발견 타깃 선등록 — 워크스페이스에서 서빙되는 즉시 자동 등록). 두 Bedrock 프로파일은 변경 전 ACTIVE 확인 + 라이브 프로브(`pong` / `end_turn`) 검증. Covered Model 제약·단가 티어는 Fable 5와 동일($10 / $50 per MTok). 프론트: `FAMILY_ORDER` 최상단, `MODEL_COLORS` 3개(sky 계열), Comparison Lab 이름, OptimizePrompt 대상.

### Changed
- Parity Run `tool_use` probe now uses `tool_choice: auto` + prompt instruction on models that reject forced tool choice (`parity/catalog.py` `supports_forced_tool_choice()` — Fable 5.1 returns 400 on `type: tool`/`any`). Other models keep the forced-tool probe unchanged.
- 패리티 런 `tool_use` 프로브가 forced tool_choice를 거부하는 모델에서는 `tool_choice: auto` + 프롬프트 지시로 동작 (`parity/catalog.py` `supports_forced_tool_choice()` — Fable 5.1은 `type: tool`/`any`에 400). 그 외 모델은 기존 강제 도구 프로브 그대로.

### Fixed
- CP on AWS model discovery (`_discover_anthropic_models`) could mislabel a longer model id with a shorter target's label when substrings overlap (`fable-5` ⊂ `fable-5-1`), depending on `/v1/models` ordering. New `_match_anthropic_model()` excludes ids that contain a longer registered target.
- CP on AWS 모델 자동 발견(`_discover_anthropic_models`)이 substring 접두 충돌(`fable-5` ⊂ `fable-5-1`) 시 `/v1/models` 순서에 따라 긴 id에 짧은 타깃 라벨을 붙일 수 있던 문제 수정. 신규 `_match_anthropic_model()`이 더 긴 등록 타깃을 포함하는 id를 후보에서 제외.

## v2.21.0 — 2026-08-18

### Added
- **iPhone/iPad installable app (PWA)** — Safari Share → "Add to Home Screen" now installs the dashboard as a full-screen standalone app. Web app manifest (`src/app/manifest.ts` → `/manifest.webmanifest`) + generated app icons (emerald pulse glyph on dark gradient; regular + maskable variants, `app/icon.png`·`app/apple-icon.png` conventions) + iOS meta tags (`appleWebApp`, black-translucent status bar) + `viewport-fit=cover` with safe-area padding for the notch/Dynamic Island/home indicator (standalone-only via `display-mode: standalone` media query). Middleware `no-store` matcher excludes the new static PWA assets.
- **iPhone/iPad 설치형 앱 (PWA)** — Safari 공유 → "홈 화면에 추가"로 대시보드를 전체화면 standalone 앱으로 설치. Web app manifest(`src/app/manifest.ts` → `/manifest.webmanifest`) + 생성 앱 아이콘(다크 그라데이션 + 에메랄드 펄스, 일반/maskable 변형, `app/icon.png`·`apple-icon.png` 컨벤션) + iOS 메타태그(`appleWebApp`, 반투명 상태바) + `viewport-fit=cover`와 노치/Dynamic Island/홈 인디케이터 safe-area 패딩(설치형에서만 적용되는 `display-mode: standalone` 미디어 쿼리). middleware `no-store` matcher에서 신규 PWA 정적 자산 제외.

### Fixed
- Synced runtime-visible version strings during release finalization: FastAPI OpenAPI version was stuck at 2.0.0 (now 2.21.0), `frontend/package.json` at 1.0.0, root CLAUDE.md overview at v2.19.2. Canonical locations are now listed in CLAUDE.md "Version strings".
- 릴리스 마무리 과정에서 런타임 노출 버전 문자열 동기화: FastAPI OpenAPI 버전이 2.0.0으로 고착(→ 2.21.0), `frontend/package.json` 1.0.0, 루트 CLAUDE.md 개요 v2.19.2 교정. 정식 위치 목록을 CLAUDE.md "Version strings" 절로 신설.

## v2.20.1 — 2026-08-18

### Added
- GPT on AWS bench (`/gpt-on-aws`) now includes the **GPT 5.6 Terra Global CRIS** channel (8 → 9 channels, user-approved). Same key/label convention as the prober (`openai:global:global.openai.gpt-5.6-terra`, `(Global)`); routed via the Seoul bedrock-runtime OpenAI-compat endpoint (`OPENAI_GLOBAL_BASE_URL`). Panel gets a violet region color + updated legend/description. Estimated cost +~$20/day on top of the existing ~$150/day. GPT 5.4/5.5 have no global profile; Sol/Luna remain out of bench scope.
- GPT on AWS 벤치(`/gpt-on-aws`)에 **GPT 5.6 Terra Global CRIS** 채널 편입 (8 → 9채널, 사용자 승인). prober와 동일한 키/라벨 규약(`openai:global:global.openai.gpt-5.6-terra`, `(Global)`), Seoul bedrock-runtime OpenAI-compat 엔드포인트(`OPENAI_GLOBAL_BASE_URL`) 경유. 패널에 보라색 리전 색상 + 범례/설명 갱신. 비용 추정 기존 ~$150/일 대비 +~$20/일. GPT 5.4/5.5는 global 프로파일 미지원, Sol/Luna는 벤치 대상 아님(기존 결정 유지).

## v2.20.0 — 2026-08-18

### Added
- OpenAI GPT-5.6 (Sol/Terra/Luna) Bedrock **Global cross-region inference** channels — 3 new monitored channels (active catalog 37 → 40), announced by AWS on 2026-08-17 (5.6 generation only; 5.4/5.5 unsupported). Key scheme `openai:global:global.openai.gpt-5.6-*` (pseudo-region `global`, profile id derived by prepending `global.` — no new model-id env), label `OpenAI GPT 5.6 * (Global)`. Called via the Seoul bedrock-runtime OpenAI-compat endpoint (`OPENAI_GLOBAL_BASE_URL`, reuses the existing Mantle bearer key) because the bedrock-mantle host does not support global profiles. Pricing is channel-split with `-global` suffix keys since Global CRIS is cheaper than in-region (Sol $5/$30, Terra $2/$12, Luna $0.20/$1.20 per MTok). See ADR-025.
- OpenAI GPT-5.6 (Sol/Terra/Luna) Bedrock **Global cross-region inference** 채널 3개 추가 (활성 카탈로그 37 → 40) — 2026-08-17 AWS 발표(5.6 세대만, 5.4/5.5 미지원). 키 스킴 `openai:global:global.openai.gpt-5.6-*`(pseudo-region `global`, 프로파일 id는 `global.` 접두사 파생 — 신규 model-id env 없음), 라벨 `OpenAI GPT 5.6 * (Global)`. global 프로파일은 bedrock-mantle 호스트 미지원이라 Seoul bedrock-runtime OpenAI-compat 엔드포인트(`OPENAI_GLOBAL_BASE_URL`, 기존 Mantle bearer 키 재사용)로 호출. Global CRIS 단가가 in-region보다 저렴해 `-global` suffix 키로 가격 분리 (Sol $5/$30, Terra $2/$12, Luna $0.20/$1.20 per MTok). ADR-025 참조.

### Fixed
- Pricing table: GPT-5.6 in-region rates corrected to reflect the 2026-07-30 AWS price reduction (Luna -80%, Terra -20%; Sol unchanged at the official $5.50/$33 — the previous "1P parity $5/$30" entry was stale). Cost dashboards recalculate retroactively at the corrected rates (same policy as the v2.19.0 Opus correction).
- 가격 테이블: GPT-5.6 in-region 단가를 2026-07-30 AWS 인하 반영으로 교정 (Luna -80%, Terra -20%; Sol은 공식 $5.50/$33 — 기존 "1P parity $5/$30" 기재는 낡은 값). 비용 대시보드는 교정 단가로 소급 재계산 (v2.19.0 Opus 교정과 동일 정책).

### Infra
- EventBridge Scheduler invoke role: added the missing `gptbench` task-def family `:*` wildcard to `ecs:RunTask` (ADR-011 hardening — prevents silent schedule failure after a manual task-def revision bump).
- EventBridge Scheduler invoke role의 `ecs:RunTask`에 누락돼 있던 `gptbench` task-def family `:*` wildcard 추가 (ADR-011 예방 — 수동 revision bump 후 스케줄 silent fail 방지).

## v2.19.2 — 2026-08-01

### Changed
- AI insights job (Haiku 4.5) now excludes hidden `"(1P)"` channels from its stats collection (`insights_runner.collect_stats_for_window` / `run_once`) — completes the v2.19.1 exposure removal for AI-generated analysis. Chatbot tools were already filtered in v2.19.1.
- AI 인사이트 잡(Haiku 4.5)의 통계 수집(`insights_runner`)에서도 숨김 `"(1P)"` 채널을 제외 — v2.19.1 비노출 조치를 AI 생성 분석까지 확장. 챗봇 tools는 v2.19.1에서 이미 필터 적용됨.

## v2.19.1 — 2026-07-31

### Changed
- OpenAI 1P direct (Path 5, 5 channels) excluded from comparison/monitoring exposure per user decision — capability preserved, not deleted. Three-layer switch: CDK `ENABLE_OPENAI_1P=false` (env/secret not injected → prober silently skips registration), backend `visibility.py` read-layer filter hiding `"(1P)"` labels from all query APIs (results, auto-probe latest/trend/anomalies, cost, reliability, efficiency, analysis, chatbot tools) while DB rows are retained, frontend `EXCLUDED_FAMILIES` hard-filter. Active catalog 42 → 37. Background: the stored 1P key was revoked (401) as of 2026-07-31. Re-enable path: CDK flag true + valid key in SSM + `HIDDEN_MODEL_PATTERNS=""` + remove frontend filter entry.
- OpenAI 1P direct (Path 5, 5개 채널)를 사용자 결정으로 비교·모니터링 노출에서 제외 — 기능(코드)은 보존. 3중 스위치: CDK `ENABLE_OPENAI_1P=false`(env 미주입 → prober가 등록 조용히 skip), backend `visibility.py` 조회 계층 필터(`"(1P)"` 라벨을 모든 조회 API에서 숨김, DB 행은 보존), frontend `EXCLUDED_FAMILIES` 하드필터. 활성 카탈로그 42 → 37. 배경: 저장된 1P 키가 2026-07-31 기준 폐기(401) 상태. 재노출: CDK 플래그 true + 유효 키 SSM 저장 + `HIDDEN_MODEL_PATTERNS=""` + 프런트 필터 항목 제거.

## v2.19.0 — 2026-07-24

### Fixed
- Pricing table: Claude Opus 4.8 / 4.7 / 4.6 corrected from \$15/\$75 to the official \$5/\$25 per MTok (\$15/\$75 is Opus 4.1's rate). Cost dashboards recalculate retroactively at the corrected rate (user decision: display consistency over historical accuracy).
- 가격표: Claude Opus 4.8/4.7/4.6을 \$15/\$75 → 공식 \$5/\$25 per MTok로 교정 (\$15/\$75는 Opus 4.1 단가). 비용 대시보드는 교정 단가로 소급 재계산 (사용자 결정: 표시 일관성 우선).

### Added
- Claude Opus 5 (launched 2026-07-24) across all menus — Bedrock Global/US inference profiles (`global./us.anthropic.claude-opus-5`, both verified live), catalog 39 → 41. CP on AWS target pre-registered (auto-discovers when the org recovers → 42). Reasoning model (temperature rejected). Pricing $5/$25 per MTok (official).
- Claude Opus 5 전 메뉴 추가 (2026-07-24 출시) — Bedrock Global/US 추론 프로파일 2채널 (실측 검증), 카탈로그 39 → 41. CP on AWS 타깃 선등록 (조직 복구 시 자동 발견 → 42). reasoning 모델 (temperature 거부). 가격 $5/$25 per MTok (공식).

## v2.18.1 — 2026-07-22

### Fixed
- GPT on AWS: /latest now returns the most recent **completed** cycle (channel-wise commits exposed a running cycle's partial 4 cards for ~7 of every 15 minutes); /trend excludes the in-progress cycle's partial endpoint.
- GPT on AWS: /latest가 최신 **완료** 사이클을 반환 (채널 단위 커밋 탓에 실행 중 사이클의 부분 카드 4개가 노출되던 문제), /trend도 진행 중 사이클 끝점 제외.

### Added
- GPT on AWS: score cards are now clickable channel filters for the trend charts (empty selection = all — same rule as the dashboard), with an "All" reset and N/8 counter.
- GPT on AWS: 스코어 카드 클릭으로 그래프 채널 선택(빈 선택 = 전체 — 대시보드와 동일 규칙), "전체" 초기화 버튼과 N/8 카운터 추가.

## v2.18.0 — 2026-07-22

### Added
- **GPT on AWS** page (`/gpt-on-aws`): precision latency bench for Bedrock Mantle (3P) GPT channels — GPT 5.4 ×3 US regions + GPT 5.5 ×2 + GPT 5.6 Terra ×3 (8 channels). Every 15 minutes a scheduled Fargate task runs 10 sequential calls per channel with the fixed ~55.8k-token cached prompt (docs/benchmarks methodology): TTFB (first stream event) / TTFT (first text delta) / GAP (≈ thinking). Page shows per-channel score cards (median TTFB/TTFT/GAP, p95, cache hit rate, success) and per-cycle median trend charts with time-range control.
- **GPT on AWS** 페이지(`/gpt-on-aws`): Bedrock Mantle(3P) GPT 채널 정밀 레이턴시 벤치 — GPT 5.4 ×3리전 + 5.5 ×2 + 5.6 Terra ×3 (8채널). 15분마다 스케줄 태스크가 채널당 10회 순차 호출(~55.8k 토큰 고정 캐시 프롬프트, docs/benchmarks 방법론): TTFB/TTFT/GAP(≈thinking). 채널별 스코어 카드(median·p95·캐시 히트율·성공률)와 사이클별 median 시계열 그래프 + 기간 조절 제공.

### Infra
- New table `gpt_bench_results`, router `/api/gptbench/{latest,trend}` (public read), EventBridge schedule `rate(15 minutes)` → GptBench Fargate task (backend image, `python -m gptbench_runner --once`).
- 신규 테이블 `gpt_bench_results`, 라우터 `/api/gptbench/{latest,trend}`(공개 조회), EventBridge `rate(15 minutes)` → GptBench Fargate 태스크 (backend 이미지 공용).

## v2.17.1 — 2026-07-14

### Added
- Historical Stats panel: per-model filter chips (empty selection = all, same rule as the dashboard card filter). Selection persists across time-range changes.
- 이력 통계 패널: 모델별 선택 필터 칩 추가 (빈 선택 = 전체 — 대시보드 카드 필터와 동일 규칙). 조회 기간을 바꿔도 선택 유지.

## v2.17.0 — 2026-07-14

### Added
- OpenAI GPT-5.6 generation (Sol / Terra / Luna) across all menus — 11 new channels (Bedrock Mantle 8: Sol us-east-1/2, Terra·Luna us-east-1/2/west-2 + 1P direct 3), catalog 28 → 39. Sol is not offered in us-west-2. Responses-API-only like GPT-5.4/5.5. Bedrock in-region pricing at parity with OpenAI 1P (Sol $5/$30, Terra $2.5/$15, Luna $1/$6 per MTok — no 10% markup unlike 5.4/5.5).
- OpenAI GPT-5.6 세대(Sol/Terra/Luna)를 전 메뉴에 추가 — 신규 11채널 (Bedrock Mantle 8: Sol은 us-east-1/2, Terra·Luna는 us-east-1/2/west-2 + 1P direct 3), 카탈로그 28 → 39. Sol은 us-west-2 미제공. GPT-5.4/5.5와 동일하게 Responses API 전용. Bedrock in-region 가격은 OpenAI 1P와 동일(parity — Sol $5/$30, Terra $2.5/$15, Luna $1/$6 per MTok, 5.4/5.5식 10% 마크업 없음).

### Infra
- New env vars injected by CDK (AppServices + Scheduler): `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`, `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`.
- CDK(AppServices + Scheduler)가 주입하는 신규 env: `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`, `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`.

## v2.16.5 — 2026-07-12

### Added
- Real User Monitoring via aws-rum-pipeline: `RumProvider` loads the self-hosted RUM SDK and stamps every event with `appName: llm-monitor` (page views, SPA route dwell time, Core Web Vitals, JS errors). Enabled only when `NEXT_PUBLIC_RUM_ENDPOINT`/`NEXT_PUBLIC_RUM_API_KEY` are provided at build time (Docker build args).
- aws-rum-pipeline 연동 RUM(Real User Monitoring): `RumProvider`가 자체 호스팅 SDK를 로드해 모든 이벤트에 `appName: llm-monitor`를 스탬핑 (페이지뷰·SPA 체류시간·Core Web Vitals·JS 에러). 빌드 타임 `NEXT_PUBLIC_RUM_*` 주입 시에만 활성화 (Docker build args).

## v2.16.4 — 2026-07-12

### Changed
- Dashboard model cards: input/output tokens and the probe timestamp now share one line (was two rows).
- 대시보드 모델 카드: 입력/출력 토큰과 프로빙 시간을 한 줄로 병합 (기존 2줄).

## v2.16.3 — 2026-07-12

### Changed
- Parity provider cards: replace the donut chart with a horizontal segmented bar (health % + status distribution) — visually consistent with the feature summary rows.
- 패리티 provider 카드: 도넛 그래프를 가로 세그먼트 막대(헬스 % + 상태 분포)로 교체 — 피처 요약행 막대와 시각 언어 통일.

## v2.16.2 — 2026-07-12

### Fixed
- **Model Explorer i18n**: API descriptions, code comments, link labels, and the copy button now follow the selected language (they were Korean-only under EN).
- **Parity page i18n**: the feature catalog now serves `label_en`/`desc_en` so feature names, tooltips, and the changes banner localize; evidence-modal verdict sentences are bilingual.
- **Terminology**: "깨끗한 미지원" → "명시적 미지원" (UI·주석·문서) — 더 자연스러운 한국어 표현.
- **모델 탐색 i18n**: API 설명·코드 주석·링크 라벨·복사 버튼이 선택 언어를 따르도록 수정 (EN에서도 한글이 출력되던 문제).
- **패리티 페이지 i18n**: 카탈로그에 `label_en`/`desc_en` 추가 — 피처명·툴팁·변경 배너 현지화, 증거 모달 판정 문장 이중언어화.

## v2.16.1 — 2026-07-12

### Changed
- Move login-required menus (Manual Probe, Prompts) to the end of the top navigation — public pages (Dashboard, Models, Parity, Cost, Reliability, Efficiency, Analysis) come first.
- 로그인이 필요한 메뉴(수동 프로브·프롬프트)를 상단 내비 맨 뒤로 이동 — 공개 페이지(대시보드·모델 탐색·패리티 런·비용·신뢰성·효율성·분석)가 앞에 오도록 정렬.

## v2.16.0 — 2026-07-12

### Added
- **Mobile responsive layout**: a shared `AppHeader` component replaces the header duplicated across all 9 pages — desktop keeps the current horizontal nav (lg+), narrow screens get a hamburger menu with a vertical dropdown (page-specific actions included). The manual-probe sidebar stacks vertically on mobile and panel paddings tighten on small screens. Same URLs — layout adapts purely by viewport width.
- **모바일 반응형 레이아웃**: 9개 페이지에 중복돼 있던 헤더를 공용 `AppHeader`로 통합 — 데스크톱(lg+)은 기존 가로 내비 그대로, 좁은 화면은 햄버거(☰) 세로 드롭다운(페이지별 버튼 포함). 수동 프로브 사이드바는 모바일에서 세로 스택, 패널 패딩은 소형 화면에서 축소. URL 변경 없음 — 뷰포트 폭만으로 레이아웃 전환.

## v2.15.1 — 2026-07-12

### Fixed
- Classify "not yet supported" (URL sources on newer Claude models) as cleanly unsupported — the last 12 false-Broken cells from run #10.
- "not yet supported"(신형 Claude 모델의 URL 소스 거부 문구)를 깨끗한 미지원으로 분류 — run #10의 잔여 false-Broken 12셀 해소.

## v2.15.0 — 2026-07-12

### Added
- **Full feature catalog (12 → 19)**: reasoning_effort (effort param acceptance — Claude output_config / GPT reasoning effort), json_schema (strict schema output with key validation), url_sources (remote PDF document source), memory_tool / code_execution (beta server-tool acceptance), files_api (list round-trip), models_api (model retrieve round-trip). Admin/Usage APIs and MCP connector are intentionally excluded (cannot be probed honestly without an admin key / a live MCP server).
- **Collapsible feature matrix**: each feature renders as a summary row (bold name, status distribution bar, supported·unsupported·broken counts) that expands to per-model rows on click; features containing Broken cells auto-expand, search/status filters expand everything, plus expand-all / collapse-all buttons.
- **피처 카탈로그 완성 (12 → 19)**: reasoning_effort(effort 파라미터 수락 — Claude output_config / GPT reasoning effort), json_schema(strict 스키마 출력+키 검증), url_sources(원격 PDF 문서 소스), memory_tool/code_execution(beta 서버 도구 수락), files_api(목록 왕복), models_api(모델 조회 왕복). Admin/Usage API·MCP connector는 정직한 판정 불가(관리자 키/실 MCP 서버 필요)로 의도적 제외.
- **접이식 피처 매트릭스**: 피처별 요약행(굵은 이름 + 상태 분포 바 + supported·unsupported·broken 카운트) 클릭 시 모델 행 펼침. Broken 포함 피처는 자동 펼침, 검색/상태 필터 시 전체 펼침, 모두 펼치기/접기 버튼 제공.

## v2.14.2 — 2026-07-11

### Fixed
- **Final feature-expansion follow-ups (run #8 evidence)**: bare-404 responses (Mantle has no batches endpoint) and explicit tool-schema rejections ("does not match any of the expected tags") now classify as cleanly unsupported; adaptive_thinking probe budget raised to 8000 tokens matching the reference request (at 2048 the model accepted but skipped thinking).
- **피처 확장 최종 후속 (run #8 증거)**: 본문 없는 404(Mantle batches 엔드포인트 미제공)와 도구 스키마 명시 거부("does not match any of the expected tags")를 깨끗한 미지원으로 분류. adaptive_thinking 예산을 참조 요청과 동일한 8000 토큰으로 상향(2048에서는 수락 후 thinking 생략).

## v2.14.1 — 2026-07-11

### Fixed
- **Feature-expansion follow-ups from run #7 evidence**: added missing IAM actions `bedrock:CountTokens` and `bedrock-mantle:CountTokens` (29+14 cells were 403-broken); fixed the batches probe TypeError (`_req_snapshot` model collision); strengthened the adaptive_thinking probe with `output_config: {effort: high}` and a harder prompt (accepted requests were returning no thinking block); classified Bedrock's generic "request is not valid" rejection and "not yet available" (Mantle live web search) as cleanly unsupported.
- **피처 확장 후속 (run #7 증거 기반)**: IAM `bedrock:CountTokens`·`bedrock-mantle:CountTokens` 추가(43셀 403 해소), batches 프로브 TypeError 수정(`_req_snapshot` model 충돌), adaptive_thinking 프로브에 `output_config effort high`+난이도 있는 프롬프트(수락은 되나 thinking 블록 미출력 문제), Bedrock generic "request is not valid" 거부와 "not yet available"(Mantle live 웹 검색)을 깨끗한 미지원으로 분류.

## v2.14.0 — 2026-07-11

### Added
- **Five new parity features** (catalog 7 → 12): `adaptive_thinking` (thinking type adaptive, thinking-block evidence, Fable 5 only), `count_tokens` (endpoint round-trip, input_tokens > 0), `batches` (Message Batches submit → status → cancel), `web_search` and `computer_use` (server-tool definition acceptance; web_search also probes the OpenAI Responses built-in tool). Per-feature surface maps keep non-implemented combinations as skipped; ~536 probes per run.
- **패리티 피처 5종 추가** (카탈로그 7 → 12): `adaptive_thinking`(thinking type adaptive, thinking 블록 증거, Fable 5 전용), `count_tokens`(엔드포인트 왕복, input_tokens > 0), `batches`(Message Batches submit→status→cancel), `web_search`·`computer_use`(서버측 도구 정의 수락 — web_search는 OpenAI Responses 내장 도구도 프로빙). 피처별 surface 맵으로 미구현 조합은 skipped 유지, 런당 ~536 프로브.

## v2.13.0 — 2026-07-11

### Added
- **Mantle Messages surface in parity runs**: Bedrock Claude models now also probe the Bedrock Mantle `/anthropic` (Anthropic Messages-compatible) endpoint in `MANTLE_ANTHROPIC_REGION` (default ap-northeast-1) as a 6th matrix column — SigV4-derived bearer token, FM ids (profile prefix stripped). Live check 2026-07-11: the endpoint exists in ap-northeast-1 but serves no Claude model yet, so cells report as cleanly unsupported (`does not exist` now classifies as unsupported) and will flip automatically when AWS enables models there.
- **패리티 런에 Mantle Messages surface 추가**: Bedrock Claude 모델이 Bedrock Mantle `/anthropic`(Anthropic Messages 호환) 엔드포인트도 프로빙 — 6번째 매트릭스 컬럼, 리전 `MANTLE_ANTHROPIC_REGION`(기본 ap-northeast-1), SigV4 파생 bearer + FM id(프로파일 접두사 제거). 2026-07-11 실측: 엔드포인트는 실존하나 ap-northeast-1 서빙 모델 없음 → "깨끗한 미지원"으로 기록(`does not exist` → unsupported 분류)되며, 서빙 시작 시 자동으로 Supported 전환.
- **Evidence modal with Request/Response JSON**: every parity probe now stores a request snapshot (long strings trimmed with original length noted) in its evidence; the cell modal is restyled as an EVIDENCE panel — `feature · surface · model_id` header, status pill + latency + verdict sentence, and collapsible Error / Request JSON / Response JSON sections (collapsed on success, expanded on failure).
- **증거 모달 Request/Response JSON**: 모든 패리티 프로브가 요청 스냅샷(장문은 원 길이 표기와 함께 절단)을 증거에 저장. 셀 모달을 EVIDENCE 패널로 개편 — `feature · surface · model_id` 헤더, 상태 pill + latency + 판정 문장, 접이식 Error / Request JSON / Response JSON 섹션 (성공 시 접힘, 실패 시 펼침).

### Changed
- **Parity matrix rows**: first column now shows the feature name (bold, on every row) with the model id in monospace beneath — matching the Feature Parity reference layout.
- **Model Explorer Messages API note**: the Bedrock Claude Messages API tab now also mentions the Bedrock Mantle `/anthropic` endpoint (bearer token, some regions e.g. us-east-1) as an alternative path — verified live 2026-07-11.
- **패리티 매트릭스 행**: 첫 컬럼을 피처명(굵게, 매 행) + 모델 id(모노스페이스)로 변경 — 참조 레이아웃과 일치.
- **모델 탐색 Messages API 설명**: Bedrock Mantle `/anthropic` 엔드포인트(bearer 토큰, us-east-1 등 일부 리전) 경로 병기 (2026-07-11 실측).

## v2.12.0 — 2026-07-11

### Added
- **Parity provider summary cards + insights drawer**: /parity now opens with per-provider cards (Anthropic / OpenAI / Amazon — health donut, check counts by status); selecting a card slides in a right-hand Key Findings drawer (broken features with cell ratios and affected models/surfaces, cleanly-unsupported chips, weakest-model bars).
- **Parity run-over-run changes banner**: `/api/parity/latest` now returns `changes` (diff vs the previous completed run, new cells marked); the page shows them at the top (or an explicit "no changes" note).
- **Parity model picker**: the search box is now a combobox — focusing it lists all models for one-click selection, with a clear (×) button.
- **Dashboard anomaly box**: a rounded banner at the top of the dashboard summarizes probe failures in the last 12 hours per model (`GET /api/auto-probe/anomalies?hours=12`), green when all probes succeeded.
- **패리티 provider 요약 카드 + 상세 드로어**: /parity 상단에 provider별 카드(Anthropic/OpenAI/Amazon — 헬스 도넛, 상태별 검사 수). 카드 선택 시 우측 Key Findings 바 — Broken 피처(셀 비율·대상 모델/surface), 깨끗한 미지원 칩, 취약 모델 바.
- **패리티 런 간 변경 배너**: `/api/parity/latest`가 직전 완료 런 대비 `changes`(diff, 신규 셀 표시) 반환, 페이지 상단에 변경사항(또는 "변경 없음") 표시.
- **패리티 모델 선택기**: 검색창이 콤보박스로 — 포커스 시 전체 모델 리스트에서 클릭 선택, 지우기(×) 버튼.
- **대시보드 이상 징후 박스**: 대시보드 상단 라운드 배너가 최근 12시간 프로브 실패를 모델별 요약 (`GET /api/auto-probe/anomalies?hours=12`), 전체 성공 시 녹색 표시.

### Changed
- **Parity schedule: daily → every 12 hours** (`rate(12 hours)` EventBridge schedule, was cron 01:00 UTC).
- **패리티 스케줄: 일 1회 → 12시간 주기** (`rate(12 hours)`, 기존 cron 01:00 UTC).

## v2.11.2 — 2026-07-11

### Fixed
- **Model Explorer: Messages API example missing on Bedrock Claude cards**: Bedrock Claude cards only showed Converse/InvokeModel tabs. Added a third tab — Anthropic Messages API via the `AnthropicBedrock` client (anthropic SDK, SigV4, no Anthropic API key) — matching the Bedrock Central reference (Converse / InvokeModel / Messages all visible).
- **모델 탐색: Bedrock Claude 카드에 Messages API 예제 누락**: Converse/InvokeModel 두 탭만 표시되던 것을 수정 — anthropic SDK의 `AnthropicBedrock` 클라이언트(SigV4, Anthropic API 키 불필요)로 호출하는 Messages API 탭을 추가해 Bedrock Central 참조안처럼 3개 API가 모두 표기되도록 함.

## v2.11.1 — 2026-07-11

### Fixed
- **Parity probe token budget — false-Broken fix**: run #1 evidence showed every Claude `structured_output` cell Broken because `max_tokens=64` truncated the (valid) fenced JSON before its closing `}`, and Fable 5 `system_instructions` returned empty text under the same budget. Introduced per-feature budgets (`max_tokens_for`): structured_output 512, default 256, reasoning unchanged at 2048. Regression tests assert the budgets and that truncated JSON is still rejected.
- **패리티 프로브 토큰 예산 — false-Broken 수정**: 첫 런 증거에서 Claude 전 모델의 `structured_output`이 Broken — 모델은 정상 JSON을 반환했으나 `max_tokens=64`로 닫는 `}` 이전에 절단된 것이 원인. Fable 5 `system_instructions`의 빈 응답도 동일 계열. 피처별 예산(`max_tokens_for`) 도입: structured_output 512, 기본 256, reasoning 2048 유지. 예산 회귀 테스트 + 절단 JSON 거부 테스트 추가.

## v2.11.0 — 2026-07-11

### Added
- **Parity Run engine — real execution-evidence probes** (replaces the v2.10.0 screenshot gallery): a sweep fans out across monitored models × 5 API surfaces (Converse / InvokeModel / Messages / ChatCompletions / Responses) × 7 features (basic, streaming, system_instructions, tool_use, structured_output, reasoning, caching). Each cell is judged from real API responses — tool canary round-trip, system-instruction canary, JSON validity, cached-token counts on repeat, ≥2 stream deltas — never from HTTP 200 alone. Clean provider rejections classify as `unsupported`, evidence failures as `broken`. Results persist to RDS (`parity_runs`/`parity_results`); the /parity page renders a health summary + status matrix with per-cell evidence modal; manual trigger (login) + daily EventBridge schedule (01:00 UTC) via a new Fargate one-shot task.
- **패리티 런 엔진 — 실제 실행-증거 프로브** (v2.10.0 스크린샷 갤러리 대체): 모니터링 모델 × 5개 API surface(Converse/InvokeModel/Messages/ChatCompletions/Responses) × 7개 피처(basic, streaming, system_instructions, tool_use, structured_output, reasoning, caching)로 팬아웃. 도구 카나리 왕복·시스템 지시 카나리·JSON 유효성·반복 요청 캐시 토큰·스트림 델타 2개 이상 등 응답 내용으로 판정 — HTTP 200만으로는 판정하지 않음. provider의 깨끗한 거부는 `unsupported`, 증거 실패는 `broken`. 결과는 RDS(`parity_runs`/`parity_results`)에 저장, /parity 페이지가 헬스 요약 + 상태 매트릭스 + 셀별 증거 모달 렌더링. 수동 트리거(로그인) + 일일 EventBridge 스케줄(01:00 UTC, 신규 Fargate one-shot).

### Changed
- **`APP_VERSION` v2.10.0 → v2.11.0** (`frontend/src/lib/version.ts`).

---

## v2.10.0 — 2026-07-11

### Added
- **Parity Run page (`/parity`)**: new nav menu documenting how a Bedrock feature-parity run works — Korean translation of the 5-step process (scheduled sweep via EventBridge/Step Functions, agent-maintained feature catalog in DynamoDB, model × region × API-surface fan-out, execution-evidence probes, classification & storage) with the original English available via the language toggle, a 20-capture result gallery (deduplicated, WebP-optimized 9.5MB → 2.2MB, click-to-enlarge lightbox), and a link to the full HTML report (2026-07-08).
- **패리티 런 페이지 (`/parity`)**: Bedrock 기능 패리티 런의 동작 방식을 문서화한 신규 메뉴 — 5단계 프로세스(EventBridge/Step Functions 예약 스윕, DynamoDB 에이전트 관리 피처 카탈로그, 모델×리전×API surface 팬아웃, 실행-증거 프로브, 분류·저장)의 한국어 번역(EN 토글 시 원문), 결과 스크린샷 20장 갤러리(중복 제거·WebP 최적화 9.5MB→2.2MB, 클릭 확대), 전체 HTML 리포트(2026-07-08) 링크.

### Changed
- **`APP_VERSION` v2.9.2 → v2.10.0** (`frontend/src/lib/version.ts`).

---

## v2.9.2 — 2026-07-11

### Added
- **Model Explorer: API-type tabs with explanations** — code examples are now labeled by API (Bedrock: Converse API + InvokeModel API for Claude models; Anthropic CP: Messages API; OpenAI: Responses API) with a short description of what each API means, shown when a model card is selected.
- **모델 탐색 코드 예제에 API 종류 탭 + 설명** — Converse API/InvokeModel API(Bedrock), Messages API(Anthropic CP), Responses API(OpenAI)로 표기하고, 카드 선택 시 각 API가 의미하는 바를 설명으로 표시. Claude 계열 Bedrock 모델은 InvokeModel 네이티브 예제 추가.

### Fixed
- **/models 페이지 자체의 내비 순서 누락 수정**: v2.9.1 재배치가 다른 페이지에만 적용되고 모델 탐색 페이지의 활성 탭은 끝에 남아 있었음.
- **`APP_VERSION` v2.9.1 → v2.9.2**.

---

## v2.9.1 — 2026-07-11

### Changed
- **Nav order**: "모델 탐색" menu moved to sit right after "대시보드" on all pages.
- **내비 순서**: "모델 탐색" 메뉴를 전 페이지에서 "대시보드" 바로 다음으로 이동.
- **`APP_VERSION` v2.9.0 → v2.9.1** (`frontend/src/lib/version.ts`).

---

## v2.9.0 — 2026-07-11

### Added
- **Model Explorer (`/models`)**: new nav menu listing all monitored models as a searchable/filterable card grid (channel filter: Anthropic CP / Bedrock / OpenAI Mantle / OpenAI 1P). Selecting a card opens a detail modal with the exact invoke model ID per provider path, endpoint/region, token pricing, copy-ready code examples matching the prober's real call patterns (boto3 `converse_stream`, anthropic SDK + CP on AWS endpoint, openai SDK + Mantle base_url, openai SDK + 1P Responses API), documentation/console links, and a deep link to that model's dashboard trend (v2.7.1 URL-share format). Data comes from `/api/models` — new models appear automatically.
- **모델 탐색 (`/models`)**: 모니터링 중인 전체 모델을 검색·채널 필터 가능한 카드 그리드로 보여주는 신규 메뉴. 카드 선택 시 상세 모달 — provider path별 정확한 호출 모델 ID, 엔드포인트·리전, 토큰 단가, prober 실제 호출 방식과 동일한 복사용 코드 예제(boto3 `converse_stream` / anthropic SDK + CP on AWS / openai SDK + Mantle / openai SDK + 1P Responses API), 문서·콘솔 링크, 해당 모델 대시보드 트렌드 바로가기. 데이터는 `/api/models` 기반 — 모델 추가 시 자동 반영.

### Changed
- **`APP_VERSION` v2.8.4 → v2.9.0** (`frontend/src/lib/version.ts`).

---

## v2.8.4 — 2026-07-11

### Fixed
- **White theme: tinted panel cards now render as clean white cards** (matching the dashboard): reliability channel cards and the cost gradient card keep their colored titles/borders for identity, but the card body is white in the light theme via a new `light:` Tailwind variant (`html.light &`). Dark theme unchanged.
- **화이트 테마 카드 정리**: 신뢰성 채널 카드·비용 그라데이션 카드의 색 틴트 배경을 라이트에서 대시보드와 동일한 흰색 카드로 전환 (채널 식별용 제목·보더 색은 유지). 신규 `light:` Tailwind 변형 도입. 다크 테마는 변경 없음.

### Changed
- **`APP_VERSION` v2.8.3 → v2.8.4** (`frontend/src/lib/version.ts`).

---

## v2.8.3 — 2026-07-11

### Fixed
- **Accent colors unreadable in white theme across all pages**: metric/badge text tuned for dark backgrounds (`text-emerald-400`, `text-rose-400`, `text-amber-400`, `text-blue-300`, …) washed out on white cards. The light tints (steps 200/300/400) of all 17 used accent hues are now CSS variables that swap to the same hue's dark tones (200→800, 300→700, 400→600) in the light theme — no component changes; solid 500+ (buttons) and low-opacity tint boxes stay shared between themes.
- **화이트 테마에서 전 페이지 액센트 색 가독성 저하**: 다크 배경 기준으로 선정된 지표·배지 텍스트(`text-emerald-400`, `text-rose-400`, `text-amber-400`, `text-blue-300` 등)가 흰 카드에서 씻겨 보임. 사용 중인 17개 액센트 hue의 밝은 톤(200/300/400)을 CSS 변수화해 라이트에서 같은 hue의 진한 톤(200→800, 300→700, 400→600)으로 교체 — 컴포넌트 무수정, 500 이상(버튼)과 저투명 틴트 박스는 양 테마 공용 유지.

### Changed
- **`APP_VERSION` v2.8.2 → v2.8.3** (`frontend/src/lib/version.ts`).

---

## v2.8.2 — 2026-07-10

### Fixed
- **AI Insights unreadable in white theme**: `MessageMarkdown` hardcoded `prose-invert` (dark-only typography), rendering light text on white cards. Typography now switches with the theme; chat bubbles use the same component and are fixed together.
- **화이트 테마에서 AI 인사이트 안 보임**: `MessageMarkdown`이 다크 전용 `prose-invert`를 하드코딩해 흰 카드 위 밝은 글자로 렌더링됨. 테마에 따라 typography 분기 — 같은 컴포넌트를 쓰는 챗봇 말풍선도 함께 수정.

### Changed
- **`APP_VERSION` v2.8.1 → v2.8.2** (`frontend/src/lib/version.ts`).

---

## v2.8.1 — 2026-07-10

### Fixed
- **Chatbot `prompt is too long` (1.6M tokens)**: the `get_trend` chat tool returned every raw probe point (56k+ points ≈ 1.6M tokens at hours=168) as a tool_result, blowing ConverseStream's 1M-token limit. Ranges over 6h now aggregate to (model, hour-bucket) averages, responses are capped at `MAX_TREND_POINTS`(2500) with an explicit `aggregation`/`note` field, and the query selects only needed columns. `compare_models` computes p50/p95 from raw values (unaffected by aggregation).
- **챗봇 `prompt is too long`(160만 토큰) 오류**: `get_trend` 도구가 원본 포인트 전부(168h 기준 56k+개 ≈ 1.6M 토큰)를 tool_result로 반환해 ConverseStream 1M 토큰 상한 초과. 6시간 초과 조회는 (모델, 정시 버킷) 평균으로 축약, 응답 포인트는 `MAX_TREND_POINTS`(2500) 상한 + `aggregation` 필드 명시, 필요한 컬럼만 조회. `compare_models`의 p50/p95는 원본 값으로 계산(축약 영향 없음).
- **2026-07-08 커넥션 풀 장애 수정 git 복구**: TCP keepalive + statement_timeout `connect_args`가 미커밋 상태로 운영 이미지에만 존재했음 — 이미지에서 추출해 회귀 테스트와 함께 정식 커밋 (다음 빌드에서의 조용한 소실 방지).

### Changed
- **`APP_VERSION` v2.8.0 → v2.8.1** (`frontend/src/lib/version.ts`).

---

## v2.8.0 — 2026-07-10

### Added
- **Dark/light theme toggle**: header ☀️/🌙 button on all 6 pages switches between the existing dark theme (default) and a new SnowUI-toned white theme; choice persists in localStorage and is restored pre-hydration (no flash). Implementation remaps the Tailwind gray scale to CSS variables (`globals.css` + `tailwind.config.ts`), so all ~495 existing `gray-*` class usages theme automatically with zero component changes; charts (Recharts JS-constant colors) switch via a `useChartTheme()` hook. Light theme adds subtle card shadows for depth.
- **다크/화이트 테마 토글**: 6개 페이지 헤더의 ☀️/🌙 버튼으로 기존 다크(기본)와 SnowUI 톤 화이트 테마 전환. 선택은 localStorage에 저장되고 하이드레이션 전에 복원(FOUC 없음). Tailwind gray 스케일을 CSS 변수로 재매핑해 기존 `gray-*` 클래스 약 495곳이 컴포넌트 수정 없이 자동 테마화, 차트(Recharts JS 상수 색)는 `useChartTheme()` 훅으로 분기. 화이트 테마에는 카드 그림자 추가.

### Changed
- **`APP_VERSION` v2.7.2 → v2.8.0** (`frontend/src/lib/version.ts`).

---

## v2.7.2 — 2026-07-10

### Fixed
- **First-visit selection defaults to All**: the v2.7.1 representative-model auto-selection also highlighted those models' cards in the status grid, which looked like stray pre-selected cards on first load. Auto-selection removed — first visit shows all models (전체) with no cards highlighted; "대표 모델" remains available as an explicit button, and shared URLs still restore their exact selection.
- **첫 진입 선택 기본값을 전체로 복원**: v2.7.1의 대표 모델 자동 선택이 상태 그리드 카드 하이라이트와 연동되어 첫 화면에서 일부 카드가 선택된 것처럼 보였음. 자동 선택 제거 — 첫 진입은 전체 표시(카드 하이라이트 없음), "대표 모델"은 명시적 버튼으로 유지, 공유 URL 복원은 그대로 동작.

### Changed
- **`APP_VERSION` v2.7.1 → v2.7.2** (`frontend/src/lib/version.ts`).

---

## v2.7.1 — 2026-07-09

### Added
- **Trend chart readability**: first visit now shows one representative channel per family (~10 lines instead of 28); "대표 모델"/"전체" buttons switch modes. Legend entries are clickable to toggle model lines. Long-range views (>24h) draw a min–max band behind the average line when a single model is selected (backend now returns per-bucket min/max). Selection state (models/hours/category) is synced to the URL query — survives refresh and is shareable.
- **트렌드 차트 가독성**: 첫 방문 시 패밀리별 대표 채널 1개만 표시(28개 → 약 10개 라인), "대표 모델"/"전체" 버튼으로 전환. 범례 클릭으로 라인 토글. 24h 초과 조회에서 단일 모델 선택 시 평균선 뒤에 min–max 밴드 표시(backend가 버킷별 min/max 반환). 선택 상태(models/hours/category)는 URL query에 동기화 — 새로고침 유지·링크 공유 가능.

### Changed
- **`APP_VERSION` v2.7.0 → v2.7.1** (`frontend/src/lib/version.ts`).

---

## v2.7.0 — 2026-07-09

### Added
- **Data retention policy**: raw `probe_results` older than `RETENTION_DAYS` (default 60) are aggregated into a new `probe_results_hourly` table — per (model, category, hour bucket): total/success counts, avg TTFT/latency/TPS, input/output token sums (cost reconstruction possible) — then deleted, in a single atomic transaction (safe retry, no double-aggregation). Runs at the end of every auto-prober cycle. Old `probe_runs` without remaining results are cleaned up (FK-safe).
- **데이터 보존 정책**: `RETENTION_DAYS`(기본 60일)를 지난 원본 `probe_results`를 신규 `probe_results_hourly` 테이블에 (모델, 카테고리, 정시 버킷)별 집계 — 전체/성공 수, 평균 TTFT/레이턴시/TPS, 토큰 합계(비용 재계산 가능) — 로 이관 후 삭제. 집계+삭제는 단일 트랜잭션(재시도 안전). 매 auto-prober cycle 말미 실행, 결과 없는 옛 `probe_runs`도 정리.

### Infra
- **CI (GitHub Actions)**: push(main)/PR마다 backend pytest + frontend tsc/vitest/next build + CDK jest 병렬 실행 (`.github/workflows/ci.yml`, v2.6.2 이후 추가분 포함).
- **CDK 이미지 digest 고정**: 모든 배포는 `-c backendImage`/`-c frontendImage`(digest URI) 필수 — cdk deploy가 서비스를 :latest 구버전으로 되돌리던 실사고(2026-07-09) 원천 차단. `llm-monitor.whchoi.net` alias + ACM cert도 CDK(edge-stack) 소유로 이전.

### Changed
- **`APP_VERSION` v2.6.2 → v2.7.0** (`frontend/src/lib/version.ts`).

---

## v2.6.2 — 2026-07-09

### Fixed
- **Dashboard graph-selection latency**: `/api/auto-probe/trend` took 4.3s even for `hours=1` (336 rows) and 22.2s / 13.3MB for `hours=168`; category/time-range clicks appeared frozen for up to 22s with no feedback, and model-chip clicks blocked the main thread for seconds. Root causes: zero non-PK DB indexes (full scans on burstable t4g.micro), ORM hydrating unused large TEXT columns (`output_text`), no downsampling, an O(T×M×N) client-side pivot re-running on every render (including the 1-second countdown re-render), and no fetch cancellation (a slow stale response could overwrite a newer selection).
- **대시보드 그래프 선택 지연**: `hours=1`(336행)도 4.3초, `hours=168`은 22.2초/13.3MB — 필터 클릭 후 최대 22초 무반응처럼 보였고 모델 칩 클릭도 수 초 멈춤. 원인: PK 외 인덱스 전무(풀 스캔), 미사용 대형 TEXT 컬럼까지 ORM 로드, 다운샘플링 부재, 매 렌더(1초 카운트다운 포함)마다 재실행되는 O(T×M×N) 클라이언트 피벗, fetch 취소 부재(늦게 도착한 이전 응답이 최신 선택을 덮어쓰는 경쟁 상태).

### Changed
- backend: `probe_runs(is_auto,status,created_at)` / `probe_results(run_id)` / `probe_results(timestamp)` 인덱스 (lifespan 마이그레이션 `ensure_performance_indexes`, 멱등). timestamp 인덱스는 cost/reliability/efficiency/analysis 공통 이득.
- backend: trend 쿼리 다이어트 — 응답에 쓰는 8컬럼만 SELECT + JOIN (`output_text`/`prompt` 미조회).
- backend: `hours>24` 시간 버킷 평균 다운샘플링 (168h: 56k행 → ~4.7k행), 24h 이하는 5분 해상도 유지.
- backend: trend/latest에 `Cache-Control: public, max-age=0, s-maxage=30` (CloudFront 전용, 브라우저 캐시 없음).
- frontend: TrendChart 피벗을 `lib/pivotTrend.ts` Map 기반 O(N)으로 추출 + `useMemo`/`React.memo`, 700 포인트 초과 시 dot 생략 (vitest 테스트 도입).
- frontend: 필터 재조회 중 "데이터 갱신 중…" 오버레이, `AbortController`로 이전 요청 취소, 필터 변경 시 `/status` 재호출 생략.
- **`APP_VERSION` v2.6.1 → v2.6.2** (`frontend/src/lib/version.ts`).

### Infra
- CDK `edge-stack.ts`: `/api/auto-probe/*` 전용 behavior — `BedrockMonitorAutoProbeCache` 캐시 정책(origin Cache-Control 존중, 쿼리스트링 캐시 키, gzip/brotli 압축). 기존 `/api/*`는 SSE 보호로 무압축이었음. **적용에는 `cdk deploy BedrockMonitor-Edge` 필요.**

---

## v2.6.1 — 2026-07-03

### Fixed
- **Reliability view now includes OpenAI/GPT channels**: `routers/reliability.py` `_parse_label` only matched `Bedrock|Anthropic` labels, so every `OpenAI …` label fell to channel `"Other"`, and the formatter's hardcoded 3-channel tuple silently dropped it. Now the regex accepts `OpenAI`, OpenAI labels map to `family="GPT 5.x"` / `channel="OpenAI <region|1P>"`, and the formatter iterates all present channels in rank order (Anthropic → Bedrock Global → Bedrock US → OpenAI Mantle/1P). GPT 5.4 (4 channels: us-east-1/2/west-2 + 1P) and GPT 5.5 (3: us-east-1/2 + 1P) now appear on `/reliability`.
- **신뢰성 화면에 OpenAI/GPT 채널 포함**: `reliability.py` `_parse_label`이 `Bedrock|Anthropic`만 매칭해 모든 `OpenAI …` 라벨이 채널 `"Other"`로 빠졌고, 포매터의 하드코딩 3채널 튜플이 이를 조용히 누락시켰습니다. 이제 regex가 `OpenAI`를 허용하고, OpenAI 라벨은 `family="GPT 5.x"` / `channel="OpenAI <region|1P>"`로 매핑되며, 포매터는 존재하는 모든 채널을 순위 순서로 표시합니다.

### Changed
- **`APP_VERSION` v2.6.0 → v2.6.1** (`frontend/src/lib/version.ts`).
- `ReliabilityPanel.tsx`: OpenAI 채널 색상(green 계열) + 설명 텍스트에 OpenAI 채널 명시.

---

## v2.6.0 — 2026-07-02

### Added
- **OpenAI GPT 1P direct monitoring (2 channels)**: `OpenAI GPT 5.4 (1P)` + `OpenAI GPT 5.5 (1P)` via a **5th provider path** calling `https://api.openai.com/v1` directly (OpenAI Responses API streaming), distinct from the Bedrock Mantle path. Catalog 26 → 28 (Bedrock 15 + Anthropic CP 6 + OpenAI 5 → 7). Key scheme `openai:1p:gpt-5.x` (pseudo-region `1p`, no AWS region) — reuses the `openai:` prefix so pricing/cost/sort normalizers need no change. Separate credential: **OpenAI platform key** (`OPENAI_1P_API_KEY`, `sk-proj-…`) — not interchangeable with the Mantle bearer (`ABSK-…`). Verified live: both models invocable (`status=completed`).
- **OpenAI GPT 1P direct 모니터링 추가 (2채널)**: `OpenAI GPT 5.4 (1P)` + `OpenAI GPT 5.5 (1P)`. `https://api.openai.com/v1` 직접 호출(Responses API 스트리밍)하는 **5번째 provider path** — Bedrock Mantle와 별개. 모니터링 대상 26 → 28개 (Bedrock 15 + Anthropic CP 6 + OpenAI 5 → 7). key 스킴 `openai:1p:gpt-5.x`(pseudo-region `1p`, AWS 리전 없음) — `openai:` prefix 재사용으로 pricing/cost/sort 정규화 수정 불필요. 별도 자격증명: **OpenAI platform 키**(`OPENAI_1P_API_KEY`, `sk-proj-…`) — Mantle bearer(`ABSK-…`)와 호환 불가.
- **ADR-020**: OpenAI 1P direct (api.openai.com) provider path 설계 결정 기록.

### Changed
- **`APP_VERSION` v2.5.0 → v2.6.0** (`frontend/src/lib/version.ts`).
- `_register_openai_models()` — Mantle(`OPENAI_API_KEY`)과 1P(`OPENAI_1P_API_KEY`) 경로를 독립 gate (한쪽 키만 있어도 그쪽만 등록).

### Infra
- CDK `app-services-stack.ts` + `scheduler-stack.ts`: SSM SecureString `/bedrock-monitor/openai-1p-api-key` → `OPENAI_1P_API_KEY` secret + `OPENAI_1P_GPT_54/55_MODEL_ID` env 주입 (backend + autoprober + insights). IAM/SigV4 없음(bearer). 배포 runbook에 1P 키 사전 생성 스텝 추가.

### Docs
- 모니터링 카운트 26 → 28 동기화: CLAUDE.md(Monitored Models 표에 1P 컬럼 + 카운트 8곳 + Path 5 설명 + 라벨 정책), README.md(영/한 + version 배지 2.5.0 → 2.6.0), docs/architecture.md(ADR-020 행 + 토폴로지 카운트), docs/api-reference.md(`model_count`).

---

## v2.5.0 — 2026-06-30

### Added
- **Claude Sonnet 5 monitoring (3 channels)**: Bedrock Global (`global.anthropic.claude-sonnet-5`), Bedrock US/Geo (`us.anthropic.claude-sonnet-5`), Anthropic CP on AWS (`sonnet-5`, `/v1/models` auto-discovery). Catalog 23 → 26 (Bedrock 13 → 15 + Anthropic CP 5 → 6 + OpenAI 5). Reasoning model — `temperature` suppressed via `_REASONING_MODEL_PATTERNS` (adaptive-thinking family, like Opus 4.7/4.8 / Fable 5). `FAMILY_ORDER` 9 → 10 (Sonnet 5 ranks above Sonnet 4.6) + indigo color (`#6366f1`/`#4f46e5`/`#4338ca`).
- **Claude Sonnet 5 모니터링 추가 (3채널)**: Bedrock Global (`global.anthropic.claude-sonnet-5`), Bedrock US/Geo (`us.anthropic.claude-sonnet-5`), Anthropic CP on AWS (`sonnet-5`, `/v1/models` 자동 발견). 모니터링 대상 23 → 26개 (Bedrock 13 → 15 + Anthropic CP 5 → 6 + OpenAI 5). Reasoning 모델 — `_REASONING_MODEL_PATTERNS`로 `temperature` 미전송 (Opus 4.7/4.8 · Fable 5와 동일한 adaptive-thinking family). `FAMILY_ORDER` 9 → 10 (Sonnet 5가 Sonnet 4.6 위) + indigo 색상.
- **Sonnet 5 토큰 단가** (AWS Bedrock 기준, USD/1M): input $2.00 / output $10.00 — `backend/pricing.py` + `frontend/src/lib/pricing.ts`. `/cost`·효율성 점수 자동 반영.

### Changed
- **`APP_VERSION` v2.4.1 → v2.5.0** (`frontend/src/lib/version.ts`).

### Docs
- 모니터링 카운트 23 → 26 동기화: CLAUDE.md(모델 표 + 카운트 6곳), README.md(영/한 8곳 + version 배지 2.2.0 → 2.5.0), docs/architecture.md, docs/api-reference.md(`model_count`), frontend/src/components/CLAUDE.md. CLAUDE.md Monitored Models 표에 Claude Sonnet 5 행 추가 (Global ✅ / US ✅ / CP ✅).

---

## v2.4.1 — 2026-06-26

### Added
- **OpenAI GPT 5.4 monitoring in us-west-2 (Bedrock Mantle)**: catalog 22 → 23 (OpenAI 4 → 5). us-west-2 serves gpt-5.4 only — gpt-5.5 is not available there. Model registration is now per-model region availability via `_OPENAI_MODEL_SPECS`.
- **OpenAI GPT 5.4 모니터링 us-west-2 추가 (Bedrock Mantle)**: 모니터링 대상 22 → 23개 (OpenAI 4 → 5). us-west-2는 gpt-5.4만 제공 — gpt-5.5 미지원. `_OPENAI_MODEL_SPECS`를 통해 모델별 리전 가용성으로 등록.

### Changed
- **`APP_VERSION` v2.4.0 → v2.4.1** (`frontend/src/lib/version.ts`).

### Docs
- CLAUDE.md OpenAI 표에 us-west-2 컬럼 추가 (GPT 5.4 ✅ / GPT 5.5 —). 카운트 22 → 23 동기화. README·architecture.md·api-reference.md·frontend/src/components/CLAUDE.md 업데이트.

---

## v2.4.0 — 2026-06-26

### Added
- **OpenAI GPT 5.4 / GPT 5.5 모니터링 (4채널)**: Bedrock Mantle OpenAI-compatible endpoint 경유. 각 모델을 us-east-1 + us-east-2 2개 리전에서 모니터링 (채널 4개). 새 `"OpenAI"` family 추가. 모니터링 대상 18 → 22개 (Bedrock 13 + Anthropic CP 5 + OpenAI 4).
- **OpenAI 토큰 단가** (USD/1M): gpt-5.4 input $2.75 / output $16.50, gpt-5.5 input $5.50 / output $33.00 — `backend/pricing.py` + `frontend/src/lib/pricing.ts`. `/cost`·효율성 점수 자동 반영.
- **ADR-019**: OpenAI GPT via Bedrock Mantle 설계 결정 기록.

### Changed
- **`APP_VERSION` v2.3.0 → v2.4.0** (`frontend/src/lib/version.ts`).

---

## v2.3.0 — 2026-06-10

### Added
- **Claude Fable 5 모니터링 추가 (3채널)**: Bedrock Global (`global.anthropic.claude-fable-5`), Bedrock US/Geo (`us.anthropic.claude-fable-5`), Anthropic CP on AWS (`anthropic:claude-fable-5`, `/v1/models` 자동 발견). 2026-06-09 GA된 Anthropic 최신 flagship(Mythos-class). 모니터링 대상 15 → 18개 (Bedrock 13 + Anthropic CP 5). `FAMILY_ORDER` 최상단(flagship) + teal 색상. 6개 메뉴 dynamic 집계로 자동 포함.
- **참고 — Fable 5 Covered Model + Data Retention(리전별)**: Fable/Mythos는 `provider_data_share` retention 모드에서만 동작하며 **리전별 설정**이다. us.(us-east-1) + global.(Seoul ap-northeast-2 경유) 둘 다 `provider_data_share` opt-in 적용(2026-06-10). plain `anthropic.*` FM ID는 on-demand 미지원(inference profile 필요). 1P/CP는 별도 계정·워크스페이스라 그 계정에서 관리. ⚠️ 30일 데이터 공유.
- **Fable 5 토큰 단가** input $10 / output $50 per 1M (AWS Bedrock on-demand 출시 가격) — `backend/pricing.py` + `frontend/src/lib/pricing.ts`. US-only(Geo) inference의 1.1x 프리미엄은 기존 단일-키 단가 정책상 미반영(모든 모델 공통).

### Changed
- **`_REASONING_MODEL_PATTERNS`에 `fable-5` 추가** — Opus 4.x와 동일하게 `inferenceConfig.temperature` 생략.
- **`APP_VERSION` v2.2.1 → v2.3.0**.

### Docs
- CLAUDE.md `Monitored Models` 표에 Fable 5 행 추가 + 카운트 15 → 18. README·architecture.md·api-reference.md 동기화.

---

## v2.2.1 — 2026-06-09

### Fixed
- **AutoProber DB connection-pool 고갈 (운영 장애)**: `run_cycle()`가 모델당 `SessionLocal()`을 submit 루프에서 미리 생성하고 in-order 결과 루프에서야 close → 느린 probe(Opus 4.8 Global read-timeout)가 루프를 막는 동안 완료된 세션들의 connection이 누적되어 pool(5+5=10)을 고갈. 모델 수 12→15 확장으로 한계 초과 → tail 5개 모델(Nova US + Anthropic CP 4종)이 `QueuePool limit reached`로 결과 저장 실패(대시보드 카드 누락). 세션 수명을 worker 실행에 묶어 동시 connection을 `max_workers`(3)로 제한 → 모델 수와 무관하게 안전. 회귀 테스트 `backend/tests/test_auto_prober_pool.py` 추가.

---

## v2.2.0 — 2026-06-01

### Added
- **Claude Opus 4.8 모니터링 (3채널)**: Bedrock Global (`global.anthropic.claude-opus-4-8`), Bedrock US (`us.anthropic.claude-opus-4-8`), Anthropic CP on AWS (`anthropic:claude-opus-4-8`, `/v1/models` 자동 발견). `prober.py` `AVAILABLE_MODELS` + `_ANTHROPIC_TARGETS` 등록. 모니터링 대상 12 → 15개 (Bedrock 11 + Anthropic CP 4). 6개 메뉴(Dashboard·Cost·Reliability·Efficiency·Analysis·Prompts)는 dynamic 집계라 자동 포함.
- **Opus 4.8 토큰 단가** input $15 / output $75 per 1M (Opus 4.7과 동일) — `backend/pricing.py` + `frontend/src/lib/pricing.ts` 동기화. `/cost`·효율성 점수 자동 반영.
- **Frontend Opus 4.8 색상/정렬**: `TrendChart.tsx` MODEL_COLORS 3종(rose 계열) + FAMILY_FALLBACK, `StreamingView.tsx` MODEL_COLORS + `extractModelName` 분기, `sortModels.ts` FAMILY_ORDER 최상단, `PromptsPanel.tsx` OptimizePrompt 타겟 2종.

### Changed
- **`_REASONING_MODEL_PATTERNS`에 `opus-4-8` 추가** — Opus 4.7과 동일하게 `inferenceConfig.temperature` 생략 (reasoning model). 4.8이 temperature를 거부해도 프로브 에러 방지.
- **`APP_VERSION` v2.1.0 → v2.2.0** (`frontend/src/lib/version.ts`).

### Fixed
- **`routers/compare.py` SSE 이중 wrap 버그**: `stream_compare_events`가 이미 `"event: X\ndata: Y\n\n"` 형식으로 yield하는데 `EventSourceResponse`로 감싸 이중 wrap → 클라이언트 파싱 불가. `probes.py`/`insights.py`와 동일하게 `StreamingResponse(media_type="text/event-stream")` + `X-Accel-Buffering: no` 헤더로 수정.

### Infra
- **EventBridge Scheduler `ecs:RunTask` ADR-011 wildcard 적용**: 런타임 IAM role의 RunTask Resource가 옛 task def revision(`:12`/`:5`)에 pin되어 autoprober/insights가 silent fail(2일+ 정지) 중이었음 → task def family `:*` wildcard로 교체해 복구.
- **CDK `scheduler-stack.ts`**: L2 `EcsRunFargateTask`의 자동 생성 role(revision pin) 대신 명시적 `SchedulerInvokeRole`(family `:*` wildcard RunTask + scoped PassRole)을 두 schedule target에 전달 — 재배포 시 재발 방지.

### Docs
- CLAUDE.md `Monitored Models` 표에 Opus 4.8 행 추가 + 모델 카운트 12/13 → 15 정정. README·architecture.md·api-reference.md 카운트 동기화.

---

## v2.1.0 — 2026-05-20

### Added
- **Output Analysis 페이지** (`/analysis`): Stop reason 분포 (end_turn / max_tokens / stop_sequence / tool_use / guardrail_intervened / content_filtered) + Output token 길이 분포 (median/p50/p95/std + 7-bin histogram). 모델 가로 비교 + 카테고리/시간 윈도우 필터 + 해석 가이드 박스.
- **Backend `/api/analysis/*`**: `stop-reasons`, `output-length` 두 엔드포인트. `_normalize_stop_reason()` vendor 차이 흡수.
- **`ProbeResult.stop_reason` 컬럼** + lifespan `ALTER TABLE ADD COLUMN IF NOT EXISTS`. Bedrock `messageStop.stopReason` + Anthropic `final_message.stop_reason` 양쪽 capture.
- **모델 catalogue 확장 9 → 13개**: Claude Opus 4.5 / Sonnet 4.5 × Global/US 추가.
- **Admin user management endpoints**: `GET /api/admin/users`, `DELETE /api/admin/users/{username}`, `POST /api/admin/users/{username}/approve`. admin 전용 (`username == "admin"`).
- **챗봇 초기 추천 풍선말 6개**: 효율성/비용/분석/신뢰성/출력 길이/에러 진단 등 신기능 인사이트 질문으로 갱신.
- **헤더에 `APP_VERSION` 표시** (v2.1.0). `frontend/src/lib/version.ts`가 single source of truth.

### Changed
- **회원가입 `username` → `EmailStr` 검증 강제** (Pydantic + `email-validator>=2.1.0`). 이메일 형식 아닌 입력은 422. LoginForm `type="email"` + 안내.
- **모델명 라벨 통일**: `AVAILABLE_MODELS` 13개 모두 `"Bedrock <family> (<channel>)"` prefix. Frontend `MODEL_COLORS`, `FAMILY_ORDER` 통일. 옛 row는 lifespan rename으로 자동 변환.
- **`/api/auto-probe/status`** DB-sourced: backend in-process state 대신 `ProbeRun(is_auto=1)` 최근 row 기준 (Fargate task 분리 이후 일관성).

### Fixed
- **`_probe_single_model` retry-raise 버그**: retry 소진 시 `raise`로 함수 종료 → ProbeResult row 미저장 → 카드 누락. `raise` → `break` + outer try에서 처리로 수정.
- **ECR `:latest` 태그 함정**: ECS Fargate가 cached container를 실행 → 새 코드 silent 반영 안 됨. 모든 task def를 immutable `v<timestamp>` tag로 전환.
- **EventBridge Scheduler IAM role의 `ecs:RunTask` Resource가 task def revision pinned**: 새 revision으로 schedule update 시 silent fail (autoprober 정지). Resource를 task def family `:*` wildcard로 변경.

### Security
- 회원가입 시 username 이메일 형식 강제.
- Admin endpoint `_ensure_admin` gate + 자기 자신 삭제 차단.

### Infra
- `ecr-image-tag-management` 권장 절차: immutable tag → register-task-definition → update-service + autoprober schedule 동시 갱신.
- AutoProber + Insights 모두 `rate(5 minutes)` 주기.
- **ECR repository 변경** — `bedrock-monitor-backend` → `bedrock-monitor-backend-v2` (Fargate image cache silent bug 우회, ADR-018). 새 repo는 `IMMUTABLE` tag mutability.
- ECS Fargate silent failure 완전 우회를 위해 image URI에 `@sha256:<digest>` 직접 명시 (task def `containerDefinitions[].image` 필드).

### Removed
- **Opus 4.5 (Global/US), Sonnet 4.5 (Global/US)** — 사용자 요청으로 모니터링 대상에서 제외 (2026-05-20). backend `AVAILABLE_MODELS` 정리 + lifespan `DELETE FROM probe_results WHERE model_name LIKE '%Opus 4.5%' OR LIKE '%Sonnet 4.5%'` 자동 적용. 모니터링 대상 9개 Bedrock + 3개 Anthropic CP = 12개.

### Fixed
- Frontend `AutoDashboard.tsx`에 `Opus 4.5`/`Sonnet 4.5` hard-filter 추가 — backend silent bug로 옛 row가 응답에 포함되어도 UI 숨김. 방어적 패치.
- `StreamingView.tsx` MODEL_COLORS에서 4.5 reference 정리 + Opus 4.7 / Sonnet 4.6 추가.

### Docs
- README, CLAUDE.md를 v2.1.0 기준으로 재작성.
- ADR-010~018 신규 작성 (immutable tag, scheduler IAM wildcard, model catalog, output analysis, admin endpoints, status DB-sourced, frontend route split, model catalog reduction, ECR repo swap).

---

## v2.X — 진행 중 (2026-05-19)

### Added
- **Claude Platform on AWS (Path 3 External) 채널 통합**: vendor endpoint `aws-external-anthropic.us-east-2.api.aws` 호출 + `anthropic-workspace-id` 헤더. Anthropic SDK base_url override 패턴. SSM SecureString 2종 (`/bedrock-monitor/anthropic-api-key`, `/bedrock-monitor/anthropic-workspace-id`). 3개 Anthropic 직접 API 모델 자동 등록.
- **Prompts 탭 (`/prompts`)**: 별도 라우트 페이지. 프롬프트 세트 CRUD + Bedrock Simple Prompt Optimization (`bedrock-agent-runtime.optimize_prompt`) 통합. 9개 모니터링 모델로 타겟 매핑.
- **그래프 다중 선택**: 모델 칩/카드 toggle → N개 동시 비교. `selectedModels: Set<string>` 패턴.
- **카드 family-grouped grid**: Opus 4.7 / 4.6 / Sonnet 4.6 / Haiku 4.5 / Nova 2.0 Lite 각각 별도 row를 차지하도록 그룹화.
- **상단 헤더 로그인 버튼** (미인증 시 모달 노출).
- **챗봇 아이콘 친근한 로봇 얼굴** (안테나/눈/입/헤드폰), 위치 `bottom-24`.
- **채널 설명 패널**: Bedrock vs Anthropic CP on AWS 호출 채널 + endpoint URL.
- **모델 카드 inference profile ID 표시**.
- **이력조회 정렬 통일** (family/channel 순서).
- **추천 검색어 + Follow-up 풍선말** (FloatingChat + InsightsPanel).
- **AI Insights bilingual (KO/EN)** + 미인증 사용자 새로고침/검색 시 로그인 모달.

### Changed
- 모델 라벨 통일: 1P는 `Anthropic ... (US)`, 나머지는 `Bedrock ... (Global|US)` 접두사. `lib/sortModels.ts` 공유 유틸 추출.
- AI 인사이트 위치를 그래프 밑으로 이동.
- 인사이트 본문 스크롤 박스 제거 (전체 출력).
- 트렌드 그래프 색상 13개 모두 다른 색 (Bedrock 주황·핑크·인디고·시안 + Anthropic 보라 계열).
- `next.config.mjs` HTML route → `cache-control: no-store, no-cache, must-revalidate, max-age=0`, `_next/static/*` → `public, max-age=31536000, immutable`.
- 5분 주기 Insights 잡 (이전 30분).

### Removed
- `Nova Pro (US)` / `Nova Lite (US)` / `Nova 2.0 Lite (Global)` 모니터링 대상 제외 — `Nova 2.0 Lite (US)`만 유지.
- DB row 자동 삭제 마이그레이션 (lifespan).

### Fixed
- ECS Task Definition rev 9 INACTIVE 상태 → manual register rev 10. CDK가 secret 추가 후 ACTIVE 보장 안 되는 문제 회피.
- SSM `/bedrock-monitor/anthropic-workspace-id` 미존재 시 ECS task가 secret fetch 실패 → 사용자에게 SSM 저장 가이드.
- Frontend Docker build가 `cdk/` 작업 디렉토리에서 실행되어 옛 image SHA 그대로 push되는 문제 → 절대경로 + `--no-cache` 빌드 + 명시적 `docker rmi`.
- Frontend `created_at` PromptSet 타입 에러로 npm build 실패 → 참조 제거.
- backend ECS Task ExecutionRole에 `anthropic-workspace-id` SSM read 권한 부족 → inline policy `AnthropicWorkspaceIdAccess`.
- backend TaskRole에 `bedrock:OptimizePrompt` 권한 부족 → inline policy `BedrockOptimizePrompt`.
- `data-stack.ts`의 JWT_SECRET_KEY plaintext placeholder → `fromSecureStringParameterAttributes` 사전 생성 import.

### Security
- ANTHROPIC_API_KEY / ANTHROPIC_WORKSPACE_ID: ECS Secret (SSM SecureString) 주입.
- JWT_SECRET_KEY: SecureString import 패턴으로 통일.
- 노출된 자격증명 회수·재발급 권고 (사용자 측 실행).

### Infra
- CDK context 영구화: `existingVpcId=vpc-0dfa5610180dfa628`, `appSubnetIds`, `dataSubnetIds`, `albCertificateArn` cdk.json에 박음.
- 카드 정렬 + i18n 채널 설명 + endpoint URL.

### Docs
- 이 문서(`CHANGELOG.md`) 최초 생성.

---

## v2 — 기존 (git history 요약)

### v2-Phase 11~13
- ObservabilityStack (알람·대시보드).
- 8 stacks 전체 architecture + 9 ADRs + runbooks 문서화.
- Seoul region 적응 + 기존 VPC + CloudFront prefix list 패턴.

### v2-Phase 10
- FloatingChat (popup/iframe duality).
- InsightsPanel (AI 인사이트 위젯).

### v2-Phase 9
- SchedulerStack (AutoProber + Insights EventBridge 잡).

### v2-Phase 8
- Auto-prober를 Fargate Task로 분리 (one-shot runner).
- agent/insights/chat 모듈 분리.

### v2-Phase 7
- EdgeStack 분리 (AppServices ALB + CloudFront/WAF Edge).

### v2-Phase 6
- AppServicesStack (frontend/backend Fargate services + Internal ALB).

### v2-Phase 5
- AgentCoreStack (Memory + backend access policy). Runtime은 deferred.

### v2-Phase 4
- ClusterStack (ECS, ECR, KMS log key).

### v2-Phase 3
- DataStack (RDS PostgreSQL).
- NetworkStack을 NAT egress 모드로 revise.

### v2-Phase 2
- NetworkStack (dual VPC mode + PrivateLink endpoints).

---

## v1 — Legacy (점진적으로 정리 중)

- EC2 + Docker Compose PostgreSQL + systemd 운영.
- CloudFront → ALB → EC2 (Next.js 14 + FastAPI).
- 자동 프로빙 5분 주기, 9 모델.
- JWT + bcrypt 인증, SES 승인 이메일.
- 한글 UI (`frontend/src/lib/i18n.ts`).
