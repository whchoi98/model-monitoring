# Frontend App — Next.js App Router routes

## Role
Route entry points, the root layout, PWA manifest/icons and global CSS. Pages stay thin: each wraps one panel
from `src/components/` in `AppShell` (header, page title, `FloatingChat`).

## Key Files
- `layout.tsx` — root layout (server component): reads the `lang` cookie (`await cookies()`, `en` or default `ko`) and passes it to `Providers` (language + auth); inline pre-hydration script restores `localStorage.theme === "light"` to avoid a theme flash; `metadata.appleWebApp` (standalone, `black-translucent`), `formatDetection.telephone: false`, `viewport.viewportFit: "cover"`, `themeColor` `#030712`; mounts `RumProvider`
- `manifest.ts` — served as `/manifest.webmanifest`; `display: "standalone"`, icons from `public/icons/` (192/512 + maskable)
- `icon.png`, `apple-icon.png` — Next.js file-convention app icons
- `globals.css` — gray scale remapped to CSS variables (`:root` dark, `html.light` white — tailwind `light:` variant), shared `@layer components` classes, and the `@media (display-mode: standalone)` block: `header.sticky` gets `env(safe-area-inset-top)` and `body` gets left/right/bottom insets. The selector depends on `AppHeader` rendering `<header className="sticky …">`
- `page.tsx` — `/` dashboard (`AutoDashboard`); `?view=manual` switches to the manual probe view (`useProbeStream`, results/charts/compare tabs, history). `useSearchParams` is read inside `<Suspense>`
- `chat/page.tsx` — `/chat`, the popup-window target of `FloatingChat` (Firefox/Safari). Renders `ChatPanel variant="popup"` without `AppShell` (no header, no floating button); the auth token is shared through same-origin `localStorage`
- `prompts/page.tsx` — login gate via `useAuth()`, then `PromptsPanel`
- `models/`, `parity/`, `gpt-on-aws/`, `claude-features/`, `cost/`, `pricing/` (v2.30.0, `PricingPanel`), `reliability/`, `efficiency/`, `analysis/` — one-line pages: `<AppShell navKey="…"><Panel /></AppShell>`

## Rules
- Every route page except `/chat` exports `dynamic = "force-dynamic"` so HTML is never statically cached (stale buildId chunk URLs caused 404 / blank screens after deploys). `src/proxy.ts` also sets `Cache-Control: no-store` on HTML and its matcher excludes `api`, `_next/static`, `icons/`, `icon.png`, `apple-icon.png`, `manifest.webmanifest` — keep new PWA assets in that exclusion
- `navKey` must match a `key` in `AppHeader.tsx` `useNavItems` (`dashboard`, `manual`, `models`, `parity`, `gptbench`, `features`, `pricing`, …); the active item's label becomes the page title via `usePageTitle`, so an unknown key leaves the title as plain "LLM Monitor"
- A new page = folder + `page.tsx` wrapping a component + a `useNavItems` entry (labels there are inline `L(en, ko)`, not `i18n.ts`)
