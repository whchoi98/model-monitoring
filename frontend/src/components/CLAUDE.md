# Frontend Components

## Role
React UI components for the monitoring dashboard (27 top-level + a `chat/` subfolder). All are client components (`"use client"`).

## Key Components
- `RumProvider.tsx` — RUM(Real User Monitoring, v2.16.5): 자체 호스팅 `public/rum-sdk.min.js`를 next/script로 로드, appName=llm-monitor. `NEXT_PUBLIC_RUM_ENDPOINT/_API_KEY`는 **빌드 타임** 인라인 — 미설정 빌드는 수집 비활성
- `AppHeader.tsx` — 공용 헤더 (v2.16.0): NavItem 데이터 기반 — 데스크톱(lg+) 가로 내비 / 모바일 햄버거 드롭다운, 페이지별 `actions` 슬롯. 로그인 필요 메뉴(수동 프로브·프롬프트)는 항목 순서상 맨 뒤 (v2.16.1)
- `AutoDashboard.tsx` — Main dashboard: 최근 12h 이상 징후 배너(/api/auto-probe/anomalies) + status panel + model grid + trend charts + workload/model filters
- `ModelStatusGrid.tsx` — family-grouped model cards (40 active models), color-coded metrics
- `TrendChart.tsx` — Recharts LineChart (TTFT / latency / TPS); `MODEL_COLORS` + `FAMILY_FALLBACK`
- `LatencyChart.tsx`, `StatsCards.tsx`, `ProgressBar.tsx` — supporting dashboard widgets
- `ModelSelector.tsx` — multi-select model chips (`selectedModels: Set<string>`)
- `ProbeConfigPanel.tsx` + `StreamingView.tsx` — manual probe config + live SSE token stream
- `ComparePanel.tsx` + `ComparisonView.tsx` — Comparison Lab (N-model parallel invoke)
- `CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx` — per-page analytical panels
- `InsightsPanel.tsx` — SSE stream-regenerate AI insights
- `PromptsPanel.tsx` — prompt CRUD + Bedrock OptimizePrompt target selector
- `ModelExplorer.tsx` — 모델 카드 그리드 + 상세 모달 (API 탭: Converse/InvokeModel/Messages/Responses, `lib/modelExplorer.ts` 유도, v2.9.x)
- `ParityPanel.tsx` — 패리티: provider 요약 카드(세그먼트 막대 `HealthBar`, v2.16.3에서 도넛 대체)+Key Findings 드로어, 직전 런 대비 변경 배너, 모델 콤보박스, 피처별 접이식 그룹(분포 바, Broken 자동 펼침), `EvidenceModal`(Request/Response JSON 접이식) + 수동 트리거 (v2.15.x)
- `ClaudeFeaturesPanel.tsx` — Claude API Features: 5열(CP/Mantle/Bedrock runtime Messages API·InvokeModel·Converse) 매트릭스; 헬스 카드(문서 기준 헬스 docHealth + 6상태 분포 막대 + "{total} 셀" 칩, 클릭 → `SurfaceDrawer` Key Findings 6섹션); 모델 칩(전체/Fable 5.1/Fable 5/Opus 5/Sonnet 5 — `buildGroups(..., modelKey)`, 카드·배너·드로어 동일 필터); 문서 드리프트 배너(0건이면 "문서 드리프트 없음" 카드); 직전 런 대비 변경 배너(`kind` 카탈로그 규칙/실측 태그, 항목 클릭 → 증거 모달, 0건이면 "변경 없음" 카드); 셀 툴팁 모델별 프로브 소요 시간 + 드롭다운 ms/mono model_id; 상태/드리프트 필터 활성 시 그룹 강제 펼침 + 모두 펼치기/접기; 증거 모달(요청 스냅샷·응답 신호·문서 링크·검증 강도 툴팁); 수동 트리거 (`lib/claudeFeatures.ts` 순수 로직 + vitest, v2.24.0). **i18n 예외**: 이 패널과 `ParityPanel`은 `src/lib/i18n.ts` 대신 인라인 `L(en, ko)`/삼항 헬퍼를 쓴다(하위 컴포넌트는 `useLang()` + 로컬 `T`). 라벨은 카탈로그(`labelMaps`)가 단일 출처, 한글 문장은 쉼표 열거·"1." 번호·단정형 판정 문구.
- `LoginForm.tsx` — login + registration (EmailStr) with approval-pending state
- `ResultsTable.tsx`, `HistoryPanel.tsx` — results table + history cards
- `chat/` — `FloatingChat`, `ChatModal`, `ChatPanel`, `ChatInput`, `MessageList`, `MessageMarkdown`

## Patterns
- Color coding: emerald (good) → amber (warning) → rose (bad)
- `model_name` labels carry a `"Bedrock <family> (<channel>)"` / `"Anthropic <family> (US)"` prefix;
  `TrendChart` `MODEL_COLORS` keys and `lib/sortModels.ts` `FAMILY_ORDER` must match these byte-for-byte
- Sort order: Anthropic → Global(Bedrock·OpenAI `(Global)` 공통) → Bedrock US → OpenAI 리전, family newest-first (`sortModels.ts` `channelRank`/`familyRank`)
- Tooltips via `MetricTooltip` with Korean descriptions from i18n
- Auto-refresh via `useAutoRefresh` hook (30s with countdown)
