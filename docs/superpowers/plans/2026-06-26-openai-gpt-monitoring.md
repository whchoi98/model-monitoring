# OpenAI GPT 5.4/5.5 Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenAI GPT-5.4 and GPT-5.5 (each in us-east-1 + us-east-2 = 4 channels) to the Bedrock LLM Monitor via a new OpenAI/Bedrock-Mantle provider path.

**Architecture:** A third provider call-path in `prober.py`, dispatched by an `openai:` model-id prefix (alongside `anthropic:` → CP and bare → boto3 Bedrock). The path uses the `openai` SDK against the Bedrock Mantle OpenAI-compatible endpoint (`/openai/v1`, bearer auth) with native streaming for TTFT capture. Catalog grows 18 → 22.

**Tech Stack:** Python 3.11 (FastAPI/SQLAlchemy backend), `openai>=1.0.0` SDK, Next.js 14/TS frontend, AWS CDK v2 (TypeScript).

## Global Constraints

- Python runtime is 3.11; `X | Y` union syntax is fine. `prober.py` already uses `from __future__ import annotations` (allowed for non-FastAPI modules) — keep it.
- Do NOT add `from __future__ import annotations` to any FastAPI router file that lacks it.
- `frontend/src/lib/pricing.ts` must mirror `backend/pricing.py` **byte-for-byte** in keys, prices, and normalize logic (in-file sync comments mandate this).
- `model_name` labels must be **byte-identical** across `prober.py` (registration) and `frontend/.../TrendChart.tsx` `MODEL_COLORS` keys. Canonical OpenAI label: `OpenAI GPT 5.4 (us-east-1)` / `OpenAI GPT 5.4 (us-east-2)` / `OpenAI GPT 5.5 (us-east-1)` / `OpenAI GPT 5.5 (us-east-2)`.
- Internal model_id key scheme: `openai:<region>:<actual_model_id>` (e.g. `openai:us-east-1:openai.gpt-5.4`).
- Pricing values (USD per 1M tokens, input/output only — cached-input out of scope): GPT-5.4 = `2.75 / 16.50`; GPT-5.5 = `5.50 / 33.00`.
- Env var values: `OPENAI_US_EAST_1_BASE_URL=https://bedrock-mantle.us-east-1.api.aws/openai/v1`, `OPENAI_US_EAST_2_BASE_URL=https://bedrock-mantle.us-east-2.api.aws/openai/v1`, `BEDROCK_OPENAI_GPT_54_MODEL_ID=openai.gpt-5.4`, `BEDROCK_OPENAI_GPT_55_MODEL_ID=openai.gpt-5.5`. Secret: `OPENAI_API_KEY` via SSM SecureString `/bedrock-monitor/openai-api-key`.
- Catalog count 18 → 22 (Bedrock 13 + Anthropic CP 5 + OpenAI 4) in all docs.
- Commit each task to branch `feat/openai-gpt-monitoring`. Conventional-commit messages.
- `openai` SDK is imported **lazily** inside `_get_openai_client` so unit tests (which monkeypatch that factory) run without the package installed.

## File Structure

**Backend (modify):**
- `backend/prober.py` — helpers, `_register_openai_models()`, OpenAI branch in `_probe_single_model` + `_compare_single_model`, retry patterns.
- `backend/requirements.txt` — add `openai>=1.0.0`.
- `backend/main.py` (~line 118) + `backend/auto_prober_runner.py` (~lines 14, 31) — call `_register_openai_models()`.
- `backend/pricing.py` — `_normalize_key` openai strip + 2 `PRICE_TABLE` keys.
- `backend/routers/cost.py` — `_channel()` OpenAI branch.

**Backend (create):**
- `backend/tests/test_openai_probe.py` — probe-branch unit tests.
- `backend/tests/test_openai_pricing.py` — pricing + channel unit tests.

**Frontend (modify):**
- `frontend/src/lib/pricing.ts`, `frontend/src/lib/sortModels.ts`, `frontend/src/lib/version.ts`, `frontend/src/components/TrendChart.tsx`, `frontend/src/components/StreamingView.tsx`.

**CDK (modify):**
- `cdk/lib/stacks/app-services-stack.ts`, `cdk/lib/stacks/scheduler-stack.ts`.

**Docs (modify/create):**
- `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/api-reference.md`, `frontend/src/components/CLAUDE.md`, `docs/runbooks/deploy.md`, new `docs/decisions/ADR-019-openai-bedrock-mantle-provider-path.md`, memory `adding-a-monitored-model.md`.

---

### Task 1: Backend — OpenAI helpers, registration, dependency, wiring

**Files:**
- Modify: `backend/prober.py` (add helpers after line 148; add `_register_openai_models` after `_discover_anthropic_models` at line 107)
- Modify: `backend/requirements.txt`
- Modify: `backend/main.py:118-119`, `backend/auto_prober_runner.py:14,31`
- Test: `backend/tests/test_openai_probe.py` (created here, extended in Task 2)

**Interfaces:**
- Produces: `_is_openai_direct(model_id: str) -> bool`, `_openai_parts(model_id: str) -> tuple[str, str]` (region, actual_id), `_openai_base_url(region: str) -> str`, `_get_openai_client(base_url: str)`, `_map_openai_finish_reason(reason: str | None) -> str | None`, `_register_openai_models() -> None`. Module dict `_OPENAI_REGION_ENV`.

- [ ] **Step 1: Write failing tests for helpers + registration**

Create `backend/tests/test_openai_probe.py`:

