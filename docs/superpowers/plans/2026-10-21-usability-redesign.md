# Website usability redesign implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild all website screens as a cohesive, readable monitoring workspace that makes the main tasks easy to find and perform.

**Architecture:** Keep the existing Next.js routes, data hooks and backend contracts. Introduce a shared visual vocabulary and page heading, reorganize the dashboard, then migrate every specialized and execution screen. Implementers run sequentially, with task reviews and a final independent review.

**Tech Stack:** Next.js 16, React, TypeScript, Tailwind CSS, existing Recharts, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-21-usability-redesign.md`

## Global Constraints

- Baseline: `bc34c77`, v2.35.1. Final release: v2.36.0.
- Center desktop navigation; Dashboard and Unit Prices remain the first two links.
- Korean default, English supported; preserve existing saved theme preference.
- Preserve all API/auth/catalog/metric/price/SSE contracts and URL state.
- Keep Sonnet 5.5, Haiku 4.5 follow-ups and server visitor counts; no opening-balance UI sentence.
- Native dialog focus/Escape, visible keyboard focus, reduced motion, PWA safe areas, chart semantics and floating-control clearance remain functional.
- New behavior earns browser regression tests; simple visual changes use existing tests and screenshot/geometry verification rather than class-name tests.
- Do not edit unrelated local files, backend behavior or CDK infrastructure.
- Root controller owns release metadata, final verification and deployment.

## Shared interfaces

Task 1 produces `frontend/src/components/PageHeading.tsx`:

```tsx
import type { ReactNode } from "react";

export interface PageHeadingProps {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}
// Default export PageHeading renders one h1, optional short description,
// optional category label, an action slot and a lower context/refresh slot.
```

Shared CSS classes produced by Task 1:

```css
/* page-stack: content spacing, no outer horizontal padding.
   workspace-main: AppShell main owns max-width 1680px and responsive padding.
   ui-panel: elevated neutral panel with border and 14–16px corners.
   ui-panel-muted: subordinate neutral surface.
   ui-toolbar: wrapping controls with 12px gaps and clear alignment.
   ui-stat-card: aligned label / value / context.
   ui-section-heading: section title / optional actions.
   ui-table-shell: only the table scrolls horizontally.
   ui-table: readable header, row separators and tabular alignment.
   ui-label: readable input/control caption.
   ui-button, ui-button-primary, ui-input: existing names, redesigned consistently.
*/
```

Do not infer unlisted shared component APIs. Native HTML plus these classes is sufficient.

### Task 1: Foundation, navigation and dashboard

**Files**

- Create: `frontend/src/components/PageHeading.tsx`, `frontend/src/components/QuickNavigation.tsx`, `frontend/e2e/redesign.spec.ts`.
- Modify: `frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`, `frontend/src/lib/theme.ts`, `frontend/src/lib/i18n.ts`, `frontend/src/components/AppShell.tsx`, `AppHeader.tsx`, `ThemeToggle.tsx`, `Dialog.tsx`, `DataState.tsx`, `RefreshControls.tsx`, `SiteFooter.tsx`, `AutoDashboard.tsx`, `MonitoringOverview.tsx`, `ModelStatusGrid.tsx`, `ModelStatusItem.tsx`, `ModelComparisonDock.tsx`, `TrendComparisonControls.tsx`, `InsightsPanel.tsx`, `TrendChart.tsx`.
- Update directly affected frontend guidance documents to describe shared classes and theme behavior.

**Consumes:** Existing useNavItems, Dialog, query-state functions, monitoring data and all current hooks.

**Produces:** Shared interfaces above; a complete redesigned dashboard and common shell usable by all remaining pages.

- [ ] Add meaningful failing browser cases for quick navigation and theme persistence. Example behavior:

```ts
await page.getByRole("button", { name: "Quick navigation", exact: true }).click();
await page.getByRole("dialog").getByRole("searchbox").fill("Unit Prices");
await page.getByRole("dialog").getByRole("link", { name: /Unit Prices/ }).click();
await expect(page).toHaveURL(/\/pricing$/);
// Also cover Cmd/Ctrl+K, Escape/focus return, no search matches, saved dark/light,
// fresh light default and storage-blocked manual toggling.
```

- [ ] Implement the shared palette, spacing, typography, heading and controls. Keep current Inter; do not introduce a remote runtime font dependency.
- [ ] Rebuild the centered header with an easy-to-find quick-navigation button, current-page state and clear mobile groups. Use native Dialog for page search. Skip global shortcuts during IME composition and while another modal is open.
- [ ] Default new visitors to light mode; honor explicit saved dark/light choices before hydration. Synchronize the html theme classes and theme-color metadata; preserve resilient storage behavior.
- [ ] Reorganize dashboard: compact summary metrics first, workload/filter context next, model results as the main region, collection/attention/AI as a secondary region on large screens. Use a sidebar or two-column composition so repeated summary blocks do not hide the model list below several screens. On mobile use a logical stacked order. Keep all previous information accessible.
- [ ] Move AI analysis near the main work area with an accessible expand/collapse control for long text and a visible Sonnet 5.5 label. Preserve actual refresh/login/streaming behavior.
- [ ] Retain model-card grades, family collapse, URL filters, trend selection, comparison dock and focus scrolling. Restyle charts and legends with the shared surfaces.
- [ ] Run frontend typecheck and unit tests plus relevant shell/dashboard/presence browser checks. Review 1440px and 390px screenshots in both themes.
- [ ] Commit only owned files and write the implementer report including verification and outstanding issues.

### Task 2: All analytics, catalog, pricing and verification screens

**Files**

- Modify `frontend/src/components/CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx`, `ModelExplorer.tsx`, `PricingPanel.tsx`, `ParityPanel.tsx`, `GptOnAwsPanel.tsx`, `ClaudeFeaturesPanel.tsx`.
- Add narrowly scoped CSS to globals.css only when an existing shared class cannot express a necessary page pattern. Preserve shared interfaces.
- Update directly affected guidance and only those existing E2E layout expectations intentionally changed by the design.

**Consumes:** Task 1 PageHeading and shared CSS. Same APIs and data logic as baseline.

**Produces:** A cohesive redesign of all nine specialized pages, including drawers and evidence/details.

- [ ] Replace independent outer padding/max-width wrappers with page-stack; AppShell owns the page width.
- [ ] Use the shared heading and a predictable title → filters/context → summary → details order on every page:

```tsx
<div className="page-stack">
  <PageHeading title={existingTitle} description={existingDescription}
    eyebrow={localizedCategory} actions={existingActions}>
    <RefreshControls {...existingRefreshProps} />
  </PageHeading>
  <div className="ui-panel ui-toolbar">{existingFilters}</div>
  {/* Existing calculations and data, composed into readable shared panels. */}
