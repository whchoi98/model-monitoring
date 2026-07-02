# TTFB / TTFT 벤치마크 — 원시 측정 로그 (raw output)

`docs/benchmarks/ttft_bench.py`의 전 리전 실행 콘솔 출력 원본입니다.
정제된 분석은 [`2026-06-26-openai-gpt-ttfb-ttft.md`](./2026-06-26-openai-gpt-ttfb-ttft.md) 참고.

- 측정일: 2026-06-26
- vantage: ap-northeast-2 (Seoul) EC2 → 각 리전 Bedrock Mantle 엔드포인트
- input ≈ 55,839 토큰, reasoning effort=medium, verbosity=low, max_output_tokens=4096
- (region, model) 조합당 워밍업 1회 + 측정 10회, 단일 순차 실행

```text
################  openai.gpt-5.4  @ us-east-1  ################
warm-up: ttfb=1946.8616843223572 ttft=3015.875766053796 input_tokens=55839 cached=55785 reasoning=47 err=None
run  1: TTFB= 1114.2ms  TTFT= 3535.5ms  gap= 2421.3ms  cached=55785/55839  reasoning_tok=28  out=65
run  2: TTFB= 1108.9ms  TTFT= 2414.3ms  gap= 1305.4ms  cached=55785/55839  reasoning_tok=61  out=103
run  3: TTFB= 1146.1ms  TTFT= 3290.2ms  gap= 2144.1ms  cached=55785/55839  reasoning_tok=88  out=130
run  4: TTFB= 1097.1ms  TTFT= 1821.7ms  gap=  724.6ms  cached=55785/55839  reasoning_tok=20  out=62
run  5: TTFB= 1073.6ms  TTFT= 2591.3ms  gap= 1517.6ms  cached=55785/55839  reasoning_tok=69  out=106
run  6: TTFB= 1056.6ms  TTFT= 3276.8ms  gap= 2220.2ms  cached=55785/55839  reasoning_tok=64  out=106
run  7: TTFB= 1074.9ms  TTFT= 3766.2ms  gap= 2691.3ms  cached=55785/55839  reasoning_tok=50  out=94
run  8: TTFB= 1082.0ms  TTFT= 4589.1ms  gap= 3507.1ms  cached=55785/55839  reasoning_tok=72  out=116
run  9: TTFB= 1106.3ms  TTFT= 4224.6ms  gap= 3118.2ms  cached=55785/55839  reasoning_tok=37  out=74
run 10: TTFB= 1066.5ms  TTFT= 2774.0ms  gap= 1707.5ms  cached=55785/55839  reasoning_tok=61  out=94
  TTFB(ms): min  1056.6 | median  1089.6 | mean  1092.6 | max  1146.1
  TTFT(ms): min  1821.7 | median  3283.5 | mean  3228.4 | max  4589.1
  GAP (ms): min   724.6 | median  2182.2 | mean  2135.7 | max  3507.1

################  openai.gpt-5.5  @ us-east-1  ################
warm-up: ttfb=1114.3514197319746 ttft=3357.6289722695947 input_tokens=55839 cached=38249 reasoning=32 err=None
run  1: TTFB= 1115.5ms  TTFT= 2461.3ms  gap= 1345.8ms  cached=55657/55839  reasoning_tok=57  out=85
run  2: TTFB= 1137.9ms  TTFT= 4986.7ms  gap= 3848.7ms  cached=0/55839  reasoning_tok=51  out=82
run  3: TTFB= 1066.3ms  TTFT= 4626.2ms  gap= 3560.0ms  cached=55657/55839  reasoning_tok=62  out=91
run  4: TTFB= 1165.0ms  TTFT= 4716.4ms  gap= 3551.5ms  cached=55657/55839  reasoning_tok=65  out=97
run  5: TTFB= 1188.9ms  TTFT= 2347.2ms  gap= 1158.3ms  cached=0/55839  reasoning_tok=0  out=25
run  6: TTFB= 1116.6ms  TTFT= 2419.9ms  gap= 1303.3ms  cached=55657/55839  reasoning_tok=61  out=88
run  7: TTFB= 1074.9ms  TTFT= 3221.2ms  gap= 2146.3ms  cached=55657/55839  reasoning_tok=58  out=89
run  8: TTFB= 1313.0ms  TTFT= 3884.1ms  gap= 2571.1ms  cached=55657/55839  reasoning_tok=59  out=95
run  9: TTFB=  951.8ms  TTFT= 4200.3ms  gap= 3248.4ms  cached=55657/55839  reasoning_tok=36  out=67
run 10: TTFB= 1083.4ms  TTFT= 2231.8ms  gap= 1148.3ms  cached=55657/55839  reasoning_tok=37  out=64
  TTFB(ms): min   951.8 | median  1116.1 | mean  1121.3 | max  1313.0
  TTFT(ms): min  2231.8 | median  3552.6 | mean  3509.5 | max  4986.7
  GAP (ms): min  1148.3 | median  2358.7 | mean  2388.2 | max  3848.7

################  openai.gpt-5.4  @ us-east-2  ################
warm-up: ttfb=1498.1985725462437 ttft=3113.8663459569216 input_tokens=55839 cached=55785 reasoning=66 err=None
run  1: TTFB= 1024.6ms  TTFT= 5535.0ms  gap= 4510.5ms  cached=0/55839  reasoning_tok=66  out=108
run  2: TTFB= 1023.2ms  TTFT= 2333.1ms  gap= 1309.9ms  cached=55785/55839  reasoning_tok=60  out=102
run  3: TTFB=  998.9ms  TTFT= 2607.9ms  gap= 1609.0ms  cached=55785/55839  reasoning_tok=15  out=52
run  4: TTFB= 1009.6ms  TTFT= 5779.6ms  gap= 4769.9ms  cached=0/55839  reasoning_tok=57  out=100
run  5: TTFB=  926.8ms  TTFT= 6283.1ms  gap= 5356.3ms  cached=55785/55839  reasoning_tok=109  out=150
run  6: TTFB= 1000.8ms  TTFT= 2506.7ms  gap= 1505.9ms  cached=55785/55839  reasoning_tok=70  out=116
run  7: TTFB=  899.6ms  TTFT= 5809.4ms  gap= 4909.8ms  cached=55785/55839  reasoning_tok=97  out=138
run  8: TTFB=  979.2ms  TTFT= 1967.1ms  gap=  987.9ms  cached=55785/55839  reasoning_tok=27  out=69
run  9: TTFB= 1021.3ms  TTFT= 5060.1ms  gap= 4038.8ms  cached=55785/55839  reasoning_tok=68  out=110
run 10: TTFB= 1074.8ms  TTFT= 3786.4ms  gap= 2711.7ms  cached=55785/55839  reasoning_tok=22  out=59
  TTFB(ms): min   899.6 | median  1005.2 | mean   995.9 | max  1074.8
  TTFT(ms): min  1967.1 | median  4423.3 | mean  4166.9 | max  6283.1
  GAP (ms): min   987.9 | median  3375.2 | mean  3171.0 | max  5356.3

################  openai.gpt-5.5  @ us-east-2  ################
warm-up: ttfb=895.9629451856017 ttft=2809.6836041659117 input_tokens=55839 cached=55657 reasoning=54 err=None
run  1: TTFB=  997.9ms  TTFT= 2459.3ms  gap= 1461.4ms  cached=55657/55839  reasoning_tok=44  out=75
run  2: TTFB=  856.8ms  TTFT= 3890.0ms  gap= 3033.3ms  cached=0/55839  reasoning_tok=64  out=100
run  3: TTFB= 1022.1ms  TTFT= 3174.3ms  gap= 2152.2ms  cached=55657/55839  reasoning_tok=96  out=126
run  4: TTFB= 1024.9ms  TTFT= 2136.9ms  gap= 1112.0ms  cached=55657/55839  reasoning_tok=57  out=93
run  5: TTFB= 1013.9ms  TTFT= 4547.3ms  gap= 3533.4ms  cached=55657/55839  reasoning_tok=72  out=100
run  6: TTFB= 1034.2ms  TTFT= 4849.4ms  gap= 3815.2ms  cached=55657/55839  reasoning_tok=74  out=106
run  7: TTFB= 1016.0ms  TTFT= 2259.0ms  gap= 1243.0ms  cached=0/55839  reasoning_tok=33  out=59
run  8: TTFB=  972.3ms  TTFT= 2297.7ms  gap= 1325.4ms  cached=55657/55839  reasoning_tok=69  out=100
run  9: TTFB=  971.8ms  TTFT= 4269.9ms  gap= 3298.0ms  cached=55657/55839  reasoning_tok=43  out=70
run 10: TTFB= 1028.3ms  TTFT= 3848.3ms  gap= 2820.1ms  cached=55657/55839  reasoning_tok=51  out=79
  TTFB(ms): min   856.8 | median  1014.9 | mean   993.8 | max  1034.2
  TTFT(ms): min  2136.9 | median  3511.3 | mean  3373.2 | max  4849.4
  GAP (ms): min  1112.0 | median  2486.1 | mean  2379.4 | max  3815.2

################  openai.gpt-5.4  @ us-west-2  ################
warm-up: ttfb=1106.7879535257816 ttft=3124.9639438465238 input_tokens=55839 cached=0 reasoning=69 err=None
run  1: TTFB=  829.3ms  TTFT= 3928.9ms  gap= 3099.7ms  cached=55785/55839  reasoning_tok=85  out=127
run  2: TTFB=  774.1ms  TTFT= 4063.6ms  gap= 3289.5ms  cached=55785/55839  reasoning_tok=65  out=101
run  3: TTFB=  817.3ms  TTFT= 2434.7ms  gap= 1617.3ms  cached=0/55839  reasoning_tok=51  out=89
run  4: TTFB=  830.1ms  TTFT= 2133.4ms  gap= 1303.3ms  cached=55785/55839  reasoning_tok=63  out=99
run  5: TTFB=  847.5ms  TTFT= 2845.4ms  gap= 1997.9ms  cached=55785/55839  reasoning_tok=30  out=66
run  6: TTFB=  638.1ms  TTFT= 1951.7ms  gap= 1313.6ms  cached=55785/55839  reasoning_tok=56  out=96
run  7: TTFB=  824.9ms  TTFT= 2723.3ms  gap= 1898.4ms  cached=55785/55839  reasoning_tok=59  out=102
run  8: TTFB=  873.4ms  TTFT= 4577.7ms  gap= 3704.3ms  cached=55785/55839  reasoning_tok=82  out=122
run  9: TTFB= 1118.3ms  TTFT= 2806.7ms  gap= 1688.4ms  cached=55785/55839  reasoning_tok=69  out=112
run 10: TTFB=  848.5ms  TTFT= 2657.3ms  gap= 1808.7ms  cached=0/55839  reasoning_tok=64  out=107
  TTFB(ms): min   638.1 | median   829.7 | mean   840.1 | max  1118.3
  TTFT(ms): min  1951.7 | median  2765.0 | mean  3012.3 | max  4577.7
  GAP (ms): min  1303.3 | median  1853.6 | mean  2172.1 | max  3704.3

================  SUMMARY MATRIX (median ms)  ================
region      model                TTFB     TTFT      GAP
us-east-1   openai.gpt-5.4       1090     3284     2182
us-east-1   openai.gpt-5.5       1116     3553     2359
us-east-2   openai.gpt-5.4       1005     4423     3375
us-east-2   openai.gpt-5.5       1015     3511     2486
us-west-2   openai.gpt-5.4        830     2765     1854
```