```python
"""Unit tests for the OpenAI (Bedrock Mantle) provider path in prober.py.

No live API calls — env is monkeypatched and the OpenAI client is faked in Task 2.
"""
import prober


def test_is_openai_direct():
    assert prober._is_openai_direct("openai:us-east-1:openai.gpt-5.4") is True
    assert prober._is_openai_direct("anthropic:claude-fable-5") is False
    assert prober._is_openai_direct("us.anthropic.claude-opus-4-8") is False


def test_openai_parts():
    region, actual = prober._openai_parts("openai:us-east-2:openai.gpt-5.5")
    assert region == "us-east-2"
    assert actual == "openai.gpt-5.5"


def test_openai_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setenv("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1")
    assert prober._openai_base_url("us-east-1") == "https://e1/openai/v1"
    assert prober._openai_base_url("us-east-2") == "https://e2/openai/v1"


def test_map_openai_finish_reason():
    assert prober._map_openai_finish_reason("stop") == "end_turn"
    assert prober._map_openai_finish_reason("length") == "max_tokens"
    assert prober._map_openai_finish_reason("tool_calls") == "tool_use"
    assert prober._map_openai_finish_reason("content_filter") == "content_filtered"
    assert prober._map_openai_finish_reason(None) is None
    assert prober._map_openai_finish_reason("weird") == "weird"


def test_register_openai_models_registers_four(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setenv("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_54_MODEL_ID", "openai.gpt-5.4")
    monkeypatch.setenv("BEDROCK_OPENAI_GPT_55_MODEL_ID", "openai.gpt-5.5")
    prober._register_openai_models()
    assert prober.AVAILABLE_MODELS["openai:us-east-1:openai.gpt-5.4"] == "OpenAI GPT 5.4 (us-east-1)"
    assert prober.AVAILABLE_MODELS["openai:us-east-2:openai.gpt-5.4"] == "OpenAI GPT 5.4 (us-east-2)"
    assert prober.AVAILABLE_MODELS["openai:us-east-1:openai.gpt-5.5"] == "OpenAI GPT 5.5 (us-east-1)"
    assert prober.AVAILABLE_MODELS["openai:us-east-2:openai.gpt-5.5"] == "OpenAI GPT 5.5 (us-east-2)"


def test_register_openai_models_skips_without_key(monkeypatch):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = len(prober.AVAILABLE_MODELS)
    prober._register_openai_models()
    assert len(prober.AVAILABLE_MODELS) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_openai_probe.py -v`
Expected: FAIL with `AttributeError: module 'prober' has no attribute '_is_openai_direct'`

- [ ] **Step 3: Implement helpers in `backend/prober.py`**

Insert after line 148 (after `_is_reasoning_model`), before `_get_region_for_model`:

```python
# =====================================================================
# OpenAI GPT via Bedrock Mantle (OpenAI-compatible /openai/v1) — Path 4.
# model_id 키 스킴: "openai:<region>:<actual_model_id>" (예: openai:us-east-1:openai.gpt-5.4).
# region이 채널 식별자 (같은 model_id를 두 리전에 호출). bearer 토큰 인증.
# =====================================================================
_OPENAI_REGION_ENV: dict[str, str] = {
    "us-east-1": "OPENAI_US_EAST_1_BASE_URL",
    "us-east-2": "OPENAI_US_EAST_2_BASE_URL",
}

# OpenAI finish_reason → 기존 stop_reason enum(anthropic/bedrock와 정렬).
_OPENAI_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "content_filtered",
}

_openai_client_cache: dict[str, object] = {}


def _is_openai_direct(model_id: str) -> bool:
    return model_id.startswith("openai:")


def _openai_parts(model_id: str) -> tuple[str, str]:
    """openai:<region>:<actual_id> → (region, actual_id)."""
    _, region, actual_id = model_id.split(":", 2)
    return region, actual_id


def _openai_base_url(region: str) -> str:
    env_name = _OPENAI_REGION_ENV.get(region)
    if not env_name:
        raise ValueError(f"Unknown OpenAI region: {region}")
    url = os.environ.get(env_name)
    if not url:
        raise RuntimeError(f"{env_name} not set")
    return url


def _get_openai_client(base_url: str):
    """Lazy-init OpenAI SDK client per base_url. Bedrock Mantle endpoint + bearer key."""
    if base_url not in _openai_client_cache:
        from openai import OpenAI
        _openai_client_cache[base_url] = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=base_url,
        )
    return _openai_client_cache[base_url]


def _map_openai_finish_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    return _OPENAI_FINISH_REASON_MAP.get(reason, reason)


def _register_openai_models() -> None:
    """OPENAI_API_KEY + region별 base_url + model-id env가 있으면 4개 채널 등록.

    누락 시 조용히 skip (해당 채널만 미등록 — 나머지 정상).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.info("OPENAI_API_KEY not set - skipping OpenAI (Bedrock Mantle) models")
        return
    specs = [
        (os.environ.get("BEDROCK_OPENAI_GPT_54_MODEL_ID"), "GPT 5.4"),
        (os.environ.get("BEDROCK_OPENAI_GPT_55_MODEL_ID"), "GPT 5.5"),
    ]
    for actual_id, family in specs:
        if not actual_id:
            continue
        for region, env_name in _OPENAI_REGION_ENV.items():
            if not os.environ.get(env_name):
                continue
            key = f"openai:{region}:{actual_id}"
            label = f"OpenAI {family} ({region})"
            AVAILABLE_MODELS[key] = label
            logger.info("Registered OpenAI model: %s -> %s", key, label)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_openai_probe.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Add the dependency and wire registration into startup**

Edit `backend/requirements.txt` — add after the `anthropic>=0.40.0` line:

```
openai>=1.0.0
```

Edit `backend/main.py` lines 118-119 — change:

```python
        from prober import _discover_anthropic_models
        _discover_anthropic_models()
```

to:

```python
        from prober import _discover_anthropic_models, _register_openai_models
        _discover_anthropic_models()
        _register_openai_models()
```

Edit `backend/auto_prober_runner.py` line 14 — change `from prober import _discover_anthropic_models` to `from prober import _discover_anthropic_models, _register_openai_models`. Then after the `_discover_anthropic_models()` call at line 31, add on the next line (same indentation):

```python
        _register_openai_models()
```

(Read both files first to confirm exact indentation before editing.)

- [ ] **Step 6: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (existing tests + 6 new)

- [ ] **Step 7: Commit**

```bash
git add backend/prober.py backend/requirements.txt backend/main.py backend/auto_prober_runner.py backend/tests/test_openai_probe.py
git commit -m "feat(prober): OpenAI/Bedrock-Mantle helpers + 4-channel registration"
```

---

### Task 2: Backend — OpenAI streaming branch in `_probe_single_model`

**Files:**
- Modify: `backend/prober.py` (add `_openai_create_stream` helper near other helpers; add `elif` branch at line 227 inside `_probe_single_model`; extend `_RETRYABLE_PATTERNS` at lines 166-174)
- Test: `backend/tests/test_openai_probe.py` (extend)

**Interfaces:**
- Consumes (from Task 1): `_is_openai_direct`, `_openai_parts`, `_openai_base_url`, `_get_openai_client`, `_map_openai_finish_reason`.
- Produces: `_openai_create_stream(client, actual_id: str, prompt: str, max_tokens: int)` returning an iterable stream. The OpenAI branch sets the same locals the shared success block reads: `first_token_time`, `collected_text`, `input_tokens`, `output_tokens`, `stop_reason` (and leaves `server_latency_ms = None`).

- [ ] **Step 1: Write failing tests for the streaming branch + param fallback**

Append to `backend/tests/test_openai_probe.py`:

```python
import json
from queue import Queue


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content=None, finish_reason=None):
        self.delta = _Delta(content)
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Chunk:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


