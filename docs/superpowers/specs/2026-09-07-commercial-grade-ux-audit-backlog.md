# 상용화급 UX 감사 백로그 (2026-09-07)

목표는 소유자가 정한 "모델 모니터링의 최상위 수준의 상용화급 구현, 디자인, 편의성"이다. 이 문서는 그 목표를 코드 수준의 실행 항목으로 환산한 durable 기록이며, v2.25.0 이후 릴리스의 단일 백로그로 쓴다.

- 방법: 영역 리더 6종(대시보드, 분석 4페이지, /models와 /parity, /gpt-on-aws, 앱 셸, 비주얼, API/오류)이 소스 정독과 라이브 GET 측정, 실제 브라우저 스크린샷(390px, 1440px, 다크와 라이트, KO와 EN)으로 감사 → 2개 합성 렌즈(디자인 시스템 DS-01~DS-20, 편의성/신뢰성 CV-01~CV-20) → 모든 P1, P2 항목을 적대적 검증(32건 유지, 6건 중복 병합) → 완결성 크리틱(24건 추가) → 릴리스 번들 4개로 재편.
- 기준 커밋: HEAD `f11dda9` (`feat/features-detail-parity`, main = `a048028`). 리더 감사는 v2.23.1 기준이며, 크리틱이 `git diff --stat a048028..HEAD`로 인용 앵커 무변동을 재확인했다.
- 라이브: https://llm-monitor.whchoi.net (공개 GET, HEAD만 사용, 2026-09-07 16:2x~19:4x UTC).
- 범위 제외: `/claude-features` 상세도 패리티(v2.24.0 계획 `docs/superpowers/plans/2026-09-07-claude-features-detail-parity.md`, 16 태스크)는 이 백로그의 대상이 아니다. 감사 6종과 합성 2종이 의도적으로 제외했고, 검증도 "v2.24.0 플랜과 중복 0건"을 항목마다 확인했다. 이 백로그에 `/claude-features` 상세 항목을 추가하지 않는다. 단 같은 파일을 만지는 항목(DS-06 모달 3곳, DS-08 채택, DS-14b, DS-18 i18n 개편, DS-10 formatDuration 이관, DS-11a 매트릭스 카드 뷰)은 v2.24.0 머지 후 착수한다.
- 총 항목 58건(검증 32, 크리틱 추가 24, 미검증 P3 2), 총 공수 364~509h(선택 항목 N-05, N-21 탑재 제외 시 356~491h). 프론트와 백엔드 2트랙 병행 시 캘린더 7~9주.

---

## 1. 한눈에 보기

### 1.1 심각도 분포 (번들별, 최초 등장 번들 기준)

| 번들 | P1 | P2 | P3 | 계 | 구성 |
|---|---|---|---|---|---|
| B1 (v2.25.0) | 10 | 6 | 2 | 18 | 검증 12건, 크리틱 6건 |
| B2 (v2.26.0) | 2 | 9 | 2 | 13 | 검증 7건, 크리틱 6건 |
| B3 (v2.27.0) | 2 | 5 | 1 | 8 | 검증 5건, 크리틱 3건 |
| B4 (v2.28.0, v2.28.1) | 0 | 11 | 8 | 19 | 검증 8건, 크리틱 9건, 미검증 P3 2건 |
| **합계** | **14** | **31** | **13** | **58** | |

P1 14건 = 검증 항목 12건(DS-01, DS-02, DS-05, DS-07, DS-08, DS-12, CV-01, CV-03, CV-05, CV-07, CV-08, CV-09) + 크리틱 2건(N-01, N-02). 여러 번들로 쪼개지는 항목(DS-03, DS-04, DS-07, DS-15, DS-19, CV-03, CV-04, CV-05, CV-08, CV-13)은 최초 등장 번들에서 1회만 셌다.

### 1.2 릴리스 번들 4개 (크리틱 §8 원문)

| 번들 | 릴리스 | 포함 항목 id | 총 공수 | 근거 |
|---|---|---|---|---|
| B1 안전, 오류 규약, 모바일 P1, OOM 차단 (PR1 핫픽스 세트는 main 분기로 당일 배포, v2.24.0 머지 전이면 v2.23.2, 후면 v2.24.1 태그) | v2.25.0 | CV-08a, N-02, CV-04a, N-01, DS-03(핫픽스 1줄), DS-04(B3-a 토큰 상향), DS-05, CV-13 F-1(=N-20), CV-05a, N-10, CV-03a, CV-01, DS-02, N-19, CV-02 fold-in, CV-07, N-25, DS-07a, N-09 | 74~98h | 라이브와 코드로 재확정된 P1 전부를 닫는다. 무인증 유료 트리거, results/stats와 분석 4라우터의 OOM 경로(오늘 3회 실측), 보안 헤더와 CORS, 장애를 "데이터 없음"으로 오보, 24시간 세션 만료 무처리, 390px 오버플로, 모바일 범례 겹침. N-10 하네스를 여기서 끝내 후속 항목의 테스트 인프라 가산분 약 8~10h를 제거한다. |
| B2 셸, 다이얼로그, 인증 UX, 액션 피드백 | v2.26.0 | DS-06, DS-15 fix 4(Toast/LiveRegion), DS-13, N-04, DS-09, DS-19 fix 2(경계 파일), N-03, N-11, CV-16 fold-in, DS-01, CV-08b, N-08, N-06, DS-12, N-18 | 74~105h | Dialog 프리미티브가 N-06 관리자 UI, N-08 삭제 확인, CV-08b ConfirmDialog, DS-12 챗 시트, 로그인 모달 12곳의 공통 의존이라 첫 PR로 고정한다. PageShell과 Providers가 인증 공백, 언어 플래시, 페이지별 title, 경계 파일, 승인 리다이렉트를 한 번에 해결한다. B1과 무관한 셸 계층이며 CDK 변경이 없다. |
| B3 데이터 신뢰, 신선도, 포맷, 백엔드 성능 | v2.27.0 | CV-03b, CV-04b, N-24, CV-05b, CV-05c, CV-09, DS-10, CV-12 fold-in, DS-08, CV-06 fold-in, DS-17, CV-13 F-2, CV-11 fold-in, CV-10, N-07, N-22 | 76~107h | 카드 "-" 사유(라이브 20~23/43), 기간 전환 레이스와 monthlyEstimate 7배 과대, 시각과 통화 포맷 단일화, 신선도와 지연 경보, /api/version과 health/ready, 페이로드 다이어트, CDK 캐시 분리와 WAF, 프롬프트 소유권, 인사이트 재생성 무결성. 백엔드 PR과 프론트 PR이 API 계약(since, bucket_seconds, owner_id, next_expected_at)만 공유하고 프론트가 필드 부재를 허용하므로 백엔드만 먼저 배포해도 동작한다. |
| B4 시각 시스템, 접근성 (v2.28.0, 72~104h) + i18n, 편의 (v2.28.1, 68~95h), 2 PR 트레인 | v2.28.0 / v2.28.1 | DS-03(잔여), DS-04(B3-b), DS-16, N-16, N-23, CV-19, DS-07b, DS-11a, N-17, DS-14, DS-15(잔여), DS-19(잔여), N-12, DS-20, DS-18, N-15, CV-17 fold-in, CV-20(흡수), CV-14, CV-15, DS-11b, CV-18, CV-13 F-3, N-13, N-14, N-21(결정), N-05(선택) | 140~199h | 전부 표시 계층이며 B1~B3 프리미티브(Dialog, Toast, ErrorState, format.ts, useAsyncData) 위에 얹는다. 28.0(토큰, 필, 표, 컨트롤, 차트 시간축, 테마 크롬, 아이콘)과 28.1(i18n 네임스페이스와 KO 카피 규칙, URL 상태, 내보내기와 대시보드 정렬, SSE와 챗 보존, RUM api_error, 첫 방문 안내와 푸터 고지, Comparison Lab 결정, 비밀번호 재설정) 어느 쪽만 배포해도 회귀가 없다. |

---

## 2. 검증된 항목 (32)

각 항목은 적대적 검증을 통과했다. 심각도와 공수는 검증이 교정한 값이며, 원안 수치가 틀렸던 곳은 "검증 교정" 행에 적었다. 번들과 PR 번호는 크리틱 §8 기준이다.

### 2.1 B1 — v2.25.0 안전, 오류 규약, 모바일 P1, OOM 차단

### CV-08 — 액션 피드백 규약: 트리거 인증 게이트, 409/202 계약, 토스트, alert/confirm 대체, 실행 상태 DB 기반 폴링

| | |
|---|---|
| 심각도(교정) | P1 유지 (P1은 인증 게이트 CV-08a에 귀속, 나머지 CV-08b는 P2) |
| 공수(교정) | L (14~18h) 단일 PR, 또는 CV-08a S (1.5~2h) + CV-08b M (11~14h) 분할 권고 |
| 페이지/영역 | / (지금 실행, 프로브 설정), /parity, /prompts, /claude-features |
| 번들/PR | B1 PR1(CV-08a), B2 PR5(CV-08b, N-08 동반) |
| 근거 요약 | `backend/routers/auto_probe.py:259-265` trigger_probe에 `Depends(get_current_user)` 없음, `:262-263` 실행 중 200 영문 문구, `api.ts:215` Authorization 미부착, `AutoDashboard.tsx:285-291` 비로그인에도 버튼 렌더, `cdk/lib/stacks/edge-stack.ts:134` ALLOW_ALL. `parity.py:122`와 `features.py:99`는 JWT를 요구해 정책이 갈린다. 응답 계약 3종(`api.ts:216` throw, `:892` `{triggered:false}`, `ParityPanel.tsx:392-395` try/catch 없는 인라인 fetch), 실행 중 disabled와 폴링 0건, `PromptsPanel.tsx:97,110` alert, `:105` confirm, `ProbeConfigPanel.tsx:140-141,149-150` console.error만. |
| 수정안 | 1. trigger_probe에 `user=Depends(get_current_user)` 추가(`auto_probe.py:3`이 `from __future__ import annotations`라 타입 주석 없이 `parity.py:122` 형태로). 2. 실행 중 409 `{detail, code:"ALREADY_RUNNING"}`, 시작 202 `{estimated_minutes}`, 쿨다운은 DB(`is_auto=1` 최근 5분) 기준 429와 Retry-After. 3. 프론트 postAction 헬퍼, 공용 Toast(CV-08 소유), ConfirmDialog(DS-06 Dialog와 공유해 1회만 구현). 4. 버튼은 user가 있을 때만 활성, 실행 중 disabled와 스피너, 트리거 후 30초 폴링과 완료 토스트. 5. 문서 4곳 갱신(`docs/api-reference.md:64`, `docs/onboarding.md:76`, ADR-003:15, `backend/routers/CLAUDE.md`). |
| 검증 교정 | 인용 12건 전부 HEAD에서 확인. 추가 증거 2건 — 수동 트리거도 `is_auto=1`로 저장돼 자동 데이터셋과 비용, 신뢰성 지표를 오염시키고 `_next_preset` 라운드로빈 위상을 교란한다(`auto_prober.py:174-181`, `:100-118`), `routers/auto_probe.py:97` current_cycle_running이 in-process라 스케줄 사이클 진행 중에도 false다. DB 기반 running으로 바꿀 때 runner가 `failed`를 쓰지 않으므로(`parity/runner.py:79-136`) `started_at > now()-N분` 스테일 가드가 필수다. 문구는 실측 소요 100초와 새로고침 주기 30초를 반영해 "약 2분 후 반영"으로 고친다. |

### CV-04 — API 응답 압축, CloudFront /api/* 비헤이비어 분리, 엔드포인트별 Cache-Control, PWA 자산 캐시

