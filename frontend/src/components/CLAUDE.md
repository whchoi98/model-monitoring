# Frontend Components

## Role
React UI components for the monitoring dashboard.

## Key Components
- `AutoDashboard.tsx` — Main dashboard: status panel + model grid + trend charts
- `ModelStatusGrid.tsx` — 13-card grid with color-coded metrics, sorted by version
- `TrendChart.tsx` — Recharts LineChart for TTFT / latency / TPS time series
- `LoginForm.tsx` — Login + registration form with approval-pending state
- `ProbeRunner.tsx` — Manual probe execution UI with model/prompt selection
- `ResultsTable.tsx` — Paginated probe results table
- `HistoryPanel.tsx` — Card-layout history panel with Global/US sort

## Patterns
- All components are client components (`"use client"`)
- Color coding: emerald (good) → amber (warning) → rose (bad)
- Tooltips via `MetricTooltip` with Korean descriptions from i18n
- Auto-refresh via `useAutoRefresh` hook (30s with countdown)