class _FakeSession:
    def add(self, *a, **k):
        pass

    def commit(self, *a, **k):
        pass

    def refresh(self, obj, *a, **k):
        from datetime import datetime, timezone
        if getattr(obj, "id", None) is None:
            obj.id = 1
        if getattr(obj, "timestamp", None) is None:
            obj.timestamp = datetime.now(timezone.utc)


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _parse(ev):
    etype = ev.split("event: ", 1)[1].split("\n", 1)[0]
    body = json.loads(ev.split("data: ", 1)[1].rstrip("\n"))
    return etype, body


def _install_fake_openai(monkeypatch, chunks, calls=None):
    class _FakeCompletions:
        def create(self, **kwargs):
            if calls is not None:
                calls.append("mct" if "max_completion_tokens" in kwargs else "mt")
            assert kwargs["stream"] is True
            assert kwargs["stream_options"] == {"include_usage": True}
            return iter(chunks)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeClient())


def test_openai_probe_streams_and_persists(monkeypatch):
    chunks = [
        _Chunk([_Choice(content="Hello")]),
        _Chunk([_Choice(content=" world")]),
        _Chunk([_Choice(content=None, finish_reason="length")]),
        _Chunk([], usage=_Usage(prompt_tokens=12, completion_tokens=5)),
    ]
    _install_fake_openai(monkeypatch, chunks)
    q: Queue = Queue()
    prober._probe_single_model(
        client=None,
        model_id="openai:us-east-1:openai.gpt-5.4",
        model_name="OpenAI GPT 5.4 (us-east-1)",
        prompt="hi",
        temperature=0.1,
        max_tokens=64,
        iteration=1,
        event_queue=q,
        run_id=1,
        db=_FakeSession(),
    )
    events = [_parse(e) for e in _drain(q)]
    types = [t for t, _ in events]
    assert "ttft" in types
    assert types.count("token") == 2
    result = next(b for t, b in events if t == "result")
    assert result["status"] == "success"
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 5
    assert result["output_text"] == "Hello world"
    assert result["stop_reason"] == "max_tokens"
    assert result["ttft_ms"] is not None
    assert result["server_latency_ms"] is None


def test_openai_probe_falls_back_to_max_tokens(monkeypatch):
    chunks = [
        _Chunk([_Choice(content="x", finish_reason="stop")]),
        _Chunk([], usage=_Usage(1, 1)),
    ]
    calls = []

    class _FakeCompletions:
        def create(self, **kwargs):
            if "max_completion_tokens" in kwargs:
                calls.append("mct")
                raise Exception("Unsupported parameter: 'max_completion_tokens'")
            calls.append("mt")
            return iter(chunks)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: _FakeClient())
    q: Queue = Queue()
    prober._probe_single_model(
        client=None,
        model_id="openai:us-east-1:openai.gpt-5.5",
        model_name="OpenAI GPT 5.5 (us-east-1)",
        prompt="hi",
        temperature=0.1,
        max_tokens=64,
        iteration=1,
        event_queue=q,
        run_id=1,
        db=_FakeSession(),
    )
    assert calls == ["mct", "mt"]
    result = next(b for t, b in (_parse(e) for e in _drain(q)) if t == "result")
    assert result["status"] == "success"
    assert result["stop_reason"] == "end_turn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_openai_probe.py::test_openai_probe_streams_and_persists -v`
Expected: FAIL — the model_id falls into the Bedrock `else` branch and errors (no `_openai_create_stream`, no OpenAI handling).

- [ ] **Step 3: Add `_openai_create_stream` helper to `backend/prober.py`**

Insert immediately after `_register_openai_models` (from Task 1):

```python
def _openai_create_stream(client, actual_id: str, prompt: str, max_tokens: int):
    """OpenAI Chat Completions streaming. gpt-5.x reasoning models use
    max_completion_tokens; fall back to max_tokens if the endpoint rejects it.
    temperature는 보내지 않음 (reasoning model 거부 — anthropic 분기와 동일).
    """
    base = dict(
        model=actual_id,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        stream_options={"include_usage": True},
    )
    try:
        return client.chat.completions.create(max_completion_tokens=max_tokens, **base)
    except Exception as exc:
        if "max_completion_tokens" in str(exc):
            logger.info("OpenAI endpoint rejected max_completion_tokens; retrying with max_tokens")
            return client.chat.completions.create(max_tokens=max_tokens, **base)
        raise
```

- [ ] **Step 4: Add the OpenAI branch in `_probe_single_model`**

In `backend/prober.py`, the dispatch at line 227 currently reads `if _is_anthropic_direct(model_id):` ... `else:` (Bedrock). Insert a new `elif` between the Anthropic block (ends line 259) and the `else:` (line 260). The new branch:

```python
            elif _is_openai_direct(model_id):
                region, actual_id = _openai_parts(model_id)
                oa_client = _get_openai_client(_openai_base_url(region))
                stream = _openai_create_stream(oa_client, actual_id, prompt, max_tokens)
                for chunk in stream:
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                        output_tokens = getattr(usage, "completion_tokens", 0) or 0
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    text = getattr(choice.delta, "content", None) if choice.delta else None
                    if text:
                        now = time.monotonic()
                        if first_token_time is None:
                            first_token_time = now
                            ttft_ms = (first_token_time - start_time) * 1000.0
                            event_queue.put(_sse("ttft", {
                                "model_id": model_id,
                                "model_name": model_name,
                                "iteration": iteration,
                                "ttft_ms": round(ttft_ms, 2),
                            }))
                        collected_text.append(text)
                        event_queue.put(_sse("token", {
                            "model_id": model_id,
                            "model_name": model_name,
                            "iteration": iteration,
                            "token": text,
                        }))
                    if choice.finish_reason:
                        stop_reason = _map_openai_finish_reason(choice.finish_reason)
                # OpenAI-compatible 엔드포인트는 server-side latency 미제공 - None 유지.
```

