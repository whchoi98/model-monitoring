# Frontend — Next.js 14 + React 18

## Role
Dashboard UI for monitoring Bedrock LLM model performance.

## Tech Stack
- Next.js 14.2.5 (App Router)
- React 18 + TypeScript 5.3
- Tailwind CSS 3.4
- Recharts 2.12

## Key Directories
- `src/app/` — Pages and layout (App Router)
- `src/components/` — UI components (dashboard, charts, forms)
- `src/hooks/` — Custom hooks (auto-refresh, SSE streaming)
- `src/lib/` — Utilities (API client, i18n, types)

## Conventions
- 헤더는 공용 `components/AppHeader.tsx` 사용 (페이지별 헤더 중복 금지, v2.16.0) — 모바일은 햄버거 드롭다운, 같은 URL에서 뷰포트 폭으로만 전환
- All `/api/*` requests are proxied to FastAPI via `next.config.mjs` rewrites
- UI text must go through `src/lib/i18n.ts` (Korean primary, English secondary)
- Components use Tailwind dark theme (bg-gray-900/950 palette); v2.8.0부터 화이트 테마 토글 (`html.light` class + `light:` variant, `lib/theme.ts`)
- Model cards are sorted by: channel (Anthropic → Global[Bedrock·OpenAI `(Global)` 공통] → Bedrock US → OpenAI 리전) → family (newest first), via `lib/sortModels.ts` `channelRank`/`familyRank`
- Pages: `/` 대시보드, `/models` Model Explorer (v2.9.0), `/parity` 패리티 매트릭스 (v2.11.0), `/prompts`, `/cost`, `/reliability`, `/efficiency`, `/analysis`

## Commands
```bash
npm run dev    # Development server on :3000
npm run build  # Production build
npm start      # Start production server
```