| | |
|---|---|
| 심각도(교정) | P2 (원안 P1에서 하향) |
| 공수(교정) | M (6~10h), 재산정 7~9h (GZip 포함 시 +1.5h) |
| 페이지/영역 | 전체, 특히 /parity, /claude-features, /gpt-on-aws, /analysis |
| 번들/PR | B1 PR1(CV-04a GZipMiddleware), B3 PR2(CV-04b CDK, N-24 동반) |
| 근거 요약 | `cdk/lib/stacks/edge-stack.ts:138-145` `/api/*`가 CACHING_DISABLED에 compress:false. 라이브 실측 `/api/parity/latest` 347,587B 무압축, `/api/features/latest` 188,731B → gzip 13,245B(−93%), `/api/gptbench/trend?hours=24` 106,341B → 12,511B(−88%), `/api/insights/latest` 30,475B → 8,258B(−73%) 전부 content-encoding 없음. `/api/auto-probe/latest`만 별도 비헤이비어(`:130-136`)로 br과 RefreshHit. `parity.py:39`, `features.py:67`의 s-maxage=60은 12초 간격 3회 연속 Miss로 무효. `backend/main.py` 미들웨어는 CORS만. PWA 자산 7경로가 no-store와 Miss. |
| 수정안 | 1. `main.py`에 GZipMiddleware(minimum_size=1024) 추가는 선택으로 격하하고, CloudFront compress:true와 커스텀 캐시 정책만으로 목표를 달성한다. 2. SSE 4경로(/api/chat/*, /api/probes/*, /api/compare/*, /api/insights/stream-regenerate)만 CACHING_DISABLED와 compress:false로 남기고 나머지 `/api/*`는 origin Cache-Control 존중과 compress:true. 3. 캐시 정책에 `CacheHeaderBehavior.allowList("Authorization")` 또는 `/api/auth/*`, `/api/admin/*` 분리 비헤이비어를 반드시 넣는다. 4. `queryStringBehavior.all()` 필수(cost와 analysis의 window, gptbench의 hours). 5. PWA 자산은 htmlNoCachePolicy가 적용되지 않는 CDK 캐싱 비헤이비어를 추가한다(비헤이비어 4개 → 약 10개, 한도 25 이내). |
| 검증 교정 | 원안의 원인 귀속 2건이 오류다. 1. PWA 자산 no-store의 지배 계층은 Next 정규식이 아니라 CloudFront 기본 비헤이비어 htmlNoCachePolicy(`edge-stack.ts:64-75` override:true)와 CACHING_DISABLED(`:120-122`)다. 2. `/api/*`를 캐시 정책으로 옮기면 GET/HEAD의 Authorization 헤더가 제거돼 `GET /api/auth/me`가 401이 되고 로그인 세션이 파손된다. GZipMiddleware는 Starlette <0.46.0에서 SSE 청크를 압축하고 `requirements.txt`가 `fastapi>=0.109.0`만 핀해 운영 버전이 불확정이므로 포함 시 `starlette>=0.46` 핀과 SSE 비압축 테스트가 필요하다. 1,000B 미만 응답(status 174B, categories 412B, anomalies 265B)이 미압축인 것은 정상이다. |

### DS-03 — 라이트 테마 하드코딩 색 10곳 수정과 회귀 가드

| | |
|---|---|
| 심각도(교정) | P2, 단 `CostDashboardPanel.tsx:144` 1줄 핫픽스는 P1로 즉시 처리 |
| 공수(교정) | S (2~3h) 재범위 기준 (원안 500 변수화와 의미 토큰까지면 M~L 12h+이며 DS-04, DS-16과 중복) |
| 페이지/영역 | /cost, /, /gpt-on-aws, 전체 |
| 번들/PR | B1 PR1(핫픽스 1줄), B4 PR1(잔여) |
| 근거 요약 | `CostDashboardPanel.tsx:144` `text-blue-100`이 라이브 CSS(`/_next/static/css/0406cac977186828.css`)에 정적 컴파일돼 라이트 카드 위 대비 1.18:1로 "30일 예상" 금액이 보이지 않는다(v2.1.0 커밋 `5f8418f`부터 존재). `ModelStatusGrid.tsx:139-140` `bg-amber-950/20`, `bg-rose-950/20`이 라이트에서 회갈색 틴트가 되고 `:203` `text-amber-500/60`은 1.22:1, `ComparePanel.tsx:482` 동일. `GptOnAwsPanel.tsx:222` `bg-rose-950/40` 2.32:1, `AnalysisPanel.tsx:153` `bg-rose-950/50` 동일 계열. `AppHeader.tsx:104,110` 활성 칩 `bg-gray-600 text-white`가 라이트 2.56:1, 같은 결함군인 `InsightsPanel.tsx:150`과 `chat/ChatPanel.tsx:93` `bg-gray-700 text-white`는 1.48:1이다. |
| 수정안 | 1. 핫픽스 `CostDashboardPanel.tsx:144` → `text-gray-100`(라이트 17.2:1) 또는 `text-blue-100 light:text-blue-900`(9.99:1), 활성 칩은 `bg-blue-600 text-white`(5.17:1). 2. 950 틴트 이탈 4곳(GptOnAws:222, Analysis:153, ModelStatusGrid:139-140, Compare:482)을 코드베이스에 이미 있는 공용 패턴 `bg-X-500/10 border-X-500/30 text-X-300`(라이트 5.15:1)으로 정렬한다. 3. `text-white` 결합 3곳(AppHeader, InsightsPanel, ChatPanel)을 함께 고친다. 4. vitest 가드 1개로 금지 패턴(`text-\w+-(50|100)`, `bg-\w+-950`, `bg-gray-*`와 결합된 `text-white`)을 0건으로 잠근다. |
| 검증 교정 | 판정 partial이다. 1. 기각 — "globals.css:160 rounded-lg 카드 3곳 그림자 누락"은 전수 grep에서 해당 카드가 0건이고 6개 source_id 어디에도 없는 주장이다. 2. 과대 — "100, 950 단계 커버리지 갭"은 실사용 6곳(text-*-100 1, bg-*-950 5)뿐이고 이미 `light:` 변형(`tailwind.config.ts:132`, 7파일 36곳)이 있어 17색조 × 2단계 변수화는 비례하지 않는다. 3. `*-500` 변수화는 폐기 — 약 240회 사용에 `globals.css:25`와 CHANGELOG v2.8.3이 "500 이상과 저투명 틴트는 양 테마 공용"을 설계 결정으로 기록했다. 4. 대비 수치 미세 교정(amber 1.06 → 1.22, GptOnAws 2.46 → 2.32). Playwright는 미설치라 제외하고 vitest 가드로 대체한다. |

### DS-04 — 보조 텍스트 대비 토큰 상향과 최소 타이포 스케일 (10px, 9px 61곳 제거)

| | |
|---|---|
| 심각도(교정) | P2 유지 |
| 공수(교정) | M (6~10h, 추정 7~9h). 분할 권고 — B3-a 토큰(변수 상향과 placeholder, 약 2h) / B3-b 스케일(치환과 가드, 5~7h, v2.24.0 머지 후) |
| 페이지/영역 | 전체 |
| 번들/PR | B1 PR1(B3-a), B4 PR1(B3-b) |
| 근거 요약 | `globals.css:17-18` 다크 gray-500 `107 114 128`(카드 위 3.94:1), gray-600 `75 85 99`(2.52~2.66:1), `:88-89` 라이트 gray-500 `100 116 139`, gray-600 `148 163 184`(2.39~2.56:1). 재카운트 `text-gray-500` 171건/27파일, `text-gray-600` 27건/14파일, `text-[10px]` 57 + `text-[9px]` 4 = 61건, `opacity-70` 7건(라이트 2.68~3.77), `placeholder-gray-600` 4곳(1.94:1). 라이트 emerald-400 3.51~3.77, amber-400 2.96~3.19, `EfficiencyPanel.tsx:105` amber-400/70 2.22. 라이브 CSS 번들에 동일 값과 `text-[9px]`, `text-[10px]` 규칙이 존재해 배포본도 같다. |
| 수정안 | 1. CSS 변수 상향 — 다크 gray-500을 `128 136 152`(카드 5.34:1, gray-400과 위계 유지), 라이트 gray-600을 `71 85 105`(7.58:1), gray-500을 `85 99 120`(6.10:1). gray-600은 텍스트 금지가 아니라 비텍스트 전용으로 규정한다(bg-gray-600 7곳, border-gray-600 5곳 존재). 2. placeholder를 gray-500로. 3. 타이포 스케일 11/12/14/16/20/24 고정(`text-2xs`=11px), 61곳 치환, 기존 `text-[11px]` 39곳도 통일. 4. `chartTheme.ts:17` 다크 틱 하드코딩 `#6b7280` 2줄 동기화. 5. ESLint가 없으므로 `src/**/*.tsx`를 fs로 스캔해 금지 패턴 0건을 단언하는 vitest(약 30 LOC)로 대체한다. |
| 검증 교정 | 원안 제안값 다크 `139 147 167`은 카드 위 6.19:1로 "4.6:1"이 오산이며 gray-400(7.49)과 위계가 좁아진다. `text-gray-600` 27곳 중 SVG 아이콘 2, 구분 글리프 4, hover 아이콘 1은 치환 대상이 아니라 정보성은 약 20곳이다. 감사가 인용한 contrast.js는 저장소에 없어 이식이 아닌 신규 구현이다. 레이아웃 위험 — `ParityPanel.tsx:749` 10px 필 1,135셀은 11px로 올리면 1440px에서 가로 스크롤이 생기고 `:100` 9px HEALTHY는 w-24 폭 재조정이 필요하다. v2.24.0 플랜 자체가 ClaudeFeaturesPanel에 9px, 10px, gray-600을 추가하므로 머지 후 61곳을 재카운트한다. |

### DS-05 — 390px 가로 오버플로 4곳과 상태바 축소 줄바꿈 수정

| | |
|---|---|
| 심각도(교정) | P1 (대시보드 기간 행 단독 P1, 모바일 첫 페이지 84% 축소 렌더와 FAB 화면 밖. 상태바, 이력 패널, GPT 카드, 패리티는 각각 P2) |
| 공수(교정) | S (3~5h) 조건부. 수정안 1~4와 패리티 문단, 첫 열 축소는 합계 약 1.5h |
| 페이지/영역 | /, /parity, /gpt-on-aws |
| 번들/PR | B1 PR1 |
| 근거 요약 | `AutoDashboard.tsx:355` 기간 12버튼 nowrap이 행 폭 424px(가용 358)로 넘쳐 documentElement.scrollWidth 463, 모바일 에뮬레이션 innerWidth가 463으로 확장되고 FAB가 x375~439로 49px 화면 밖이다. `:354` 라벨 "조회기간"도 글자 단위로 세로 적층된다. `HistoryPanel.tsx:182` 8버튼 행 cw341/sw398로 패널 내부 33px 가로 스크롤. `GptOnAwsPanel.tsx:279` 카드 9장이 전부 inline-block 261px(부모 358). `ParityPanel.tsx:774` "동작 방식" 3번 KO 문단의 슬래시 연속 토큰이 p를 cw324/sw414로 만들어 문서 scrollWidth 447의 실제 원인이다. 768px은 전 페이지 통과. |
| 수정안 | 1. `AutoDashboard.tsx:355` `flex flex-wrap gap-1`과 `:354` 라벨 `shrink-0 whitespace-nowrap`. 2. `:242` 상태바 좌측 그룹 `grid grid-cols-2 gap-2 sm:flex sm:items-center sm:gap-6`, 필 `whitespace-nowrap`(오버플로가 아닌 축소 줄바꿈 해소 목적). 3. `HistoryPanel.tsx:182` `flex flex-wrap gap-2`. 4. `GptOnAwsPanel.tsx:279` `block w-full` 1줄. 5. `ParityPanel.tsx:774` KO 카피를 쉼표 나열로 교체("3. 모델 × API surface(Converse, InvokeModel, Messages, ChatCompletions, Responses) × 19개 피처로 팬아웃합니다."), 첫 열 `max-w-[8.5rem] sm:max-w-none truncate`와 title, model_id `hidden sm:block`은 스크롤러 내부 가시 폭 개선(120 → 220px)으로 별도 기술. |
| 검증 교정 | 5곳 중 4곳 확인, 1곳 반증, 1곳 원인 귀속 오류다. 반증 — 상태바 좌측 그룹은 scrollWidth 324 = clientWidth 324로 오버플로가 없고 실제 결함은 flex-shrink 축소로 "대기 중" 필이 4줄 58px이 되는 P2 미관 문제다. 원인 오류 — 패리티 테이블 래퍼는 `overflow-x-auto`(`:679`)라 body 오버플로에 기여하지 않으며 첫 열 축소만으로는 447이 해소되지 않는다. 수치 교정 — 기간 행 424(≈650 아님), 이력 행 398(≈490 아님), 상태바 324(≈510 아님). `<sm` 카드 뷰는 DS-11로, Playwright 회귀는 N-10으로 이관한다. `ParityPanel.tsx:772-776` "1 ·" 번호는 한글 카피 규칙 위반으로 DS-18 범위다. |

### CV-13 — 버전과 헬스 신뢰 신호: /api/version, /api/health/ready, RUM appVersion, 모바일 버전과 푸터, 문서 링크

| | |
|---|---|
| 심각도(교정) | P2 유지 (푸터, 문서 링크, 모바일 버전 하위 항목은 번들 내 P3로 구분) |
| 공수(교정) | M~L (8~11h). 3단계 분할 — F-1 0.5h, F-2 5~6h, F-3 3~4h |
| 페이지/영역 | 전체(헤더와 푸터), 백엔드 /api/health |
| 번들/PR | B1 PR1(F-1 = N-20), B3 PR7(F-2), B4 PR14(F-3) |
| 근거 요약 | `RumProvider.tsx:37` appVersion "2.16.2" vs `lib/version.ts:3` "v2.23.1" — CHANGELOG 기준 17개 릴리스가 오기록됐고 커밋 `0c30110`(2026-07-12) 이후 변경이 없다. `backend/main.py:248-251` `/api/health`가 `{"status":"ok"}`만 반환해 DB를 확인하지 않는데 `app-services-stack.ts:227` ALB 헬스체크가 이 경로다. `main.py:215` version은 `/docs`에만 있고 라이브 `GET /api/version`, `/api/health/ready`는 404다. `AppHeader.tsx:95` 버전이 `hidden sm:inline`이라 390px에서 안 보이고 드로어(`:168-172`)에도 없다. `<footer>` 0건, 문서 링크 0건. |
| 수정안 | 1. F-1 — `RumProvider` appVersion을 `APP_VERSION.replace(/^v/,"")`로, CLAUDE.md 버전 표와 release 스킬 체크리스트에 RumProvider.tsx 추가(v2.24.0 Task 16에 편입). 2. F-2 — `/api/version`(정적 빌드 정보만)과 `/api/health/ready`(SELECT 1, statement_timeout 2s, 프로세스 내 10~15초 캐시), 공용 AppFooter(`layout.tsx:48` 1곳으로 9페이지 커버), 드로어 버전, 대시보드 15분 지연 amber, 방법론 링크. 3. F-3 — `lib/api.ts`에 공용 apiGet() 래퍼를 신설해 36콜을 이전하고 실패 시 `RumSDK.addCustomEvent("api_error", {url,status,page,app_version})`. |
| 검증 교정 | 핵심 증거 8/8 확인, fix 문구 2건이 오류다. 1. `lib/api.ts`에 apiFetch가 존재하지 않는다(`await fetch(` 36회 독립). 2. rum-sdk.min.js 공개 API는 init, destroy, setUser, addCustomEvent만이며 recordError가 없다(custom event의 app_version은 ""로 고정되는 quirk가 있어 payload에 버전을 명시해야 한다). 3. "7개 릴리스"는 17개다. 구현 위험 — ALB healthCheckPath는 liveness(`/api/health`)로 유지해야 한다(readiness로 바꾸면 DB 장애 시 태스크 교체 루프와 서킷 브레이커 롤백, 2026-09-06 사고 계열). git_sha와 build_time은 backend Dockerfile ARG가 0건이라 런북 수정이 동반된다. |

### CV-05 — 대시보드 trend, latest 페이로드 다이어트

| | |
|---|---|
| 심각도(교정) | P1 유지 (근거 교체 — 무인증 공개 GET 수 회로 단일 backend 태스크가 OOM되어 약 90초 전면 5xx, 오늘 3회 실측. 페이로드 형태만 놓고 보면 P2) |
| 공수(교정) | M (10~14h). CV-05a 3~4h / CV-05b 6~8h / CV-05c 1.5~2h 분할 |
| 페이지/영역 | /, /parity, /gpt-on-aws, InsightsPanel |
| 번들/PR | B1 PR1(CV-05a), B3 PR3(CV-05b, CV-05c) |
| 근거 요약 | 라이브 `/api/auto-probe/trend?hours=24` raw 4,482,643B, 12,341포인트, 5.6s(gzip wire 348,979B), min/max 74,046필드가 전부 null. `hours=1`은 473포인트가 473개 상이 타임스탬프라 `pivotTrend.ts:36,45`가 행당 모델 1개를 만들어 툴팁에 1개만 뜬다. `/latest` 56,236B 중 output_text와 prompt가 38,558B(69%)이고 UI 미사용. `/api/parity/latest` 347,587B 중 skipped 618/1,805(32% 바이트)를 직렬화한 뒤 프론트가 숨긴다. gptbench trend 168h 737,435B, 6.6s. `aws ecs describe-tasks`에서 backend 컨테이너 exit 137 OutOfMemoryError가 오늘 3회(18:10Z, 18:19Z, 19:02Z) 기록됐고 19:02Z는 이 검증의 순차 GET 직후다. |
| 수정안 | 1. CV-05a 핫픽스 — trend >24h와 gptbench를 SQL GROUP BY와 컬럼 SELECT로 바꿔 Python 원본 적재를 제거하고 `gptbench.py:181` `le=720`을 168로 내리고 포인트 상한을 둔다. 2. CV-05b — hours≤24는 집계가 아니라 timestamp를 `ProbeRun.created_at`으로 정규화한다(비용 0, pivotTrend 무수정, D-06 동시 해결), `?format=series`로 gzip −64%, `/latest`는 `response_model_exclude={"output_text","prompt"}` 한 줄, trend 재조회를 `status.last_run_time` 변경 시로 게이트, GptOnAws 기간 변경 시 trend만 재요청. 3. CV-05c — parity skipped 제외와 provider별 skipped 카운트 서버 제공, latency 정수화, insights `?include=model_breakdown` opt-in. |
| 검증 교정 | 수치 11건은 전부 재현됐지만 효과 주장 2건이 오류다. 1. "24h 5분 버킷 → 288행"은 포인트 수를 줄이지 못한다(원본이 이미 5분 해상도). 2. "null min/max 생략 35%"는 raw 기준이며 `/api/auto-probe/*`는 이미 br 압축이라 gzip 감소는 −2.7%뿐이고, wire를 줄이는 것은 시리즈 포맷(−64%)이다. "−95%"는 D-05 원안의 재조회 게이트를 되살려야 성립한다. 운영 주의 — 후속 검증자는 `trend?hours=168`과 `gptbench/trend?hours>=168`을 라이브에 연속 호출하지 말고 `hours=720`은 절대 호출하지 않는다. |

### CV-03 — 분석 4라우터 Python 집계를 SQL 집계로, window 화이트리스트, since 계약 통일

| | |
|---|---|
| 심각도(교정) | P1 유지, 확정 |
| 공수(교정) | L (14~20h). CV-03a 8~10h 핫픽스 + CV-03b 6~10h + cost/trend 사문 삭제 0.5h |
| 페이지/영역 | /cost, /reliability, /efficiency, /analysis (백엔드) |
| 번들/PR | B1 PR3(CV-03a), B3 PR1(CV-03b) |
| 근거 요약 | `reliability.py:142-146`, `efficiency.py:112-116`, `analysis.py:100-108`, `:207-219`가 prompt와 output_text를 포함한 전체 엔티티를 `.all()`로 적재한 뒤 Python으로 집계한다. 라이브 재현(19:03Z) — 비인증 `GET /api/reliability/multi-channel?window=7d` 1회로 502(5.93s) → ECS describe-tasks에서 backend `exitCode 137, OutOfMemoryError` → 약 65초 뒤 복구. 오늘 backend 태스크 교체 8회, 보존된 stopped task 4건 전부 exit 137. `_parse_window`가 4곳 복붙이라 `?window=1.5d`는 500, `?window=zzz`는 200 에코, `?window=7`은 조용히 24h다. analysis 응답에 since가 없다. |
| 수정안 | 1. GROUP BY model_name + count FILTER + avg + percentile_cont(0.95)로 SQL 이전(3라우터 4엔드포인트). 2. `window: Literal["1h","6h","24h","7d","30d"]` Query로 7엔드포인트를 잠그고 422 KO detail "지원하지 않는 기간입니다. 1h, 6h, 24h, 7d, 30d 중 하나를 선택하세요." 3. 4라우터 응답에 since와 window_hours를 통일해 넣고 프론트 타입을 동기화한다. 4. 수용 기준을 "5xx와 exit 137 0건, 메모리 피크 <400MiB, 서버측 p95 <3s(CV-03a) → <1.5s(CV-03b)"로 재작성한다. 5. 임시 완화 1h — `with_entities`로 Text 2컬럼(행당 prompt 497자, output_text 431자)을 제외한다. |
| 검증 교정 | 부분 반박 2건. 1. `cost.py`의 summary와 channel-compare는 이미 SQL GROUP BY이고 Python `.all()`은 프론트 호출처가 0인 cost/trend뿐이라 SQL 이전 대상은 3라우터다. 2. "30d 사실상 불가"가 아니라 7d부터 OOM이고 `/analysis`는 기본값이 7d라 페이지 진입만으로 OOM된다. 설계 결함 2건 — "p95 < 1.5s"는 SQL 집계만으로 불가하며(이미 SQL인 cost/summary가 7d 4.89s), "초과는 probe_results_hourly" 경로는 현 스키마에 stop_reason 빈도와 p95, error_buckets가 없고 ≤60일 행이 0개라 불가하다(CV-03b에서 스키마 확장). 테스트가 전부 sqlite라 percentile_cont는 dialect 분기 또는 PG 하네스가 필요하다(+3~5h). 4라우터 모두 `from __future__ import annotations`가 있어 Literal 도입 시 제거한다. |

### CV-01 — apiFetch, ApiError 단일 규약: HTTP/2 빈 statusText, HTML 5xx, 422 배열 detail 정규화

| | |
|---|---|
| 심각도(교정) | P1 유지 |
| 공수(교정) | M (10~14h), 재산정 약 12.5h |
| 페이지/영역 | 전체 (api.ts를 쓰는 모든 패널과 raw fetch 5곳) |
| 번들/PR | B1 PR4 |
| 근거 요약 | `frontend/src/lib/api.ts` 28곳(84, 102, 118, 126, 133, 149, 159, 179, 188, 198, 210, 216, 222, 260, 428, 434, 446, 665, 671, 677, 711, 748, 772, 800, 848, 854, 872, 878)이 `… failed: ${res.statusText}`를 throw한다. 라이브는 전 경로 http_version=2이고 상태행이 `HTTP/2 502 `로 reason phrase가 없어 statusText가 항상 빈 문자열이다. 렌더 경로는 `AnalysisPanel:84→152`, `GptOnAwsPanel:179→221`, `CostDashboardPanel:47→105`, `Reliability:73`, `Efficiency:46`, `PromptsPanel:126`. raw fetch 5곳은 `ParityPanel.tsx:369-370`, `:277`, `:391`, `AutoDashboard.tsx:132`. 백엔드 문구가 KO와 EN으로 갈린다(`auto_probe.py:263` EN vs `parity.py:126` KO). |
| 수정안 | 1. `apiRequest`(Response 단계)와 `apiFetch<T>`(JSON 단계) 2단 래퍼를 도입한다. 스트리밍 4곳(`api.ts:263,356,501,577`)과 `/api/prompts/optimize`는 timeout을 해제한다. 2. `!ok`면 `ApiError{status, code, detail, url}`을 throw하고 JSON detail을 정규화하며(배열은 `loc[-1]: msg` join) non-JSON은 code NON_JSON, 네트워크는 NETWORK. 3. 28개 호출부와 raw fetch 5곳을 교체한다. 4. `lib/apiErrorMessage.ts`로 status와 code를 i18n 문구에 매핑하고 원문은 "자세히" 토글에 둔다. 5. 백엔드 오류 봉투 `{detail, code}` 표준화와 전역 exception handler, vitest와 pytest로 빈 statusText, 배열 detail, HTML 503, 401, 타임아웃을 고정한다. |
| 검증 교정 | `ClaudeFeaturesPanel.tsx:157-160`은 api.ts 함수 호출이라 "api.ts 우회"가 아니며 누락된 5번째 raw fetch는 `ParityPanel.tsx:276-279` 증거 모달이다. 422 `[object Object]` 도달 경로는 `LoginForm.tsx:91` type=email과 `:94` required 때문에 무점 도메인과 100자 초과만 남아 P1 근거의 주축이 아니다. FastAPI 미처리 500은 text/plain이라 code는 UPSTREAM_HTML보다 NON_JSON이 정확하다. 소유권 경계 — ApiError, normalizeDetail, describeApiError의 단일 소유자는 CV-01이고 DS-02, DS-13, CV-07, CV-08은 소비자다. v2.24.0이 `api.ts:860-894`를 접촉하므로 선머지 후 리베이스한다. |

### DS-02 — ErrorState, EmptyState 프리미티브와 ApiError 표시 규약

| | |
|---|---|
| 심각도(교정) | P1 |
| 공수(교정) | L (16~20h), 분해 약 19.5h |
| 페이지/영역 | 전체 (/, /models, /parity, /gpt-on-aws, /cost, /reliability, /efficiency, /analysis, /prompts, 인사이트) |
| 번들/PR | B1 PR5 (N-19와 CV-02 fold-in 5건 동반) |
| 근거 요약 | 검증 중(18:11Z~18:13Z) 전 API 경로가 503, 504, 502로 플래핑하고 본문이 HTML이었으며 그동안 화면은 자기 장애를 "데이터 없음"으로 오보했다. `AutoDashboard.tsx:114-118` catch가 console.error만 하고 error state가 0건이라 `:188`, `:329`, `:467-468`이 "아직 자동 프로빙 데이터가 없습니다"(`i18n.ts:134`)를 렌더한다. `ModelExplorer.tsx:180-186` → "0개 모델", "0 / 0". `ParityPanel.tsx:369-370`이 `r.ok`를 검사하지 않아 HTML 본문에서 reject되고 `:592-596` "아직 실행된 패리티 런이 없습니다"가 뜬다(run #128 존재). `InsightsPanel.tsx:29-36`, `PromptsPanel.tsx:65-75` 동일. `CostDashboardPanel.tsx:105-109` 오류 배너와 `:160-165` 빈 상태가 동시 렌더된다(Reliability:120-131, Efficiency:114-124 동일). `role="alert"`와 aria-live 0건, 재시도 버튼 0건, 오류 박스 배경 6종. |
| 수정안 | 1. `components/ui/ErrorState.tsx`(variant banner/block/inline, role=alert, status→i18n 문구, "다시 시도", staleSince 배지, 양 테마 공용 틴트 `bg-rose-500/10 border-rose-500/30 text-rose-300`). 2. `EmptyState.tsx`는 `status==="empty" && !error`일 때만 렌더하고 컨트롤은 항상 유지한다. 3. 데이터 상태를 null(미수신)과 []( 빈 결과)로 분리(5곳). 4. CV-01 ApiError를 소비한다(자체 구현 금지, B1 PR4 선행). 5. `CostDashboardPanel.tsx:40-43`과 `AnalysisPanel.tsx:77-80`을 `Promise.allSettled`로 바꿔 실패 섹션만 inline ErrorState. 6. 카테고리 실패 시 `lib/workloadPresets.ts` 6행 폴백과 비활성 필터 인라인 문구. 7. `lib/apiError.ts` `describeApiError(err, lang)` 순수 함수 vitest(jsdom 미설치 대체). |
| 검증 교정 | 수치 교정 — throw는 26곳이 아니라 28곳, 오류 박스는 4종이 아니라 배경 6종, ParityPanel 앵커는 `:367-381`과 `:592-596`. 인용 스크린샷 2장이 스크래치패드에 없어 라이브 curl로 대체 검증했다. fix 4의 "엔지니어링 백로그 의존"은 삭제하고 CV-01 선행으로 바꾼다. 채택 목록에 `HistoryPanel.tsx:120-131`(오류를 "이력 없음"으로 표시)과 `app/page.tsx:92-101`(fetchModels, fetchPromptSets 무음)을 추가한다(N-19). `/claude-features`는 범위 밖이지만 `ClaudeFeaturesPanel.tsx:32,:93` `setError(String(e))`는 v2.24.0 이후 후속 적용 후보로 기록한다. |

### CV-07 — 세션 만료 UX: 401 중앙 처리, fetchMe는 401과 403만 로그아웃, 만료 예고

| | |
|---|---|
| 심각도(교정) | P1 유지 |
| 공수(교정) | M (9~12h), 재산정 약 10.5h |
| 페이지/영역 | 전체(로그인 사용자), /prompts, /parity, 챗봇, 수동 프로브 |
| 번들/PR | B1 PR6 (N-25 동반) |
| 근거 요약 | `backend/auth.py:32` ACCESS_TOKEN_EXPIRE_HOURS=24이고 리프레시 엔드포인트가 없다. `api.ts`에 "401" 문자열이 0건이고 auth-changed는 `:39` 로그인과 로그아웃 버튼 경로에서만 dispatch된다. 만료 후 문구가 `PromptsPanel.tsx:96-97` alert, `app/page.tsx:209`, `ChatPanel.tsx:148-150`에 원문 노출되고 헤더는 사용자명을 유지한다. `api.ts:78`이 status와 무관하게 throw해 `.catch(() => setToken(null))`이 10곳(9 서브페이지 + `app/page.tsx:83`)에서 실행되므로 5xx 순간에 페이지를 열면 강제 로그아웃된다. 라이브 19:03Z `GET /api/auth/me`가 502 HTML, 19:04:46Z부터 401 JSON으로 플래핑해 이 경로가 오늘 실제 발생 가능했다. 401 응답에 www-authenticate와 cache-control이 없다. |
| 수정안 | 1. apiRequest(CV-01) 위에 401, 403 인터셉터를 얹어 setToken(null)과 전역 토스트 "세션이 만료되었습니다. 다시 로그인해 주세요."를 띄우고 로그인 모달을 연다(모달이 페이지 로컬 state이므로 auth-changed와 동형의 auth-expired CustomEvent로 배선). 2. `fetchMe`가 HTTP status를 노출하게 바꿔 401, 403만 토큰을 지우고 5xx와 네트워크는 토큰 유지, authChecked=true, 배너와 재시도. 3. JWT exp를 atob로 디코드해 만료 5분 전 amber 배너, 로드 시 만료면 왕복 없이 즉시 로그아웃 상태로 전환. 4. 백엔드 401에 `WWW-Authenticate: Bearer`와 no-store(`auth.py:75,81,83,87`). 5. SSE 4종을 apiRequest 경유로 바꿔 401 공통 경로에 연결한다. 6. `window.addEventListener("storage", …)` 1블록으로 다중 탭 동기화(N-25). |
| 검증 교정 | 핵심 5/5 확인, 부속 2건 보정. "SSE 4종 detail 미판독"은 runProbe와 chatStream 2종만 해당한다(compareStream, insightStream은 `res.text()`를 이미 읽지만 detail 파싱과 401 분기가 없다). `.catch(() => setToken(null))`은 9곳이 아니라 10곳이다. 만료 토큰은 ExpiredSignatureError가 JWTError에 포함돼 401로 오므로 401, 403 분기가 타당하다. 수정안 4번 "인증 확인 중 헤더 렌더"는 DS-09 PageShell 소유로 이관하고 참조만 남긴다. |

### DS-07 — 차트 시스템: 범례 외부화, 테마별 계열 팔레트, 막대 라벨 대비, 축과 툴팁 규약

| | |
|---|---|
| 심각도(교정) | P1 유지 (모바일 기본 대시보드 추이가 판독 불가, 설치형 PWA를 표방하는 제품 기준. 라이트 팔레트 단독은 P2, GPT 범례 P2, 분석 막대와 히스토그램 P3) |
| 공수(교정) | M~L (13~17h). 분할 권고 — DS-07a (P1, 8~10h, 의존 없음) / DS-07b (P2, 5~7h, DS-10 의존) |
| 페이지/영역 | / (TrendChart 3개), /gpt-on-aws (3개), /analysis (스택 바, 히스토그램) |
| 번들/PR | B1 PR7(DS-07a), B4 PR4(DS-07b) |
| 근거 요약 | 390px 대시보드 실측 legendH 718 vs chartH 300, 43항목, legendTop −422로 범례가 모델 칩과 "TTFT 추이" 제목, 접힌 플롯, 이전 카드 위에 겹쳐 그려진다. 1440px은 legendH 157에 플롯 약 139px이고 기본값이 models=all(`AutoDashboard.tsx:62-64`)이라 129선(43×3)이다. GPT 390px legendH 149/260, Y축이 "1.2s/600/0" 혼재. 라이트 테마에서 활성 MODEL_COLORS 43색 중 10색이 흰 배경 대비 2:1 미만이고 19/48이 3:1 미만이다. `chartTheme.ts:6-12`에 계열 팔레트가 없다. `pivotTrend.ts:36-47`이 1시간 516포인트를 516행으로 만들어 툴팁에 모델 1개만 뜨고 x축에 "오후 05:17"이 중복된다. 7개 차트 전부 svg role과 aria-label이 null이다. `AnalysisPanel.tsx:203` 흰 글자 on amber-500 2.15:1, `:207` 개별 반올림 합 101%. |
| 수정안 | 1. 대시보드는 Recharts Legend를 전 브레이크포인트에서 제거하고 상단 모델 칩을 범례로 만든다(색 점, aria-pressed). GPT 데스크톱 범례(9항목, 33px)는 유지하고 `<sm`만 컴팩트 키 1줄. 2. 팔레트는 색조=패밀리(약 13색) × 스트로크 패턴=채널로 재설계한다(HSL 밝기 클램프는 Global/US/리전 구분 축을 파괴하므로 금지), `≥3:1` vitest. 3. 5분 floor 또는 60초 갭 클러스터링으로 x축을 정규화하고 `scale="time"`, Y축 단위는 지표별로(TPS는 tok/s). 4. 스택 바 라벨을 `text-gray-950` 또는 바깥으로, fmtPct는 `r.counts[k]/r.total`에 최대 잔여법 적용, 세그먼트를 `<button aria-label>`로, 히스토그램 빈 라벨 표기. 5. 7개 차트에 `role="img"` aria-label("TTFT 추이, 선택 모델 43개, 최근 1시간")과 sr-only 데이터 표, `LatencyChart.tsx:126`도 같은 규약(+0.5h). |
| 검증 교정 | 다크 "4색 < 2:1"은 실제 `#881337`(1.99) 1색뿐이고 라이트는 9색이 아니라 10색이다. 원안 fix 3의 "기본값을 대표 모델로"는 `AutoDashboard.tsx:58-61`이 기록한 소유자 결정(2026-07-10 사용자 피드백으로 제거)과 충돌하므로 그리드 하이라이트 분리 또는 소유자 재승인이 필요한 결정 항목이다. fix 4의 run_id 키는 `/api/auto-probe/trend`와 TrendPoint에 run_id가 없어 불가하며 프론트 5분 floor가 실측 안전하다(12/12 버킷 = 43모델). >24h는 서버가 이미 시간 버킷이라 툴팁 문제는 ≤24h 한정이다. `pivotTrend.test.ts`의 타임스탬프 문자열 키와 56k행 <200ms 성능 경계를 함께 갱신한다. |

### 2.2 B2 — v2.26.0 셸, 다이얼로그, 인증 UX, 액션 피드백

### DS-06 — Dialog 프리미티브로 모달 17곳 통일: dialog 시맨틱, 포커스 트랩, Esc, 스크롤 잠금

| | |
|---|---|
| 심각도(교정) | P2 (접근성 적합성 WCAG AA와 VPAT가 상용 판매 요건이면 P1 유지). P1 승격 근거였던 "키보드로 닫을 수 없다"가 실측상 거짓이고 마우스와 터치 사용자 영향이 없다 |
| 공수(교정) | M~L (14~20h). N-10 하네스가 B1에서 끝나므로 B2에서는 11~16h + Toast 2h |
| 페이지/영역 | 전체 (로그인 모달 12곳, FloatingChat, ChatModal, InsightsPanel, ModelExplorer, ParityPanel 증거와 드로어, ClaudeFeaturesPanel, HistoryPanel) |
| 번들/PR | B2 PR1 (DS-15 fix 4 Toast, LiveRegion 동반) |
| 근거 요약 | 코드, 배포 번들, 라이브 4중 확인 — grep에서 `role=dialog`, `aria-modal`, `autoFocus`, `showModal` 0건이고 Escape 처리는 `chat/ChatModal.tsx:21` 하나다. `aria-label="overlay"` 포커스 가능 버튼이 17건/16파일이고 스크롤 잠금 코드가 0건, `HistoryPanel.tsx:161` 닫기에 라벨이 없고 `ModelExplorer.tsx:70-78` 닫기가 스크롤 컨테이너 안에 있어 고정되지 않는다. `PromptsPanel.tsx:97,105,110`은 alert와 confirm이다. 배포 청크 `page-31a456bef9a2108d.js`에 overlay 2건, dialog 0건. 라이브 로그인 모달은 role=null, activeElement가 트리거에 잔류, Tab 1회로 배경 검색 input으로 이동, Escape 후에도 열려 있고 `body.overflow=visible`, 닫기 버튼 13×20px이다. |
| 수정안 | 1. `components/ui/Dialog.tsx` — 네이티브 `<dialog>` + `showModal()` 또는 focus-trap, props는 open/onClose/title(aria-labelledby)/size sm,md,lg,sheet/initialFocusRef/closeLabel(i18n). 첫 포커스, Tab 순환, Esc, 트리거 복귀, body 스크롤 잠금, 헤더 sticky, 닫기 44px, `<sm` 하단 시트. 2. ConfirmDialog(role=alertdialog)로 PromptsPanel 삭제 확인을 대체한다(CV-08과 공유해 1회만 구현). 3. 로그인 모달 12곳은 동일 JSX이므로 LoginDialog 1개로 기계적 치환(2~3h), 고유 채택 6곳은 4~6h. 4. 오버레이를 포커스 불가 div 또는 `<dialog>` ::backdrop 클릭으로 교체한다(현재 모달 내부 첫 Tab 정지점이 전체 화면 "overlay" 버튼이다). 5. `i18n.ts`에 close 키를 추가한다(KO "닫기", EN "Close"). |
| 검증 교정 | 로그인 모달은 9곳이 아니라 12곳이다(+app/page.tsx, InsightsPanel, FloatingChat). "키보드 사용자는 닫을 수 없다"는 과장이다(Tab으로 overlay나 close에 도달해 Enter로 닫히고 ChatModal은 Esc가 동작한다). WCAG 인용은 2.1.2가 아니라 2.4.3, 4.1.2, 1.3.1과 APG Modal Dialog가 맞다. v2.24.0 Task 12 SurfaceDrawer가 같은 비접근성 패턴을 복제하므로 채택 대상이 18곳으로 늘거나 Dialog를 v2.24.0과 같은 릴리스에 선행 배치해야 한다. jsdom은 showModal을 구현하지 않아 폴리필 또는 수동 트랩 구현이 필요하다. |

### DS-15 — 포커스 링, Tooltip과 Popover, 폼 라벨, LiveRegion

| | |
|---|---|
| 심각도(교정) | P2 유지, 근거 교체 — 스크린리더 시맨틱(button 안의 h3 43개, 무명 검색 input 2개와 select 1개, aria-live 0건), 터치 접근 불가 데이터(분석 세그먼트 317개, 패리티 desc 19행), hover 전용 툴팁 129개. 포커스 링과 reduced-motion 소항목만은 P3 |
| 공수(교정) | S~M (6~9h). Tooltip과 Popover 프리미티브까지 CV-19로 넘기면 S (4~6h) |
| 페이지/영역 | 전체 |
| 번들/PR | B2 PR1(fix 4 Toast, LiveRegion), B4 PR7(잔여) |
| 근거 요약 | 코드 grep과 라이브 CSS 번들에서 `focus-visible`, `prefers-reduced-motion`, `htmlFor`, `aria-live`, `aria-describedby`가 전부 0건이다. `ModelStatusGrid.tsx:17-36` MetricTooltip이 hover 전용이고 라이브 `svg.cursor-help` 129개는 포커스 0, aria 0이다. `AnalysisPanel.tsx:128` select가 무명(라이브 aria-label null), `:203-208`과 `:296-304`의 title 전용 div 442개 중 텍스트 없는 것이 317개다. `ParityPanel.tsx:699-703` tr title 19행, 검색 input은 placeholder만(`ModelExplorer.tsx:225`, `ParityPanel.tsx:612`), `ModelExplorer.tsx:42` clipboard에 catch가 없다. 라이브에서 `[role=button]` 안의 h3가 43개다. |
| 수정안 | 1. `globals.css`에 `:focus-visible` outline 2px blue-400 offset 2px와 `:focus:not(:focus-visible)` none을 1규칙으로 넣고 `focus:outline-none` 14건 중 보더만 복원한 7건을 정리하며 motion-reduce를 추가한다. 2. `components/ui/Field.tsx`(label+id+hint+error aria-describedby, React 18 useId), 검색과 select에 aria-label. 3. LiveRegion(role=status)을 CV-16 대신 `app/layout.tsx`에 1회 마운트하고 useAnnounce()와 Toast(aria-live)를 제공한다. 4. 카드 제목을 span으로 바꾸고 장식 이모지에 aria-hidden(`TrendChart.tsx:153`, `ModelStatusGrid.tsx:228`). |
| 검증 교정 | 반박 3건. 1. "다크에서 포커스 비가시"는 거짓이다 — `globals.css:77` `color-scheme: dark` 때문에 Chromium UA 링이 rgb(238,238,238)로 선명하게 그려지고 인용된 rgb(16,16,16)은 `html.light` 값이라 WCAG 2.4.7 위반이 아니다. 2. "title 전용 아이콘 53개"는 code[title] 43개와 가시 텍스트 버튼 10개로 아이콘이 아니다. 3. "터치 사용자는 지표 설명을 열 수 없다"는 `AutoDashboard.tsx:445-456` 설명 패널이 상주하므로 과장이다. 중복 4건을 이관한다 — Tooltip과 Popover는 CV-19, Toast는 CV-08, 복사 폴백은 CV-15, PageShell 상주는 DS-09. |

### DS-13 — LoginForm 임베디드 변형: 카드 속 카드와 py-24 제거, label 연결, 422 배열 detail 표시

| | |
|---|---|
| 심각도(교정) | P2 (원안 P1에서 하향). 번들의 P1 근거가 API-06 하나였고 native type=email 가드로 `[object Object]` 경로가 엣지 케이스가 됐다 |
| 공수(교정) | S (6~8h) |
| 페이지/영역 | 전체 로그인 모달(12 호스트), /prompts 게이트 |
| 번들/PR | B2 PR2 (N-04 백엔드 min_length=8과 같은 PR) |
| 근거 요약 | `LoginForm.tsx:51-53` 무조건 `py-24`(상하 96px)와 자체 카드가 12곳의 동일 카드 클래스에 다시 감싸인다(`app/page.tsx:311`, `prompts/page.tsx:71,96`, 7개 서브페이지 `:62-64`, `claude-features:56`, `FloatingChat.tsx:126`, `InsightsPanel.tsx:222`). /prompts는 인라인(`:66-83`)과 헤더 모달(`:88-108`) 두 경로가 동시에 살아 있다. `htmlFor`, `role="alert"`, aria-live, autoFocus가 프로젝트 전체 0건이라 label이 형제 요소가 되고 접근 이름이 placeholder "admin"으로 떨어진다. `placeholder-gray-600` on gray-800은 1.94:1이다. 라이브 `GET /api/results/stats?start_time=bad`가 422 `{"detail":[{…}]}`를 반환하고 `api.ts:58,71,892`가 detail을 그대로 넘겨 `[object Object]`가 된다. |
| 수정안 | 1. `variant=embedded/page`를 도입해 embedded는 폼만 렌더하고 배치는 호출부가 맡는다. /prompts는 카드 1개로 합치고 헤더 "로그인"은 인라인 폼으로 포커스를 옮긴다. 2. id와 htmlFor, autoFocus(당장은 plain autoFocus, DS-06 도착 후 initialFocusRef로 승격), 오류 role=alert aria-live=assertive, 제출 스피너와 aria-busy, 비밀번호 표시 토글. 3. 등록 모드에만 8자 이상 힌트를 붙이고 백엔드 RegisterRequest min_length를 함께 올린다(N-04). 4. 등록 입력에 도메인 점 정규식과 `maxLength={100}`을 추가한다. 5. 422 정규화는 CV-01의 ApiError를 소비하거나 CV-01이 흡수할 최소 normalizeDetail만 넣는다. |
| 검증 교정 | 반박 1건 — "EmailStr 가입 시 [object Object]"는 대부분 차단돼 있다(`LoginForm.tsx:91,94` type=email과 required로 무점 도메인 `user@localhost`와 100자 초과만 도달). "username type=email 선검증"은 로그인 모드에 잘못된 처방이다(LoginRequest는 비이메일 username을 의도적으로 허용하고 seed admin이 그렇다). "8자 이상"을 로그인에 적용하면 기존 4~7자 계정이 잠긴다. source_ids에서 D-10은 DS-06 몫이므로 제거한다. 선택 추가 — `i18n.ts:180` `t.loginDesc`가 모든 모달에 노출되므로 embedded description prop으로 정리한다. |

### DS-09 — PageShell과 layout Providers: 페이지 래퍼 10곳 통합, 인증 공백, 언어 플래시, 랜드마크

| | |
|---|---|
| 심각도(교정) | P2 |
| 공수(교정) | L (14~20h) 유지. 약 25파일 접촉, 쿠키 SSR 언어를 넣으면 20h 쪽 |
| 페이지/영역 | 전체 |
| 번들/PR | B2 PR3 (DS-19 fix 2, N-03, N-11, CV-16 fold-in 동반) |
| 근거 요약 | `app/{cost,reliability,efficiency,analysis,models,parity,gpt-on-aws}/page.tsx` 7파일이 70행 동일(치환 4행)이고 claude-features 62행, prompts 111행이다. LanguageProvider가 10곳에 마운트되고 `tsc --noUnusedLocals`가 9파일에서 미사용 import 3개와 미사용 훅 결과 2개를 잡는다. `if (!authChecked) return null`이 9곳이라 `/api/auth/me`(TTFB 1.02s) 동안 헤더까지 백지이고, 검증에서 더 강한 사실이 나왔다 — `/cost`, `/models`, `/parity`, `/claude-features`의 SSR body가 가시 문자 0개다(`return null`이 서버에서도 적용돼 익명 사용자와 크롤러가 빈 페이지를 받는다). `lib/i18n-context.tsx:14-21`이 `useState("ko")` 후 useEffect라 EN 사용자는 페이지마다 KO 플래시를 보고 `setLang`이 documentElement.lang을 갱신하지 않으며 `app/layout.tsx:36`은 정적 `lang="ko"`다. h1이 6곳, 페이지 제목 h2가 4곳이고 `<main>`과 스킵 링크가 없다. `api.ts:76-80` fetchMe가 모든 !ok를 "인증 만료"로 뭉개 10곳의 `.catch(() => setToken(null))`이 5xx에도 로그아웃한다. |
| 수정안 | 1. `app/layout.tsx`에 Providers(Language, Auth, Theme)를 1회 마운트하고 언어는 `setLang`이 쿠키를 기록하고 서버 layout이 `cookies().get("lang")`으로 `<html lang>`과 initialLang을 시드한다(전 페이지 force-dynamic이라 비용 0, 인라인 스크립트는 보조). 2. `components/PageShell.tsx`(navKey, title, subtitle, actions, maxWidth) — 스킵 링크, AppHeader, `<main id="main">`, h1 하나(text-2xl), children, FloatingChat, 로그인 Dialog. 인증 확인 중에는 헤더와 콘텐츠를 즉시 렌더하고 로그인 슬롯만 같은 크기 스켈레톤으로 둔다(하드 요구사항). 3. fetchMe가 status를 노출하게 바꿔 401, 403만 로그아웃한다(CV-07과 상호 참조). 4. 9개 page.tsx를 약 10행으로 축소하고 패널 내부 h1과 h2를 제거하며 SectionTitle로 통일한다. 5. `/?tab=manual`을 URL화한다(Next 14는 useSearchParams에 Suspense 경계가 필요하고 `app/page.tsx:183` `<main>`은 중첩을 피해 div로 바꾼다). |
| 검증 교정 | 13/13 근거가 재현됐다. `return null`은 "로그인 → 사용자명" 플립을 피하려 넣은 것으로 보이므로 스켈레톤 요구를 명시해야 하며, 9개 중 8개 페이지 본문은 공개 데이터라 즉시 렌더 가능하고 /prompts만 게이트로 남는다. AuthProvider가 `auth-changed` window 이벤트(`api.ts:37-40`)를 대체할 수 있다. `/chat`은 Provider가 없어 `ChatPanel.tsx:51`의 useLang이 "ko"에 고정되는데 layout Providers가 이를 무료로 고친다. 컨테이너 폭 불일치는 Analysis 외에 `PromptsPanel.tsx:141` max-w-6xl도 있어 2건이고, "미사용 import 5개"는 정확히 import 3개와 미사용 훅 결과 2개다. |

### DS-19 — 테마 크롬과 라우트 경계: theme-color 동기화, 시스템 테마, not-found와 error, 오프라인 배너

| | |
|---|---|
| 심각도(교정) | P2 유지 |
| 공수(교정) | M (8~12h) 유지, 재구성 후 약 10.5~11.5h. 분할 권고 — DS-19a 테마 크롬(B4, 약 4h) / DS-19b 라우트 경계와 오프라인, 설치(B2, 약 7h) |
| 페이지/영역 | 전체 (설치형 PWA 포함) |
| 번들/PR | B2 PR3(fix 2 경계 파일), B4 PR8(잔여, N-12 동반) |
| 근거 요약 | `app/layout.tsx:27` themeColor "#030712" 정적(주석이 "화이트 토글은 수동이라 정적 값 유지"로 한계를 자인), `manifest.ts:16-17` 다크만, `:17` black-translucent. `lib/theme.ts:12,18-19`가 2상태이고 SSR 기본이 dark이며 src 전체에 matchMedia와 prefers-color-scheme이 0건이다. `src/app`에 not-found, error, global-error, loading이 0건이라 라이브 `/this-page-does-not-exist`가 Next 기본 영문 404이고 `body{background:#fff}`를 주입해 앱 테마와 Inter 폰트까지 무시한다. `navigator.onLine`, beforeinstallprompt, serviceWorker가 0건이고 i18n에 404와 오프라인, 설치 문구가 없다. 런타임 예외 시 "Application error" 기본 문구는 RSC 페이로드와 next error-boundary로 확정했다. |
| 수정안 | 1. `setTheme()`에서 meta theme-color를 갱신하고 테마를 3상태(시스템, 다크, 라이트)로 만들며 matchMedia로 초기값을 잡는다. ThemeToggle을 SVG와 a11y 라벨로 바꾸고 manifest에 lang, id, shortcuts를 넣으며 `manifest.ts:11` 설명의 가운데 점을 쉼표로 고친다. 2. `app/not-found.tsx`(KO와 EN "페이지를 찾을 수 없습니다", 주요 링크), `app/error.tsx`(ErrorState block, reset(), `window.RumSDK.addCustomEvent("render_error", …)`), `global-error.tsx`. 루트 loading.tsx 1개만 두고 라우트별 loading.tsx는 만들지 않는다. 3. OfflineBanner를 `app/layout.tsx`에 1회 마운트한다("오프라인 상태입니다. 연결되면 자동으로 갱신합니다."), beforeinstallprompt는 "앱 설치" 메뉴로. |
| 검증 교정 | 갭은 실재하지만 수정안 3건이 이 스택에서 그대로 동작하지 않는다. 1. iOS 홈 화면 앱 상태바는 theme-color가 아니라 `apple-mobile-web-app-status-bar-style`(실행 시 고정)이 결정하므로 meta 동기화로는 안 고쳐진다(statusBarStyle "default" 전환 또는 safe-area 띠 고정 중 택일, 실기기 검수 필수). 2. rum-sdk 공개 API에 recordError가 없고 React 18 prod는 경계가 잡은 예외를 console.error로만 남기므로 error.tsx 도입 시 오히려 RUM에서 예외가 사라진다 — addCustomEvent 명시 호출과 타입 확장이 필요하다(부수 발견 `RumProvider.tsx:37` appVersion "2.16.2" 하드코딩). 3. 11개 페이지 전부 "use client"라 첫 로드 상태는 패널이 소유하므로 라우트별 loading.tsx는 이중 스켈레톤이다. PageShell과 ErrorState가 아직 없으므로 not-found와 error는 LanguageProvider와 AppHeader를 자체 마운트한다. |

### DS-01 — 헤더 우선순위 내비와 브랜드 블록 보호: 1024~1700px 붕괴 종결

| | |
|---|---|
| 심각도(교정) | P1 유지 |
| 공수(교정) | M (8~12h). Playwright 회귀 2~3h는 N-10이 B1에서 끝내므로 B2에서는 5~8h |
| 페이지/영역 | 전체 (AppHeader) |
| 번들/PR | B2 PR4 |
| 근거 요약 | `AppHeader.tsx:29-41` 내비 11개(`useNavItems`, 10개 page.tsx 전부 사용), `:48` 항목 `whitespace-nowrap`(자연폭 KO 960px, EN 1164px), `:84` justify-between, `:86,92-95` 브랜드 블록이 `min-w-0`와 truncate에 3줄 스택이라 shrink 보호가 없고 `:99` 우측 그룹이 `shrink-0`라 남는 폭을 브랜드가 0px까지 흡수한다. 라이브 재측 — 1024px `/cost` 헤더 254px, h1 폭 0, 설명 11줄, 문서 scrollWidth 1175(가로 스크롤 +151), `/` 1282(+258); 1280px `/cost` 헤더 142px에 h1 "A…"; 1440px `/cost` h1 197/267; EN 1440px h1 0px에 헤더 158px. Playwright `waitForSelector('header h1')`이 1024px에서 hidden으로 타임아웃한 것 자체가 증거다. `app/page.tsx:160` 사이드바가 `lg:top-[57px]`를 가정한다. |
| 수정안 | 1. 헤더 높이를 `h-14` 1행으로 고정하고 브랜드를 `shrink-0 min-w-[10rem]`으로, 설명과 버전은 `2xl:block`, 제목은 짧은 브랜드명 "LLM Monitor"로 통일하고 전체명은 title과 sr-only에 둔다(`layout.tsx`의 application-name이 이미 "LLM Monitor"다). 2. ResizeObserver 기반 priority+ 내비와 "더보기" 오버플로 메뉴. 관측 대상은 nav만이 아니라 우측 그룹 전체(언어와 테마, 내비, 로그인, actions)여야 대시보드 1250px에서도 성립한다. 접힘 우선순위는 뒤에서부터 프롬프트, 수동 프로브, Claude API 기능, GPT on AWS, 패리티 런. 3. `aria-current="page"`, nav aria-label, 모바일 메뉴 id와 aria-controls, Escape와 외부 클릭, pathname 변경 시 닫기, 스크림. 4. `--header-h` 변수로 `page.tsx:160` 계약을 복원한다. 5. 회귀 조건은 1024/1280/1440/1512(KO와 EN 각각)에서 `documentElement.scrollWidth === innerWidth`, 헤더 높이 ≤64, `h1.clientWidth >= 120`, aside sticky top === 헤더 높이. |
| 검증 교정 | 정정 2건. 1. 붕괴 범위 과소 — fit 임계는 KO 서브페이지 약 1510px, KO 대시보드(actions 슬롯 +107px) 약 1620px, EN 약 1715px이라 "1024~1499"가 아니라 1024~1700px이며 MacBook Air 13"(1440)과 Pro 14"(1512)에서도 대시보드 제목이 잘린다. 2. 사이드바 57px 계약은 아무것도 깨지지 않는 1920px에서도 헤더가 94px(3줄 스택 + py-3)이라 모든 데스크톱 폭에서 어긋난다. 미세 차이 — EN 1440의 3px 가로 오버플로는 재현되지 않고 1366 헤더는 174 → 110이다. 감사가 인용한 `shots/*.png`는 이 스크래치패드에 없어 `verify-ds01/header_{1024,1280,1440}_ko.png`와 `header_1440_en.png`로 재생성했다. |

### DS-12 — 챗 표면 반응형: ChatModal 시트화, FAB 48px와 safe-area, 포인터 이벤트, 게스트 노출

| | |
|---|---|
| 심각도(교정) | P1 (범위 한정) — (a) 390px에서 ChatModal이 138px 화면 밖(Android Chrome, Samsung Internet, iOS standalone PWA, 좁은 데스크톱 창), (b) 96px 오프셋의 64px FAB가 모든 방문자에게 카드 지표를 가린다(단독 P2). 포인터 드래그, 게스트 노출 정책, aria-label 혼재, i18n은 P2와 P3 |
| 공수(교정) | 권고 범위(fix 1, 3, 4)만 M (6~9h). 5개 전부면 L (12~16h) |
| 페이지/영역 | 전체 (FloatingChat, ChatModal, ChatPanel, /chat) |
| 번들/PR | B2 PR7 (N-18 동반) |
| 근거 요약 | `chat/ChatModal.tsx:83-84` `w-[504px] h-[640px]` 고정(`:14` 주석이 인용한 `sm:items-end`가 `:84`에 없음), `:90` onMouseDown 전용 드래그(repo에 onPointerDown 0건), `:53` `if (!open) return null`이 ChatPanel을 언마운트해 오버레이 클릭 한 번에 messages와 sessionId가 죽는다. `FloatingChat.tsx:87` `fixed bottom-24 right-6 w-16 h-16`이고 `globals.css:207-216` safe-area 패딩은 header.sticky와 body에만 적용돼 fixed FAB에는 무효다. 라이브 실측 — 390×844에서 FAB가 x302~366, y684~748로 Fable 5.1 (Global) 카드의 "2088 ms"와 "총 응답시간 2.5s"를 덮고, 768×1024에서는 Fable 5 (Global)의 "성공" 배지와 "2940 ms"를 덮는다. ChatModal 클래스를 주입하면 390px에서 left = −138px다. `:52-55` 비로그인에도 노출, `:88-89` aria-label EN과 title KO 혼재, 챗 문자열은 i18n 키 0건. |
| 수정안 | 1. ChatModal을 Dialog size=chat으로 — `w-[min(504px,calc(100vw-1rem))] h-[min(640px,calc(100dvh-2rem))]`, `<sm` 하단 시트(100dvh, safe-area), Pointer Events 드래그와 setPointerCapture, 위치 localStorage, textarea 자동 높이. 2. FAB를 48px로 줄이고 `bottom: calc(1rem + safe-area)`, 스크롤 시 축소, 비로그인은 툴팁 또는 숨김, 로그인 모달은 PageShell 재사용. 3. 터치와 standalone에서 팝업 새 탭을 금지한다(`useUaPopupStrategy.ts:24-34`, standalone PWA UA에 "Safari"가 없어 프로젝트 자체 PWA가 504px 모달을 맞는다). 4. `app/chat/page.tsx:9` `h-screen`을 `h-dvh`로(N-18). |
| 검증 교정 | 수치 교정 — "390px에서 114px 밖"은 138px이다(right-6 앵커 24px 가산). FAB x 범위는 294~358이 아니라 302~366이다. 범위 중복 2건을 제거한다 — fix 2(hidden 유지와 sessionStorage, 바닥 근접 자동 스크롤, aria-live, 경고와 오류 분리)는 CV-18이, fix 5(chat.* i18n과 /chat Provider)는 DS-18과 DS-09가 소유하며 `backlog-design.md:510` 자체가 "DS-12는 표면과 레이아웃만"이라고 적었다. 의존 명시 — fix 1은 DS-06 Dialog, fix 3의 로그인 모달 재사용은 DS-09 PageShell. |

### 2.3 B3 — v2.27.0 데이터 신뢰, 신선도, 포맷, 백엔드 성능

### CV-09 — 카드 "-" 사유 표기: stop_reason과 워크로드 칩, 추론 모델 TTFT 정의 정리

| | |
|---|---|
| 심각도(교정) | P1 유지, 프론트 "사유 표기"에 한정. 백엔드 TTFT 재정의와 ttfb 컬럼은 P2 후속으로 분리 |
| 공수(교정) | M (8~12h) 유지, `truncated` 상태 분리를 제외하는 조건. 포함 시 L (14~18h) |
| 페이지/영역 | / (ModelStatusGrid, TrendChart) |
| 번들/PR | B3 PR4 |
| 근거 요약 | 라이브 18:57Z `/api/auto-probe/latest`(run #29540, category reasoning) 43행 중 20행이 `ttft_ms` null, `tps` null, `output_text` "", `stop_reason` max_tokens, `status` success이고 `output_tokens == 512 == max_tokens`다. `trend?hours=1`은 null이 48/473이다. 원인은 `prober.py:468-472`, `:534-539`, `:356-359`가 텍스트 델타에서만 first_token_time을 설정하고 3 surface 모두 thinking 파라미터를 보내지 않는 것이며, claude-api 대조 결과 Fable 5와 5.1은 thinking 상시 ON, Opus 5와 Sonnet 5는 생략 시 adaptive ON이라 라이브에서 공백 모델(5세대)과 텍스트를 낸 모델의 경계가 정확히 여기서 갈린다. UI는 `ModelStatusGrid.tsx:166,:188`이 "-"만 찍고 stop_reason과 category 렌더가 0건이며 `types.ts:6-24` ProbeResult에 stop_reason 필드가 없다(API는 반환 중). `TrendChart.tsx:211` connectNulls로 추론 사이클이 소실된다. |
| 수정안 | 1. 상태값 신설 없이 `status==="success" && ttft_ms===null && stop_reason==="max_tokens" && output_tokens>0`을 lib 순수 함수(vitest)로 판정해 amber 칩 "텍스트 미생성"과 툴팁을 붙인다(한도 숫자는 output_tokens에서 유도, 512 하드코딩 금지). 2. 워크로드 칩은 AutoDashboard가 이미 로드한 categories를 ModelStatusGrid에 내려 label_ko와 label_en으로 표기하고 stop_reason 칩은 `AnalysisPanel.tsx:42-50` labelStopReason 맵을 lib로 승격해 쓴다. 3. `truncated` status 분리는 채택하지 않는다. 4. TTFT 정의는 유지하고 ADR로 기록하며 추론 모델용 `ttfb_ms` 보조 컬럼은 별도 P2 항목으로 둔다. 5. `i18n.ts:197` overloadedHint를 "공급자 일시 과부하입니다. 2초, 4초, 8초 간격으로 자동 재시도했고, 다음 5분 주기에 다시 시도합니다."로 교체하고 `ModelStatusGrid:202,209` 인라인 영어를 i18n으로 옮긴다. |
| 검증 교정 | 보정 3건. 1. "21행"은 사이클마다 20~23행이다(thinking 길이가 비결정적). 2. "해당 모델 전부"가 아니라 호출별 확률 사건이다(같은 세대라도 Fable 5 CP와 Global, Luna와 Terra us-east-1은 텍스트를 일부 생성). 3. 추론 사이클만이 아니다 — `?category=code-gen`에서도 4행이 null이다. 설계 결함 2건 — `truncated` 분리는 백엔드 `status=="success"` 필터 20곳에 ripple을 일으켜 `cost.py:92,159,223`에서 과금된 thinking 토큰이 비용 집계에서 탈락하고 `anomalies.py:24`가 30분마다 거짓 경보 20건을 만들며 성공률이 약 53%로 떨어진다. reasoning max_tokens 상향은 비용 결정이다(512 → 2048 시 약 +$37/일, 현재 약 $12/일). `gptbench.py:4`가 이미 TTFB와 TTFT, GAP을 정의해 발표했으므로 prober만 TTFT를 바꾸면 사이트 내 정의가 분열된다. |

### DS-10 — lib/format.ts: 시각과 상대시각, 타임존, 통화, 숫자, 퍼센트 단일화

| | |
|---|---|
| 심각도(교정) | P2 |
| 공수(교정) | M (8~10h), 범위 축소 후 |
| 페이지/영역 | /, /cost, /efficiency, /parity, /gpt-on-aws, /analysis, 인사이트 |
| 번들/PR | B3 PR5 (CV-12 fold-in 7건 동반) |
| 근거 요약 | 라이브 KO `/parity` 상태줄이 "최근 런 #128 · 9/7/2026, 3:12:59 PM"으로 렌더되고 본문에 KST나 UTC 토큰이 없다(`ParityPanel.tsx:503`, `GptOnAwsPanel.tsx:138,247`, `ClaudeFeaturesPanel.tsx:201` 모두 무인자 toLocaleString). `pivotTrend.ts:40-43`이 "ko-KR"을 하드코딩하고 lang 파라미터가 없다. `AutoDashboard.tsx:15-31`과 `ModelStatusGrid.tsx:84-93`은 hoursAgo에서 멈추고(i18n에 daysAgo 없음) 렌더 지점에 title이 없다. `pricing.ts:87-92` formatCost가 라이브 값에서 "$4.2745", "$84.38¢", "$8.13¢"를 한 열에, "$1.48¢"와 "$0.28m"를 호출당 열에 만들고 30일 예상은 "$1967.1745"로 769px에서 넘친다(값 박스 137px vs scrollWidth 146, "$1,967.17"은 들어감). `AnalysisPanel.tsx:209` toFixed(0)이 69.5/30.5를 70%+31% = 101%로 만든다. `/api/gptbench/latest`의 region "global"이 `GptOnAwsPanel.tsx:292`에 소문자로 노출된다. frontend/src 어디에도 lib/format.ts와 Intl 사용이 없다. |
| 수정안 | 1. `lib/format.ts`(vitest) — `fmtDateTime(iso, lang, {tz:"Asia/Seoul"})`에 "KST" 리터럴 접미(Intl short는 "GMT+9"를 낸다), `hourCycle:"h23"`(hour12:false + 2-digit은 "24:12:59"를 낸다), `fmtRelative`와 `<RelativeTime>`(time title에 절대시각), `fmtCurrency`(≥$1 2자리와 천 단위, <$1 4자리 고정, <$0.0001은 "<$0.0001"과 title, 접미 기호 제거), `fmtInt`, `fmtPctParts` 최대 잔여법, `fmtRegion`. 2. 모든 호출부를 채택하고 formatCost는 fmtCurrency에 위임한다. 3. pivotTrend에서 포맷을 제거하고 TrendChart가 useLang과 tickFormatter로 처리한다(rangeHours는 prop). 4. 요약 카드는 `text-xl md:text-2xl`과 축약. 5. v2.24.0 머지 후 그 릴리스의 formatDuration과 formatMs를 format.ts로 이동해 재export한다. |
| 검증 교정 | 과대 2건 — CostDashboardPanel의 정수 toLocaleString 8곳은 ko-KR과 en-US 출력이 같아 사용자에게 보이는 결함이 아니고, `InsightsPanel.tsx:110`은 이미 lang 기반 로케일을 넘긴다(TZ 라벨만 없음). 범위 축소 — fix 3의 상태줄 카피와 "다음 예정" ETA는 DS-17 소유이며 백엔드 next_run_time이 필요하다(패리티는 cron이 아니라 rate(12h)). 축 dedupe와 XAxis 재작성은 DS-07 몫이고 DS-10은 pivotTrend에서 포맷을 걷어내는 데까지다. CV-12의 통화 규칙 `maximumFractionDigits: usd<0.01?4:2`는 0.0148을 "$0.01"로 만들어 Avg/call 열의 변별력을 없애므로 폐기하고 위 규칙을 쓴다. 앵커 교정 — toFixed(0)은 `:207`이 아니라 `AnalysisPanel.tsx:209`다. |

### DS-08 — useAsyncData와 Skeleton: stale-while-revalidate, 기간 전환 레이스 종결

| | |
|---|---|
| 심각도(교정) | P1 유지. P1의 원천은 레이스 단일 성분(비용 페이지 기간 라벨과 총 비용, 30일 예상 동시 불일치, 라이브 재현). 스켈레톤과 로딩 통일 성분만 보면 P2 |
| 공수(교정) | M (10~14h) 유지, 약 12h. Parity와 ClaudeFeatures 채택은 v2.24.0 머지 후 +2h로 분리 |
| 페이지/영역 | /cost, /reliability, /efficiency, /analysis, /gpt-on-aws, /models, /prompts, 인사이트, HistoryPanel |
| 번들/PR | B3 PR6 (CV-06 fold-in 동반) |
| 근거 요약 | 레이스를 실브라우저에서 결정적으로 재현했다 — `/cost`에서 `window=7d` 응답만 6초 지연 주입 후 7일 → 24시간 클릭 시, 활성 버튼 "24시간"과 부제 "최근 24h"가 유지된 채 총 비용이 $443.79(=7d 실값)로 덮이고 30일 예상이 $13,313.70(올바른 값 약 $1,901의 약 7배)이 됐다. `CostDashboardPanel.tsx:36-55`, `ReliabilityPanel.tsx:66-81`, `EfficiencyPanel.tsx:39-52`, `AnalysisPanel.tsx:73-92`에 AbortController가 0건이고 `api.ts`의 signal은 auto-probe 3함수(186, 194, 205)만 지원한다. 로딩 삼항이 콘텐츠를 언마운트하고(Cost 160-161, 192-193, Reliability 126-127, Efficiency 120-121) 요약 카드가 "—"라 빈 데이터와 구분되지 않으며 disabled, aria-busy, role=status가 전부 0건이다. 실측 응답 시간은 cost 24h 1.30s / 7d 4.54s, reliability 3.98/7.90s, efficiency 2.43/9.67s, stop-reasons 7d 13.29s로 7d가 2~4배 느리다. |
| 수정안 | 1. `lib/useAsyncData.ts` — `{data, prev, status, error, fetchedAt, retry}`, cleanup에서 abort, 최신 AbortController 동일성 비교(`AutoDashboard.tsx:95-123`의 올바른 패턴을 훅으로 추출), keepPrevious. 폴링 정지는 CV-10, 오류 UI는 DS-02 소유이므로 훅은 fetchedAt만 노출한다(DS-17이 소비). 2. `components/ui/Skeleton.tsx`(stat, card, row, chart, count) — 첫 로드는 레이아웃 보존 스켈레톤, 재검증은 opacity-60과 진행 바에 aria-busy, 컨트롤 disabled, 로딩 문구 role=status 1종. 3. 섹션 독립 로드(allSettled). 4. `api.ts` GET 페처 12개에 선택 signal 파라미터(호환 변경). 5. 1차 채택은 4패널과 GptOnAws, Models, Insights, Prompts, HistoryPanel(`:244-246` 스피너), 2차는 Parity와 ClaudeFeatures. |
| 검증 교정 | 필수 정정 3건. 1. CV-06은 같은 4파일과 같은 source_ids의 동일 항목이라 M 6~8h가 이중 계상됐다 — DS-08로 통합한다. 2. CV-06 fold-in — `CostDashboardPanel.tsx:60-64` monthlyEstimate가 `window` 상태 문자열로 시간을 나누므로 abort를 넣어도 keepPrevious 구간에서 7배 과대가 재발한다. `summary.window` 또는 since에서 시간을 유도해야 한다. 3. `window_hours` 의존은 삭제한다(응답에 이미 window와 since가 있다). "7d 10.9s / 24h 3s"는 감사 시점 reliability 값이다. jsdom과 @testing-library가 미설치라 테스트 인프라가 필요하지만 N-10이 B1에서 해결한다. |

### DS-17 — FreshnessBadge와 스케줄 지연 경보: 4 분석 패널, 대시보드 상태바, 패리티와 벤치 상태줄

| | |
|---|---|
| 심각도(교정) | P2 유지. 수치 자체는 정확해 P1이 아니지만 라이브에서 사이클 누락 26분 무표시, 6분 장애 중 무표시, 배너 오신호가 동시에 확인돼 P3도 아니다 |
| 공수(교정) | M (10~14h), 훅 v2(CV-10)와 푸터, SHA, 문서 링크(CV-13), 토스트(DS-15)를 분리한 기준. 원안 전 범위는 L (14~20h) |
| 페이지/영역 | /cost, /reliability, /efficiency, /analysis, /parity, /gpt-on-aws, / (상태바) |
| 번들/PR | B3 PR7 (CV-13 F-2, CV-11 fold-in 7건 동반) |
| 근거 요약 | `cost.py:69`, `reliability.py:131`, `efficiency.py:96`이 since를 반환하는데 UI가 표시하지 않고 `analysis.py:85-88,150-153`은 since 자체가 없다(계약 불일치). useAutoRefresh 사용처가 `AutoDashboard.tsx:155` 하나이고 4패널은 자동과 수동 새로고침이 없다(Analysis만 수동). `AutoDashboard.tsx:38` `Math.max(0,…)` clamp 때문에 next_run_time 경과 후 "0분 00초"가 무한 표시된다. 라이브 추가 실측 3건 — 18:23Z 시점에 gptbench 18:12 사이클이 누락됐는데 `/latest`가 26분 전 사이클을 정상 카드로 표시했고, 18:16:48~18:20:15Z에 9경로가 전부 5xx인 동안 대시보드는 옛 데이터와 카운트다운을 유지했으며, `anomalies.py:12-36`이 행 수만 세므로 스케줄러 정지 시 `AutoDashboard.tsx:218-230`이 초록 "프로브 0회 전체 성공"을 오표시한다. `AppHeader.tsx:95` 버전이 `hidden sm:inline`이고 `<footer>`와 PRICING 상수가 0건이다. |
| 수정안 | 1. `components/ui/FreshnessBadge.tsx`(since, fetchedAt, nextRefreshIn, lagWarnAfterSec, onRefresh) — "기준 2026-09-07 16:26 KST 이후 24시간, 32초 전 조회, 28초 후 갱신" + IconButton(aria-busy), 지연 시 amber "예정 시각 3분 경과", 15분이면 rose role=alert "자동 프로빙이 지연되고 있습니다. 운영자 확인이 필요합니다." 2. 배치는 AppHeader actions 슬롯이 아니라 각 패널 헤더 행이다(actions는 모바일에서 안 보인다). 3. 백엔드 계약 4건 — analysis since 2줄, `/status`의 소요 시간과 프로브 수는 신규 컬럼 대신 probe_results count와 max 집계(PR #51 마이그레이션 사고 직후라 컬럼 추가 비권장), parity/latest에 next_expected_at과 interval_seconds(rate(12h) 위상 하드코딩 금지)와 `started_at > now()-2h` 스테일 가드, gptbench/latest에 interval_seconds. 4. fetchedAt은 `/api/auto-probe/*` edge 캐시 s-maxage=30 때문에 최대 30초 낙관적이므로 "조회 성공 시각"으로 표기하고 서버 since를 우선한다. 5. 상태바 개편 시 항상 "대기 중"인 죽은 current_cycle_running 필과 total_probes===0 오신호를 함께 정리한다. |
| 검증 교정 | 인용 근거 11개가 전부 재현됐다. 오류 1건 — 수정안 예시 "다음 예정 03:00 KST"는 UTC 오표기다(run #128이 15:00:09Z이므로 다음은 03:00Z = 12:00 KST). CV-11이 source_ids와 수정안, 예시 문구까지 동일한 중복 항목이므로 DS-17을 정본으로 하고 CV-11은 폐기한다. 선행 조건에서 DS-09 PageShell을 제거한다. 시각 포맷은 DS-10과 v2.24.0의 formatDuration을 공유하고 재구현하지 않는다. 훅 렌더 테스트는 지연 단계와 문구 로직을 lib 순수 함수로 분리한다. `docs/api-reference.md:43-55`가 문서화한 `/status`의 model_count가 실제 응답에 없으므로 계약 변경 시 함께 정합한다. |

### CV-10 — useAutoRefresh v2: 숨은 탭 정지, 실패 백오프, 설정 기억

| | |
|---|---|
| 심각도(교정) | P2 유지, 근거 축 교체 — 배터리와 트래픽이 아니라 "탭 복귀 즉시 갱신 부재, 장애 중 고정 주기 무음 폴링, 토글 미영속" |
| 공수(교정) | S (4~6h) 재범위 기준. 원안 전 범위(타임아웃과 재시도, OfflineBanner)는 M (8~10h)이나 그 둘은 CV-01과 DS-19 소유 |
| 페이지/영역 | 전체 (/ 30초, InsightsPanel 60초, /gpt-on-aws 60초, 분석 4페이지 예정) |
| 번들/PR | B3 PR8 |
| 근거 요약 | `hooks/useAutoRefresh.ts:19-27`이 setCountdown updater 안에서 `callbackRef.current()`를 호출하는 부수효과 구조이고 `:5` 콜백 타입이 `() => void`라 실패를 관측할 수 없어 백오프가 불가능하며 `:6` enabled가 영속되지 않는다. 프로젝트와 로컬 브랜치 25개 전수 grep에서 `visibilitychange`, `navigator.onLine`, `AbortSignal.timeout`이 0건이다. `InsightsPanel.tsx:39-43`과 `GptOnAwsPanel.tsx:188-191`이 별도 setInterval을 돌린다. `edge-stack.ts:54` readTimeout 60초. 라이브 19:03Z 약 2분간 trend와 insights, gptbench가 502(awselb, 122B)인 창에서 고정 주기 무음 실패가 반복됐다. |
| 수정안 | 1. `useAutoRefresh(callback, {intervalMs, key})` — 콜백을 useEffect에서 실행하고 document.hidden이면 정지하며 복귀 시 즉시 1회 갱신, 연속 실패 시 30 → 60 → 120초 백오프, enabled는 mount 후 useEffect에서 localStorage로 복원(하이드레이션 불일치 회피). 2. 훅은 nextAt만 반환하고 1초 state는 `<RefreshCountdown/>`이 격리한다(`AutoDashboard.tsx:157-165`의 두 번째 interval도 이관, N-09와 절반 공유). 3. 콜백 계약을 `() => Promise<unknown> | void`로 바꾸고 소비자 3곳(`AutoDashboard.tsx:114-117`, `InsightsPanel.tsx:32-34`, `GptOnAwsPanel.tsx:177-179`)이 catch 후 rethrow하거나 boolean을 반환하게 한다. 4. Insights와 GptOnAws의 setInterval을 훅으로 교체한다. 5. `lib/refreshSchedule.ts` 순수 함수로 vitest. |
| 검증 교정 | 반박 5건. 1. "30초마다 272KB"는 wire 기준 약 15배 과대다 — auto-probe 경로는 compress:true와 s-maxage=30이라 br wire가 `/latest` 4,142B, `/trend?hours=1` 13,857B로 1폴링 약 18KB다(hours=24만 561KB). 2. "장애 시 폭주 방지"는 edge 캐시가 이미 흡수한다. 3. Chrome 88+ intensive throttling으로 숨은 탭 폴링은 5분 이후 사실상 정지하므로 진짜 격차는 복귀 즉시 갱신 부재다. 4. fix 2의 apiFetch 타임아웃은 CV-01, fix 3의 OfflineBanner는 DS-19가 문구까지 동일하게 소유한다. 5. 소비자 3곳이 오류를 삼켜 콜백 계약 변경 없이는 백오프 구현이 불가능한데 원안이 이를 빠뜨렸다. 크리틱의 초기 병합 맵(CV-10을 DS-17과 DS-08에 흡수)은 방향이 틀렸고 CV-10을 스케줄러 훅 단일 소유자로 둔다. |

### 2.4 B4 — v2.28.0 시각 시스템과 접근성, v2.28.1 i18n과 편의

### DS-16 — StatusPill과 Badge, channelColors.ts, thresholds.ts

| | |
|---|---|
| 심각도(교정) | P2 유지. 제목의 "필 4종"은 10종으로, "BEST 43/43"과 "TTFT null 사유 배지"는 제목에서 제거한다(CV-19와 CV-09 소유) |
| 공수(교정) | M (8~12h) 재범위 기준 8.5~11.5h(BEST와 TTFT null 배지 제외, `cost.py _channel()` OpenAI 분리 포함). 원안 6항목 전부면 M~L (11~15h) |
| 페이지/영역 | /, /cost, /reliability, /efficiency, /parity, /gpt-on-aws |
| 번들/PR | B4 PR2 (N-16, N-23 동반). 번들은 원안 B5 접근성이 아니라 B3 토큰 계열이 맞다 |
| 근거 요약 | 상태 필 클래스 조합이 10종 이상이다(`ModelStatusGrid.tsx:62/70/77/227`, `ParityPanel.tsx:232/326/749`, `ReliabilityPanel.tsx:153`, `CostDashboardPanel.tsx:218`, `TrendChart.tsx:152`, `AutoDashboard.tsx:212/259`, `HistoryPanel.tsx:77`, `ModelExplorer.tsx:84`, `ResultsTable.tsx:176`). `CostDashboardPanel.tsx:21-26` CHANNEL_COLORS에 OpenAI가 없어 라이브 43행 중 OpenAI 16행의 배지가 `?? ""`로 무색이 되고(`:218`) 채널 카드는 `:171` bg-gray-800 폴백이다. 채널에서 색으로 가는 맵이 4파일에 따로 있다(Cost 4키, Reliability 8키, ModelExplorer 4키, GptOnAws hex). `AutoDashboard.tsx:429`와 `i18n.ts:154-165` 채널 설명이 2채널뿐이다. 임계값이 `StatsCards.tsx:113-141`과 `ModelStatusGrid.tsx:38-57`에서 불일치하고 `GptOnAwsPanel.tsx:63-75`는 설명이 0건이다. `ReliabilityPanel.tsx:183` `border-current/20`은 Tailwind 3.4에서 규칙이 생성되지 않는다(로컬 컴파일과 라이브 CSS 모두 0건). `ParityPanel.tsx:521-549` 변경 배너가 인라인 span 7개에 slice(0,10)이고 펼치기가 없다. |
| 수정안 | 1. `components/ui/StatusPill.tsx`(tone success, warn, error, info, neutral, skipped / size sm 11px, md 12px / dot, pulse, icon / 텍스트 라벨 필수)와 `Badge.tsx`. 비인터랙티브 전용이며 토글은 DS-14 Chip이 맡는다. 2. `lib/channelColors.ts` `channelOf()` → `{key, label(lang), tone, hex(theme)}`로 Anthropic CP, Bedrock Global, US, OpenAI Global, Mantle 리전을 1곳에서 관리하고 Cost, Reliability, TrendChart, ModelStatusGrid, 채널 설명이 공유하며 미매핑은 가시 폴백. 백엔드 `cost.py:41-53 _channel()`이 openai:*를 "OpenAI"로 합산해 프론트 정규식으로 분리할 수 없으므로 백엔드 분리를 이 항목에 포함한다. 3. `lib/thresholds.ts` 1세트와 `tierOf()`, `<TierLegend>` 컴포넌트. 4. `border-{tone}-500/30`으로 교체. 5. 패리티 변경 배너를 2줄 카드와 StatusPill 2개로 바꾸고 기본 5건에 "모두 보기". 6. 즉시 핫픽스 2건 — `CostDashboardPanel.tsx:218` `?? ""`를 가시 폴백 클래스로, `ReliabilityPanel.tsx:183`을 border-gray-700으로. |
| 검증 교정 | 근거 10건 중 9건 확인, 1건은 시간 의존이다. 편의 백로그와 이중 등재가 핵심 문제다 — 수정안 5(TTFT null 배지)는 CV-09 수정 1과 문구까지 동일하고 수정안 4(BEST 단일 승자, 이상치 warn)는 CV-19 수정 2와 5, 채널 설명 OpenAI 카드와 TierLegend는 CV-19 수정 2, 3, 4에 있다. 따라서 DS-16은 프리미티브와 channelColors, thresholds, border, 변경 배너만 소유하고 BEST와 TTFT null 로직은 CV-19와 CV-09가 DS-16의 `tone="warn"`을 소비한다. 축소 — TTFT null은 기본 latest에서 검증 시점 0/43이고 `?category=reasoning`에서만 19/43이라 기본 화면 노출은 30분 중 5분이다. "OpenAI 14채널"은 오기이며 16행 4채널 정체성이다. avg_tps 9,240.9는 이동 평균 드리프트로 재측 9,090.97이다. |

### CV-19 — 툴팁 키보드와 터치 접근, 분석 페이지 지표 설명 재사용, 이상치 경고, 티어 범례, OpenAI 채널 설명

| | |
|---|---|
| 심각도(교정) | P2 유지 |
| 공수(교정) | M (8~10h) 유지, DS-15 Tooltip과 DS-16 TierLegend, channelColors를 소비하는 재범위 기준 8.5~11.5h. 프리미티브까지 단독 구현하면 M~L (12~15h) |
| 페이지/영역 | / (카드, 채널 설명), /reliability, /efficiency, /gpt-on-aws, /analysis |
| 번들/PR | B4 PR3 |
| 근거 요약 | `ModelStatusGrid.tsx:17-36` MetricTooltip이 onMouseEnter와 onMouseLeave만 쓰고 라이브 `svg.cursor-help` 129개는 focusable 0, aria 0이며 Tab 80회로 툴팁에 도달하지 못한다. 분석 4패널에 TTFT, p95, TPS 툴팁 자체가 없고 `i18n.ts` metrics.*.desc는 6키뿐이다(p95, GAP, TTFB, 점수 없음). 라이브 avg_tps가 CP Fable 5 9,040.96, Opus 5 4,733.85(타 채널 100~600)인데 `ReliabilityPanel.tsx:179`와 `EfficiencyPanel.tsx:163`이 원값을 그대로 표시하고 `efficiency.py:66-76` min-max 정규화로 TPS 성분이 0.05 미만인 모델이 37/43이며 점수 ≥80이 0개다. `EfficiencyPanel.tsx:19-24` 색 임계에 범례가 없다. `GptOnAwsPanel.tsx:63-75`에 임계 설명이 0건이고 `:292` region이 "global" 소문자이며 median_reasoning_tokens와 errors는 응답에 있지만 UI가 0건이다. `AutoDashboard.tsx:429` 채널 설명 2채널, `ModelStatusGrid.tsx:149-152`가 내부 키를 "실제 호출 model ID"로 표시한다. BEST 배지는 라이브 42/43이다. |
| 수정안 | 1. DS-15의 Tooltip과 Popover를 소비해 분석 4패널 표 헤더와 벤치 카드에 지표 설명을 붙이고 신규 카피(p95, GAP, TTFB, 캐시, 점수)를 작성한다. MetricTooltip은 DS-15 도착 전이라도 button 래핑과 stopPropagation으로 0.5h 핫픽스가 가능하다. 2. TPS 집계를 평균에서 중앙값으로 바꾼다(`reliability.py:204`, `efficiency.py:153,164`). 툴팁 카피는 "TPS는 출력 토큰 수를 첫 텍스트 토큰 이후 시간으로 나눈 값입니다. 추론 토큰이 max_tokens를 소진한 호출은 집계에서 제외합니다." 3. 효율 티어 라벨 배치(80 이상 우수, 60~79 보통, 60 미만 개선 필요). 4. BEST는 `pickBest`(성공률 → p95 TTFT → 채널명) 단일 승자로 하고 동률과 표본 30 미만은 판정 보류, 채널이 1개인 family는 배지를 생략한다(N-23). 5. GPT 벤치 리전 정규화(`gptbench.py:95-99` 백엔드 1줄 권장), median_reasoning_tokens와 errors ReferenceDot(DS-07 뒤). 6. 카드에 `nativeId()` 표시(현재 24/43 오표기, `lib/modelExplorer.ts:86-90`이 이미 있어 프론트 단독 가능). |
| 검증 교정 | 반박 2건. 1. "터치 접근 불가"는 부정확하다 — iPhone 13 에뮬레이션에서 tap 시 툴팁은 열리지만 카드 선택이 함께 토글되므로(ring과 URL 변경) 결함은 stopPropagation 부재다. 2. 원인 문구 "CP 채널은 TTFT 정의 차이로 TPS 과대"는 틀렸다 — TTFT 정의는 3경로 동일하고 원인은 `tps = output_tokens(추론 포함) / (end − 첫 텍스트)`(`prober.py:598-602`)가 추론 사이클에서 폭발하는 것이다. 24h 원본에서 CP Fable 5는 266행 중 tps>1000인 49행이 합계의 99%를 차지하고 중앙값은 90.3이며 Bedrock Global Opus 5도 11행이 84%를 만든다(CP 전용이 아니다). 제안된 `p95×3` 배지는 임계가 2,536이라 845를 놓치고 5~95 클리핑은 p95 자체가 인플레 값이라 폐기한다. 부수 발견 — `getTpsColor`가 추론 사이클 2,354 TPS를 "우수"로 칠하고 StatsCards와 ModelStatusGrid의 TPS 임계가 80/40 vs 50/20으로 다르다. |

### DS-11 — DataTable 프리미티브: min-width, 첫 열 고정, 스크롤 힌트, scope와 caption, 정렬, 모바일 카드 뷰

| | |
|---|---|
| 심각도(교정) | P2 (세 표 모두 overflow-x-auto로 접근은 가능해 차단은 아니다) |
| 공수(교정) | L (16~24h). 분할 권고 — DS-11a DataTable과 5곳 채택 12~18h / DS-11b ModelStatusGrid 토글, 정렬, 필터, 복사 6~10h |
| 페이지/영역 | /cost, /efficiency, /analysis, / (카드 그리드), /reliability, /parity(장기) |
| 번들/PR | B4 PR5(DS-11a, N-17 동반), B4 PR12(DS-11b, CV-15와 같은 PR) |
| 근거 요약 | 390px 재현 — `/cost` 표가 427/356px(min-width 없음, `CostDashboardPanel.tsx:188,199`)에 td 7개가 전부 5줄이고 표 높이 3,580px, `/efficiency`는 510/356px에 헤더 3줄 65px(`EfficiencyPanel.tsx:128-139`), `/analysis`는 n 셀이 15px/46px로 43/43행이 넘치고(`AnalysisPanel.tsx:212`) 이름 열 97px에서 43행이 4종 프리픽스로 붕괴한다(`:193`). 768px `/reliability`는 `md:grid-cols-2`(`:142`)로 고아 카드가 11/15이고 대시보드 43카드는 1열 8,800px이다(`ModelStatusGrid.tsx:107`). `<table>` 8곳 전부 scope, caption, aria-sort가 0건이고 KO 모드에 영문 헤더가 남아 있으며 CSV와 정렬이 없다(`ResultsTable.tsx:50-95`에 정렬 로직만 존재). |
| 수정안 | 1. `components/ui/DataTable.tsx` — columns(key, header, align, width, sortable, format, hideBelow), caption, stickyFirst, minWidth(cost 640, efficiency 760), 클라이언트 sort와 aria-sort, mobile scroll/cards(<640 자동), onExportCsv(CV-15가 핸들러 제공), 우측 그라디언트와 힌트, `th scope="col"`, tabular-nums, 헤더 i18n. 2. 채택은 Cost(KO 헤더 "모델, 채널, 호출, 입력 토큰, 출력 토큰, 호출당, 합계"), Efficiency, Analysis(`grid-cols-[minmax(0,1fr)_2fr_auto]`), ResultsTable, Reliability auto-fit `minmax(220px,1fr)`. 3. 인사이트 표는 DataTable을 끼울 수 없으므로 `MessageMarkdown.tsx:38-43` 렌더러의 table, th, td 스타일(min-w, sticky 첫 열, nowrap, 그라디언트)로 대체한다(약 1h, 챗 말풍선과 공유). 4. DS-11b는 ModelStatusGrid 카드와 표 토글, 패밀리 접기, 정렬, 채널 필터, model_id CopyButton. 5. `ResultsTable.tsx:130-220`의 Fragment key 부재와 인덱스 기반 펼침을 `<Fragment key>`와 `expandedKey=model_id:iteration`으로 고친다(N-17). |
| 검증 교정 | 범위 정정 3건. 1. `ComparePanel.tsx:424`는 어디에도 import되지 않는 데드 코드이므로 채택 대상에서 제외한다(N-21 결정 대기). 2. 인사이트 표 채택은 불가하다(react-markdown 렌더). 3. 매트릭스에서 ClaudeFeaturesPanel은 v2.24.0 머지 후로 순연하고 ParityPanel만 장기 후보다. 수치 보정 — `<table>`은 7 → 8곳(MessageMarkdown 포함), n 열 약 24px → 15px, 모델명은 "전 행 Anthropic Cl…"이 아니라 4종 프리픽스, 고아 카드 10 → 11, 카드 열 8,000 → 8,800px. AP-13의 "text/csv는 ModelExplorer와 PromptsPanel만"은 오류다(0건). sticky 셀은 Cost와 Efficiency 카드가 반투명이라 불투명 토큰이 필요하고, iOS standalone PWA에서 Blob 다운로드가 불안정해 클립보드 TSV 폴백을 병행한다. |

### DS-14 — 컨트롤 프리미티브 SegmentedControl, Chip, Button: aria-pressed와 키보드, 기간 옵션 1세트, 탭 타깃

| | |
|---|---|
| 심각도(교정) | P2 유지. 상태 미노출은 WCAG 4.1.2(Level A), `<tr onClick>`은 2.1.1(Level A)로 P2를 견인한다. 탭 타깃 단독은 P3(24px 헤더는 2.5.8 AA 최소를 충족, 22px 필은 행 피치 34px 간격 예외 통과, 44px는 AAA와 HIG 권고) |
| 공수(교정) | L (12~18h). 2분할 권고 — DS-14a 프리미티브와 windows.ts, 채택 약 8h / DS-14b 패리티 td와 tr, combobox, AppHeader 모바일 약 6h(v2.24.0 머지 후) |
| 페이지/영역 | 전체 |
| 번들/PR | B4 PR6 |
| 근거 요약 | frontend/src 전체 grep에서 aria-pressed, aria-current, aria-checked, role=radiogroup, combobox가 0건이다(aria-expanded는 `AppHeader.tsx:153` 1건). 카드는 `ModelStatusGrid.tsx:113-128` role=button과 tabIndex만이고 칩 6그룹이 상태를 노출하지 않으며 `AnalysisPanel.tsx:128-141` select에 라벨이 없다. `ParityPanel.tsx:604-640` 모델 피커에 combobox 패턴이 없고(onBlur 150ms 타이머) `:697-701` `<tr onClick>`은 키보드로 조작할 수 없다. 탭 타깃 산술이 일치한다 — `AppHeader.tsx:101-115` 24px, `AutoDashboard.tsx:358` 24px, `ParityPanel.tsx:749` 22px. 기간 옵션은 5세트가 아니라 7세트다(위 5곳 + `HistoryPanel.tsx:15,93-100` + `InsightsPanel.tsx:74` "6h" 하드코딩)이고 문자열 window와 숫자 hours 두 표현이 공존한다. |
| 수정안 | 1. `SegmentedControl.tsx`(role=radiogroup과 aria-checked, 방향키, min-h-9), `Chip.tsx`(aria-pressed, count, 색 점, dismiss), `Button.tsx`(variant primary, secondary, ghost, danger / loading → aria-busy / min-h-9), IconButton 44px. 활성 스타일은 `bg-blue-600` 1종으로 통일하고 라디우스는 컨트롤 md, 카드 xl, 필 full로 규정한다. 2. `lib/windows.ts` WINDOW_OPTIONS 1세트를 `{value, hours, labelKey}` 3필드로 만들고 페이지별 allowed 부분집합을 허용한다. CV-03a Literal 도입과 같은 집합으로 맞추며(의존) 대시보드 30d는 `auto_probe.py:165` `le=168` 완화가 선행이다. 3. 카테고리 필터를 Chip 그룹 1종으로. 4. 매트릭스는 `<td>` 전체 클릭, 요약행은 `<button aria-expanded>`, 피커는 combobox 패턴. 5. AppHeader 모바일 언어와 테마를 햄버거 하단으로. |
| 검증 교정 | 교정 5건. 1. "백엔드 Literal과 동일 집합"의 Literal은 현존하지 않는다(4라우터 `_parse_window`는 자유형 파싱과 24h 폴백이며 Literal은 CV-03 제안이다). 2. 기간 세트는 5 → 7이고 GptOnAws는 6개다(3h 포함). 3. 매트릭스 셀은 1,135 → 라이브 1,187이며 런별로 변동한다(약 1,100~1,200개로 표기). 4. 증거 중복 — ModelExplorer 닫기 약 20px는 DS-06, "복사" 2줄은 CV-15 담당이므로 DS-14에서 제거한다. 5. 라이브 SSR에는 button이 0개다(클라이언트 렌더)라 실측치는 브라우저 접근성 트리 측정이며 소스와 일치한다. "대시보드 12 → 대표 6 + 더보기"는 5분 주기 프로버의 분 단위 확대(5m, 10m, 15m, 30m) 용도를 약화시키므로 `overflow-x-auto snap-x`를 기본으로 두고 사용자 결정 항목으로 표기한다. |

### DS-18 — i18n 통합(인라인 삼항 231개)과 KO 카피 규칙 적용

| | |
|---|---|
| 심각도(교정) | P2 |
| 공수(교정) | L (16~24h), 범위 조정 후 약 20h. ESLint 커스텀 룰은 프론트에 ESLint 자체가 없어 3~4h가 추가되므로 CI grep 한 줄과 순수 사전 vitest로 대체 권고 |
| 페이지/영역 | 전체 |
| 번들/PR | B4 PR10 (N-15, CV-17과 CV-20 fold-in 동반, v2.24.0 머지 후) |
| 근거 요약 | 방식 3종이 공존한다 — `lang === "en"` 삼항 231건, 로컬 `L()` 5곳(`GptOnAws:154`, `ClaudeFeatures:147`, `AppHeader:27`, `modelExplorer.ts:97,257`), useT 사전. useLang만 쓰고 useT를 쓰지 않는 컴포넌트가 13개다. EN 모드 한글 잔존은 라이브 번들에서도 재현된다(`AutoDashboard.tsx:375`, `ModelStatusGrid.tsx:228-239`, `TrendChart.tsx:141,153`, `pivotTrend.ts:40` "ko-KR" 고정, `modelExplorer.ts:39-83` channelOf → 라이브 청크에 "Global 프로파일" 존재, `ParityPanel.tsx:750,338`, `parity.py:126,139`, `ChatModal.tsx:92-104`, `LoginForm.tsx:102`, 챗 6파일 KO 전용). KO 모드 영문 잔존도 확인된다(Cost th 202-208, Efficiency th 131-139, Reliability 30-37 KO 맵에 EN 값, ParityPanel STATUS_LABEL과 "HEALTHY", "Key Findings", "Evidence", `ModelStatusGrid:209`, aria-label 혼재). 카피 위반은 `i18n.ts:197`, `Efficiency:108` "Tip:", `Analysis:343`, `Cost:279,121`, `Parity:772-776` "1 ·", `Parity:774` surface 5개(라이브 catalog는 6개), `Reliability:94-95` 1P 낡음, `Cost:242-243` OpenAI 미언급이다. |
| 수정안 | 1. `i18n.ts` 네임스페이스(common, nav, auth, a11y, errors, chat, dashboard, cost, reliability, efficiency, analysis, models, parity, gpt, metrics)와 useT 1종으로 삼항과 `L()`을 치환하고 `channelOf(modelId, lang)`, `STATUS_LABEL {ko,en}`("지원, 미지원, 오류, —"), 백엔드 code → 프론트 번역을 도입한다. 2. KO 카피 교정(쉼표, "1.", 단정형) — 가운데 점을 쉼표나 슬래시로(구분자는 aria-hidden span), overloadedHint와 `InsightsPanel.tsx:206`, `AutoDashboard.tsx:204` "프로브 N회 기준", `ParityPanel.tsx:291` "확실한 미지원 응답입니다. 프로브 결함이 아닙니다.", surface 목록을 catalog에서 파생, 각주를 현행 채널로 갱신하고 1P 제거. 3. `<html lang>` 동기화와 aria-label a11y.* 키(DS-09와 분담). 4. CI grep 한 줄과 순수 사전 vitest(en 값에 한글 0, ko 값에 가운데 점 0, 키 집합 동일), 인사이트 프롬프트에 "가운데 점 대신 쉼표" 지시. 5. 수동 프로브 탭 영어 리터럴 약 60개를 6파일에 걸쳐 정리한다(N-15, +2~3h). |
| 검증 교정 | 반박과 보정 7건. 1. "가운데 점 59건"은 전수 93자/55행 중 주석 17행, 모노 구분자 8행, 프롬프트 페이로드 6행을 제외하면 KO 문장 위반 13행과 번호 5행으로 약 18~20곳이다. 2. "i18n.ts 282키"는 94키다(interface와 ko, en 3중 계산). 3. "인사이트 본문 KO"는 이미 해결됐다(`insights_runner.py:197-203` 이중 생성). 4. 인용 오류 — LatencyChart는 `:138,145`, ModelSelector는 `:24-29`, AnalysisPanel:95는 실제로 `ReliabilityPanel.tsx:95`다. 5. StatsCards와 LatencyChart, ModelSelector, Compare, ProbeConfig는 로그인 게이트 뒤라 노출이 과대 평가됐다. 6. `<html lang>`과 /chat Provider는 DS-09 범위다. 7. ClaudeFeaturesPanel의 `L()` 치환은 v2.24.0 계획 RUL-3(L() 유지, i18n.ts 미사용)과 "Never touch i18n.ts"에 충돌하므로 제외하고 i18n.ts 개편은 머지 후에 착수한다(삼항 231 → 218). |

### CV-14 — URL 상태와 딥링크, 필터 기억

| | |
|---|---|
| 심각도(교정) | P2 |
| 공수(교정) | M (10~14h) 전체 유지 시. 수정 3(/?tab=manual)과 4(빈 트렌드 선택기)를 DS-09와 DS-02로 이관하면 M (8~10h) |
| 페이지/영역 | /cost, /reliability, /efficiency, /analysis, /models, /parity, /gpt-on-aws, / (수동 탭) |
| 번들/PR | B4 PR11 |
| 근거 요약 | URL 동기화는 `AutoDashboard.tsx:148-151` replaceState 1곳뿐이고 hooks에 URL 훅이 없으며 필터 localStorage가 0건이다. 라이브 확인 — `/` 로드 직후 URL이 `/?models=all&hours=1`로 치환되고(`trendSelection.ts:38-41`), `/cost?window=7d`는 24시간 버튼이 활성인 채 쿼리를 무시하고, `/models?q=fable&channel=bedrock`은 검색값이 빈 채 43/43이며, `/?tab=manual`은 대시보드를 렌더한 뒤 URL이 소거된다. `AutoDashboard.tsx:350` `{trend.length > 0 &&` 가드 때문에 `/?hours=0.0833&category=translate`에서 조회 기간 라벨과 버튼, 차트가 모두 사라져 기간 축이 갇힌다. |
| 수정안 | 1. `hooks/useUrlState<T>(key, {default, parse, serialize, persist?})` — 읽기는 useSearchParams, 쓰기는 `window.history.replaceState`(Next 14.2.5가 App Router에서 이를 패치해 useSearchParams와 동기화한다). 기본값이면 파라미터를 생략하고 선택적으로 localStorage에 남긴다. 2. 적용은 `/cost?window=7d`, `/analysis?window=30d&category=reasoning`, `/models?q=&channel=&model=`, `/parity?status=broken&model=&cell=`, `/gpt-on-aws?hours=72&ch=`. 3. 수동 프로브 `/?tab=manual`(내비 href와 pathname+query 기반 active 판정, DS-09 소유). 4. `:350` 가드를 차트만 감싸도록 옮기는 최소 변경만 CV-14가 하고 EmptyState 문구는 DS-02가 소유한다. |
| 검증 교정 | 정정 3건. 1. 수정안의 `router.replace`는 잘못된 도구다 — 전 페이지 force-dynamic이라 클릭마다 RSC 재요청이 발생한다. Suspense 경계 우려는 force-dynamic이라 해당 없다. 2. 추가 결함 — `buildTrendQuery`가 새 URLSearchParams를 만들어 외부 키를 지우므로 `/?tab=manual`이 마운트 즉시 소거된다(미지 키 보존 없이는 수정 3이 동작하지 않는다). 3. `models=all` 센티널은 잔재이므로(explicitAll 소비처 0, 대표 모델 자동 선택은 2026-07-10 제거) 기본값 생략이 안전하고 `trendSelection.test.ts:56-61`만 갱신한다. 앵커 보정 — `AnalysisPanel.tsx:59`는 "7d"이고 ParityPanel 필터 상태는 `:358-361,:365`다. 문구 메모 — 카테고리별 포인트는 30분에 1개이므로 "30분 이상"보다 "1시간 이상"이 정확하다. |

### CV-15 — 내보내기와 복사, 정렬, 검색: CSV와 JSON, CopyButton 공용, 빈 필터 상태, 죽은 1P 칩 제거

| | |
|---|---|
| 심각도(교정) | P2 |
| 공수(교정) | M (9~12h) — DataTable 정렬은 DS-11a, 대시보드 정렬 드롭다운과 채널 필터는 DS-11b로 이관한 잔여 기준 약 10.5h. 원문 범위를 한 PR로 하면 L (14~18h) |
| 페이지/영역 | /, /cost, /efficiency, /models, /parity, /gpt-on-aws, /prompts |
| 번들/PR | B4 PR12 (DS-11b와 같은 PR로 `ModelStatusGrid.tsx`를 한 번만 연다) |
| 근거 요약 | 내보내기가 0건이다(`text/csv`, `download=`, `new Blob`이 frontend/src와 원격 ref 21개 전수에서 0건, CHANGELOG와 docs도 0건). 라이브 `/api/cost/summary?window=24h` rows 43과 `/api/efficiency/score?window=24h` models 43인데 `CostDashboardPanel.tsx:199-209`와 `EfficiencyPanel.tsx:128-140`이 정적 `<th>`이고 aria-sort와 scope가 전체 0건이다. 대시보드는 `groupByFamily` 고정 정렬에 칩 43개 검색이 없고 `ModelStatusGrid.tsx:150`은 title만이다. `ModelExplorer.tsx:26` "OpenAI 1P" 칩은 `prober.py:330-341` 등록 skip과 `isExcludedModel`, `sortModels.ts:28` 이중 차단으로 어떤 환경에서도 결과가 없는데 `:264-289` 그리드에 length===0 분기가 없어 빈 화면과 "0 / 43"만 남는다. `ParityPanel.tsx:301-306` `<pre>`에 복사가 없고 `ModelExplorer.tsx:36-50` CopyButton은 미export 로컬 함수이며 `:42`에 catch가 없고 390px에서 47자 Haiku ID 옆 버튼이 29×38px 2줄로 깨진다. `PromptsPanel.tsx:238` 복사에 피드백과 catch가 없다. |
| 수정안 | 1. `components/ui/CopyButton.tsx`(try/catch와 execCommand 폴백, role=status "복사했습니다.", `whitespace-nowrap shrink-0 min-h-9`)를 CV-15 단일 소유로 만들고 4곳에 채택한다. 2. `lib/csv.ts`(UTF-8 BOM 명시)와 vitest, `ExportMenu.tsx`(CSV 내보내기, JSON 내보내기, 표 복사(TSV), navigator.share 폴백 — iOS standalone PWA 대비). 3. 채택은 대시보드 최신 결과 CSV와 트렌드 JSON, 카드 model_id 복사, cost와 efficiency CSV(DS-11 onExportCsv에 핸들러 제공), 패리티 매트릭스 CSV와 증거 JSON 복사, 벤치 CSV. 4. ModelExplorer 채널 칩을 데이터에서 파생하고(count>0만, 개수 배지 "Bedrock 19, Anthropic CP 8, OpenAI Mantle 16") 채널 별칭 검색과 0건 상태("'{q}'와 일치하는 모델이 없습니다."와 "필터 초기화")를 넣는다. |
| 검증 교정 | 오기 2건. 1. "text/csv 사용처가 ModelExplorer와 PromptsPanel"은 틀렸다(두 파일은 `navigator.clipboard.writeText`만 쓰고 text/csv는 0건). 2. "채널 별칭 Global 미매칭"도 틀렸다(라이브 43라벨 중 global 12건, anthropic 8건이 매칭되며 공백은 'CP'와 'Mantle'뿐이다). 번들 제약 "CV-14 이후"는 삭제한다(내보내기는 컴포넌트 state를 읽으면 되므로 URL 상태 의존이 없고 같은 파일을 만지니 머지 순서만 조정한다). source_ids의 D-15는 "복사 부분만"으로 표기한다 — D-15 본체(채널 설명 2채널, 내부 키 vs 호출 ID)는 어느 항목도 흡수를 명시하지 않아 소실 위험이 있으며 DS-16과 CV-19가 받는다. vitest가 node 환경이라 csv 직렬화와 칩 집계, 별칭 매칭만 순수 함수로 테스트한다. |

### CV-18 — SSE 안정성과 챗 상태 보존: idle 감시, keepalive, 실패 재시도, 경고와 오류 분리

| | |
|---|---|
| 심각도(교정) | P2 |
| 공수(교정) | M (10~13h) — 챗 생성기 블로킹 해소 2h 선행 때문에 원안 8~10h에서 상향 |
| 페이지/영역 | / (수동 프로브, Comparison Lab), 챗봇(FloatingChat, ChatModal, /chat), InsightsPanel 재생성 |
| 번들/PR | B4 PR13 |
| 근거 요약 | `api.ts:244-326,331-422,476-548,551-612` SSE 4종이 단일 reader 루프이고 idle 타이머가 없으며(setTimeout과 AbortSignal.timeout 0건) AbortError를 무시한다(`:320,:416,:543,:607`). `useChatStream.ts:57` warning이 setError로 흘러 `ChatPanel.tsx:148-152` 빨간 오류 박스가 되고(발생원은 `chat.py:266-271` MAX_TOOL_HOPS), `:64-67`과 `:75-78`에서 빈 말풍선이 남고 재시도가 0건이다. `MessageList.tsx:31-33`이 매 delta마다 scrollIntoView하고 프론트 전체 aria-live가 0건이다. `ChatModal.tsx:53` return null이 로컬 state를 버리는데 언마운트 cleanup이 없어 fetch는 백그라운드에서 계속되고 히스토리 GET 엔드포인트도 없다. 인프라가 먼저 절단한다 — CloudFront OriginReadTimeout 60s, ALB idle_timeout 60s인데 백엔드는 `prober.py:823/:1009`에서 300초 무음 대기하고 라이브 p99 TTFT가 GPT 5.6 Sol (Global) 91,466ms다. |
| 수정안 | 1. `lib/sse.ts` `readSse(res, handlers, {idleMs:45000})` — 무응답 45초면 abort와 `ApiError STREAM_IDLE`("응답이 45초 동안 없어 연결을 종료했습니다. 다시 시도하세요."), 종단 이벤트 미수신 EOF는 STREAM_CLOSED로 승격(현재 4훅 모두 영구 "생성 중"에 갇힌다), 4종 교체. 2. 백엔드 ping은 4경로 각각에 넣는다(`prober.py:823/:1009` queue.get을 15초 슬라이스로, insights는 wait_for, chat은 to_thread 리팩터 후 wait_for). 현행 파서 4곳이 `: ping` 블록을 이미 무시하므로 백엔드 ping은 프론트 변경 없이 선배포할 수 있다. 3. 챗은 ChatModal hidden 토글(언마운트 금지)과 sessionStorage 복원, `ChatMessage.status`(failed, cancelled)와 재시도(마지막 user 재전송), warnings amber 분리, 취소 시 "중단됨", 바닥 근접 자동 스크롤과 "↓ 새 메시지", 마지막 버블 aria-live=polite. 4. 프로브와 비교에 "N/M 완료 후 중단됨" 배지. 5. `InsightsPanel.tsx:77-83` onFinal이 ok:false를 무음 폐기하는 것을 범위에 추가한다. |
| 검증 교정 | 반박 1건 — `useProbeStream.ts:90-96` "부분 결과 표시 없음"은 틀렸다(results와 tokens가 보존되고 `page.tsx:214-251`이 렌더한다). 빠진 것은 중단 사실과 진행 수치 안내이므로 문구를 그렇게 고친다. 하향 1건 — `ChatPanel.tsx:107-110` 'Sonnet 4.6' 하드코딩은 `bedrock.py:22`와 현재 일치해 드리프트 위험(P3 선택)뿐이며 `/api/chat/meta` 신설은 불필요하고 CV-13 `/api/version`에 chat_model 1필드로 대체한다. 설계 결함 3건 — `stream_with_final`은 `chat.py:307`만 사용해 ping이 3/4 경로를 덮지 못하고, chat 생성기가 이벤트 루프를 블로킹해 asyncio ping 발화가 불가하며(insights의 to_thread 패턴 선행), 종단 이벤트 없는 EOF 콜백이 없다. 범위 밖 분리 — 프로브 stop 시 백엔드 워커 스레드 취소 전파가 없어 과금이 계속된다. |

---

## 3. 크리틱 추가 항목 (24)

검증 백로그 34건이 표시 계층과 API 규약은 잘 덮지만 보안, 인증 강도, 다중 사용자 데이터, 운영 콘솔, 테스트 인프라 다섯 축이 비어 있었다. 아래 24건은 완결성 크리틱이 HEAD `f11dda9`와 라이브에서 재확인한 것이다. N-20(RUM appVersion 1줄)은 CV-13 F-1로 흡수되어 종결됐으므로 번호가 비어 있다.

### 3.1 P1 — 보안과 가용성

**N-01 [P1, S 2~4h, B1 PR1] 보안 응답 헤더 부재, x-powered-by 노출, CORS `*`와 allow_credentials=True 동시**
라이브 `curl -sI /`에 `x-powered-by: Next.js`가 있고 strict-transport-security, content-security-policy, x-frame-options, x-content-type-options, referrer-policy, permissions-policy가 전부 없다. `frontend/next.config.mjs:20-35` headers()에 Cache-Control 2규칙만 있고 poweredByHeader가 미설정이며 `backend/main.py:221-226`이 `CORSMiddleware(allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`("for development" 주석)다.
왜 중요한가 — 로그인 폼 페이지의 iframe 삽입(클릭재킹)이 가능하고 HSTS가 없으며 임의 Origin에 credentials를 허용하는 구성은 보안 리뷰와 조달에서 즉시 불합격이다. 토큰이 localStorage(`api.ts:27,35`)에 있어 CSP 부재가 XSS 피해 범위를 키운다. 백로그 34건 어디에도 없었다.
수정 — poweredByHeader:false와 헤더 4종(next.config), HSTS는 CloudFront ResponseHeadersPolicy(`edge-stack.ts:64` 기존 정책에 추가), CSP는 인라인 테마 스크립트와 RUM SDK 때문에 Report-Only로 1주 관찰 후 강제, `allow_origins=[PUBLIC_BASE_URL]`과 `allow_credentials=False`(프론트와 API가 동일 오리진이라 기능 영향 없음).

**N-02 [P1, S 1~1.5h, B1 PR1] `/api/results/stats?start_time=` 무상한 공개 GET, 이력 패널 30일이 2026-09-01 OOM 경로를 그대로 탄다**
`backend/routers/results.py:18-20` 주석이 "전체 probe_results(수십만 행)를 ORM으로 적재해 OOM(1024MB, exit 137), 2026-09-01 실사고"를 기록했는데 `:83-86`은 start_time이 명시되면 상한 없이 통과하고 `:94`가 `query.all()`이다. `frontend/src/components/HistoryPanel.tsx:17-36` `getStartTime("30d")`가 이 경로를 탄다. 43모델 × 288회/일 × 30일이면 약 370k행이고 공개 엔드포인트다.
왜 중요한가 — 이력 패널의 "30일" 클릭 한 번, 또는 누구든 GET 1회로 backend OOM을 재현할 수 있다. CV-03의 대상(4라우터, 화이트리스트 7엔드포인트)에 이 라우터가 없다.
수정 — start_time이 7일 이전이면 7일로 클램프하고 응답에 `window_clamped: true`, HistoryPanel에 안내 1줄 "7일까지 원본, 30일은 시간 집계입니다." window 화이트리스트는 CV-03a에서 1회만 구현한다.

**CV-08a 관련 [검증 항목, 코드 재확인 필요]** 크리틱은 실행 순서 §7에서 첫 핫픽스를 "CV-08a 트리거 인증 게이트"로 적었고, CV-08 항목의 가치 문구는 "유료 사이클을 누구나 실행할 수 있는 상태를 닫고 모든 쓰기 액션에 결과 피드백 제공"이며, 증거는 "`backend/routers/auto_probe.py:259-265` trigger_probe에 `Depends(get_current_user)` 없음"과 "`edge-stack.ts:134` `/api/auto-probe/*` ALLOW_ALL"이다. 검증은 이를 confirmed로 판정했고 라이브에서 `GET /api/auto-probe/trigger`가 405(라우트가 CloudFront를 통과)임을 확인했다. 다만 POST는 실행하지 않았다(비용과 데이터 오염 방지). 따라서 이 문서는 무인증 실행 가능 여부를 단정하지 않고 "코드 재확인 필요"로 표기한다. 착수 전 `auto_probe.py:259-265`의 의존성 목록과 배포된 리비전의 동일성을 먼저 확인하고, 그 다음 스테이징 또는 배포 직후 비인증 POST가 401을 반환하는지로 완료를 판정한다.

### 3.2 P2 — 인증 강도, 다중 사용자, 운영, 성능, 인에이블러

**N-03 [P2, S 2~3h, B2 PR3] 페이지별 `<title>` 부재, OG와 metadataBase 없음, robots.txt와 sitemap.xml 404**
`frontend/src/app/layout.tsx:8-20` metadata.title이 정적 1개, description이 EN 고정이고 openGraph, twitter, metadataBase가 없다. 모든 page.tsx가 "use client"라 세그먼트 메타가 없고 라이브 `/robots.txt`와 `/sitemap.xml`이 404다.
탭 10개가 같은 이름이라 북마크와 PWA 최근 목록에서 구분되지 않고 링크 미리보기가 없으며 공개 대시보드의 색인 방침이 미명시다. 수정 — PageShell에서 document.title 또는 라우트 layout `title.template`, metadataBase와 OG, `app/robots.ts`(공개 유지면 allow에 /api, /prompts, /chat disallow, 내부 도구면 index:false). 색인 정책은 소유자 결정 항목이다.

**N-04 [P2, S 3~4h, B2 PR2] 로그인 무제한 시도(rate limit 0)와 비밀번호 min_length=4**
`backend/routers/auth.py:104-121` login()에 실패 카운트와 지연, 락이 없고 `grep -rn "slowapi|limiter|RateLimit" backend/`가 0건이며 `:36,42`가 `Field(min_length=4, max_length=100)`, `LoginForm.tsx:113`이 minLength=4다. `edge-stack.ts:138-145` `/api/*`는 ALLOW_ALL이고 WAF가 없다.
이메일 아이디에 4자 비밀번호, 무제한 시도는 사전 공격에 노출된다. DS-13의 프론트 8자 힌트는 백엔드 동반 변경 없이는 거짓 안내다. 수정 — 아이디당 5회/15분 초과 시 429와 Retry-After, KO detail "로그인 시도가 너무 많습니다. 15분 후 다시 시도하세요.", RegisterRequest만 min_length=8(로그인은 유지). 401 헤더는 CV-07 소유, WAF는 N-24와 같은 CDK PR.

**N-05 [P2 정책 결정, M 8~12h, B4 PR17] 비밀번호 재설정과 변경, 계정 자기 삭제 경로 부재**
`routers/auth.py`의 엔드포인트가 login, register, approve, me 4개뿐이고 reset, forgot, change가 0건이며 LoginForm에 찾기 링크가 없고 사용자 자기 삭제도 없다(admin DELETE만). SES 발송 경로 `_send_approval_email`은 이미 있다.
계정이 있는 상용 제품에서 비밀번호를 잊으면 관리자가 DB를 직접 고쳐야 한다. 수정 — `POST /api/auth/forgot`(존재 비노출, 항상 200) → 서명 토큰 15분 → `/reset` → `POST /api/auth/reset`, 로그인 상태에서는 `POST /api/auth/password`. 착수는 소유자 정책 결정 후다.

**N-06 [P2, M 6~10h, B2 PR6] 관리자 UI 부재, 사용자 목록과 승인, 삭제, 데이터 초기화가 curl 전용**
`backend/routers/admin.py:36 reset-monitoring-data`, `:87 users`, `:106 DELETE users/{username}`, `:125 approve`가 있는데 프론트 `grep -rln "admin" src/`는 LoginForm.tsx와 i18n.ts(placeholder)만 잡는다. CLAUDE.md의 "Admin operations"가 curl과 jq 절차이고 감사 추적은 `admin.py:54,121,140` logger뿐이다.
운영자가 터미널 없이 승인 대기 목록을 볼 수 없어 인수인계와 감사가 불가하다. 수정 — `/admin` 라우트(PageShell, `user.username === "admin"` 게이트와 백엔드 403 유지), 사용자 표, 승인과 삭제 ConfirmDialog(role=alertdialog), 초기화 2단계 확인(이름 타이핑). KO "승인 대기 3명", "삭제하면 되돌릴 수 없습니다." Dialog(DS-06) 이후에 착수한다.

**N-07 [P2, S~M 4~6h(+2h), B3 PR9] 프롬프트 세트 소유권 부재, 승인 사용자 누구나 타인 세트를 삭제**
`backend/models.py:115-123` PromptSet에 소유자 컬럼이 없고 name이 전역 유일이며 `routers/prompts.py:87-95` delete_prompt_set이 인증만 확인한다. `PromptsPanel.tsx:17-39`는 타겟 모델 19개를 하드코딩해 `/api/models`와 드리프트하고 `:87-92` temperature 0.1과 max_tokens 256이 비노출이다.
다중 사용자 데이터 무결성의 결정적 공백이다. 수정 — `owner_id`(nullable, 기존 행 NULL=공용)를 lifespan `ADD COLUMN IF NOT EXISTS`로 추가하고 삭제는 owner 또는 admin만(403 "다른 사용자의 프롬프트 세트는 삭제할 수 없습니다."), 유일성을 `(owner_id, name)`으로, UI에 "내 세트"와 "공용" 배지. 부속으로 타겟 모델을 `/api/models`에서 파생(+1h)하고 파라미터 2필드를 노출한다(+1h).

**N-08 [P2, S 3~4h, B2 PR5] 수동 프로브: 실행 전 호출 수와 시간, 비용 견적 없음, hover 전용 아이콘 1클릭 무확인 삭제, 재실행 시 이전 결과 무확인 소거**
`ProbeConfigPanel.tsx:296-360` max_tokens ≤4096, concurrency ≤10, repeat ≤20에 모델 수 제한이 없어 43×20 = 860회를 견적 없이 실행할 수 있다(`lib/pricing.ts estimateCost`는 이미 존재). `:241` `opacity-0 group-hover:opacity-100`은 저장소에서 유일한 hover 전용 컨트롤이라 터치에서 보이지 않고 `:146-152`가 확인 없이 deletePromptSet을 호출하며 실패는 console.error다. `useProbeStream.ts:34-46` run()이 이전 results를 즉시 지운다.
비용 모니터링 제품의 수동 실행이 비용을 미리 알려주지 않고 되돌릴 수 없는 삭제가 확인 없이 실행된다. 수정 — 실행 버튼 위 "예상 호출 129회, 약 2분, 예상 비용 $0.42"와 200회 초과 시 ConfirmDialog, 삭제 아이콘 상시 노출과 ConfirmDialog, 재실행 시 "이전 결과 N건이 지워집니다. CSV로 저장하시겠습니까?" CV-08b와 같은 PR이다.

**N-09 [P2, S 3~4h, B1 PR8] 1초 tick이 카드 43개와 Recharts 3개를 매초 리렌더, 수동 탭 컴포넌트 정적 import**
`hooks/useAutoRefresh.ts:19-27`이 setCountdown updater 안에서 콜백을 호출하고 `AutoDashboard.tsx:70-78` toggleModel과 clearSelection에 useCallback이 없어 `TrendChart.tsx:222` memo가 무효화되며 `:155,158-165` 1초 interval 2개가 루트 state를 갱신한다. ModelStatusGrid에 memo가 없고 `app/page.tsx:15-22`가 수동 탭 전용 6컴포넌트와 Recharts를 정적 import한다(리더 실측 314KB gz).
모바일 PWA의 배터리와 발열, 스크롤 jank의 직접 원인이고 첫 화면 성능 예산을 넘긴다. 리더 finding D-04와 D-22가 백로그 이관에서 소실됐다. 수정 — useCallback과 memo, 카운트다운을 StatusBar 자식으로 격리(CV-10 훅 v2의 콜백 분리만 B1에서 선반영), next/dynamic으로 수동 탭 분리.

**N-10 [P2 인에이블러, S~M 4~6h, B1 PR2] 테스트 하네스 부재(jsdom, @testing-library, Playwright, CI e2e 0)**
`frontend/package.json` devDependencies가 tailwind 계열과 typescript, vitest뿐이고 vitest.config와 playwright.config가 없으며 테스트 5파일이 전부 `src/lib/*.test.ts`이고 `.github/workflows/ci.yml:27-42` frontend job은 tsc와 vitest, build만 돈다. 검증 노트들이 하네스 가산을 반복 계상했다(DS-01 +2~3h, DS-06 +3~4h, DS-08 +1.5h, DS-14, DS-18).
DS-01, DS-05, DS-07의 완료 기준이 전부 브라우저 assert(`scrollWidth === 390`, 헤더 ≤64)라 한 번 세우면 후속 항목의 가산분 8~10h가 사라진다. 수정 — vitest.config(jsdom)과 RTL, `e2e/` Playwright 스모크(9페이지 × 4폭 × 2테마, axe critical 0), CI frontend-e2e job.

**N-15 [P2, DS-18 범위 확장 +2~3h, B4 PR10] 수동 프로브 탭 UI 크롬 영어 리터럴 약 60개**
삼항이 없는 리터럴이라 KO 모드에서 영어가 그대로 보인다 — `ProbeConfigPanel.tsx:197,203,261,268,291-292,389,395`, `ResultsTable.tsx:97-105`(헤더 9개)와 `:112`, `StreamingView.tsx:155,174,178`, `ComparisonView.tsx:159,175,189,203`, `StatsCards.tsx:104-157`(5개), `ModelSelector.tsx:24-29`(그룹명 6개). DS-18 검증은 이를 우선순위 후순위로만 언급하고 공수에 넣지 않았다.
로그인 사용자 전용이라 공개 페이지 다음 우선이지만 KO 제품에서 한 탭 전체가 영어다. 처리 — DS-18 evidence에 6파일을 추가하고 공수를 +2~3h 반영한다.

**N-21 [P2 결정 항목, 삭제 0.5h 또는 탑재 4~6h, B4 PR16] Comparison Lab 고아 표면과 죽은 클라이언트, 서버 코드**
`grep -rn "ComparePanel" frontend/src`가 `components/CLAUDE.md:15` 문서 행만 잡는다(어느 page도 import하지 않으며 `app/page.tsx:59,258`의 compare 탭은 다른 컴포넌트 ComparisonView를 렌더한다). `ComparePanel.tsx`(약 470행, v2.1.0 커밋 `5f8418f` 이후 단독 커밋 없음)는 추천 프롬프트 5종과 비교 매트릭스까지 완성된 화면이고 `CHANGELOG.md:71-72` v2.22.0이 "Comparison Lab 이름" 갱신을 릴리스 노트에 적었다. api.ts 죽은 함수 4개(`compareStream:476`, `regenerateInsight:438`, `fetchInsights:432`, `fetchCostTrend:675`)와 백엔드 미사용 엔드포인트 2개(`routers/compare.py /api/compare/run`, `insights.py:94-120 POST /regenerate`)가 딸려 있다. 검증 노트 4건(DS-10, CV-12, DS-15, DS-18)이 ComparePanel을 살아 있는 채택 지점으로 계산했다.
결정 없이 진행하면 죽은 화면에 프리미티브 채택 공수가 들어간다. 선택지 — 1. 탑재: `/compare` 라우트와 내비 "비교 랩"(4~6h, CV-18 SSE 유틸 재사용). 2. 삭제: 컴포넌트와 함수 4개, 라우터, include_router, `prober.stream_compare_events`, 문서 행 제거(0.5h, 번들 약 −15KB).

**N-24 [P2, S 2~3h(CDK), B3 PR2] 공개 API 속도 제한과 WAF 부재**
`grep -rn "wafv2|WebAcl|RateBased" cdk/lib`가 0건이고 `edge-stack.ts:138-145` `/api/*`가 ALLOW_ALL에 CACHING_DISABLED이며 앱 레벨 slowapi도 0이다. 리더 실측 공개 GET이 `/api/reliability/multi-channel?window=7d` 10.9s, `/api/auto-probe/trend?hours=168` 13.1s, `/api/analysis/output-length?window=7d` 10.0s이고 같은 원인의 OOM이 오늘 3회 관측됐다.
CV-03(SQL 집계)과 CV-04(캐시)는 요청 1회 비용을 줄이지만 요청 수를 제한하지 않는다. 단일 t4g.micro RDS와 1024MiB 태스크 1개 구성에서 폭주는 전면 장애다. 수정 — Edge 스택에 `CfnWebACL` rate-based rule(`/api/*` IP당 300req/5min, `/api/auth/*` 100, `/api/*/trigger` POST 10)과 distribution webAclId 연결, 초과 시 429 JSON `{code:"RATE_LIMITED"}` → CV-01 매핑. CV-04b와 같은 CDK PR로 ADR-018 digest 고정 절차를 따른다.

### 3.3 P3 — 마감과 교정

**N-11 [P3, S 1h, B2 PR3] 승인 링크 결과 페이지가 백엔드 원시 HTML** — `backend/routers/auth.py:149-181` approve_user가 `_result_html(:187-204)`로 인라인 스타일 다크 고정, KO 고정, 앱으로 돌아갈 링크 없는 페이지를 반환한다. 관리자가 메일에서 클릭하면 브랜드 없는 검은 카드에서 끝난다. 수정 — `RedirectResponse(f"{PUBLIC_BASE_URL}/?approved={username}")`와 `?approve_error=expired`, PageShell 토스트 "계정 {name}을 승인했습니다."

**N-12 [P3, S 2h, B4 PR8] 인쇄 스타일 0건** — `@media print`와 `print:`가 `globals.css`와 `tailwind.config.ts`에 0건이라 비용과 신뢰성 보고서를 인쇄하면 다크 배경에 헤더와 FAB, 필터 칩이 그대로 나온다. 상용 대시보드의 기본 인쇄와 PDF 저장 경로가 없다. 수정 — `@media print`에서 라이트 토큰 강제, header와 FloatingChat, 필터 행 숨김, 카드 `break-inside:avoid`, `print:hidden` 6곳.

**N-13 [P3, S 2~3h, B4 PR15] 사용자 첫 방문 안내와 방법론 진입점 부재** — `docs/onboarding.md`는 "Clone the repository"로 시작하는 개발자 문서이고 UI 진입점은 `AutoDashboard.tsx:427-455` 설명 박스뿐이며 나머지 8페이지에는 없다. 첫 방문자가 43모델, 5분 주기, 6워크로드 구조를 알 수 없다. 수정 — 첫 진입 1회 접이식 카드(localStorage dismiss)로 "이 대시보드는 43개 모델을 5분마다 6종 워크로드로 프로빙합니다. 1. 카드는 최신 사이클입니다. 2. 추이는 선택한 모델입니다. 3. 인사이트는 5분 주기 요약입니다."와 방법론 링크, 빈 DB EmptyState "첫 프로브는 배포 후 약 5분 뒤 도착합니다."

**N-14 [P3 정책, S 1h, B4 PR15] 푸터 법적, 연락, 데이터 출처, RUM 수집 고지 부재** — `<footer>`가 0건이고 이용 약관과 개인정보, 문의, 데이터 출처 고지가 어디에도 없으며 RUM(CloudWatch)이 세션을 수집하는데 고지가 0건이다. 수정 — CV-13 F-2의 AppFooter에 "데이터 출처", "문의(GitHub Issues)", "이용 안내"와 RUM 수집 1줄. 법적 문서 유무는 소유자 결정이다.

**N-16 [P3, +1h, B4 PR2] StreamingView 모델 배지 대비와 죽은 1P 엔트리, 별개 색 맵** — `StreamingView.tsx:38` bg-lime-400, `:42` bg-emerald-300, `:49` bg-green-300 위에 `:135` text-white(약 1.5~1.9:1)이고 `:10-52`에 "(1P)" 엔트리 5개가 남아 있으며 TrendChart MODEL_COLORS와 별개 사전에 `:56-108`이 부분 문자열로 모델명을 재유도한다. 모델 추가 시 두 곳을 고쳐야 하고 신규 모델은 원시 id가 노출된다. 처리 — DS-16 channelColors.ts 채택 목록에 추가한다.

**N-17 [P3, +1h, B4 PR5] ResultsTable map 안 Fragment key 없음, 펼친 행이 인덱스 기반** — `ResultsTable.tsx:130-220`이 `sortedResults.map((result, idx) => (<> … </>))`로 Fragment key가 없어 React 경고가 나고 `:135,186`이 `expandedRow === idx`라 정렬을 바꾸면 다른 행이 펼쳐져 데이터를 오독하게 만든다. 처리 — DS-11a에서 `<Fragment key>`와 `expandedKey=model_id:iteration`.

**N-18 [P3, +0.5h, B2 PR7] `/chat` 팝업 h-screen이 iOS Safari 툴바에 입력창을 가린다** — `frontend/src/app/chat/page.tsx:9` `<main className="h-screen w-screen overflow-hidden">`이고 iOS Safari의 100vh는 툴바 뒤까지 포함한다. Tailwind 3.4가 `h-dvh`를 지원하므로 DS-12 PR에서 교체한다.

**N-19 [P3, +1h, B1 PR5] HistoryPanel이 fetchStats 실패를 "이력 없음"으로 표시, page.tsx 무음 실패** — HEAD 재확인 결과 `HistoryPanel.tsx:120-131` loadStats catch가 console.error만 하고 stats를 유지해 `:309-315`가 `t.historyNoData`를 렌더하며, `app/page.tsx:92-101` fetchModels와 fetchPromptSets도 console.error만 해 ModelSelector가 빈 채 "Select at least one model"이 남는다. DS-02 채택 목록(5곳)과 CV-02 fold-in 어디에도 없던 잔여 2곳이다. 처리 — DS-02 채택 목록에 추가한다.

**N-22 [P3, S 1.5~2h, B3 PR10] 인사이트 수동 재생성이 KO와 EN 쌍을 깨뜨린다** — `backend/routers/insights.py:205-210`이 `summary_md=full_text`, `summary_md_en=full_text if lang == "en" else None`으로 저장하므로 KO 재생성 시 EN 사용자는 `InsightsPanel.tsx:196-198` 폴백으로 KO 본문을 보고, EN 재생성 시 KO 사용자가 영어 본문을 본다(스케줄 잡 `insights_runner.py:163-210`은 양언어를 저장한다). `stream-regenerate(:132-223)`에 동시 실행 락이 없어 두 사용자가 동시에 누르면 Bedrock 호출 2회와 Insight 행 2개가 생긴다. `InsightsPanel.tsx:189` 'Sonnet 4.6' 하드코딩은 CLAUDE.md의 "Haiku 4.5 인사이트 잡"과 이미 문서 드리프트다. 수정 — 요청 lang 본문만 해당 필드에 쓰고 다른 필드는 직전 행에서 복사, final 이벤트에 model_id, SSE 경로에도 락과 `ALREADY_RUNNING`(KO "다른 사용자가 인사이트를 생성하고 있습니다. 잠시 후 자동으로 반영됩니다.").

**N-23 [P3, DS-16과 CV-19 교정 +0.5~1h, B4 PR2] 신뢰성 BEST 배지 라이브 42/43, 단일 채널 family 상시 BEST, family 알파벳 정렬** — 라이브 `/api/reliability/multi-channel?window=24h`에서 15 family, 43카드 중 42개가 `success_rate === bestRate`이고(`ReliabilityPanel.tsx:135-144` 동률 전원 winner, 유일한 비승자는 Bedrock Claude Opus 4.8 (US) 0.9965) 비교 대상이 없는 단일 채널 family Nova 2.0 Lite도 상시 BEST다. family 순서는 `reliability.py:185 sorted(agg.keys())` 알파벳이라 대시보드 FAMILY_ORDER와 다르고 방법론 문구(`:220-224`)의 "동률이면 알파벳 순"은 미구현이다. 처리 — DS-16 fix 4에 "채널 1개 family는 배지 생략(비교 대상 없음)"을 추가하고 family 정렬은 프론트 `sortModels.ts familyRank`를 재사용한다(백엔드 무수정).

**N-25 [P3, +0.5h, B1 PR6] 다중 탭 인증 비동기화** — `api.ts:31-41` setToken이 `window.dispatchEvent(new Event("auth-changed"))`만 발행해 같은 문서에 한정되고 `addEventListener("storage"`가 0건이며 `:22-29` `_token` 메모리 캐시 때문에 탭 A에서 로그아웃해도 탭 B는 다음 보호 요청 401까지 로그인 상태로 보인다. 처리 — CV-07 PR에서 storage 이벤트 1블록(auth_token 키 변경 시 `_token` 갱신과 auth-changed dispatch).

---

## 4. 병합, 폐기 6건과 fold-in 의무

검증에서 6건은 결함이 거짓이라서가 아니라 이미 kept로 확정된 항목과 완전 중복이라 폐기됐다. 폐기 사유서에만 존재하는 교정이 있으므로, 구현자가 폐기 목록을 읽지 않으면 사라진다. 크리틱이 이를 §1.2 원장으로 고정했고 아래가 그 전량이다.

| 폐기 | 원 심각도와 공수 | 흡수 항목 | 중복 근거 |
|---|---|---|---|
| CV-02 패널별 오류, 빈, stale 상태 분리와 재시도 버튼 | P1, L (16~24h) | DS-02 (+DS-08, DS-17, DS-15) | source_ids 12개 중 10개가 DS-02에 그대로 포함되고 나머지 2개는 DS-08 소관. fix 5요소 전부가 DS-02, DS-08, DS-17, DS-15에 대응 |
| CV-06 분석 패널 기간 전환 레이스와 stale-while-revalidate | P1, M (6~8h) | DS-08 | 같은 4파일, 같은 source_ids(AP-04, AP-17, AP-18, V-23)의 진부분집합. 별도 유지 시 6~8h 이중 계상 |
| CV-11 신선도 배지와 스케줄러 지연 경보 | P2, M (8~10h) | DS-17 | source_ids 7개, 수정안, 예시 카피까지 동일 |
| CV-12 lib/format.ts 시각과 통화 단일화 | P2, S (4~6h) | DS-10 | 근거 문장과 인용 행, source_ids가 글자 단위로 동일하고 DS-10이 상위집합(fmtInt, fmtPct, fmtRegion, RelativeTime 추가) |
| CV-16 App Router 경계 파일과 PageShell 공용화 | P2, M (6~8h) | DS-09, DS-19 | fix 1 = DS-19 fix 2, fix 2 = DS-09 fix 1, fix 3 = DS-09 fix 2와 4. 증거도 DS-09 §1과 같은 소스(EPG-19, AP-20, SH-05) |
| CV-17 i18n 완결 | P2, L (16~24h) | DS-18 (+DS-09, CV-01) | source_ids 10개 중 8개가 DS-18과 일치, SH-05와 SH-06은 DS-09, 백엔드 code 봉투는 CV-01 |

### fold-in 의무 체크리스트

크리틱 본문은 이를 "21개"로 요약했지만 §1.2 원장을 항목 단위로 세면 30개다. 아래 번호가 정본이며 구현 전에 흡수 항목의 fix 텍스트에 반영한다.

CV-02 → DS-02 (5건, B1 PR5)
1. `Promise.allSettled` 전환 대상 명시 — `CostDashboardPanel.tsx:40-43`, `AnalysisPanel.tsx:77-80`, 실패 섹션만 inline ErrorState.
2. `AutoDashboard.tsx:131-136` anomalies — 첫 로드 실패는 인라인 오류, 갱신 실패는 stale 라벨(현재 두 경우 모두 무음).
3. `lib/workloadPresets.ts` 6행 폴백 신설과 id 집합 vitest, 폴백 적용 3곳(`AutoDashboard:127`, `EfficiencyPanel:36`, `AnalysisPanel:70`).
4. 앵커 보정 — ParityPanel 빈 상태 `:592-596`, load `:367-381`.
5. 공용 틴트를 `bg-rose-500/10 border-rose-500/30 text-rose-300`으로 고정(rose-950 계열은 라이트 재매핑이 없어 2.46:1이 재발한다).

CV-06 → DS-08 (2건, B3 PR6)
6. `CostDashboardPanel.tsx:60-64` monthlyEstimate가 `window` 상태 문자열로 시간을 나누므로 keepPrevious 구간에서 상태는 새 기간, 데이터는 이전 기간이 되어 7배 과대가 재발한다. `summary.window` 또는 since에서 시간을 유도한다.
7. `window_hours` 의존 삭제(응답에 이미 window와 since가 있다).

CV-11 → DS-17 (7건, B3 PR7)
8. parity/latest에 `next_expected_at`과 `interval_seconds` 추가(rate(12h) 위상 프론트 하드코딩 금지).
9. running을 DB 기준으로 바꿀 때 `started_at > now()-2h` 가드 필수(`parity/runner.py:79-136`이 failed를 기록하지 않는다).
10. `/status`의 소요 시간과 프로브 수는 신규 컬럼이 아니라 probe_results count와 max 집계로 얻는다(PR #51 마이그레이션 사고 직후).
11. 배지는 AppHeader actions가 아니라 패널 헤더에 배치한다(actions는 모바일에서 보이지 않는다).
12. `fetchedAt`은 "조회 성공 시각"으로 표기한다(`/api/auto-probe/*` s-maxage=30).
13. 이상 징후 배너에서 `total_probes === 0`을 경고로 처리한다.
14. gptbench/latest에 `interval_seconds`를 노출한다.

CV-12 → DS-10 (7건, B3 PR5)
15. 통화 규칙 `maximumFractionDigits: usd<0.01?4:2`는 결함이다(0.0148 → "$0.01") → ≥$1 2자리와 천 단위, <$1 4자리 고정, <$0.0001은 "<$0.0001"과 title.
16. "KST"는 리터럴 접미로 붙인다(Intl `timeZoneName:"short"`는 "GMT+9"를 낸다).
17. `hourCycle:"h23"` 명시(hour12:false와 2-digit 조합은 "24:12:59"를 낸다).
18. `pivotTrend`에서 포맷을 제거하고 TrendChart가 useLang과 tickFormatter로 처리한다(rangeHours prop).
19. `ComparePanel.tsx:459` 호출부 포함 여부는 N-21 결정에 따른다.
20. `ParityPanel.tsx:502` 가운데 점을 쉼표로 고친다.
21. v2.24.0 머지 후 `formatDuration`과 `formatMs`를 format.ts로 이동한다.

CV-16 → DS-09, DS-19 (5건, B2 PR3)
22. 언어 SSR은 쿠키를 기본안으로 한다(`setLang`이 cookie를 기록하고 `layout.tsx`가 `cookies().get("lang")`을 `<html lang>`과 initialLang에 주입), 인라인 스크립트는 보조.
23. DS-09 증거 #7 교정 — `/`(게이트 없음, SSR KO)만 플래시이고 9곳은 백지이며 미사용 import는 "9파일 44건"이다.
24. DS-19 fix 2 교정 — `recordError`를 `addCustomEvent("render_error", …)`로, 라우트별 loading.tsx 삭제, 루트 error.tsx는 페이지가 마운트한 AppHeader를 대체하므로 자체 헤더를 렌더한다.
25. AuthProvider의 401과 403 정책은 CV-07 소유로 상호 참조한다.
26. `backlog-convenience.md:34,203,340`의 CV-16 참조를 DS-09로 갱신한다.

CV-17 → DS-18 (4건, B4 PR10)
27. `ReliabilityPanel.tsx:30-37` KO 맵 내용 교정("Throttle" → "스로틀링" 등).
28. `frontend/CLAUDE.md:22` "UI text must go through i18n.ts" 규약과 v2.24.0 RUL-3 예외의 결정을 기록한다.
29. `pivotTrend.ts:40` `toLocaleTimeString("ko-KR")` 고정 제거(15~21의 #18과 같은 작업).
30. ClaudeFeaturesPanel(9곳)과 `claudeFeatures.ts`(5곳)는 제외하고 i18n.ts 개편은 v2.24.0 머지 후에 착수한다.

---

## 5. 미검증 P3 (2)

두 항목은 P3라서 적대적 검증을 하지 않았다. 근거는 합성 백로그 수준이며 착수 전 재확인이 필요하다.

| ID | 제목 | 심각도 | 공수 | 크리틱 판정 |
|---|---|---|---|---|
| DS-20 | 아이콘과 타이포 마감 — 이모지를 SVG 아이콘으로, Pretendard, 라디우스와 타입 스케일 문서화 | P3 | M (6~10h) | 유지(B4 PR9). 고유 항목이다. 단 Pretendard 셀프호스팅은 `layout.tsx:6` `Inter({subsets:["latin"]})` 교체이므로 DS-04 타이포 스케일과 같은 PR이 효율적이다 |
| CV-20 | KO 카피 규칙과 낡은 설명 — 가운데 점을 쉼표로, "1." 번호, 영어 용어, surface 6개, 1P 문구, 단가 기준일, BEST 방법론 | P3 | S (3~5h) | 폐기 권고, 완전 흡수. 가운데 점과 번호, 영어 용어, surface 6개, 1P 문구는 DS-18 fix 2와 동일 문장이고 단가 기준일 `PRICING_UPDATED_AT`은 DS-17 fix 3 푸터, BEST 방법론은 DS-16 fix 4와 CV-19다. 남는 고유 부분이 없다 |

---

## 6. 결정이 필요한 항목

아래는 구현 전에 소유자 결정이 있어야 착수 범위가 정해지는 항목이다. 결정 없이 진행하면 되돌리는 비용이 든다.

| # | 항목 | 결정할 내용 | 미결 시 영향 |
|---|---|---|---|
| 1 | N-21 Comparison Lab | 탑재(`/compare` 라우트와 내비, 4~6h) 또는 삭제(컴포넌트와 api.ts 함수 4개, `routers/compare.py`, include_router, `stream_compare_events`, 문서 행, 0.5h) | 검증 노트 4건(DS-10, CV-12, DS-15, DS-18)이 이 파일을 살아 있는 채택 지점으로 계산했다. 결정 전에는 죽은 화면에 프리미티브 채택 공수가 들어간다 |
| 2 | DS-06 심각도 | WCAG AA 적합성과 VPAT를 상용 판매 요건으로 볼 것인지 | 요건이면 P1, 아니면 P2. 어느 쪽이든 B2 첫 PR 고정은 바뀌지 않는다(N-06, N-08, CV-08b, DS-12가 Dialog에 의존) |
| 3 | N-05 비밀번호 재설정과 계정 자기 관리 | 셀프서비스 계정 복구를 제품 범위에 넣을지, 관리자 개입 모델을 유지할지 | 유지하면 비밀번호를 잊은 사용자마다 DB 직접 수정이 필요하다. 도입하면 M 8~12h와 SES 템플릿, 서명 토큰 정책이 따라온다 |
| 4 | N-14 푸터 법적 고지 | 이용 약관과 개인정보 문서를 만들지, "데이터 출처와 문의, RUM 수집" 고지만 둘지 | RUM이 세션을 수집하는데 고지가 0건인 상태가 유지된다 |
| 5 | N-03 색인 정책 | 공개 대시보드로 색인 허용(robots allow + /api, /prompts, /chat disallow)인지 내부 도구(index:false)인지 | robots.txt 404가 유지되고 OG와 sitemap 작업 범위가 정해지지 않는다 |
| 6 | DS-07 기본 모델 선택 | 대시보드 추이 기본값을 "대표 모델"로 되돌릴지 | `AutoDashboard.tsx:58-61`이 2026-07-10 사용자 피드백으로 대표 모델 기본값을 제거한 기록을 남겼다. 되돌리려면 그리드 하이라이트 분리(사용자 클릭 시에만 하이라이트) 또는 명시적 재승인이 필요하다. 현행 유지 시 1440px에서 129선 스파게티가 남는다 |
| 7 | DS-14 대시보드 기간 옵션 | 12개를 유지(overflow-x-auto snap-x)할지 대표 6개와 "더보기"로 줄일지 | 6개로 줄이면 5분 주기 프로버의 분 단위 확대(5m, 10m, 15m, 30m) 용도가 약해진다. 검증은 현행 12개 유지와 스크롤 처방을 기본으로 권고했다 |
| 8 | CV-09 reasoning max_tokens | 512를 2048로 올릴지 | 상한 소진 시 약 +$37/일(월 약 $1,100, 현재 약 $12/일)이라 사용자 승인이 필요하다. 승인 없이도 프론트 사유 표기(P1)는 선행할 수 있다 |
| 9 | CV-09 `truncated` status | 새 status 값을 도입할지 | 도입하면 백엔드 `status=="success"` 필터 20곳에 ripple이 생겨 과금된 thinking 토큰이 비용 집계에서 탈락하고 이상 징후가 30분마다 거짓 경보 20건을 낸다. 검증은 도입 반대와 ADR 별건 처리를 권고했다 |
| 10 | CV-04a GZipMiddleware | 백엔드 압축을 넣을지 CloudFront compress만 쓸지 | 넣으려면 `starlette>=0.46` 핀과 SSE 4경로 비압축 테스트가 필요하다(현 requirements는 `fastapi>=0.109.0`만 핀해 운영 버전이 불확정) |
| 11 | DS-19 iOS 상태바 | `apple-mobile-web-app-status-bar-style`을 "default"(시스템 추종)로 바꿀지, safe-area 띠를 `#030712`로 고정할지 | theme-color 동기화만으로는 홈 화면 앱 상태바가 고쳐지지 않는다. 실기기 검수가 필요하고 이 환경에서는 불가하다 |
| 12 | N-10 CI 범위 | Playwright e2e job을 CI에 상시 편입할지 로컬과 런북 절차로 둘지 | CI 편입이 아니면 DS-01, DS-05, DS-07의 완료 기준을 기계로 잠글 수 없고 회귀가 다음 릴리스에서 재발한다 |

---

## 7. 실행 순서 제안

v2.24.0은 `/claude-features` 상세도 플랜이 점유한다(브랜치 HEAD에 3/16 태스크 커밋). 아래 순서는 그 머지 뒤 v2.25.0부터이며, 핫픽스 세트만 예외로 `main`에서 분기한다.

### 7.1 핫픽스 컷 (당일 배포, 14~20h)

`main`에서 분기해 v2.24.0 머지 전이면 `v2.23.2`, 후면 `v2.24.1`로 태그한다. 순서는 CV-08a 트리거 인증 게이트(1.5~2h) → N-02 results/stats 7일 클램프(1~1.5h) → CV-04a GZipMiddleware(0.5~1h, 결정 10에 따라 CloudFront compress로 대체 가능) → N-01 보안 헤더와 poweredByHeader:false, CORS 축소(2~4h, CSP는 Report-Only) → DS-03 핫픽스 `CostDashboardPanel.tsx:144`(0.3h)와 DS-04 B3-a gray-500, gray-600 변수 상향(2h) → DS-05 390px 4곳과 상태바(3~5h) → CV-13 F-1 RUM 버전 1줄(0.5h) → CV-05a trend >24h와 gptbench SQL GROUP BY, `le=720 → 168`(3~4h).

배포 후 검증 — `curl -sI`로 보안 헤더 6종, `/api/parity/latest` content-encoding, 390px 9페이지 documentElement.scrollWidth, 비인증 `POST /api/auto-probe/trigger` 401, `?start_time=2020-01-01`에서 200과 `window_clamped`. CDK 변경은 HSTS 1줄뿐이라 다음 CDK 배포에 편승한다.

### 7.2 B1 나머지 (v2.25.0)

1. N-10 하네스(PR2, 4~6h)를 먼저 끝낸다. 이후 반응형과 접근성 완료 기준을 기계로 잠그고 후속 항목의 테스트 인프라 가산분 약 8~10h를 제거한다.
2. CV-03a OOM 차단(PR3, 8~10h)은 백엔드 트랙으로 병행한다. 프론트와 독립 배포가 가능하다.
3. CV-01 apiFetch와 ApiError(PR4, 10~14h) → DS-02 ErrorState와 EmptyState(PR5, 17~21h, N-19와 CV-02 fold-in 5건 포함) → CV-07 세션 만료(PR6, 10~13h, N-25 포함) 순서로 잠근다. DS-02, CV-07, CV-08, DS-13이 모두 `ApiError.status`와 code를 전제하므로 CV-01이 선행이다.
4. DS-07a 차트 범례와 팔레트, a11y(PR7, 8~10h)와 N-09 성능(PR8, 3~4h)은 의존이 없어 병행한다.

### 7.3 B2 (v2.26.0)

DS-06 Dialog(PR1)를 첫 PR로 고정한다. N-06 관리자 UI, N-08 삭제 확인, CV-08b ConfirmDialog, DS-12 챗 시트, 로그인 모달 12곳이 전부 Dialog에 의존하므로 심각도 결정(결정 2)과 무관하게 순서가 먼저다. 이어 DS-13 LoginForm과 N-04(PR2) → DS-09 PageShell과 Providers(PR3, DS-19 fix 2, N-03, N-11, CV-16 fold-in 5건 포함) → DS-01 헤더(PR4) → CV-08b와 N-08(PR5) → N-06 관리자 UI(PR6) → DS-12 챗 표면과 N-18(PR7).

선행 조건 — DS-12 fix 1은 DS-06 Dialog, DS-12의 로그인 모달 재사용과 CV-07 fix 4는 DS-09 PageShell이 있어야 한다. ClaudeFeaturesPanel 모달 채택 3곳만 v2.24.0 머지 후로 미룬다.

### 7.4 B3 (v2.27.0), 백엔드와 프론트 2트랙

- 백엔드 — CV-03b(PR1) → CV-04b와 N-24 WAF(PR2, 같은 CDK PR) → CV-05b와 CV-05c(PR3) → CV-09(PR4) → N-07(PR9) → N-22(PR10).
- 프론트 — DS-10 lib/format.ts(PR5, CV-12 fold-in 7건) → DS-08 useAsyncData와 Skeleton(PR6, CV-06 fold-in) → DS-17 FreshnessBadge와 CV-13 F-2(PR7, CV-11 fold-in 7건) → CV-10 훅 v2(PR8).
- 계약 공유는 since, bucket_seconds, owner_id, next_expected_at뿐이고 프론트가 필드 부재를 허용하므로 백엔드만 먼저 배포해도 기존 프론트가 동작한다. DS-17은 DS-10의 fmtDateTime과 fmtRelative를 소비하므로 DS-10이 선행이다.

### 7.5 B4 (v2.28.0, v2.28.1)

- v2.28.0 시각과 접근성 — DS-03 잔여와 DS-04 B3-b(PR1) → DS-16과 N-16, N-23(PR2) → CV-19(PR3) → DS-07b(PR4, DS-10과 CV-05 의존) → DS-11a와 N-17(PR5) → DS-14(PR6) → DS-15 잔여(PR7) → DS-19 잔여와 N-12(PR8) → DS-20(PR9, DS-04와 같은 PR 권고).
- v2.28.1 i18n과 편의 — DS-18과 N-15, CV-17 및 CV-20 fold-in(PR10, v2.24.0 머지 후) → CV-14(PR11) → CV-15와 DS-11b(PR12, `ModelStatusGrid.tsx`를 한 번만 연다) → CV-18(PR13) → CV-13 F-3(PR14) → N-13과 N-14(PR15) → N-21 결정(PR16) → N-05(PR17, 정책 결정 후 선택).
- 프리미티브 소유권 — Tooltip과 Popover는 DS-15, TierLegend와 channelColors는 DS-16, CopyButton과 ExportMenu는 CV-15, DataTable 정렬은 DS-11a가 단일 소유자다. CV-19와 DS-16이 서로의 부품을 소비하되 중복 구현하지 않는다.

### 7.6 선행 관계 요약

1. CV-01 ApiError → DS-02, DS-13, CV-07, CV-08.
2. DS-06 Dialog → N-06, N-08, CV-08b ConfirmDialog, DS-12 시트, v2.24.0 SurfaceDrawer(순서 조정 시).
3. DS-09 PageShell → DS-17 배치 제외, CV-07 fix 4, DS-19 경계 파일의 헤더 처리, N-03 제목, N-06 라우트.
4. N-10 하네스 → DS-01, DS-05, DS-07의 완료 기준과 DS-06, DS-08, DS-14, DS-18의 컴포넌트 테스트.
5. DS-10 format.ts → DS-07b 시간축, DS-17 배지 문구.
6. CV-03a → CV-03b, DS-14 windows.ts의 window 집합.
7. DS-16 StatusPill과 channelColors → CV-09 amber 칩, CV-19 이상치와 티어, DS-07 채널 계열 hex, N-16.
8. v2.24.0 머지 후 착수 — DS-18 전체, DS-14b, DS-11a 매트릭스 카드 뷰, DS-08과 DS-06의 ClaudeFeatures 채택, DS-10의 formatDuration 이관, CV-01의 `api.ts:860-894` 리베이스.

---

## 8. 근거 파일

아래 보고서는 이 세션의 워크플로가 생성한 산출물이며 스크래치패드에 있어 세션이 끝나면 사라진다. **이 문서가 durable 기록이다.** 수치와 앵커를 재확인해야 하면 보고서가 아니라 이 문서의 file:line과 라이브 재측정을 기준으로 삼는다.

- 워크플로 id — `wf_055d172c-307`(영역 리더 6종, 이전 세션), `wf_8986ae30-bfc`(합성 2종, 항목별 검증 26종, 완결성 크리틱).
- 결과 집계 — `scratchpad/ux-audit/result.json`(kept 32, dropped 6, p3 2, critic 24와 번들 4).
- 완결성 크리틱 — `scratchpad/ux-audit/critic.md`(§1.2 fold-in 원장, §2 상용 기준 체크리스트 매트릭스, §3 N-01~N-25, §4 `/efficiency` 재스캔, §5 `/reliability` 재스캔, §6 인사이트 위젯과 Comparison Lab, §7 실행 순서, §8 PR 번들). 이전 판은 `critic.prev.md`.
- 합성 렌즈 2종 — `scratchpad/ux-audit/backlog-design.md`(DS-01~DS-20, 중복 실측표와 프리미티브 맵), `scratchpad/ux-audit/backlog-convenience.md`(CV-01~CV-20).
- 영역 리더 6종 — `scratchpad/ux-audit/dashboard.md`(D-01~23), `analytics-pages.md`(AP-01~24), `explorer-parity-gpt.md`(EPG-01~25), `shell.md`(SH-01~34), `visual.md`(V-01~31), `api-and-errors.json`(API-01~21). id 대조용 `findings-*__FINAL.json` 6종.
- 항목별 검증 보고서 — `scratchpad/ux-audit/verify/{CV-01,CV-02,CV-03,CV-04,CV-05,CV-06,CV-07,CV-08,CV-09,CV-10,CV-11,CV-12,CV-14,CV-15,CV-16,CV-17,CV-18,CV-19,DS-09,DS-10,DS-13,DS-15,DS-16,DS-17,DS-18,DS-19}.md`, `scratchpad/ux-audit/verify-{DS-02,DS-03,DS-12}.md`, `scratchpad/verify-ds01/DS-01-verify.md`(실측 원본 `measure.json`, 스크립트 `measure.js`, 스크린샷 4장), `scratchpad/verify-ds04.md`, `scratchpad/verify-DS-05.md`, `scratchpad/verify-DS-06.md`, `scratchpad/verify-DS-07.md`, `scratchpad/verify-DS-08.md`, `scratchpad/verify-DS-11.md`, `scratchpad/verify-ds14/DS-14.md`, `scratchpad/verify-CV-13.md`.
- 측정 산출물 — `scratchpad/verify-ds05/`, `verify-ds07/`, `verify-ds11/`, `verify-cv15/`, `verify-cv19/`, `cv05/`, `ds15/`(스크립트와 JSON, 스크린샷).
- 감사 방법 — 코드는 HEAD `f11dda9` 워킹트리 직접 열람, 라이브는 https://llm-monitor.whchoi.net 공개 GET과 HEAD만(POST 없음), AWS는 읽기 전용 조회(`ecs describe-tasks`, `cloudwatch get-metric-statistics`, `cloudfront get-distribution-config`, `elbv2 describe-load-balancer-attributes`). 브라우저는 로컬 headless Chromium(playwright-core 1.61~1.63)과 AgentCore 클라우드 Chromium. 저장소 파일은 수정하지 않았다.
- 운영 주의 — 감사와 검증 중 `/api/auto-probe/trend?hours=168`, `/api/gptbench/trend?hours=168`, 7일 분석 조회가 backend 컨테이너 OOM(exit 137)을 3회 유발했다(18:10Z, 18:19Z, 19:02Z, 각 약 90초 전면 5xx). CV-03a와 CV-05a 배포 전에는 이 조회를 라이브에 연속 호출하지 말고 `hours=720`은 절대 호출하지 않는다.
- 원 감사가 인용한 `shots/*.png` 일부는 이 스크래치패드에 존재하지 않는다. 해당 수치는 검증 단계에서 라이브 재측정과 계산 대비로 대체 검증했고 그 결과가 각 항목의 "검증 교정" 행에 반영돼 있다.