- [ ] **Step 5: Extend retry classification**

In `backend/prober.py`, change `_RETRYABLE_PATTERNS` (lines 166-174) to add OpenAI overload/throttle markers. Replace the closing of the tuple:

```python
    "ModelStreamErrorException",
)
```

with:

```python
    "ModelStreamErrorException",
    # OpenAI (Bedrock Mantle) rate-limit / overload markers.
    "RateLimitError",
    "rate_limit",
    "ServiceUnavailable",
    "overloaded",
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_openai_probe.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/prober.py backend/tests/test_openai_probe.py
git commit -m "feat(prober): OpenAI streaming probe branch + max_tokens fallback + retry markers"
```

---

### Task 3: Backend — OpenAI branch in `_compare_single_model` (Comparison Lab)

**Files:**
- Modify: `backend/prober.py` (`_compare_single_model`, the `if _is_anthropic_direct` / `else` at lines 625-669)
- Test: `backend/tests/test_openai_probe.py` (extend)

**Interfaces:**
- Consumes: same Task 1/2 helpers + `_openai_create_stream`. This function has NO DB; it emits via the local `emit(...)` closure.

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_openai_probe.py`:

```python
def test_openai_compare_emits_result(monkeypatch):
    chunks = [
        _Chunk([_Choice(content="Hi")]),
        _Chunk([_Choice(content=None, finish_reason="stop")]),
        _Chunk([], usage=_Usage(prompt_tokens=3, completion_tokens=2)),
    ]
    _install_fake_openai(monkeypatch, chunks)
    q: Queue = Queue()
    prober._compare_single_model(
        model_id="openai:us-east-1:openai.gpt-5.4",
        prompt="hi",
        max_tokens=64,
        temperature=0.1,
        event_queue=q,
    )
    events = [_parse(e) for e in _drain(q)]
    types = [t for t, _ in events]
    assert "ttft" in types
    assert types.count("token") == 1
    result = next(b for t, b in events if t == "result")
    assert result["status"] == "success"
    assert result["input_tokens"] == 3
    assert result["output_tokens"] == 2
    assert result["output_text"] == "Hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_openai_probe.py::test_openai_compare_emits_result -v`
Expected: FAIL — the OpenAI model_id hits the Bedrock `else` branch and errors.

- [ ] **Step 3: Add the OpenAI branch in `_compare_single_model`**

In `backend/prober.py`, the dispatch at line 625 reads `if _is_anthropic_direct(model_id):` (block ends line 643) ... `else:` (line 644, Bedrock). Insert this `elif` between them:

```python
        elif _is_openai_direct(model_id):
            region, actual_id = _openai_parts(model_id)
            client = _get_openai_client(_openai_base_url(region))
            stream = _openai_create_stream(client, actual_id, prompt, max_tokens)
            for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(usage, "completion_tokens", 0) or 0
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                text = getattr(choice.delta, "content", None) if choice.delta else None
                if text:
                    now = time.monotonic()
                    if first_token_time is None:
                        first_token_time = now
                        emit("ttft", {"ttft_ms": round((now - start_time) * 1000, 2)})
                    collected_text.append(text)
                    emit("token", {"token": text})
```

