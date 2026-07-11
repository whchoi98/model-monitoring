# TTFB / TTFT 재측정 (N=20) — 원시 측정 로그 (raw output)

`docs/benchmarks/ttft_bench_n20.py`의 전 채널(Mantle 5 + 1P 2) 실행 콘솔 출력 원본입니다.
정제된 분석은 [`2026-07-06-openai-gpt-ttfb-ttft.md`](./2026-07-06-openai-gpt-ttfb-ttft.md) 참고.

- 측정일: 2026-07-06
- vantage: ap-northeast-2 (Seoul) EC2 → Mantle 3리전 + api.openai.com(글로벌)
- input ≈ 55,839 토큰, reasoning effort=medium, verbosity=low, max_output_tokens=4096
- (channel, model) 조합당 워밍업 1회 + 측정 20회, 단일 순차 실행 (총 140 측정 호출)
- 1P는 v2.6.0 프로덕션 키(SSM `/bedrock-monitor/openai-1p-api-key`) 사용, gpt-5.4·gpt-5.5 둘 다 측정

```text

################  openai.gpt-5.4  @ mantle us-east-1  ################
warm-up: ttfb=1954.1519545018673 ttft=4619.433454237878 input_tokens=55839 cached=0 reasoning=67 err=None
run  1: TTFB= 1115.9ms  TTFT= 4621.0ms  gap= 3505.1ms  cached=0/55839  reasoning_tok=68  out=105
run  2: TTFB= 1112.0ms  TTFT= 4915.0ms  gap= 3803.0ms  cached=0/55839  reasoning_tok=62  out=104
run  3: TTFB= 1075.6ms  TTFT= 2688.8ms  gap= 1613.2ms  cached=0/55839  reasoning_tok=47  out=95
run  4: TTFB= 1115.5ms  TTFT= 4433.8ms  gap= 3318.3ms  cached=55785/55839  reasoning_tok=57  out=92
run  5: TTFB= 1143.0ms  TTFT= 3864.2ms  gap= 2721.2ms  cached=55785/55839  reasoning_tok=71  out=111
run  6: TTFB=  934.0ms  TTFT= 4065.0ms  gap= 3131.0ms  cached=0/55839  reasoning_tok=68  out=109
run  7: TTFB= 1073.8ms  TTFT= 1777.0ms  gap=  703.2ms  cached=55785/55839  reasoning_tok=21  out=58
run  8: TTFB=  907.2ms  TTFT= 2039.8ms  gap= 1132.6ms  cached=55785/55839  reasoning_tok=37  out=74
run  9: TTFB= 1119.1ms  TTFT= 3201.9ms  gap= 2082.8ms  cached=55785/55839  reasoning_tok=71  out=114
run 10: TTFB= 1091.3ms  TTFT= 3996.2ms  gap= 2904.9ms  cached=55785/55839  reasoning_tok=31  out=68
run 11: TTFB= 1193.0ms  TTFT= 2519.0ms  gap= 1326.0ms  cached=55785/55839  reasoning_tok=64  out=106
run 12: TTFB=  933.6ms  TTFT= 2851.5ms  gap= 1917.9ms  cached=55785/55839  reasoning_tok=59  out=102
run 13: TTFB= 1081.8ms  TTFT= 4892.6ms  gap= 3810.9ms  cached=55785/55839  reasoning_tok=85  out=128
run 14: TTFB= 1102.5ms  TTFT= 4404.5ms  gap= 3302.0ms  cached=55785/55839  reasoning_tok=80  out=120
run 15: TTFB=  958.3ms  TTFT= 4255.0ms  gap= 3296.7ms  cached=55785/55839  reasoning_tok=57  out=98
run 16: TTFB= 1086.0ms  TTFT= 4574.5ms  gap= 3488.6ms  cached=55785/55839  reasoning_tok=65  out=106
run 17: TTFB= 1113.3ms  TTFT= 3219.5ms  gap= 2106.2ms  cached=55785/55839  reasoning_tok=45  out=87
run 18: TTFB= 1096.8ms  TTFT= 2408.6ms  gap= 1311.8ms  cached=55785/55839  reasoning_tok=53  out=94
run 19: TTFB= 1097.4ms  TTFT= 2387.4ms  gap= 1290.0ms  cached=55785/55839  reasoning_tok=60  out=103
run 20: TTFB=  926.1ms  TTFT= 4019.3ms  gap= 3093.3ms  cached=55785/55839  reasoning_tok=49  out=90
  TTFB(ms): min   907.2 | median  1094.0 | mean  1063.8 | max  1193.0
  TTFT(ms): min  1777.0 | median  3930.2 | mean  3556.7 | max  4915.0
  GAP (ms): min   703.2 | median  2813.1 | mean  2492.9 | max  3810.9

################  openai.gpt-5.5  @ mantle us-east-1  ################
warm-up: ttfb=1110.629309900105 ttft=3844.3291997537017 input_tokens=55839 cached=0 reasoning=55 err=None
run  1: TTFB=  949.1ms  TTFT= 2743.6ms  gap= 1794.5ms  cached=55657/55839  reasoning_tok=37  out=64
run  2: TTFB= 1108.6ms  TTFT= 4926.4ms  gap= 3817.7ms  cached=55657/55839  reasoning_tok=67  out=94
run  3: TTFB= 1109.4ms  TTFT= 3925.4ms  gap= 2816.0ms  cached=55657/55839  reasoning_tok=34  out=62
run  4: TTFB=  953.4ms  TTFT= 3834.9ms  gap= 2881.5ms  cached=0/55839  reasoning_tok=0  out=25
run  5: TTFB= 1080.6ms  TTFT= 3733.8ms  gap= 2653.2ms  cached=55657/55839  reasoning_tok=60  out=94
run  6: TTFB=  966.0ms  TTFT= 1910.5ms  gap=  944.4ms  cached=0/55839  reasoning_tok=0  out=27
run  7: TTFB= 1091.1ms  TTFT= 3674.1ms  gap= 2583.0ms  cached=55657/55839  reasoning_tok=39  out=67
run  8: TTFB=  953.9ms  TTFT= 3168.6ms  gap= 2214.7ms  cached=55657/55839  reasoning_tok=68  out=95
run  9: TTFB=  950.1ms  TTFT= 3208.4ms  gap= 2258.3ms  cached=55657/55839  reasoning_tok=57  out=86
run 10: TTFB= 1102.3ms  TTFT= 3661.4ms  gap= 2559.1ms  cached=55657/55839  reasoning_tok=0  out=39
run 11: TTFB=  926.7ms  TTFT= 4436.7ms  gap= 3509.9ms  cached=55657/55839  reasoning_tok=38  out=65
run 12: TTFB=  958.4ms  TTFT= 3505.4ms  gap= 2547.1ms  cached=55657/55839  reasoning_tok=43  out=71
run 13: TTFB= 1078.8ms  TTFT= 2311.9ms  gap= 1233.1ms  cached=55657/55839  reasoning_tok=0  out=32
run 14: TTFB= 1138.8ms  TTFT= 4773.9ms  gap= 3635.1ms  cached=55657/55839  reasoning_tok=41  out=68
run 15: TTFB= 1102.2ms  TTFT= 3812.7ms  gap= 2710.5ms  cached=55657/55839  reasoning_tok=55  out=83
run 16: TTFB= 1123.8ms  TTFT= 2359.5ms  gap= 1235.7ms  cached=55657/55839  reasoning_tok=0  out=28
run 17: TTFB=  929.7ms  TTFT= 3066.6ms  gap= 2136.9ms  cached=55657/55839  reasoning_tok=53  out=78
run 18: TTFB= 1132.2ms  TTFT= 4778.8ms  gap= 3646.6ms  cached=55657/55839  reasoning_tok=66  out=93
run 19: TTFB= 1154.9ms  TTFT= 3928.3ms  gap= 2773.4ms  cached=55657/55839  reasoning_tok=60  out=87
run 20: TTFB= 1098.1ms  TTFT= 4835.5ms  gap= 3737.4ms  cached=55657/55839  reasoning_tok=66  out=93
  TTFB(ms): min   926.7 | median  1085.9 | mean  1045.4 | max  1154.9
  TTFT(ms): min  1910.5 | median  3704.0 | mean  3629.8 | max  4926.4
  GAP (ms): min   944.4 | median  2618.1 | mean  2584.4 | max  3817.7

################  openai.gpt-5.4  @ mantle us-east-2  ################
warm-up: ttfb=1528.3401543274522 ttft=5645.351071842015 input_tokens=55839 cached=0 reasoning=63 err=None
run  1: TTFB=  997.5ms  TTFT= 2897.4ms  gap= 1899.9ms  cached=0/55839  reasoning_tok=51  out=93
run  2: TTFB= 1018.1ms  TTFT= 5018.2ms  gap= 4000.1ms  cached=0/55839  reasoning_tok=101  out=143
run  3: TTFB= 1005.2ms  TTFT= 4798.6ms  gap= 3793.5ms  cached=0/55839  reasoning_tok=64  out=106
run  4: TTFB= 1038.2ms  TTFT= 2535.0ms  gap= 1496.9ms  cached=55785/55839  reasoning_tok=45  out=91
run  5: TTFB= 1025.6ms  TTFT= 4340.4ms  gap= 3314.8ms  cached=0/55839  reasoning_tok=52  out=93
run  6: TTFB= 1039.7ms  TTFT= 2192.9ms  gap= 1153.3ms  cached=55785/55839  reasoning_tok=27  out=69
run  7: TTFB= 1034.2ms  TTFT= 2844.8ms  gap= 1810.7ms  cached=0/55839  reasoning_tok=60  out=93
run  8: TTFB=  997.4ms  TTFT= 2316.0ms  gap= 1318.6ms  cached=55785/55839  reasoning_tok=58  out=101
run  9: TTFB= 1000.1ms  TTFT= 1897.8ms  gap=  897.7ms  cached=55785/55839  reasoning_tok=26  out=63
run 10: TTFB= 1057.1ms  TTFT= 4165.4ms  gap= 3108.3ms  cached=55785/55839  reasoning_tok=57  out=99
run 11: TTFB=  870.1ms  TTFT= 2585.5ms  gap= 1715.4ms  cached=55785/55839  reasoning_tok=85  out=129
run 12: TTFB=  991.1ms  TTFT= 2481.9ms  gap= 1490.8ms  cached=55785/55839  reasoning_tok=66  out=103
run 13: TTFB= 1013.8ms  TTFT= 2521.9ms  gap= 1508.1ms  cached=55785/55839  reasoning_tok=61  out=105
run 14: TTFB= 1015.2ms  TTFT= 4019.5ms  gap= 3004.2ms  cached=55785/55839  reasoning_tok=62  out=106
run 15: TTFB= 1008.7ms  TTFT= 3138.0ms  gap= 2129.3ms  cached=55785/55839  reasoning_tok=60  out=102
run 16: TTFB= 1028.0ms  TTFT= 1927.7ms  gap=  899.6ms  cached=55785/55839  reasoning_tok=25  out=63
run 17: TTFB=  994.1ms  TTFT= 3599.6ms  gap= 2605.5ms  cached=55785/55839  reasoning_tok=60  out=102
run 18: TTFB= 1016.2ms  TTFT= 4528.5ms  gap= 3512.3ms  cached=55785/55839  reasoning_tok=68  out=107
run 19: TTFB=  865.1ms  TTFT= 2368.0ms  gap= 1502.9ms  cached=55785/55839  reasoning_tok=27  out=64
run 20: TTFB=  984.1ms  TTFT= 1893.4ms  gap=  909.3ms  cached=55785/55839  reasoning_tok=27  out=64
  TTFB(ms): min   865.1 | median  1011.2 | mean  1000.0 | max  1057.1
  TTFT(ms): min  1893.4 | median  2715.2 | mean  3103.5 | max  5018.2
  GAP (ms): min   897.7 | median  1763.0 | mean  2103.6 | max  4000.1

################  openai.gpt-5.5  @ mantle us-east-2  ################
warm-up: ttfb=1003.4746322780848 ttft=4508.739126846194 input_tokens=55839 cached=0 reasoning=82 err=None
run  1: TTFB= 1000.4ms  TTFT= 3914.5ms  gap= 2914.1ms  cached=0/55839  reasoning_tok=68  out=95
run  2: TTFB=  974.9ms  TTFT= 2695.2ms  gap= 1720.3ms  cached=0/55839  reasoning_tok=61  out=91
run  3: TTFB=  866.0ms  TTFT= 2927.2ms  gap= 2061.1ms  cached=0/55839  reasoning_tok=43  out=70
run  4: TTFB= 1039.7ms  TTFT= 2491.6ms  gap= 1451.8ms  cached=0/55839  reasoning_tok=62  out=90
run  5: TTFB=  995.7ms  TTFT= 3302.2ms  gap= 2306.5ms  cached=0/55839  reasoning_tok=53  out=87
run  6: TTFB=  993.2ms  TTFT=  n/a  ms  gap=  n/a  ms  cached=None/None  reasoning_tok=None  out=None
run  7: TTFB=  389.5ms  TTFT= 3367.2ms  gap= 2977.7ms  cached=0/55839  reasoning_tok=52  out=80
run  8: TTFB=  981.7ms  TTFT= 4486.7ms  gap= 3505.0ms  cached=55657/55839  reasoning_tok=64  out=91
run  9: TTFB= 1023.1ms  TTFT= 2419.8ms  gap= 1396.7ms  cached=0/55839  reasoning_tok=52  out=89
run 10: TTFB= 1001.5ms  TTFT= 4229.4ms  gap= 3227.9ms  cached=0/55839  reasoning_tok=32  out=60
run 11: TTFB= 1000.2ms  TTFT= 3515.5ms  gap= 2515.4ms  cached=55657/55839  reasoning_tok=77  out=103
run 12: TTFB=  997.9ms  TTFT= 2103.1ms  gap= 1105.2ms  cached=55657/55839  reasoning_tok=60  out=87
run 13: TTFB=  876.3ms  TTFT= 4212.0ms  gap= 3335.6ms  cached=55657/55839  reasoning_tok=54  out=81
run 14: TTFB=  976.1ms  TTFT= 2587.2ms  gap= 1611.1ms  cached=0/55839  reasoning_tok=75  out=109
run 15: TTFB= 1000.2ms  TTFT= 2109.1ms  gap= 1108.9ms  cached=55657/55839  reasoning_tok=53  out=82
run 16: TTFB=  988.0ms  TTFT= 3987.8ms  gap= 2999.9ms  cached=0/55839  reasoning_tok=46  out=79
run 17: TTFB=  845.6ms  TTFT=  n/a  ms  gap=  n/a  ms  cached=None/None  reasoning_tok=None  out=None
run 18: TTFB=  831.5ms  TTFT= 2994.7ms  gap= 2163.2ms  cached=55657/55839  reasoning_tok=60  out=87
run 19: TTFB= 1021.9ms  TTFT= 3230.7ms  gap= 2208.8ms  cached=0/55839  reasoning_tok=52  out=86
run 20: TTFB=  846.4ms  TTFT= 2021.2ms  gap= 1174.8ms  cached=0/55839  reasoning_tok=38  out=65
  TTFB(ms): min   389.5 | median   990.6 | mean   932.5 | max  1039.7
  TTFT(ms): min  2021.2 | median  3112.7 | mean  3144.2 | max  4486.7
  GAP (ms): min  1105.2 | median  2186.0 | mean  2210.2 | max  3505.0

################  openai.gpt-5.4  @ mantle us-west-2  ################
warm-up: ttfb=1157.10483584553 ttft=3004.428865388036 input_tokens=55839 cached=0 reasoning=63 err=None
run  1: TTFB=  613.3ms  TTFT= 2833.0ms  gap= 2219.7ms  cached=0/55839  reasoning_tok=94  out=136
run  2: TTFB=  863.9ms  TTFT= 2685.2ms  gap= 1821.3ms  cached=0/55839  reasoning_tok=66  out=109
run  3: TTFB=  790.8ms  TTFT=  n/a  ms  gap=  n/a  ms  cached=None/None  reasoning_tok=None  out=None
run  4: TTFB=  264.1ms  TTFT= 3267.6ms  gap= 3003.4ms  cached=55785/55839  reasoning_tok=118  out=164
run  5: TTFB=  819.2ms  TTFT= 3234.8ms  gap= 2415.6ms  cached=0/55839  reasoning_tok=55  out=96
run  6: TTFB=  611.9ms  TTFT= 3828.4ms  gap= 3216.4ms  cached=0/55839  reasoning_tok=25  out=62
run  7: TTFB=  792.0ms  TTFT= 1906.2ms  gap= 1114.2ms  cached=55785/55839  reasoning_tok=46  out=87
run  8: TTFB=  622.7ms  TTFT= 3936.6ms  gap= 3313.8ms  cached=0/55839  reasoning_tok=46  out=88
run  9: TTFB=  826.8ms  TTFT= 2140.3ms  gap= 1313.4ms  cached=55785/55839  reasoning_tok=30  out=67
run 10: TTFB=  818.7ms  TTFT= 2927.9ms  gap= 2109.2ms  cached=55785/55839  reasoning_tok=61  out=96
run 11: TTFB=  828.5ms  TTFT= 2825.6ms  gap= 1997.1ms  cached=0/55839  reasoning_tok=28  out=65
run 12: TTFB=  786.5ms  TTFT= 4207.1ms  gap= 3420.7ms  cached=0/55839  reasoning_tok=43  out=80
run 13: TTFB=  619.4ms  TTFT= 1947.0ms  gap= 1327.6ms  cached=55785/55839  reasoning_tok=62  out=98
run 14: TTFB= 1004.5ms  TTFT= 5208.0ms  gap= 4203.5ms  cached=0/55839  reasoning_tok=91  out=131
run 15: TTFB=  794.2ms  TTFT= 2597.3ms  gap= 1803.1ms  cached=0/55839  reasoning_tok=63  out=101
run 16: TTFB=  610.9ms  TTFT= 2525.4ms  gap= 1914.5ms  cached=55785/55839  reasoning_tok=68  out=119
run 17: TTFB=  785.7ms  TTFT= 3983.3ms  gap= 3197.6ms  cached=0/55839  reasoning_tok=70  out=114
run 18: TTFB=  612.1ms  TTFT= 1902.6ms  gap= 1290.5ms  cached=55785/55839  reasoning_tok=56  out=89
run 19: TTFB=  792.2ms  TTFT= 3882.6ms  gap= 3090.4ms  cached=55785/55839  reasoning_tok=52  out=94
run 20: TTFB=  620.2ms  TTFT= 2142.3ms  gap= 1522.1ms  cached=55785/55839  reasoning_tok=69  out=114
  TTFB(ms): min   264.1 | median   788.6 | mean   723.9 | max  1004.5
  TTFT(ms): min  1902.6 | median  2833.0 | mean  3051.6 | max  5208.0
  GAP (ms): min  1114.2 | median  2109.2 | mean  2331.3 | max  4203.5

################  gpt-5.4  @ 1P (global)  ################
warm-up: ttfb=890.3909344226122 ttft=1555.7223139330745 input_tokens=55839 cached=0 reasoning=27 err=None
run  1: TTFB=  717.9ms  TTFT= 1269.8ms  gap=  551.9ms  cached=55552/55839  reasoning_tok=28  out=65
run  2: TTFB=  436.8ms  TTFT= 1380.7ms  gap=  943.9ms  cached=55552/55839  reasoning_tok=25  out=60
run  3: TTFB=  401.5ms  TTFT= 2457.9ms  gap= 2056.4ms  cached=55552/55839  reasoning_tok=188  out=236
run  4: TTFB=  353.6ms  TTFT= 1509.0ms  gap= 1155.4ms  cached=55552/55839  reasoning_tok=37  out=74
run  5: TTFB=  388.3ms  TTFT=  807.6ms  gap=  419.3ms  cached=55552/55839  reasoning_tok=15  out=53
run  6: TTFB=  570.5ms  TTFT= 1340.9ms  gap=  770.4ms  cached=55552/55839  reasoning_tok=54  out=87
run  7: TTFB=  508.3ms  TTFT= 1496.7ms  gap=  988.4ms  cached=55552/55839  reasoning_tok=79  out=124
run  8: TTFB=  662.4ms  TTFT= 1379.3ms  gap=  717.0ms  cached=55552/55839  reasoning_tok=27  out=73
run  9: TTFB=  402.7ms  TTFT=  852.3ms  gap=  449.7ms  cached=55552/55839  reasoning_tok=28  out=65
run 10: TTFB=  383.3ms  TTFT= 1139.2ms  gap=  755.9ms  cached=55552/55839  reasoning_tok=64  out=98
run 11: TTFB=  342.7ms  TTFT= 1199.3ms  gap=  856.7ms  cached=55552/55839  reasoning_tok=60  out=107
run 12: TTFB= 1700.1ms  TTFT= 2666.8ms  gap=  966.7ms  cached=55552/55839  reasoning_tok=70  out=102
run 13: TTFB=  336.8ms  TTFT= 1198.8ms  gap=  862.0ms  cached=55552/55839  reasoning_tok=51  out=99
run 14: TTFB=  355.1ms  TTFT= 1121.8ms  gap=  766.6ms  cached=55552/55839  reasoning_tok=59  out=96
run 15: TTFB=  376.0ms  TTFT= 1284.5ms  gap=  908.5ms  cached=55552/55839  reasoning_tok=32  out=69
run 16: TTFB=  380.9ms  TTFT= 2807.8ms  gap= 2427.0ms  cached=55552/55839  reasoning_tok=65  out=104
run 17: TTFB=  366.9ms  TTFT=  761.7ms  gap=  394.8ms  cached=55552/55839  reasoning_tok=18  out=60
run 18: TTFB=  376.9ms  TTFT=  860.3ms  gap=  483.4ms  cached=55552/55839  reasoning_tok=15  out=56
run 19: TTFB=  328.3ms  TTFT= 1602.1ms  gap= 1273.7ms  cached=55552/55839  reasoning_tok=106  out=149
run 20: TTFB=  334.8ms  TTFT= 1318.0ms  gap=  983.2ms  cached=55552/55839  reasoning_tok=53  out=94
  TTFB(ms): min   328.3 | median   382.1 | mean   486.2 | max  1700.1
  TTFT(ms): min   761.7 | median  1301.2 | mean  1422.7 | max  2807.8
  GAP (ms): min   394.8 | median   859.3 | mean   936.5 | max  2427.0

################  gpt-5.5  @ 1P (global)  ################
warm-up: ttfb=371.77411653101444 ttft=2243.1195322424173 input_tokens=55839 cached=0 reasoning=41 err=None
run  1: TTFB=  385.0ms  TTFT= 2471.3ms  gap= 2086.3ms  cached=55552/55839  reasoning_tok=57  out=85
run  2: TTFB=  370.7ms  TTFT= 2701.9ms  gap= 2331.2ms  cached=55552/55839  reasoning_tok=68  out=96
run  3: TTFB=  345.3ms  TTFT= 4096.9ms  gap= 3751.6ms  cached=55552/55839  reasoning_tok=56  out=92
run  4: TTFB=  375.8ms  TTFT= 3585.4ms  gap= 3209.6ms  cached=55552/55839  reasoning_tok=63  out=90
run  5: TTFB=  360.5ms  TTFT= 2220.9ms  gap= 1860.4ms  cached=55552/55839  reasoning_tok=43  out=70
run  6: TTFB=  354.0ms  TTFT= 2849.0ms  gap= 2495.0ms  cached=55552/55839  reasoning_tok=65  out=93
run  7: TTFB=  350.3ms  TTFT= 2919.1ms  gap= 2568.8ms  cached=55552/55839  reasoning_tok=65  out=95
run  8: TTFB=  367.4ms  TTFT= 1640.3ms  gap= 1273.0ms  cached=55552/55839  reasoning_tok=27  out=53
run  9: TTFB=  370.5ms  TTFT= 2996.2ms  gap= 2625.7ms  cached=55552/55839  reasoning_tok=56  out=84
run 10: TTFB=  415.7ms  TTFT= 2279.2ms  gap= 1863.5ms  cached=55552/55839  reasoning_tok=37  out=66
run 11: TTFB=  360.5ms  TTFT= 2112.8ms  gap= 1752.3ms  cached=55552/55839  reasoning_tok=59  out=88
run 12: TTFB=  373.7ms  TTFT= 2425.7ms  gap= 2052.0ms  cached=55552/55839  reasoning_tok=55  out=84
run 13: TTFB=  335.5ms  TTFT= 3049.8ms  gap= 2714.3ms  cached=55552/55839  reasoning_tok=63  out=90
run 14: TTFB=  343.3ms  TTFT= 2116.3ms  gap= 1773.0ms  cached=55552/55839  reasoning_tok=54  out=81
run 15: TTFB=  345.9ms  TTFT= 2225.2ms  gap= 1879.2ms  cached=55552/55839  reasoning_tok=65  out=93
run 16: TTFB=  397.2ms  TTFT= 2315.5ms  gap= 1918.2ms  cached=55552/55839  reasoning_tok=59  out=87
run 17: TTFB=  343.5ms  TTFT= 2708.6ms  gap= 2365.2ms  cached=55552/55839  reasoning_tok=36  out=63
run 18: TTFB=  378.1ms  TTFT= 2090.4ms  gap= 1712.3ms  cached=55552/55839  reasoning_tok=51  out=80
run 19: TTFB=  425.3ms  TTFT= 2213.7ms  gap= 1788.4ms  cached=55552/55839  reasoning_tok=75  out=106
run 20: TTFB=  352.9ms  TTFT= 2335.7ms  gap= 1982.8ms  cached=55552/55839  reasoning_tok=59  out=91
  TTFB(ms): min   335.5 | median   363.9 | mean   367.6 | max   425.3
  TTFT(ms): min  1640.3 | median  2380.7 | mean  2567.7 | max  4096.9
  GAP (ms): min  1273.0 | median  2017.4 | mean  2200.1 | max  3751.6

================  SUMMARY MATRIX (median ms, N=20)  ================
channel            model                TTFB     TTFT      GAP
mantle us-east-1   openai.gpt-5.4       1094     3930     2813
mantle us-east-1   openai.gpt-5.5       1086     3704     2618
mantle us-east-2   openai.gpt-5.4       1011     2715     1763
mantle us-east-2   openai.gpt-5.5        991     3113     2186
mantle us-west-2   openai.gpt-5.4        789     2833     2109
1P (global)        gpt-5.4               382     1301      859
1P (global)        gpt-5.5               364     2381     2017
```