---

## 1P direct (api.openai.com, global) — gpt-5.4 raw log

별도 1P OpenAI 키(`sk-proj-…`, 측정 후 폐기)로 gpt-5.4만 측정. 동일 방법론 (~55.8k 토큰, 동일 body, 워밍업 1회 + 10회).

```text
################  1P (api.openai.com, global)  /  gpt-5.4  ################
warm-up: ttfb=1973.3113022521138 ttft=2581.731771118939 input_tokens=55839 cached=0 reasoning=33 err=None
run  1: TTFB=  735.5ms  TTFT= 1837.1ms  gap= 1101.6ms  cached=55552/55839  reasoning_tok=89  out=131
run  2: TTFB=  728.1ms  TTFT= 1445.1ms  gap=  717.1ms  cached=55552/55839  reasoning_tok=31  out=68
run  3: TTFB=  407.4ms  TTFT= 1241.6ms  gap=  834.1ms  cached=55552/55839  reasoning_tok=65  out=102
run  4: TTFB=  356.5ms  TTFT= 1105.6ms  gap=  749.1ms  cached=55552/55839  reasoning_tok=69  out=117
run  5: TTFB= 1081.6ms  TTFT= 2188.9ms  gap= 1107.3ms  cached=55552/55839  reasoning_tok=54  out=93
run  6: TTFB=  364.4ms  TTFT= 1240.8ms  gap=  876.4ms  cached=55552/55839  reasoning_tok=75  out=109
run  7: TTFB=  411.9ms  TTFT= 1261.1ms  gap=  849.3ms  cached=55552/55839  reasoning_tok=74  out=116
run  8: TTFB=  384.5ms  TTFT=  989.3ms  gap=  604.8ms  cached=55552/55839  reasoning_tok=34  out=71
run  9: TTFB=  637.4ms  TTFT= 1484.5ms  gap=  847.1ms  cached=55552/55839  reasoning_tok=67  out=107
run 10: TTFB=  350.9ms  TTFT=  815.8ms  gap=  464.9ms  cached=55552/55839  reasoning_tok=26  out=57
  TTFB(ms): min   350.9 | median   409.7 | mean   545.8 | max  1081.6
  TTFT(ms): min   815.8 | median  1251.4 | mean  1361.0 | max  2188.9
  GAP (ms): min   464.9 | median   840.6 | mean   815.2 | max  1107.3
```