(Note: `_compare_single_model` does not record `stop_reason`, matching the existing Anthropic/Bedrock compare branches — no change to its result payload.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_openai_probe.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/prober.py backend/tests/test_openai_probe.py
git commit -m "feat(prober): OpenAI branch in Comparison Lab (_compare_single_model)"
```

---

### Task 4: Backend + Frontend — pricing (py + ts mirror)

**Files:**
- Modify: `backend/pricing.py` (`_normalize_key` lines 27-39; `PRICE_TABLE` lines 12-24)
- Modify: `frontend/src/lib/pricing.ts` (`getPricing` lines 31-51; `PRICE_TABLE` lines 16-28)
- Test: `backend/tests/test_openai_pricing.py` (created)

**Interfaces:**
- Consumes: nothing from prior tasks (pure pricing). model_id keys produced in Task 1 are the lookup inputs (`openai:<region>:openai.gpt-5.4`).
- Produces: `get_pricing("openai:...:openai.gpt-5.4")` → `{"input": 2.75, "output": 16.5}`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_openai_pricing.py`:

```python
"""OpenAI pricing normalization + cost estimation."""
import pricing


def test_normalize_openai_key():
    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.4") == "gpt-5.4"
    assert pricing._normalize_key("openai:us-east-2:openai.gpt-5.5") == "gpt-5.5"


def test_get_pricing_openai():
    assert pricing.get_pricing("openai:us-east-1:openai.gpt-5.4") == {"input": 2.75, "output": 16.5}
    assert pricing.get_pricing("openai:us-east-2:openai.gpt-5.5") == {"input": 5.5, "output": 33.0}


def test_estimate_cost_openai():
    # 1M input @2.75 + 1M output @16.5 = 19.25
    assert pricing.estimate_cost_usd("openai:us-east-1:openai.gpt-5.4", 1_000_000, 1_000_000) == 19.25


def test_existing_pricing_unbroken():
    assert pricing.get_pricing("us.anthropic.claude-fable-5") == {"input": 10.0, "output": 50.0}
    assert pricing.get_pricing("anthropic:claude-opus-4-8") == {"input": 15.0, "output": 75.0}
```

(The cost `_channel` test lives in Task 5, which owns the cost.py edit — keeping this file green at the end of Task 4.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_openai_pricing.py -v`
Expected: FAIL — `_normalize_key` returns `openai.gpt-5.4` (not stripped).

- [ ] **Step 3: Edit `backend/pricing.py`**

Add the 2 entries to `PRICE_TABLE` — after the Nova line (`"nova-2-lite-v1:0": {"input": 0.06, "output": 0.24},`):

```python
    # OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
    "gpt-5.4": {"input": 2.75, "output": 16.50},
    "gpt-5.5": {"input": 5.50, "output": 33.00},
```

Edit `_normalize_key`. Change:

```python
    key = model_id
    if key.startswith("anthropic:"):
        key = key[len("anthropic:"):]
    parts = key.split(".", 1)
```

to:

```python
    key = model_id
    if key.startswith("anthropic:"):
        key = key[len("anthropic:"):]
    if key.startswith("openai:"):
        # openai:<region>:<actual_id> → <actual_id>
        key = key.split(":", 2)[-1]
    parts = key.split(".", 1)
```

And change the end of the function:

```python
    if key.startswith("amazon."):
        key = key[len("amazon."):]
    return key
```

to:

```python
    if key.startswith("amazon."):
        key = key[len("amazon."):]
    if key.startswith("openai."):
        key = key[len("openai."):]
    return key
```

- [ ] **Step 4: Edit `frontend/src/lib/pricing.ts` (byte-for-byte mirror)**

Add the 2 entries to `PRICE_TABLE` — after the Nova line (`"nova-2-lite-v1:0": { input: 0.06, output: 0.24 },`):

```typescript
  // OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
  "gpt-5.4": { input: 2.75, output: 16.50 },
  "gpt-5.5": { input: 5.50, output: 33.00 },
```

In `getPricing`, change:

```typescript
  let key = modelId.startsWith("anthropic:") ? modelId.slice("anthropic:".length) : modelId;
  // global.X.Y / us.X.Y → X.Y (Y는 그대로)
  const parts = key.split(".");
```

to:

```typescript
  let key = modelId.startsWith("anthropic:") ? modelId.slice("anthropic:".length) : modelId;
  // openai:<region>:<actual_id> → <actual_id>
  if (key.startsWith("openai:")) key = key.split(":").slice(2).join(":");
  // global.X.Y / us.X.Y → X.Y (Y는 그대로)
  const parts = key.split(".");
```

And change:

```typescript
  if (key.startsWith("anthropic.")) key = key.slice("anthropic.".length);
  if (key.startsWith("amazon.")) key = key.slice("amazon.".length);
```

to:

```typescript
  if (key.startsWith("anthropic.")) key = key.slice("anthropic.".length);
  if (key.startsWith("amazon.")) key = key.slice("amazon.".length);
  if (key.startsWith("openai.")) key = key.slice("openai.".length);
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd backend && python -m pytest tests/test_openai_pricing.py -v`
Expected: PASS (4 tests)
Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/pricing.py frontend/src/lib/pricing.ts backend/tests/test_openai_pricing.py
git commit -m "feat(pricing): GPT-5.4/5.5 token pricing + openai: key normalization (py+ts)"
```

---

### Task 5: Backend — cost channel bucket

**Files:**
- Modify: `backend/routers/cost.py` (`_channel` lines 40-50)
- Test: `backend/tests/test_openai_pricing.py` (append the channel test)

- [ ] **Step 1: Write the failing channel test**

Append to `backend/tests/test_openai_pricing.py`:

```python
from routers.cost import _channel


def test_channel_openai():
    assert _channel("openai:us-east-1:openai.gpt-5.4") == "OpenAI"
    assert _channel("us.anthropic.claude-opus-4-8") == "Bedrock US"
    assert _channel("anthropic:claude-fable-5") == "Anthropic (CP on AWS)"
```

Run: `cd backend && python -m pytest tests/test_openai_pricing.py::test_channel_openai -v`
Expected: FAIL — `_channel` returns `"Other"` for the openai key.

- [ ] **Step 2: Edit `_channel` in `backend/routers/cost.py`**

Change:

```python
    if model_id.startswith("anthropic:"):
        return "Anthropic (CP on AWS)"
```

to:

```python
    if model_id.startswith("anthropic:"):
        return "Anthropic (CP on AWS)"
    if model_id.startswith("openai:"):
        return "OpenAI"
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_openai_pricing.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/cost.py backend/tests/test_openai_pricing.py
git commit -m "feat(cost): bucket openai: model_ids into 'OpenAI' channel"
```

---

### Task 6: Frontend — display plumbing (sort, colors, streaming view, version)

**Files:**
- Modify: `frontend/src/lib/sortModels.ts` (`FAMILY_ORDER` lines 6-14; `channelRank` lines 30-34)
- Modify: `frontend/src/components/TrendChart.tsx` (`MODEL_COLORS` lines 25-44; `FAMILY_FALLBACK` lines 46-54)
- Modify: `frontend/src/components/StreamingView.tsx` (`MODEL_COLORS` lines 11-25; `extractModelName` lines 31-56)
- Modify: `frontend/src/lib/version.ts` (line 3)

**Interfaces:**
- Consumes: backend `model_name` labels from Task 1 (`OpenAI GPT 5.4 (us-east-1)` etc.) and model_id keys (`openai:<region>:openai.gpt-5.x`). No frontend test runner — gate is `npx tsc --noEmit` + visual check at verification.

- [ ] **Step 1: `frontend/src/lib/sortModels.ts`**

In `FAMILY_ORDER`, change the closing entries:

```typescript
  "Claude Haiku 4.5",
  "Nova 2.0 Lite",
];
```

to:

```typescript
  "Claude Haiku 4.5",
  "Nova 2.0 Lite",
  "GPT 5.5",
  "GPT 5.4",
];
```

In `channelRank`, change:

```typescript
export function channelRank(name: string): number {
  if (name.startsWith("Anthropic ")) return 0;
  if (name.includes("(Global)")) return 1;
  return 2; // Bedrock US (default)
}
```

to:

```typescript
export function channelRank(name: string): number {
  if (name.startsWith("Anthropic ")) return 0;
  if (name.includes("(Global)")) return 1;
  if (name.startsWith("OpenAI ")) return 3; // OpenAI 자체 채널 티어 (us-east-1 → us-east-2)
  return 2; // Bedrock US (default)
}
```

- [ ] **Step 2: `frontend/src/components/TrendChart.tsx`**

In `MODEL_COLORS`, change the last Anthropic entry's trailing line:

```typescript
  "Anthropic Claude Haiku 4.5 (US)": "#d946ef",
};
```

to:

```typescript
  "Anthropic Claude Haiku 4.5 (US)": "#d946ef",
  "OpenAI GPT 5.5 (us-east-1)": "#10a37f",
  "OpenAI GPT 5.5 (us-east-2)": "#0d8a6a",
  "OpenAI GPT 5.4 (us-east-1)": "#34d399",
  "OpenAI GPT 5.4 (us-east-2)": "#059669",
};
```

In `FAMILY_FALLBACK`, change:

```typescript
  ["Nova", "#84cc16"],
];
```

to:

```typescript
  ["Nova", "#84cc16"],
  ["GPT 5.5", "#10a37f"],
  ["GPT 5.4", "#34d399"],
];
```

- [ ] **Step 3: `frontend/src/components/StreamingView.tsx`**

In `MODEL_COLORS`, change:

```typescript
  "Nova 2.0 Lite": "bg-amber-600",
};
```

to:

```typescript
  "Nova 2.0 Lite": "bg-amber-600",
  "GPT 5.5 (us-east-1)": "bg-emerald-600",
  "GPT 5.5 (us-east-2)": "bg-emerald-700",
  "GPT 5.4 (us-east-1)": "bg-green-600",
  "GPT 5.4 (us-east-2)": "bg-green-700",
};
```

In `extractModelName`, change:

```typescript
  if (modelId.includes("nova")) return "Nova 2.0 Lite";
  return modelId;
}
```

to:

```typescript
  if (modelId.includes("nova")) return "Nova 2.0 Lite";
  if (modelId.includes("gpt-5.5")) {
    return modelId.includes("us-east-2") ? "GPT 5.5 (us-east-2)" : "GPT 5.5 (us-east-1)";
  }
  if (modelId.includes("gpt-5.4")) {
    return modelId.includes("us-east-2") ? "GPT 5.4 (us-east-2)" : "GPT 5.4 (us-east-1)";
  }
  return modelId;
}
```

- [ ] **Step 4: `frontend/src/lib/version.ts`**

Change `export const APP_VERSION = 'v2.3.0';` to `export const APP_VERSION = 'v2.4.0';` (preserve the exact quote style used in the file).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/sortModels.ts frontend/src/components/TrendChart.tsx frontend/src/components/StreamingView.tsx frontend/src/lib/version.ts
git commit -m "feat(frontend): surface OpenAI GPT family (sort, colors, streaming view, v2.4.0)"
```

---

### Task 7: CDK — inject OPENAI_* into backend + autoprober/insights tasks

**Files:**
- Modify: `cdk/lib/stacks/app-services-stack.ts` (SSM import after line 118; `backendSecrets` lines 120-132; `backendEnv` lines 134-137)
- Modify: `cdk/lib/stacks/scheduler-stack.ts` (SSM import after line 119; `buildTaskDef` env lines 151-154 + secrets lines 155-165)

**Interfaces:**
- Consumes: SSM SecureString `/bedrock-monitor/openai-api-key` (operator-created — see Task 9). No code from prior tasks.

- [ ] **Step 1: `cdk/lib/stacks/app-services-stack.ts` — add SSM import**

After the `anthropicWorkspaceIdParam` block (ends line 118), add:

```typescript
    // OpenAI via Bedrock Mantle (Path 4) - 사전 생성된 SSM SecureString import. 없어도 동작.
    const openaiApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      "OpenAiApiKeyParam",
      { parameterName: "/bedrock-monitor/openai-api-key" },
    );
```

- [ ] **Step 2: add to `backendSecrets` and `backendEnv`**

In `backendSecrets`, change:

```typescript
      ANTHROPIC_WORKSPACE_ID: ecs.Secret.fromSsmParameter(anthropicWorkspaceIdParam),
    };
