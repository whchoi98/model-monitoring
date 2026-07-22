# 2026-07-20 GPT-5.4 Mantle 재측정 — 원시 출력

```

################  openai.gpt-5.4  @ mantle us-east-1  ################
warm-up: ttfb=2151.391673833132 ttft=4517.475975677371 input_tokens=55839 cached=0 reasoning=102 err=None
run  1: TTFB= 1061.1ms  TTFT= 2290.1ms  gap= 1229.0ms  cached=0/55839  reasoning_tok=21  out=58
run  2: TTFB= 1098.6ms  TTFT= 3036.7ms  gap= 1938.1ms  cached=55785/55839  reasoning_tok=97  out=136
run  3: TTFB= 1079.0ms  TTFT= 2610.5ms  gap= 1531.5ms  cached=55785/55839  reasoning_tok=71  out=114
run  4: TTFB= 1135.7ms  TTFT= 2868.1ms  gap= 1732.4ms  cached=55785/55839  reasoning_tok=81  out=122
run  5: TTFB= 1067.8ms  TTFT= 2169.1ms  gap= 1101.3ms  cached=55785/55839  reasoning_tok=41  out=80
run  6: TTFB= 1081.2ms  TTFT= 2187.5ms  gap= 1106.4ms  cached=55785/55839  reasoning_tok=53  out=96
run  7: TTFB= 1136.8ms  TTFT= 3178.3ms  gap= 2041.5ms  cached=55785/55839  reasoning_tok=74  out=113
run  8: TTFB= 1074.1ms  TTFT= 2404.2ms  gap= 1330.2ms  cached=55785/55839  reasoning_tok=62  out=104
run  9: TTFB= 1064.8ms  TTFT= 2774.0ms  gap= 1709.2ms  cached=55785/55839  reasoning_tok=83  out=125
run 10: TTFB= 1052.1ms  TTFT= 2381.0ms  gap= 1328.9ms  cached=55785/55839  reasoning_tok=66  out=108
run 11: TTFB= 1062.2ms  TTFT= 2401.6ms  gap= 1339.4ms  cached=55785/55839  reasoning_tok=59  out=105
run 12: TTFB= 1080.6ms  TTFT= 2403.5ms  gap= 1322.9ms  cached=55785/55839  reasoning_tok=57  out=94
run 13: TTFB= 1055.9ms  TTFT= 2777.8ms  gap= 1721.9ms  cached=55785/55839  reasoning_tok=81  out=122
run 14: TTFB= 1067.5ms  TTFT= 2386.3ms  gap= 1318.8ms  cached=55785/55839  reasoning_tok=67  out=105
run 15: TTFB= 1061.3ms  TTFT= 2378.6ms  gap= 1317.3ms  cached=55785/55839  reasoning_tok=62  out=95
run 16: TTFB= 1151.8ms  TTFT= 3294.5ms  gap= 2142.6ms  cached=55785/55839  reasoning_tok=110  out=142
run 17: TTFB= 1093.8ms  TTFT= 2000.1ms  gap=  906.4ms  cached=55785/55839  reasoning_tok=29  out=66
run 18: TTFB= 1164.1ms  TTFT= 2514.6ms  gap= 1350.5ms  cached=55785/55839  reasoning_tok=62  out=104
run 19: TTFB= 1261.5ms  TTFT= 2561.3ms  gap= 1299.8ms  cached=55785/55839  reasoning_tok=55  out=90
run 20: TTFB= 1090.1ms  TTFT= 2614.2ms  gap= 1524.1ms  cached=55785/55839  reasoning_tok=65  out=104
  TTFB(ms): min  1052.1 | median  1079.8 | mean  1097.0 | max  1261.5
  TTFT(ms): min  2000.1 | median  2459.4 | mean  2561.6 | max  3294.5
  GAP (ms): min   906.4 | median  1334.8 | mean  1464.6 | max  2142.6

################  openai.gpt-5.4  @ mantle us-east-2  ################
warm-up: ttfb=1503.2609961926937 ttft=7503.266541287303 input_tokens=55839 cached=0 reasoning=70 err=None
run  1: TTFB=  984.7ms  TTFT= 5099.6ms  gap= 4114.9ms  cached=0/55839  reasoning_tok=76  out=114
run  2: TTFB=  997.3ms  TTFT= 3526.9ms  gap= 2529.6ms  cached=55785/55839  reasoning_tok=77  out=109
run  3: TTFB=  998.8ms  TTFT= 3297.5ms  gap= 2298.8ms  cached=55785/55839  reasoning_tok=90  out=127
run  4: TTFB=  989.7ms  TTFT= 2619.6ms  gap= 1629.9ms  cached=55785/55839  reasoning_tok=65  out=97
run  5: TTFB= 1009.5ms  TTFT= 3994.7ms  gap= 2985.2ms  cached=55785/55839  reasoning_tok=54  out=87
run  6: TTFB= 1013.4ms  TTFT= 2517.0ms  gap= 1503.5ms  cached=55785/55839  reasoning_tok=66  out=107
run  7: TTFB=  987.5ms  TTFT= 4593.0ms  gap= 3605.5ms  cached=0/55839  reasoning_tok=72  out=111
run  8: TTFB=  987.6ms  TTFT= 4386.0ms  gap= 3398.4ms  cached=55785/55839  reasoning_tok=60  out=102
run  9: TTFB=  985.8ms  TTFT= 2918.0ms  gap= 1932.2ms  cached=55785/55839  reasoning_tok=49  out=84
run 10: TTFB= 1001.2ms  TTFT= 2911.0ms  gap= 1909.8ms  cached=55785/55839  reasoning_tok=56  out=99
run 11: TTFB=  995.8ms  TTFT= 2422.6ms  gap= 1426.8ms  cached=0/55839  reasoning_tok=26  out=66
run 12: TTFB=  994.6ms  TTFT= 8119.8ms  gap= 7125.2ms  cached=55785/55839  reasoning_tok=78  out=120
run 13: TTFB=  989.5ms  TTFT= 2691.3ms  gap= 1701.8ms  cached=55785/55839  reasoning_tok=62  out=104
run 14: TTFB=  996.0ms  TTFT= 3043.3ms  gap= 2047.3ms  cached=55785/55839  reasoning_tok=64  out=109
run 15: TTFB= 1001.6ms  TTFT= 2914.5ms  gap= 1912.9ms  cached=55785/55839  reasoning_tok=64  out=104
run 16: TTFB=  852.9ms  TTFT= 4265.7ms  gap= 3412.8ms  cached=55785/55839  reasoning_tok=87  out=131
run 17: TTFB= 1014.8ms  TTFT= 5770.3ms  gap= 4755.6ms  cached=55785/55839  reasoning_tok=45  out=91
run 18: TTFB=  988.2ms  TTFT=  n/a  ms  gap=  n/a  ms  cached=None/None  reasoning_tok=None  out=None
run 19: TTFB=  990.9ms  TTFT= 8598.4ms  gap= 7607.5ms  cached=55785/55839  reasoning_tok=69  out=111
run 20: TTFB=  995.0ms  TTFT= 1898.8ms  gap=  903.8ms  cached=55785/55839  reasoning_tok=27  out=67
  TTFB(ms): min   852.9 | median   994.8 | mean   988.7 | max  1014.8
  TTFT(ms): min  1898.8 | median  3297.5 | mean  3978.3 | max  8598.4
  GAP (ms): min   903.8 | median  2298.8 | mean  2989.6 | max  7607.5

################  openai.gpt-5.4  @ mantle us-west-2  ################
warm-up: ttfb=1178.026881068945 ttft=2167.3433957621455 input_tokens=55839 cached=0 reasoning=67 err=None
run  1: TTFB=  807.7ms  TTFT= 1769.2ms  gap=  961.5ms  cached=0/55839  reasoning_tok=50  out=89
run  2: TTFB=  796.3ms  TTFT= 1979.5ms  gap= 1183.2ms  cached=0/55839  reasoning_tok=93  out=135
run  3: TTFB=  800.0ms  TTFT= 1569.2ms  gap=  769.2ms  cached=55646/55839  reasoning_tok=56  out=98
run  4: TTFB=  831.5ms  TTFT= 1785.7ms  gap=  954.2ms  cached=55646/55839  reasoning_tok=86  out=125
run  5: TTFB=  820.6ms  TTFT= 1794.4ms  gap=  973.8ms  cached=55646/55839  reasoning_tok=66  out=107
run  6: TTFB=  948.2ms  TTFT= 1713.1ms  gap=  764.9ms  cached=55646/55839  reasoning_tok=62  out=103
run  7: TTFB=  822.4ms  TTFT= 1684.3ms  gap=  861.9ms  cached=55646/55839  reasoning_tok=57  out=94
run  8: TTFB=  697.9ms  TTFT= 1477.7ms  gap=  779.8ms  cached=55646/55839  reasoning_tok=54  out=93
run  9: TTFB=  683.9ms  TTFT= 1460.9ms  gap=  777.1ms  cached=55646/55839  reasoning_tok=64  out=105
run 10: TTFB=  817.3ms  TTFT= 1621.1ms  gap=  803.7ms  cached=55646/55839  reasoning_tok=52  out=94
run 11: TTFB=  662.1ms  TTFT= 1434.6ms  gap=  772.4ms  cached=55646/55839  reasoning_tok=63  out=104
run 12: TTFB=  688.5ms  TTFT= 1467.7ms  gap=  779.1ms  cached=55646/55839  reasoning_tok=55  out=91
run 13: TTFB=  696.3ms  TTFT= 1463.4ms  gap=  767.1ms  cached=55646/55839  reasoning_tok=28  out=65
run 14: TTFB=  714.2ms  TTFT= 1716.2ms  gap= 1002.0ms  cached=55646/55839  reasoning_tok=74  out=116
run 15: TTFB=  679.7ms  TTFT= 1834.6ms  gap= 1154.8ms  cached=55646/55839  reasoning_tok=116  out=153
run 16: TTFB=  637.8ms  TTFT= 1412.4ms  gap=  774.6ms  cached=55646/55839  reasoning_tok=45  out=88
run 17: TTFB=  655.9ms  TTFT= 1428.0ms  gap=  772.1ms  cached=55646/55839  reasoning_tok=61  out=103
run 18: TTFB=  712.7ms  TTFT= 1280.1ms  gap=  567.4ms  cached=55646/55839  reasoning_tok=33  out=70
run 19: TTFB=  716.9ms  TTFT= 1693.8ms  gap=  976.9ms  cached=55646/55839  reasoning_tok=80  out=115
run 20: TTFB=  681.7ms  TTFT= 1639.4ms  gap=  957.7ms  cached=55646/55839  reasoning_tok=75  out=106
  TTFB(ms): min   637.8 | median   713.5 | mean   743.6 | max   948.2
  TTFT(ms): min  1280.1 | median  1630.2 | mean  1611.3 | max  1979.5
  GAP (ms): min   567.4 | median   791.8 | mean   867.7 | max  1183.2

================  SUMMARY MATRIX (median ms, N=20)  ================
channel            model                TTFB     TTFT      GAP
mantle us-east-1   openai.gpt-5.4       1080     2459     1335
mantle us-east-2   openai.gpt-5.4        995     3298     2299
mantle us-west-2   openai.gpt-5.4        713     1630      792
```

