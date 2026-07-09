# OpenAI GPT-5.x — TTFB / TTFT 벤치마크 리포트 (Bedrock Mantle 전 리전 + 1P 비교)

**측정일**: 2026-06-26
**채널**:
- **Bedrock Mantle** (3P) — `openai.gpt-5.4`, `openai.gpt-5.5`, 엔드포인트 `bedrock-mantle.<region>.api.aws/openai/v1`
- **1P direct OpenAI** (global) — `gpt-5.4`, 엔드포인트 `api.openai.com/v1` (2026-06-26 추가 측정)
**리전 (Mantle)**: **us-east-1, us-east-2, us-west-2** — 리전별 가용 모델 (us-west-2는 gpt-5.4만; gpt-5.5는 404 not_found)
**측정 위치 (vantage point)**: ap-northeast-2 (Seoul) EC2 — 모니터링 autoprober와 동일 위치
**도구**: `openai` Python SDK, `client.responses.create(stream=True)`
**측정 횟수**: (region, model) 조합당 워밍업 1회 + **측정 10회** (총 5조합 = 50 측정 호출, 단일 순차 실행)

---

## 1. Executive Summary

### 요약 매트릭스 (median, ms)

| channel / region | model | TTFB | TTFT | GAP (thinking) |
|---|---|--:|--:|--:|
| **1P direct (global)** | gpt-5.4 | **410** | **1,251** | **841** |
| Mantle us-west-2 | gpt-5.4 | 830 | 2,765 | 1,854 |
| Mantle us-east-2 | gpt-5.4 | 1,005 | 4,423 | 3,375 |
| Mantle us-east-2 | gpt-5.5 | 1,015 | 3,511 | 2,486 |
| Mantle us-east-1 | gpt-5.4 | 1,090 | 3,284 | 2,182 |
| Mantle us-east-1 | gpt-5.5 | 1,116 | 3,553 | 2,359 |

### 핵심 결론
0. **1P direct(api.openai.com)가 Bedrock Mantle보다 전 지표에서 압도적으로 빠름** — gpt-5.4 기준 TTFB ~2–2.7×, TTFT ~2.2–3.5×, thinking GAP ~2.2–4× 빠름. 1P는 prompt cache hit도 안정적(매 호출 cached≈55.5k)인 반면 Mantle은 0↔55k로 변동. (1P §4.6, 비교 §5.3)
1. **(Mantle 내) TTFB는 리전 근접성에 비례** — Seoul vantage 기준 **us-west-2(≈830ms) < us-east-2(≈1,010ms) < us-east-1(≈1,100ms)**. us-west-2가 us-east-1보다 TTFB ~270ms 빠름 (서부가 trans-Pacific 경로상 더 가까움). Mantle 내에서 가장 견고한(robust) 리전 신호.
2. **TTFB는 모델과 무관** — 같은 리전 내 gpt-5.4 ≈ gpt-5.5 (전송 bound, 추론 bound 아님).
3. **TTFT는 thinking이 지배** — TTFB(~0.8–1.1s) 이후 medium 추론이 끝나야 첫 텍스트. GAP median 1.85–3.38s.
4. **TTFT의 리전·모델 차이는 noisy** — 호출별 `reasoning_tokens`(0–109개) 변동이 워낙 커서, 10회 표본의 TTFT median 차이는 단정하기 어려움. (예: us-east-2 gpt-5.4의 높은 TTFT median 4,423ms는 그 표본에 추론 100+ 토큰 호출이 몰린 영향.)

---

## 2. 정의 (Metrics)

| 지표 | 정의 | 측정 |
|---|---|---|
| **TTFB** | 요청 → 첫 스트림 이벤트(`response.created`), 서버 첫 바이트 | `t(first event) − t(request start)` |
| **TTFT** | 요청 → 첫 `response.output_text.delta` (= reasoning 종료 후 첫 가시 텍스트) | `t(first text delta) − t(request start)` |
| **GAP** | TTFT − TTFB ≈ 서버측 thinking(reasoning) 시간 | 파생 |

> reasoning 모델은 `response.created`(ack)를 먼저 보내고, 숨겨진 chain-of-thought 생성 후 **그 다음에** 첫 텍스트 delta를 스트리밍한다. `include:["reasoning.encrypted_content"]`로 reasoning은 암호화되어 텍스트 delta로 노출되지 않으므로, 첫 `output_text.delta`가 곧 "thinking 이후 첫 text"이다.