```

to:

```typescript
      ANTHROPIC_WORKSPACE_ID: ecs.Secret.fromSsmParameter(anthropicWorkspaceIdParam),
      OPENAI_API_KEY: ecs.Secret.fromSsmParameter(openaiApiKeyParam),
    };
```

In `backendEnv`, change:

```typescript
    const backendEnv: Record<string, string> = {
      AWS_REGION: this.region,
      PYTHONUNBUFFERED: "1",
    };
```

to:

```typescript
    const backendEnv: Record<string, string> = {
      AWS_REGION: this.region,
      PYTHONUNBUFFERED: "1",
      OPENAI_US_EAST_1_BASE_URL: "https://bedrock-mantle.us-east-1.api.aws/openai/v1",
      OPENAI_US_EAST_2_BASE_URL: "https://bedrock-mantle.us-east-2.api.aws/openai/v1",
      BEDROCK_OPENAI_GPT_54_MODEL_ID: "openai.gpt-5.4",
      BEDROCK_OPENAI_GPT_55_MODEL_ID: "openai.gpt-5.5",
    };
```

- [ ] **Step 3: `cdk/lib/stacks/scheduler-stack.ts` — add SSM import**

After the `anthropicWorkspaceIdParam` block (ends line 119), add the same `openaiApiKeyParam` block as Step 1 (identical code, same `"OpenAiApiKeyParam"` id).

- [ ] **Step 4: add to `buildTaskDef` environment + secrets**

Inside `buildTaskDef`, change the `environment` map:

```typescript
        environment: {
          AWS_REGION: this.region,
          PYTHONUNBUFFERED: "1",
        },
```

to:

```typescript
        environment: {
          AWS_REGION: this.region,
          PYTHONUNBUFFERED: "1",
          OPENAI_US_EAST_1_BASE_URL: "https://bedrock-mantle.us-east-1.api.aws/openai/v1",
          OPENAI_US_EAST_2_BASE_URL: "https://bedrock-mantle.us-east-2.api.aws/openai/v1",
          BEDROCK_OPENAI_GPT_54_MODEL_ID: "openai.gpt-5.4",
          BEDROCK_OPENAI_GPT_55_MODEL_ID: "openai.gpt-5.5",
        },
```

And change the `secrets` map's last entry:

```typescript
          ANTHROPIC_WORKSPACE_ID: ecs.Secret.fromSsmParameter(anthropicWorkspaceIdParam),
        },
```

to:

```typescript
          ANTHROPIC_WORKSPACE_ID: ecs.Secret.fromSsmParameter(anthropicWorkspaceIdParam),
          OPENAI_API_KEY: ecs.Secret.fromSsmParameter(openaiApiKeyParam),
        },
