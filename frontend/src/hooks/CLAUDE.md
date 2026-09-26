# Frontend Hooks — Data loading, refresh and streaming state

## Role
Client-only (`"use client"`) React hooks shared by pages and panels. Network calls go through `src/lib/api.ts`;
the hooks own request lifecycle and UI state.

## Key Files
- `useAsyncResource.ts` — `useAsyncResource(key, loader(signal))` → `{ data, error, updatedAt, loading, refreshing, refresh }`. Results belong to their `key`: a refresh of the same key keeps the last good data (so a failed background refresh shows the error next to stale data), a new key starts from `null` and never shows the previous query's data. Each refresh aborts the previous request; late or aborted responses are dropped. `loading` = pending with no data, `refreshing` = any pending
- `useAutoRefresh.ts` — `useAutoRefresh(callback, intervalMs = 30000)` → `{ countdown, enabled, setEnabled, reset }`. Deadline-based 1 s ticker; skips ticks while the tab is hidden and refreshes immediately when it becomes visible; never overlaps calls (`inFlightRef`); swallows callback errors — each consumer shows its own error state
- `useChatStream.ts` — chatbot state over `api.chatStream` (SSE): appends user + empty assistant message, accumulates `delta`, records `tool_call` names, keeps `session_id` from the `final` event for the next turn, replaces `followups`; `warning` events surface as `error` text. `send` is ignored while streaming; `reset` aborts and clears the session
- `useProbeStream.ts` — manual probe SSE (`api.runProbe`): tokens / TTFT per `${model_id}:${iteration}`, results, progress (`model_ids.length × repeat_count`), `run_id` on completion. A generation counter drops callbacks from a superseded or stopped run; unmount aborts. `StreamInterruptedError` maps to `t.common.streamInterrupted`
- `usePageTitle.ts` — sets `document.title` and re-applies it through a `MutationObserver` on `<head>`, because streamed fallback metadata would otherwise overwrite the localized title. Used by `AppShell` and `/chat`
- `useUaPopupStrategy.ts` — `openChat(url)` → `{ mode: "popup" | "iframe", popup }` (ADR-009). Firefox and Safari try `window.open(url, "bedrock-monitor-chat", POPUP_FEATURES)`; Chrome and any blocked popup fall back to `"iframe"`, which `FloatingChat` renders as the in-page `ChatModal`. Must be called synchronously inside the click handler or the popup blocker fires

## Rules
- New reads: prefer `useAsyncResource` + `DataState` / `RefreshControls` over ad-hoc `useEffect` fetches, and keep "error" distinct from "empty but successful" (`frontend/CLAUDE.md`)
- Streaming hooks must guard every callback against a newer run (generation counter or a replaced `AbortController`) before calling `setState`
- SSE parsing lives in `src/lib/api.ts` (`runProbe`, `chatStream`); `src/lib/probeStream.test.ts` covers `runProbe` (401 recovery, interrupted stream, server `error` events) — there are no hook-level tests