---

## 3. 요청 파라미터

사용자 제공 body를 `extra_body`로 그대로 재현:

```python
client.responses.create(
    model=<region별 가용 모델>,
    input=<~55.8k 토큰 컨텍스트 + 고정 질문>,   # 호출 간 고정 → prompt cache
    instructions=<고정>,
    max_output_tokens=4096,
    stream=True,
    extra_body={
        "text":   {"format": {"type": "text"}, "verbosity": "low"},
        "reasoning": {"effort": "medium"},
        "include": ["reasoning.encrypted_content"],
        "store": False,
        "prompt_cache_retention": "24h",
    },
)
```

- **input ≈ 55,839 토큰** (사용자 시나리오 55,066에 근접). 워밍업 1회로 캐시 선점.
- 실측 `cached_tokens`는 호출마다 **0 / 38,249 / 55,657 / 55,785** 등으로 변동 — Mantle prompt cache는 best-effort.
- 리전별 가용: us-east-1/us-east-2 → gpt-5.4·gpt-5.5, **us-west-2 → gpt-5.4만**.
- `tools` 미포함 (제공되지 않음).

---

## 4. 결과 — 조합별 10회

### 4.1 us-east-1 / gpt-5.4

| run | TTFB | TTFT | GAP | reasoning_tok | cached |
|--:|--:|--:|--:|--:|--:|
|1|1,114|3,536|2,421|28|55,785|
|2|1,109|2,414|1,305|61|55,785|
|3|1,146|3,290|2,144|88|55,785|
|4|1,097|1,822|725|20|55,785|
|5|1,074|2,591|1,518|69|55,785|
|6|1,057|3,277|2,220|64|55,785|
|7|1,075|3,766|2,691|50|55,785|
|8|1,082|4,589|3,507|72|55,785|
|9|1,106|4,225|3,118|37|55,785|
|10|1,067|2,774|1,708|61|55,785|

TTFB **min 1,057 / median 1,090 / mean 1,093 / max 1,146** · TTFT **min 1,822 / median 3,284 / mean 3,228 / max 4,589** · GAP **min 725 / median 2,182 / mean 2,136 / max 3,507**

### 4.2 us-east-1 / gpt-5.5

| run | TTFB | TTFT | GAP | reasoning_tok | cached |
|--:|--:|--:|--:|--:|--:|
|1|1,116|2,461|1,346|57|55,657|
|2|1,138|4,987|3,849|51|0|
|3|1,066|4,626|3,560|62|55,657|
|4|1,165|4,716|3,552|65|55,657|
|5|1,189|2,347|1,158|0|0|
|6|1,117|2,420|1,303|61|55,657|
|7|1,075|3,221|2,146|58|55,657|
|8|1,313|3,884|2,571|59|55,657|
|9|952|4,200|3,248|36|55,657|
|10|1,083|2,232|1,148|37|55,657|

TTFB **min 952 / median 1,116 / mean 1,121 / max 1,313** · TTFT **min 2,232 / median 3,553 / mean 3,510 / max 4,987** · GAP **min 1,148 / median 2,359 / mean 2,388 / max 3,849**

### 4.3 us-east-2 / gpt-5.4

| run | TTFB | TTFT | GAP | reasoning_tok | cached |
|--:|--:|--:|--:|--:|--:|
|1|1,025|5,535|4,511|66|0|
|2|1,023|2,333|1,310|60|55,785|
|3|999|2,608|1,609|15|55,785|
|4|1,010|5,780|4,770|57|0|
|5|927|6,283|5,356|109|55,785|
|6|1,001|2,507|1,506|70|55,785|
|7|900|5,809|4,910|97|55,785|
|8|979|1,967|988|27|55,785|
|9|1,021|5,060|4,039|68|55,785|
|10|1,075|3,786|2,712|22|55,785|

TTFB **min 900 / median 1,005 / mean 996 / max 1,075** · TTFT **min 1,967 / median 4,423 / mean 4,167 / max 6,283** · GAP **min 988 / median 3,375 / mean 3,171 / max 5,356**

### 4.4 us-east-2 / gpt-5.5