```

- [ ] **Step 5: Typecheck (no deploy)**

Run: `cd cdk && npx tsc --noEmit`
Expected: no errors.
Run (parity grep): `grep -rn "OPENAI_API_KEY\|bedrock-mantle" cdk/lib/stacks/` — expect both stacks to show the secret + both base URLs.

- [ ] **Step 6: Commit**

```bash
git add cdk/lib/stacks/app-services-stack.ts cdk/lib/stacks/scheduler-stack.ts
git commit -m "feat(cdk): wire OPENAI_* env + OPENAI_API_KEY secret into backend + scheduler tasks"
```

---

### Task 8: Docs — counts 18→22, ADR-019, deploy runbook, memory

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/api-reference.md`, `frontend/src/components/CLAUDE.md`, `docs/runbooks/deploy.md`
- Create: `docs/decisions/ADR-019-openai-bedrock-mantle-provider-path.md`
- Modify (memory): `/home/ec2-user/.claude/projects/-home-ec2-user-my-project-model-monitoring/memory/adding-a-monitored-model.md` + `MEMORY.md`

**Count framing:** 18 → **22** = Bedrock 13 + Anthropic CP 5 + **OpenAI 4**. (NOT "Bedrock 15" — OpenAI is its own family/channel.)

- [ ] **Step 1: Update catalog counts (grep-driven — line numbers may have drifted)**

Run to find every catalog-count reference: `grep -rn "18\b" CLAUDE.md README.md docs/architecture.md docs/api-reference.md frontend/src/components/CLAUDE.md` and update only genuine model-count references (ignore distractors: "8 stacks", "6 categories", "ADR-018", "20 components", "TLS 1.2", "20GB", "10.20.0.0/16").

Apply these specific edits:
- `CLAUDE.md`: `18 model cards`→`22 model cards`; `1 cycle = 18 models`→`= 22 models`; `AVAILABLE_MODELS (18개)`→`(22개)`; `status + 18 cards`→`22 cards`; `family-grouped 18 cards`→`22 cards`; `MODEL_COLORS 18개 (13 Bedrock + 5 Anthropic CP)`→`22개 (13 Bedrock + 5 Anthropic CP + 4 OpenAI)`; section header `Monitored Models (18 total) / 모니터링 대상 모델 (총 18개)`→`(22 total)` / `(총 22개)`. Add an OpenAI block to the Monitored Models table (new rows below the Claude/Nova table):
  ```markdown

  **OpenAI (Bedrock Mantle, in-region)** — 신규 v2.4.0:

  | Family | us-east-1 | us-east-2 |
  |--------|-----------|-----------|
  | GPT 5.5 | ✅ | ✅ |
  | GPT 5.4 | ✅ | ✅ |

  model_id 키: `openai:<region>:openai.gpt-5.x`. 라벨: `OpenAI GPT 5.x (<region>)`. CP/Bedrock과 다른 3rd provider path (OpenAI-compatible `/openai/v1`, bearer 토큰). 자세히는 ADR-019.
  ```
  Also extend the 라벨 정책 note: OpenAI 라벨은 `"OpenAI <family> (<region>)"` prefix, 정렬은 Anthropic → Bedrock Global → Bedrock US → OpenAI.
- `README.md`: replace `18 LLM channels`/`18 monitored channels`/`18-model`/`18개`/`최신 18개` occurrences with `22`. Extend the 3-path channel description to mention "OpenAI GPT via Bedrock Mantle (Path 4)". Bump ADR range refs `ADR-018`→`ADR-019`.
- `docs/architecture.md`: topology diagram `18 모델`/`18 models`→`22`. Bump ADR range `ADR-018`→`ADR-019` and add a table row `019 | OpenAI/Bedrock-Mantle provider path 추가 (gpt-5.4, gpt-5.5, 4 channels)`. Do NOT alter the historical ADR-017 `13 → 12` row.
- `docs/api-reference.md`: `model_count` example `18`→`22`.
- `frontend/src/components/CLAUDE.md`: `family-grouped model cards (15 models)`→`(22 models)`. Do NOT touch `20 top-level components`.

- [ ] **Step 2: Create `docs/decisions/ADR-019-openai-bedrock-mantle-provider-path.md`**

```markdown
# ADR-019: OpenAI GPT monitoring via Bedrock Mantle (4th provider path)

- **Status**: Accepted
- **Date**: 2026-06-26
- **Supersedes**: —

## Context

We monitored two call paths: boto3 Bedrock `converse_stream` (`global.*`/`us.*`) and
Anthropic CP-on-AWS (`anthropic:*`). The user requested monitoring OpenAI GPT-5.4 and
GPT-5.5, which AWS serves via the **Bedrock Mantle OpenAI-compatible endpoint**
(`https://bedrock-mantle.<region>.api.aws/openai/v1`) — OpenAI Chat Completions shape,
authed with a Bedrock long-term API key as a bearer token. Both models are monitored
in **us-east-1 and us-east-2** (4 channels), in-region (no cross-region profile).

## Decision

Add a 4th provider path keyed by an `openai:<region>:<actual_model_id>` model-id prefix.
- `prober.py` dispatches on the prefix; the OpenAI branch uses the `openai` SDK with a
  per-base-url client, native streaming for TTFT, and `stream_options.include_usage` for
  token counts. `finish_reason` is mapped to the existing stop-reason enum
  (stop→end_turn, length→max_tokens, tool_calls→tool_use, content_filter→content_filtered).
- gpt-5.x reasoning models: temperature is omitted; `max_completion_tokens` is tried first
  with a fallback to `max_tokens` (endpoint-dependent).
- New `OpenAI` display family (label `OpenAI GPT 5.x (<region>)`), its own cost channel.
- Pricing (USD/1M, input/output only; cached-input not tracked): GPT-5.4 2.75/16.50,
  GPT-5.5 5.50/33.00.
- Secret `OPENAI_API_KEY` via SSM SecureString `/bedrock-monitor/openai-api-key`; base URLs
  + model ids as plain env on both backend and scheduler tasks. No new IAM (bearer auth).

Catalog: 18 → 22 (Bedrock 13 + Anthropic CP 5 + OpenAI 4).

## Consequences

- Endpoint quirks (`max_tokens` vs `max_completion_tokens`, whether `include_usage` is
  honored) are verified live, not assumed (see plan Task 9). A (region, model) combo not
  actually served surfaces as error rows.
