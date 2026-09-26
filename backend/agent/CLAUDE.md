# Backend Agent — Chatbot / Insights LLM Layer

## Role
Bedrock Converse helpers, the 4 chatbot tools, AgentCore Memory persistence and SSE helpers shared by
`routers/chat.py` (`/api/chat/stream`), `routers/insights.py` and `insights_runner.py`. No routes live here.

## Key Files
- `bedrock.py` — `CHAT_MODEL_ID` and `INSIGHTS_MODEL_ID`, both `global.anthropic.claude-sonnet-4-6` (the insights job is Sonnet 4.6, not Haiku). `converse_stream_chat` (async generator of `text_delta` / `tool_use` / `stop` / `usage` / `error` dicts; tool input JSON is accumulated per content block, unparseable input becomes `{"_raw": ...}`), `converse_blocking` (insights job, follow-ups), `converse_stream_text` (sync generator for the insights SSE), `tool_spec_for`, `DEFAULT_CHAT_SYSTEM` (Korean). Client region is `AWS_REGION` (CDK injects it), fallback `us-east-1`
- `tools.py` — `TOOL_REGISTRY`: `get_latest_results` (delegates to `latest_results.latest_auto_rows`, so 10-minute CP channels still appear, each row with its own `timestamp`), `get_trend`, `compare_models`, `optimize_prompt` (no DB — returns guidance text for the LLM). DB tools read completed automatic runs through `visibility.visible_only`. `get_trend` clamps `hours` to 1..168, averages into (model, hour) buckets when `hours > 6`, and keeps only the newest `MAX_TREND_POINTS` (2500) — 2026-07-10 incident: raw 168 h points (~1.6M tokens) overflowed the model context. `compare_models` computes avg/p50/p95 on raw values, never on the hourly averages
- `memory.py` — AgentCore Memory via `bedrock-agentcore` `create_event` / `list_events`; ID from `AGENTCORE_MEMORY_ID` (CDK injects SSM `/bedrock-monitor/agentcore-memory-id`; the AgentCore stack sets 30-day event expiry). Best-effort: missing env or any error logs and returns `None` / `[]` so chat keeps working
- `streaming.py` — `sse_event(event, data)` builds `event:` / `data:` strings (`ensure_ascii=False`); `stream_with_final` always ends with one `final` event (`ok: true`, or error type/message plus `on_error_metadata` — the stack trace goes to logs only); `simulate_streaming` is used only by tests

## Wiring in routers/chat.py
- Tool JSON schemas are `_TOOL_SPECS` in `routers/chat.py`, not here. A new tool needs `TOOL_REGISTRY` + `_TOOL_SPECS` + `_invoke_tool` (it passes `db` to every tool except `optimize_prompt`) + `tests/test_tools.py`, which pins the 4-tool set
- `MAX_TOOL_HOPS = 4`; session id = request `session_id` or `chat-{username}-{uuid4().hex[:12]}`, actor `user-{username}`; history = last 20 Memory messages
- Follow-ups: `_generate_followups` → `converse_blocking` with `global.anthropic.claude-haiku-4-5-20251001-v1:0`, only when the answer is at least 20 chars; failures are non-fatal

## Gotchas
- `converse_stream_chat` iterates boto3's synchronous EventStream inside the async generator. `await asyncio.sleep(0)` after each text delta only yields between chunks — waiting for the next chunk still blocks the event loop. `routers/insights.py` pulls `converse_stream_text` chunks with `asyncio.to_thread` instead
- SSE endpoints return these pre-formatted strings via `StreamingResponse(media_type="text/event-stream")`, never `EventSourceResponse` (ADR-007)
- Tests: `tests/test_tools.py`, `tests/test_agent_tools.py` (trend caps on SQLite), `tests/test_streaming.py`
