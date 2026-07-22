# 2026-07-21 Mantle 5채널 재측정 — 원시 출력

```

################  openai.gpt-5.4  @ mantle us-east-1  ################
warm-up: ttfb=1911.6504834964871 ttft=3026.9741313531995 input_tokens=55839 cached=0 reasoning=65 err=None
run  1: TTFB= 1074.8ms  TTFT= 2355.5ms  gap= 1280.7ms  cached=0/55839  reasoning_tok=63  out=104
run  2: TTFB= 1084.5ms  TTFT= 2267.6ms  gap= 1183.1ms  cached=0/55839  reasoning_tok=85  out=127
run  3: TTFB= 1077.1ms  TTFT= 2456.4ms  gap= 1379.3ms  cached=0/55839  reasoning_tok=101  out=142
run  4: TTFB= 1074.7ms  TTFT= 2262.4ms  gap= 1187.8ms  cached=55646/55839  reasoning_tok=92  out=130
run  5: TTFB= 1084.0ms  TTFT= 1854.3ms  gap=  770.3ms  cached=55646/55839  reasoning_tok=59  out=100
run  6: TTFB=  897.4ms  TTFT= 1669.2ms  gap=  771.8ms  cached=55646/55839  reasoning_tok=61  out=104
run  7: TTFB=  919.5ms  TTFT= 1986.4ms  gap= 1066.9ms  cached=55646/55839  reasoning_tok=63  out=102
run  8: TTFB=  887.0ms  TTFT= 1864.2ms  gap=  977.2ms  cached=55646/55839  reasoning_tok=87  out=125
run  9: TTFB=  907.7ms  TTFT= 1776.6ms  gap=  868.9ms  cached=55646/55839  reasoning_tok=59  out=99
run 10: TTFB=  725.2ms  TTFT= 1384.3ms  gap=  659.1ms  cached=55646/55839  reasoning_tok=26  out=71
run 11: TTFB=  872.9ms  TTFT= 2042.3ms  gap= 1169.4ms  cached=55646/55839  reasoning_tok=68  out=114
run 12: TTFB=  885.0ms  TTFT= 2852.0ms  gap= 1967.1ms  cached=55646/55839  reasoning_tok=110  out=143
run 13: TTFB= 1054.4ms  TTFT= 1831.2ms  gap=  776.8ms  cached=55646/55839  reasoning_tok=58  out=95
run 14: TTFB=  900.0ms  TTFT= 2201.0ms  gap= 1301.0ms  cached=55646/55839  reasoning_tok=63  out=106
run 15: TTFB=  739.6ms  TTFT= 1701.1ms  gap=  961.5ms  cached=55646/55839  reasoning_tok=69  out=106
run 16: TTFB=  938.2ms  TTFT= 1919.8ms  gap=  981.6ms  cached=55646/55839  reasoning_tok=82  out=120
run 17: TTFB=  891.8ms  TTFT= 2177.5ms  gap= 1285.7ms  cached=55646/55839  reasoning_tok=96  out=143
run 18: TTFB= 1075.1ms  TTFT= 2048.4ms  gap=  973.2ms  cached=55646/55839  reasoning_tok=67  out=104
run 19: TTFB= 1095.6ms  TTFT= 2483.4ms  gap= 1387.8ms  cached=55646/55839  reasoning_tok=117  out=160
run 20: TTFB= 1085.7ms  TTFT= 2135.2ms  gap= 1049.5ms  cached=55646/55839  reasoning_tok=60  out=100
  TTFB(ms): min   725.2 | median   928.8 | mean   963.5 | max  1095.6
  TTFT(ms): min  1384.3 | median  2045.3 | mean  2063.4 | max  2852.0
  GAP (ms): min   659.1 | median  1058.2 | mean  1099.9 | max  1967.1

################  openai.gpt-5.5  @ mantle us-east-1  ################
warm-up: ttfb=966.0863019526005 ttft=2373.962316662073 input_tokens=55839 cached=0 reasoning=59 err=None
run  1: TTFB= 1059.0ms  TTFT= 2868.6ms  gap= 1809.6ms  cached=0/55839  reasoning_tok=73  out=101
run  2: TTFB= 1037.4ms  TTFT= 2411.9ms  gap= 1374.4ms  cached=0/55839  reasoning_tok=52  out=80
run  3: TTFB= 1093.8ms  TTFT= 2610.6ms  gap= 1516.7ms  cached=55646/55839  reasoning_tok=95  out=123
run  4: TTFB= 1103.6ms  TTFT= 2313.3ms  gap= 1209.7ms  cached=0/55839  reasoning_tok=47  out=77
run  5: TTFB=  931.8ms  TTFT= 2047.0ms  gap= 1115.2ms  cached=55646/55839  reasoning_tok=47  out=78
run  6: TTFB=  916.3ms  TTFT= 2104.8ms  gap= 1188.5ms  cached=55646/55839  reasoning_tok=53  out=81
run  7: TTFB=  897.5ms  TTFT= 1969.0ms  gap= 1071.4ms  cached=55646/55839  reasoning_tok=50  out=77
run  8: TTFB= 1047.4ms  TTFT= 2300.5ms  gap= 1253.0ms  cached=55646/55839  reasoning_tok=75  out=102
run  9: TTFB= 1050.3ms  TTFT= 2376.6ms  gap= 1326.3ms  cached=55646/55839  reasoning_tok=90  out=122
run 10: TTFB= 1084.5ms  TTFT= 2368.6ms  gap= 1284.1ms  cached=55646/55839  reasoning_tok=51  out=79
run 11: TTFB= 1068.0ms  TTFT= 2394.0ms  gap= 1326.0ms  cached=55646/55839  reasoning_tok=63  out=94
run 12: TTFB=  914.8ms  TTFT= 2510.3ms  gap= 1595.5ms  cached=0/55839  reasoning_tok=72  out=101
run 13: TTFB= 1054.8ms  TTFT= 2158.1ms  gap= 1103.3ms  cached=55646/55839  reasoning_tok=51  out=78
run 14: TTFB= 1117.4ms  TTFT= 2555.2ms  gap= 1437.8ms  cached=0/55839  reasoning_tok=62  out=90
run 15: TTFB= 1063.7ms  TTFT= 2567.3ms  gap= 1503.6ms  cached=55646/55839  reasoning_tok=80  out=108
run 16: TTFB= 1032.4ms  TTFT= 2140.1ms  gap= 1107.8ms  cached=55646/55839  reasoning_tok=39  out=67
run 17: TTFB= 1069.2ms  TTFT= 2667.6ms  gap= 1598.4ms  cached=0/55839  reasoning_tok=60  out=89
run 18: TTFB= 1084.3ms  TTFT= 2104.2ms  gap= 1020.0ms  cached=55646/55839  reasoning_tok=44  out=74
run 19: TTFB= 1060.7ms  TTFT= 1974.8ms  gap=  914.1ms  cached=55646/55839  reasoning_tok=37  out=64
run 20: TTFB=  889.3ms  TTFT= 2009.5ms  gap= 1120.2ms  cached=55646/55839  reasoning_tok=55  out=84
  TTFB(ms): min   889.3 | median  1056.9 | mean  1028.8 | max  1117.4
  TTFT(ms): min  1969.0 | median  2340.9 | mean  2322.6 | max  2868.6
  GAP (ms): min   914.1 | median  1268.6 | mean  1293.8 | max  1809.6

################  openai.gpt-5.4  @ mantle us-east-2  ################
warm-up: ttfb=2730.1691798493266 ttft=3842.766151763499 input_tokens=55839 cached=0 reasoning=33 err=None
run  1: TTFB= 1130.8ms  TTFT= 5499.9ms  gap= 4369.2ms  cached=55646/55839  reasoning_tok=68  out=109
run  2: TTFB= 5856.6ms  TTFT= 6859.2ms  gap= 1002.5ms  cached=55646/55839  reasoning_tok=63  out=106
run  3: TTFB=13902.6ms  TTFT=14882.0ms  gap=  979.5ms  cached=55646/55839  reasoning_tok=60  out=93
run  4: TTFB= 3012.5ms  TTFT= 3818.1ms  gap=  805.5ms  cached=55646/55839  reasoning_tok=65  out=103
run  5: TTFB= 5219.9ms  TTFT= 7191.4ms  gap= 1971.5ms  cached=55646/55839  reasoning_tok=200  out=241
run  6: TTFB= 4006.0ms  TTFT= 5219.5ms  gap= 1213.5ms  cached=55646/55839  reasoning_tok=91  out=133
run  7: TTFB= 2970.9ms  TTFT= 4143.3ms  gap= 1172.3ms  cached=55646/55839  reasoning_tok=77  out=122
run  8: TTFB= 4130.5ms  TTFT= 5437.3ms  gap= 1306.8ms  cached=55646/55839  reasoning_tok=93  out=134
run  9: TTFB= 1198.9ms  TTFT= 2403.4ms  gap= 1204.6ms  cached=0/55839  reasoning_tok=63  out=97
run 10: TTFB=  963.3ms  TTFT= 1964.1ms  gap= 1000.8ms  cached=55646/55839  reasoning_tok=51  out=84
run 11: TTFB= 8505.0ms  TTFT= 9501.0ms  gap=  996.0ms  cached=55646/55839  reasoning_tok=62  out=108
run 12: TTFB= 8296.1ms  TTFT= 9277.8ms  gap=  981.7ms  cached=55646/55839  reasoning_tok=79  out=123
run 13: TTFB= 6001.1ms  TTFT= 9808.6ms  gap= 3807.6ms  cached=55646/55839  reasoning_tok=98  out=140
run 14: TTFB= 1156.0ms  TTFT= 2318.5ms  gap= 1162.5ms  cached=55646/55839  reasoning_tok=31  out=68
run 15: TTFB= 1330.4ms  TTFT= 2326.9ms  gap=  996.5ms  cached=55646/55839  reasoning_tok=65  out=102
run 16: TTFB= 1583.5ms  TTFT= 2751.1ms  gap= 1167.5ms  cached=55646/55839  reasoning_tok=96  out=131
run 17: TTFB= 7838.5ms  TTFT= 9032.1ms  gap= 1193.6ms  cached=55646/55839  reasoning_tok=97  out=139
run 18: TTFB= 5961.3ms  TTFT= 7337.7ms  gap= 1376.4ms  cached=55646/55839  reasoning_tok=90  out=132
run 19: TTFB= 2989.3ms  TTFT= 4372.5ms  gap= 1383.2ms  cached=55646/55839  reasoning_tok=113  out=150
run 20: TTFB= 1976.8ms  TTFT= 3154.3ms  gap= 1177.6ms  cached=55646/55839  reasoning_tok=102  out=147
  TTFB(ms): min   963.3 | median  3509.3 | mean  4401.5 | max 13902.6
  TTFT(ms): min  1964.1 | median  5328.4 | mean  5864.9 | max 14882.0
  GAP (ms): min   805.5 | median  1175.0 | mean  1463.4 | max  4369.2

################  openai.gpt-5.5  @ mantle us-east-2  ################
warm-up: ttfb=14219.491519965231 ttft=62571.17065321654 input_tokens=55839 cached=55646 reasoning=58 err=None
run  1: TTFB= 6132.5ms  TTFT=23577.0ms  gap=17444.5ms  cached=55646/55839  reasoning_tok=42  out=73
run  2: TTFB= 3082.2ms  TTFT= 6265.4ms  gap= 3183.2ms  cached=0/55839  reasoning_tok=41  out=69
run  3: TTFB= 1544.0ms  TTFT= 3207.8ms  gap= 1663.9ms  cached=55646/55839  reasoning_tok=68  out=97
run  4: TTFB= 2002.8ms  TTFT= 3583.0ms  gap= 1580.1ms  cached=55646/55839  reasoning_tok=64  out=99
run  5: TTFB= 8697.7ms  TTFT= 9785.6ms  gap= 1087.9ms  cached=55646/55839  reasoning_tok=39  out=67
run  6: TTFB= 8580.5ms  TTFT= 9692.9ms  gap= 1112.4ms  cached=55646/55839  reasoning_tok=35  out=60
run  7: TTFB= 1786.9ms  TTFT= 2866.1ms  gap= 1079.2ms  cached=55646/55839  reasoning_tok=53  out=81
run  8: TTFB= 9090.0ms  TTFT=10469.8ms  gap= 1379.8ms  cached=55646/55839  reasoning_tok=67  out=98
run  9: TTFB=17525.2ms  TTFT=28262.2ms  gap=10737.0ms  cached=55646/55839  reasoning_tok=63  out=91
run 10: TTFB= 1647.5ms  TTFT= 4359.6ms  gap= 2712.1ms  cached=55646/55839  reasoning_tok=44  out=71
run 11: TTFB= 2551.1ms  TTFT= 4110.3ms  gap= 1559.2ms  cached=55646/55839  reasoning_tok=60  out=88
run 12: TTFB= 1973.1ms  TTFT= 3060.1ms  gap= 1087.1ms  cached=55646/55839  reasoning_tok=35  out=61
run 13: TTFB=19521.1ms  TTFT=21228.7ms  gap= 1707.6ms  cached=55646/55839  reasoning_tok=66  out=95
run 14: TTFB= 2694.1ms  TTFT= 3866.6ms  gap= 1172.5ms  cached=55646/55839  reasoning_tok=36  out=63
run 15: TTFB= 1588.6ms  TTFT= 2864.9ms  gap= 1276.3ms  cached=55646/55839  reasoning_tok=68  out=96
run 16: TTFB= 5046.4ms  TTFT= 6364.0ms  gap= 1317.5ms  cached=55646/55839  reasoning_tok=55  out=83
run 17: TTFB=19041.9ms  TTFT=57523.9ms  gap=38482.0ms  cached=55646/55839  reasoning_tok=60  out=85
run 18: TTFB= 2212.1ms  TTFT=25022.8ms  gap=22810.7ms  cached=55646/55839  reasoning_tok=37  out=67
run 19: TTFB= 5653.0ms  TTFT= 6840.2ms  gap= 1187.3ms  cached=55646/55839  reasoning_tok=51  out=77
run 20: TTFB= 2720.1ms  TTFT=32663.8ms  gap=29943.7ms  cached=55646/55839  reasoning_tok=29  out=56
  TTFB(ms): min  1544.0 | median  2901.1 | mean  6154.5 | max 19521.1
  TTFT(ms): min  2864.9 | median  6602.1 | mean 13280.7 | max 57523.9
  GAP (ms): min  1079.2 | median  1569.7 | mean  7126.2 | max 38482.0

################  openai.gpt-5.4  @ mantle us-west-2  ################
warm-up: ttfb=1308.3417862653732 ttft=2074.0845585241914 input_tokens=55839 cached=55646 reasoning=41 err=None
run  1: TTFB=  798.8ms  TTFT= 1375.3ms  gap=  576.5ms  cached=55646/55839  reasoning_tok=33  out=70
run  2: TTFB=  718.6ms  TTFT= 1783.9ms  gap= 1065.3ms  cached=55646/55839  reasoning_tok=74  out=115
run  3: TTFB=  663.7ms  TTFT= 1696.8ms  gap= 1033.2ms  cached=55646/55839  reasoning_tok=59  out=101
run  4: TTFB=  951.1ms  TTFT= 2121.7ms  gap= 1170.6ms  cached=55646/55839  reasoning_tok=105  out=148
run  5: TTFB=  708.6ms  TTFT= 1468.2ms  gap=  759.6ms  cached=55646/55839  reasoning_tok=56  out=100
run  6: TTFB=  523.9ms  TTFT= 1504.1ms  gap=  980.2ms  cached=55646/55839  reasoning_tok=76  out=117
run  7: TTFB=  676.4ms  TTFT= 1535.8ms  gap=  859.4ms  cached=55646/55839  reasoning_tok=59  out=101
run  8: TTFB=  651.5ms  TTFT= 2760.4ms  gap= 2108.9ms  cached=55646/55839  reasoning_tok=187  out=229
run  9: TTFB=  835.6ms  TTFT= 1405.1ms  gap=  569.4ms  cached=55646/55839  reasoning_tok=28  out=66
run 10: TTFB=  656.8ms  TTFT= 1727.0ms  gap= 1070.3ms  cached=55646/55839  reasoning_tok=57  out=103
run 11: TTFB=  796.1ms  TTFT= 1903.5ms  gap= 1107.5ms  cached=55646/55839  reasoning_tok=76  out=111
run 12: TTFB=  794.9ms  TTFT= 1962.4ms  gap= 1167.5ms  cached=55646/55839  reasoning_tok=86  out=128
run 13: TTFB=  804.4ms  TTFT= 1779.9ms  gap=  975.5ms  cached=55646/55839  reasoning_tok=83  out=123
run 14: TTFB=  759.1ms  TTFT= 1632.4ms  gap=  873.3ms  cached=55646/55839  reasoning_tok=65  out=106
run 15: TTFB=  794.8ms  TTFT= 1477.9ms  gap=  683.0ms  cached=55646/55839  reasoning_tok=41  out=79
run 16: TTFB=  692.3ms  TTFT= 1557.2ms  gap=  864.9ms  cached=55646/55839  reasoning_tok=27  out=67
run 17: TTFB=  663.9ms  TTFT= 2232.9ms  gap= 1569.1ms  cached=55646/55839  reasoning_tok=159  out=196
run 18: TTFB=  766.2ms  TTFT= 1556.9ms  gap=  790.6ms  cached=55646/55839  reasoning_tok=35  out=72
run 19: TTFB=  652.4ms  TTFT= 1635.4ms  gap=  983.0ms  cached=55646/55839  reasoning_tok=69  out=113
run 20: TTFB=  504.7ms  TTFT= 1745.9ms  gap= 1241.2ms  cached=55646/55839  reasoning_tok=100  out=141
  TTFB(ms): min   504.7 | median   713.6 | mean   720.7 | max   951.1
  TTFT(ms): min  1375.3 | median  1666.1 | mean  1743.1 | max  2760.4
  GAP (ms): min   569.4 | median   981.6 | mean  1022.5 | max  2108.9

================  SUMMARY MATRIX (median ms, N=20)  ================
channel            model                TTFB     TTFT      GAP
mantle us-east-1   openai.gpt-5.4        929     2045     1058
mantle us-east-1   openai.gpt-5.5       1057     2341     1269
mantle us-east-2   openai.gpt-5.4       3509     5328     1175
mantle us-east-2   openai.gpt-5.5       2901     6602     1570
mantle us-west-2   openai.gpt-5.4        714     1666      982
```