- See memory `claude-on-aws-endpoint-model-id-matrix` for the now-four call paths.
```

- [ ] **Step 3: Add the operator prerequisite to `docs/runbooks/deploy.md`**

Find the section listing the anthropic-api-key / jwt-secret-key `put-parameter` steps and add (matching that section's format):

```bash
# OpenAI (Bedrock Mantle) bearer key — Path 4. 배포 전 1회, 운영 리전(ap-northeast-2).
aws ssm put-parameter --region ap-northeast-2 \
  --name /bedrock-monitor/openai-api-key --type SecureString \
  --value '<bedrock-long-term-api-key>'
```

Add a note: ⚠️ the key value must be rotated if it was ever shared in plaintext.

- [ ] **Step 4: Update memory**

Edit `/home/ec2-user/.claude/projects/-home-ec2-user-my-project-model-monitoring/memory/adding-a-monitored-model.md`: update the catalog count line to note **22** (Bedrock 13 + CP 5 + OpenAI 4 after v2.4.0, 2026-06-26), and add a short note that OpenAI is a 4th provider path (`openai:<region>:<id>` prefix; frontend touchpoints add a new `OpenAI` family in sortModels/TrendChart/StreamingView; cost `_channel` gets `OpenAI`; no IAM). Update the `MEMORY.md` one-line pointer's "Catalog now 18" → "22". Cross-link `[[claude-on-aws-endpoint-model-id-matrix]]`.

- [ ] **Step 5: Verify no stale counts remain**

Run: `grep -rn "18개\|18 model\|18 LLM\|18 monitored\|18-model\|18 모델" CLAUDE.md README.md docs/ frontend/src/components/CLAUDE.md`
Expected: no genuine catalog-count hits remain (historical ADR text excepted).

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md README.md docs/architecture.md docs/api-reference.md frontend/src/components/CLAUDE.md docs/runbooks/deploy.md docs/decisions/ADR-019-openai-bedrock-mantle-provider-path.md
git commit -m "docs(v2.4.0): catalog 18->22 + ADR-019 OpenAI/Bedrock-Mantle path + deploy runbook"
```

(Memory files are outside the repo — they are saved by the Write tool, not committed.)

---

### Task 9: Verification — live smoke + post-deploy checklist

**Files:** none (operational). This task resolves the three live-endpoint unknowns from the spec.

**Interfaces:** Consumes a real `OPENAI_API_KEY` + base URLs. Cannot be fully done on the feature branch without either a local key or a deployed task.

- [ ] **Step 1 (optional, local): smoke-test the endpoint to resolve unknowns**

Only if the operator wants empirical confirmation before deploy. Requires `pip install openai` and the real key exported. Run this throwaway script (do NOT commit it):

```python
import os
from openai import OpenAI
c = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
           base_url="https://bedrock-mantle.us-east-1.api.aws/openai/v1")
for param in ("max_completion_tokens", "max_tokens"):
    try:
        s = c.chat.completions.create(model="openai.gpt-5.4",
            messages=[{"role": "user", "content": "say hi in 3 words"}],
            stream=True, stream_options={"include_usage": True}, **{param: 32})
        got_usage = False
        for ch in s:
            if getattr(ch, "usage", None):
                got_usage = True
                print(param, "-> usage:", ch.usage.prompt_tokens, ch.usage.completion_tokens)
        print(param, "OK; include_usage honored:", got_usage)
        break
    except Exception as e:
        print(param, "FAILED:", str(e)[:200])
```

Confirms: (a) which token param the endpoint accepts (the code already self-heals via fallback), (b) whether `include_usage` returns a usage chunk (if not, tokens/TPS/cost will be 0 — open a follow-up to parse non-streaming usage), (c) bearer key alone suffices.

- [ ] **Step 2 (post-merge/deploy): build + push backend image with immutable tag**

Follow `docs/runbooks/deploy.md`. Backend image must contain the new code; use an immutable `v<timestamp>` tag (never `:latest` in the task def) per ADR-018. Ensure `/bedrock-monitor/openai-api-key` SSM param exists (Task 8 Step 3) before deploying.

- [ ] **Step 3 (post-deploy): confirm the 4 channels are live**

```bash
curl -s https://d36s7ml54xwemr.cloudfront.net/api/auto-probe/status | jq '.model_count'   # expect 22
curl -s https://d36s7ml54xwemr.cloudfront.net/api/models | jq '.[] | select(.model_id|startswith("openai:"))'
curl -s https://d36s7ml54xwemr.cloudfront.net/api/auto-probe/latest | jq '[.results[] | select(.model_id|startswith("openai:")) | {model_name, status, ttft_ms, output_tokens}]'
```
Expect 4 OpenAI rows; after a probe cycle they show `status: success`, non-null `ttft_ms`, and non-zero `output_tokens`. Check `/cost` shows non-zero OpenAI cost and the dashboard groups them under OpenAI (green trend lines). If `output_tokens` is 0, the endpoint did not honor `include_usage` → follow up.

- [ ] **Step 4: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to open a PR or merge per the user's preference. Rotate the `OPENAI_API_KEY` if it was shared in plaintext.

---

## Self-Review

**Spec coverage:** Every spec §4–§7 item maps to a task — prober helpers/registration/dispatch (T1–T3), requirements (T1), pricing py+ts (T4), cost channel (T5), frontend 4 files (T6), CDK both stacks + secret (T7), docs 18→22 + ADR-019 + runbook + memory (T8), verification of the 3 live unknowns (T9). Spec §9 out-of-scope (cached-input, OptimizePrompt, imageTag policy) intentionally untouched. No gaps.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; tests have real assertions. Doc-count edits are grep-driven because upstream line numbers may have drifted since mapping (the grep + explicit phrase list make them concrete, not vague).

**Type consistency:** Helper names are identical across tasks (`_openai_parts`, `_openai_base_url`, `_get_openai_client`, `_map_openai_finish_reason`, `_openai_create_stream`, `_register_openai_models`). Label strings `OpenAI GPT 5.x (<region>)` and key scheme `openai:<region>:openai.gpt-5.x` are byte-consistent across prober registration (T1), pricing normalization (T4), cost channel (T5), TrendChart MODEL_COLORS (T6), and docs (T8). PRICE_TABLE keys `gpt-5.4`/`gpt-5.5` match what `_normalize_key` produces.

