# Frontend — Next.js 16 + React

## Role
Dashboard UI for monitoring LLM channel performance — Amazon Bedrock, Claude Platform on AWS and OpenAI (Mantle in-region, Global/US CRIS).

## Tech Stack
- Next.js 16.3.5 (App Router, Node >=20.9)
- React 18 + TypeScript 5.3
- Tailwind CSS 3.4
- Recharts 2.12
- react-markdown 10 + remark-gfm 4 (chat and insights markdown, `components/chat/MessageMarkdown.tsx`)
- Tests: vitest 4.1 (`npm test`), `@playwright/test` 1.63.0 (`npm run test:e2e`, `e2e/`)

## Key Directories
- `src/app/` — Pages and layout (App Router)
- `src/components/` — UI components (dashboard, charts, forms)
- `src/hooks/` — Custom hooks (auto-refresh, SSE streaming)
- `src/lib/` — Utilities (API client, i18n, types)

## Conventions
- 헤더는 `components/AppShell.tsx`가 렌더링하는 공용 `AppHeader` 하나다 — 페이지에서 헤더를 직접 만들거나 `AppHeader`를 따로 import하지 않는다(헤더 없는 `/chat` 팝업은 예외). 모바일은 햄버거 드롭다운, 같은 URL에서 뷰포트 폭으로만 전환
- Public pages use `AppShell`; root `Providers` owns persistent language and authentication state. `useAuth()` provides the shared login dialog. Public reads must not wait for authentication.
- Use `useAsyncResource` for abortable, query-keyed reads and `DataState` / `RefreshControls` for loading, failure, retry and background refresh. Keep errors distinct from empty successful responses.
- Layout cookie reads are asynchronous; `src/proxy.ts` preserves the HTML no-store guard and excludes APIs/PWA assets.
- API calls are same-origin `/api/*` from the browser (`lib/api.ts` `BASE = ""`). In production the internal ALB routes `/api/*` straight to the backend service (the frontend task gets no `BACKEND_INTERNAL_URL`); the `next.config.mjs` rewrite to `BACKEND_INTERNAL_URL` (default `http://localhost:8000`) only serves local runs
- PWA (v2.21.0): `src/app/manifest.ts`(→ /manifest.webmanifest) + `app/icon.png`·`apple-icon.png` 컨벤션 + `public/icons/*`(maskable 포함). iOS standalone은 layout.tsx `appleWebApp`/`viewport-fit=cover` + globals.css의 `display-mode: standalone` safe-area 패딩이 세트 — 아이콘 재생성은 Pillow 스크립트(커밋 메시지 참조), proxy no-store matcher에서 PWA 자산 제외 유지
- UI text must go through `src/lib/i18n.ts` (Korean primary, English secondary)
- Components use Tailwind dark theme (bg-gray-900/950 palette); v2.8.0부터 화이트 테마 토글 (`html.light` class + `light:` variant, `lib/theme.ts`)
- Default model cards group by family (newest first), then channel (Anthropic → Global → US → OpenAI regions). Attention/TTFT sorting uses a flat grid. An empty comparison selection means all models.
- Card metric values are graded per workload category (normal blue / warning amber ▲ / critical rose ◆, v2.28.0). The KO grade names are 양호/경고/위험 — never 정상 for a grade, which belongs to the channel health badge. Thresholds, display rounding and color classes live only in `src/lib/metricGrade.ts` (ADR-029); tests and e2e read the `data-grade` attribute, not color classes.
- Pages: `/` 대시보드 (`/?view=manual` = 수동 프로브, 로그인 필요 — 결과 테이블/차트/비교 분석 탭, 비교 분석 탭은 `ComparisonView`), `/chat` 챗봇 팝업 창(헤더 없음, `FloatingChat`이 여는 `ChatPanel variant="popup"`), `/models` Model Explorer (v2.9.0), `/parity` 패리티 매트릭스 (v2.11.0), `/gpt-on-aws` GPT on AWS 벤치 (v2.18.0), `/claude-features` Claude API Features 매트릭스 (v2.23.0), `/prompts`, `/cost`, `/reliability`, `/efficiency`, `/analysis`

## Commands
```bash
npm run dev    # Development server on :3000
npm run build  # Production build
npm start      # Start production server
npm run typecheck # next typegen && tsc --noEmit (CI, `make frontend-lint`)
npm test       # Data, chart and stream regression tests
npm run test:e2e # Browser flows with fixture APIs
```