---

## 재현 런 (2회차) 원시 출력

```

################  openai.gpt-5.4  @ mantle us-east-1  ################
warm-up: ttfb=1944.2351767793298 ttft=3419.0501291304827 input_tokens=55839 cached=55785 reasoning=64 err=None
run  1: TTFB= 1127.0ms  TTFT= 2538.5ms  gap= 1411.5ms  cached=55785/55839  reasoning_tok=69  out=111
run  2: TTFB= 1156.7ms  TTFT= 2693.2ms  gap= 1536.4ms  cached=55785/55839  reasoning_tok=73  out=110
run  3: TTFB= 1094.7ms  TTFT= 3001.5ms  gap= 1906.8ms  cached=55785/55839  reasoning_tok=95  out=132
run  4: TTFB= 1128.9ms  TTFT= 2043.0ms  gap=  914.1ms  cached=55785/55839  reasoning_tok=28  out=68
run  5: TTFB= 1139.4ms  TTFT= 2450.4ms  gap= 1311.0ms  cached=55785/55839  reasoning_tok=58  out=91
run  6: TTFB= 1087.1ms  TTFT= 2800.3ms  gap= 1713.3ms  cached=55785/55839  reasoning_tok=92  out=134
run  7: TTFB= 1094.8ms  TTFT= 2418.9ms  gap= 1324.0ms  cached=55785/55839  reasoning_tok=68  out=110
run  8: TTFB= 1116.9ms  TTFT= 2839.5ms  gap= 1722.6ms  cached=55785/55839  reasoning_tok=85  out=122
run  9: TTFB= 1176.7ms  TTFT= 2701.9ms  gap= 1525.2ms  cached=55785/55839  reasoning_tok=79  out=115
run 10: TTFB= 1124.2ms  TTFT= 2636.4ms  gap= 1512.2ms  cached=55785/55839  reasoning_tok=69  out=115
run 11: TTFB= 1100.4ms  TTFT= 2432.1ms  gap= 1331.7ms  cached=55785/55839  reasoning_tok=52  out=85
run 12: TTFB= 1090.5ms  TTFT= 2917.8ms  gap= 1827.3ms  cached=0/55839  reasoning_tok=59  out=94
run 13: TTFB= 1092.7ms  TTFT= 3411.9ms  gap= 2319.2ms  cached=55785/55839  reasoning_tok=115  out=146
run 14: TTFB= 1088.0ms  TTFT= 2211.4ms  gap= 1123.4ms  cached=55785/55839  reasoning_tok=52  out=91
run 15: TTFB= 1118.4ms  TTFT= 2218.5ms  gap= 1100.1ms  cached=55785/55839  reasoning_tok=47  out=79
run 16: TTFB=  947.8ms  TTFT= 2302.5ms  gap= 1354.7ms  cached=55785/55839  reasoning_tok=54  out=87
run 17: TTFB= 1087.7ms  TTFT= 2607.2ms  gap= 1519.5ms  cached=55785/55839  reasoning_tok=64  out=105
run 18: TTFB= 1080.5ms  TTFT= 2643.7ms  gap= 1563.3ms  cached=55785/55839  reasoning_tok=82  out=125
run 19: TTFB= 1164.1ms  TTFT= 2102.1ms  gap=  938.0ms  cached=55785/55839  reasoning_tok=28  out=70
run 20: TTFB= 1127.8ms  TTFT= 2258.7ms  gap= 1130.9ms  cached=55785/55839  reasoning_tok=54  out=87
  TTFB(ms): min   947.8 | median  1108.7 | mean  1107.2 | max  1176.7
  TTFT(ms): min  2043.0 | median  2572.9 | mean  2561.5 | max  3411.9
  GAP (ms): min   914.1 | median  1461.9 | mean  1454.3 | max  2319.2

################  openai.gpt-5.4  @ mantle us-east-2  ################
warm-up: ttfb=1489.8898964747787 ttft=7215.784014202654 input_tokens=55839 cached=55785 reasoning=45 err=None
run  1: TTFB=  992.1ms  TTFT= 3860.4ms  gap= 2868.3ms  cached=55785/55839  reasoning_tok=33  out=70
run  2: TTFB= 1008.4ms  TTFT= 3721.0ms  gap= 2712.6ms  cached=55785/55839  reasoning_tok=133  out=177
run  3: TTFB=  986.2ms  TTFT= 3778.6ms  gap= 2792.4ms  cached=55785/55839  reasoning_tok=63  out=96
run  4: TTFB=  992.2ms  TTFT= 2972.6ms  gap= 1980.4ms  cached=55785/55839  reasoning_tok=59  out=94
run  5: TTFB= 1080.1ms  TTFT= 3734.1ms  gap= 2654.0ms  cached=55785/55839  reasoning_tok=28  out=69
run  6: TTFB= 1048.9ms  TTFT= 3365.7ms  gap= 2316.8ms  cached=55785/55839  reasoning_tok=77  out=121
run  7: TTFB=  986.3ms  TTFT= 6292.1ms  gap= 5305.8ms  cached=55785/55839  reasoning_tok=57  out=98
run  8: TTFB=  878.8ms  TTFT= 2578.3ms  gap= 1699.5ms  cached=55785/55839  reasoning_tok=62  out=106
run  9: TTFB=  972.1ms  TTFT= 4181.9ms  gap= 3209.9ms  cached=55785/55839  reasoning_tok=57  out=90
run 10: TTFB=  994.2ms  TTFT= 3011.9ms  gap= 2017.7ms  cached=55785/55839  reasoning_tok=76  out=113
run 11: TTFB=  988.8ms  TTFT= 2892.1ms  gap= 1903.3ms  cached=55785/55839  reasoning_tok=80  out=122
run 12: TTFB=  992.5ms  TTFT=  n/a  ms  gap=  n/a  ms  cached=None/None  reasoning_tok=None  out=None
run 13: TTFB=  993.3ms  TTFT= 2986.4ms  gap= 1993.2ms  cached=55785/55839  reasoning_tok=56  out=93
run 14: TTFB=  875.0ms  TTFT= 2822.0ms  gap= 1947.0ms  cached=55785/55839  reasoning_tok=90  out=130
run 15: TTFB= 1075.4ms  TTFT= 5444.1ms  gap= 4368.7ms  cached=55785/55839  reasoning_tok=79  out=124
run 16: TTFB= 1003.2ms  TTFT= 3550.5ms  gap= 2547.4ms  cached=55785/55839  reasoning_tok=53  out=98
run 17: TTFB= 1003.2ms  TTFT= 3133.4ms  gap= 2130.2ms  cached=55785/55839  reasoning_tok=87  out=133
run 18: TTFB=  975.4ms  TTFT= 4519.9ms  gap= 3544.5ms  cached=55785/55839  reasoning_tok=49  out=92
run 19: TTFB= 1002.1ms  TTFT= 2846.6ms  gap= 1844.4ms  cached=55785/55839  reasoning_tok=55  out=98
run 20: TTFB=  978.9ms  TTFT= 2678.4ms  gap= 1699.5ms  cached=55785/55839  reasoning_tok=30  out=64
  TTFB(ms): min   875.0 | median   992.4 | mean   991.4 | max  1080.1
  TTFT(ms): min  2578.3 | median  3365.7 | mean  3598.4 | max  6292.1
  GAP (ms): min  1699.5 | median  2316.8 | mean  2607.1 | max  5305.8

################  openai.gpt-5.4  @ mantle us-west-2  ################
warm-up: ttfb=1160.7771702110767 ttft=2068.9769880846143 input_tokens=55839 cached=55646 reasoning=60 err=None
run  1: TTFB=  707.8ms  TTFT= 1247.2ms  gap=  539.5ms  cached=55646/55839  reasoning_tok=16  out=46
run  2: TTFB=  560.5ms  TTFT= 1535.6ms  gap=  975.1ms  cached=55646/55839  reasoning_tok=69  out=111
run  3: TTFB=  617.8ms  TTFT= 1486.3ms  gap=  868.5ms  cached=55646/55839  reasoning_tok=59  out=96
run  4: TTFB=  660.3ms  TTFT= 1449.0ms  gap=  788.7ms  cached=55646/55839  reasoning_tok=53  out=96
run  5: TTFB=  666.6ms  TTFT= 1472.6ms  gap=  806.0ms  cached=55646/55839  reasoning_tok=54  out=95
run  6: TTFB=  696.5ms  TTFT= 1452.2ms  gap=  755.7ms  cached=55646/55839  reasoning_tok=55  out=97
run  7: TTFB=  562.9ms  TTFT= 1440.4ms  gap=  877.4ms  cached=55646/55839  reasoning_tok=45  out=78
run  8: TTFB=  696.8ms  TTFT= 1490.3ms  gap=  793.5ms  cached=55646/55839  reasoning_tok=53  out=93
run  9: TTFB=  549.4ms  TTFT= 1502.9ms  gap=  953.5ms  cached=55646/55839  reasoning_tok=68  out=110
run 10: TTFB=  868.1ms  TTFT= 1651.0ms  gap=  783.0ms  cached=55646/55839  reasoning_tok=61  out=98
run 11: TTFB=  687.6ms  TTFT= 1855.6ms  gap= 1168.0ms  cached=55646/55839  reasoning_tok=77  out=110
run 12: TTFB=  788.2ms  TTFT= 1978.9ms  gap= 1190.6ms  cached=55646/55839  reasoning_tok=99  out=141
run 13: TTFB=  845.1ms  TTFT= 1812.8ms  gap=  967.7ms  cached=55646/55839  reasoning_tok=68  out=100
run 14: TTFB=  794.4ms  TTFT= 1767.0ms  gap=  972.7ms  cached=55646/55839  reasoning_tok=56  out=98
run 15: TTFB=  789.0ms  TTFT= 1476.1ms  gap=  687.1ms  cached=55646/55839  reasoning_tok=17  out=50
run 16: TTFB=  526.8ms  TTFT= 1615.6ms  gap= 1088.8ms  cached=55646/55839  reasoning_tok=76  out=116
run 17: TTFB=  646.0ms  TTFT= 1830.3ms  gap= 1184.4ms  cached=55646/55839  reasoning_tok=116  out=155
run 18: TTFB=  519.4ms  TTFT= 1682.0ms  gap= 1162.6ms  cached=55646/55839  reasoning_tok=97  out=135
run 19: TTFB=  658.1ms  TTFT= 1622.4ms  gap=  964.2ms  cached=55646/55839  reasoning_tok=65  out=106
run 20: TTFB=  771.5ms  TTFT= 1734.8ms  gap=  963.2ms  cached=55646/55839  reasoning_tok=72  out=114
  TTFB(ms): min   519.4 | median   677.1 | mean   680.6 | max   868.1
  TTFT(ms): min  1247.2 | median  1575.6 | mean  1605.2 | max  1978.9
  GAP (ms): min   539.5 | median   958.4 | mean   924.5 | max  1190.6

================  SUMMARY MATRIX (median ms, N=20)  ================
channel            model                TTFB     TTFT      GAP
mantle us-east-1   openai.gpt-5.4       1109     2573     1462
mantle us-east-2   openai.gpt-5.4        992     3366     2317
mantle us-west-2   openai.gpt-5.4        677     1576      958
```