</div>
```

- [ ] Rebuild the cost/reliability/efficiency/analysis summaries and comparison sections with consistently aligned values and concise contextual copy.
- [ ] Rework model cards and model details for scanning: family/name first, channel and status next, meaningful actions and readable code blocks.
- [ ] Rework pricing presentation while preserving all row/column order, figures, cache/long-context notes, references, export controls and disclaimers. Wide tables scroll inside their panels; keep model identity readable.
- [ ] Rework parity, GPT benchmark and Claude features with clear summaries, filter bars, legends, matrix headings and evidence entry points. Preserve measured/not-applicable/unknown semantics; never manufacture a passing score.
- [ ] Restyle every drawer/dialog owned by these panels, including long JSON/code evidence and mobile close buttons.
- [ ] Run frontend typecheck/unit tests and the existing analytics, pricing, verification, catalog-benchmark and channel-label browser checks. Inspect desktop/mobile and dark/light screenshots.
- [ ] Commit owned changes and write the report with per-page coverage.

### Task 3: Execution workflows, authentication and chat

**Files**

- Modify `frontend/src/app/page.tsx`, `frontend/src/components/ProbeConfigPanel.tsx`, `ModelSelector.tsx`, `StatsCards.tsx`, `ProgressBar.tsx`, `StreamingView.tsx`, `ResultsTable.tsx`, `LatencyChart.tsx`, `ComparisonView.tsx`, `ComparePanel.tsx`, `HistoryPanel.tsx`, `PromptsPanel.tsx`, `LoginForm.tsx`, and `frontend/src/components/chat/*.tsx`.
- Update affected guidance; add behavioral browser coverage only for new interaction.

**Consumes:** Shared PageHeading/classes, existing probe/auth/chat/query hooks.

**Produces:** A finished manual probe, prompt, results, login and chat experience matching the redesigned public pages.

- [ ] Recompose manual probing with clear labelled sections for model selection, prompt/configuration and results. Use a steady workspace grid on desktop and ordered sections on mobile; no hidden required step or state reset.
- [ ] Keep the primary run/stop actions easy to find and execution progress clear. Preserve streaming, partial results, error/final distinctions and selected inputs.
- [ ] Make results, history, charts and comparisons use shared panels and readable tables. Keep filters, empty/error states and dialogs operable.
- [ ] Rebuild prompts as a coherent create/optimize/saved workflow, preserving CRUD, validation and auth.
- [ ] Rebuild login/registration and chat surfaces with readable labels, a clear primary action, keyboard-safe forms, usable suggestions and Markdown. Keep IME behavior, scroll hiding, focus, popup strategy, Sonnet 5.5 label and Haiku follow-ups.
- [ ] Run typecheck/unit tests and history-prompts, chat-fab, visibility and shell browser checks. Inspect 320/390px layouts and popup/modal chat in both themes.
- [ ] Commit owned changes and write the report.

### Task 4: Whole-site verification, release and production

**Files**

- Release metadata: version.ts, package.json/package-lock.json, backend/main.py version only, README.md, CLAUDE.md, CHANGELOG.md.
- Add `docs/reviews/2026-10-21-usability-redesign.md` with per-page before/after findings, validation and screenshots.

**Consumes:** All completed tasks and their reports. No new backend behavior.

**Produces:** v2.36.0 verified and deployed with the current resource/image contract.

- [ ] Review all routes and states against the design, not just the landing page. Fix review findings via the responsible implementer and re-review the actual fixes.
- [ ] Bump all application version strings to v2.36.0, update bilingual changelog and relevant documentation.
- [ ] Run `make verify`; build both production images with immutable tags and explicit digests, injecting current RUM build arguments.
- [ ] Run the production-image Python suite and complete Chromium/WebKit suite. Capture actual screenshots for all primary pages in light/dark and representative mobile layouts; check no body overflow, legible controls, modal keyboard flow, centered navigation and safe footer/FAB/dock spacing.
- [ ] Independently review the entire change set. All material findings must be resolved before deployment.
- [ ] Inspect current AWS images and reviewed CDK differences. Deploy AppServices and all six Scheduler task definitions together if the shared backend version image changes. Do not deploy unrelated stacks.
- [ ] Verify stable running image digests, health, visitor-count preservation, RUM and live pages. Invalidate CloudFront as required.
- [ ] Fast-forward the user's main checkout, preserve unrelated files, push commits and release tag. Report the concrete UI improvements and verification outcome.