| run | TTFB | TTFT | GAP | reasoning_tok | cached |
|--:|--:|--:|--:|--:|--:|
|1|998|2,459|1,461|44|55,657|
|2|857|3,890|3,033|64|0|
|3|1,022|3,174|2,152|96|55,657|
|4|1,025|2,137|1,112|57|55,657|
|5|1,014|4,547|3,533|72|55,657|
|6|1,034|4,849|3,815|74|55,657|
|7|1,016|2,259|1,243|33|0|
|8|972|2,298|1,325|69|55,657|
|9|972|4,270|3,298|43|55,657|
|10|1,028|3,848|2,820|51|55,657|

TTFB **min 857 / median 1,015 / mean 994 / max 1,034** · TTFT **min 2,137 / median 3,511 / mean 3,373 / max 4,849** · GAP **min 1,112 / median 2,486 / mean 2,379 / max 3,815**

### 4.5 us-west-2 / gpt-5.4

| run | TTFB | TTFT | GAP | reasoning_tok | cached |
|--:|--:|--:|--:|--:|--:|
|1|829|3,929|3,100|85|55,785|
|2|774|4,064|3,290|65|55,785|
|3|817|2,435|1,617|51|0|
|4|830|2,133|1,303|63|55,785|
|5|848|2,845|1,998|30|55,785|
|6|638|1,952|1,314|56|55,785|
|7|825|2,723|1,898|59|55,785|
|8|873|4,578|3,704|82|55,785|
|9|1,118|2,807|1,688|69|55,785|
|10|849|2,657|1,809|64|0|

TTFB **min 638 / median 830 / mean 840 / max 1,118** · TTFT **min 1,952 / median 2,765 / mean 3,012 / max 4,578** · GAP **min 1,303 / median 1,854 / mean 2,172 / max 3,704**

### 4.6 1P direct (api.openai.com, global) / gpt-5.4

| run | TTFB | TTFT | GAP | reasoning_tok | cached |
|--:|--:|--:|--:|--:|--:|
|1|736|1,837|1,102|89|55,552|
|2|728|1,445|717|31|55,552|
|3|407|1,242|834|65|55,552|
|4|357|1,106|749|69|55,552|
|5|1,082|2,189|1,107|54|55,552|
|6|364|1,241|876|75|55,552|
|7|412|1,261|849|74|55,552|
|8|385|989|605|34|55,552|
|9|637|1,485|847|67|55,552|
|10|351|816|465|26|55,552|

TTFB **min 351 / median 410 / mean 546 / max 1,082** · TTFT **min 816 / median 1,251 / mean 1,361 / max 2,189** · GAP **min 465 / median 841 / mean 815 / max 1,107**

> warm-up: TTFB 1,973 ms (cold TLS) → 이후 connection 재사용으로 ~350–730 ms. cached가 매 호출 55,552/55,839로 **안정적 hit** (Mantle의 0↔55k 변동과 대조).

---

## 5. 비교 분석

### 5.1 리전별 TTFB (Seoul vantage) — 가장 견고한 신호

| region | TTFB median | TTFB min | vs us-east-1 |
|---|--:|--:|--:|
| **us-west-2** | **830 ms** | 638 ms | **−260 ms** |
| us-east-2 | 1,005–1,015 ms | 857 ms | −80~90 ms |
| us-east-1 | 1,090–1,116 ms | 952 ms | (기준) |

→ TTFB는 모델과 무관하고 **리전(지리적 근접)에만 의존**. Seoul → us-west-2(서부)가 us-east(동부)보다 일관되게 ~80–270ms 빠름. **TTFB 절대값은 측정 위치 의존적**이므로, 다른 위치/in-region에서는 순위·값이 달라질 수 있음.

### 5.2 TTFT / GAP

- TTFT median 범위 2,765 ms(us-west-2 gpt-5.4) ~ 4,423 ms(us-east-2 gpt-5.4).
- 그러나 이 차이의 대부분은 **호출별 reasoning_tokens 변동**(0~109개)에서 옴 — region/model 고유 차이로 보기엔 표본(10회) 노이즈가 큼. 예: us-east-2 gpt-5.4 표본에 reasoning 97/109 토큰 호출(→TTFT 5.8/6.3s)이 끼어 median을 끌어올림.
- 안정적으로 말할 수 있는 것: **TTFT ≈ TTFB(전송) + thinking(reasoning 분량에 비례)**, 그리고 thinking이 TTFT의 절반 이상을 차지.

