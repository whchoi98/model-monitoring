# Frontend Components

## Role
React UI components for the monitoring dashboard (24 top-level + a `chat/` subfolder). All are client components (`"use client"`).

## Key Components
- `AppHeader.tsx` — 공용 헤더 (v2.16.0): NavItem 데이터 기반 — 데스크톱(lg+) 가로 내비 / 모바일 햄버거 드롭다운, 페이지별 `actions` 슬롯. 로그인 필요 메뉴(수동 프로브·프롬프트)는 항목 순서상 맨 뒤 (v2.16.1)
- `AutoDashboard.tsx` — Main dashboard: 최근 12h 이상 징후 배너(/api/auto-probe/anomalies) + status panel + model grid + trend charts + workload/model filters
- `ModelStatusGrid.tsx` — family-grouped model cards (28 models), color-coded metrics
- `TrendChart.tsx` — Recharts LineChart (TTFT / latency / TPS); `MODEL_COLORS` + `FAMILY_FALLBACK`
- `LatencyChart.tsx`, `StatsCards.tsx`, `ProgressBar.tsx` — supporting dashboard widgets
- `ModelSelector.tsx` — multi-select model chips (`selectedModels: Set<string>`)
- `ProbeConfigPanel.tsx` + `StreamingView.tsx` — manual probe config + live SSE token stream
- `ComparePanel.tsx` + `ComparisonView.tsx` — Comparison Lab (N-model parallel invoke)
- `CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx` — per-page analytical panels
- `InsightsPanel.tsx` — SSE stream-regenerate AI insights
- `PromptsPanel.tsx` — prompt CRUD + Bedrock OptimizePrompt target selector
- `ModelExplorer.tsx` — 모델 카드 그리드 + 상세 모달 (API 탭: Converse/InvokeModel/Messages/Responses, `lib/modelExplorer.ts` 유도, v2.9.x)
- `ParityPanel.tsx` — 패리티: provider 요약 카드(도넛)+Key Findings 드로어, 직전 런 대비 변경 배너, 모델 콤보박스, 피처별 접이식 그룹(분포 바, Broken 자동 펼침), `EvidenceModal`(Request/Response JSON 접이식) + 수동 트리거 (v2.15.x)
- `LoginForm.tsx` — login + registration (EmailStr) with approval-pending state
- `ResultsTable.tsx`, `HistoryPanel.tsx` — results table + history cards
- `chat/` — `FloatingChat`, `ChatModal`, `ChatPanel`, `ChatInput`, `MessageList`, `MessageMarkdown`

## Patterns
- Color coding: emerald (good) → amber (warning) → rose (bad)
- `model_name` labels carry a `"Bedrock <family> (<channel>)"` / `"Anthropic <family> (US)"` prefix;
  `TrendChart` `MODEL_COLORS` keys and `lib/sortModels.ts` `FAMILY_ORDER` must match these byte-for-byte
- Sort order: Anthropic → Bedrock Global → Bedrock US → OpenAI, family newest-first (`sortModels.ts` `channelRank`/`familyRank`)
- Tooltips via `MetricTooltip` with Korean descriptions from i18n
- Auto-refresh via `useAutoRefresh` hook (30s with countdown)
