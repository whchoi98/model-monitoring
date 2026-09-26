# Frontend Lib — API client, single-source tables and pure view logic

## Role
Framework-light modules shared by components: the API client, auth/language providers, and pure functions
(sorting, price-table formatting, grading, trend pivoting, feature-matrix aggregation) that vitest covers.

## Key Files
- `api.ts` — every backend call. Token in `localStorage["auth_token"]` (in-memory fallback when storage is blocked); `setToken` dispatches `auth-changed`; a 401 clears the token only if it is still the one that was sent. SSE clients `runProbe`, `chatStream`, `compareStream`, `streamRegenerateInsight` parse `event:` / `data:` blocks by hand. `fetchPricing` (`GET /api/pricing`) and `pricingExportUrl(format, lang)` (v2.30.0)
- `http.ts` — `fetchJson` (20 s default timeout → `TimeoutError`, caller `signal` honored) and `ApiError(status)` carrying FastAPI `detail`. Streams use plain `fetch` with no read timeout
- `auth-context.tsx` — `AuthProvider` / `useAuth()`: one session check and one login dialog for the whole app; `openLogin(afterLogin?)` resumes the action after sign-in (used by `FloatingChat`)
- `i18n.ts` + `i18n-context.tsx` — `ko` / `en` `Translations`, `LanguageProvider` (initial value from the `lang` cookie, then `localStorage`, cross-tab `storage` sync, writes the cookie back), `useT()`, `useLang()`
- `sortModels.ts` — `FAMILY_ORDER` (substring `includes`, so a longer name such as Fable 5.1 / Opus 5.5 must precede its prefix), `channelRank` (Anthropic 0 → `(Global)` 1 → US / OpenAI `(US)` 2 → OpenAI regions 3; keep the branch order), `EXCLUDED_FAMILIES` (Opus 4.5, Sonnet 4.5, `(1P)` — hard filter), `sortResults`, `groupByFamily`
- `monitoring.ts` — card rows and health: `channelKey` (model_id prefix before `:`), `cadenceResolver` (per-channel seconds from `/status` `channel_intervals`, base otherwise), `getFreshness` (stale after cadence + min(cadence, 300 s)), `buildMonitoringRows`, `summarizeMonitoring`, `filterMonitoringRows`
- `metricGrade.ts` — only source of card grade thresholds (`LATENCY_THRESHOLDS` per workload category, `FALLBACK_LATENCY_THRESHOLDS`, `TPS_THRESHOLD` warn < 40 / crit < 15), `roundForDisplay` (grade what is shown), `GRADE_TEXT_CLASS`, `GRADE_MARKER` (ADR-029). `WORKLOAD_CATEGORY_IDS` mirrors `backend/auto_prober.py` `WORKLOAD_PRESETS`
- `pricing.ts` — `formatCost` only. v2.30.0 removed `PRICE_TABLE`, `getPricing` and `estimateCost`: unit prices come from `GET /api/pricing` (ADR-030)
- `pricingTable.ts` — pure helpers for `/pricing` and price display: `formatUnitPrice` (`$4.00`), `formatPricePair` (`$4.00 / $20.00`), `tierBadges` ("unverified" for `stale` / `seed_only` — tooltip "마지막 확인 <date>" for `stale`, "마지막 확인일 없음" when a `stale` tier has no `observed_at`, "초기값" for `seed_only`; "pending", promo note, "promo_check" after `min_until`), `costFromPrices(models, modelId, inputTokens, outputTokens)` (null without a price, Comparison Lab); Model Explorer cards use `formatPricePair`. No sorting and no footnote numbering: the backend sends the order and `n`
- `pivotTrend.ts` — `pivotTrend` to Recharts wide rows + per-series data; `cadenceSeconds` (number or per-model function) breaks a line after a longer silence; `isolatedSampleTimes` keeps lone samples visible
- `trendSelection.ts` — `defaultTrendSelection` (one line per family), `buildTrendQuery` / `parseTrendQuery` (models/hours/category in the URL, `models=all` sentinel)
- `claudeFeatures.ts` — `/claude-features` types and pure logic (`aggregateCell`, `buildGroups`, `surfaceSummary`, `surfaceFindings`, `labelMaps`, change-kind summary, latency helpers); mirrors `backend/claude_features/engine.py` status/verdict vocabulary
- `modelExplorer.ts` — `channelOf`, `nativeId`, `codeExamples`, `modelLinks` per model-id scheme (Bedrock profile, `anthropic:`, `openai:<region|global|us|1p>:`), KO/EN via `lang`
- `format.ts` (`parseTimestamp` treats offset-less DB timestamps as UTC, `formatDateTime`, `formatAge`), `costProjection.ts` (30-day projection), `theme.ts` (`html.light` + `localStorage.theme`, `useTheme`), `chartTheme.ts` (Recharts colors per theme), `types.ts` (shared API types)
- `version.ts` — `APP_VERSION`, canonical app version shown in every header (bump list in root CLAUDE.md)

## Rules
- Never add a price table to the frontend: prices live only in the backend `price_history` table and reach the UI through `/api/pricing`. Render `families`, `references` and footnote numbers in the order the API sends them
- Change grade thresholds only in `metricGrade.ts`; tests and e2e read `data-grade`, and the KO grade name is 양호, never 정상 (`metricGrade.test.ts`)
- New model families: `FAMILY_ORDER` here plus `TrendChart.tsx` `MODEL_COLORS` (labels must match byte-for-byte) and backend `pricing_sources.FAMILY_ORDER` (a pytest reads `sortModels.ts` and pins equality)

## Commands
```bash
cd frontend && npm test        # vitest run — src/**/*.test.{ts,tsx}: lib tests + components GptOnAwsPanel, PricingPanel, ComparePanel
npm run typecheck              # next typegen && tsc --noEmit
```
