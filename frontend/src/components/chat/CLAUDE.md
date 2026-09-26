# Frontend Chat — Floating chatbot UI

## Role
The chatbot client for `POST /api/chat/stream` (Sonnet 4.6 + 4 tools, `backend/agent/`). `AppShell` mounts
`FloatingChat` on every page except `/chat`; chat requires login.

## Key Files
- `FloatingChat.tsx` — fixed round button (`bottom-24 right-6`). Logged out → `openLogin(showChat)` so the chat opens after sign-in. `showChat` calls `useUaPopupStrategy().openChat("/chat")`: `"popup"` keeps the window in `popupRef` (a second click focuses it), `"iframe"` opens `ChatModal`. Despite the name, `"iframe"` mode renders `ChatPanel` in-page — there is no `<iframe>` (ADR-009 dual mode)
- `ChatModal.tsx` — overlay + fixed 504×640 panel, bottom-right by default; drag by the header bar (position survives close/reopen, "위치 초기화" resets), Escape and overlay click close. Drag handle strings are Korean-only literals
- `ChatPanel.tsx` — shared body for `variant="modal" | "popup"` (close button only in modal). Uses `useChatStream`; shows a login prompt when signed out. Static `SUGGESTED_*` questions on an empty chat, `FOLLOWUP_*` fallbacks until the backend sends `followups` (Haiku 4.5). Header label "Sonnet 4.6" is hard-coded — update it with `agent/bedrock.py` `CHAT_MODEL_ID`
- `MessageList.tsx` — auto-scroll, user text as plain `whitespace-pre-wrap`, assistant text through `MessageMarkdown`, tool-call chips from `toolCalls`, follow-up chips only after the last assistant message completes
- `MessageMarkdown.tsx` — `react-markdown` 10 + `remark-gfm` (tables, code blocks). No `rehype-raw`, so raw HTML in model output is not rendered; links open with `target="_blank" rel="noopener noreferrer"`. `prose-invert` only in dark theme (`useTheme`)
- `ChatInput.tsx` — Enter sends, Shift+Enter newline, ignores Enter during IME composition (`isComposing` / keyCode 229 — needed for Korean input); Stop button calls `cancel` while streaming

## Gotchas
- Popup and page share auth only through same-origin `localStorage["auth_token"]` (`lib/api.ts`). Conversation state lives in each `ChatPanel`'s `useChatStream`: closing the modal unmounts it (`ChatModal` returns `null` when closed), so the messages and `session_id` are dropped and the next open starts a new AgentCore session
- `FloatingChat`'s mount-time interval never starts (`popupRef` is null at mount); a user-closed popup is detected in `showChat` via `popupRef.current.closed`
- Keep raw-HTML rendering off: adding `rehype-raw` would render model output as HTML (XSS)
- Mixed i18n: `ChatPanel`, `ChatInput` and `FloatingChat` use inline `lang === "en"` ternaries, not `src/lib/i18n.ts`