### 5.3 1P direct vs Bedrock Mantle (gpt-5.4, median ms)

| 경로 | TTFB | TTFT | GAP | cached 안정성 |
|---|--:|--:|--:|---|
| **1P direct (global)** | **410** | **1,251** | **841** | 안정 (≈55.5k 매번) |
| Mantle us-west-2 | 830 | 2,765 | 1,854 | 변동 (0↔55.8k) |
| Mantle us-east-1 | 1,090 | 3,284 | 2,182 | 변동 |
| Mantle us-east-2 | 1,005 | 4,423 | 3,375 | 변동 |
| **1P 대비 Mantle 배수** | 2.0–2.7× 느림 | 2.2–3.5× 느림 | 2.2–4.0× 느림 | — |

**관찰 / 추정 원인**:
- **TTFB (전송)**: 1P가 ~410ms로 Mantle 최저(us-west-2 830ms)의 절반. OpenAI global 엣지/PoP가 Seoul에서 peering·근접성이 더 좋고, 1P는 cold 이후 connection 재사용으로 ~350ms까지 떨어짐.
- **thinking GAP**: 1P median 841ms vs Mantle 1.85–3.38s. 같은 모델·같은 reasoning effort인데 1P thinking이 훨씬 빠름 → Mantle 경유 시 **추가 게이트웨이 홉 / 추론 서빙 인프라 차이**로 추정 (단정은 어려움, 더 큰 N 필요).
- **prompt cache**: 1P는 매 호출 cache hit이 안정적, Mantle은 0↔55k로 flapping → Mantle은 캐시 라우팅이 best-effort라 prefill 비용/시간 변동이 큼.
- ⚠️ 단, vantage가 Seoul 고정이고 1P는 글로벌 엔드포인트(자동 라우팅) vs Mantle은 특정 AWS 리전이라 **순수 비교는 아님**. 또한 1P/Mantle는 과금·데이터경로·거버넌스가 다른 별개 채널.

---

## 6. 분석 요약

1. **TTFB = 전송 상수, 리전 근접 의존.** 모델·추론과 무관. us-west-2가 Seoul에서 가장 빠름(≈830ms).
2. **TTFT = thinking 지배.** 첫 텍스트까지 체감 지연의 대부분은 네트워크가 아니라 추론 대기.
3. **TTFT 변동의 주원인은 reasoning 분량.** effort=medium은 입력에 따라 추론량(0~109토큰)을 동적 조절 → TTFT 분산이 큼.
4. **prompt cache는 TTFB 무영향, TTFT 약영향.** cached 0↔55,785로 변동해도 TTFB 일정.
5. **cold start 주의.** 첫(워밍업) 호출은 TLS/connection 수립으로 TTFB가 1.5~2.0s까지 튐 → 정상(재사용)에선 위 값.

---

## 7. 한계 (재현 충실도)

- 원본 `input`/`instructions`/`tools`가 가려져 있어 **합성 컨텍스트(~55.8k 토큰) + tools 미포함**으로 측정. 실제 tools 스키마·instructions는 prefill/캐시/TTFT에 영향 가능.
- **vantage point = Seoul(ap-northeast-2)**. TTFB 절대값·리전 순위는 측정 위치 의존적.
- prompt cache best-effort → cache hit/miss 변동(0↔55k).
- 표본 10회 — 분포 파악용. 운영 SLO엔 N=50+ 와 p95/p99 권장.

---

## 8. 재현 / 후속

**측정 스크립트**: [`docs/benchmarks/ttft_bench.py`](./ttft_bench.py) — 이 리포트 수치를 만든 멀티리전 스크립트 (region × 가용 모델 순차 측정).
실행: `python3 docs/benchmarks/ttft_bench.py` (사전: `pip install --user openai`, SSM `/bedrock-monitor/openai-api-key` 읽기 권한). 측정은 **순차** — 병렬화하면 contention으로 레이턴시가 왜곡되므로 금지.

**후속 제안**: ① 실제 instructions/tools로 정확 재현, ② in-region(us-east-1 내부) vantage 측정으로 네트워크 분리, ③ effort low/medium/high 비교, ④ N=50+ 로 p95/p99.
