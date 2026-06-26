# Frontend Components

## Role
React UI components for the monitoring dashboard (20 top-level + a `chat/` subfolder). All are client components (`"use client"`).

## Key Components
- `AutoDashboard.tsx` — Main dashboard: status panel + model grid + trend charts + workload/model filters
- `ModelStatusGrid.tsx` — family-grouped model cards (22 models), color-coded metrics
- `TrendChart.tsx` — Recharts LineChart (TTFT / latency / TPS); `MODEL_COLORS` + `FAMILY_FALLBACK`
- `LatencyChart.tsx`, `StatsCards.tsx`, `ProgressBar.tsx` — supporting dashboard widgets
- `ModelSelector.tsx` — multi-select model chips (`selectedModels: Set<string>`)
- `ProbeConfigPanel.tsx` + `StreamingView.tsx` — manual probe config + live SSE token stream
- `ComparePanel.tsx` + `ComparisonView.tsx` — Comparison Lab (N-model parallel invoke)
- `CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx` — per-page analytical panels
- `InsightsPanel.tsx` — SSE stream-regenerate AI insights
- `PromptsPanel.tsx` — prompt CRUD + Bedrock OptimizePrompt target selector
- `LoginForm.tsx` — login + registration (EmailStr) with approval-pending state
- `ResultsTable.tsx`, `HistoryPanel.tsx` — results table + history cards
- `chat/` — `FloatingChat`, `ChatModal`, `ChatPanel`, `ChatInput`, `MessageList`, `MessageMarkdown`

## Patterns
- Color coding: emerald (good) → amber (warning) → rose (bad)
- `model_name` labels carry a `"Bedrock <family> (<channel>)"` / `"Anthropic <family> (US)"` prefix;
  `TrendChart` `MODEL_COLORS` keys and `lib/sortModels.ts` `FAMILY_ORDER` must match these byte-for-byte
- Sort order: Anthropic → Bedrock Global → Bedrock US, family newest-first (`sortModels.ts` `channelRank`/`familyRank`)
- Tooltips via `MetricTooltip` with Korean descriptions from i18n
- Auto-refresh via `useAutoRefresh` hook (30s with countdown)
