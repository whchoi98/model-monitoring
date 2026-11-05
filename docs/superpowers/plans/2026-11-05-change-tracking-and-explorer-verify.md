# v2.40.0 — Pricing Run-to-Run Changes and Daily Model Explorer Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/pricing` shows what changed since the previous price sync, and `/models` runs every code example once a day and shows the result and the run-to-run changes — both "like Claude API 기능 검증".

**Architecture:** Model Explorer code examples move to one backend function (`backend/model_explorer/examples.py`) that both `GET /api/explorer/latest` and the new daily ExplorerVerify Fargate task use; the task runs each example's EN code in an isolated child Python and stores `explorer_runs`/`explorer_results`. Every price sync run stores what `/pricing` shows (`price_sync_runs.summary["snapshot"]`), and `/api/pricing` `changes` compares the two latest snapshot runs. The frontend reads both APIs and renders banners, badges and the verification box.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (Python 3.11 runtime, 3.12 locally), pytest; Next.js 16 + React 18 + TypeScript, vitest, Playwright; AWS CDK v2 (EventBridge Scheduler, ECS Fargate), jest.

**Spec:** `docs/superpowers/specs/2026-11-05-change-tracking-and-explorer-verify-design.md` (committed as `3c55e8c` on `feat/v2-40-change-tracking-explorer-verify`).

## How this plan was made

Every code block and diff below was written and run before the plan was saved, in a detached scratch worktree of `c96a592` (main, v2.39.0):

- backend: `python3.12 -m pytest tests/ -q` → 1783 passed, 18 skipped; the new and changed modules also under `python:3.11-slim` with FastAPI 0.162 (CI's newest) → 276 passed; `ruff check` clean
- the Python examples port equals the TS `codeExamples()` output byte for byte for all 49 active channels plus two 1P ids, KO and EN (174 examples)
- frontend: `npx vitest run` → 392 passed; `npm run typecheck` clean; Playwright Chromium → 152 passed, 2 failed — `presence.spec.ts:78` and `shell.spec.ts:9` fail the same way on an untouched `c96a592` checkout with the dev server (real-HTTP presence cookie, dev-server `Cache-Control`), so they are not caused by this work. WebKit does not launch on the dev host.
- cdk: `npx jest --ci` → 98 passed; `tsc --noEmit` clean; eslint 9 warnings, the same 9 as on `c96a592`

So each task's tests are expected to pass as written. If one does not, the plan or the base moved — stop and compare with the hunk instead of improvising.

## Global Constraints

- Work on branch `feat/v2-40-change-tracking-explorer-verify` (it holds the spec commit `3c55e8c` on top of `c96a592`). Never commit to `main`.
- Backend tests are offline: no network beyond 127.0.0.1, no AWS credentials, no provider calls (fake executors and fake scripts only). Run them with `python3.12` (the host `python3` is 3.9). CI runs Python 3.11.
- Child processes of an example get only the allow-listed environment: `AWS_*`, `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, `OPENAI_API_KEY`, `OPENAI_1P_API_KEY`, `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`. Never `DB_*`, `JWT_SECRET_KEY`, `SEED_ADMIN_PASSWORD`, `AGENTCORE_MEMORY_ID`.
- Secret values never enter example code text (placeholders become `os.environ[...]` expressions) and are masked (`***`, values of 8+ characters) before stdout/stderr are stored. Never print a key in a log, a commit or a report.
- No session transaction stays open during the sweep (commit the `running` row first, open a new session to save) — the v2.32.2 rule in `backend/CLAUDE.md`.
- Timestamps are timezone-aware UTC datetimes bound as parameters.
- Korean UI sentences use commas for lists, never the middle dot "·"; result wording is assertive. These panels use inline `L(en, ko)` text, not `i18n.ts`.
- `/api/pricing` exports (CSV, Markdown, JSON) keep their v2.39.0 content — `changes` is page-only.
- `data-tier` stays the first attribute of a price `<td>` (`PricingPanel.test.tsx` reads the markup).
- Production images: immutable tag + `@sha256` digest, full registry URI in `-c backendImage`/`-c frontendImage`, `cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler`. Never `:latest`.
- Deploying (Task 14) is outward-facing: do it only after the user approves the release in this session.

## Spec differences (decided while writing the plan)

1. Snapshot channels and change items carry `region` (the AWS region of an In Region channel, else `null`), so two In Region channels of one family are told apart in the banner ("GPT 5.6 Terra, AWS Bedrock - In Region (us-east-1), …").
2. A failed result's `error_message` is the exception line, a newline, then the stderr tail (1,500 chars); the frontend splits on the first newline (`splitError`). The backend messages stay Korean ("출력 없음", "시간 초과 90초", "자격 증명 미주입: <env>", "알 수 없는 플레이스홀더", "런 시간 상한"); `reasonText` gives their English text on the EN page.
3. A check failure's reason is worded per source: `fetch_failed` 출처 응답 실패, `parse_failed` 출처 파싱 실패 (문서 파싱 실패 on Claude Platform on AWS and OpenAI official price cells, as in the spec example), `offer_count` 공개 오퍼 수 이상, `not_found` 출처에 모델 없음, `deadline` 동기화 시간 상한, `unmapped` 출처 미지정.
4. The cell badge detail of a non-applied change is prefixed by its tag and a colon: "검토 대기: 입력 — → $3.30", "확인 실패: 문서 파싱 실패".
5. `/models` also shows a page-level `DataError` for the explorer API (besides the one in the modal), so a visitor sees why the badges are missing.
6. `python -m explorer_runner --smoke` exits 1 when an example fails (a pre-deploy gate).

## File Structure

| File | Responsibility |
|---|---|
| `backend/model_explorer/examples.py` (new) | The only generator of code examples: `code_examples(model_id)`, `API_IDS`, `API_NAMES`. Pure. |
| `backend/model_explorer/execute.py` (new) | Run one example: placeholder substitution, child Python `-I`, allow-listed env, timeout, retry, masking. |
| `backend/model_explorer/runner.py` (new) | One run: jobs = visible models × examples, 4 workers, deadline, DB rows, retention, smoke. |
| `backend/model_explorer/diff.py` (new) | Run-to-run cell changes (`catalog`, `example`, `measured`). Pure. |
| `backend/explorer_runner.py` (new) | CLI `--once` / `--smoke` for the ExplorerVerify task. |
| `backend/routers/explorer.py` (new) | `GET /api/explorer/latest`, `POST /api/explorer/trigger`. |
| `backend/models.py` | `ExplorerRun`, `ExplorerResult` tables. |
| `backend/pricing_changes.py` (new) | Snapshot builder, snapshot comparison, run selection, `/api/pricing` `changes`. |
| `backend/pricing_sync.py` | Stores the snapshot in each run summary. |
| `backend/routers/pricing.py` | Adds `changes` to `/api/pricing`; exports drop it. |
| `cdk/lib/stacks/scheduler-stack.ts` | ExplorerVerify task def, daily cron, RunTask wildcard. |
| `frontend/src/lib/types.ts`, `api.ts` | Explorer and price-change types, `fetchExplorerLatest`, `triggerExplorerRun`. |
| `frontend/src/lib/explorerVerify.ts` (new) | Badge summary, labels, failure filter, result texts. Pure. |
| `frontend/src/lib/pricingTable.ts` | Change tag, item text, cell id, cell badge. Pure. |
| `frontend/src/lib/modelExplorer.ts` | `codeExamples` removed (`channelOf`, `nativeId`, `modelLinks` stay). |
| `frontend/src/components/ModelExplorer.tsx` | Verification header, banner, badges, filter, modal verification box; code from the API. |
| `frontend/src/components/PricingPanel.tsx` | Change banner, cell ids and highlight, change badge. |
| `frontend/e2e/explorerFixtures.ts` (new), `fixtures.ts`, specs | Explorer fixture; new specs `explorer.spec.ts`, `pricing-changes.spec.ts`. |
| docs | ADR-035, architecture, API reference, runbook §5-12, CLAUDE.md files, CHANGELOG, version strings. |

---
### Task 1: Freeze the v2.39.0 frontend code examples as a golden fixture

The examples move to the backend byte for byte. Before anything changes, dump what the TS generator returns today for one id per channel type, KO and EN. Node 24 imports the `.ts` file directly (type stripping, the 2026-10-19 technique).

**Files:**
- Create: `backend/tests/fixtures/explorer_examples_v2390.json` (generated, ~29 KB)

**Interfaces:**
- Produces: `{"source": str, "examples": {model_id: {"ko": [TSExample], "en": [TSExample]}}}` where `TSExample = {label, api, description, language, code}` (the TS `CodeExample` shape). Task 2's test reads it.

- [ ] **Step 1:** Make sure `frontend/src/lib/modelExplorer.ts` is still the `c96a592` version (`git diff c96a592 -- frontend/src/lib/modelExplorer.ts` prints nothing).
- [ ] **Step 2:** Generate the golden from the repo root:

```bash
cd frontend && node --no-warnings --input-type=module -e '
import { writeFileSync } from "node:fs";
import { codeExamples } from "./src/lib/modelExplorer.ts";
const ids = [
  "global.anthropic.claude-opus-5", "us.anthropic.claude-haiku-5-5", "us.amazon.nova-2-lite-v1:0",
  "bedrock:ap-northeast-2:anthropic.claude-opus-5", "anthropic:claude-sonnet-5-5", "openai:us-east-1:openai.gpt-6-sol",
  "openai:global:global.openai.gpt-6.1-sol", "openai:us:us.openai.gpt-6-astra", "openai:1p:gpt-5.5",
];
const examples = {};
for (const id of ids) examples[id] = { ko: codeExamples(id, "ko"), en: codeExamples(id, "en") };
const golden = { source: "frontend/src/lib/modelExplorer.ts codeExamples() at c96a592 (v2.39.0)", examples };
writeFileSync("../backend/tests/fixtures/explorer_examples_v2390.json", JSON.stringify(golden, null, 2) + "\n");
' && cd ..
```
- [ ] **Step 3:** Run:

```bash
python3.12 -c "import json; g=json.load(open('backend/tests/fixtures/explorer_examples_v2390.json')); print(len(g['examples']), sum(len(v['en']) for v in g['examples'].values()))"
```

Expected: `9 13` (9 ids; 3 + 3 + 1 + 3 + 1 + 1 + 1 + 1 + 1 examples per language), file size about 29 KB.
- [ ] **Step 4:** Commit:

```bash
git add backend/tests/fixtures/explorer_examples_v2390.json
git commit -m "test(explorer): freeze the v2.39.0 frontend code examples as a golden"
```
---

### Task 2: Backend code example generator (single source)

**Files:**
- Create: `backend/model_explorer/__init__.py`, `backend/model_explorer/examples.py`
- Test: `backend/tests/test_explorer_examples.py`

**Interfaces:**
- Consumes: the Task 1 golden.
- Produces: `code_examples(model_id: str) -> list[dict]` — each dict `{"api_id": "converse"|"invoke_model"|"messages"|"responses", "api": str, "label": str, "language": "python", "description": {"ko","en"}, "code": {"ko","en"}, "code_sha": str}` (`code_sha` = SHA-256 hex of `code["en"]`); `API_IDS: tuple[str, ...]`; `API_NAMES: dict[str, str]` (api_id → tab name). Task 3's test imports `code_examples`; Task 4 imports `code_examples`; Task 5 imports `API_NAMES`, `code_examples`.

The test imports `model_explorer.execute.PLACEHOLDERS`, which Task 3 creates — so this task also creates a minimal `execute.py` with only that table in Step 3; Task 3 replaces the file.
- [ ] **Step 1:** Create `backend/tests/test_explorer_examples.py`:

````python
"""model_explorer.examples — the code examples moved from the frontend without a byte changing (v2.40.0, ADR-035).

fixtures/explorer_examples_v2390.json is what frontend/src/lib/modelExplorer.ts codeExamples() returned at c96a592
(v2.39.0) for one model id per channel type, KO and EN, dumped by node importing the .ts file. Regenerate it only for an
intended example change, and then change examples.py in the same commit.
"""

import hashlib
import json
from pathlib import Path

import pytest

from model_explorer.examples import API_IDS, API_NAMES, code_examples
from model_explorer.execute import PLACEHOLDERS
from tests.pricing_catalog import ACTIVE_MODELS

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "explorer_examples_v2390.json").read_text(encoding="utf-8"))
GOLDEN_IDS = list(GOLDEN["examples"])


def _without_comments(code: str) -> list[str]:
    return [line for line in code.split("\n") if not line.lstrip().startswith("#")]


@pytest.mark.parametrize("model_id", GOLDEN_IDS)
@pytest.mark.parametrize("lang", ["ko", "en"])
def test_examples_equal_the_v2390_frontend_output_byte_for_byte(model_id, lang):
    want = GOLDEN["examples"][model_id][lang]
    got = code_examples(model_id)
    assert [(e["label"], e["api"], e["language"], e["description"][lang], e["code"][lang]) for e in got] == [
        (e["label"], e["api"], e["language"], e["description"], e["code"]) for e in want]


def test_the_golden_covers_every_channel_type():
    assert GOLDEN_IDS == [
        "global.anthropic.claude-opus-5", "us.anthropic.claude-haiku-5-5", "us.amazon.nova-2-lite-v1:0",
        "bedrock:ap-northeast-2:anthropic.claude-opus-5", "anthropic:claude-sonnet-5-5",
        "openai:us-east-1:openai.gpt-6-sol", "openai:global:global.openai.gpt-6.1-sol",
        "openai:us:us.openai.gpt-6-astra", "openai:1p:gpt-5.5",
    ]


@pytest.mark.parametrize("model_id", [*ACTIVE_MODELS, "openai:1p:gpt-5.5"])
def test_ko_and_en_differ_only_in_comment_lines(model_id):
    for example in code_examples(model_id):
        assert _without_comments(example["code"]["ko"]) == _without_comments(example["code"]["en"])


@pytest.mark.parametrize("model_id, api_ids", [
    ("global.anthropic.claude-opus-5", ["converse", "invoke_model", "messages"]),
    ("us.anthropic.claude-haiku-5-5", ["converse", "invoke_model", "messages"]),
    ("bedrock:ap-northeast-2:anthropic.claude-sonnet-5", ["converse", "invoke_model", "messages"]),
    ("us.amazon.nova-2-lite-v1:0", ["converse"]),
    ("anthropic:claude-opus-5-5", ["messages"]),
    ("openai:us-east-1:openai.gpt-6.1-terra", ["responses"]),
    ("openai:global:global.openai.gpt-6-luna", ["responses"]),
    ("openai:us:us.openai.gpt-6-sol", ["responses"]),
    ("openai:1p:gpt-5.6-sol", ["responses"]),
])
def test_api_ids_per_channel_type(model_id, api_ids):
    examples = code_examples(model_id)
    assert [e["api_id"] for e in examples] == api_ids
    assert all(e["api"] == API_NAMES[e["api_id"]] and e["api_id"] in API_IDS for e in examples)


def test_every_active_model_has_an_example_and_85_in_all():
    counts = {model_id: len(code_examples(model_id)) for model_id in ACTIVE_MODELS}
    assert min(counts.values()) >= 1
    assert sum(counts.values()) == 85


def test_every_placeholder_in_every_example_is_in_the_substitution_table():
    import re

    for model_id in [*ACTIVE_MODELS, "openai:1p:gpt-5.5"]:
        for example in code_examples(model_id):
            for lang in ("ko", "en"):
                assert set(re.findall(r'"<[^"\n]*>"', example["code"][lang])) <= set(PLACEHOLDERS), (model_id, lang)


def test_code_sha_is_the_sha256_of_the_en_code():
    for model_id in GOLDEN_IDS:
        for example in code_examples(model_id):
            assert example["code_sha"] == hashlib.sha256(example["code"]["en"].encode("utf-8")).hexdigest()


def test_the_in_region_key_calls_its_own_region_with_the_bare_fm_id():
    converse = code_examples("bedrock:ap-northeast-2:anthropic.claude-opus-5")[0]["code"]["en"]
    assert 'region_name="ap-northeast-2"' in converse and 'modelId="anthropic.claude-opus-5"' in converse
    assert "bedrock:" not in converse


def test_us_profiles_call_us_east_1_and_global_profiles_seoul():
    assert 'region_name="us-east-1"' in code_examples("us.anthropic.claude-opus-5")[0]["code"]["en"]
    assert 'region_name="ap-northeast-2"' in code_examples("global.anthropic.claude-opus-5")[0]["code"]["en"]
````
- [ ] **Step 2:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_examples.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'model_explorer'`.
- [ ] **Step 3a:** Create `backend/model_explorer/__init__.py`:

````python
"""Model Explorer code example verification (v2.40.0, ADR-035): examples, execute, runner, diff."""
````
- [ ] **Step 3b:** Create `backend/model_explorer/examples.py`:

````python
"""Model Explorer code examples (v2.40.0, ADR-035) — the one source of the /models code examples.

Moved byte for byte from frontend/src/lib/modelExplorer.ts codeExamples() (v2.39.0): the golden
tests/fixtures/explorer_examples_v2390.json pins the move. The page shows these strings and the daily ExplorerVerify
run executes the EN code (explorer_runner), so what is shown is what is verified.

Key schemes (backend prober.py, frontend channelOf):
  global.* / us.*            Bedrock inference profile, called from the prober _REGION_MAP region
                             (global.* ap-northeast-2, us.* us-east-1 — a us.* profile from ap-northeast-2 is
                             "The provided model identifier is invalid", 2026-10-19)
  bedrock:<region>:<fm id>   Bedrock in-region on-demand, the key's region and the bare FM id
  anthropic:<id>             Claude Platform on AWS (vendor endpoint + anthropic-workspace-id header)
  openai:<region>:<id>       OpenAI on Bedrock Mantle
  openai:global:<id>         OpenAI Global CRIS (Seoul bedrock-runtime OpenAI-compatible endpoint)
  openai:us:<id>             OpenAI US CRIS (us-east-1 bedrock-runtime OpenAI-compatible endpoint)
  openai:1p:<id>             OpenAI 1P direct (api.openai.com)

KO and EN differ only in comment lines (lines that start with "#" after leading spaces) — pinned by tests, so the run
executes the EN code once per example. Pure functions: no DB, no network.
"""

from __future__ import annotations

import hashlib

API_IDS = ("converse", "invoke_model", "messages", "responses")  # stable run-to-run cell keys (tab names may change)
API_NAMES = {"converse": "Converse API", "invoke_model": "InvokeModel API", "messages": "Messages API",
             "responses": "Responses API"}

_CP_ENDPOINT = "https://aws-external-anthropic.us-east-2.api.aws"


def _channel(model_id: str) -> str:
    """bedrock | anthropic-cp | openai-mantle | openai-1p — frontend ChannelType."""
    if model_id.startswith("anthropic:"):
        return "anthropic-cp"
    if model_id.startswith("openai:1p:"):
        return "openai-1p"
    if model_id.startswith("openai:"):
        return "openai-mantle"
    return "bedrock"


def _native_id(model_id: str) -> str:
    """The model id the call sends (frontend nativeId)."""
    if model_id.startswith("anthropic:"):
        return model_id[len("anthropic:"):]
    if model_id.startswith(("openai:", "bedrock:")):
        return ":".join(model_id.split(":")[2:])
    return model_id


def _bedrock_region(model_id: str) -> str:
    if model_id.startswith("bedrock:"):
        return model_id.split(":")[1]
    return "us-east-1" if model_id.startswith("us.") else "ap-northeast-2"


def _openai_endpoint(model_id: str) -> str:
    if model_id.startswith("openai:global:"):
        return "https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1"
    if model_id.startswith("openai:us:"):
        return "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"
    return f"https://bedrock-mantle.{model_id.split(':')[1]}.api.aws/openai/v1"


def _example(api_id: str, label: str, description: dict[str, str], code: dict[str, str]) -> dict:
    return {
        "api_id": api_id,
        "api": API_NAMES[api_id],
        "label": label,
        "language": "python",
        "description": description,
        "code": code,
        "code_sha": hashlib.sha256(code["en"].encode("utf-8")).hexdigest(),
    }


def _both(build) -> dict[str, str]:
    """{"ko": build(L_ko), "en": build(L_en)} where L(en, ko) picks the language — the TS L() helper."""
    return {"ko": build(lambda en, ko: ko), "en": build(lambda en, ko: en)}


def _lines(*lines: str) -> str:
    return "\n".join(lines)


def _bedrock_examples(model_id: str) -> list[dict]:
    mid = _native_id(model_id)
    region = _bedrock_region(model_id)
    converse = _example(
        "converse", "Python (boto3)",
        {
            "en": "Bedrock unified conversation API — every Bedrock model is called with the same request shape, so you can swap models without code changes. Use converse_stream for streaming. This monitor's prober uses this API.",
            "ko": "Bedrock의 통합 대화 API — 모든 Bedrock 모델을 동일한 요청 형식으로 호출하므로 코드 수정 없이 모델을 교체할 수 있습니다. 스트리밍은 converse_stream을 사용합니다. 이 모니터의 prober도 이 API를 사용합니다.",
        },
        _both(lambda L: _lines(
            "import boto3",
            "",
            f'client = boto3.client("bedrock-runtime", region_name="{region}")',
            "",
            "response = client.converse_stream(",
            f'    modelId="{mid}",',
            '    messages=[{"role": "user", "content": [{"text": "Hello!"}]}],',
            '    inferenceConfig={"maxTokens": 512},',
            ")",
            'for event in response["stream"]:',
            '    if "contentBlockDelta" in event:',
            '        print(event["contentBlockDelta"]["delta"].get("text", ""), end="")',
        )),
    )
    # InvokeModel needs the model-native payload — examples for Claude (Anthropic) models only.
    if "anthropic" not in model_id:
        return [converse]
    invoke = _example(
        "invoke_model", "Python (boto3)",
        {
            "en": "Low-level API that passes the model-native payload as-is — use it to control model-specific schemas (Anthropic Messages format for Claude) and fine-grained parameters. Changing the model means changing the request body too.",
            "ko": "모델 네이티브 페이로드를 그대로 전달하는 저수준 API — 모델 고유 스키마(Claude는 Anthropic Messages 형식)와 세부 파라미터를 직접 제어할 때 사용합니다. 모델을 바꾸면 요청 본문도 함께 바꿔야 합니다.",
        },
        _both(lambda L: _lines(
            "import boto3, json",
            "",
            f'client = boto3.client("bedrock-runtime", region_name="{region}")',
            "",
            "response = client.invoke_model(",
            f'    modelId="{mid}",',
            "    body=json.dumps({",
            '        "anthropic_version": "bedrock-2023-05-31",',
            '        "max_tokens": 512,',
            '        "messages": [{"role": "user", "content": "Hello!"}],',
            "    }),",
            ")",
            'result = json.loads(response["body"].read())',
            L("# Opus 5 and Fable 5 return a thinking block first — print only the text blocks",
              "# Opus 5, Fable 5는 thinking 블록을 먼저 돌려준다 — text 블록만 출력"),
            'print("".join(b["text"] for b in result["content"] if b["type"] == "text"))',
        )),
    )
    messages = _example(
        "messages", "Python (anthropic SDK)",
        {
            "en": "Use the Anthropic-native API on top of Bedrock — the anthropic SDK AnthropicBedrock client signs Messages-format requests with SigV4 and forwards them to Bedrock (no Anthropic API key; billing and IAM stay in your AWS account). Note: the Bedrock Mantle /anthropic endpoint (bearer token, some regions e.g. us-east-1) also accepts the same Messages format.",
            "ko": "Anthropic 네이티브 API를 Bedrock 위에서 그대로 쓰는 방식 — anthropic SDK의 AnthropicBedrock 클라이언트가 Messages 형식 요청을 SigV4로 서명해 Bedrock으로 전달합니다. Claude 전용 파라미터를 Anthropic 문서 그대로 사용하면서 과금·권한은 AWS 계정으로 관리할 때 사용합니다. 참고: Bedrock Mantle /anthropic 엔드포인트(bearer 토큰, us-east-1 등 일부 리전)로도 동일한 Messages 형식 호출이 가능합니다.",
        },
        _both(lambda L: _lines(
            "from anthropic import AnthropicBedrock",
            "",
            L("# Via Bedrock — AWS credentials (SigV4), no Anthropic API key required",
              "# Bedrock 경유 — AWS 자격 증명(SigV4) 사용, Anthropic API 키 불필요"),
            f'client = AnthropicBedrock(aws_region="{region}")',
            "",
            "with client.messages.stream(",
            f'    model="{mid}",',
            "    max_tokens=512,",
            '    messages=[{"role": "user", "content": "Hello!"}],',
            ") as stream:",
            "    for text in stream.text_stream:",
            '        print(text, end="")',
        )),
    )
    return [converse, invoke, messages]


def _cp_examples(model_id: str) -> list[dict]:
    mid = _native_id(model_id)
    return [_example(
        "messages", "Python (anthropic SDK)",
        {
            "en": "Anthropic-native API — the most complete support for Claude-specific features (extended thinking, prompt caching, ...). Called here via the Claude Platform on AWS endpoint with a workspace header.",
            "ko": "Anthropic 네이티브 API — Claude 전용 기능(확장 사고, 프롬프트 캐싱 등)을 가장 완전하게 지원합니다. 여기서는 Claude Platform on AWS 엔드포인트와 workspace 헤더로 호출합니다.",
        },
        _both(lambda L: _lines(
            "from anthropic import Anthropic",
            "",
            L("# Claude Platform on AWS — vendor endpoint + workspace header",
              "# Claude Platform on AWS — vendor endpoint + workspace 헤더"),
            "client = Anthropic(",
            '    api_key="<ANTHROPIC_API_KEY>",',
            f'    base_url="{_CP_ENDPOINT}",',
            '    default_headers={"anthropic-workspace-id": "<ANTHROPIC_WORKSPACE_ID>"},',
            ")",
            "",
            "with client.messages.stream(",
            f'    model="{mid}",',
            "    max_tokens=512,",
            '    messages=[{"role": "user", "content": "Hello!"}],',
            ") as stream:",
            "    for text in stream.text_stream:",
            '        print(text, end="")',
        )),
    )]


def _responses_tail(mid: str) -> tuple[str, ...]:
    return (
        "stream = client.responses.create(",
        f'    model="{mid}",',
        '    input="Hello!",',
        "    stream=True,",
        ")",
        "for event in stream:",
        '    if event.type == "response.output_text.delta":',
        '        print(event.delta, end="")',
    )


def _openai_mantle_examples(model_id: str) -> list[dict]:
    mid = _native_id(model_id)
    # Global and US CRIS use the same openai SDK call on the bedrock-runtime OpenAI-compatible endpoint, so the
    # description and comment do not say "Bedrock Mantle" for them.
    cris = model_id.startswith(("openai:global:", "openai:us:"))
    if cris:
        description = {
            "en": "OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Cross-region profiles (global.* and us.*) are served by the bedrock-runtime OpenAI-compatible endpoint (not the bedrock-mantle host); the call shape is identical and the key is a Bedrock bearer (ABSK-...).",
            "ko": "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. cross-region 프로파일(global.*, us.*)은 bedrock-runtime OpenAI 호환 엔드포인트로 호출합니다(bedrock-mantle 호스트 미지원). 호출 형식은 동일하며 키는 Bedrock bearer(ABSK-…)를 사용합니다.",
        }
        comment = ("# Bedrock CRIS (cross-region profile) — bedrock-runtime OpenAI-compatible endpoint + Bedrock bearer key (ABSK-...)",
                   "# Bedrock CRIS(cross-region 프로파일) — bedrock-runtime OpenAI 호환 엔드포인트 + Bedrock bearer 키(ABSK-…)")
    else:
        description = {
            "en": "OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Bedrock Mantle is an OpenAI-compatible endpoint, so the call shape is identical but the key is a Bedrock bearer (ABSK-...).",
            "ko": "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. Bedrock Mantle은 OpenAI 호환 엔드포인트라 동일한 형식으로 호출하되, 키는 Bedrock bearer(ABSK-…)를 사용합니다.",
        }
        comment = ("# Bedrock Mantle — OpenAI-compatible endpoint + Bedrock bearer key (ABSK-...)",
                   "# Bedrock Mantle — OpenAI 호환 엔드포인트 + Bedrock bearer 키(ABSK-…)")
    return [_example(
        "responses", "Python (openai SDK)", description,
        _both(lambda L: _lines(
            "from openai import OpenAI",
            "",
            L(*comment),
            "client = OpenAI(",
            '    api_key="<ABSK-...>",  # Bedrock long-term API key',
            f'    base_url="{_openai_endpoint(model_id)}",',
            ")",
            "",
            *_responses_tail(mid),
        )),
    )]


def _openai_1p_examples(model_id: str) -> list[dict]:
    mid = _native_id(model_id)
    return [_example(
        "responses", "Python (openai SDK)",
        {
            "en": "OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Calls api.openai.com directly and requires an OpenAI platform key (sk-proj-...).",
            "ko": "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. api.openai.com 직접 호출이며 OpenAI platform 키(sk-proj-…)가 필요합니다.",
        },
        _both(lambda L: _lines(
            "from openai import OpenAI",
            "",
            L("# OpenAI 1P direct — platform key (sk-proj-...), not interchangeable with Mantle bearer",
              "# OpenAI 1P direct — platform 키(sk-proj-…), Mantle bearer와 호환 불가"),
            'client = OpenAI(api_key="<OPENAI_API_KEY>")',
            "",
            *_responses_tail(mid),
        )),
    )]


def code_examples(model_id: str) -> list[dict]:
    """The model's code examples in tab order. Each has api_id, api, label, language, description {ko, en},
    code {ko, en} and code_sha (SHA-256 of the EN code before any placeholder substitution)."""
    channel = _channel(model_id)
    if channel == "bedrock":
        return _bedrock_examples(model_id)
    if channel == "anthropic-cp":
        return _cp_examples(model_id)
    if channel == "openai-mantle":
        return _openai_mantle_examples(model_id)
    return _openai_1p_examples(model_id)
````
- [ ] **Step 3c:** Create a minimal `backend/model_explorer/execute.py` so the placeholder test can import the table (Task 3 replaces this file with the full executor):

```python
"""Run one Model Explorer code example in a child Python (v2.40.0, ADR-035) — placeholder table only until Task 3."""

PLACEHOLDERS: dict[str, str] = {
    '"<ANTHROPIC_API_KEY>"': "ANTHROPIC_API_KEY",
    '"<ANTHROPIC_WORKSPACE_ID>"': "ANTHROPIC_WORKSPACE_ID",
    '"<ABSK-...>"': "OPENAI_API_KEY",
    '"<OPENAI_API_KEY>"': "OPENAI_1P_API_KEY",
}
```
- [ ] **Step 4:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_examples.py -q
```

Expected: `83 passed`.
- [ ] **Step 5:** Commit:

```bash
git add backend/model_explorer/__init__.py \
  backend/model_explorer/examples.py \
  backend/model_explorer/execute.py \
  backend/tests/test_explorer_examples.py
git commit -m "feat(explorer): generate the code examples in the backend, byte-identical to v2.39.0"
```
---

### Task 3: Example executor

**Files:**
- Modify (replace): `backend/model_explorer/execute.py`
- Test: `backend/tests/test_explorer_execute.py`

**Interfaces:**
- Consumes: `code_examples` (Task 2).
- Produces: `execute(code: str, *, env: Mapping[str, str] | None = None, timeout_s: float | None = None, python: str = sys.executable) -> Outcome`; `Outcome(status: "passed"|"failed"|"skipped", latency_ms: float | None, attempts: int, output_excerpt: str | None, error_message: str | None)` (frozen dataclass); `prepare(code, env) -> Prepared(source, skip_reason)`; `child_env(env)`; `mask(text, env)`; constants `PLACEHOLDERS`, `SECRET_ENV`, `EXCERPT_CHARS = 300`, `STDERR_TAIL_CHARS = 1500`, `NO_OUTPUT = "출력 없음"`, `UNKNOWN_PLACEHOLDER = "알 수 없는 플레이스홀더"`; `call_timeout_s()` reads `EXPLORER_CALL_TIMEOUT_S` (default 90). Task 4 uses `Outcome` and `execute`.
- [ ] **Step 1:** Create `backend/tests/test_explorer_execute.py`:

````python
"""model_explorer.execute — real child processes on fake scripts, no provider is reached (v2.40.0, ADR-035)."""

import os
import sys

import pytest

from model_explorer import execute as ex
from model_explorer.examples import code_examples

SECRET = "sk-test-SECRET-0123456789"


def _env(**extra):
    return {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp", **extra}


def test_a_script_that_prints_passes_on_the_first_attempt():
    out = ex.execute('print("Hello!")', env=_env(), timeout_s=30)
    assert (out.status, out.attempts, out.output_excerpt, out.error_message) == ("passed", 1, "Hello!\n", None)
    assert out.latency_ms is not None and out.latency_ms > 0


def test_an_exception_fails_after_one_retry_with_the_exception_line_first():
    out = ex.execute('raise KeyError("text")', env=_env(), timeout_s=30)
    assert (out.status, out.attempts) == ("failed", 2)
    head, _, tail = out.error_message.partition("\n")
    assert head == "KeyError: 'text'"
    assert "Traceback (most recent call last)" in tail and len(tail) <= ex.STDERR_TAIL_CHARS


def test_blank_output_fails_as_no_output():
    out = ex.execute('print("   ")', env=_env(), timeout_s=30)
    assert (out.status, out.error_message, out.attempts) == ("failed", ex.NO_OUTPUT, 2)


def test_a_call_past_the_cap_is_killed_and_fails_as_a_timeout():
    out = ex.execute("import time\ntime.sleep(30)", env=_env(), timeout_s=0.5)
    assert (out.status, out.error_message, out.attempts) == ("failed", "시간 초과 0.5초", 2)


def test_a_flap_that_passes_on_the_retry_passes_with_two_attempts(tmp_path):
    marker = tmp_path / "first"
    code = f"import pathlib\np = pathlib.Path({str(marker)!r})\nif not p.exists():\n    p.write_text('x')\n    raise SystemExit(3)\nprint('ok')"
    out = ex.execute(code, env=_env(), timeout_s=30)
    assert (out.status, out.attempts, out.output_excerpt) == ("passed", 2, "ok\n")


def test_the_key_placeholders_become_environment_reads_and_the_secret_never_enters_the_code():
    code = 'key = "<ABSK-...>"\nprint(len(key))'
    prepared = ex.prepare(code, _env(OPENAI_API_KEY=SECRET))
    assert prepared.source == 'import os\nkey = os.environ["OPENAI_API_KEY"]\nprint(len(key))'
    assert SECRET not in prepared.source
    out = ex.execute(code, env=_env(OPENAI_API_KEY=SECRET), timeout_s=30)
    assert (out.status, out.output_excerpt) == ("passed", f"{len(SECRET)}\n")


@pytest.mark.parametrize("literal, name", sorted(ex.PLACEHOLDERS.items()))
def test_a_missing_key_skips_the_example(literal, name):
    out = ex.execute(f"key = {literal}\nprint(key)", env=_env(), timeout_s=30)
    assert (out.status, out.attempts, out.error_message) == ("skipped", 0, f"자격 증명 미주입: {name}")


def test_an_unknown_placeholder_skips_the_example():
    out = ex.execute('key = "<SOME_NEW_KEY>"\nprint(key)', env=_env(), timeout_s=30)
    assert (out.status, out.error_message) == ("skipped", ex.UNKNOWN_PLACEHOLDER)


def test_the_child_gets_only_the_allow_listed_environment():
    env = _env(DB_PASSWORD="db-secret-value", JWT_SECRET_KEY="jwt-secret-value-0123456789",
               SEED_ADMIN_PASSWORD="admin-secret", AGENTCORE_MEMORY_ID="mem-1", PYTHONPATH="/nowhere",
               AWS_REGION="us-east-1", AWS_CONTAINER_CREDENTIALS_RELATIVE_URI="/v2/credentials/x",
               ANTHROPIC_API_KEY="anthropic-key-0123456789")
    code = "import os\nprint(','.join(sorted(os.environ)))"
    out = ex.execute(code, env=env, timeout_s=30)
    names = set(out.output_excerpt.strip().split(","))
    assert {"AWS_REGION", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "ANTHROPIC_API_KEY", "PATH", "HOME"} <= names
    assert not names & {"DB_PASSWORD", "JWT_SECRET_KEY", "SEED_ADMIN_PASSWORD", "AGENTCORE_MEMORY_ID", "PYTHONPATH"}


def test_secrets_printed_by_the_example_are_masked_in_stdout_and_stderr():
    env = _env(ANTHROPIC_API_KEY=SECRET, AWS_SESSION_TOKEN="session-token-0123456789", OPENAI_1P_API_KEY="short")
    code = ('import os, sys\nprint(os.environ["ANTHROPIC_API_KEY"], os.environ["OPENAI_1P_API_KEY"])\n'
            'sys.stderr.write(os.environ["AWS_SESSION_TOKEN"] + "\\n")\nraise SystemExit(1)')
    out = ex.execute(code, env=env, timeout_s=30)
    assert out.status == "failed"
    assert SECRET not in (out.output_excerpt or "") and "***" in out.output_excerpt
    assert "short" in out.output_excerpt  # values under 8 characters are not masked (they would mask common words)
    assert "session-token-0123456789" not in out.error_message and out.error_message.startswith("***")


def test_the_temporary_directory_is_removed_and_is_the_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(ex.tempfile, "tempdir", str(tmp_path))
    out = ex.execute("import os\nprint(os.getcwd())", env=_env(), timeout_s=30)
    cwd = out.output_excerpt.strip()
    assert cwd.startswith(str(tmp_path)) and os.path.basename(cwd).startswith("explorer-")
    assert not os.path.exists(cwd)


def test_every_placeholder_of_every_example_is_known():
    ids = ["global.anthropic.claude-opus-5", "anthropic:claude-sonnet-5-5", "openai:us-east-1:openai.gpt-6-sol",
           "openai:1p:gpt-5.5", "us.amazon.nova-2-lite-v1:0"]
    env = _env(**{name: "x" * 12 for name in ex.PLACEHOLDERS.values()})
    for model_id in ids:
        for example in code_examples(model_id):
            assert ex.prepare(example["code"]["en"], env).source is not None, (model_id, example["api_id"])


def test_the_default_python_is_the_current_interpreter():
    assert ex.execute.__kwdefaults__["python"] == sys.executable
````
- [ ] **Step 2:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_execute.py -q
```

Expected: failures such as `AttributeError: module 'model_explorer.execute' has no attribute 'execute'`.
- [ ] **Step 3:** Replace `backend/model_explorer/execute.py` with:

````python
"""Run one Model Explorer code example in a child Python (v2.40.0, ADR-035).

The example text is executed as shown, with only its key placeholders replaced by os.environ[...] expressions (the
secret values never enter the code text). Each run gets a fresh temporary directory as its cwd and runs
`<python> -I example.py`: -I drops PYTHON* variables, the user site and the script directory from sys.path. The child
environment is an allow-list (AWS_*, the four provider keys, PATH, HOME, LANG, LC_ALL, TMPDIR), so DB_*,
JWT_SECRET_KEY, SEED_ADMIN_PASSWORD and AGENTCORE_MEMORY_ID of the scheduled task never reach it. Output goes to a
public API, so every secret value of 8 characters or more is masked before it is returned.

Verdict: exit 0 with non-blank stdout = passed; exit 0 with blank stdout = failed "출력 없음" (an InvokeModel reply
that only had a thinking block lands here); any other exit = failed with the last non-blank stderr line and the
stderr tail; past the per-call cap = failed "시간 초과 N초"; a placeholder this module does not know or a provider key
that is not injected = skipped. A failed example runs once more and the second result decides (service flaps).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Mapping

# Example literal -> the environment variable it reads in the child. Every placeholder an example may contain must be
# here (tests pin it), or the example is skipped rather than run with a literal "<...>" key.
PLACEHOLDERS: dict[str, str] = {
    '"<ANTHROPIC_API_KEY>"': "ANTHROPIC_API_KEY",
    '"<ANTHROPIC_WORKSPACE_ID>"': "ANTHROPIC_WORKSPACE_ID",
    '"<ABSK-...>"': "OPENAI_API_KEY",
    '"<OPENAI_API_KEY>"': "OPENAI_1P_API_KEY",
}
SECRET_ENV: tuple[str, ...] = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "OPENAI_1P_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN",
)
_PASS_ENV: frozenset[str] = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "OPENAI_1P_API_KEY",
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
})
_LEFTOVER = re.compile(r'"<[^"\n]*>"')
_MIN_SECRET_LEN = 8
EXCERPT_CHARS = 300
STDERR_TAIL_CHARS = 1500
DEFAULT_CALL_TIMEOUT_S = 90.0

UNKNOWN_PLACEHOLDER = "알 수 없는 플레이스홀더"
NO_OUTPUT = "출력 없음"


def call_timeout_s() -> float:
    """EXPLORER_CALL_TIMEOUT_S (default 90), read at call time."""
    return float(os.getenv("EXPLORER_CALL_TIMEOUT_S", str(DEFAULT_CALL_TIMEOUT_S)))


@dataclass(frozen=True)
class Prepared:
    source: str | None       # the code to run (import os + substituted text), None when skipped
    skip_reason: str | None


@dataclass(frozen=True)
class Outcome:
    status: str               # passed | failed | skipped
    latency_ms: float | None
    attempts: int             # 0 when skipped, else 1 or 2
    output_excerpt: str | None
    error_message: str | None  # failed: first line = the exception line, then the stderr tail; skipped: the reason


def prepare(code: str, env: Mapping[str, str]) -> Prepared:
    """Replace the key placeholders with os.environ[...] and check that every key the example reads is injected."""
    source = code
    needed: list[str] = []
    for literal, name in PLACEHOLDERS.items():
        if literal in source:
            source = source.replace(literal, f'os.environ["{name}"]')
            needed.append(name)
    if _LEFTOVER.search(source):
        return Prepared(None, UNKNOWN_PLACEHOLDER)
    missing = [name for name in needed if not env.get(name)]
    if missing:
        return Prepared(None, f"자격 증명 미주입: {', '.join(missing)}")
    return Prepared("import os\n" + source, None)


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """The allow-listed environment of the child: AWS_* (task role credentials included) and _PASS_ENV."""
    return {k: v for k, v in env.items() if k.startswith("AWS_") or k in _PASS_ENV}


def mask(text: str, env: Mapping[str, str]) -> str:
    for name in SECRET_ENV:
        value = env.get(name)
        if value and len(value) >= _MIN_SECRET_LEN:
            text = text.replace(value, "***")
    return text


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def _run_once(source: str, env: Mapping[str, str], timeout_s: float, python: str) -> tuple[str, float, str | None, str | None]:
    """(status, latency_ms, output_excerpt, error_message) of one child run."""
    workdir = tempfile.mkdtemp(prefix="explorer-")
    try:
        path = os.path.join(workdir, "example.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [python, "-I", path], cwd=workdir, env=child_env(env), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return "failed", (time.monotonic() - started) * 1000.0, None, f"시간 초과 {timeout_s:g}초"
        latency_ms = (time.monotonic() - started) * 1000.0
        stdout, stderr = mask(proc.stdout, env), mask(proc.stderr, env)
        if proc.returncode == 0 and stdout.strip():
            return "passed", latency_ms, stdout[:EXCERPT_CHARS], None
        if proc.returncode == 0:
            return "failed", latency_ms, None, NO_OUTPUT
        head = _last_line(stderr) or f"exit code {proc.returncode}"
        return "failed", latency_ms, stdout[:EXCERPT_CHARS] or None, f"{head}\n{stderr[-STDERR_TAIL_CHARS:]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def execute(code: str, *, env: Mapping[str, str] | None = None, timeout_s: float | None = None,
            python: str = sys.executable) -> Outcome:
    """Run one example; a failed run is retried once and the second result decides."""
    env = dict(os.environ) if env is None else env
    timeout_s = call_timeout_s() if timeout_s is None else timeout_s
    prepared = prepare(code, env)
    if prepared.source is None:
        return Outcome("skipped", None, 0, None, prepared.skip_reason)
    status, latency_ms, excerpt, error = _run_once(prepared.source, env, timeout_s, python)
    attempts = 1
    if status == "failed":
        status, latency_ms, excerpt, error = _run_once(prepared.source, env, timeout_s, python)
        attempts = 2
    return Outcome(status, round(latency_ms, 1), attempts, excerpt, error)
````
- [ ] **Step 4:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_execute.py tests/test_explorer_examples.py -q
```

Expected: `99 passed` (16 + 83) in about 2 s — these start real child processes running fake scripts; nothing reaches a provider.
- [ ] **Step 5:** Commit:

```bash
git add backend/model_explorer/execute.py \
  backend/tests/test_explorer_execute.py
git commit -m "feat(explorer): run one example in an isolated child Python with an allow-listed env"
```
---

### Task 4: Tables, run orchestration, run-to-run diff and the CLI

**Files:**
- Modify: `backend/models.py` (two ORM classes after `FeatureResult`)
- Create: `backend/model_explorer/runner.py`, `backend/model_explorer/diff.py`, `backend/explorer_runner.py`
- Test: `backend/tests/test_explorer_runner.py`

**Interfaces:**
- Consumes: `execute.Outcome`, `execute.execute` (Task 3), `code_examples` (Task 2).
- Produces:
  - `models.ExplorerRun(id, started_at, finished_at, status, totals, error_message)`, `models.ExplorerResult(id, run_id, model_id, model_name, api_id, status, latency_ms, attempts, code_sha, output_excerpt, error_message)`, index `ix_explorer_results_run_id`.
  - `runner.visible_models(models: Mapping[str, str] | None = None) -> dict[str, str]`, `runner.build_jobs(models, model_ids=None) -> list[dict]` (keys `model_id, model_name, api_id, api, code, code_sha`), `runner.run_explorer(model_ids=None, *, session_factory=None, execute_fn=None, models=None, deadline_s=None, now=None) -> int`, `runner.smoke(model_ids=None, *, execute_fn=None, models=None) -> list[dict]`, constants `KEEP_RUNS = 60`, `MAX_WORKERS = 4`, `RUN_DEADLINE_REASON = "런 시간 상한"`; `run_deadline_s()` reads `EXPLORER_RUN_DEADLINE_S` (default 1200).
  - `diff.diff_cells(prev, cur) -> list[dict]` with `{model_id, model_name, api_id, api, before, after, kind}`; `prev`/`cur` map `(model_id, api_id)` → `{"status", "code_sha", "model_name", "api"}`. Task 5 uses it.
  - `explorer_runner.main(argv=None) -> int`, `explorer_runner._finish(exit_code, _exit=os._exit)`.
- [ ] **Step 1:** Create `backend/tests/test_explorer_runner.py`:

````python
"""model_explorer.runner — fake executor + in-memory SQLite, no child process, no provider (v2.40.0, ADR-035)."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from model_explorer import runner
from model_explorer.examples import code_examples
from model_explorer.execute import Outcome
from models import ExplorerResult, ExplorerRun

MODELS = {
    "global.anthropic.claude-opus-5": "Bedrock Claude Opus 5 (Global)",           # 3 examples
    "us.amazon.nova-2-lite-v1:0": "Bedrock Nova 2.0 Lite (US)",                    # 1
    "anthropic:claude-sonnet-5-5": "Anthropic Claude Sonnet 5.5 (US)",             # 1
    "openai:us-east-1:openai.gpt-6-sol": "OpenAI GPT 6 Sol (us-east-1)",           # 1
    "openai:1p:gpt-5.5": "OpenAI GPT 5.5 (1P)",                                    # hidden by default
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": "Bedrock Claude Haiku 4.5 (Global)",  # hidden (v2.39.0)
}
T0 = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)


@pytest.fixture()
def Session(monkeypatch):
    monkeypatch.delenv("HIDDEN_MODEL_PATTERNS", raising=False)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _passing(code):
    return Outcome("passed", 12.5, 1, "Hello!", None)


def _rows(Session, run_id):
    with Session() as db:
        rows = db.query(ExplorerResult).filter(ExplorerResult.run_id == run_id).order_by(ExplorerResult.id).all()
        db.expunge_all()
        return rows


def _run(Session, run_id):
    with Session() as db:
        run = db.get(ExplorerRun, run_id)
        db.expunge(run)
        return run


def test_jobs_are_every_visible_model_times_its_examples():
    jobs = runner.build_jobs(runner.visible_models(MODELS))
    assert [(j["model_id"], j["api_id"]) for j in jobs] == [
        ("global.anthropic.claude-opus-5", "converse"), ("global.anthropic.claude-opus-5", "invoke_model"),
        ("global.anthropic.claude-opus-5", "messages"), ("us.amazon.nova-2-lite-v1:0", "converse"),
        ("anthropic:claude-sonnet-5-5", "messages"), ("openai:us-east-1:openai.gpt-6-sol", "responses"),
    ]
    first = code_examples("global.anthropic.claude-opus-5")[0]
    assert jobs[0]["code"] == first["code"]["en"] and jobs[0]["code_sha"] == first["code_sha"]


def test_the_production_catalog_makes_85_jobs():
    from tests.pricing_catalog import ACTIVE_MODELS

    assert len(runner.build_jobs(runner.visible_models(ACTIVE_MODELS))) == 85


def test_a_run_saves_one_row_per_example_with_totals(Session):
    calls = []

    def fake(code):
        calls.append(code)
        return Outcome("failed", 30.0, 2, None, "KeyError: 'text'\ntail") if "invoke_model" in code else _passing(code)

    run_id = runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS, now=lambda: T0)
    run = _run(Session, run_id)
    assert (run.status, run.totals) == ("completed", {"passed": 5, "failed": 1, "skipped": 0})
    rows = _rows(Session, run_id)
    assert len(rows) == len(calls) == 6
    failed = next(r for r in rows if r.api_id == "invoke_model")
    assert (failed.status, failed.attempts, failed.error_message) == ("failed", 2, "KeyError: 'text'\ntail")
    assert all(r.model_name == MODELS[r.model_id] for r in rows)
    assert {r.code_sha for r in rows} == {
        ex["code_sha"] for mid in list(MODELS)[:4] for ex in code_examples(mid)}


def test_hidden_models_are_not_run(Session):
    run_id = runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    assert {r.model_id for r in _rows(Session, run_id)} == set(list(MODELS)[:4])


def test_the_running_row_is_committed_before_the_first_example(Session, monkeypatch):
    monkeypatch.setattr(runner, "MAX_WORKERS", 1)  # one worker: the shared in-memory SQLite connection is not thread-safe
    seen = []

    def fake(code):
        with Session() as db:
            seen.append([(r.status, r.finished_at) for r in db.query(ExplorerRun).all()])
        return _passing(code)

    runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS)
    assert seen[0] == [("running", None)]


def test_jobs_past_the_run_deadline_are_skipped(Session):
    def slow(code):
        time.sleep(0.05)
        return _passing(code)

    run_id = runner.run_explorer(session_factory=Session, execute_fn=slow, models=MODELS, deadline_s=0.0)
    rows = _rows(Session, run_id)
    assert {r.status for r in rows} == {"skipped"}
    assert {r.error_message for r in rows} == {runner.RUN_DEADLINE_REASON}
    assert _run(Session, run_id).totals == {"passed": 0, "failed": 0, "skipped": 6}


def test_an_executor_exception_is_a_failed_row_not_a_failed_run(Session):
    def boom(code):
        raise RuntimeError("worker died")

    run_id = runner.run_explorer(session_factory=Session, execute_fn=boom, models=MODELS)
    assert _run(Session, run_id).status == "completed"
    assert {r.error_message for r in _rows(Session, run_id)} == {"executor: RuntimeError: worker died"}


def test_an_internal_error_marks_the_run_failed_and_reraises(Session, monkeypatch):
    monkeypatch.setattr(runner, "_totals", lambda results: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    with Session() as db:
        (run,) = db.query(ExplorerRun).all()
        assert (run.status, run.error_message) == ("failed", "db down") and run.finished_at is not None


def test_only_the_latest_60_runs_are_kept(Session):
    with Session() as db:
        for i in range(61):
            db.add(ExplorerRun(status="completed", started_at=T0 - timedelta(days=61 - i)))
        db.commit()
        old_id = db.query(ExplorerRun.id).order_by(ExplorerRun.id).first()[0]
        db.add(ExplorerResult(run_id=old_id, model_id="m", model_name="m", api_id="converse", status="passed",
                              attempts=1, code_sha="x"))
        db.commit()
    runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    with Session() as db:
        assert db.query(ExplorerRun).count() == runner.KEEP_RUNS
        assert db.query(ExplorerRun).filter(ExplorerRun.id == old_id).first() is None
        assert db.query(ExplorerResult).filter(ExplorerResult.run_id == old_id).count() == 0


def test_a_prune_failure_never_overwrites_the_completed_run(Session, monkeypatch):
    monkeypatch.setattr(runner, "_prune", lambda factory: (_ for _ in ()).throw(RuntimeError("prune")))
    run_id = runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    assert _run(Session, run_id).status == "completed"


def test_examples_run_four_at_a_time(Session):
    active, peak, lock = [0], [0], threading.Lock()

    def fake(code):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return _passing(code)

    runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS)
    assert peak[0] == runner.MAX_WORKERS


def test_smoke_runs_without_the_database():
    rows = runner.smoke(execute_fn=_passing, models=MODELS)
    assert [(r["model_id"], r["api_id"], r["status"]) for r in rows][:2] == [
        ("anthropic:claude-sonnet-5-5", "messages", "passed"), ("global.anthropic.claude-opus-5", "converse", "passed")]
    assert len(rows) == 6


# ── CLI (explorer_runner.py) ─────────────────────────────────────────────────

import json  # noqa: E402

import explorer_runner  # noqa: E402


def test_cli_needs_once_or_smoke():
    with pytest.raises(SystemExit):
        explorer_runner.main([])


def test_cli_smoke_prints_json_and_exits_1_on_a_failed_example(monkeypatch, capsys):
    row = {"model_id": "m", "model_name": "M", "api_id": "converse", "status": "failed", "latency_ms": 1.0,
           "attempts": 2, "output_excerpt": None, "error_message": "KeyError: 'x'\ntail"}
    monkeypatch.setattr(explorer_runner, "_register_models", lambda: None)
    monkeypatch.setattr(runner, "smoke", lambda model_ids: [row])
    assert explorer_runner.main(["--smoke", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == [row]


def test_cli_once_registers_models_creates_tables_then_runs(monkeypatch):
    import database

    calls = []
    monkeypatch.setattr(explorer_runner, "_register_models", lambda: calls.append("register"))
    monkeypatch.setattr(database, "create_tables", lambda: calls.append("tables"))
    monkeypatch.setattr(runner, "run_explorer", lambda model_ids: calls.append(("run", model_ids)) or 7)
    assert explorer_runner.main(["--once", "--models", "a,b"]) == 0
    assert calls == ["register", "tables", ("run", ["a", "b"])]


def test_cli_once_exits_1_when_the_run_fails(monkeypatch):
    import database

    monkeypatch.setattr(explorer_runner, "_register_models", lambda: None)
    monkeypatch.setattr(database, "create_tables", lambda: None)
    monkeypatch.setattr(runner, "run_explorer", lambda model_ids: (_ for _ in ()).throw(RuntimeError("x")))
    assert explorer_runner.main(["--once"]) == 1


def test_finish_ends_with_os_exit(monkeypatch):
    codes = []
    monkeypatch.setattr(explorer_runner.logging, "shutdown", lambda: None)
    explorer_runner._finish(3, _exit=codes.append)
    assert codes == [3]
````
- [ ] **Step 2:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_runner.py -q
```

Expected: collection error `ImportError: cannot import name 'runner' from 'model_explorer'`.
- [ ] **Step 3a:** Apply this change to `backend/models.py` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/backend/models.py b/backend/models.py
index bee5a05..c40deb6 100644
--- a/backend/models.py
+++ b/backend/models.py
@@ -215,6 +215,40 @@ class FeatureResult(Base):
     error_message = Column(Text, nullable=True)
 
 
+class ExplorerRun(Base):
+    """Model Explorer 코드 예제 검증 런 1회 (v2.40.0, ADR-035) — ExplorerVerify 태스크가 매일 18:00 UTC에 기록."""
+
+    __tablename__ = "explorer_runs"
+
+    id = Column(Integer, primary_key=True, autoincrement=True)
+    started_at = Column(DateTime(timezone=True), nullable=False)
+    finished_at = Column(DateTime(timezone=True), nullable=True)
+    status = Column(Text, nullable=False)  # running | completed | failed
+    totals = Column(JSON, nullable=True)   # {passed, failed, skipped}
+    error_message = Column(Text, nullable=True)
+
+
+class ExplorerResult(Base):
+    """예제 1건(모델 × API)의 실행 결과 (v2.40.0). code_sha = 실행한 EN 예제 원문(치환 전)의 SHA-256."""
+
+    __tablename__ = "explorer_results"
+    __table_args__ = (
+        Index("ix_explorer_results_run_id", "run_id"),
+    )
+
+    id = Column(Integer, primary_key=True, autoincrement=True)
+    run_id = Column(Integer, ForeignKey("explorer_runs.id"), nullable=False)
+    model_id = Column(Text, nullable=False)
+    model_name = Column(Text, nullable=False)
+    api_id = Column(Text, nullable=False)       # converse | invoke_model | messages | responses
+    status = Column(Text, nullable=False)       # passed | failed | skipped
+    latency_ms = Column(Float, nullable=True)
+    attempts = Column(Integer, nullable=False, default=0)
+    code_sha = Column(Text, nullable=False)
+    output_excerpt = Column(Text, nullable=True)
+    error_message = Column(Text, nullable=True)
+
+
 class GptBenchResult(Base):
     """GPT on AWS 벤치 호출 1건 (v2.18.0) — gptbench.run_cycle()이 15분마다 채널당 10건 기록.
 
````
- [ ] **Step 3b:** Create `backend/model_explorer/runner.py`:

````python
"""Model Explorer verification run (v2.40.0, ADR-035) — every visible model × its code examples, executed for real.

- Jobs = visible prober.AVAILABLE_MODELS (labels without a HIDDEN_MODEL_PATTERNS pattern) × examples.code_examples.
- ThreadPoolExecutor(4) runs execute.execute on the EN code; rows are gathered on the main thread and saved at once
  (no DB session in a worker, parity/runner.py pattern).
- The `running` row is committed before the sweep and no transaction stays open during it (v2.32.2 rule).
- A run deadline (EXPLORER_RUN_DEADLINE_S, 1200 s) records the jobs that had not started as skipped.
- Retention: the latest KEEP_RUNS runs; a prune failure is logged and never turns a completed run into a failed one.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Mapping

from model_explorer import execute as executor
from model_explorer.examples import code_examples

logger = logging.getLogger(__name__)

KEEP_RUNS = 60
MAX_WORKERS = 4
DEFAULT_RUN_DEADLINE_S = 1200.0
RUN_DEADLINE_REASON = "런 시간 상한"
STATUSES = ("passed", "failed", "skipped")


def run_deadline_s() -> float:
    return float(os.getenv("EXPLORER_RUN_DEADLINE_S", str(DEFAULT_RUN_DEADLINE_S)))


def visible_models(models: Mapping[str, str] | None = None) -> dict[str, str]:
    """{model_id: label} of the catalog without the hidden labels (visibility.HIDDEN_MODEL_PATTERNS)."""
    import prober
    from visibility import hidden_patterns

    patterns = hidden_patterns()
    source = prober.AVAILABLE_MODELS if models is None else models
    return {mid: label for mid, label in source.items() if not any(p in label for p in patterns)}


def build_jobs(models: Mapping[str, str], model_ids: list[str] | None = None) -> list[dict]:
    """One job per (model, example) in catalog order; `model_ids` narrows the models (CLI --models)."""
    jobs: list[dict] = []
    for model_id, label in models.items():
        if model_ids is not None and model_id not in model_ids:
            continue
        for example in code_examples(model_id):
            jobs.append({"model_id": model_id, "model_name": label, "api_id": example["api_id"],
                         "api": example["api"], "code": example["code"]["en"], "code_sha": example["code_sha"]})
    return jobs


def _sweep(jobs: list[dict], execute_fn: Callable[[str], executor.Outcome], deadline_s: float,
           clock: Callable[[], float] = time.monotonic) -> list[tuple[dict, executor.Outcome]]:
    started = clock()

    def work(job: dict) -> executor.Outcome:
        if clock() - started > deadline_s:
            return executor.Outcome("skipped", None, 0, None, RUN_DEADLINE_REASON)
        return execute_fn(job["code"])

    done: list[tuple[dict, executor.Outcome]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(work, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 — one broken job never stops the run
                outcome = executor.Outcome("failed", None, 0, None, f"executor: {type(exc).__name__}: {exc}"[:1500])
            done.append((job, outcome))
            if len(done) % 20 == 0:
                logger.info("explorer: %d/%d done", len(done), len(jobs))
    return done


def _totals(results: list[tuple[dict, executor.Outcome]]) -> dict[str, int]:
    totals = dict.fromkeys(STATUSES, 0)
    for _, outcome in results:
        totals[outcome.status] = totals.get(outcome.status, 0) + 1
    return totals


def run_explorer(model_ids: list[str] | None = None, *, session_factory=None,
                 execute_fn: Callable[[str], executor.Outcome] | None = None,
                 models: Mapping[str, str] | None = None, deadline_s: float | None = None,
                 now: Callable[[], datetime] | None = None) -> int:
    """One DB-recorded run; returns explorer_runs.id. Re-raises after marking the run failed."""
    from models import ExplorerResult, ExplorerRun

    if session_factory is None:
        from database import SessionLocal as session_factory
    clock = now or (lambda: datetime.now(timezone.utc))
    execute_fn = execute_fn or executor.execute
    deadline_s = run_deadline_s() if deadline_s is None else deadline_s

    db = session_factory()
    try:
        run = ExplorerRun(status="running", started_at=clock())
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()  # no refresh: the sweep runs with no transaction open
    finally:
        db.close()

    try:
        jobs = build_jobs(visible_models(models), model_ids)
        logger.info("Explorer run %d: %d examples", run_id, len(jobs))
        results = _sweep(jobs, execute_fn, deadline_s)
        totals = _totals(results)
        db = session_factory()
        try:
            db.add_all([
                ExplorerResult(run_id=run_id, model_id=job["model_id"], model_name=job["model_name"],
                               api_id=job["api_id"], status=o.status, latency_ms=o.latency_ms, attempts=o.attempts,
                               code_sha=job["code_sha"], output_excerpt=o.output_excerpt, error_message=o.error_message)
                for job, o in sorted(results, key=lambda r: (r[0]["model_id"], r[0]["api_id"]))
            ])
            run = db.get(ExplorerRun, run_id)
            run.status, run.finished_at, run.totals = "completed", clock(), totals
            db.commit()
        finally:
            db.close()
        logger.info("Explorer run %d completed: %s", run_id, totals)
    except Exception as exc:
        _mark_failed(session_factory, run_id, clock(), exc)
        raise
    try:
        _prune(session_factory)
    except Exception:  # noqa: BLE001 — retention never fails a completed run
        logger.exception("explorer run prune failed (non-fatal)")
    return run_id


def _mark_failed(session_factory, run_id: int, finished_at: datetime, exc: BaseException) -> None:
    from models import ExplorerRun

    db = session_factory()
    try:
        run = db.get(ExplorerRun, run_id)
        if run is not None:
            run.status, run.finished_at, run.error_message = "failed", finished_at, str(exc)[:1500]
            db.commit()
    except Exception:  # noqa: BLE001 — the original error is re-raised by the caller
        db.rollback()
        logger.exception("failed to mark explorer run %d as failed", run_id)
    finally:
        db.close()


def _prune(session_factory) -> None:
    from models import ExplorerResult, ExplorerRun

    db = session_factory()
    try:
        keep = [r.id for r in db.query(ExplorerRun.id).order_by(ExplorerRun.id.desc()).limit(KEEP_RUNS)]
        if not keep:
            return
        old = [r.id for r in db.query(ExplorerRun.id).filter(ExplorerRun.id < min(keep)).all()]
        if old:
            db.query(ExplorerResult).filter(ExplorerResult.run_id.in_(old)).delete(synchronize_session=False)
            db.query(ExplorerRun).filter(ExplorerRun.id.in_(old)).delete(synchronize_session=False)
            db.commit()
            logger.info("pruned %d old explorer runs", len(old))
    finally:
        db.close()


def smoke(model_ids: list[str] | None = None, *, execute_fn: Callable[[str], executor.Outcome] | None = None,
          models: Mapping[str, str] | None = None) -> list[dict]:
    """Run without the DB and return one row per example (local check before a deploy)."""
    jobs = build_jobs(visible_models(models), model_ids)
    results = _sweep(jobs, execute_fn or executor.execute, run_deadline_s())
    return [
        {"model_id": job["model_id"], "model_name": job["model_name"], "api_id": job["api_id"], "status": o.status,
         "latency_ms": o.latency_ms, "attempts": o.attempts, "output_excerpt": o.output_excerpt,
         "error_message": o.error_message}
        for job, o in sorted(results, key=lambda r: (r[0]["model_id"], r[0]["api_id"]))
    ]
````
- [ ] **Step 3c:** Create `backend/model_explorer/diff.py`:

````python
"""Model Explorer run-to-run changes (v2.40.0, ADR-035) — pure functions.

A cell is (model_id, api_id). Against the previous completed run, a cell of the current run is a change when its
status or its code_sha differs:
  catalog  — the previous run had no such cell (a new model or a new API tab)
  example  — the example code changed (code_sha differs), whatever the status — a release that changed an example
             shows whether the new code still passes
  measured — same code, different status
Cells only the previous run had (a model that left monitoring) are ignored, like the Claude API Features and parity
diffs. Output is sorted by (model_id, api_id); the page orders models itself.
"""

from __future__ import annotations

from typing import Mapping

KINDS = ("catalog", "example", "measured")


def diff_cells(prev: Mapping[tuple[str, str], Mapping], cur: Mapping[tuple[str, str], Mapping]) -> list[dict]:
    """prev/cur: {(model_id, api_id): {"status", "code_sha", "model_name", "api"}} -> change items."""
    changes: list[dict] = []
    for key in sorted(cur):
        after = cur[key]
        before = prev.get(key)
        if before is None:
            kind = "catalog"
        elif before["code_sha"] != after["code_sha"]:
            kind = "example"
        elif before["status"] != after["status"]:
            kind = "measured"
        else:
            continue
        model_id, api_id = key
        changes.append({
            "model_id": model_id, "model_name": after["model_name"], "api_id": api_id, "api": after.get("api", api_id),
            "before": None if before is None else before["status"], "after": after["status"], "kind": kind,
        })
    return changes
````
- [ ] **Step 3d:** Create `backend/explorer_runner.py`:

````python
"""Model Explorer verification Fargate one-shot / local smoke entry point (v2.40.0, ADR-035).

ECS CMD:  python -m explorer_runner --once            (ExplorerVerify, daily cron(0 18 * * ? *) UTC = 03:00 KST)
Local:    python -m explorer_runner --smoke [--models id,id] [--json]

Both modes register the runtime channels first (Claude Platform on AWS /v1/models, OpenAI env), like
pricing_sync_runner, so the run covers what the dashboard monitors. --once ends with os._exit like
auto_prober_runner: a stray thread must not keep the task RUNNING.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def _csv(value: str | None) -> list[str] | None:
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


def _register_models() -> None:
    from prober import _discover_anthropic_models, _register_openai_models

    for register in (_discover_anthropic_models, _register_openai_models):
        try:
            register()
        except Exception:  # noqa: BLE001 — a failed registration only leaves those channels out of the run
            logging.exception("explorer_runner: model registration failed (non-fatal)")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run every Model Explorer code example once and exit")
    parser.add_argument("--once", action="store_true", help="DB에 기록하는 실행 1회")
    parser.add_argument("--smoke", action="store_true", help="DB 없이 실행 후 표 출력 (배포 전 로컬 확인)")
    parser.add_argument("--models", help="model id 목록(콤마)")
    parser.add_argument("--json", action="store_true", help="--smoke 결과를 JSON으로 출력")
    args = parser.parse_args(argv)
    if not (args.once or args.smoke):
        parser.error("--once 또는 --smoke 필수")

    _register_models()
    from model_explorer.runner import run_explorer, smoke

    if args.smoke:
        rows = smoke(_csv(args.models))
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                head = (r["error_message"] or r["output_excerpt"] or "").split("\n")[0][:100]
                print(f"{r['status']:8s} {r['attempts']} {(r['latency_ms'] or 0):8.0f}ms  "
                      f"{r['model_id']:52s} {r['api_id']:13s} {head}")
        return 0 if all(r["status"] != "failed" for r in rows) else 1

    from database import create_tables

    create_tables()  # explorer_runs / explorer_results — the task can run before the backend is redeployed
    try:
        run_id = run_explorer(_csv(args.models))
    except Exception:
        logging.exception("explorer_runner 실패")
        return 1
    logging.info("explorer_runner done (run_id=%d)", run_id)
    return 0


def _finish(exit_code: int, _exit=os._exit) -> None:
    """Dispose the DB engine, flush the logs and end with os._exit (auto_prober_runner._finish, v2.28.2)."""
    try:
        from database import engine

        engine.dispose()
    except Exception:  # noqa: BLE001
        logging.exception("explorer_runner: engine dispose failed (ignored)")
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    _exit(exit_code)


if __name__ == "__main__":
    _finish(main())
````
- [ ] **Step 4:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_runner.py -q && for i in 1 2 3; do python3.12 -m pytest tests/test_explorer_runner.py -q | tail -1; done
```

Expected: `17 passed` four times (the repeat guards against thread interleaving; the one test whose fake reads the DB runs with a single worker because the shared in-memory SQLite connection is not thread-safe).
- [ ] **Step 5:** Commit:

```bash
git add backend/models.py \
  backend/model_explorer/runner.py \
  backend/model_explorer/diff.py \
  backend/explorer_runner.py \
  backend/tests/test_explorer_runner.py
git commit -m "feat(explorer): daily verification run, explorer_runs and explorer_results, run-to-run diff and CLI"
```
---

### Task 5: `/api/explorer/latest` and `/api/explorer/trigger`

**Files:**
- Create: `backend/routers/explorer.py`
- Modify: `backend/main.py` (import and `include_router`)
- Test: `backend/tests/test_explorer_router.py`

**Interfaces:**
- Consumes: `diff_cells` (Task 4), `API_NAMES`, `code_examples` (Task 2), `runner.visible_models`, `runner.run_explorer` (Task 4), `visibility.visible_only`.
- Produces: `routers.explorer.router` (prefix `/api/explorer`), `build_latest_payload(db, models, *, now, in_process=False) -> dict`, `db_running(db, now) -> bool`, `RUNNING_WINDOW = timedelta(minutes=30)`, module state `_running = {"active": bool}`. Response shape: see the spec §A6 and `docs/api-reference.md` (Task 11). The frontend types of Task 8 mirror it.
- [ ] **Step 1:** Create `backend/tests/test_explorer_router.py`:

````python
"""routers/explorer.py — /api/explorer/latest and /trigger on in-memory SQLite (v2.40.0, ADR-035)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober
from auth import create_access_token
from database import get_db
from model_explorer import runner
from model_explorer.examples import code_examples
from routers import explorer as explorer_router

OPUS = "global.anthropic.claude-opus-5"
NOVA = "us.amazon.nova-2-lite-v1:0"
CP = "anthropic:claude-sonnet-5-5"
HIDDEN = "openai:1p:gpt-5.5"
MODELS = {OPUS: "Bedrock Claude Opus 5 (Global)", NOVA: "Bedrock Nova 2.0 Lite (US)",
          CP: "Anthropic Claude Sonnet 5.5 (US)", HIDDEN: "OpenAI GPT 5.5 (1P)"}
NOW = datetime.now(timezone.utc)


def _sha(model_id, api_id):
    return next(ex["code_sha"] for ex in code_examples(model_id) if ex["api_id"] == api_id)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.delenv("HIDDEN_MODEL_PATTERNS", raising=False)
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(MODELS))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add(models.User(username="viewer@example.com", password_hash="x", approved=1))
        db.commit()
    app = FastAPI()
    app.include_router(explorer_router.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    explorer_router._running["active"] = False
    with TestClient(app) as client:
        yield factory, client
    engine.dispose()


def _add_run(factory, cells, *, status="completed", started=NOW - timedelta(hours=2), finished=True):
    """cells: [(model_id, api_id, status, code_sha or None for the current one)]"""
    with factory() as db:
        run = models.ExplorerRun(status=status, started_at=started,
                                 finished_at=started + timedelta(minutes=2) if finished else None,
                                 totals={"passed": 1, "failed": 0, "skipped": 0})
        db.add(run)
        db.flush()
        for model_id, api_id, cell_status, sha in cells:
            db.add(models.ExplorerResult(
                run_id=run.id, model_id=model_id, model_name=MODELS[model_id], api_id=api_id, status=cell_status,
                latency_ms=1180.0, attempts=1, code_sha=sha or _sha(model_id, api_id),
                output_excerpt="Hello!" if cell_status == "passed" else None,
                error_message=None if cell_status == "passed" else "KeyError: 'text'\nTraceback"))
        db.commit()
        return run.id


def test_no_run_yet_still_sends_every_visible_models_examples(env):
    _, client = env
    body = client.get("/api/explorer/latest").json()
    assert (body["run"], body["running"], body["previous_run_id"], body["changes"]) == (None, False, None, [])
    assert list(body["models"]) == [OPUS, NOVA, CP]
    opus = body["models"][OPUS]["examples"]
    assert [ex["api_id"] for ex in opus] == ["converse", "invoke_model", "messages"]
    assert opus[0]["code"]["en"] == code_examples(OPUS)[0]["code"]["en"] and opus[0]["result"] is None
    assert set(opus[0]["description"]) == {"ko", "en"}


def test_latest_attaches_the_completed_runs_result_and_cache_header(env):
    factory, client = env
    run_id = _add_run(factory, [(OPUS, "converse", "passed", None), (OPUS, "invoke_model", "failed", None)])
    response = client.get("/api/explorer/latest")
    assert response.headers["cache-control"] == "public, max-age=0, s-maxage=60"
    body = response.json()
    assert body["run"]["id"] == run_id and body["run"]["totals"] == {"passed": 1, "failed": 0, "skipped": 0}
    assert body["run"]["finished_at"].endswith("Z") and body["previous_run_id"] is None and body["changes"] == []
    converse, invoke, messages = body["models"][OPUS]["examples"]
    assert converse["result"] == {"status": "passed", "latency_ms": 1180.0, "attempts": 1, "error_message": None,
                                  "output_excerpt": "Hello!", "run_id": run_id,
                                  "verified_at": body["run"]["finished_at"], "stale_code": False}
    assert invoke["result"]["status"] == "failed" and invoke["result"]["error_message"].startswith("KeyError")
    assert messages["result"] is None


def test_a_result_measured_on_older_code_is_marked_stale(env):
    factory, client = env
    _add_run(factory, [(OPUS, "converse", "passed", "0" * 64)])
    assert client.get("/api/explorer/latest").json()["models"][OPUS]["examples"][0]["result"]["stale_code"] is True


def test_changes_have_three_kinds_and_ignore_cells_only_the_previous_run_had(env):
    factory, client = env
    previous = _add_run(factory, [
        (OPUS, "converse", "passed", None),          # unchanged
        (OPUS, "invoke_model", "passed", None),      # measured: passed -> failed
        (OPUS, "messages", "passed", "0" * 64),      # example: code changed, still passing
        (NOVA, "converse", "passed", None),          # gone from the current run: ignored
    ], started=NOW - timedelta(days=1))
    _add_run(factory, [
        (OPUS, "converse", "passed", None), (OPUS, "invoke_model", "failed", None),
        (OPUS, "messages", "passed", None), (CP, "messages", "passed", None),   # catalog: new cell
    ])
    body = client.get("/api/explorer/latest").json()
    assert body["previous_run_id"] == previous
    assert body["changes"] == [
        {"model_id": CP, "model_name": MODELS[CP], "api_id": "messages", "api": "Messages API",
         "before": None, "after": "passed", "kind": "catalog"},
        {"model_id": OPUS, "model_name": MODELS[OPUS], "api_id": "invoke_model", "api": "InvokeModel API",
         "before": "passed", "after": "failed", "kind": "measured"},
        {"model_id": OPUS, "model_name": MODELS[OPUS], "api_id": "messages", "api": "Messages API",
         "before": "passed", "after": "passed", "kind": "example"},
    ]


def test_failed_and_running_runs_are_not_the_latest(env):
    factory, client = env
    done = _add_run(factory, [(OPUS, "converse", "passed", None)], started=NOW - timedelta(days=1))
    _add_run(factory, [], status="failed", started=NOW - timedelta(hours=3))
    _add_run(factory, [], status="running", started=NOW - timedelta(minutes=5), finished=False)
    body = client.get("/api/explorer/latest").json()
    assert body["run"]["id"] == done and body["running"] is True


def test_a_running_row_older_than_30_minutes_is_not_running(env):
    factory, client = env
    _add_run(factory, [], status="running", started=NOW - timedelta(minutes=31), finished=False)
    assert client.get("/api/explorer/latest").json()["running"] is False


def test_hidden_models_are_left_out_of_models_and_changes(env):
    factory, client = env
    _add_run(factory, [(HIDDEN, "responses", "passed", None)], started=NOW - timedelta(days=1))
    _add_run(factory, [(HIDDEN, "responses", "failed", None)])
    body = client.get("/api/explorer/latest").json()
    assert HIDDEN not in body["models"] and body["changes"] == []


def test_trigger_needs_a_login(env):
    _, client = env
    assert client.post("/api/explorer/trigger").status_code == 401


def test_trigger_starts_one_run_and_refuses_a_second(env, monkeypatch):
    factory, client = env
    started = []
    monkeypatch.setattr(runner, "run_explorer", lambda: started.append(True))
    headers = {"Authorization": f"Bearer {create_access_token('viewer@example.com')}"}
    explorer_router._running["active"] = True
    assert client.post("/api/explorer/trigger", headers=headers).json() == {
        "triggered": False, "message": "이미 실행 중입니다"}
    explorer_router._running["active"] = False
    _add_run(factory, [], status="running", started=NOW - timedelta(minutes=5), finished=False)
    assert client.post("/api/explorer/trigger", headers=headers).json()["triggered"] is False
    with factory() as db:
        db.query(models.ExplorerRun).delete()
        db.commit()
    body = client.post("/api/explorer/trigger", headers=headers).json()
    assert body == {"triggered": True, "message": "모델 탐색 검증 런을 시작했습니다 (약 2분 소요)"}
    for _ in range(100):
        if started and not explorer_router._running["active"]:
            break
        import time
        time.sleep(0.01)
    assert started == [True] and explorer_router._running["active"] is False
````
- [ ] **Step 2:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_router.py -q
```

Expected: collection error `ImportError: cannot import name 'explorer' from 'routers'`.
- [ ] **Step 3a:** Create `backend/routers/explorer.py`:

````python
"""Model Explorer verification API (v2.40.0, ADR-035).

- GET  /api/explorer/latest  — every visible model's code examples (KO and EN) with the latest completed run's result
                               per example, the run-to-run changes and whether a run is in progress (s-maxage=60)
- POST /api/explorer/trigger — manual run in a backend daemon thread (JWT)

The examples come from model_explorer.examples at request time, so a release that changes an example shows the new
code at once; `stale_code` marks a result that was measured on an older version of that code. "Running" is read from
the DB (a `running` row started less than 30 minutes ago): the scheduled run is a separate Fargate task the backend
process cannot see, like /api/auto-probe/status.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Mapping

from fastapi import APIRouter, Depends, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from model_explorer.diff import diff_cells
from model_explorer.examples import API_NAMES, code_examples
from model_explorer.runner import visible_models
from models import ExplorerResult, ExplorerRun, User
from visibility import visible_only

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/explorer", tags=["explorer"])

RUNNING_WINDOW = timedelta(minutes=30)
_run_lock = threading.Lock()
_running = {"active": False}

_RESULT_COLUMNS = (ExplorerResult.model_id, ExplorerResult.model_name, ExplorerResult.api_id, ExplorerResult.status,
                   ExplorerResult.latency_ms, ExplorerResult.attempts, ExplorerResult.code_sha,
                   ExplorerResult.output_excerpt, ExplorerResult.error_message)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def db_running(db: Session, now: datetime) -> bool:
    return (db.query(ExplorerRun.id)
            .filter(ExplorerRun.status == "running", ExplorerRun.started_at >= now - RUNNING_WINDOW)
            .first()) is not None


def _cells(rows) -> dict[tuple[str, str], dict]:
    return {(r.model_id, r.api_id): {"status": r.status, "code_sha": r.code_sha, "model_name": r.model_name,
                                    "api": API_NAMES.get(r.api_id, r.api_id)} for r in rows}


def build_latest_payload(db: Session, models: Mapping[str, str], *, now: datetime, in_process: bool = False) -> dict:
    running = in_process or db_running(db, now)
    run = (db.query(ExplorerRun).filter(ExplorerRun.status == "completed")
           .order_by(desc(ExplorerRun.id)).first())
    rows = []
    prev_run = None
    changes: list[dict] = []
    if run is not None:
        rows = visible_only(db.query(*_RESULT_COLUMNS).filter(ExplorerResult.run_id == run.id),
                            ExplorerResult.model_name).all()
        prev_run = (db.query(ExplorerRun).filter(ExplorerRun.status == "completed", ExplorerRun.id < run.id)
                    .order_by(desc(ExplorerRun.id)).first())
        if prev_run is not None:
            prev_rows = visible_only(db.query(*_RESULT_COLUMNS).filter(ExplorerResult.run_id == prev_run.id),
                                     ExplorerResult.model_name).all()
            changes = diff_cells(_cells(prev_rows), _cells(rows))
    by_cell = {(r.model_id, r.api_id): r for r in rows}

    def result(model_id: str, example: dict) -> dict | None:
        r = by_cell.get((model_id, example["api_id"]))
        if r is None:
            return None
        return {"status": r.status, "latency_ms": r.latency_ms, "attempts": r.attempts,
                "error_message": r.error_message, "output_excerpt": r.output_excerpt, "run_id": run.id,
                "verified_at": _iso(run.finished_at), "stale_code": r.code_sha != example["code_sha"]}

    return {
        "run": None if run is None else {"id": run.id, "started_at": _iso(run.started_at),
                                         "finished_at": _iso(run.finished_at), "totals": run.totals},
        "running": running,
        "previous_run_id": None if prev_run is None else prev_run.id,
        "changes": changes,
        "models": {mid: {"examples": [{**ex, "result": result(mid, ex)} for ex in code_examples(mid)]}
                   for mid in models},
    }


@router.get("/latest")
def get_latest(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=0, s-maxage=60"
    return build_latest_payload(db, visible_models(), now=datetime.now(timezone.utc), in_process=_running["active"])


@router.post("/trigger")
def trigger(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    with _run_lock:
        if _running["active"] or db_running(db, datetime.now(timezone.utc)):
            return {"triggered": False, "message": "이미 실행 중입니다"}
        _running["active"] = True
    db.close()  # the run opens its own sessions; nothing here holds a transaction while it runs

    def _worker():
        try:
            from model_explorer.runner import run_explorer
            run_explorer()
        except Exception:
            logger.exception("Explorer run failed")
        finally:
            _running["active"] = False

    threading.Thread(target=_worker, daemon=True, name="explorer-run").start()
    return {"triggered": True, "message": "모델 탐색 검증 런을 시작했습니다 (약 2분 소요)"}
````
- [ ] **Step 3b:** Register the router in `backend/main.py` (the version bump in the same file is Task 12):

````diff
diff --git a/backend/main.py b/backend/main.py
index 6302c34..f325db2 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -28,6 +28,7 @@ from routers import analysis as analysis_router
 from routers import parity as parity_router
 from routers import gptbench as gptbench_router
 from routers import features as features_router
+from routers import explorer as explorer_router
 from routers import pricing as pricing_router
 from routers import presence as presence_router
 
@@ -350,6 +351,7 @@ app.include_router(analysis_router.router)
 app.include_router(parity_router.router)
 app.include_router(gptbench_router.router)
 app.include_router(features_router.router)
+app.include_router(explorer_router.router)
 app.include_router(pricing_router.router)
 app.include_router(pricing_router.admin_router)
 app.include_router(presence_router.router)
````
- [ ] **Step 4:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_explorer_router.py tests/test_explorer_runner.py tests/test_explorer_execute.py tests/test_explorer_examples.py -q
```

Expected: `125 passed` (9 + 17 + 16 + 83).
- [ ] **Step 5:** Commit:

```bash
git add backend/routers/explorer.py \
  backend/main.py \
  backend/tests/test_explorer_router.py
git commit -m "feat(explorer): public latest results with run-to-run changes, authenticated manual trigger"
```
---

### Task 6: Price sync run snapshots and `/api/pricing` `changes`

**Files:**
- Create: `backend/pricing_changes.py`
- Modify: `backend/pricing_sync.py` (import, snapshot inside `run_sync`), `backend/routers/pricing.py` (`changes` in the payload, exports without it)
- Test: `backend/tests/test_pricing_changes.py` (new), `backend/tests/test_pricing_sync.py`, `backend/tests/test_pricing_router.py` (additions and two updated assertions)

**Interfaces:**
- Consumes: `price_history.current_rows`, `pending_rows`, `pricing_payload.iso_z`, `price_number_or_none`, `pricing_sources.FAMILY_ORDER`, `PROVIDER_ORDER`, `tier_of`, `region_of`, `pricing_parsers.PRICE_FIELDS`.
- Produces: `build_snapshot(db, active, channels, at) -> {"version": 1, "channels": {model_id: {family_key, family, provider, tier, region, shown, pending, result}}}`; `compare_snapshots(before, after) -> list[item]` with item `{model_id, family_key, family, provider, tier, region, kind: "channel"|"price"|"pending"|"check", field, before, after}`; `select_runs(runs_newest_first) -> (latest, previous)`; `changes_block(latest, previous) -> dict`; `latest_changes(db) -> dict` (`{"available": false, "run_id"}` or `{"available": true, run_id, finished_at, previous_run_id, previous_finished_at, items}`). Task 8's `PricingChangeItem`/`PricingChanges` types mirror these.

`SessionLocal` has `autoflush=False`, so `run_sync` must `db.flush()` before the snapshot queries can see the rows `_apply` added.
- [ ] **Step 1a:** Create `backend/tests/test_pricing_changes.py`:

````python
"""pricing_changes — run-to-run unit price changes from the run snapshots (v2.40.0, ADR-035). Pure, no DB."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pricing_changes import changes_block, compare_snapshots, select_runs
from pricing_parsers import PRICE_FIELDS

T = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)
SONNET_G = "global.anthropic.claude-sonnet-5-5"
SONNET_CP = "anthropic:claude-sonnet-5-5"
SOL_US = "openai:us:us.openai.gpt-6-sol"
NOVA = "us.amazon.nova-2-lite-v1:0"
TERRA_E1 = "openai:us-east-1:openai.gpt-5.6-terra"


def _shown(i, o, **extra):
    return {**dict.fromkeys(PRICE_FIELDS), "input": i, "output": o, **extra}


def _ch(family_key, family, provider, tier, shown, pending=None, result="unchanged", region=None):
    return {"family_key": family_key, "family": family, "provider": provider, "tier": tier, "region": region,
            "shown": shown, "pending": pending, "result": result}



BASE = {
    SONNET_G: _ch("claude-sonnet-5-5", "Claude Sonnet 5.5", "anthropic", "global", _shown(2, 10, cache_read=0.2)),
    SONNET_CP: _ch("claude-sonnet-5-5", "Claude Sonnet 5.5", "anthropic", "cp", _shown(2, 10, cache_read=0.2)),
    SOL_US: _ch("gpt-6-sol", "GPT 6 Sol", "openai", "us", _shown(2.2, 11)),
    NOVA: _ch("nova-2-lite", "Nova 2.0 Lite", "amazon", "us", _shown(0.33, 2.75)),
}


def _with(**changes):
    out = {mid: dict(ch) for mid, ch in BASE.items()}
    for mid, ch in changes.items():
        out[mid] = ch
    return {"version": 1, "channels": out}


def test_identical_snapshots_have_no_change():
    assert compare_snapshots(_with(), _with()) == []


def test_a_shown_field_change_is_a_price_item():
    after = _with(**{SONNET_G: {**BASE[SONNET_G], "shown": _shown(2, 10, cache_read=0.1)}})
    assert compare_snapshots(_with(), after) == [{
        "model_id": SONNET_G, "family_key": "claude-sonnet-5-5", "family": "Claude Sonnet 5.5", "provider": "anthropic",
        "tier": "global", "region": None, "kind": "price", "field": "cache_read", "before": 0.2, "after": 0.1}]


def test_a_first_time_value_has_a_null_before():
    after = _with(**{NOVA: {**BASE[NOVA], "shown": _shown(0.33, 2.75, cache_read=0.0825)}})
    (item,) = compare_snapshots(_with(), after)
    assert (item["kind"], item["field"], item["before"], item["after"]) == ("price", "cache_read", None, 0.0825)


def test_a_pending_value_starts_and_clears():
    started = _with(**{SOL_US: {**BASE[SOL_US], "pending": {"input": 3.3}, "result": "pending"}})
    (item,) = compare_snapshots(_with(), started)
    assert (item["kind"], item["field"], item["before"], item["after"]) == ("pending", "input", None, 3.3)
    approved = _with(**{SOL_US: {**BASE[SOL_US], "shown": _shown(3.3, 11)}})
    assert [(i["kind"], i["field"], i["before"], i["after"]) for i in compare_snapshots(started, approved)] == [
        ("price", "input", 2.2, 3.3), ("pending", "input", 3.3, None)]


def test_a_skipped_check_and_its_recovery():
    failed = _with(**{SONNET_CP: {**BASE[SONNET_CP], "result": "skipped:parse_failed"}})
    (item,) = compare_snapshots(_with(), failed)
    assert (item["kind"], item["before"], item["after"]) == ("check", "ok", "skipped:parse_failed")
    (back,) = compare_snapshots(failed, _with())
    assert (back["kind"], back["before"], back["after"]) == ("check", "skipped:parse_failed", "ok")


def test_changed_enriched_and_pending_results_are_all_ok_checks():
    for result in ("changed", "enriched", "pending", "no_baseline", "rejected"):
        assert compare_snapshots(_with(), _with(**{NOVA: {**BASE[NOVA], "result": result}})) == []


def test_a_new_and_a_left_channel_give_one_channel_item_each():
    after = _with()
    del after["channels"][NOVA]
    after["channels"][TERRA_E1] = _ch("gpt-5.6-terra", "GPT 5.6 Terra", "openai", "in_region", _shown(2.2, 13.2),
                                      region="us-east-1")
    items = compare_snapshots(_with(), after)
    assert [(i["model_id"], i["kind"], i["field"], i["before"], i["after"], i["region"]) for i in items] == [
        (TERRA_E1, "channel", None, None, "present", "us-east-1"),
        (NOVA, "channel", None, "present", None, None),
    ]


def test_items_follow_provider_family_tier_kind_and_field_order():
    after = _with(**{
        NOVA: {**BASE[NOVA], "shown": _shown(0.4, 2.75)},
        SOL_US: {**BASE[SOL_US], "shown": _shown(2.2, 12), "pending": {"input": 3.3}},
        SONNET_G: {**BASE[SONNET_G], "shown": _shown(2, 11, cache_read=0.1)},
        SONNET_CP: {**BASE[SONNET_CP], "result": "skipped:not_found"},
    })
    assert [(i["model_id"], i["kind"], i["field"]) for i in compare_snapshots(_with(), after)] == [
        (SONNET_CP, "check", None),               # anthropic, Sonnet 5.5, cp before global
        (SONNET_G, "price", "output"), (SONNET_G, "price", "cache_read"),
        (SOL_US, "price", "output"), (SOL_US, "pending", "input"),   # openai
        (NOVA, "price", "input"),                 # amazon last
    ]


def _run(id_, status="completed", snapshot=True, minutes=0):
    summary = {"snapshot": _with()} if snapshot else {"sources": {}}
    return SimpleNamespace(id=id_, status=status, finished_at=T - timedelta(minutes=minutes), summary=summary)


def test_select_runs_skips_failed_runs_and_needs_a_snapshot_on_the_latest():
    runs = [_run(9, "failed", snapshot=False), _run(8, snapshot=False, minutes=1), _run(7, "partial", minutes=2),
            _run(6, "failed", minutes=3), _run(5, minutes=4)]
    latest, previous = select_runs(runs)
    assert (latest.id, previous.id) == (7, 5)


def test_no_comparison_until_the_previous_run_has_a_snapshot():
    assert changes_block(*select_runs([_run(3), _run(2, snapshot=False)])) == {"available": False, "run_id": 3}
    assert changes_block(*select_runs([_run(3)])) == {"available": False, "run_id": 3}
    assert changes_block(*select_runs([])) == {"available": False, "run_id": None}


def test_changes_block_names_both_runs():
    block = changes_block(*select_runs([_run(4), _run(3, minutes=720)]))
    assert block == {"available": True, "run_id": 4, "finished_at": "2026-11-05T03:00:00Z", "previous_run_id": 3,
                     "previous_finished_at": "2026-11-04T15:00:00Z", "items": []}
````
- [ ] **Step 1b:** Apply this change to `backend/tests/test_pricing_sync.py`, `backend/tests/test_pricing_router.py` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact). Two existing assertions change on purpose: the run summary gains the `snapshot` key, and the JSON export equals the page payload without `changes`.

````diff
diff --git a/backend/tests/test_pricing_router.py b/backend/tests/test_pricing_router.py
index 19b5de3..39035aa 100644
--- a/backend/tests/test_pricing_router.py
+++ b/backend/tests/test_pricing_router.py
@@ -320,8 +320,10 @@ def test_export_headers_and_bodies(env, fmt, content_type, ext):
     elif fmt == "md":
         assert text.startswith("> " + DISCLAIMER["en"] + "\n")
         assert text.rstrip("\n").endswith("> " + DISCLAIMER["en"])
-    else:
-        assert res.json() == client.get("/api/pricing").json()
+    else:  # the JSON export is the page payload without the v2.40.0 run-to-run `changes`
+        page = client.get("/api/pricing").json()
+        assert "changes" in page and "changes" not in res.json()
+        assert res.json() == {key: value for key, value in page.items() if key != "changes"}
 
 
 def test_export_lang_defaults_to_korean(env):
@@ -351,3 +353,32 @@ def test_hidden_model_patterns_drop_classifiable_channels(env, monkeypatch):
     body = client.get("/api/pricing").json()
     assert "openai:us-east-2:openai.gpt-5.5" not in body["models"]
     assert "openai:us-east-1:openai.gpt-5.5" in body["models"]
+
+
+def test_pricing_changes_wait_for_two_snapshot_runs_then_list_the_items(env):
+    """v2.40.0 (ADR-035): `changes` compares the two latest completed/partial runs that carry a snapshot."""
+    factory, client, now = env
+    assert client.get("/api/pricing").json()["changes"] == {"available": False, "run_id": None}
+
+    def snapshot(cache_read):
+        shown = {"input": 4.4, "output": 22, "cache_read": cache_read, "cache_write": 5.5, "cache_write_1h": 8.8,
+                 "long_input": None, "long_output": None, "long_cache_read": None, "long_cache_write": None}
+        return {"version": 1, "channels": {"us.anthropic.claude-opus-5-5": {
+            "family_key": "claude-opus-5-5", "family": "Claude Opus 5.5", "provider": "anthropic", "tier": "us",
+            "region": None, "shown": shown, "pending": None, "result": "unchanged"}}}
+
+    with factory() as db:
+        first = models.PriceSyncRun(started_at=now - timedelta(minutes=50), finished_at=now - timedelta(minutes=49),
+                                    status="completed", summary={"snapshot": snapshot(0.44)})
+        second = models.PriceSyncRun(started_at=now - timedelta(minutes=30), finished_at=now - timedelta(minutes=29),
+                                     status="partial", summary={"snapshot": snapshot(0.22)})
+        db.add_all([first, second])
+        db.commit()
+        first_id, second_id = first.id, second.id
+    pricing_router.invalidate_cache()
+    changes = client.get("/api/pricing").json()["changes"]
+    assert (changes["available"], changes["run_id"], changes["previous_run_id"]) == (True, second_id, first_id)
+    assert changes["items"] == [{
+        "model_id": "us.anthropic.claude-opus-5-5", "family_key": "claude-opus-5-5", "family": "Claude Opus 5.5",
+        "provider": "anthropic", "tier": "us", "region": None, "kind": "price", "field": "cache_read",
+        "before": 0.44, "after": 0.22}]
diff --git a/backend/tests/test_pricing_sync.py b/backend/tests/test_pricing_sync.py
index 72848e9..4d2adf6 100644
--- a/backend/tests/test_pricing_sync.py
+++ b/backend/tests/test_pricing_sync.py
@@ -444,7 +444,7 @@ def test_the_run_row_is_committed_as_running_before_the_first_fetch(Session):
     run = _sync(Session, on_call=inspect)
     assert seen == [[("running", None, T0)]]
     assert run.status == "completed" and run.finished_at is not None
-    assert set(run.summary) == {"sources", "channels", "errors"} and sorted(run.summary["channels"]) == sorted(ALL)
+    assert set(run.summary) == {"sources", "channels", "errors", "snapshot"} and sorted(run.summary["channels"]) == sorted(ALL)
 
 
 def test_an_internal_error_marks_the_run_failed_and_reraises(Session, monkeypatch):
@@ -876,3 +876,75 @@ def test_seoul_in_region_shares_one_offer_call_with_the_cris_channels(Session):
     assert calls.count("offers:anthropic.claude-opus-5") == 1
     assert run.summary["channels"] == {m: "unchanged" for m in sorted(opus)}
     assert run.summary["sources"]["offers"] == {"calls": 1, "ok": 1, "failed": 0}
+
+
+# ── v2.40.0 run snapshot: what /pricing shows when the run ends (pricing_changes.build_snapshot, ADR-035) ──
+
+from price_history import current_rows  # noqa: E402
+from pricing_changes import latest_changes  # noqa: E402
+from pricing_payload import price_number_or_none  # noqa: E402
+
+
+def test_the_run_snapshot_is_what_the_page_shows_when_the_run_ends(Session):
+    _seed(Session)
+    run = _sync(Session, sol=("5.5", "33", "5", "30"))  # both Sol channels change within 50 %
+    snapshot = run.summary["snapshot"]
+    assert snapshot["version"] == 1 and sorted(snapshot["channels"]) == sorted(ALL)
+    with Session() as db:
+        current = current_rows(db, ALL, now=run.finished_at)
+    for model_id in ALL:
+        channel = snapshot["channels"][model_id]
+        assert channel["shown"] == {f: price_number_or_none(getattr(current[model_id], f"{f}_per_mtok"))
+                                    for f in PRICE_FIELDS}
+        assert channel["result"] == run.summary["channels"][model_id]
+    sol = snapshot["channels"][SOL_E1]
+    assert (sol["shown"]["input"], sol["shown"]["output"], sol["pending"]) == (5.5, 33, None)
+    assert (sol["family_key"], sol["family"], sol["provider"], sol["tier"], sol["region"]) == (
+        "gpt-5.6-sol", "GPT 5.6 Sol", "openai", "in_region", "us-east-1")
+    assert (snapshot["channels"][OPUS_G]["tier"], snapshot["channels"][OPUS_G]["region"]) == ("global", None)
+
+
+def test_a_pending_snapshot_field_is_only_what_differs_from_the_shown_value(Session):
+    _seed(Session)
+    run = _sync(Session, sol=("5.5", "33.01", "4", "20"))
+    sol = run.summary["snapshot"]["channels"][SOL_E1]
+    assert (sol["shown"]["input"], sol["pending"], sol["result"]) == (4.4, {"input": 5.5, "output": 33.01}, "pending")
+    assert run.summary["snapshot"]["channels"][SOL_G]["pending"] is None
+
+
+def test_a_no_baseline_channel_shows_nothing_and_pends_every_set_field(Session):
+    _seed(Session, {k: v for k, v in BASELINE.items() if k != SOL_E1})
+    sol = _sync(Session).summary["snapshot"]["channels"][SOL_E1]
+    assert (sol["shown"], sol["pending"], sol["result"]) == (None, {"input": 4.4, "output": 22}, "no_baseline")
+
+
+def test_two_unchanged_runs_compare_with_no_change(Session):
+    _seed(Session)
+    _sync(Session, at=T0)
+    _sync(Session, at=T1)
+    with Session() as db:
+        block = latest_changes(db)
+    assert block["available"] is True and block["items"] == []
+
+
+def test_a_change_between_two_runs_is_one_price_item_per_field(Session):
+    _seed(Session)
+    first = _sync(Session, at=T0)
+    second = _sync(Session, at=T1, sol=("5.5", "33", "5", "30"))
+    with Session() as db:
+        block = latest_changes(db)
+    assert (block["run_id"], block["previous_run_id"]) == (second.id, first.id)
+    assert [(i["model_id"], i["kind"], i["field"], i["before"], i["after"]) for i in block["items"]] == [
+        (SOL_G, "price", "input", 4, 5), (SOL_G, "price", "output", 20, 30),
+        (SOL_E1, "price", "input", 4.4, 5.5), (SOL_E1, "price", "output", 22, 33),
+    ]
+
+
+def test_a_failed_run_has_no_snapshot(Session, monkeypatch):
+    _seed(Session)
+    monkeypatch.setattr(pricing_sync, "_apply", lambda *_a: (_ for _ in ()).throw(RuntimeError("db")))
+    with pytest.raises(RuntimeError):
+        run_sync(Session, _active(*ALL), _fetchers(), now=lambda: T0)
+    with Session() as db:
+        (run,) = db.query(PriceSyncRun).all()
+        assert run.status == "failed" and "snapshot" not in run.summary
````
- [ ] **Step 2:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_pricing_changes.py tests/test_pricing_sync.py tests/test_pricing_router.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'pricing_changes'`.
- [ ] **Step 3a:** Create `backend/pricing_changes.py`:

````python
"""Unit price run-to-run changes (v2.40.0, ADR-035).

Every price sync run stores what /pricing showed when it finished (`price_sync_runs.summary["snapshot"]`, built by
`build_snapshot` inside the run's transaction). The page compares the latest run that has a snapshot with the run
before it:
  channel — a channel only one side has: before null -> after "present" (new) or the reverse (left)
  price   — a shown field differs (a sync change, an admin approval or a first-time value — before null)
  pending — a pending field differs (null -> value: review started; value -> null: approved or rejected)
  check   — the check category differs: "ok" or the `skipped:<reason>` result of the run
A new or left channel gives only its channel item. Admin approvals and rejections between the two runs land in the
later snapshot, so the page says "table values changed since sync #N" without telling which path changed them.
Stored values are price_number values (6 decimals), so they compare as they are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from models import PriceSyncRun
from price_history import current_rows, pending_rows
from pricing_parsers import PRICE_FIELDS
from pricing_payload import iso_z, price_number_or_none
from pricing_sources import FAMILY_ORDER, PROVIDER_ORDER, PriceIdentity, region_of, tier_of

SNAPSHOT_VERSION = 1
TIER_ORDER = ("cp", "openai_list", "global", "us", "in_region")
KIND_ORDER = ("channel", "price", "pending", "check")
_COMPARED_STATUSES = ("completed", "partial")
_RECENT_RUNS = 20  # runs read to find the two latest comparable ones (failed runs in between are skipped)


def _fields(row) -> Optional[dict]:
    if row is None:
        return None
    return {f: price_number_or_none(getattr(row, f"{f}_per_mtok")) for f in PRICE_FIELDS}


def _pending_diff(shown: Optional[dict], held: Optional[dict]) -> Optional[dict]:
    """The pending fields that differ from what is shown; every set field when nothing is shown (no_baseline)."""
    if held is None:
        return None
    if shown is None:
        diff = {f: v for f, v in held.items() if v is not None}
    else:
        diff = {f: v for f, v in held.items() if v != shown[f]}
    return diff or None


def build_snapshot(db: Session, active: Mapping[str, PriceIdentity], channels: Mapping[str, str],
                   at: datetime) -> dict:
    """What /pricing shows for every active channel at `at` (call after db.flush(), before the commit)."""
    ids = sorted(active)
    current = current_rows(db, ids, now=at)
    pending = pending_rows(db, ids)
    out: dict[str, dict] = {}
    for mid in ids:
        ident = active[mid]
        shown = _fields(current.get(mid))
        out[mid] = {
            "family_key": ident.family_key, "family": ident.family, "provider": ident.provider,
            "tier": tier_of(ident.channel), "region": region_of(ident.channel),
            "shown": shown, "pending": _pending_diff(shown, _fields(pending.get(mid))),
            "result": channels.get(mid),
        }
    return {"version": SNAPSHOT_VERSION, "channels": out}


def _check(result: Optional[str]) -> str:
    return result if isinstance(result, str) and result.startswith("skipped:") else "ok"


def _meta(model_id: str, ch: Mapping) -> dict:
    return {"model_id": model_id, "family_key": ch["family_key"], "family": ch["family"],
            "provider": ch["provider"], "tier": ch["tier"], "region": ch.get("region")}


def _rank(item: Mapping) -> tuple:
    provider = PROVIDER_ORDER.index(item["provider"]) if item["provider"] in PROVIDER_ORDER else len(PROVIDER_ORDER)
    family = FAMILY_ORDER.index(item["family"]) if item["family"] in FAMILY_ORDER else len(FAMILY_ORDER)
    tier = TIER_ORDER.index(item["tier"]) if item["tier"] in TIER_ORDER else len(TIER_ORDER)
    field = PRICE_FIELDS.index(item["field"]) if item.get("field") in PRICE_FIELDS else -1
    return (provider, family, item["family_key"], tier, item["region"] or "", item["model_id"],
            KIND_ORDER.index(item["kind"]), field)


def compare_snapshots(before: Mapping, after: Mapping) -> list[dict]:
    """Change items between two snapshots, in table order (provider, family, tier, kind, field)."""
    prev, cur = before["channels"], after["channels"]
    items: list[dict] = []
    for mid in set(prev) | set(cur):
        if mid not in prev or mid not in cur:
            ch = cur.get(mid) or prev[mid]
            items.append({**_meta(mid, ch), "kind": "channel", "field": None,
                          "before": None if mid not in prev else "present",
                          "after": None if mid not in cur else "present"})
            continue
        a, b = prev[mid], cur[mid]
        meta = _meta(mid, b)
        shown_a, shown_b = a["shown"] or {}, b["shown"] or {}
        pend_a, pend_b = a["pending"] or {}, b["pending"] or {}
        for field in PRICE_FIELDS:
            if shown_a.get(field) != shown_b.get(field):
                items.append({**meta, "kind": "price", "field": field,
                              "before": shown_a.get(field), "after": shown_b.get(field)})
        for field in PRICE_FIELDS:
            if pend_a.get(field) != pend_b.get(field):
                items.append({**meta, "kind": "pending", "field": field,
                              "before": pend_a.get(field), "after": pend_b.get(field)})
        if _check(a["result"]) != _check(b["result"]):
            items.append({**meta, "kind": "check", "field": None,
                          "before": _check(a["result"]), "after": _check(b["result"])})
    return sorted(items, key=_rank)


def _snapshot_of(run: PriceSyncRun) -> Optional[dict]:
    summary = run.summary if isinstance(run.summary, dict) else {}
    snapshot = summary.get("snapshot")
    return snapshot if isinstance(snapshot, dict) and isinstance(snapshot.get("channels"), dict) else None


def select_runs(runs: Iterable[PriceSyncRun]) -> tuple[Optional[PriceSyncRun], Optional[PriceSyncRun]]:
    """(R, P): R = the latest finished completed/partial run with a snapshot, P = the completed/partial run before it.

    `runs` are newest first. Failed runs are skipped on both sides.
    """
    comparable = [r for r in runs if r.finished_at is not None and r.status in _COMPARED_STATUSES]
    for i, run in enumerate(comparable):
        if _snapshot_of(run) is not None:
            return run, comparable[i + 1] if i + 1 < len(comparable) else None
    return None, None


def changes_block(latest: Optional[PriceSyncRun], previous: Optional[PriceSyncRun]) -> dict:
    """The /api/pricing `changes` block for the two selected runs."""
    if latest is None or previous is None or _snapshot_of(previous) is None:
        return {"available": False, "run_id": None if latest is None else latest.id}
    return {
        "available": True,
        "run_id": latest.id, "finished_at": iso_z(latest.finished_at),
        "previous_run_id": previous.id, "previous_finished_at": iso_z(previous.finished_at),
        "items": compare_snapshots(_snapshot_of(previous), _snapshot_of(latest)),
    }


def latest_changes(db: Session) -> dict:
    runs = (db.query(PriceSyncRun)
            .filter(PriceSyncRun.finished_at.isnot(None))
            .order_by(PriceSyncRun.finished_at.desc(), PriceSyncRun.id.desc())
            .limit(_RECENT_RUNS)
            .all())
    return changes_block(*select_runs(runs))
````
- [ ] **Step 3b:** Apply this change to `backend/pricing_sync.py`, `backend/routers/pricing.py` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/backend/pricing_sync.py b/backend/pricing_sync.py
index ea86002..d6884e9 100644
--- a/backend/pricing_sync.py
+++ b/backend/pricing_sync.py
@@ -39,6 +39,7 @@ from pricing_parsers import (
     select_offer_price,
     single_public_offer,
 )
+from pricing_changes import build_snapshot
 from pricing_sources import (
     ANTHROPIC_PRICING_URL,
     ANTHROPIC_SOURCE_ID,
@@ -584,10 +585,14 @@ def run_sync(
                 elif result in ("pending", "no_baseline"):
                     pending += 1
             status = _run_status(channels, sources)
+            finished_at = clock()
+            db.flush()  # SessionLocal has autoflush off: the snapshot queries must see this run's new rows
+            snapshot = build_snapshot(db, active, channels, finished_at)  # what /pricing shows now (v2.40.0)
             run = db.get(PriceSyncRun, run_id)
-            run.finished_at = clock()
+            run.finished_at = finished_at
             run.status = status
-            run.summary = {"sources": sources, "channels": dict(sorted(channels.items())), "errors": errors[:_MAX_ERRORS]}
+            run.summary = {"sources": sources, "channels": dict(sorted(channels.items())), "errors": errors[:_MAX_ERRORS],
+                           "snapshot": snapshot}
             run.changes = changes
             run.pending = pending
             db.commit()
diff --git a/backend/routers/pricing.py b/backend/routers/pricing.py
index 0d2d0ff..e149119 100644
--- a/backend/routers/pricing.py
+++ b/backend/routers/pricing.py
@@ -2,7 +2,8 @@
 
 Public:
   GET /api/pricing                                   - price table payload (pricing_payload.build_pricing_payload)
-  GET /api/pricing/export?format=csv|md|json&lang=ko|en - the same table as a download (attachment)
+                                                       + `changes`, the run-to-run table changes (pricing_changes, v2.40.0)
+  GET /api/pricing/export?format=csv|md|json&lang=ko|en - the same table as a download (attachment), without `changes`
 Admin (JWT, username == "admin"):
   GET  /api/admin/pricing/pending                    - pending_review rows with current value and change ratio
   POST /api/admin/pricing/pending/{row_id}/approve   - status -> verified (effective_from unchanged)
@@ -29,6 +30,7 @@ from auth import get_current_user
 from database import get_db
 from models import PriceHistory, User
 from price_history import as_utc, current_rows
+from pricing_changes import latest_changes
 from pricing_export import export_filename, to_csv, to_json, to_markdown
 from pricing_parsers import PRICE_FIELDS
 from pricing_payload import build_pricing_payload, iso_z, price_number, price_number_or_none
@@ -87,6 +89,7 @@ def _payload(db: Session) -> dict:
         generation = _cache["generation"]
     now = datetime.now(timezone.utc)
     payload = build_pricing_payload(db, _active(db, now), now=now)
+    payload["changes"] = latest_changes(db)
     with _cache_lock:
         if _cache["generation"] == generation:  # an approve/reject during the build may have made it stale
             _cache["payload"] = payload
@@ -107,7 +110,8 @@ def export_pricing_table(
     db: Session = Depends(get_db),
 ):
     """Download the price table as CSV (UTF-8 BOM), Markdown or JSON."""
-    payload = _payload(db)
+    # The run-to-run changes are a page feature (v2.40.0): the exports keep their v2.39.0 content.
+    payload = {key: value for key, value in _payload(db).items() if key != "changes"}
     if fmt == "csv":
         body = to_csv(payload, lang)
     elif fmt == "md":
````
- [ ] **Step 4:** Run:

```bash
cd backend && python3.12 -m pytest tests/test_pricing_changes.py tests/test_pricing_sync.py tests/test_pricing_router.py tests/test_pricing_export.py tests/test_pricing_payload.py tests/test_haiku55_catalog.py tests/test_pricing_sync_runner.py -q
```

Expected: all pass (the three suites of Step 2 are 124 tests; `test_pricing_export.py` and `test_pricing_payload.py` goldens are unchanged).
- [ ] **Step 5:** Run:

```bash
cd backend && python3.12 -m pytest tests/ -q
```

Expected: `1783 passed, 18 skipped` (the whole suite, about 45 s).
- [ ] **Step 6:** Commit:

```bash
git add backend/pricing_changes.py \
  backend/pricing_sync.py \
  backend/routers/pricing.py \
  backend/tests/test_pricing_changes.py \
  backend/tests/test_pricing_sync.py \
  backend/tests/test_pricing_router.py
git commit -m "feat(pricing): store what /pricing shows at the end of each sync run and list the run-to-run changes"
```
---

### Task 7: ExplorerVerify schedule (CDK)

**Files:**
- Modify: `cdk/lib/stacks/scheduler-stack.ts`
- Test: `cdk/test/scheduler-stack.test.ts`, `cdk/test/image-pinning.test.ts`

**Interfaces:**
- Consumes: `explorer_runner --once` (Task 4).
- Produces: task def `ExplorerVerifyTaskDef` (family `BedrockMonitorSchedulerExplorerVerifyTaskDef…`), schedule `ExplorerVerifySchedule` `cron(0 18 * * ? *)` Etc/UTC, log group `/ecs/explorer`. Task 11's runbook and Task 14's deploy use these names.
- [ ] **Step 1:** Apply this change to `cdk/test/scheduler-stack.test.ts`, `cdk/test/image-pinning.test.ts` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact). Counts go from 6 to 7 schedules and task defs, the daily cron list gets `cron(0 18 * * ? *)`, and a new `ExplorerVerify` describe block pins the cron, the command, the log group, the shared role, env and secrets, and the RunTask wildcard.

````diff
diff --git a/cdk/test/image-pinning.test.ts b/cdk/test/image-pinning.test.ts
index 473e460..4ceb2a9 100644
--- a/cdk/test/image-pinning.test.ts
+++ b/cdk/test/image-pinning.test.ts
@@ -130,13 +130,14 @@ describe("context 이미지 주입 (backendImage/frontendImage)", () => {
     }));
   });
 
-  it("scheduler의 autoprober/insights/parity/gptbench/features/pricingsync task definition도 backend digest URI를 사용한다", () => {
+  it("scheduler의 autoprober/insights/parity/gptbench/features/pricingsync/explorer task definition도 backend digest URI를 사용한다", () => {
     const tds = schedTemplate.findResources("AWS::ECS::TaskDefinition");
     const images = Object.values(tds).map(
       (td) => (td as any).Properties.ContainerDefinitions[0].Image,
     );
     // autoprober + insights + parityrun (v2.11.0) + gptbench (v2.18.0) + featuresverify (v2.23.0) + pricingsync (v2.30.0)
-    expect(images).toHaveLength(6);
+    // + explorerverify (v2.40.0)
+    expect(images).toHaveLength(7);
     for (const img of images) {
       expect(img).toBe(BE_URI);
     }
diff --git a/cdk/test/scheduler-stack.test.ts b/cdk/test/scheduler-stack.test.ts
index ecf5f7c..fcc9b76 100644
--- a/cdk/test/scheduler-stack.test.ts
+++ b/cdk/test/scheduler-stack.test.ts
@@ -37,8 +37,8 @@ describe("SchedulerStack", () => {
     template = Template.fromStack(scheduler);
   });
 
-  it("Schedule이 6개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify + PricingSync)", () => {
-    template.resourceCountIs("AWS::Scheduler::Schedule", 6);
+  it("Schedule이 7개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify + PricingSync + ExplorerVerify)", () => {
+    template.resourceCountIs("AWS::Scheduler::Schedule", 7);
   });
 
   it("AutoProber는 rate(5 minutes) 스케줄을 사용한다", () => {
@@ -76,8 +76,8 @@ describe("SchedulerStack", () => {
     }));
   });
 
-  it("TaskDefinition이 6개 생성된다 (PricingSync 포함, v2.30.0)", () => {
-    template.resourceCountIs("AWS::ECS::TaskDefinition", 6);
+  it("TaskDefinition이 7개 생성된다 (PricingSync v2.30.0, ExplorerVerify v2.40.0 포함)", () => {
+    template.resourceCountIs("AWS::ECS::TaskDefinition", 7);
   });
 
   it("Task는 Fargate, awsvpc, X86_64로 설정된다", () => {
@@ -158,11 +158,12 @@ describe("SchedulerStack", () => {
       ScheduleExpressionTimezone: "Etc/UTC",
       Description: Match.stringLikeRegexp("daily at 17:30 UTC"),
     }));
-    // 일 1회 스케줄은 이 cron 하나뿐 — 이전 rate(1 day)가 남아 하루 두 번 돌지 않는다.
+    // 일 1회 스케줄은 고정 cron 두 개뿐(FeaturesVerify 17:30, ExplorerVerify 18:00 UTC) — 이전 rate(1 day)가 남아 하루 두 번 돌지 않는다.
     const expressions = Object.values(template.findResources("AWS::Scheduler::Schedule"))
       .map((resource) => resource.Properties.ScheduleExpression);
     expect(expressions).not.toContain("rate(1 day)");
-    expect(expressions.filter((expression: string) => expression.startsWith("cron("))).toEqual(["cron(30 17 * * ? *)"]);
+    expect(expressions.filter((expression: string) => expression.startsWith("cron(")).sort())
+      .toEqual(["cron(0 18 * * ? *)", "cron(30 17 * * ? *)"]);
     template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
       ContainerDefinitions: Match.arrayWith([Match.objectLike({
         Command: ["python", "-m", "features_runner", "--once"],
@@ -205,6 +206,56 @@ describe("SchedulerStack", () => {
     }));
   });
 
+  describe("ExplorerVerify (v2.40.0, ADR-035)", () => {
+    const EXPLORER_COMMAND = ["python", "-m", "explorer_runner", "--once"];
+    type Container = { Command: string[]; Environment?: { Name: string; Value: string }[]; Secrets?: { Name: string }[] };
+    const taskDefs = () => Object.entries(template.findResources("AWS::ECS::TaskDefinition"));
+    const byCommand = (command: string[]) => {
+      const found = taskDefs().filter(([, r]) => (r.Properties.ContainerDefinitions as Container[])
+        .some((c) => c.Command.join(" ") === command.join(" ")));
+      expect(found).toHaveLength(1);
+      return found[0]!;
+    };
+
+    it("매일 18:00 UTC 고정 cron 스케줄이 explorer_runner --once task def를 실행한다", () => {
+      const [taskDefId] = byCommand(EXPLORER_COMMAND);
+      const targeting = Object.values(template.findResources("AWS::Scheduler::Schedule"))
+        .filter((schedule) => schedule.Properties.Target.EcsParameters.TaskDefinitionArn.Ref === taskDefId);
+      expect(targeting).toHaveLength(1);
+      expect(targeting[0]!.Properties.ScheduleExpression).toBe("cron(0 18 * * ? *)");
+      expect(targeting[0]!.Properties.ScheduleExpressionTimezone).toBe("Etc/UTC");
+      expect(targeting[0]!.Properties.Description).toMatch(/daily at 18:00 UTC/);
+    });
+
+    it("로그 그룹 /ecs/explorer 14일, 0.5 vCPU / 1 GB, autoprober와 같은 task role, env, secret", () => {
+      const [, explorer] = byCommand(EXPLORER_COMMAND);
+      const [, autoProber] = byCommand(["python", "-m", "auto_prober_runner", "--once"]);
+      expect(explorer.Properties.Cpu).toBe("512");
+      expect(explorer.Properties.Memory).toBe("1024");
+      expect(explorer.Properties.TaskRoleArn).toEqual(autoProber.Properties.TaskRoleArn);
+      const container = explorer.Properties.ContainerDefinitions[0] as Container & {
+        LogConfiguration: { Options: { "awslogs-group": { Ref: string } } } };
+      const logGroupId = container.LogConfiguration.Options["awslogs-group"].Ref;
+      expect(template.findResources("AWS::Logs::LogGroup")[logGroupId]?.Properties)
+        .toEqual({ LogGroupName: "/ecs/explorer", RetentionInDays: 14 });
+      const probe = autoProber.Properties.ContainerDefinitions[0] as Container;
+      expect(container.Environment).toEqual(
+        (probe.Environment ?? []).filter((variable) => variable.Name !== "ANTHROPIC_CP_PROBE_INTERVAL_S"));
+      expect((container.Secrets ?? []).map((s) => s.Name).sort()).toEqual((probe.Secrets ?? []).map((s) => s.Name).sort());
+    });
+
+    it("Scheduler 역할의 RunTask family ':*' 목록에 ExplorerVerify가 들어간다 (ADR-011)", () => {
+      const [, explorer] = byCommand(EXPLORER_COMMAND);
+      const statements = Object.entries(template.findResources("AWS::IAM::Policy"))
+        .filter(([logicalId]) => logicalId.startsWith("SchedulerInvokeRoleDefaultPolicy"))
+        .flatMap(([, policy]) => policy.Properties.PolicyDocument.Statement)
+        .filter((statement: { Sid?: string }) => statement.Sid === "RunTaskFamilyWildcard");
+      expect(statements).toHaveLength(1);
+      expect(statements[0].Resource).toContain(
+        `arn:aws:ecs:us-east-1:111111111111:task-definition/${explorer.Properties.Family as string}:*`);
+    });
+  });
+
   describe("PricingSync (v2.30.0, ADR-030)", () => {
     const PRICING_COMMAND = ["python", "-m", "pricing_sync_runner", "--once"];
     type Container = { Command: string[]; Environment?: { Name: string; Value: string }[]; Secrets?: { Name: string }[] };
@@ -308,19 +359,19 @@ describe("SchedulerStack", () => {
 
   it("모든 스케줄 task def에 GPT-6.1 Sol model id가 주입된다 (v2.32.0)", () => {
     const containers = Object.values(template.findResources("AWS::ECS::TaskDefinition")).flatMap((r: any) => r.Properties.ContainerDefinitions);
-    expect(containers).toHaveLength(6);
+    expect(containers).toHaveLength(7);
     for (const c of containers) expect(c.Environment).toContainEqual({ Name: "BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", Value: "openai.gpt-6.1-sol" });
   });
 
   it("모든 스케줄 task def에 GPT-6.1 Terra model id가 주입된다 (v2.38.0)", () => {
     const containers = Object.values(template.findResources("AWS::ECS::TaskDefinition")).flatMap((r: any) => r.Properties.ContainerDefinitions);
-    expect(containers).toHaveLength(6);
+    expect(containers).toHaveLength(7);
     for (const c of containers) expect(c.Environment).toContainEqual({ Name: "BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID", Value: "openai.gpt-6.1-terra" });
   });
 
   it("어느 스케줄 task def에도 GPT 5.4 model id가 없다 (v2.39.0 — 모니터링에서 뺐다)", () => {
     const containers = Object.values(template.findResources("AWS::ECS::TaskDefinition")).flatMap((r: any) => r.Properties.ContainerDefinitions);
-    expect(containers).toHaveLength(6);
+    expect(containers).toHaveLength(7);
     for (const c of containers) {
       const names = c.Environment.map((e: any) => e.Name);
       expect(names).not.toContain("BEDROCK_OPENAI_GPT_54_MODEL_ID");
@@ -328,9 +379,9 @@ describe("SchedulerStack", () => {
     }
   });
 
-  it("all six shared backend tasks retain the visitor origin configuration", () => {
+  it("all seven shared backend tasks retain the visitor origin configuration", () => {
     const tasks = Object.values(template.findResources("AWS::ECS::TaskDefinition"));
-    expect(tasks).toHaveLength(6);
+    expect(tasks).toHaveLength(7);
     for (const task of tasks) {
       expect(task.Properties.ContainerDefinitions[0].Environment).toContainEqual({
         Name: "PRESENCE_ALLOWED_ORIGINS", Value: "https://llm-monitor.whchoi.net",
````
- [ ] **Step 2:** Run:

```bash
cd cdk && npx jest --ci test/scheduler-stack.test.ts test/image-pinning.test.ts
```

Expected: failures such as `Expected 7 resources of type AWS::Scheduler::Schedule but found 6`.
- [ ] **Step 3:** Apply this change to `cdk/lib/stacks/scheduler-stack.ts` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/cdk/lib/stacks/scheduler-stack.ts b/cdk/lib/stacks/scheduler-stack.ts
index 4b33767..6e7a551 100644
--- a/cdk/lib/stacks/scheduler-stack.ts
+++ b/cdk/lib/stacks/scheduler-stack.ts
@@ -1,4 +1,4 @@
-// SchedulerStack - EventBridge Scheduler + AutoProber / Insights / ParityRun / GptBench / FeaturesVerify / PricingSync one-shot TaskDefinitions.
+// SchedulerStack - EventBridge Scheduler + AutoProber / Insights / ParityRun / GptBench / FeaturesVerify / PricingSync / ExplorerVerify one-shot TaskDefinitions.
 //
 // 책임:
 //   - rate(5 minutes) → AutoProber Fargate Task (auto_prober_runner --once)
@@ -11,6 +11,8 @@
 //   - cron(30 17 * * ? *) Etc/UTC → FeaturesVerify Fargate Task (features_runner --once)
 //     (v2.29.0: 매일 17:30 UTC = 02:30 KST 고정 1회. 이전 rate(24 hours)는 스케줄 생성 시각 기준이라 시각이 고정되지 않았다)
 //   - rate(12 hours) → PricingSync Fargate Task (pricing_sync_runner --once)
+//   - cron(0 18 * * ? *) Etc/UTC → ExplorerVerify Fargate Task (explorer_runner --once)
+//     (v2.40.0, ADR-035: 매일 18:00 UTC = 03:00 KST 고정 1회 — FeaturesVerify(17:30 UTC, 약 13분) 뒤라 같은 모델 호출이 겹치지 않는다)
 //     (v2.30.0: 공식 단가 동기화 — Bedrock agreement offers, AWS Price List, Anthropic pricing.md. 모델 호출 권한 없음, ADR-030)
 //   - 각 TaskDefinition은 backend ECR 이미지를 재사용하고 CMD만 override.
 //   - 모든 task는 RDS:5432 egress + Bedrock/Mantle 액세스 필요 → 별도 SG + RDS SG에 ingress(standalone) 추가.
@@ -348,6 +350,17 @@ export class SchedulerStack extends cdk.Stack {
       "/ecs/features",
     );
 
+    // Model Explorer 코드 예제 검증 (v2.40.0, ADR-035) — /models가 보여 주는 예제(Converse, InvokeModel, Messages, Responses)를
+    //   모델마다 실제로 실행한다(활성 49모델 → 85건, 동시 4). 예제가 Bedrock(IAM), CP(API 키), Mantle과 CRIS(ABSK 키)를 모두
+    //   부르므로 autoprober role과 기본 env/secret을 그대로 쓴다. 예제 자식 프로세스에는 허용 목록 env만 넘긴다
+    //   (model_explorer/execute.py — DB_*, JWT_SECRET_KEY는 자식에 가지 않는다). 새 env, 새 IAM 정책은 없다.
+    const explorerTaskDef = buildTaskDef(
+      "ExplorerVerifyTaskDef",
+      autoProberTaskRole,
+      ["python", "-m", "explorer_runner", "--once"],
+      "/ecs/explorer",
+    );
+
     // 공식 단가 동기화 (v2.30.0, ADR-030) — 12시간마다 활성 61채널(v2.38.0) + OpenAI 공식 가격 10채널의 Standard 입력/출력 단가를 공식 출처에서 읽어
     // price_history에 기록한다(50% 초과 변화는 검토 대기). 같은 env/secret(buildTaskDef 기본값)으로 CP 디스커버리와
     // OpenAI 채널 등록을 AutoProber와 똑같이 해야 활성 채널 집합이 맞는다. extraEnvironment 없음.
@@ -387,6 +400,7 @@ export class SchedulerStack extends cdk.Stack {
           `arn:aws:ecs:${this.region}:${this.account}:task-definition/${gptBenchTaskDef.family}:*`,
           `arn:aws:ecs:${this.region}:${this.account}:task-definition/${featuresTaskDef.family}:*`,
           `arn:aws:ecs:${this.region}:${this.account}:task-definition/${pricingSyncTaskDef.family}:*`,
+          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${explorerTaskDef.family}:*`,
         ],
       }),
     );
@@ -476,6 +490,21 @@ export class SchedulerStack extends cdk.Stack {
       }),
     });
 
+    new scheduler.Schedule(this, "ExplorerVerifySchedule", {
+      // 일 1회 (사용자 요청 2026-11-05 "모델 탐색도 1일 1회 런으로 검증") — 매일 18:00 UTC(= 03:00 KST) 고정 cron.
+      //   FeaturesVerify(17:30 UTC, 약 13분) 뒤로 둔다. rate(24 hours)는 스케줄 생성 시각에 묶이므로 쓰지 않는다.
+      schedule: scheduler.ScheduleExpression.cron({ minute: "0", hour: "18", timeZone: cdk.TimeZone.ETC_UTC }),
+      description: "Model Explorer code example verification: every example of every monitored model, daily at 18:00 UTC",
+      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
+        taskDefinition: explorerTaskDef,
+        vpcSubnets: props.appSubnets,
+        securityGroups: [schedulerTaskSg],
+        assignPublicIp: false,
+        platformVersion: ecs.FargatePlatformVersion.LATEST,
+        role: schedulerInvokeRole,
+      }),
+    });
+
     const pricingSyncSchedule = new scheduler.Schedule(this, "PricingSyncSchedule", {
       // 12시간 주기 (v2.30.0, 사용자 결정 2026-09-26) — offers FM 20개 순차 약 28초(v2.32.0 — 서울 in-region은 기존 FM 오퍼 재사용) + Price List 1회 + Anthropic 문서 1회 + OpenAI 문서 1회.
       //   런 전체 상한 300초(SYNC_DEADLINE_S), pg_try_advisory_lock(917350004)로 수동 실행과 겹치지 않는다
````
- [ ] **Step 4:** Run:

```bash
cd cdk && npx jest --ci && npx tsc --noEmit && npm run lint
```

Expected: `Tests: 98 passed, 98 total`, no type errors, lint `0 errors, 9 warnings` (the warnings exist on `c96a592`).
- [ ] **Step 5:** Commit:

```bash
git add cdk/lib/stacks/scheduler-stack.ts \
  cdk/test/scheduler-stack.test.ts \
  cdk/test/image-pinning.test.ts
git commit -m "infra(scheduler): daily ExplorerVerify task at 18:00 UTC with the RunTask family wildcard"
```
---

### Task 8: Frontend types, API client and pure view logic

**Files:**
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/pricingTable.ts`
- Create: `frontend/src/lib/explorerVerify.ts`
- Test: `frontend/src/lib/explorerVerify.test.ts` (new), `frontend/src/lib/pricingTable.test.ts` (new describe block)

**Interfaces:**
- Consumes: the API shapes of Tasks 5 and 6.
- Produces:
  - types `ExplorerStatus`, `ExplorerResult`, `ExplorerExample`, `ExplorerChange`, `ExplorerLatest`, `PricingField`, `PricingChangeItem`, `PricingChanges`; `PricingResponse.changes?: PricingChanges`.
  - `fetchExplorerLatest(signal?) -> Promise<ExplorerLatest>`, `triggerExplorerRun() -> Promise<{triggered, message}>`.
  - `explorerVerify.ts`: `summarizeModel(examples) -> {passed, failed, skipped, total, grade: "passed"|"failed"|"none"}`, `badgeLabel(summary, lang)`, `hasFailure(examples)`, `statusLabel(status | null, lang)`, `changeKindLabel(kind, lang)`, `summarizeChanges(changes)`, `changedModelIds(changes) -> Set<string>`, `splitError(message) -> {head, tail}`, `reasonText(message, lang)`, `formatLatency(ms, lang)`, type `ModelGrade`.
  - `pricingTable.ts`: `PricingBadge.kind` adds `"changed" | "new_channel"`; `changeKindTag(item) -> PricingChangeTag`, `changeTagLabel(tag, lang)`, `changeItemText(item, lang)`, `priceCellId(familyKey, tier)`, `cellChangeBadge(items, familyKey, tier, lang) -> PricingBadge | null`, type `PricingChangeTag`.
  Tasks 9 and 10 use all of these.

`PricingBadge.kind` gains two members, so `PricingPanel.tsx`'s `BADGE_CLASS`/`BADGE_WRAP` records stop type-checking until Task 10. Run only vitest here; `npm run typecheck` is green again after Task 10.
- [ ] **Step 1a:** Create `frontend/src/lib/explorerVerify.test.ts`:

````ts
import { describe, expect, test } from "vitest";
import {
  badgeLabel, changedModelIds, changeKindLabel, formatLatency, hasFailure, reasonText, splitError, statusLabel,
  summarizeChanges, summarizeModel,
} from "./explorerVerify";
import type { ExplorerChange, ExplorerExample, ExplorerStatus } from "./types";

function example(status: ExplorerStatus | null, apiId: ExplorerExample["api_id"] = "converse"): ExplorerExample {
  return {
    api_id: apiId, api: "Converse API", label: "Python (boto3)", language: "python",
    description: { ko: "설명", en: "desc" }, code: { ko: "print(1)", en: "print(1)" }, code_sha: "x",
    result: status === null ? null : {
      status, latency_ms: 1200, attempts: 1, error_message: null, output_excerpt: "Hello!", run_id: 3,
      verified_at: "2026-11-05T18:02:00Z", stale_code: false,
    },
  };
}

function change(kind: ExplorerChange["kind"], modelId = "m1"): ExplorerChange {
  return { model_id: modelId, model_name: "M", api_id: "converse", api: "Converse API", before: "passed", after: "failed", kind };
}

describe("summarizeModel and badgeLabel — card verification badge", () => {
  test("all passed", () => {
    const summary = summarizeModel([example("passed"), example("passed"), example("passed")]);
    expect(summary).toEqual({ passed: 3, failed: 0, skipped: 0, total: 3, grade: "passed" });
    expect(badgeLabel(summary, "ko")).toBe("✓ 3/3 통과");
    expect(badgeLabel(summary, "en")).toBe("✓ 3/3 passed");
  });
  test("a failure wins over passes", () => {
    const summary = summarizeModel([example("passed"), example("failed"), example("passed")]);
    expect(summary.grade).toBe("failed");
    expect(badgeLabel(summary, "ko")).toBe("✗ 1/3 실패");
    expect(badgeLabel(summary, "en")).toBe("✗ 1/3 failed");
  });
  test("passes and skips name the skips", () => {
    const summary = summarizeModel([example("passed"), example("passed"), example("skipped")]);
    expect(badgeLabel(summary, "ko")).toBe("✓ 2/3 통과, 1 건너뜀");
    expect(badgeLabel(summary, "en")).toBe("✓ 2/3 passed, 1 skipped");
  });
  test("no result is not verified", () => {
    const summary = summarizeModel([example(null), example(null)]);
    expect(summary.grade).toBe("none");
    expect(badgeLabel(summary, "ko")).toBe("검증 전");
    expect(badgeLabel(summary, "en")).toBe("Not verified");
    expect(summarizeModel([]).grade).toBe("none");
  });
});

describe("labels", () => {
  test("statuses and the new cell", () => {
    expect(["passed", "failed", "skipped"].map((s) => statusLabel(s as ExplorerStatus, "ko"))).toEqual(["통과", "실패", "건너뜀"]);
    expect(statusLabel(null, "ko")).toBe("신규");
    expect(statusLabel(null, "en")).toBe("New");
  });
  test("change kinds", () => {
    expect(changeKindLabel("catalog", "ko")).toBe("신규");
    expect(changeKindLabel("example", "ko")).toBe("예제 변경");
    expect(changeKindLabel("measured", "ko")).toBe("실측");
    expect(changeKindLabel("example", "en")).toBe("Example changed");
  });
});

describe("changes and failures", () => {
  test("summarizeChanges counts each kind", () => {
    expect(summarizeChanges([change("catalog"), change("measured"), change("measured")]))
      .toEqual({ catalog: 1, example: 0, measured: 2 });
  });
  test("changedModelIds", () => {
    expect([...changedModelIds([change("measured", "a"), change("example", "b"), change("catalog", "a")])]).toEqual(["a", "b"]);
  });
  test("hasFailure", () => {
    expect(hasFailure([example("passed"), example("failed")])).toBe(true);
    expect(hasFailure([example("passed"), example("skipped"), example(null)])).toBe(false);
  });
});

describe("result texts", () => {
  test("splitError keeps the exception line apart from the stderr tail", () => {
    expect(splitError("KeyError: 'text'\nTraceback (most recent call last):\n  ...")).toEqual({
      head: "KeyError: 'text'", tail: "Traceback (most recent call last):\n  ..." });
    expect(splitError("출력 없음")).toEqual({ head: "출력 없음", tail: "" });
    expect(splitError(null)).toEqual({ head: "", tail: "" });
  });
  test("reasonText translates the backend messages and leaves exceptions", () => {
    expect(reasonText("출력 없음", "en")).toBe("No output");
    expect(reasonText("시간 초과 90초", "en")).toBe("Timed out after 90 s");
    expect(reasonText("자격 증명 미주입: OPENAI_1P_API_KEY", "en")).toBe("Credentials not injected: OPENAI_1P_API_KEY");
    expect(reasonText("알 수 없는 플레이스홀더", "en")).toBe("Unknown placeholder");
    expect(reasonText("런 시간 상한", "en")).toBe("Run time limit reached");
    expect(reasonText("KeyError: 'text'", "en")).toBe("KeyError: 'text'");
    expect(reasonText("시간 초과 90초", "ko")).toBe("시간 초과 90초");
  });
  test("formatLatency", () => {
    expect(formatLatency(1180, "ko")).toBe("1.2초");
    expect(formatLatency(1180, "en")).toBe("1.2 s");
    expect(formatLatency(null, "ko")).toBe("");
  });
});
````
- [ ] **Step 1b:** Apply this change to `frontend/src/lib/pricingTable.test.ts` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/frontend/src/lib/pricingTable.test.ts b/frontend/src/lib/pricingTable.test.ts
index d4ef13d..6979e84 100644
--- a/frontend/src/lib/pricingTable.test.ts
+++ b/frontend/src/lib/pricingTable.test.ts
@@ -9,10 +9,13 @@
  */
 import { afterEach, describe, expect, test, vi } from "vitest";
 import { fetchPricing, pricingExportUrl } from "./api";
-import type { PricingDocConflictNote, PricingModelPrice, PricingPending, PricingPromoNote, PricingTier } from "./types";
+import type {
+  PricingChangeItem, PricingDocConflictNote, PricingModelPrice, PricingPending, PricingPromoNote, PricingTier,
+} from "./types";
 import {
-  PROVIDER_COLUMNS, cacheItems, columnsFor, costFromPrices, formatPricePair, formatUnitPrice, headerParts, longItems,
-  notesForTier, pendingDetail, textRuns, tierBadges, tierLabel, utcDate,
+  PROVIDER_COLUMNS, cacheItems, cellChangeBadge, changeItemText, changeKindTag, changeTagLabel, columnsFor, costFromPrices,
+  formatPricePair, formatUnitPrice, headerParts, longItems, notesForTier, pendingDetail, priceCellId, textRuns, tierBadges,
+  tierLabel, utcDate,
 } from "./pricingTable";
 
 afterEach(() => {
@@ -466,3 +469,61 @@ describe("pricing API client", () => {
     expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
   });
 });
+
+describe("run-to-run changes (v2.40.0)", () => {
+  const item = (over: Partial<PricingChangeItem>): PricingChangeItem => ({
+    model_id: "global.anthropic.claude-sonnet-5-5", family_key: "claude-sonnet-5-5", family: "Claude Sonnet 5.5",
+    provider: "anthropic", tier: "global", region: null, kind: "price", field: "cache_read", before: 0.2, after: 0.1, ...over,
+  });
+
+  test("changeKindTag reads the kind and the direction", () => {
+    expect(changeKindTag(item({}))).toBe("applied");
+    expect(changeKindTag(item({ kind: "pending", before: null, after: 3.3 }))).toBe("pending");
+    expect(changeKindTag(item({ kind: "pending", before: 3.3, after: null }))).toBe("released");
+    expect(changeKindTag(item({ kind: "check", field: null, before: "ok", after: "skipped:parse_failed" }))).toBe("check_failed");
+    expect(changeKindTag(item({ kind: "check", field: null, before: "skipped:parse_failed", after: "ok" }))).toBe("check_recovered");
+    expect(changeKindTag(item({ kind: "channel", field: null, before: null, after: "present" }))).toBe("new_channel");
+    expect(changeKindTag(item({ kind: "channel", field: null, before: "present", after: null }))).toBe("left_channel");
+    expect(changeTagLabel("applied", "ko")).toBe("적용");
+    expect(changeTagLabel("pending", "en")).toBe("Pending review");
+  });
+
+  test("changeItemText names the family, the column and the values", () => {
+    expect(changeItemText(item({}), "ko")).toBe("Claude Sonnet 5.5, AWS Bedrock - Global CRIS, 캐시 읽기 $0.20 → $0.10");
+    expect(changeItemText(item({}), "en")).toBe("Claude Sonnet 5.5, AWS Bedrock - Global CRIS, cache read $0.20 → $0.10");
+    expect(changeItemText(item({ family: "GPT 6 Sol", tier: "us", kind: "pending", field: "input", before: null, after: 3.3 }), "ko"))
+      .toBe("GPT 6 Sol, AWS Bedrock - US CRIS, 입력 — → $3.30");
+    expect(changeItemText(item({ family: "Claude Opus 5", tier: "cp", kind: "check", field: null, before: "ok", after: "skipped:parse_failed" }), "ko"))
+      .toBe("Claude Opus 5, Claude Platform on AWS, 문서 파싱 실패");
+    expect(changeItemText(item({ tier: "global", kind: "check", field: null, before: "ok", after: "skipped:fetch_failed" }), "en"))
+      .toBe("Claude Sonnet 5.5, AWS Bedrock - Global CRIS, source unreachable");
+    expect(changeItemText(item({ family: "GPT 6.1 Terra", kind: "channel", field: null, before: null, after: "present" }), "ko"))
+      .toBe("GPT 6.1 Terra, AWS Bedrock - Global CRIS");
+    expect(changeItemText(item({ family: "GPT 5.6 Terra", tier: "in_region", region: "us-east-1", field: "input", before: 2.2, after: 2.5 }), "ko"))
+      .toBe("GPT 5.6 Terra, AWS Bedrock - In Region (us-east-1), 입력 $2.20 → $2.50");
+    expect(changeItemText(item({ kind: "check", field: null, before: "ok", after: "skipped:something_new" }), "ko"))
+      .toBe("Claude Sonnet 5.5, AWS Bedrock - Global CRIS, something_new");
+  });
+
+  test("priceCellId", () => {
+    expect(priceCellId("gpt-5.6-sol", "in_region")).toBe("price-gpt-5.6-sol-in_region");
+  });
+
+  test("cellChangeBadge: the cell's first change, the count of the rest, or a new channel", () => {
+    const items = [
+      item({}),
+      item({ kind: "pending", field: "input", before: null, after: 3 }),
+      item({ tier: "us", model_id: "us.anthropic.claude-sonnet-5-5", kind: "channel", field: null, before: null, after: "present" }),
+    ];
+    expect(cellChangeBadge(items, "claude-sonnet-5-5", "global", "ko"))
+      .toEqual({ kind: "changed", label: "이전 대비 변경", detail: "캐시 읽기 $0.20 → $0.10, 외 1건" });
+    expect(cellChangeBadge(items, "claude-sonnet-5-5", "global", "en"))
+      .toEqual({ kind: "changed", label: "Changed since last sync", detail: "cache read $0.20 → $0.10, +1 more" });
+    expect(cellChangeBadge(items, "claude-sonnet-5-5", "us", "ko")).toEqual({ kind: "new_channel", label: "신규 채널", detail: "" });
+    expect(cellChangeBadge(items, "claude-sonnet-5-5", "cp", "ko")).toBeNull();
+    expect(cellChangeBadge([item({ kind: "pending", field: "input", before: null, after: 3.3 })], "claude-sonnet-5-5", "global", "ko"))
+      .toEqual({ kind: "changed", label: "이전 대비 변경", detail: "검토 대기: 입력 — → $3.30" });
+    expect(cellChangeBadge([item({ kind: "channel", field: null, before: "present", after: null })], "claude-sonnet-5-5", "global", "ko"))
+      .toBeNull();
+  });
+});
````
- [ ] **Step 2:** Run:

```bash
cd frontend && npx vitest run src/lib/explorerVerify.test.ts src/lib/pricingTable.test.ts
```

Expected: fails — `Failed to resolve import "./explorerVerify"` and missing exports `cellChangeBadge`, `changeItemText`, ….
- [ ] **Step 3a:** Apply this change to `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/pricingTable.ts` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/frontend/src/lib/api.ts b/frontend/src/lib/api.ts
index 0dbb8db..aad3b98 100644
--- a/frontend/src/lib/api.ts
+++ b/frontend/src/lib/api.ts
@@ -10,6 +10,7 @@ import {
   ChatStreamEvents,
   Insight,
   AutoProbeAnomalies,
+  ExplorerLatest,
   PricingResponse,
 } from "./types";
 import { ApiError, fetchJson } from "./http";
@@ -867,6 +868,17 @@ export async function triggerFeaturesRun(): Promise<{ triggered: boolean; messag
   return authenticatedJson(`${BASE}/api/features/trigger`, { method: "POST" });
 }
 
+// ── Model Explorer verification (v2.40.0) ───────────────────────────────
+
+/** Code examples of every visible model with the latest daily verification result (backend single source). */
+export async function fetchExplorerLatest(signal?: AbortSignal): Promise<ExplorerLatest> {
+  return fetchJson(`${BASE}/api/explorer/latest`, { signal });
+}
+
+export async function triggerExplorerRun(): Promise<{ triggered: boolean; message: string }> {
+  return authenticatedJson(`${BASE}/api/explorer/trigger`, { method: "POST" });
+}
+
 // ── Unit prices (v2.30.0) ───────────────────────────────────────────────
 
 /** Public price table, backend single source (official sources refreshed every 12 hours). */
diff --git a/frontend/src/lib/pricingTable.ts b/frontend/src/lib/pricingTable.ts
index fd7947c..e3464f5 100644
--- a/frontend/src/lib/pricingTable.ts
+++ b/frontend/src/lib/pricingTable.ts
@@ -4,7 +4,8 @@
 
 import { parseTimestamp } from "./format";
 import type {
-  PricingDocConflictNote, PricingFamily, PricingModelPrice, PricingNote, PricingPriceFields, PricingPromoNote, PricingTier,
+  PricingChangeItem, PricingDocConflictNote, PricingFamily, PricingField, PricingModelPrice, PricingNote, PricingPriceFields,
+  PricingPromoNote, PricingTier,
 } from "./types";
 
 export type PricingTierKey = "cp" | "openai_list" | "global" | "us" | "in_region";
@@ -187,7 +188,7 @@ export function utcDate(value: string | null | undefined): string | null {
  * touch or keyboard users. `ref` is the reference id whose footnote carries the note's source (promotions only).
  */
 export type PricingBadge = {
-  kind: "unverified" | "pending" | "promo" | "promo_check" | "doc_conflict";
+  kind: "unverified" | "pending" | "promo" | "promo_check" | "doc_conflict" | "changed" | "new_channel";
   label: string;
   detail: string;
   ref?: string;
@@ -289,3 +290,112 @@ export function costFromPrices(
   // Missing token counts count as zero, like the backend's COALESCE(tokens, 0) row cost.
   return ((inputTokens ?? 0) * price.input + (outputTokens ?? 0) * price.output) / 1_000_000;
 }
+
+// ── Run-to-run changes (v2.40.0, ADR-035) — the /api/pricing `changes` items as banner lines and cell badges ──
+
+const FIELD_LABELS: Record<PricingField, { ko: string; en: string }> = {
+  input: { ko: "입력", en: "input" },
+  output: { ko: "출력", en: "output" },
+  cache_read: { ko: "캐시 읽기", en: "cache read" },
+  cache_write: { ko: "캐시 쓰기", en: "cache write" },
+  cache_write_1h: { ko: "1시간 캐시 쓰기", en: "1h cache write" },
+  long_input: { ko: "긴 컨텍스트 입력", en: "long-context input" },
+  long_output: { ko: "긴 컨텍스트 출력", en: "long-context output" },
+  long_cache_read: { ko: "긴 컨텍스트 캐시 읽기", en: "long-context cache read" },
+  long_cache_write: { ko: "긴 컨텍스트 캐시 쓰기", en: "long-context cache write" },
+};
+
+// pricing_sync skip reasons (the `skipped:<reason>` channel results).
+const CHECK_REASONS: Record<string, { ko: string; en: string }> = {
+  fetch_failed: { ko: "출처 응답 실패", en: "source unreachable" },
+  parse_failed: { ko: "출처 파싱 실패", en: "source parse failed" },
+  offer_count: { ko: "공개 오퍼 수 이상", en: "unexpected number of public offers" },
+  not_found: { ko: "출처에 모델 없음", en: "model not found at the source" },
+  deadline: { ko: "동기화 시간 상한", en: "sync time limit reached" },
+  unmapped: { ko: "출처 미지정", en: "no source for the channel" },
+};
+
+export type PricingChangeTag = "new_channel" | "left_channel" | "applied" | "pending" | "released" | "check_failed" | "check_recovered";
+
+/** What a change item means for the banner tag. */
+export function changeKindTag(item: PricingChangeItem): PricingChangeTag {
+  if (item.kind === "channel") return item.after === null ? "left_channel" : "new_channel";
+  if (item.kind === "price") return "applied";
+  if (item.kind === "pending") return item.after === null ? "released" : "pending";
+  return item.after === "ok" ? "check_recovered" : "check_failed";
+}
+
+const TAG_LABELS: Record<PricingChangeTag, { ko: string; en: string }> = {
+  new_channel: { ko: "신규 채널", en: "New channel" },
+  left_channel: { ko: "제외 채널", en: "Removed channel" },
+  applied: { ko: "적용", en: "Applied" },
+  pending: { ko: "검토 대기", en: "Pending review" },
+  released: { ko: "검토 해제", en: "Review closed" },
+  check_failed: { ko: "확인 실패", en: "Check failed" },
+  check_recovered: { ko: "확인 복구", en: "Check recovered" },
+};
+
+export function changeTagLabel(tag: PricingChangeTag, lang: "ko" | "en"): string {
+  return TAG_LABELS[tag][lang];
+}
+
+function changeValue(value: number | string | null): string {
+  return typeof value === "number" ? formatUnitPrice(value) : "—";
+}
+
+/** "출처 파싱 실패" for "skipped:parse_failed"; a Claude Platform on AWS or OpenAI official price cell reads a pricing
+ *  page, so its parse failure is "문서 파싱 실패". */
+function checkReason(item: PricingChangeItem, lang: "ko" | "en"): string {
+  const raw = typeof item.after === "string" && item.after.startsWith("skipped:") ? item.after.slice("skipped:".length) : "";
+  if (raw === "parse_failed" && (item.tier === "cp" || item.tier === "openai_list")) {
+    return lang === "en" ? "pricing page parse failed" : "문서 파싱 실패";
+  }
+  return Object.prototype.hasOwnProperty.call(CHECK_REASONS, raw) ? CHECK_REASONS[raw][lang] : raw;
+}
+
+/** The value part of an item: "캐시 읽기 $0.20 → $0.10", "입력 — → $3.30", "문서 파싱 실패", or "" for a channel. */
+function changeDetail(item: PricingChangeItem, lang: "ko" | "en"): string {
+  if ((item.kind === "price" || item.kind === "pending") && item.field) {
+    return `${FIELD_LABELS[item.field][lang]} ${changeValue(item.before)} → ${changeValue(item.after)}`;
+  }
+  if (item.kind === "check" && item.after !== "ok") return checkReason(item, lang);
+  return "";
+}
+
+/** Banner line after the tag: "Claude Sonnet 5.5, AWS Bedrock - Global CRIS, 캐시 읽기 $0.20 → $0.10". An In Region
+ *  channel names its region: "GPT 5.6 Terra, AWS Bedrock - In Region (us-east-1)". */
+export function changeItemText(item: PricingChangeItem, lang: "ko" | "en"): string {
+  const column = `${tierLabel(item.tier, lang)}${item.region ? ` (${item.region})` : ""}`;
+  const detail = changeDetail(item, lang);
+  return [item.family, column, detail].filter(Boolean).join(", ");
+}
+
+/** The id of a price cell, the banner's scroll target: "price-claude-sonnet-5-5-global". */
+export function priceCellId(familyKey: string, tier: string): string {
+  return `price-${familyKey}-${tier}`;
+}
+
+/**
+ * The change badge of one cell: "이전 대비 변경" with the first change of the cell as its detail ("캐시 읽기 $0.20 →
+ * $0.10", "검토 대기: 입력 — → $3.30", "확인 실패: 문서 파싱 실패", then ", 외 N건" for more), or "신규 채널" for a cell
+ * whose only change is a new channel. null when the cell has no change.
+ */
+export function cellChangeBadge(items: PricingChangeItem[], familyKey: string, tier: string, lang: "ko" | "en"): PricingBadge | null {
+  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
+  const mine = items.filter((item) => item.family_key === familyKey && item.tier === tier);
+  const changes = mine.filter((item) => item.kind !== "channel");
+  if (changes.length === 0) {
+    return mine.some((item) => item.kind === "channel" && item.after !== null)
+      ? { kind: "new_channel", label: L("New channel", "신규 채널"), detail: "" }
+      : null;
+  }
+  const first = changes[0];
+  const tag = changeKindTag(first);
+  const prefix = tag === "applied" ? "" : `${changeTagLabel(tag, lang)}: `;
+  const more = mine.length > 1 ? L(`, +${mine.length - 1} more`, `, 외 ${mine.length - 1}건`) : "";
+  return {
+    kind: "changed",
+    label: L("Changed since last sync", "이전 대비 변경"),
+    detail: `${prefix}${changeDetail(first, lang)}${more}`.trim(),
+  };
+}
diff --git a/frontend/src/lib/types.ts b/frontend/src/lib/types.ts
index e867545..8912b90 100644
--- a/frontend/src/lib/types.ts
+++ b/frontend/src/lib/types.ts
@@ -265,6 +265,39 @@ export interface PricingModelPrice {
   verification: PriceVerification;
 }
 
+/** The nine price fields of a channel, in backend PRICE_FIELDS order. */
+export type PricingField =
+  | "input" | "output" | "cache_read" | "cache_write" | "cache_write_1h"
+  | "long_input" | "long_output" | "long_cache_read" | "long_cache_write";
+
+/** One run-to-run change of the price table (v2.40.0, backend pricing_changes.compare_snapshots). */
+export interface PricingChangeItem {
+  model_id: string;
+  family_key: string;
+  family: string;
+  provider: string;
+  tier: "cp" | "openai_list" | "global" | "us" | "in_region";
+  /** The AWS region of an In Region channel, else null. */
+  region: string | null;
+  /** channel: a new or left channel; price: a shown value; pending: a pending-review value; check: the source check. */
+  kind: "channel" | "price" | "pending" | "check";
+  field: PricingField | null;
+  /** price/pending: number or null; channel: "present" or null; check: "ok" or "skipped:<reason>". */
+  before: number | string | null;
+  after: number | string | null;
+}
+
+export type PricingChanges =
+  | { available: false; run_id: number | null }
+  | {
+      available: true;
+      run_id: number;
+      finished_at: string | null;
+      previous_run_id: number;
+      previous_finished_at: string | null;
+      items: PricingChangeItem[];
+    };
+
 export interface PricingResponse {
   currency: "USD";
   unit: "per_1m_tokens";
@@ -275,4 +308,52 @@ export interface PricingResponse {
   models: Record<string, PricingModelPrice>;
   references: PricingReference[];
   disclaimer: { en: string; ko: string };
+  /** Run-to-run table changes (v2.40.0); absent from an older backend. */
+  changes?: PricingChanges;
+}
+
+// ── Model Explorer verification (v2.40.0, GET /api/explorer/latest) ───────────
+
+export type ExplorerStatus = "passed" | "failed" | "skipped";
+
+export interface ExplorerResult {
+  status: ExplorerStatus;
+  latency_ms: number | null;
+  attempts: number;
+  /** failed: the exception line, then the stderr tail after the first newline; skipped: the reason. */
+  error_message: string | null;
+  output_excerpt: string | null;
+  run_id: number;
+  verified_at: string | null;
+  /** The example changed after this result was measured. */
+  stale_code: boolean;
+}
+
+export interface ExplorerExample {
+  api_id: "converse" | "invoke_model" | "messages" | "responses";
+  api: string;
+  label: string;
+  language: string;
+  description: { ko: string; en: string };
+  code: { ko: string; en: string };
+  code_sha: string;
+  result: ExplorerResult | null;
+}
+
+export interface ExplorerChange {
+  model_id: string;
+  model_name: string;
+  api_id: string;
+  api: string;
+  before: ExplorerStatus | null;
+  after: ExplorerStatus;
+  kind: "catalog" | "example" | "measured";
+}
+
+export interface ExplorerLatest {
+  run: { id: number; started_at: string | null; finished_at: string | null; totals: Record<ExplorerStatus, number> | null } | null;
+  running: boolean;
+  previous_run_id: number | null;
+  changes: ExplorerChange[];
+  models: Record<string, { examples: ExplorerExample[] }>;
 }
````
- [ ] **Step 3b:** Create `frontend/src/lib/explorerVerify.ts`:

````ts
// Model Explorer verification (v2.40.0, ADR-035) — pure view logic for /models over GET /api/explorer/latest:
// card badge summary, change labels, failure filter and the texts of a verification result. vitest covers it.
// The backend stores result messages in Korean ("출력 없음", "시간 초과 90초", skip reasons); `reasonText` gives the
// English text for the ones it knows and leaves an exception line as it is.

import type { ExplorerChange, ExplorerExample, ExplorerStatus } from "./types";

type Lang = "ko" | "en";

export type ModelGrade = "passed" | "failed" | "none";

export interface ModelSummary {
  passed: number;
  failed: number;
  skipped: number;
  total: number;
  grade: ModelGrade;
}

/** Counts of a model's examples by result; examples without a result count only in `total`. */
export function summarizeModel(examples: ExplorerExample[]): ModelSummary {
  const count = (status: ExplorerStatus) => examples.filter((example) => example.result?.status === status).length;
  const passed = count("passed");
  const failed = count("failed");
  const skipped = count("skipped");
  const grade: ModelGrade = failed > 0 ? "failed" : passed + skipped > 0 ? "passed" : "none";
  return { passed, failed, skipped, total: examples.length, grade };
}

/** Card badge: "✓ 3/3 통과", "✗ 1/3 실패", "검증 전", "✓ 2/3 통과, 1 건너뜀". */
export function badgeLabel(summary: ModelSummary, lang: Lang): string {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  if (summary.grade === "none") return L("Not verified", "검증 전");
  if (summary.grade === "failed") return L(`✗ ${summary.failed}/${summary.total} failed`, `✗ ${summary.failed}/${summary.total} 실패`);
  const skipped = summary.skipped > 0 ? L(`, ${summary.skipped} skipped`, `, ${summary.skipped} 건너뜀`) : "";
  return L(`✓ ${summary.passed}/${summary.total} passed${skipped}`, `✓ ${summary.passed}/${summary.total} 통과${skipped}`);
}

export function hasFailure(examples: ExplorerExample[]): boolean {
  return examples.some((example) => example.result?.status === "failed");
}

/** "통과" / "실패" / "건너뜀"; null (a cell the previous run did not have) is "신규". */
export function statusLabel(status: ExplorerStatus | null, lang: Lang): string {
  const labels: Record<ExplorerStatus, { en: string; ko: string }> = {
    passed: { en: "Passed", ko: "통과" },
    failed: { en: "Failed", ko: "실패" },
    skipped: { en: "Skipped", ko: "건너뜀" },
  };
  if (status === null) return lang === "en" ? "New" : "신규";
  return labels[status][lang];
}

const CHANGE_KIND: Record<ExplorerChange["kind"], { en: string; ko: string }> = {
  catalog: { en: "New", ko: "신규" },
  example: { en: "Example changed", ko: "예제 변경" },
  measured: { en: "Measured", ko: "실측" },
};

export function changeKindLabel(kind: ExplorerChange["kind"], lang: Lang): string {
  return CHANGE_KIND[kind][lang];
}

export function summarizeChanges(changes: ExplorerChange[]): Record<ExplorerChange["kind"], number> {
  const out = { catalog: 0, example: 0, measured: 0 };
  for (const change of changes) out[change.kind] += 1;
  return out;
}

export function changedModelIds(changes: ExplorerChange[]): Set<string> {
  return new Set(changes.map((change) => change.model_id));
}

/** A failed result's exception line and the stderr tail (after the first newline). */
export function splitError(message: string | null): { head: string; tail: string } {
  if (!message) return { head: "", tail: "" };
  const at = message.indexOf("\n");
  return at < 0 ? { head: message, tail: "" } : { head: message.slice(0, at), tail: message.slice(at + 1) };
}

/** The English text of the backend's Korean result messages; anything else (an exception line) is returned as is. */
export function reasonText(message: string, lang: Lang): string {
  if (lang === "ko") return message;
  if (message === "출력 없음") return "No output";
  if (message === "알 수 없는 플레이스홀더") return "Unknown placeholder";
  if (message === "런 시간 상한") return "Run time limit reached";
  const timeout = /^시간 초과 ([\d.]+)초$/.exec(message);
  if (timeout) return `Timed out after ${timeout[1]} s`;
  const missing = /^자격 증명 미주입: (.+)$/.exec(message);
  if (missing) return `Credentials not injected: ${missing[1]}`;
  return message;
}

/** "1.2초" / "1.2 s" — one decimal under a minute. */
export function formatLatency(ms: number | null, lang: Lang): string {
  if (ms === null || !Number.isFinite(ms)) return "";
  const seconds = (ms / 1000).toFixed(1);
  return lang === "en" ? `${seconds} s` : `${seconds}초`;
}
````
- [ ] **Step 4:** Run:

```bash
cd frontend && npx vitest run src/lib/explorerVerify.test.ts src/lib/pricingTable.test.ts
```

Expected: `Tests  75 passed (75)`.
- [ ] **Step 5:** Commit:

```bash
git add frontend/src/lib/types.ts \
  frontend/src/lib/api.ts \
  frontend/src/lib/pricingTable.ts \
  frontend/src/lib/explorerVerify.ts \
  frontend/src/lib/explorerVerify.test.ts \
  frontend/src/lib/pricingTable.test.ts
git commit -m "feat(frontend): explorer and price-change types, API client and pure view helpers"
```
---

### Task 9: `/models` — code from the API, verification header, banner, badges, filter and modal box

**Files:**
- Modify (replace): `frontend/src/components/ModelExplorer.tsx`
- Modify: `frontend/src/lib/modelExplorer.ts`, `frontend/src/lib/modelExplorer.test.ts` (remove `codeExamples`)
- Create: `frontend/e2e/explorerFixtures.ts`, `frontend/e2e/explorer.spec.ts`
- Modify: `frontend/e2e/fixtures.ts` (serve `/api/explorer/latest`), `frontend/e2e/catalog-benchmark.spec.ts` (explorer route for its catalogs)

**Interfaces:**
- Consumes: Task 8 types, API and helpers; `formatDuration` from `lib/claudeFeatures.ts`; `useAuth`, `useAsyncResource`, `DataError`, `Dialog`.
- Produces: DOM hooks the e2e reads — `[data-explorer-run]`, `[data-explorer-changes]` (a `<details>` with items or the no-change card), `[data-verify-badge]` (`passed`/`failed`/`none`), `[data-verify-changed]`, `[data-verify]` (`passed`/`failed`/`skipped`/`none`); e2e helpers `explorerExamples(id)`, `explorerResult(status, overrides)`, `explorerLatest(models, options)`.

The e2e explorer fixture builds examples per channel type in TypeScript instead of reading the backend golden: unit tests import `e2e/fixtures.ts`, and `next build` type-checks e2e files inside the frontend Docker context, which has no `backend/` (the v2.30.0 `.dockerignore` incident).
- [ ] **Step 1a:** Create `frontend/e2e/explorerFixtures.ts`:

````ts
import type { ExplorerChange, ExplorerExample, ExplorerLatest, ExplorerResult, ModelInfo } from "../src/lib/types";

// ── GET /api/explorer/latest (v2.40.0) ─────────────────────────────────────
// The real examples come from backend/model_explorer/examples.py (pinned by backend/tests/test_explorer_examples.py).
// This fixture only needs the shape the page reads: per channel type the same API tabs, and code that names the call
// region and the invoke model id, so the specs can check what the modal shows.

function nativeId(id: string): string {
  if (id.startsWith("anthropic:")) return id.slice("anthropic:".length);
  if (id.startsWith("openai:") || id.startsWith("bedrock:")) return id.split(":").slice(2).join(":");
  return id;
}

function example(api_id: ExplorerExample["api_id"], api: string, label: string, code: string): ExplorerExample {
  return {
    api_id, api, label, language: "python",
    description: { ko: `${api} 설명`, en: `${api} description` },
    code: { ko: `# 예제\n${code}`, en: `# Example\n${code}` },
    code_sha: `sha-${api_id}`,
    result: null,
  };
}

export function explorerExamples(id: string): ExplorerExample[] {
  const mid = nativeId(id);
  if (id.startsWith("anthropic:")) {
    return [example("messages", "Messages API", "Python (anthropic SDK)", `with client.messages.stream(model="${mid}") as stream:`)];
  }
  if (id.startsWith("openai:")) {
    return [example("responses", "Responses API", "Python (openai SDK)", `stream = client.responses.create(model="${mid}")`)];
  }
  const region = id.startsWith("bedrock:") ? id.split(":")[1] : id.startsWith("us") ? "us-east-1" : "ap-northeast-2";
  const converse = example("converse", "Converse API", "Python (boto3)",
    `client = boto3.client("bedrock-runtime", region_name="${region}")\nresponse = client.converse_stream(modelId="${mid}")`);
  if (!id.includes("anthropic")) return [converse];
  return [
    converse,
    example("invoke_model", "InvokeModel API", "Python (boto3)", `response = client.invoke_model(modelId="${mid}")`),
    example("messages", "Messages API", "Python (anthropic SDK)", `client = AnthropicBedrock(aws_region="${region}")`),
  ];
}

export function explorerResult(status: ExplorerResult["status"], overrides: Partial<ExplorerResult> = {}): ExplorerResult {
  return {
    status,
    latency_ms: 1180,
    attempts: status === "failed" ? 2 : 1,
    error_message: status === "failed" ? "KeyError: 'text'\nTraceback (most recent call last):\n  File \"example.py\", line 15"
      : status === "skipped" ? "자격 증명 미주입: OPENAI_1P_API_KEY" : null,
    output_excerpt: status === "passed" ? "Hello! How can I help you today?" : null,
    run_id: 12,
    verified_at: "2026-11-05T18:02:00Z",
    stale_code: false,
    ...overrides,
  };
}

/** A latest payload for these cards; `results` sets a result per "model id|api id". */
export function explorerLatest(models: ModelInfo[], options: {
  results?: Record<string, ExplorerResult>;
  changes?: ExplorerChange[];
  previousRunId?: number | null;
  run?: ExplorerLatest["run"];
  running?: boolean;
} = {}): ExplorerLatest {
  const results = options.results ?? {};
  const run = options.run === undefined
    ? { id: 12, started_at: "2026-11-05T18:00:00Z", finished_at: "2026-11-05T18:02:00Z", totals: { passed: 83, failed: 1, skipped: 1 } }
    : options.run;
  return {
    run,
    running: options.running ?? false,
    previous_run_id: options.previousRunId === undefined ? (run ? 11 : null) : options.previousRunId,
    changes: options.changes ?? [],
    models: Object.fromEntries(models.map((model) => [model.id, {
      examples: explorerExamples(model.id).map((ex) => ({ ...ex, result: results[`${model.id}|${ex.api_id}`] ?? null })),
    }])),
  };
}
````
- [ ] **Step 1b:** Create `frontend/e2e/explorer.spec.ts`:

````ts
import { expect, test, type Page } from "@playwright/test";
import { explorerLatest, explorerResult } from "./explorerFixtures";
import { mockApi } from "./fixtures";

// Model Explorer daily verification (v2.40.0, ADR-035): badges, run-to-run changes, the verification box and the
// fallback when /api/explorer/latest fails. All APIs are fixtures.

const OPUS = { id: "global.anthropic.claude-opus-5", name: "Bedrock Claude Opus 5 (Global)" };
const NOVA = { id: "us.amazon.nova-2-lite-v1:0", name: "Bedrock Nova 2.0 Lite (US)" };
const CP = { id: "anthropic:claude-sonnet-5-5", name: "Anthropic Claude Sonnet 5.5 (US)" };
const CATALOG = [CP, OPUS, NOVA];

const RESULTS = {
  [`${OPUS.id}|converse`]: explorerResult("passed"),
  [`${OPUS.id}|invoke_model`]: explorerResult("failed"),
  [`${OPUS.id}|messages`]: explorerResult("passed", { stale_code: true }),
  [`${NOVA.id}|converse`]: explorerResult("passed"),
};
const CHANGES = [
  { model_id: OPUS.id, model_name: OPUS.name, api_id: "invoke_model", api: "InvokeModel API", before: "passed" as const, after: "failed" as const, kind: "measured" as const },
  { model_id: "global.anthropic.claude-retired", model_name: "Bedrock Claude Retired (Global)", api_id: "converse", api: "Converse API", before: null, after: "passed" as const, kind: "catalog" as const },
];

async function mockExplorer(page: Page, body: unknown) {
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/latest", (route) => route.fulfill({ json: body }));
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
  await page.clock.setFixedTime(new Date("2026-11-05T20:00:00Z"));
});

test("cards show the verification badge and the change marker", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS, changes: CHANGES }));
  await page.goto("/models");
  const opus = page.getByRole("button", { name: OPUS.name, exact: true });
  await expect(opus.locator("[data-verify-badge]")).toHaveText("✗ 1/3 failed");
  await expect(opus.locator("[data-verify-badge]")).toHaveAttribute("data-verify-badge", "failed");
  await expect(opus.locator("[data-verify-changed]")).toHaveText("Changed");
  const nova = page.getByRole("button", { name: NOVA.name, exact: true });
  await expect(nova.locator("[data-verify-badge]")).toHaveText("✓ 1/1 passed");
  await expect(nova.locator("[data-verify-changed]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: CP.name, exact: true }).locator("[data-verify-badge]")).toHaveText("Not verified");
  await expect(page.locator("[data-explorer-run]")).toContainText("Last verification run #12");
  await expect(page.locator("[data-explorer-run]")).toContainText("passed 83, failed 1, skipped 1");
});

test("the change banner opens the model on the changed API tab and leaves a model off the page as text", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS, changes: CHANGES }));
  await page.goto("/models");
  const banner = page.locator("details[data-explorer-changes]");
  await expect(banner.locator("summary")).toHaveText("Changes since run #11: 2");
  await banner.locator("summary").click();
  await expect(banner).toContainText("New 1, example changed 0, measured 1");
  await expect(banner.getByRole("button", { name: "Bedrock Claude Retired (Global), Converse API" })).toBeDisabled();
  await banner.getByRole("button", { name: `${OPUS.name}, InvokeModel API` }).click();
  const dialog = page.getByRole("dialog", { name: OPUS.name, exact: true });
  await expect(dialog.getByRole("tab", { name: "InvokeModel API", exact: true })).toHaveAttribute("aria-selected", "true");
  const box = dialog.locator('[data-verify="failed"]');
  await expect(box).toContainText("Still failing after a retry");
  await expect(box).toContainText("KeyError: 'text'");
  await expect(box.getByText("Traceback (most recent call last):")).toBeHidden();
  await box.getByText("Error output", { exact: true }).click();
  await expect(box.getByText(/Traceback \(most recent call last\):/)).toBeVisible();
});

test("the modal shows a passing result with its output and a stale-code notice", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS }));
  await page.goto("/models");
  await page.getByRole("button", { name: OPUS.name, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: OPUS.name, exact: true });
  const passed = dialog.locator('[data-verify="passed"]');
  await expect(passed).toContainText("Verified, 1.2 s");
  await expect(passed).toContainText("(run #12)");
  await expect(passed).toContainText("Hello! How can I help you today?");
  await expect(dialog.getByRole("tabpanel")).toContainText('region_name="ap-northeast-2"');
  await dialog.getByRole("tab", { name: "Messages API", exact: true }).click();
  await expect(dialog.locator('[data-verify="passed"]')).toContainText("This example changed after the last verification (run #12).");
});

test("no previous run shows no banner, a run with no change shows the no-change card", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { previousRunId: null }));
  await page.goto("/models");
  await expect(page.getByRole("button", { name: OPUS.name, exact: true })).toBeVisible();
  await expect(page.locator("[data-explorer-changes]")).toHaveCount(0);
  await page.unroute("**/api/explorer/latest");
  await page.route("**/api/explorer/latest", (route) => route.fulfill({ json: explorerLatest(CATALOG) }));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.locator("[data-explorer-changes]")).toHaveText("No changes since run #11.");
});

test("failures only keeps the models with a failed example and the reset clears it", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS }));
  await page.goto("/models");
  const toggle = page.getByRole("button", { name: "Failures only", exact: true });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("1 / 3 models", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: OPUS.name, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: NOVA.name, exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Reset filters", exact: true }).click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByText("3 / 3 models", { exact: true })).toBeVisible();
});

test("an explorer API failure keeps the cards and retries inside the modal", async ({ page }) => {
  let fail = true;
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/latest", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fulfill({ json: explorerLatest(CATALOG, { results: RESULTS }) }));
  await page.goto("/models");
  const card = page.getByRole("button", { name: OPUS.name, exact: true });
  await expect(card).toBeVisible();
  await expect(card.locator("[data-verify-badge]")).toHaveCount(0);
  await card.click();
  const dialog = page.getByRole("dialog", { name: OPUS.name, exact: true });
  const alert = dialog.getByRole("alert").filter({ hasText: "code examples" });
  await expect(alert).toBeVisible();
  fail = false;
  await alert.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(dialog.getByRole("tab", { name: "Converse API", exact: true })).toBeVisible();
  await expect(dialog.locator('[data-verify="passed"]')).toBeVisible();
});

test("the run button asks a signed-out visitor to log in", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG));
  await page.goto("/models");
  await page.getByRole("button", { name: "Run verification", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Login", exact: true })).toBeVisible();
});

test("Korean copy at 390px without horizontal page scroll", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("lang", "ko"));
  await page.setViewportSize({ width: 390, height: 844 });
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS, changes: CHANGES }));
  await page.goto("/models");
  await expect(page.getByRole("button", { name: OPUS.name, exact: true }).locator("[data-verify-badge]")).toHaveText("✗ 1/3 실패");
  await expect(page.locator("details[data-explorer-changes] summary")).toHaveText("이전 런(#11) 대비 변경 2건");
  await expect(page.getByRole("button", { name: "검증 실패만", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
````
- [ ] **Step 1c:** Apply this change to `frontend/e2e/fixtures.ts`, `frontend/e2e/catalog-benchmark.spec.ts` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/frontend/e2e/catalog-benchmark.spec.ts b/frontend/e2e/catalog-benchmark.spec.ts
index ecd2546..f7ac338 100644
--- a/frontend/e2e/catalog-benchmark.spec.ts
+++ b/frontend/e2e/catalog-benchmark.spec.ts
@@ -1,5 +1,6 @@
 import { expect, test, type Page } from "@playwright/test";
 import type { GptBenchLatest, GptBenchTrend } from "../src/lib/api";
+import { explorerLatest } from "./explorerFixtures";
 import { mockApi } from "./fixtures";
 
 const catalog = [
@@ -56,6 +57,7 @@ test.beforeEach(async ({ page }) => {
   await mockApi(page);
   await page.addInitScript(() => localStorage.setItem("lang", "en"));
   await page.route("**/api/models", (route) => route.fulfill({ json: catalog }));
+  await page.route("**/api/explorer/latest", (route) => route.fulfill({ json: explorerLatest(catalog) }));
 });
 
 test("benchmark cards show all 18 channels grouped by generation", async ({ page }) => {
@@ -389,6 +391,7 @@ test("catalog details support keyboard tabs, copy feedback and focus return", as
 test("catalog shows a Seoul In-Region card with its own endpoint and the base model ID in code (v2.32.0)", async ({ page }) => {
   const inRegion = { id: "bedrock:ap-northeast-2:anthropic.claude-opus-5", name: "Bedrock Claude Opus 5 (ap-northeast-2)" };
   await page.route("**/api/models", (route) => route.fulfill({ json: [...catalog, inRegion] }));
+  await page.route("**/api/explorer/latest", (route) => route.fulfill({ json: explorerLatest([...catalog, inRegion]) }));
   await page.goto("/models");
   const card = page.getByRole("button", { name: inRegion.name, exact: true });
   await expect(card).toBeVisible();
diff --git a/frontend/e2e/fixtures.ts b/frontend/e2e/fixtures.ts
index b323d65..bf82e0b 100644
--- a/frontend/e2e/fixtures.ts
+++ b/frontend/e2e/fixtures.ts
@@ -1,4 +1,5 @@
 import type { Page } from "@playwright/test";
+import { explorerLatest } from "./explorerFixtures";
 import type {
   PricingFamily, PricingLongContext, PricingModelPrice, PricingReference, PricingResponse, PricingTier,
 } from "../src/lib/types";
@@ -285,6 +286,7 @@ export async function mockApi(page: Page) {
       "/api/auto-probe/categories": categories,
       "/api/insights/latest": null,
       "/api/pricing": pricingFixture,
+      "/api/explorer/latest": explorerLatest(modelCatalog),
     };
     const body = values[url.pathname];
     await route.fulfill({
````
- [ ] **Step 2:** Run:

```bash
cd frontend && npx playwright test e2e/explorer.spec.ts --project=chromium --reporter=line
```

Expected: the new specs fail (no `[data-verify-badge]`, no change banner, the modal still shows the frontend examples). The dev server starts on 127.0.0.1:3100; make sure nothing else listens there (`reuseExistingServer` would reuse it).
- [ ] **Step 3a:** Apply this change to `frontend/src/lib/modelExplorer.ts`, `frontend/src/lib/modelExplorer.test.ts` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/frontend/src/lib/modelExplorer.test.ts b/frontend/src/lib/modelExplorer.test.ts
index e2ea5df..4afedac 100644
--- a/frontend/src/lib/modelExplorer.test.ts
+++ b/frontend/src/lib/modelExplorer.test.ts
@@ -1,9 +1,10 @@
 /**
- * Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·코드 예제·링크를 유도하는
+ * Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·링크를 유도하는
  * 순수 로직 테스트. 7개 provider path의 키 스킴(ADR-019/020/027/031)을 고정한다.
+ * 코드 예제는 v2.40.0부터 백엔드가 만든다 — backend/tests/test_explorer_examples.py가 v2.39.0 출력과의 바이트 일치를 고정한다.
  */
 import { describe, expect, test } from "vitest";
-import { channelOf, nativeId, codeExamples, modelLinks } from "./modelExplorer";
+import { channelOf, nativeId, modelLinks } from "./modelExplorer";
 
 describe("channelOf — 7개 provider path 판별", () => {
   test("Bedrock Global 프로파일", () => {
@@ -98,97 +99,6 @@ describe("nativeId — 실제 호출에 쓰는 모델 ID", () => {
   });
 });
 
-describe("codeExamples — 채널에 맞는 SDK 예제 + API 종류 표기", () => {
-  test("Bedrock(Claude) → Converse + InvokeModel + Messages 세 탭, 각각 설명 포함", () => {
-    const ex = codeExamples("us.anthropic.claude-haiku-4-5-20251001-v1:0");
-    expect(ex.map((e) => e.api)).toEqual(["Converse API", "InvokeModel API", "Messages API"]);
-    expect(ex[0].code).toContain("converse_stream");
-    expect(ex[0].code).toContain("us.anthropic.claude-haiku-4-5-20251001-v1:0");
-    expect(ex[0].description.length).toBeGreaterThan(10); // API 의미 설명
-    expect(ex[1].code).toContain("invoke_model");
-    expect(ex[1].description).toContain("네이티브");
-    // Opus 5, Fable 5는 서명만 있는 thinking 블록이 content[0] — content[0]["text"]는 KeyError (2026-10-19 실측)
-    expect(ex[1].code).toContain('if b["type"] == "text"');
-    expect(ex[1].code).not.toContain('["content"][0]["text"]');
-    // Messages API — anthropic SDK의 AnthropicBedrock 클라이언트 (SigV4로 Bedrock 호출)
-    expect(ex[2].code).toContain("AnthropicBedrock");
-    expect(ex[2].code).toContain("us.anthropic.claude-haiku-4-5-20251001-v1:0");
-    expect(ex[2].description).toContain("Anthropic");
-    // Bedrock Mantle /anthropic 엔드포인트 병기 (bearer 토큰, 일부 리전) — 2026-07-11 실측 병기
-    expect(ex[2].description).toContain("Mantle");
-  });
-  test("Bedrock(Nova) → Converse API 단일 탭", () => {
-    const ex = codeExamples("us.amazon.nova-2-lite-v1:0");
-    expect(ex.map((e) => e.api)).toEqual(["Converse API"]);
-  });
-  test("Anthropic CP → Messages API 표기 + 설명", () => {
-    const ex = codeExamples("anthropic:claude-fable-5");
-    expect(ex[0].api).toBe("Messages API");
-    expect(ex[0].description).toContain("Anthropic");
-    expect(ex[0].code).toContain("aws-external-anthropic");
-    // CP는 anthropic-workspace-id 헤더만 받는다 — "anthropic-workspace"는 400 "Missing 'anthropic-workspace-id' header."
-    // (prober._anthropic_default_headers와 같은 이름, 2026-10-19 실측)
-    expect(ex[0].code).toContain('default_headers={"anthropic-workspace-id": "<ANTHROPIC_WORKSPACE_ID>"}');
-    expect(ex[0].code).toContain('"claude-fable-5"');
-  });
-  test("OpenAI Mantle → Responses API 표기", () => {
-    const ex = codeExamples("openai:us-east-2:openai.gpt-5.5");
-    expect(ex[0].api).toBe("Responses API");
-    expect(ex[0].description.length).toBeGreaterThan(10);
-    expect(ex[0].code).toContain("bedrock-mantle.us-east-2");
-    expect(ex[0].code).toContain("ABSK");
-  });
-  test("OpenAI 1P → Responses API 표기", () => {
-    const ex = codeExamples("openai:1p:gpt-5.5");
-    expect(ex[0].api).toBe("Responses API");
-    expect(ex[0].code).toContain("responses");
-    expect(ex[0].code).toContain('"gpt-5.5"');
-  });
-  test("OpenAI Global CRIS → Responses API + Seoul bedrock-runtime base_url", () => {
-    const ex = codeExamples("openai:global:global.openai.gpt-5.6-luna");
-    expect(ex[0].api).toBe("Responses API");
-    expect(ex[0].code).toContain("bedrock-runtime.ap-northeast-2");
-    expect(ex[0].code).not.toContain("bedrock-mantle.global"); // 존재하지 않는 호스트 회귀 방지
-    expect(ex[0].code).toContain("global.openai.gpt-5.6-luna");
-  });
-  test("OpenAI US CRIS → Responses API + us-east-1 bedrock-runtime base_url", () => {
-    const ex = codeExamples("openai:us:us.openai.gpt-6-astra");
-    expect(ex.map((e) => e.api)).toEqual(["Responses API"]);
-    expect(ex[0].code).toContain("bedrock-runtime.us-east-1");
-    expect(ex[0].code).not.toContain("bedrock-mantle."); // 존재하지 않는 호스트 회귀 방지
-    expect(ex[0].code).toContain('"us.openai.gpt-6-astra"');
-    expect(ex[0].code).toContain("ABSK");
-    expect(ex[0].description).toContain("cross-region");
-  });
-  test("Bedrock In-Region → 세 탭 모두 기본 모델 ID와 그 리전, 키 접두는 노출하지 않는다", () => {
-    const ex = codeExamples("bedrock:ap-northeast-2:anthropic.claude-sonnet-5");
-    expect(ex.map((e) => e.api)).toEqual(["Converse API", "InvokeModel API", "Messages API"]);
-    for (const e of ex) {
-      expect(e.code).toContain('"anthropic.claude-sonnet-5"');
-      expect(e.code).not.toContain("bedrock:");
-    }
-    expect(ex[0].code).toContain('region_name="ap-northeast-2"');
-    expect(ex[1].code).toContain('region_name="ap-northeast-2"');
-    expect(ex[2].code).toContain('AnthropicBedrock(aws_region="ap-northeast-2")');
-  });
-  // 프로파일은 prober _REGION_MAP과 같은 리전에서 호출한다 — us.* 를 ap-northeast-2에서 부르면
-  // "The provided model identifier is invalid" (Converse, InvokeModel, AnthropicBedrock 모두, 2026-10-19 실측)
-  test.each([
-    ["global.anthropic.claude-haiku-5-5", "ap-northeast-2"],
-    ["us.anthropic.claude-haiku-5-5", "us-east-1"],
-    ["us.anthropic.claude-opus-5", "us-east-1"],
-  ])("프로파일 %s의 세 탭은 %s에서 호출한다", (id, region) => {
-    const ex = codeExamples(id);
-    expect(ex[0].code).toContain(`region_name="${region}"`);
-    expect(ex[1].code).toContain(`region_name="${region}"`);
-    expect(ex[2].code).toContain(`AnthropicBedrock(aws_region="${region}")`);
-    expect(channelOf(id).endpoint).toBe(`https://bedrock-runtime.${region}.amazonaws.com`);
-  });
-  test("Nova US 프로파일도 us-east-1에서 호출한다", () => {
-    expect(codeExamples("us.amazon.nova-2-lite-v1:0")[0].code).toContain('region_name="us-east-1"');
-  });
-});
-
 describe("modelLinks — 문서·대시보드 링크", () => {
   test("Bedrock 모델은 AWS 문서·콘솔 링크 포함", () => {
     const links = modelLinks("global.anthropic.claude-fable-5", "Bedrock Claude Fable 5 (Global)");
@@ -225,17 +135,12 @@ describe("modelLinks — 문서·대시보드 링크", () => {
 });
 
 describe("i18n — lang 파라미터 (v2.16.2)", () => {
-  test("EN 선택 시 설명·링크 라벨·코드 주석이 영어로 출력된다", () => {
-    const ex = codeExamples("us.anthropic.claude-haiku-4-5-20251001-v1:0", "en");
-    expect(ex[0].description).toContain("unified");           // Converse 설명 영어
-    expect(ex[0].description).not.toContain("모니터");
-    expect(ex[2].code).toContain("no Anthropic API key");     // 코드 주석 영어
+  test("EN 선택 시 링크 라벨이 영어로 출력된다", () => {
     const links = modelLinks("global.anthropic.claude-fable-5", "Bedrock Claude Fable 5 (Global)", "en");
     expect(links[0].label).toContain("trend");
     expect(links.some((l) => l.label.includes("documentation") || l.label.includes("docs") || l.label.includes("Docs"))).toBe(true);
   });
   test("기본값(ko)은 기존 한국어 출력 유지", () => {
-    const ex = codeExamples("anthropic:claude-fable-5");
-    expect(ex[0].description).toContain("Anthropic 네이티브");
+    expect(modelLinks("anthropic:claude-fable-5", "Anthropic Claude Fable 5 (US)")[0].label).toBe("📈 이 모델 트렌드 보기");
   });
 });
diff --git a/frontend/src/lib/modelExplorer.ts b/frontend/src/lib/modelExplorer.ts
index 8aab00c..32522c0 100644
--- a/frontend/src/lib/modelExplorer.ts
+++ b/frontend/src/lib/modelExplorer.ts
@@ -1,4 +1,6 @@
-// Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·코드 예제·문서 링크를 유도.
+// Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·문서 링크를 유도.
+// 코드 예제는 v2.40.0부터 백엔드 단일 출처다(backend/model_explorer/examples.py, GET /api/explorer/latest — ADR-035):
+// 화면에 보이는 코드와 매일 검증 런이 실행하는 코드가 같은 함수에서 나온다.
 //
 // 7개 provider path의 키 스킴 (ADR-019/020/027, backend prober.py와 동일):
 //   global.* / us.*            → Bedrock inference profile (boto3 converse_stream)
@@ -10,7 +12,6 @@
 //   openai:us:us.openai.<m>    → OpenAI Bedrock US CRIS (openai SDK +
 //                                 us-east-1 bedrock-runtime OpenAI-compat base_url, v2.25.0)
 //   openai:1p:<m>              → OpenAI 1P direct (openai SDK + api.openai.com)
-// 코드 예제는 실제 prober가 쓰는 호출 방식과 일치시킨다 — 복붙해서 바로 동작하는 것이 목표.
 
 export type ChannelType = "bedrock" | "anthropic-cp" | "openai-mantle" | "openai-1p";
 
@@ -26,16 +27,6 @@ export interface ChannelInfo {
   badge: string;
 }
 
-export interface CodeExample {
-  label: string;
-  /** API 종류 표기 — Converse API / InvokeModel API / Messages API / Responses API */
-  api: string;
-  /** 이 API가 의미하는 바 (카드 상세에서 탭 아래 표시) */
-  description: string;
-  language: string;
-  code: string;
-}
-
 export interface ModelLink {
   label: string;
   url: string;
@@ -130,169 +121,6 @@ export function nativeId(modelId: string): string {
 
 export type ExplorerLang = "ko" | "en";
 
-export function codeExamples(modelId: string, lang: ExplorerLang = "ko"): CodeExample[] {
-  const ch = channelOf(modelId);
-  const id = nativeId(modelId);
-  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
-  const bedrockRegion = modelId.startsWith("bedrock:") ? ch.region : profileRegion(modelId);
-
-  if (ch.type === "bedrock") {
-    const converse: CodeExample = {
-      label: "Python (boto3)",
-      api: "Converse API",
-      description:
-        L("Bedrock unified conversation API — every Bedrock model is called with the same request shape, so you can swap models without code changes. Use converse_stream for streaming. This monitor's prober uses this API.", "Bedrock의 통합 대화 API — 모든 Bedrock 모델을 동일한 요청 형식으로 호출하므로 코드 수정 없이 모델을 교체할 수 있습니다. 스트리밍은 converse_stream을 사용합니다. 이 모니터의 prober도 이 API를 사용합니다."),
-      language: "python",
-      code: `import boto3
-
-client = boto3.client("bedrock-runtime", region_name="${bedrockRegion}")
-
-response = client.converse_stream(
-    modelId="${id}",
-    messages=[{"role": "user", "content": [{"text": "Hello!"}]}],
-    inferenceConfig={"maxTokens": 512},
-)
-for event in response["stream"]:
-    if "contentBlockDelta" in event:
-        print(event["contentBlockDelta"]["delta"].get("text", ""), end="")`,
-    };
-    // InvokeModel은 모델 네이티브 페이로드가 필요 — Claude(Anthropic) 모델에만 예제 제공.
-    if (!modelId.includes("anthropic")) {
-      return [converse];
-    }
-    return [
-      converse,
-      {
-        label: "Python (boto3)",
-        api: "InvokeModel API",
-        description:
-          L("Low-level API that passes the model-native payload as-is — use it to control model-specific schemas (Anthropic Messages format for Claude) and fine-grained parameters. Changing the model means changing the request body too.", "모델 네이티브 페이로드를 그대로 전달하는 저수준 API — 모델 고유 스키마(Claude는 Anthropic Messages 형식)와 세부 파라미터를 직접 제어할 때 사용합니다. 모델을 바꾸면 요청 본문도 함께 바꿔야 합니다."),
-        language: "python",
-        code: `import boto3, json
-
-client = boto3.client("bedrock-runtime", region_name="${bedrockRegion}")
-
-response = client.invoke_model(
-    modelId="${id}",
-    body=json.dumps({
-        "anthropic_version": "bedrock-2023-05-31",
-        "max_tokens": 512,
-        "messages": [{"role": "user", "content": "Hello!"}],
-    }),
-)
-result = json.loads(response["body"].read())
-${L("# Opus 5 and Fable 5 return a thinking block first — print only the text blocks", "# Opus 5, Fable 5는 thinking 블록을 먼저 돌려준다 — text 블록만 출력")}
-print("".join(b["text"] for b in result["content"] if b["type"] == "text"))`,
-      },
-      {
-        label: "Python (anthropic SDK)",
-        api: "Messages API",
-        description:
-          L("Use the Anthropic-native API on top of Bedrock — the anthropic SDK AnthropicBedrock client signs Messages-format requests with SigV4 and forwards them to Bedrock (no Anthropic API key; billing and IAM stay in your AWS account). Note: the Bedrock Mantle /anthropic endpoint (bearer token, some regions e.g. us-east-1) also accepts the same Messages format.", "Anthropic 네이티브 API를 Bedrock 위에서 그대로 쓰는 방식 — anthropic SDK의 AnthropicBedrock 클라이언트가 Messages 형식 요청을 SigV4로 서명해 Bedrock으로 전달합니다. Claude 전용 파라미터를 Anthropic 문서 그대로 사용하면서 과금·권한은 AWS 계정으로 관리할 때 사용합니다. 참고: Bedrock Mantle /anthropic 엔드포인트(bearer 토큰, us-east-1 등 일부 리전)로도 동일한 Messages 형식 호출이 가능합니다."),
-        language: "python",
-        code: `from anthropic import AnthropicBedrock
-
-${L("# Via Bedrock — AWS credentials (SigV4), no Anthropic API key required", "# Bedrock 경유 — AWS 자격 증명(SigV4) 사용, Anthropic API 키 불필요")}
-client = AnthropicBedrock(aws_region="${bedrockRegion}")
-
-with client.messages.stream(
-    model="${id}",
-    max_tokens=512,
-    messages=[{"role": "user", "content": "Hello!"}],
-) as stream:
-    for text in stream.text_stream:
-        print(text, end="")`,
-      },
-    ];
-  }
-
-  if (ch.type === "anthropic-cp") {
-    return [
-      {
-        label: "Python (anthropic SDK)",
-        api: "Messages API",
-        description:
-          L("Anthropic-native API — the most complete support for Claude-specific features (extended thinking, prompt caching, ...). Called here via the Claude Platform on AWS endpoint with a workspace header.", "Anthropic 네이티브 API — Claude 전용 기능(확장 사고, 프롬프트 캐싱 등)을 가장 완전하게 지원합니다. 여기서는 Claude Platform on AWS 엔드포인트와 workspace 헤더로 호출합니다."),
-        language: "python",
-        code: `from anthropic import Anthropic
-
-${L("# Claude Platform on AWS — vendor endpoint + workspace header", "# Claude Platform on AWS — vendor endpoint + workspace 헤더")}
-client = Anthropic(
-    api_key="<ANTHROPIC_API_KEY>",
-    base_url="${ch.endpoint}",
-    default_headers={"anthropic-workspace-id": "<ANTHROPIC_WORKSPACE_ID>"},
-)
-
-with client.messages.stream(
-    model="${id}",
-    max_tokens=512,
-    messages=[{"role": "user", "content": "Hello!"}],
-) as stream:
-    for text in stream.text_stream:
-        print(text, end="")`,
-      },
-    ];
-  }
-
-  if (ch.type === "openai-mantle") {
-    // Global/US CRIS는 같은 openai SDK 호출이지만 엔드포인트가 bedrock-runtime OpenAI-compat —
-    // 설명, 주석의 "Bedrock Mantle" 표기가 실제 경로와 어긋나지 않게 분기.
-    const isCris = modelId.startsWith("openai:global:") || modelId.startsWith("openai:us:");
-    return [
-      {
-        label: "Python (openai SDK)",
-        api: "Responses API",
-        description: isCris
-          ? L("OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Cross-region profiles (global.* and us.*) are served by the bedrock-runtime OpenAI-compatible endpoint (not the bedrock-mantle host); the call shape is identical and the key is a Bedrock bearer (ABSK-...).", "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. cross-region 프로파일(global.*, us.*)은 bedrock-runtime OpenAI 호환 엔드포인트로 호출합니다(bedrock-mantle 호스트 미지원). 호출 형식은 동일하며 키는 Bedrock bearer(ABSK-…)를 사용합니다.")
-          : L("OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Bedrock Mantle is an OpenAI-compatible endpoint, so the call shape is identical but the key is a Bedrock bearer (ABSK-...).", "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. Bedrock Mantle은 OpenAI 호환 엔드포인트라 동일한 형식으로 호출하되, 키는 Bedrock bearer(ABSK-…)를 사용합니다."),
-        language: "python",
-        code: `from openai import OpenAI
-
-${isCris
-  ? L("# Bedrock CRIS (cross-region profile) — bedrock-runtime OpenAI-compatible endpoint + Bedrock bearer key (ABSK-...)", "# Bedrock CRIS(cross-region 프로파일) — bedrock-runtime OpenAI 호환 엔드포인트 + Bedrock bearer 키(ABSK-…)")
-  : L("# Bedrock Mantle — OpenAI-compatible endpoint + Bedrock bearer key (ABSK-...)", "# Bedrock Mantle — OpenAI 호환 엔드포인트 + Bedrock bearer 키(ABSK-…)")}
-client = OpenAI(
-    api_key="<ABSK-...>",  # Bedrock long-term API key
-    base_url="${ch.endpoint}",
-)
-
-stream = client.responses.create(
-    model="${id}",
-    input="Hello!",
-    stream=True,
-)
-for event in stream:
-    if event.type == "response.output_text.delta":
-        print(event.delta, end="")`,
-      },
-    ];
-  }
-
-  // openai-1p
-  return [
-    {
-      label: "Python (openai SDK)",
-      api: "Responses API",
-      description:
-        L("OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Calls api.openai.com directly and requires an OpenAI platform key (sk-proj-...).", "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. api.openai.com 직접 호출이며 OpenAI platform 키(sk-proj-…)가 필요합니다."),
-      language: "python",
-      code: `from openai import OpenAI
-
-${L("# OpenAI 1P direct — platform key (sk-proj-...), not interchangeable with Mantle bearer", "# OpenAI 1P direct — platform 키(sk-proj-…), Mantle bearer와 호환 불가")}
-client = OpenAI(api_key="<OPENAI_API_KEY>")
-
-stream = client.responses.create(
-    model="${id}",
-    input="Hello!",
-    stream=True,
-)
-for event in stream:
-    if event.type == "response.output_text.delta":
-        print(event.delta, end="")`,
-    },
-  ];
-}
-
 export function modelLinks(modelId: string, modelName: string, lang: ExplorerLang = "ko"): ModelLink[] {
   const ch = channelOf(modelId);
   const L = (en: string, ko: string) => (lang === "en" ? en : ko);
````
- [ ] **Step 3b:** Replace `frontend/src/components/ModelExplorer.tsx` with:

````tsx
"use client";

import PageHeading from "./PageHeading";
import { useT as usePageCopy } from "@/lib/i18n-context";

// Model Explorer (v2.9.0) — 모니터링 중인 전체 모델 카드 그리드 + 상세 모달.
// 참조 UX: aws-samples Bedrock Central의 Explore Models (검색/필터 + 카드 + 상세).
// 카드 목록은 /api/models(공개)에서 — 모델 추가 시 자동 반영, 하드코딩 없음.
// 단가는 /api/pricing `models`를 페이지에서 한 번 받아 카드와 상세에 내려준다 (v2.30.0).
// 코드 예제와 매일 검증 결과는 /api/explorer/latest에서 온다 (v2.40.0, ADR-035): 예제를 만드는 함수가 백엔드
// 하나라 화면의 코드가 곧 검증 런이 실행한 코드다. 이 API가 실패해도 카드는 /api/models만으로 그리고, 상세 모달의
// 코드 영역만 재시도를 보여 준다.

import { useCallback, useId, useMemo, useRef, useState } from "react";
import { ExplorerExample, ExplorerLatest, ModelInfo, PricingModelPrice, PricingResponse } from "@/lib/types";
import { fetchExplorerLatest, fetchModels, fetchPricing, triggerExplorerRun } from "@/lib/api";
import { ApiError } from "@/lib/http";
import { useAuth } from "@/lib/auth-context";
import { useLang, useT } from "@/lib/i18n-context";
import { formatDateTime, parseTimestamp } from "@/lib/format";
import { formatDuration } from "@/lib/claudeFeatures";
import { formatUnitPrice, formatPricePair } from "@/lib/pricingTable";
import { sortResults, isExcludedModel } from "@/lib/sortModels";
import {
  badgeLabel, changedModelIds, changeKindLabel, formatLatency, hasFailure, reasonText, splitError, statusLabel,
  summarizeChanges, summarizeModel, type ModelGrade,
} from "@/lib/explorerVerify";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { DataEmpty, DataError, DataLoading } from "@/components/DataState";
import Dialog from "@/components/Dialog";
import ModelName from "@/components/ModelName";
import RefreshControls from "@/components/RefreshControls";
import {
  ChannelType,
  channelOf,
  modelLinks,
  nativeId,
} from "@/lib/modelExplorer";

type Lang = "ko" | "en";

const CHANNEL_FILTERS: { id: ChannelType | "all"; ko: string; en: string }[] = [
  { id: "all", ko: "전체", en: "All" },
  { id: "anthropic-cp", ko: "Anthropic CP", en: "Anthropic CP" },
  { id: "bedrock", ko: "Bedrock", en: "Bedrock" },
  { id: "openai-mantle", ko: "OpenAI Mantle", en: "OpenAI Mantle" },
  { id: "openai-1p", ko: "OpenAI 1P", en: "OpenAI 1P" },
];

const CHANNEL_BADGE: Record<ChannelType, string> = {
  "anthropic-cp": "bg-purple-500/10 border-purple-500/30 text-purple-300",
  bedrock: "bg-orange-500/10 border-orange-500/30 text-orange-300",
  "openai-mantle": "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  "openai-1p": "bg-teal-500/10 border-teal-500/30 text-teal-300",
};

const GRADE_BADGE: Record<ModelGrade, string> = {
  passed: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  failed: "bg-rose-500/10 border-rose-500/30 text-rose-300",
  none: "bg-gray-800 border-gray-700 text-gray-400",
};

const STALE_RUN_MS = 26 * 3_600_000;

function CopyButton({ text, label }: { text: string; label: string }) {
  const { lang } = useLang();
  const [result, setResult] = useState<{
    text: string; status: "copying" | "copied" | "error";
  } | null>(null);
  // Feedback belongs to the copied text, including when a different code tab opens.
  const status = result?.text === text ? result.status : "idle";
  const copy = async () => {
    setResult({ text, status: "copying" });
    try {
      await navigator.clipboard.writeText(text);
      setResult({ text, status: "copied" });
    } catch {
      setResult({ text, status: "error" });
    }
  };

  return (
    <div className="flex max-w-full flex-col items-start gap-1">
      <button type="button" onClick={() => void copy()} disabled={status === "copying"}
              aria-label={label} className="ui-button shrink-0">
        {status === "copying" ? (lang === "en" ? "Copying…" : "복사 중…")
          : status === "copied" ? (lang === "en" ? "✓ Copied" : "✓ 복사됨")
            : status === "error" ? (lang === "en" ? "Retry copy" : "다시 복사")
              : (lang === "en" ? "Copy" : "복사")}
      </button>
      <span role="status" aria-atomic="true"
            className={`text-[11px] leading-relaxed ${status === "error" ? "text-rose-400" : "text-gray-500"}`}>
        {status === "copied" ? (lang === "en" ? "Copied to clipboard." : "클립보드에 복사했습니다.")
          : status === "error" ? (lang === "en" ? "Copy failed. Select the text to copy manually." : "복사하지 못했습니다. 텍스트를 선택해 직접 복사하세요.")
            : ""}
      </span>
    </div>
  );
}

/** The verification box under an example's description (v2.40.0). */
function VerifyBox({ example, lang }: { example: ExplorerExample; lang: Lang }) {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const result = example.result;
  if (!result) {
    return (
      <p data-verify="none" className="mb-2 rounded-md border border-gray-800 bg-gray-950/50 p-2.5 text-xs text-gray-400">
        {L("Not verified yet.", "아직 검증하지 않았습니다.")}
      </p>
    );
  }
  const when = `${formatDateTime(result.verified_at, lang)} (${L("run", "런")} #${result.run_id})`;
  const stale = result.stale_code && (
    <p className="mt-1.5 text-amber-300">
      {L(`This example changed after the last verification (run #${result.run_id}). The next run verifies it again.`,
         `이 예제는 마지막 검증(런 #${result.run_id}) 뒤에 바뀌었습니다. 다음 런에서 다시 검증합니다.`)}
    </p>
  );
  if (result.status === "passed") {
    return (
      <div data-verify="passed" className="mb-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs text-emerald-300">
        <p>{L("Verified", "검증 통과")}, {formatLatency(result.latency_ms, lang)}, {when}</p>
        {result.output_excerpt && (
          <pre className="mt-1.5 whitespace-pre-wrap break-all font-mono text-[11px] text-gray-300">{result.output_excerpt}</pre>
        )}
        {stale}
      </div>
    );
  }
  const message = result.error_message ?? "";
  if (result.status === "skipped") {
    return (
      <div data-verify="skipped" className="mb-2 rounded-md border border-gray-700 bg-gray-950/50 p-2.5 text-xs text-gray-400">
        <p>{L("Skipped", "건너뜀")}: {reasonText(message, lang)}, {when}</p>
        {stale}
      </div>
    );
  }
  const { head, tail } = splitError(message);
  return (
    <div data-verify="failed" role="status" className="mb-2 rounded-md border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300">
      <p>
        {result.attempts > 1 ? L("Still failing after a retry", "다시 시도 뒤에도 실패") : L("Verification failed", "검증 실패")}, {when}
      </p>
      <p className="mt-1 break-all font-mono text-[11px] text-rose-200">{reasonText(head, lang)}</p>
      {tail && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-gray-400">{L("Error output", "오류 출력")}</summary>
          <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-gray-300">{tail}</pre>
        </details>
      )}
      {stale}
    </div>
  );
}

function DetailModal({ model, price, explorer, explorerError, explorerLoading, onRetryExplorer, initialApi, onClose }: {
  model: ModelInfo;
  price: PricingModelPrice | null;
  explorer: ExplorerLatest | null;
  explorerError: Error | null;
  explorerLoading: boolean;
  onRetryExplorer: () => void;
  initialApi: string | null;
  onClose: () => void;
}) {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const ch = channelOf(model.id);
  const examples = explorer?.models[model.id]?.examples ?? null;
  const links = modelLinks(model.id, model.name, lang === "en" ? "en" : "ko");
  const [tab, setTab] = useState(() => {
    const at = examples?.findIndex((example) => example.api_id === initialApi) ?? -1;
    return at < 0 ? 0 : at;
  });
  const tabsId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = examples && examples.length > 0 ? examples[Math.min(tab, examples.length - 1)] : null;
  const code = current ? current.code[lang] : "";

  return (
    <Dialog title={<ModelName name={model.name} />} onClose={onClose}>
        {/* 헤더 */}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2 py-0.5 text-[11px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
              {ch.label}
            </span>
          </div>
          <code className="mt-2 block text-xs text-blue-300 break-all">{model.id}</code>
        </div>

        {/* 모델 정보 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div className="min-w-0 bg-gray-950/50 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{L("Invoke model ID", "호출 모델 ID")}</div>
            <div className="flex flex-col items-start gap-2">
              <code className="text-gray-200 break-all">{nativeId(model.id)}</code>
              <CopyButton text={nativeId(model.id)} label={L("Copy model ID", "모델 ID 복사")} />
            </div>
            <div className="text-gray-500 pt-1">{L("Endpoint", "엔드포인트")}</div>
            <code className="text-gray-300 break-all">{ch.endpoint}</code>
            <div className="text-gray-500 pt-1">{L("Region", "리전")}</div>
            <div className="text-gray-300">{ch.region}</div>
          </div>
          <div className="min-w-0 bg-gray-950/50 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{L("Pricing (per 1M tokens)", "토큰 단가 (1M 기준)")}</div>
            {price ? (
              <div className="text-gray-200 tabular-nums">
                {L("Input", "입력")} <span className="font-semibold">{formatUnitPrice(price.input)}</span>
                {" / "}{L("Output", "출력")} <span className="font-semibold">{formatUnitPrice(price.output)}</span>
              </div>
            ) : (
              <div className="text-gray-500">{L("Pricing unavailable", "단가 정보 없음")}</div>
            )}
            <div className="text-gray-500 pt-2">{L("Links", "연결 링크")}</div>
            <ul className="space-y-1">
              {links.map((l) => (
                <li key={l.url}>
                  <a
                    href={l.url}
                    target={l.url.startsWith("/") ? undefined : "_blank"}
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline focus-visible:underline"
                  >
                    {l.label} {l.url.startsWith("/") ? "" : "↗"}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 코드 예제 — 백엔드 단일 출처 (v2.40.0) */}
        <div>
          <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
            <h3 className="text-sm font-semibold text-gray-200">{L("Code Examples", "코드 예제")}</h3>
            {current && <CopyButton text={code} label={L("Copy code example", "코드 예제 복사")} />}
          </div>
          {!explorer && explorerError && (
            <DataError error={explorerError} resource={L("code examples", "코드 예제")} onRetry={onRetryExplorer} />
          )}
          {!explorer && !explorerError && explorerLoading && <DataLoading />}
          {explorer && !current && (
            <p className="text-xs text-gray-400">{L("Could not load the code examples for this model.", "이 모델의 코드 예제를 불러오지 못했습니다.")}</p>
          )}
          {examples && current && (
            <>
              {/* API 종류 탭 — Converse / InvokeModel / Messages / Responses */}
              <div role="tablist" aria-label={L("Code example API", "코드 예제 API")} className="flex flex-wrap gap-1 mb-2">
                {examples.map((ex, i) => (
                  <button
                    key={ex.api_id}
                    ref={(element) => { tabRefs.current[i] = element; }}
                    type="button"
                    role="tab"
                    id={`${tabsId}-${i}`}
                    aria-controls={`${tabsId}-panel`}
                    aria-selected={current === ex}
                    tabIndex={current === ex ? 0 : -1}
                    onClick={() => setTab(i)}
                    onKeyDown={(event) => {
                      const next = event.key === "ArrowRight" ? (i + 1) % examples.length
                        : event.key === "ArrowLeft" ? (i - 1 + examples.length) % examples.length
                          : event.key === "Home" ? 0 : event.key === "End" ? examples.length - 1 : null;
                      if (next === null) return;
                      event.preventDefault();
                      setTab(next);
                      tabRefs.current[next]?.focus();
                    }}
                    className={current === ex ? "ui-button-primary" : "ui-button"}
                  >
                    {ex.api}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${examples.indexOf(current)}`} className="min-w-0">
                {/* 선택된 API가 의미하는 바 */}
                <p className="text-xs text-gray-400 leading-relaxed mb-2 bg-blue-500/10 border border-blue-500/20 rounded-md p-2.5">
                  <span className="font-semibold text-gray-200">{current.api}</span>
                  {" — "}
                  {current.description[lang]}
                </p>
                <VerifyBox example={current} lang={lang} />
                <div className="text-xs text-gray-500 mb-1">{current.label}</div>
                <pre tabIndex={0} aria-label={L(`${current.api} code example`, `${current.api} 코드 예제`)}
                     className="bg-gray-950 border border-gray-800 rounded-md p-3 overflow-x-auto text-xs text-gray-200 leading-relaxed ui-table-shell">
                  <code>{code}</code>
                </pre>
              </div>
            </>
          )}
        </div>
    </Dialog>
  );
}

export default function ModelExplorer() {
  const pageCopy = usePageCopy().workspace;
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const t = useT();
  const { user, openLogin } = useAuth();
  const resource = useAsyncResource<ModelInfo[]>("model-catalog", fetchModels);
  const pricing = useAsyncResource<PricingResponse>("pricing", fetchPricing);
  const explorerResource = useAsyncResource<ExplorerLatest>("explorer-latest", fetchExplorerLatest);
  const explorer = explorerResource.data;
  const prices = pricing.data?.models ?? null;
  const priceOf = (id: string): PricingModelPrice | null =>
    prices && Object.prototype.hasOwnProperty.call(prices, id) ? prices[id] : null;
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<ChannelType | "all">("all");
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [selected, setSelected] = useState<{ model: ModelInfo; api: string | null } | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState(false);
  const [triggering, setTriggering] = useState(false);

  const models = useMemo(() => sortResults(
    (resource.data ?? []).filter((model) => !isExcludedModel(model.name))
      .map((model) => ({ ...model, model_name: model.name })),
  ).map(({ id, name }) => ({ id, name })), [resource.data]);
  const examplesOf = useCallback((id: string) => explorer?.models[id]?.examples ?? [], [explorer]);
  const changed = useMemo(() => changedModelIds(explorer?.changes ?? []), [explorer]);
  const resetFilters = () => { setSearch(""); setChannel("all"); setFailuresOnly(false); };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return models.filter((m) => {
      if (channel !== "all" && channelOf(m.id).type !== channel) return false;
      if (q && !m.name.toLowerCase().includes(q) && !m.id.toLowerCase().includes(q)) return false;
      if (failuresOnly && !hasFailure(examplesOf(m.id))) return false;
      return true;
    });
  }, [models, search, channel, failuresOnly, examplesOf]);

  const run = explorer?.run ?? null;
  const duration = formatDuration(run?.started_at ?? null, run?.finished_at ?? null, lang);
  const changes = explorer?.changes ?? [];
  const changeSummary = summarizeChanges(changes);
  const byId = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);

  const handleTrigger = async () => {
    if (!user) { openLogin(); return; }
    setTriggering(true);
    setTriggerError(false);
    try {
      const response = await triggerExplorerRun();
      setTriggerMsg(response.triggered
        ? L("Verification started. Results refresh when it completes (about 2 minutes).", "검증을 시작했습니다. 완료 후 결과가 갱신됩니다(약 2분).")
        : t.monitoring.triggerBusy);
      await explorerResource.refresh();
    } catch (error) {
      setTriggerError(true);
      setTriggerMsg(L("Could not start verification. Try again shortly.", "검증을 시작하지 못했습니다. 잠시 후 다시 시도하세요."));
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) openLogin();
    } finally { setTriggering(false); }
  };

  return (
    <div className="page-stack">
      <PageHeading eyebrow={pageCopy.exploreWorkspace} title={<>
            {L("Model Explorer", "모델 탐색")}
          </>} description={<>

          <p className="text-sm text-gray-500 mt-1">
            {L("Select a model for invoke IDs, code examples, and links. Every code example runs once a day.",
               "모델을 선택하면 호출 ID, 코드 예제, 연결 링크를 볼 수 있습니다. 코드 예제는 매일 한 번 실제로 실행해 검증합니다.")}
          </p>
          {run && (
            <p data-explorer-run className="text-xs text-gray-500 mt-1 tabular-nums">
              {L("Last verification run", "최근 검증 런")} #{run.id}, {formatDateTime(run.finished_at, lang)}
              {duration && <>, {L("took", "소요")} {duration}</>}
              {run.totals && <>, {L("passed", "통과")} {run.totals.passed}, {L("failed", "실패")} {run.totals.failed}, {L("skipped", "건너뜀")} {run.totals.skipped}</>}
              {explorer?.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
          {!run && explorer?.running && (
            <p className="text-xs text-blue-400 mt-1">● {L("run in progress…", "런 실행 중…")}</p>
          )}
        </>}
        actions={<button type="button" onClick={handleTrigger} disabled={triggering || !!explorer?.running} className="ui-button-primary">
          {L("Run verification", "검증 런 실행")}
        </button>}
        >
        <div className="ui-toolbar justify-between"><RefreshControls
          refreshing={resource.refreshing || pricing.refreshing || explorerResource.refreshing}
          onRefresh={() => { void resource.refresh(); void pricing.refresh(); void explorerResource.refresh(); }}
          updatedAt={resource.updatedAt}
        /></div>
      </PageHeading>

      {triggerMsg && (
        <div role={triggerError ? "alert" : "status"}
             className={`rounded-xl border px-4 py-3 text-xs ${triggerError ? "border-amber-500/30 bg-amber-500/10 text-amber-300" : "border-blue-500/30 bg-blue-500/10 text-blue-300"}`}>
          {triggerMsg}
        </div>
      )}
      {run?.finished_at && Date.now() - (parseTimestamp(run.finished_at) ?? 0) > STALE_RUN_MS && (
        <p role="status" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
          {L("The last completed verification is over 26 hours old. These results may be out of date.", "마지막 완료된 검증이 26시간 이상 지났습니다. 현재 상태와 다를 수 있습니다.")}
        </p>
      )}

      {/* 이전 런 대비 변경 (v2.40.0) — Claude API 기능 검증과 같은 모양: 목록(10건 초과 '외 N건') 또는 '변경 없음' 카드 */}
      {run && explorer && explorer.previous_run_id != null && changes.length > 0 && (
        <details data-explorer-changes className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-gray-300">
          <summary className="text-sm font-semibold text-amber-300 mb-1 cursor-pointer">
            {L(`Changes since run #${explorer.previous_run_id}: ${changes.length}`, `이전 런(#${explorer.previous_run_id}) 대비 변경 ${changes.length}건`)}
          </summary>
          <div className="text-xs text-gray-400 mb-2">
            {L(`New ${changeSummary.catalog}, example changed ${changeSummary.example}, measured ${changeSummary.measured}`,
               `신규 ${changeSummary.catalog}건, 예제 변경 ${changeSummary.example}건, 실측 변경 ${changeSummary.measured}건`)}
          </div>
          <ul className="space-y-1">
            {changes.slice(0, 10).map((c) => {
              const target = byId.get(c.model_id);
              return (
                <li key={`${c.model_id}|${c.api_id}`} className="flex items-center gap-2 flex-wrap">
                  <span className={`px-1.5 py-px text-[11px] rounded ${c.kind === "measured" ? "bg-gray-800 text-gray-400" : "bg-sky-500/10 text-sky-300"}`}>
                    {changeKindLabel(c.kind, lang)}
                  </span>
                  <button type="button" disabled={!target} onClick={() => target && setSelected({ model: target, api: c.api_id })}
                          className={target ? "text-amber-200 hover:underline" : "text-gray-400 cursor-default"}>
                    {c.model_name}, {c.api}
                  </button>
                  <span className="text-gray-500">:</span>
                  <span className={c.before ? "text-gray-300" : "text-gray-500"}>{statusLabel(c.before, lang)}</span>
                  <span className="text-gray-500">→</span>
                  <span className="text-gray-300">{statusLabel(c.after, lang)}</span>
                </li>
              );
            })}
            {changes.length > 10 && <li className="text-gray-500">{L(`+${changes.length - 10} more`, `외 ${changes.length - 10}건`)}</li>}
          </ul>
        </details>
      )}
      {run && explorer && explorer.previous_run_id != null && changes.length === 0 && (
        <div data-explorer-changes className="ui-panel px-3 py-2 text-xs text-gray-500">
          {L(`No changes since run #${explorer.previous_run_id}.`, `이전 런(#${explorer.previous_run_id}) 대비 변경 없음.`)}
        </div>
      )}

      {/* 검색 + 채널 필터 + 검증 실패만 */}
      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex w-full flex-col gap-2 sm:w-64">
          <span className="text-xs font-medium text-gray-400">{L("Search models", "모델 검색")}</span>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={L("Model name or ID", "모델 이름 또는 ID")}
            className="ui-input w-full"
          />
        </label>
        <div role="group" aria-label={L("Channel filter", "채널 필터")} className="flex gap-1 flex-wrap">
          {CHANNEL_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setChannel(f.id)}
              aria-pressed={channel === f.id}
              className={channel === f.id ? "ui-button-primary" : "ui-button"}
            >
              {lang === "en" ? f.en : f.ko}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => setFailuresOnly((value) => !value)} aria-pressed={failuresOnly}
                className={failuresOnly ? "ui-button-primary" : "ui-button"}>
          {L("Failures only", "검증 실패만")}
        </button>
        <button type="button" onClick={resetFilters} disabled={search === "" && channel === "all" && !failuresOnly} className="ui-button">
          {t.common.resetFilters}
        </button>
        {resource.data !== null && (
          <span aria-live="polite" aria-atomic="true" className="self-center text-xs text-gray-500">
            {L(`${filtered.length} / ${models.length} models`, `모델 ${filtered.length} / ${models.length}개`)}
          </span>
        )}
      </div>

      <DataError error={resource.error} resource={L("model catalog", "모델 카탈로그")}
                 onRetry={resource.refresh} hasData={models.length > 0} />
      <DataError error={pricing.error} resource={L("unit prices", "비용 단가")}
                 onRetry={pricing.refresh} hasData={prices !== null} />
      <DataError error={explorerResource.error} resource={L("verification results", "검증 결과")}
                 onRetry={explorerResource.refresh} hasData={explorer !== null} />
      {resource.loading && <DataLoading />}
      {!resource.error && resource.data !== null && models.length === 0 && (
        <DataEmpty title={L("No models available.", "등록된 모델이 없습니다.")}
                   description={L("The catalog is empty. Refresh to check for newly registered models.", "카탈로그가 비어 있습니다. 새로고침으로 모델 등록 여부를 확인하세요.")} />
      )}
      {!resource.error && models.length > 0 && filtered.length === 0 && (
        <DataEmpty title={L("No models match these filters.", "검색 조건에 맞는 모델이 없습니다.")}
                   description={L("Change your search or reset the filters to see all models.", "검색어를 바꾸거나 필터를 초기화하면 전체 모델을 볼 수 있습니다.")} />
      )}

      {/* 카드 그리드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((m) => {
          const ch = channelOf(m.id);
          const price = priceOf(m.id);
          const summary = summarizeModel(examplesOf(m.id));
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setSelected({ model: m, api: null })}
              aria-label={m.name}
              aria-haspopup="dialog"
              aria-expanded={selected?.model.id === m.id}
              className="ui-panel w-full min-w-0 text-left hover:border-blue-500/50 focus-visible:border-blue-500/50 transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-gray-100 group-hover:text-blue-300 group-focus-visible:text-blue-300 transition-colors">
                  <ModelName name={m.name} />
                </h3>
                <span className={`shrink-0 px-2 py-0.5 text-[11px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
                  {ch.badge}
                </span>
              </div>
              <code className="block text-xs text-gray-500 break-all mt-1.5">{m.id}</code>
              <div className="text-xs text-gray-500 mt-2 tabular-nums">
                {price
                  ? `${formatPricePair(price)} ${L("(per 1M tokens, in/out)", "(1M 토큰당 입력/출력)")}`
                  : pricing.loading ? L("Loading prices…", "단가 불러오는 중…")
                    : L("Pricing unavailable", "단가 정보 없음")}
              </div>
              {explorer && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span data-verify-badge={summary.grade}
                        className={`px-2 py-0.5 text-[11px] font-medium rounded-full border ${GRADE_BADGE[summary.grade]}`}>
                    {badgeLabel(summary, lang)}
                  </span>
                  {changed.has(m.id) && (
                    <span data-verify-changed className="px-2 py-0.5 text-[11px] font-medium rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-300">
                      {L("Changed", "변경")}
                    </span>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {selected && (
        <DetailModal key={`${selected.model.id}|${selected.api ?? ""}`} model={selected.model} price={priceOf(selected.model.id)}
                     explorer={explorer} explorerError={explorerResource.error} explorerLoading={explorerResource.loading}
                     onRetryExplorer={() => void explorerResource.refresh()} initialApi={selected.api}
                     onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
````
- [ ] **Step 4:** Run:

```bash
cd frontend && npx vitest run && npx playwright test e2e/explorer.spec.ts e2e/catalog-benchmark.spec.ts e2e/channel-labels.spec.ts e2e/visibility.spec.ts e2e/monitoring.spec.ts --project=chromium --reporter=line
```

Expected: vitest all green; Playwright all pass (8 new explorer specs; the catalog modal still has the Converse and InvokeModel tabs and `client.invoke_model`, the Seoul In-Region card shows `region_name="ap-northeast-2"` and `modelId="anthropic.claude-opus-5"`). `npm run typecheck` still fails only on `PricingPanel.tsx` `BADGE_CLASS`/`BADGE_WRAP` (fixed in Task 10).
- [ ] **Step 5:** The dev server rewrites `frontend/next-env.d.ts` (`./.next/dev/types/…`). Restore it before committing: `git checkout -- frontend/next-env.d.ts`.
- [ ] **Step 6:** Commit:

```bash
git add frontend/src/components/ModelExplorer.tsx \
  frontend/src/lib/modelExplorer.ts \
  frontend/src/lib/modelExplorer.test.ts \
  frontend/e2e/explorerFixtures.ts \
  frontend/e2e/explorer.spec.ts \
  frontend/e2e/fixtures.ts \
  frontend/e2e/catalog-benchmark.spec.ts
git commit -m "feat(models): code examples from the backend with the daily verification result and run-to-run changes"
```
---

### Task 10: `/pricing` — change banner, cell ids, highlight and badges

**Files:**
- Modify: `frontend/src/components/PricingPanel.tsx`
- Create: `frontend/e2e/pricing-changes.spec.ts`

**Interfaces:**
- Consumes: Task 8 helpers (`cellChangeBadge`, `changeItemText`, `changeKindTag`, `changeTagLabel`, `priceCellId`) and types.
- Produces: `PricingContent` props `highlightCell?: string | null`, `onCellJump?: (cellId) => void` (both optional, so `PricingPanel.test.tsx` keeps rendering it unchanged); DOM hooks `[data-price-changes]` (`unavailable`/`none`/`list`), `[data-change-tag]`, price cells `id="price-<family_key>-<tier>"` with `data-highlighted`, badges `[data-badge="changed"]` / `[data-badge="new_channel"]`.
- [ ] **Step 1:** Create `frontend/e2e/pricing-changes.spec.ts`:

````ts
import { expect, test, type Page } from "@playwright/test";
import type { PricingChangeItem, PricingChanges } from "../src/lib/types";
import { mockApi, pricingFixture } from "./fixtures";

// /pricing run-to-run changes (v2.40.0, ADR-035): the banner's three states, an item that scrolls to and highlights its
// cell, the cell badge, and a removed channel that stays text. pricing.spec.ts covers the table itself.

function item(over: Partial<PricingChangeItem>): PricingChangeItem {
  return {
    model_id: "us.anthropic.claude-opus-5-5", family_key: "claude-opus-5-5", family: "Claude Opus 5.5", provider: "anthropic",
    tier: "us", region: null, kind: "price", field: "cache_read", before: 0.44, after: 0.22, ...over,
  };
}

const LIST: PricingChanges = {
  available: true, run_id: 13, finished_at: "2026-09-26T15:00:31Z", previous_run_id: 12, previous_finished_at: "2026-09-26T03:00:29Z",
  items: [
    item({}),
    item({ model_id: "openai:global:global.openai.gpt-6-astra", family_key: "gpt-6-astra", family: "GPT 6 Astra", provider: "openai",
           tier: "global", kind: "pending", field: "input", before: null, after: 11 }),
    item({ model_id: "global.anthropic.claude-gone", family_key: "claude-gone", family: "Claude Gone", tier: "global",
           kind: "channel", field: null, before: "present", after: null }),
  ],
};

async function withChanges(page: Page, changes: PricingChanges) {
  await page.route("**/api/pricing", (route) => route.fulfill({ json: { ...pricingFixture, changes } }));
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.clock.setFixedTime(new Date("2026-09-26T12:00:00Z"));
});

test("before two snapshot runs the banner says changes start with the next sync", async ({ page }) => {
  await withChanges(page, { available: false, run_id: 13 });
  await page.goto("/pricing");
  await expect(page.locator('[data-price-changes="unavailable"]')).toHaveText("변경 비교는 다음 동기화부터 표시됩니다.");
});

test("no change is a sentence, not an empty space", async ({ page }) => {
  await withChanges(page, { ...LIST, items: [] });
  await page.goto("/pricing");
  await expect(page.locator('[data-price-changes="none"]')).toContainText("이전 동기화(#12, ");
  await expect(page.locator('[data-price-changes="none"]')).toContainText("대비 변경 없음.");
});

test("an older backend without changes shows no banner", async ({ page }) => {
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "비용 단가", level: 1, exact: true })).toBeVisible();
  await expect(page.locator("[data-price-changes]")).toHaveCount(0);
});

test("the list tags each change, jumps to its cell and badges the cell", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await withChanges(page, LIST);
  await page.goto("/pricing");
  const banner = page.locator('details[data-price-changes="list"]');
  await expect(banner.locator("summary")).toContainText("대비 변경 3건");
  await banner.locator("summary").click();
  await expect(banner.locator("[data-change-tag]")).toHaveText(["적용", "검토 대기", "제외 채널"]);
  await expect(banner.getByText("Claude Gone, AWS Bedrock - Global CRIS", { exact: true })).toBeVisible();
  await expect(banner.getByRole("button", { name: /Claude Gone/ })).toHaveCount(0);

  const cell = page.locator("#price-claude-opus-5-5-us");
  await expect(cell.locator('[data-badge="changed"]')).toHaveText("이전 대비 변경");
  await expect(cell.locator('[data-badge-detail="changed"]')).toHaveText("캐시 읽기 $0.44 → $0.22");
  await expect(page.locator("#price-gpt-6-astra-global [data-badge-detail=\"changed\"]")).toHaveText("검토 대기: 입력 — → $11.00");
  await expect(cell).toHaveAttribute("data-highlighted", "false");
  await banner.getByRole("button", { name: "Claude Opus 5.5, AWS Bedrock - US CRIS, 캐시 읽기 $0.44 → $0.22" }).click();
  await expect(cell).toHaveAttribute("data-highlighted", "true");
  await expect(cell).toBeInViewport();
  await expect(cell).toHaveAttribute("data-highlighted", "false", { timeout: 3000 });  // 1.5 s highlight
});

test("the banner fits a 390px phone without horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await withChanges(page, LIST);
  await page.goto("/pricing");
  await page.locator('details[data-price-changes="list"] summary').click();
  await expect(page.locator('details[data-price-changes="list"] li')).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
````
- [ ] **Step 2:** Run:

```bash
cd frontend && npx playwright test e2e/pricing-changes.spec.ts --project=chromium --reporter=line
```

Expected: 4 of 5 fail (no `[data-price-changes]`, no `#price-…` ids); "an older backend without changes shows no banner" passes.
- [ ] **Step 3:** Apply this change to `frontend/src/components/PricingPanel.tsx` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/frontend/src/components/PricingPanel.tsx b/frontend/src/components/PricingPanel.tsx
index deb6dc9..7b9cf8b 100644
--- a/frontend/src/components/PricingPanel.tsx
+++ b/frontend/src/components/PricingPanel.tsx
@@ -16,17 +16,20 @@ import { useT as usePageCopy } from "@/lib/i18n-context";
 // 모델 ID는 "모델 ID 보기" 토글로 보여 준다. 폰에서는 표만 가로로 스크롤되므로 표 위 안내와 오른쪽 가장자리 흐림으로 알린다.
 // 한글 문장은 break-keep(어절 단위 줄바꿈), 리전 id, 날짜, 가격 쌍, 캐시 항목, 두 조각 열 이름의 조각, 배지, 각주는 토큰
 // 중간에서 줄이 바뀌지 않는다. " - "가 없는 열 이름(Claude Platform on AWS, OpenAI 공식 가격)은 단어 사이에서 줄이 바뀐다.
+// 이전 동기화 대비 변경(v2.40.0, ADR-035): 마지막 동기화 상자 아래 배너가 `changes` 항목을 보여 주고, 항목을 누르면
+// 그 단가 셀(id="price-<family_key>-<tier>")로 스크롤해 1.5초 강조한다. 바뀐 셀에는 "이전 대비 변경" 배지가 붙는다.
 
 import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
 import { fetchPricing, pricingExportUrl } from "@/lib/api";
 import { formatDateTime } from "@/lib/format";
 import { useLang } from "@/lib/i18n-context";
 import {
-  cacheItems, columnsFor, formatPricePair, headerParts, longItems, notesForTier, textRuns, tierBadges, tierLabel,
-  type PriceItem, type PricingBadge, type PricingTierKey,
+  cacheItems, cellChangeBadge, changeItemText, changeKindTag, changeTagLabel, columnsFor, formatPricePair, headerParts,
+  longItems, notesForTier, priceCellId, textRuns, tierBadges, tierLabel,
+  type PriceItem, type PricingBadge, type PricingChangeTag, type PricingTierKey,
 } from "@/lib/pricingTable";
 import type {
-  PricingFamily, PricingInRegionTier, PricingReference, PricingResponse, PricingTier,
+  PricingChangeItem, PricingChanges, PricingFamily, PricingInRegionTier, PricingReference, PricingResponse, PricingTier,
 } from "@/lib/types";
 import { useAsyncResource } from "@/hooks/useAsyncResource";
 import { DataEmpty, DataError, DataLoading } from "./DataState";
@@ -112,6 +115,8 @@ const BADGE_CLASS: Record<PricingBadge["kind"], string> = {
   promo: "border-purple-500/40 bg-purple-500/10 text-purple-300",
   promo_check: "border-rose-500/40 bg-rose-500/10 text-rose-300",
   doc_conflict: "border-orange-500/40 bg-orange-500/10 text-orange-300",
+  changed: "border-amber-500/40 bg-amber-500/10 text-amber-300",
+  new_channel: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
 };
 // Short labels never wrap. Promotion labels are longer than a phone-width column in English, so they wrap only between
 // words (their date stays whole).
@@ -121,6 +126,17 @@ const BADGE_WRAP: Record<PricingBadge["kind"], string> = {
   promo: "break-keep",
   promo_check: "break-keep",
   doc_conflict: "whitespace-nowrap",
+  changed: "whitespace-nowrap",
+  new_channel: "whitespace-nowrap",
+};
+const CHANGE_TAG_CLASS: Record<PricingChangeTag, string> = {
+  applied: "bg-amber-500/10 text-amber-300",
+  pending: "bg-sky-500/10 text-sky-300",
+  released: "bg-gray-800 text-gray-400",
+  check_failed: "bg-rose-500/10 text-rose-300",
+  check_recovered: "bg-emerald-500/10 text-emerald-300",
+  new_channel: "bg-emerald-500/10 text-emerald-300",
+  left_channel: "bg-gray-800 text-gray-400",
 };
 
 /** Text whose price pairs and hyphenated tokens never wrap inside; `tail` (a footnote, "↗") stays with the last word. */
@@ -341,7 +357,7 @@ function HeaderLabel({ text }: { text: string }) {
   );
 }
 
-function TierCell({ family, tierKey, lang, today, refNumbers, showModelIds, onFootnote }: {
+function TierCell({ family, tierKey, lang, today, refNumbers, showModelIds, onFootnote, changes, highlighted }: {
   family: PricingFamily;
   tierKey: PricingTierKey;
   lang: Lang;
@@ -349,22 +365,32 @@ function TierCell({ family, tierKey, lang, today, refNumbers, showModelIds, onFo
   refNumbers: ReadonlyMap<string, number>;
   showModelIds: boolean;
   onFootnote: (n: number) => void;
+  changes: PricingChangeItem[];
+  highlighted: boolean;
 }) {
   const single = tierKey === "in_region" ? null : family.tiers[tierKey];
   const entries: (PricingTier | PricingInRegionTier)[] = tierKey === "in_region"
     ? family.tiers.in_region
     : single ? [single] : [];
+  const changeBadge = cellChangeBadge(changes, family.family_key, tierKey, lang);
+  const cellProps = {  // data-tier stays the first attribute (PricingPanel.test reads the markup)
+    "data-tier": tierKey,
+    id: priceCellId(family.family_key, tierKey),
+    "data-highlighted": highlighted ? "true" : "false",
+    className: `${CELL} scroll-mt-36 transition-colors ${highlighted ? "bg-blue-500/15 ring-1 ring-inset ring-blue-500/40" : ""}`,
+  };
   if (entries.length === 0) {
     return (
-      <td data-tier={tierKey} className={CELL}>
+      <td {...cellProps}>
         <span aria-hidden="true" className="text-gray-600">—</span>
         <span className="sr-only">{lang === "en" ? "No price" : "단가 없음"}</span>
+        {changeBadge && <Badges badges={[changeBadge]} lang={lang} refNumbers={refNumbers} onFootnote={onFootnote} />}
       </td>
     );
   }
   const notes = notesForTier(family.notes, tierKey);
   return (
-    <td data-tier={tierKey} className={CELL}>
+    <td {...cellProps}>
       <div className="space-y-2">
         {entries.map((entry) => (
           <div key={entry.model_ids.join(" ")} data-price-line>
@@ -379,11 +405,81 @@ function TierCell({ family, tierKey, lang, today, refNumbers, showModelIds, onFo
             <Badges badges={tierBadges(entry, notes, lang, today)} lang={lang} refNumbers={refNumbers} onFootnote={onFootnote} />
           </div>
         ))}
+        {changeBadge && <Badges badges={[changeBadge]} lang={lang} refNumbers={refNumbers} onFootnote={onFootnote} />}
       </div>
     </td>
   );
 }
 
+/**
+ * The run-to-run change banner under the last sync line (v2.40.0): a gray note before two runs with a snapshot exist,
+ * "변경 없음" when nothing changed, otherwise an amber list (10 items, then "외 N건"). An item whose cell is on the page
+ * is a button that scrolls to the cell; a removed channel has no cell and stays text.
+ */
+function ChangesBanner({ changes, families, lang, onJump }: {
+  changes: PricingChanges | undefined;
+  families: PricingFamily[];
+  lang: Lang;
+  onJump: (cellId: string) => void;
+}) {
+  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
+  if (!changes) return null;
+  if (!changes.available) {
+    return (
+      <p data-price-changes="unavailable" className="ui-panel px-3 py-2 text-xs text-gray-500">
+        {L("Changes are shown from the next price sync.", "변경 비교는 다음 동기화부터 표시됩니다.")}
+      </p>
+    );
+  }
+  const since = L(
+    `the previous sync (#${changes.previous_run_id}, ${formatDateTime(changes.previous_finished_at, lang)})`,
+    `이전 동기화(#${changes.previous_run_id}, ${formatDateTime(changes.previous_finished_at, lang)})`,
+  );
+  if (changes.items.length === 0) {
+    return (
+      <p data-price-changes="none" className="ui-panel px-3 py-2 text-xs text-gray-500">
+        {L(`No changes since ${since}.`, `${since} 대비 변경 없음.`)}
+      </p>
+    );
+  }
+  const onPage = (item: PricingChangeItem) => {
+    if (item.kind === "channel" && item.after === null) return false;
+    const family = families.find((f) => f.family_key === item.family_key);
+    return !!family && columnsFor(family.provider).includes(item.tier);
+  };
+  return (
+    <details data-price-changes="list" className={`rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-gray-300 ${PROSE}`}>
+      <summary className="mb-1 cursor-pointer text-sm font-semibold text-amber-300">
+        {L(`Changes since ${since}: ${changes.items.length}`, `${since} 대비 변경 ${changes.items.length}건`)}
+      </summary>
+      <ul className="space-y-1">
+        {changes.items.slice(0, 10).map((item) => {
+          const tag = changeKindTag(item);
+          const text = changeItemText(item, lang);
+          return (
+            <li key={`${item.model_id}|${item.kind}|${item.field ?? ""}`} className="flex flex-wrap items-baseline gap-2">
+              <span data-change-tag={tag} className={`whitespace-nowrap rounded px-1.5 py-px text-[11px] ${CHANGE_TAG_CLASS[tag]}`}>
+                {changeTagLabel(tag, lang)}
+              </span>
+              {onPage(item) ? (
+                <button type="button" onClick={() => onJump(priceCellId(item.family_key, item.tier))}
+                        className="text-left text-amber-200 hover:underline">
+                  <Runs text={text} />
+                </button>
+              ) : (
+                <span className="text-gray-400"><Runs text={text} /></span>
+              )}
+            </li>
+          );
+        })}
+        {changes.items.length > 10 && (
+          <li className="text-gray-500">{L(`+${changes.items.length - 10} more`, `외 ${changes.items.length - 10}건`)}</li>
+        )}
+      </ul>
+    </details>
+  );
+}
+
 function ReferenceItem({ reference, lang, highlighted }: { reference: PricingReference; lang: Lang; highlighted: boolean }) {
   const title = lang === "en" ? reference.title_en : reference.title_ko;
   return (
@@ -416,18 +512,21 @@ function ReferenceItem({ reference, lang, highlighted }: { reference: PricingRef
  * Everything below the page heading once /api/pricing has answered. No fetching, so vitest renders it statically
  * (the model-ID toggle starts off and the scroll cue starts hidden until the browser measures the table).
  */
-export function PricingContent({ data, lang, today, highlight, onFootnote }: {
+export function PricingContent({ data, lang, today, highlight, onFootnote, highlightCell = null, onCellJump = () => {} }: {
   data: PricingResponse;
   lang: Lang;
   today: Date;
   highlight: number | null;
   onFootnote: (n: number) => void;
+  highlightCell?: string | null;
+  onCellJump?: (cellId: string) => void;
 }) {
   const L = (en: string, ko: string) => (lang === "en" ? en : ko);
   const sync = data.last_sync;
   const syncStatus = sync ? SYNC_STATUS[sync.status] ?? { en: sync.status, ko: sync.status } : null;
   const [showModelIds, setShowModelIds] = useState(false);
   const refNumbers = useMemo(() => new Map(data.references.map((reference) => [reference.id, reference.n])), [data.references]);
+  const changeItems = data.changes?.available ? data.changes.items : [];
   return (
     <>
       <div
@@ -493,6 +592,8 @@ export function PricingContent({ data, lang, today, highlight, onFootnote }: {
         </div>
       </div>
 
+      <ChangesBanner changes={data.changes} families={data.families} lang={lang} onJump={onCellJump} />
+
       {data.families.length === 0 && (
         <DataEmpty
           title={L("No unit prices yet.", "표시할 단가가 없습니다.")}
@@ -548,6 +649,7 @@ export function PricingContent({ data, lang, today, highlight, onFootnote }: {
                         <TierCell
                           key={key} family={family} tierKey={key} lang={lang} today={today}
                           refNumbers={refNumbers} showModelIds={showModelIds} onFootnote={onFootnote}
+                          changes={changeItems} highlighted={highlightCell === priceCellId(family.family_key, key)}
                         />
                       )))}
                     </tr>
@@ -596,6 +698,16 @@ export default function PricingPanel() {
     highlightTimer.current = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS);
   }, []);
   useEffect(() => () => window.clearTimeout(highlightTimer.current), []);
+  // A change banner item scrolls to its price cell and highlights it for 1.5 s, like a footnote does for a reference.
+  const [highlightCell, setHighlightCell] = useState<string | null>(null);
+  const cellTimer = useRef<number | undefined>(undefined);
+  const onCellJump = useCallback((cellId: string) => {
+    document.getElementById(cellId)?.scrollIntoView({ block: "center", behavior: "smooth" });
+    window.clearTimeout(cellTimer.current);
+    setHighlightCell(cellId);
+    cellTimer.current = window.setTimeout(() => setHighlightCell(null), HIGHLIGHT_MS);
+  }, []);
+  useEffect(() => () => window.clearTimeout(cellTimer.current), []);
 
   return (
     <div className="page-stack">
@@ -615,7 +727,8 @@ export default function PricingPanel() {
       <DataError error={resource.error} resource={L("unit prices", "비용 단가")} onRetry={() => void resource.refresh()} hasData={resource.data !== null} />
       {resource.loading && <DataLoading />}
       {resource.data && (
-        <PricingContent data={resource.data} lang={lang} today={new Date()} highlight={highlight} onFootnote={onFootnote} />
+        <PricingContent data={resource.data} lang={lang} today={new Date()} highlight={highlight} onFootnote={onFootnote}
+                        highlightCell={highlightCell} onCellJump={onCellJump} />
       )}
     </div>
   );
````
- [ ] **Step 4:** Run:

```bash
cd frontend && npm run typecheck && npx vitest run && npx playwright test --project=chromium --reporter=line
```

Expected: typecheck clean, vitest `392 passed`, Playwright `152 passed, 2 failed` where the two failures are `presence.spec.ts:78` and `shell.spec.ts:9` — the same two fail on `c96a592` with the dev server (see "How this plan was made"). Any other failure is a regression.
- [ ] **Step 5:** `git checkout -- frontend/next-env.d.ts` (dev-server rewrite).
- [ ] **Step 6:** Commit:

```bash
git add frontend/src/components/PricingPanel.tsx \
  frontend/e2e/pricing-changes.spec.ts
git commit -m "feat(pricing): changes since the previous sync with a jump to the cell and a cell badge"
```
---

### Task 11: Documentation

**Files:**
- Create: `docs/decisions/ADR-035-pricing-changes-and-explorer-verify.md`
- Modify: `docs/architecture.md` (both languages), `docs/api-reference.md`, `docs/runbooks/deploy.md` (task list, §5-12), `CLAUDE.md`, `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `backend/tests/CLAUDE.md`, `cdk/CLAUDE.md`, `frontend/src/lib/CLAUDE.md`, `frontend/src/components/CLAUDE.md`

The root `CLAUDE.md` version line is Task 12 — leave `(v2.39.0 — …` here.
- [ ] **Step 1:** Create `docs/decisions/ADR-035-pricing-changes-and-explorer-verify.md`:

````markdown
# ADR-035: 비용 단가 런 대비 변경 표시와 모델 탐색 일일 검증 런

- **Status**: Accepted
- **Date**: 2026-11-05
- **Related**: ADR-011 (Scheduler RunTask family 와일드카드), ADR-026 (Claude API Features 검증, 런 대비 변경 배너의 원형), ADR-030 (단가 자동 동기화), v2.40.0
- **Design**: [`docs/superpowers/specs/2026-11-05-change-tracking-and-explorer-verify-design.md`](../superpowers/specs/2026-11-05-change-tracking-and-explorer-verify-design.md)

## Context

사용자 요청(2026-11-05):

1. "비용 단가에 이전 런 대비 변경이 있으면 표기한다. Claude API 기능 검증처럼."
2. "모델 탐색도 1일 1회 런으로 검증하고, 이전 런 대비 변경이 있으면 표기한다. Claude API 기능 검증처럼."

`/pricing`은 12시간마다 공식 출처와 동기화되지만, 무엇이 바뀌었는지는 `price_history` 행을 직접 봐야 알 수 있었다. `price_sync_runs.summary`에는
채널별 분류(`unchanged`, `changed`, `pending` …)만 있고, 관리자 승인과 거부는 런과 무관하게 일어나 런 사이의 표 변화를 그대로 비교할 수 없었다.

`/models`의 코드 예제는 2026-10-19 점검에서 118개 중 48개가 실제로는 실패했다(`us.*` 리전, CP 헤더 `anthropic-workspace`, thinking 블록의
`content[0]["text"]` KeyError). 모두 예제 텍스트의 결함이었고 UI 테스트로는 보이지 않았다. 예제는 프런트(`modelExplorer.ts` `codeExamples`)에만
있어 백엔드가 실행할 수 없었다.

## Decision

1. **단가: 런 스냅샷과 비교** — `pricing_sync.run_sync`가 같은 트랜잭션 안에서(커밋 전, `db.flush()` 뒤) 활성 채널마다 `/pricing`이 보여 줄 값을
   `price_sync_runs.summary["snapshot"]`에 저장한다: 9필드 `shown`(`price_history.current_rows`), `shown`과 다른 대기 필드만 담은 `pending`
   (`no_baseline`이면 대기 행의 값 전부), 그 런의 채널 결과 `result`, 이름 표시용 `family_key`, `family`, `provider`, `tier`, `region`. JSON 열에
   키를 더할 뿐이라 스키마 변경은 없다. `pricing_changes.py`가 스냅샷이 있는 최근 `completed`/`partial` 런과 그 앞 런을 비교해 `channel`, `price`,
   `pending`, `check` 네 종류 항목을 만들고 `/api/pricing` `changes`로 내보낸다. 승인과 거부도 다음 스냅샷에 반영되므로 화면 문구는 "이전
   동기화(#N) 대비 변경"이고 경로(동기화 적용인지 승인인지)는 구분하지 않는다. 내보내기(CSV, Markdown, JSON)는 바뀌지 않는다.
2. **모델 탐색: 예제 생성을 백엔드로 옮겨 단일 출처로**(사용자 결정 A안) — `backend/model_explorer/examples.py`가 TS `codeExamples()`를 바이트
   단위로 옮긴다(골든 `tests/fixtures/explorer_examples_v2390.json`, 채널 유형별 대표 9개 × KO/EN). `/api/explorer/latest`가 이 함수로 예제를
   만들고, 매일 검증 런이 같은 함수의 EN 코드를 실행한다. 프런트 `codeExamples`는 지웠다(`channelOf`, `nativeId`, `modelLinks`는 남김).
3. **실행 방식** — 예제마다 새 임시 디렉터리에서 `sys.executable -I example.py`로 실행한다. 키 플레이스홀더는 `os.environ[...]` 식으로 바꿔 비밀
   값이 코드 텍스트에 들어가지 않고, 자식 env는 허용 목록(`AWS_*`, 키 4개, `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`)이라 스케줄 태스크의
   `DB_*`, `JWT_SECRET_KEY`, `SEED_ADMIN_PASSWORD`는 넘어가지 않는다. 호출당 90초, 실패는 1회 재시도, 출력은 저장 전에 비밀 값을 `***`로 가린다.
   종료 코드 0과 비어 있지 않은 stdout만 통과다.
4. **스케줄** — `ExplorerVerifyTaskDef`(autoprober 역할, 기본 env와 secret, 로그 그룹 `/ecs/explorer`)와 `ExplorerVerifySchedule`
   `cron(0 18 * * ? *)` Etc/UTC(03:00 KST, FeaturesVerify 17:30 뒤). Scheduler 역할 RunTask family `:*` 목록에 더했다(ADR-011). 새 IAM 정책,
   새 env는 없다.
5. **변경 표시** — `explorer_runs`, `explorer_results`(ORM + `create_all`). 셀 `(model_id, api_id)`의 상태나 `code_sha`가 직전 완료 런과 다르면
   변경이다: `catalog`(새 셀), `example`(코드가 바뀜 — 상태가 같아도), `measured`(같은 코드, 다른 상태). `stale_code`는 결과가 지금 예제보다 오래된
   코드로 측정됐다는 표시다. 실행 중 판정은 DB 기준(30분 안의 `running` 행)이다 — 스케줄 런은 별도 Fargate 태스크라 백엔드 프로세스가 모른다.

## Alternatives

- **B안: TS 유지 + 생성 JSON 커밋** — 모델 추가와 템플릿 수정마다 재생성 단계가 늘고, 런타임 등록 모델(CP)과 덤프 목록이 어긋날 수 있다. 기각.
- **C안: 백엔드가 같은 호출을 따로 구현(패리티 방식)** — 예제 텍스트 자체를 실행하지 않는다. 2026-10-19의 결함 3종은 모두 텍스트 결함이라 다시
  놓친다. 기각.
- **러너가 배포된 프런트에서 예제를 받아 실행** — 네트워크로 받은 코드를 비밀 값이 있는 태스크에서 실행하는 구조다. 기각.
- **단가 변경을 `price_history` 행에서 재구성** — 승인, 거부, `enriched` 채우기는 새 행을 만들지 않아 런 사이의 화면 변화를 정확히 되살릴 수 없다.
  스냅샷을 택했다.

## Consequences

- `/pricing`: 마지막 동기화 상자 아래 변경 배너(스냅샷 런이 둘이 되기 전에는 "변경 비교는 다음 동기화부터 표시됩니다."), 항목 → 셀 스크롤과 1.5초
  강조, 바뀐 셀에 "이전 대비 변경" 배지. 배포 직후 PricingSync를 두 번 돌려 기준선을 만든다.
- `/models`: 머리글에 최근 검증 런, 카드마다 검증 배지와 "변경" 표지, "검증 실패만" 필터, 변경 배너(항목 → 그 API 탭으로 모달), 모달의 검증 상자.
  모달 코드가 백엔드에서 오므로 `/api/explorer/latest`가 실패하면 모달 코드 영역에 재시도가 보이고, 카드는 `/api/models`만으로 그린다.
- 예제를 고칠 때는 `examples.py`만 고치고, 의도한 변경이면 골든 파일을 함께 바꾼다. 새 플레이스홀더는 `execute.PLACEHOLDERS`에 먼저 넣는다
  (테스트가 모르는 플레이스홀더를 잡는다).
- 하루 85건, "Hello!" + `max_tokens` 512라 토큰 비용은 하루 $1 미만으로 예상한다(첫 운영 런에서 실측해 기록한다).
- 로컬 스모크(`python -m explorer_runner --smoke`)는 `-I`가 사용자 site-packages를 끄므로 anthropic, openai, boto3가 설치된 venv에서 돌린다.
````
- [ ] **Step 2:** Apply this change to `docs/architecture.md`, `docs/api-reference.md`, `docs/runbooks/deploy.md` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/docs/api-reference.md b/docs/api-reference.md
index 968be68..89c69cf 100644
--- a/docs/api-reference.md
+++ b/docs/api-reference.md
@@ -546,10 +546,21 @@ Current price table. The backend keeps a 60 s in-process cache per task (no `lan
   `openai-list:<family_key>` channel per active OpenAI family (8 in v2.31.0, 9 since v2.32.0 with `openai-list:gpt-6.1-sol`, 10 since
   v2.38.0 with `openai-list:gpt-6.1-terra`, 9 since v2.39.0 without `openai-list:gpt-5.4`): 49 + 9 = 58 in production (v2.39.0;
   61 + 10 = 71 in v2.38.0, 66 + 9 = 75 in v2.33.0, 62 + 9 = 71 in v2.32.0). `families` has 18 entries and `models` 49 since v2.39.0.
+- **`changes` (v2.40.0, ADR-035)** — what changed in the table since the previous price sync. Every finished sync run stores what
+  this endpoint showed at its end (`price_sync_runs.summary.snapshot`: per active channel the nine shown prices, the pending-review
+  fields that differ from them, and the run's channel result). `changes` compares the latest `completed` or `partial` run that has a
+  snapshot with the `completed`/`partial` run before it (`failed` runs are skipped):
+  `{"available": true, "run_id": 141, "finished_at": "…Z", "previous_run_id": 140, "previous_finished_at": "…Z", "items": [...]}`.
+  Each item is `{model_id, family_key, family, provider, tier, region, kind, field, before, after}`: `kind` `channel` (a channel only
+  one run has — `before: null, after: "present"` new, the reverse removed; no field items for it), `price` (a shown value changed —
+  sync, admin approval, or a first-time value with `before: null`), `pending` (a pending-review value started, `null` → value, or
+  ended, value → `null`) or `check` (`"ok"` ↔ `"skipped:<reason>"`, the run's source check). Items are in table order (provider,
+  family, tier `cp`, `openai_list`, `global`, `us`, `in_region`, kind, field). Before two runs with a snapshot exist (right after the
+  v2.40.0 deploy): `{"available": false, "run_id": <latest snapshot run or null>}`. Cached with the rest of the body (60 s).
 
 ### GET /api/pricing/export?format=csv|md|json&lang=ko|en
 Download the same table as a file: `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<csv|md|json>"`.
-`lang` defaults to `ko`. `json` is the `/api/pricing` body. `md` starts with the disclaimer as a quote, then the unit, generation
+`lang` defaults to `ko`. `json` is the `/api/pricing` body without `changes` (v2.40.0: the exports keep their v2.39.0 content). `md` starts with the disclaimer as a quote, then the unit, generation
 time and last official price sync lines (`Last official price sync: <finished_at> (<status>)`, KO `마지막 공식 단가 동기화`, with the
 screen's status words "completed", "partial, some sources failed", "failed", "running", KO "완료", "일부 출처 실패", "실패",
 "진행 중"; an unknown status as is), the pending review count when it is above 0, and one line that links the official pricing
@@ -661,6 +672,53 @@ v2.32.0 by the cell count for the 7 models of v2.33.0; it was 약 9분 with 5 mo
 
 ---
 
+## Model Explorer verification (Public read, trigger = Auth Required) — v2.40.0, ADR-035
+
+### GET /api/explorer/latest
+Every visible model's code examples with the latest daily verification result. The examples come from
+`backend/model_explorer/examples.py` at request time — the same function the ExplorerVerify run executes, so the page shows the code
+that was run (moved byte for byte from the v2.39.0 frontend `codeExamples`). No `lang` parameter: descriptions and code carry `ko` and
+`en`. `Cache-Control: public, max-age=0, s-maxage=60`.
+
+```json
+{
+  "run": {"id": 12, "started_at": "2026-11-05T18:00:01Z", "finished_at": "2026-11-05T18:01:48Z",
+          "totals": {"passed": 83, "failed": 1, "skipped": 1}},
+  "running": false,
+  "previous_run_id": 11,
+  "changes": [{"model_id": "global.anthropic.claude-opus-5", "model_name": "Bedrock Claude Opus 5 (Global)",
+               "api_id": "invoke_model", "api": "InvokeModel API", "before": "passed", "after": "failed", "kind": "measured"}],
+  "models": {
+    "global.anthropic.claude-opus-5": {"examples": [
+      {"api_id": "converse", "api": "Converse API", "label": "Python (boto3)", "language": "python",
+       "description": {"ko": "…", "en": "…"}, "code": {"ko": "…", "en": "…"}, "code_sha": "<sha256 of the EN code>",
+       "result": {"status": "passed", "latency_ms": 1180.2, "attempts": 1, "error_message": null,
+                  "output_excerpt": "Hello! …", "run_id": 12, "verified_at": "2026-11-05T18:01:48Z", "stale_code": false}}
+    ]}
+  }
+}
+```
+
+- `models` = `prober.AVAILABLE_MODELS` without the hidden labels (`visibility`), in catalog order; `api_id` ∈ `converse`,
+  `invoke_model`, `messages`, `responses` (Bedrock Claude 3, Nova 1, Claude Platform on AWS 1, OpenAI 1 — 85 for the 49 active channels).
+- `result` is the same `(model_id, api_id)` cell of the latest **completed** run, `null` before it was verified. `status` ∈ `passed`
+  (exit 0 with output), `failed` (no output — "출력 없음", an exception — the first line of `error_message` is the exception line and
+  the rest the stderr tail, or "시간 초과 90초"), `skipped` (the reason: "자격 증명 미주입: <env>", "알 수 없는 플레이스홀더",
+  "런 시간 상한"). `attempts` 2 = failed once and ran again; the second result decides. `stale_code` = the example changed after this
+  result was measured. `output_excerpt` is the first 300 characters of stdout; secret values are masked (`***`) before storage.
+- `run` = the latest completed run (null before the first). `running` = a `running` row started less than 30 minutes ago (the scheduled
+  run is a separate Fargate task, so the backend reads the DB) or this process's manual run.
+- `changes[]` = cells of the latest run that differ from the previous completed run: `kind` `catalog` (the cell was not in the previous
+  run), `example` (the code changed — `code_sha` differs — whatever the status), `measured` (same code, different status). Cells only
+  the previous run had are ignored; hidden models are left out of `models` and `changes`. Sorted by `(model_id, api_id)`.
+
+### POST /api/explorer/trigger (Auth Required)
+Start a manual run in a backend daemon thread: `{"triggered": true, "message": "모델 탐색 검증 런을 시작했습니다 (약 2분 소요)"}`, or
+`{"triggered": false, "message": "이미 실행 중입니다"}` while this process runs one or the DB has a `running` row younger than 30 minutes.
+The daily run is the ExplorerVerify Fargate task (`python -m explorer_runner --once`, `cron(0 18 * * ? *)` UTC).
+
+---
+
 ## GPT on AWS bench (Public) — v2.18.0, 18 channels since v2.39.0
 
 Data source for `/gpt-on-aws`. The GptBench task (`python -m gptbench_runner --once`, every 15 min) measures 18 channels —
diff --git a/docs/architecture.md b/docs/architecture.md
index 2a3dfe7..8229acb 100644
--- a/docs/architecture.md
+++ b/docs/architecture.md
@@ -47,6 +47,7 @@ flowchart TB
     gpt["GptBench task: 15 min"]
     feat["FeaturesVerify task: daily 17:30 UTC"]
     prc["PricingSync task: 12 h"]
+    exp["ExplorerVerify task: daily 18:00 UTC"]
   end
 
   subgraph storage[Storage Layer]
@@ -80,7 +81,7 @@ flowchart TB
   alb -->|"/*"| fe
   alb -->|"/api/*"| be
   sched --> ap & ins & par & gpt & feat & prc
-  ap & par & feat --> providers
+  ap & par & feat & exp --> providers
   prc --> offers & plist & adoc & odoc
   prc -.->|"CP model list"| cp
   gpt --> br & mantle
@@ -89,7 +90,7 @@ flowchart TB
   be --> opt
   be --> ses
   be --> mem
-  be & ap & ins & par & gpt & feat & prc --> rds
+  be & ap & ins & par & gpt & feat & prc & exp --> rds
   sec -.->|"secrets at task start"| be
   be & fe & ap --> cw
   cw --> sns
@@ -178,7 +179,8 @@ flowchart LR
 | `ParityRunSchedule` | `rate(12 hours)` | `python -m parity_runner --once` | Model × 6 surfaces × 20 features evidence cells |
 | `GptBenchSchedule` | `rate(15 minutes)` | `python -m gptbench_runner --once` | 18 GPT channels (Mantle in-region us-east-1 7 + CRIS 11) in parallel lanes, one per host: `cris` (11 Global and US CRIS channels, Bedrock Runtime OpenAI-compatible host, one lane) and one `mantle-<region>` lane per Mantle region (`bedrock-mantle.<region>`), today only `mantle-us-east-1` 7 (v2.39.0 dropped GPT 5.4, its first channel, ADR-034; v2.38.0 had 8 after Mantle in-region was consolidated to us-east-1 and GPT 6.1 Terra added at the end, user decision 2026-10-27; v2.32.1 to v2.37.x ran 21 channels in four lanes, `cris` 9, `mantle-us-east-1` 6, `mantle-us-east-2` 3, `mantle-us-west-2` 3; v2.32.0 had two lanes, `cris` 9 and `mantle` 12, split per region after the 2026-09-30 GPT 5.4 us-east-2 slowdown, user decision). Inside a lane each channel runs sequentially, warm-up 1 + `GPT_BENCH_RUNS` (10) calls, so calls to one host never overlap; per-call watchdog `GPT_BENCH_CALL_TIMEOUT` 90 s; one cycle deadline `GPT_BENCH_DEADLINE` 780 s shared by all lanes (a lane past it skips only its own remaining channels); the main thread commits each finished channel; a lane still running after deadline + call cap + `LANE_JOIN_GRACE_S` 15 s (885 s, best effort) is no longer waited for: queued events are all stored, its in-flight channel keeps its finished runs and is reported as `label (run N+)`, never-started channels as `label` |
 | `FeaturesVerifySchedule` | `cron(30 17 * * ? *)` Etc/UTC | `python -m features_runner --once` | 39 rows × 5 surfaces × 7 models (Claude Fable 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5.5, Sonnet 5, Haiku 5.5 — v2.33.0) = 1,365 cells (1,079 probed + 286 pre-decided), daily at 17:30 UTC (02:30 KST) |
-| `PricingSyncSchedule` | `rate(12 hours)` | `python -m pricing_sync_runner --once` | One `price_sync_runs` row (`completed`, `partial` or `failed`) and, per active channel (49 since v2.39.0, plus 9 display-only OpenAI official price channels — the runner logs `58 active channels`; the OpenAI official price channels date from v2.31.0), an unchanged observation, empty cache or long-context fields filled on the current row (`enriched`, v2.31.0), a new `verified` price (every field changed by 50% or less) or a `pending_review` row; run cap 300 s; `pg_try_advisory_lock(917350004)` keeps runs from overlapping — a second run exits at once (exit 1, no run row) (v2.30.0, ADR-030) |
+| `PricingSyncSchedule` | `rate(12 hours)` | `python -m pricing_sync_runner --once` | One `price_sync_runs` row (`completed`, `partial` or `failed`) and, per active channel (49 since v2.39.0, plus 9 display-only OpenAI official price channels — the runner logs `58 active channels`; the OpenAI official price channels date from v2.31.0), an unchanged observation, empty cache or long-context fields filled on the current row (`enriched`, v2.31.0), a new `verified` price (every field changed by 50% or less) or a `pending_review` row; run cap 300 s; `pg_try_advisory_lock(917350004)` keeps runs from overlapping — a second run exits at once (exit 1, no run row) (v2.30.0, ADR-030); since v2.40.0 each finished run also stores what `/pricing` shows (`summary.snapshot`), and `/api/pricing` `changes` compares the two latest runs that have one (ADR-035) |
+| `ExplorerVerifySchedule` | `cron(0 18 * * ? *)` Etc/UTC | `python -m explorer_runner --once` | Runs every Model Explorer code example (`backend/model_explorer/examples.py`, the same function `/api/explorer/latest` shows) once in a child Python per example: 85 examples for the 49 active channels, 4 at a time, 90 s per call, one retry of a failure, 1,200 s run cap; one `explorer_runs` row and one `explorer_results` row per example (`passed`, `failed`, `skipped`), daily at 18:00 UTC (03:00 KST), after FeaturesVerify (v2.40.0, ADR-035) |
 
 Every scheduled task uses the backend image with a command override, 0.5 vCPU / 1 GB, and a task definition family `:*` wildcard in the scheduler role's `ecs:RunTask` policy (ADR-011). PricingSync runs with its own task role that allows only `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts`, with no model invocation.
 
@@ -314,6 +316,7 @@ flowchart TB
     gpt["GptBench task: 15 min"]
     feat["FeaturesVerify task: daily 17:30 UTC"]
     prc["PricingSync task: 12 h"]
+    exp["ExplorerVerify task: daily 18:00 UTC"]
   end
 
   subgraph storage[Storage Layer]
@@ -347,7 +350,7 @@ flowchart TB
   alb -->|"/*"| fe
   alb -->|"/api/*"| be
   sched --> ap & ins & par & gpt & feat & prc
-  ap & par & feat --> providers
+  ap & par & feat & exp --> providers
   prc --> offers & plist & adoc & odoc
   prc -.->|"CP model list"| cp
   gpt --> br & mantle
@@ -356,7 +359,7 @@ flowchart TB
   be --> opt
   be --> ses
   be --> mem
-  be & ap & ins & par & gpt & feat & prc --> rds
+  be & ap & ins & par & gpt & feat & prc & exp --> rds
   sec -.->|"secrets at task start"| be
   be & fe & ap --> cw
   cw --> sns
@@ -445,7 +448,8 @@ flowchart LR
 | `ParityRunSchedule` | `rate(12 hours)` | `python -m parity_runner --once` | 모델 × surface 6개 × 피처 19개 실행 증거 셀 |
 | `GptBenchSchedule` | `rate(15 minutes)` | `python -m gptbench_runner --once` | GPT 18채널(Mantle 인리전 us-east-1 7 + CRIS 11)을 호스트별 갈래로 동시에 돈다. `cris`(Global, US CRIS 11채널, Bedrock Runtime OpenAI 호환 호스트, 한 갈래)와 Mantle 리전마다 한 갈래인 `mantle-<region>`(`bedrock-mantle.<region>`)이고, 지금은 `mantle-us-east-1` 7 하나다(v2.39.0에 첫 채널 GPT 5.4를 뺐다, ADR-034. v2.38.0은 Mantle 인리전 us-east-1 일원화와 GPT 6.1 Terra 편입으로 8, 사용자 결정 2026-10-27. v2.32.1~v2.37.x는 21채널 네 갈래 `cris` 9, `mantle-us-east-1` 6, `mantle-us-east-2` 3, `mantle-us-west-2` 3, v2.32.0은 `cris` 9, `mantle` 12 두 갈래였고, 2026-09-30 GPT 5.4 us-east-2 저하 뒤 사용자 결정으로 리전별로 나눴다). 갈래 안에서는 채널을 하나씩 순차로 측정하고(워밍업 1 + `GPT_BENCH_RUNS` 10회, 같은 호스트 호출은 겹치지 않는다), 호출당 watchdog은 `GPT_BENCH_CALL_TIMEOUT` 90초, 사이클 데드라인 `GPT_BENCH_DEADLINE` 780초는 모든 갈래가 공유한다(넘긴 갈래는 자기 남은 채널만 skip). 끝난 채널은 메인 스레드가 커밋하고, 데드라인 + 호출 상한 + `LANE_JOIN_GRACE_S` 15초(885초, 최선의 상한)가 지나도 도는 갈래는 기다리지 않는다. 큐에 도착한 진행은 모두 저장하고, 진행 중 채널은 끝난 회차를 저장해 `라벨 (run N+)`, 시작하지 못한 채널은 `라벨`로 보고한다 |
 | `FeaturesVerifySchedule` | `cron(30 17 * * ? *)` Etc/UTC | `python -m features_runner --once` | 39행 × surface 5개 × 모델 7개(Claude Fable 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5.5, Sonnet 5, Haiku 5.5 — v2.33.0) = 1,365셀(프로브 1,079 + 사전판정 286), 매일 17:30 UTC(02:30 KST) |
-| `PricingSyncSchedule` | `rate(12 hours)` | `python -m pricing_sync_runner --once` | `price_sync_runs` 1행(`completed`, `partial`, `failed`)과 활성 채널(v2.39.0부터 49채널, 표시 전용 OpenAI 공식 가격 9채널 — 러너 로그 `58 active channels`, OpenAI 공식 가격 채널은 v2.31.0부터)마다 변경 없음 관측, 현재 행의 빈 캐시나 긴 컨텍스트 필드 채우기(`enriched`, v2.31.0), 새 `verified` 단가(모든 필드 변화 50% 이하), `pending_review` 행 중 하나, 런 상한 300초, `pg_try_advisory_lock(917350004)`로 런이 겹치지 않게 한다 — 겹치면 두 번째 런은 즉시 exit 1로 끝난다(런 행 없음) (v2.30.0, ADR-030) |
+| `PricingSyncSchedule` | `rate(12 hours)` | `python -m pricing_sync_runner --once` | `price_sync_runs` 1행(`completed`, `partial`, `failed`)과 활성 채널(v2.39.0부터 49채널, 표시 전용 OpenAI 공식 가격 9채널 — 러너 로그 `58 active channels`, OpenAI 공식 가격 채널은 v2.31.0부터)마다 변경 없음 관측, 현재 행의 빈 캐시나 긴 컨텍스트 필드 채우기(`enriched`, v2.31.0), 새 `verified` 단가(모든 필드 변화 50% 이하), `pending_review` 행 중 하나, 런 상한 300초, `pg_try_advisory_lock(917350004)`로 런이 겹치지 않게 한다 — 겹치면 두 번째 런은 즉시 exit 1로 끝난다(런 행 없음) (v2.30.0, ADR-030). v2.40.0부터 끝난 런마다 `/pricing`이 보여 주는 값을 함께 저장하고(`summary.snapshot`), `/api/pricing` `changes`가 스냅샷이 있는 최근 두 런을 비교한다(ADR-035) |
+| `ExplorerVerifySchedule` | `cron(0 18 * * ? *)` Etc/UTC | `python -m explorer_runner --once` | 모델 탐색 코드 예제(`backend/model_explorer/examples.py`, `/api/explorer/latest`가 보여 주는 함수와 같은 함수)를 예제마다 자식 Python에서 한 번씩 실행한다. 활성 49채널 85건, 동시 4, 호출당 90초, 실패는 1회 재시도, 런 상한 1,200초. `explorer_runs` 1행과 예제마다 `explorer_results` 1행(`passed`, `failed`, `skipped`)을 남긴다. 매일 18:00 UTC(03:00 KST), FeaturesVerify 뒤 (v2.40.0, ADR-035) |
 
 모든 스케줄 태스크는 backend 이미지를 command override로 쓰고 0.5 vCPU / 1 GB이며, 스케줄러 역할의 `ecs:RunTask` 정책은 태스크 정의 family `:*` 와일드카드를 씁니다(ADR-011). PricingSync는 `bedrock:ListFoundationModelAgreementOffers`와 `pricing:GetProducts`만 허용하는 전용 태스크 역할로 돌며 모델 호출 권한이 없습니다.
 
diff --git a/docs/runbooks/deploy.md b/docs/runbooks/deploy.md
index f046797..e168a5f 100644
--- a/docs/runbooks/deploy.md
+++ b/docs/runbooks/deploy.md
@@ -109,13 +109,14 @@ BE_ARN=$(aws ecs register-task-definition --region $REGION \
 aws ecs update-service --cluster bedrock-monitor --service backend \
   --task-definition "$BE_ARN" --region $REGION
 
-# 스케줄 태스크 6개 모두 동일하게 (각각 별도 Fargate Task — backend image 공용). 하나라도 빠지면 그 태스크만 옛 이미지로 돈다.
+# 스케줄 태스크 7개 모두 동일하게 (각각 별도 Fargate Task — backend image 공용). 하나라도 빠지면 그 태스크만 옛 이미지로 돈다.
 # AutoProber:     family BedrockMonitorSchedulerAutoProberTaskDef*,     schedule rate(5 minutes),  CLI auto_prober_runner --once (env ANTHROPIC_CP_PROBE_INTERVAL_S=300 = CP도 매 사이클 — v2.29.1, 600이면 CP만 두 사이클에 한 번)
 # Insights:       family BedrockMonitorSchedulerInsightsTaskDef*,       schedule rate(5 minutes),  CLI insights_runner --window 6h
 # ParityRun:      family BedrockMonitorSchedulerParityRunTaskDef*,      schedule rate(12 hours),   CLI parity_runner --once (v2.11.0)
 # GptBench:       family BedrockMonitorSchedulerGptBenchTaskDef*,       schedule rate(15 minutes), CLI gptbench_runner --once (v2.18.0)
 # FeaturesVerify: family BedrockMonitorSchedulerFeaturesVerifyTaskDef*, schedule cron(30 17 * * ? *) Etc/UTC, CLI features_runner --once (v2.23.0, 고정 cron v2.29.0)
 # PricingSync:    family BedrockMonitorSchedulerPricingSyncTaskDef*,    schedule rate(12 hours),   CLI pricing_sync_runner --once (v2.30.0, 전용 task role — 최초 배포는 CDK로만)
+# ExplorerVerify: family BedrockMonitorSchedulerExplorerVerifyTaskDef*, schedule cron(0 18 * * ? *) Etc/UTC, CLI explorer_runner --once (v2.40.0 — 최초 배포는 CDK로만)
 # 정확한 family 이름: aws ecs list-task-definition-families --family-prefix BedrockMonitorScheduler --status ACTIVE --region $REGION
 AP_FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerAutoProberTaskDef \
   --status ACTIVE --region $REGION --query 'families[0]' --output text)
@@ -124,7 +125,7 @@ aws ecs describe-task-definition --task-definition "$AP_FAM" \
 # ... (위와 동일하게 image 교체 + register) ...
 AP_ARN=...
 # 스케줄 이름 — AutoProber/Insights는 Scheduler 스택 output(AutoProberScheduleName / InsightsScheduleName)에 있다.
-# 6개 전부: aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION --query 'Schedules[].Name'
+# 7개 전부: aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION --query 'Schedules[].Name'
 AP_SCHED=$(aws cloudformation describe-stacks --stack-name BedrockMonitor-Scheduler --region $REGION \
   --query "Stacks[0].Outputs[?OutputKey=='AutoProberScheduleName'].OutputValue" --output text)
 aws scheduler get-schedule --name "$AP_SCHED" --region $REGION > /tmp/sched.json
@@ -922,6 +923,78 @@ curl -s "https://$CF_DOMAIN/api/pricing" | jq '{last_sync: .last_sync.status, pe
 - 롤백 지점은 v2.38.0(`v2d64a44`, digest는 `docs/reviews/2026-10-27-v238-deployment.md`)이다. 절차는 [rollback.md](rollback.md)의
   "v2.39.0에서 v2.38.0으로 되돌릴 때"를 따른다.
 
+### 5-12. v2.40.0 배포 경로와 확인 (비용 단가 런 대비 변경, 모델 탐색 일일 검증 런)
+
+**배포 경로**: CDK 변경이 있다. Scheduler 스택에 `ExplorerVerifyTaskDef`(`python -m explorer_runner --once`, autoprober task role, 기본 env와 secret,
+로그 그룹 `/ecs/explorer` 14일)와 `ExplorerVerifySchedule`(`cron(0 18 * * ? *)` Etc/UTC = 03:00 KST)이 생기고, Scheduler 역할 RunTask family `:*` 목록에
+새 family가 들어간다(ADR-011). 이 태스크는 처음이라 §2-1 이미지-only 경로로는 만들 수 없다 — **digest 고정 CDK로 `BedrockMonitor-AppServices` +
+`BedrockMonitor-Scheduler`**를 배포한다. 새 env, 새 IAM 정책은 없고, 새 테이블 `explorer_runs`, `explorer_results`는 `create_all`이 만든다(러너도
+`create_tables()`를 먼저 부른다). `/api/pricing`은 `changes`를 더 보낸다. 내보내기 내용은 그대로다(ADR-035).
+
+배포 전 로컬 스모크 — `-I`가 사용자 site-packages를 끄므로 venv에서 돌린다(SSM 키는 화면에 찍지 않는다):
+
+```bash
+python3.12 -m venv /tmp/explorer-venv && /tmp/explorer-venv/bin/pip install -q -r backend/requirements.txt
+export ANTHROPIC_API_KEY=$(aws ssm get-parameter --name /bedrock-monitor/anthropic-api-key --with-decryption --query Parameter.Value --output text --region ap-northeast-2)
+export ANTHROPIC_WORKSPACE_ID=$(aws ssm get-parameter --name /bedrock-monitor/anthropic-workspace-id --with-decryption --query Parameter.Value --output text --region ap-northeast-2)
+export OPENAI_API_KEY=$(aws ssm get-parameter --name /bedrock-monitor/openai-api-key --with-decryption --query Parameter.Value --output text --region ap-northeast-2)
+# OpenAI 22채널 등록용 env — cdk/lib/stacks/scheduler-stack.ts buildTaskDef environment와 같은 값
+export OPENAI_US_EAST_1_BASE_URL=https://bedrock-mantle.us-east-1.api.aws/openai/v1
+export OPENAI_GLOBAL_BASE_URL=https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1
+export OPENAI_US_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1
+export BEDROCK_OPENAI_GPT_55_MODEL_ID=openai.gpt-5.5 BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID=openai.gpt-5.6-sol \
+  BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID=openai.gpt-5.6-terra BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID=openai.gpt-5.6-luna \
+  BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID=openai.gpt-6-astra BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID=openai.gpt-6-sol \
+  BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID=openai.gpt-6-luna BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID=openai.gpt-6.1-sol \
+  BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID=openai.gpt-6.1-terra
+cd backend && /tmp/explorer-venv/bin/python -m explorer_runner --smoke
+# 기댓값: 85줄(Bedrock Claude 18 × 3 + Nova 1 + CP 8 + OpenAI 22), 전부 passed, exit 0. failed가 있으면 예제 결함인지(같은 API 전체가 실패)
+#   서비스 쪽인지(한 모델만, 재시도 뒤에도) 먼저 가리고 보고한다.
+```
+
+배포 뒤 확인:
+
+```bash
+REGION=ap-northeast-2
+CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
+# 1. 스케줄 — cron + Etc/UTC, ExplorerVerify task def
+N=$(aws scheduler list-schedules --region $REGION --query 'Schedules[].Name' --output text | tr '\t' '\n' | grep ExplorerVerify)
+aws scheduler get-schedule --name "$N" --region $REGION \
+  --query '{e: ScheduleExpression, tz: ScheduleExpressionTimezone, td: Target.EcsParameters.TaskDefinitionArn}'
+# 기댓값: {"e": "cron(0 18 * * ? *)", "tz": "Etc/UTC", "td": "…:task-definition/BedrockMonitorSchedulerExplorerVerifyTaskDef…:N"}
+#   task def image는 이번 릴리스 digest여야 한다(§3 확인과 같은 방법).
+
+# 2. ExplorerVerify 수동 1회 — 네트워크 설정은 스케줄 타깃에서 복사
+FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerExplorerVerifyTaskDef --status ACTIVE \
+  --region $REGION --query 'families[0]' --output text)
+NETCFG=$(aws scheduler get-schedule --name "$N" --region $REGION \
+  --query 'Target.EcsParameters.NetworkConfiguration.awsvpcConfiguration' --output json \
+  | jq -c '{awsvpcConfiguration: {subnets: .Subnets, securityGroups: .SecurityGroups, assignPublicIp: .AssignPublicIp}}')
+aws ecs run-task --cluster bedrock-monitor --task-definition "$FAM" --launch-type FARGATE --region $REGION \
+  --network-configuration "$NETCFG" --query 'tasks[0].taskArn' --output text
+# 약 2~3분 뒤
+aws logs tail /ecs/explorer --since 10m --region $REGION | grep -E 'Explorer run|explorer_runner'
+curl -s "https://$CF_DOMAIN/api/explorer/latest" | jq '{run: .run, running, prev: .previous_run_id,
+  models: (.models | length), examples: ([.models[].examples[]] | length),
+  failed: [.models | to_entries[] | .key as $m | .value.examples[] | select(.result.status == "failed") | {m: $m, api: .api_id, e: (.result.error_message | split("\n")[0])}]}'
+# 기댓값: run.totals 합 85, models 49, examples 85, prev null(첫 런), failed []
+
+# 3. PricingSync 수동 2회 — §5-5의 2번과 같은 명령(SCHED, FAM, NETCFG, run-task). 첫 런이 끝난 뒤(약 1분) 두 번째를 시작한다
+#    (pg_try_advisory_lock — 겹치면 두 번째는 exit 1).
+curl -s "https://$CF_DOMAIN/api/pricing" | jq '.changes | {available, run_id, previous_run_id, n: (.items | length)}'
+# 기댓값: 첫 런 뒤 {"available": false, "run_id": <첫 런>}, 두 번째 런 뒤 {"available": true, …, "n": 0}("변경 없음")
+#   — 60초 프로세스 캐시가 있으므로 각 런 뒤 1분 지나서 확인한다.
+curl -s "https://$CF_DOMAIN/api/pricing/export?format=json" | jq 'has("changes")'
+# 기댓값: false
+```
+
+- 화면 확인(Playwright, KO/EN, 390px): `/models` 머리글 "최근 검증 런 #N", 카드 검증 배지 "✓ 3/3 통과"(Bedrock Claude), 상세 모달의 검증 상자와
+  코드, "검증 실패만" 토글. `/pricing` 마지막 동기화 상자 아래 "이전 동기화(#N, …) 대비 변경 없음." 카드.
+- 첫 스케줄 런은 배포 뒤 첫 18:00 UTC다. 두 번째 런부터 `/models`에 "이전 런(#N) 대비 변경" 배너가 보인다.
+- 토큰 비용은 첫 런의 Bedrock, CP, OpenAI 사용량으로 실측해 ADR-035에 적는다(예상 하루 $1 미만).
+- 롤백 지점은 v2.39.0이다. 되돌리면 ExplorerVerify 스케줄과 task def가 CDK에서 지워지고, `explorer_runs`, `explorer_results` 테이블과
+  `price_sync_runs.summary.snapshot` 키는 남지만 v2.39.0 코드는 읽지 않는다.
+
 ## 6. 후속 배포 (코드만 변경 시)
 
 ⚠️ **신규 env가 추가된 릴리스(예: v2.20.0 `OPENAI_GLOBAL_BASE_URL`, v2.25.0 `OPENAI_US_BASE_URL` + `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID`, v2.27.0 `BEDROCK_OPENAI_GPT_6_{SOL,LUNA}_MODEL_ID`, v2.32.0 `BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID`, v2.38.0 `BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID`)에는 이미지-only
````
- [ ] **Step 3:** Apply the CLAUDE.md changes (the root overview version line is Task 12).

````diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 384a5e0..fc482f3 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -331,8 +337,8 @@ Claude Platform on AWS 채널(anthropic:*)도 기본값에서는 매 사이클 
 - **Register**: `username`은 **EmailStr** 검증 강제 (v2.1.0). approved=0 → admin SES → approved=1 → login
 - **Admin email**: `whchoi98@gmail.com` (`backend/auth.py:ADMIN_EMAIL`)
   - SES region: `us-east-1`. **Sandbox 모드 시 sender/recipient 둘 다 verified identity 필요**
-- **Public**: `/api/health`, `/api/auth/{login,register,approve}`, 모든 조회 GET — `/api/auto-probe/*`, `/api/results/*`, `/api/models`, `/api/cost/*`, `/api/reliability/*`, `/api/efficiency/*`, `/api/analysis/*`, `/api/parity/{catalog,latest,evidence}`, `/api/features/{catalog,latest,evidence}`, `/api/gptbench/*`, `/api/pricing`, `/api/pricing/export`, `/api/insights`·`/latest`, `GET /api/prompts`, `GET /api/probes/{run_id}`
-- **Auth required** (`Depends(get_current_user)`): `/api/auth/me`, `/api/auto-probe/trigger` (202 accepted / 409 active reservation), `/api/probes/run`, `/api/compare/run`, `/api/parity/trigger`, `/api/features/trigger`, `/api/prompts` (POST/DELETE, `/optimize`), `/api/insights/regenerate`·`/stream-regenerate`
+- **Public**: `/api/health`, `/api/auth/{login,register,approve}`, 모든 조회 GET — `/api/auto-probe/*`, `/api/results/*`, `/api/models`, `/api/cost/*`, `/api/reliability/*`, `/api/efficiency/*`, `/api/analysis/*`, `/api/parity/{catalog,latest,evidence}`, `/api/features/{catalog,latest,evidence}`, `/api/explorer/latest`, `/api/gptbench/*`, `/api/pricing`, `/api/pricing/export`, `/api/insights`·`/latest`, `GET /api/prompts`, `GET /api/probes/{run_id}`
+- **Auth required** (`Depends(get_current_user)`): `/api/auth/me`, `/api/auto-probe/trigger` (202 accepted / 409 active reservation), `/api/probes/run`, `/api/compare/run`, `/api/parity/trigger`, `/api/features/trigger`, `/api/explorer/trigger`, `/api/prompts` (POST/DELETE, `/optimize`), `/api/insights/regenerate`·`/stream-regenerate`
 - **Admin only**: `/api/admin/*` (username == "admin") — `/api/admin/pricing/*` 검토 대기 단가 승인/거부 포함 (v2.30.0). admin 비밀번호는 `SEED_ADMIN_PASSWORD` env var (8자 이상)
 - **Public chat** (`POST /api/chat/stream`, v2.37.0): JWT 없이 이용한다. 유효한 로그인은 사용자별 해시 actor, 비회원은 별도 서명 HttpOnly 쿠키의 해시 actor로 대화를 분리한다. `session_id`만 복사해 다른 사용자 대화를 읽을 수 없다. 성공·실패의 `final` 이벤트에 세션 ID를 담고 AgentCore는 필수 `eventTimestamp`, `includePayloads=True`로 대화를 기록·조회한다. 브라우저 Origin은 사이트 별칭만 허용하며 비회원은 백엔드 프로세스당 브라우저 6회/분·전체 30회/분을 초과하면 `429`와 `Retry-After: 60`을 받는다. 수동 프로브·프롬프트·인사이트 재생성의 인증은 그대로다.
 - **Visitor counts**: `GET /api/presence`는 공개 집계 조회와 서명된 HttpOnly 방문자 쿠키 준비, `POST /api/presence`는 JWT 없이 같은 Origin·전용 클라이언트 헤더·유효한 쿠키·빈 JSON 본문을 확인한 접속 신호다. 최근 90초의 브라우저를 접속자로 세고 누적값은 10,000부터 시작한다. `site_visitors`, `site_presence_totals`에 저장해 재배포와 여러 태스크에서 공유한다. IP나 브라우저 지문을 저장하지 않는다.
````

````diff
diff --git a/backend/CLAUDE.md b/backend/CLAUDE.md
index a1014cc..4af001b 100644
--- a/backend/CLAUDE.md
+++ b/backend/CLAUDE.md
@@ -32,6 +32,9 @@ separate scheduled Fargate tasks (reusing this image), NOT in-process.
 - `parity_runner.py` — CLI entrypoint for the ParityRun task (`rate(12 hours)`): `python -m parity_runner --once`
 - `parity/` — 패리티 런 엔진: `catalog.py` (6 surface × 20 feature, `surfaces_for`/`is_applicable`/`_FEATURE_SURFACES`, Bedrock in-region `bedrock:<region>:` 키는 converse + invoke_model만 — v2.32.0), `engine.py` (판정 순수 로직 — `classify_error`, 증거 검사), `probes.py` (surface별 실행기 + `_req_snapshot` 요청 증거, `max_tokens_for` 피처별 예산), `runner.py` (ThreadPoolExecutor 4, 결과 일괄 저장)
 - `gptbench.py` / `gptbench_runner.py` — GPT on AWS 벤치 (`rate(15 minutes)`, `python -m gptbench_runner --once`, v2.18.0): `_BENCH_SPECS` 18채널(Mantle 인리전 us-east-1 7 + CRIS 11, GPT 5.4 제외 v2.39.0, GPT-6 Sol/Luna v2.28.0, GPT-6.1 Sol v2.32.0, GPT-6.1 Terra v2.38.0 — 목록 끝). v2.32.1부터 호스트별 갈래를 동시에 돌린다 — `cris` 11 = 유사 리전 global/us 한 갈래, 인리전은 Mantle 리전마다 한 갈래 `mantle-<region>`(`mantle_lane()`, v2.38.0부터 Mantle 인리전이 us-east-1 하나라 `mantle-us-east-1` 하나뿐(v2.39.0부터 7채널, v2.38.0은 8) — v2.32.1~v2.37.x는 `mantle-us-east-1` 6, `mantle-us-east-2` 3, `mantle-us-west-2` 3, 새 리전은 코드 수정 없이 자기 갈래), 갈래 순서는 cris 다음 Mantle 리전의 첫 채널 순서(v2.32.0은 `cris` 9, `mantle` 12 두 갈래 — 2026-09-30 GPT 5.4 (us-east-2) 저하로 `mantle`이 783초, 802초까지 늘어 us-east-1 끝 채널이 잘리자 사용자 결정으로 분할). 갈래 안은 채널당 워밍업 1 + `GPT_BENCH_RUNS`회 순차(같은 호스트 호출은 겹치지 않는다), 사이클 데드라인은 모든 갈래 공유(넘긴 갈래만 자기 남은 채널 skip), 갈래는 DB를 만지지 않고 메인 스레드가 채널 단위로 커밋, 갈래 대기 상한 = 데드라인 + 호출 상한 + `LANE_JOIN_GRACE_S` 15초(885초, 최선의 상한 — 넘기면 큐에 도착한 진행은 모두 저장, 진행 중 채널은 끝난 회차 저장 후 `라벨 (run N+)`, 시작 못 한 채널은 `라벨`, 예외로 멈춘 갈래도 같음), 로그 `GPT bench lanes: cris=11 mantle-us-east-1=7`(v2.39.0, v2.38.0은 `mantle-us-east-1=8`, v2.37.x까지 `cris=9 mantle-us-east-1=6 mantle-us-east-2=3 mantle-us-west-2=3`)와 갈래마다 `GPT bench lane done: <lane> channels=N elapsed=Ns`; 호출당 wall-clock watchdog(`GPT_BENCH_CALL_TIMEOUT`, 소켓 shutdown 후 close — v2.28.2부터 `stream_watchdog.py` 공용) + `max_retries=0`(v2.28.0), 사이클 데드라인 `GPT_BENCH_DEADLINE`(780초, v2.18.0부터). 채널 키/라벨은 prober 규약 재사용, prober에 모델을 추가해도 벤치에는 자동 반영되지 않는다
+- `model_explorer/` — Model Explorer verification (v2.40.0, ADR-035): `examples.py` (the single source of the `/models` code examples, moved byte for byte from the v2.39.0 frontend `codeExamples` — golden `tests/fixtures/explorer_examples_v2390.json`, nine ids, KO/EN; KO and EN differ only in comment lines; `code_sha` = SHA-256 of the EN code; `API_NAMES`), `execute.py` (`PLACEHOLDERS` → `os.environ[...]` expressions so no secret enters the code text, unknown `"<...>"` or a missing key → skipped, `sys.executable -I example.py` in a fresh temp dir, allow-listed child env (`AWS_*`, the four provider keys, `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR` — never `DB_*` or `JWT_SECRET_KEY`), `EXPLORER_CALL_TIMEOUT_S` 90 s, one retry of a failure, secrets of 8+ characters masked before anything is returned), `runner.py` (visible models × examples, `ThreadPoolExecutor(4)`, rows saved on the main thread, `running` row committed before the sweep, `EXPLORER_RUN_DEADLINE_S` 1,200 s → skipped, 60 runs kept), `diff.py` (`catalog`, `example`, `measured`)
+- `explorer_runner.py` — CLI entrypoint for the scheduled ExplorerVerify task (daily `cron(0 18 * * ? *)` Etc/UTC = 03:00 KST): `python -m explorer_runner --once` registers CP and OpenAI channels, `create_tables()`, runs, ends with `os._exit`; `--smoke [--models a,b] [--json]` runs without the DB and exits 1 on a failed example. `-I` turns off the user site-packages, so run the smoke from a venv that has anthropic, openai and boto3
+- `pricing_changes.py` — run-to-run unit price changes (v2.40.0, ADR-035): `build_snapshot` (called by `run_sync` after `db.flush()`, before the commit — `SessionLocal` has autoflush off — stored as `price_sync_runs.summary["snapshot"]`: per active channel the nine shown prices, the pending fields that differ from them, the run result, family, provider, tier and region), `compare_snapshots` (`channel`, `price`, `pending`, `check` items in table order), `select_runs` (latest `completed`/`partial` run with a snapshot and the run before it, `failed` skipped), `latest_changes` (`/api/pricing` `changes`; the exports leave it out)
 - `features_runner.py` — CLI entrypoint for the scheduled FeaturesVerify task (daily `cron(30 17 * * ? *)` Etc/UTC = 02:30 KST — a fixed wall-clock time; `rate(24 hours)` would anchor to the schedule's creation time): `python -m features_runner --once` (v2.23.0)
 - `claude_features/` — Claude API Features 검증 엔진: `catalog.py` (39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1; 5 surface — cp/mantle/bedrock_messages/bedrock_invoke/bedrock_converse, `documented_for`; 대표 `MODELS` 7종 — Opus 5.5 v2.28.0, Sonnet 5.5 v2.32.0, Haiku 5.5 v2.33.0, 1런 1365셀 = 프로브 1079 + 사전판정 286, `MODELS` 변경 시 `runner.CATALOG_VERSION` 범프 — 현재 `2026-10-07`), `transports.py` (raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화; 스레드 로컬 `record_request`/`last_request`로 마지막 요청 본문을 남겨 `run_probe`가 실패 셀 증거에 회수, v2.24.0), `probes.py` (피처별 프로브), `engine.py` (판정 순수 로직), `runner.py` (ThreadPoolExecutor 4, 60런 보존)
 - `anomalies.py` — 최근 N시간 프로브 실패의 모델별 요약 (`/api/auto-probe/anomalies`, v2.12.0)
@@ -55,7 +58,7 @@ separate scheduled Fargate tasks (reusing this image), NOT in-process.
 - `models.py` — SQLAlchemy ORM models (`PriceHistory`, `PriceSyncRun` since v2.30.0 — created by `create_all`, not the lifespan ALTER block; the seven nullable cache and long-context columns of `PriceHistory` reach existing databases through `pricing_seed.ensure_price_columns`, v2.31.0)
 - `schemas.py` — Pydantic response schemas
 - `database.py` — DB connection, session factory; `connect_args` sets TCP keepalive, `connect_timeout` and `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`, default 30000, per statement — the `yield_per` reads are bounded overall by `streamed_read`)
-- `routers/` — API endpoint handlers (18 router modules)
+- `routers/` — API endpoint handlers (20 router modules since v2.40.0 added `explorer.py`)
 
 ## Commands
 ```bash
diff --git a/backend/routers/CLAUDE.md b/backend/routers/CLAUDE.md
index 1fdd217..2f45223 100644
--- a/backend/routers/CLAUDE.md
+++ b/backend/routers/CLAUDE.md
@@ -1,7 +1,7 @@
 # Backend Routers — API Endpoint Handlers
 
 ## Role
-FastAPI router modules defining all API endpoints (19 router modules, registered in `main.py`; `pricing.py` holds two routers).
+FastAPI router modules defining all API endpoints (20 router modules, registered in `main.py`; `pricing.py` holds two routers).
 `GET /api/health` (public liveness, `{"status": "ok"}`) is defined in `backend/main.py`, not in a router.
 
 ## Files
@@ -19,10 +19,11 @@ FastAPI router modules defining all API endpoints (19 router modules, registered
 - `cost.py` — `/api/cost/*` — summary, channel-compare, trend (`window` ≤ 30d on all three, the Cost page's longest, else 422; the trend streams with `yield_per` into the buckets, summary and channel-compare aggregate in SQL but still scan the window, 2026-09-30; the trend's streamed read is bounded by `streamed_read.stream_rows_or_503`); every row priced at the unit price in effect at its timestamp (`price_history.with_row_cost`, v2.30.0), a model without a price has a null cost, response shapes unchanged; only input and output prices enter the cost, the cache and long-context prices are display-only (v2.31.0); `_channel` maps `bedrock:<region>:<fm-id>` keys to `Bedrock <region>` (`Bedrock ap-northeast-2`, the same name as reliability and the frontend color maps; a malformed key is `Other`, v2.32.0)
 - `reliability.py` — `/api/reliability/multi-channel` — family/channel success rate + error buckets; `_parse_label` channels `Anthropic (CP on AWS)`, `Bedrock Global`, `Bedrock US`, `Bedrock <aws-region>` (a Bedrock label whose parenthesis matches `_AWS_REGION_RE`, e.g. `Bedrock ap-northeast-2` for the Seoul in-region channels, v2.32.0; other non-Global Bedrock labels stay in `Bedrock US`), `OpenAI <region>`, sorted in that order by `_channel_sort_key`; `window` ≤ 7d (the page's longest, else 422), metric columns only with `yield_per` through `streamed_read.stream_rows_or_503`, `error_message` only for non-success rows (2026-09-30)
 - `efficiency.py` — `/api/efficiency/score` — 0-100 weighted Token Efficiency Score per category (cost component = average per-row cost of priced success rows, v2.30.0); `window` ≤ 7d (else 422), metric columns only with `yield_per` through `streamed_read.stream_rows_or_503`, sums stay in Python in row order (SQL AVG would move `round` boundaries and split multi-label models, 2026-09-30)
-- `pricing.py` — `router` `/api/pricing` (public, `build_pricing_payload`, 60 s in-process cache without `lang` in the key; the active set also carries the display-only `openai-list:<family_key>` channels, v2.31.0) and `/api/pricing/export?format=csv|md|json&lang=ko|en` (public, `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<ext>"`); `admin_router` `/api/admin/pricing/pending` (current and new values with the optional cache and long-context fields, a change ratio for every field set on both sides, v2.31.0), `POST /pending/{row_id}/approve`, `POST /pending/{row_id}/reject` (admin only, `effective_from` kept on approve, `warnings` when a verified price comes later in the lookup order `(effective_from, id)`, 404/409 with a Korean `detail`, `invalidate_cache()` after each — other backend tasks can lag up to 60 s; a generation counter keeps a payload built during a clear out of the cache) (v2.30.0, ADR-030)
+- `pricing.py` — `router` `/api/pricing` (public, `build_pricing_payload` plus `changes` from `pricing_changes.latest_changes` (v2.40.0), 60 s in-process cache without `lang` in the key; the active set also carries the display-only `openai-list:<family_key>` channels, v2.31.0) and `/api/pricing/export?format=csv|md|json&lang=ko|en` (public, the payload without `changes`, `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<ext>"`); `admin_router` `/api/admin/pricing/pending` (current and new values with the optional cache and long-context fields, a change ratio for every field set on both sides, v2.31.0), `POST /pending/{row_id}/approve`, `POST /pending/{row_id}/reject` (admin only, `effective_from` kept on approve, `warnings` when a verified price comes later in the lookup order `(effective_from, id)`, 404/409 with a Korean `detail`, `invalidate_cache()` after each — other backend tasks can lag up to 60 s; a generation counter keeps a payload built during a clear out of the cache) (v2.30.0, ADR-030)
 - `analysis.py` — `/api/analysis/*` — stop-reason distribution + output-length histograms. The `/analysis` page calls both at once, and until v2.32.0 each read every success row of the window as a full `ProbeResult` (prompt and output_text included): the default 7d pair OOM-killed the 1 GiB backend task on 2026-09-30 (exit 137). Both now `GROUP BY (model_id, model_name, raw value)` with `count` and `min(id)` — stop reasons are normalized after grouping and merged, output lengths expand to `[value] * count` — so memory is models × distinct values, and ties on `model_name` and the `counts` keys follow first appearance (`min(id)`). `window` ≤ 30d (the page offers 24h, 7d, 30d; longer, 0 or less, or unreadable → 422 via `window_spec.parse_window`, the echoed `window` is the request string). Never load `ProbeResult` entities in a public aggregate endpoint, nor `ProbeRun` entities (their `results` relationship is `selectin`)
 - `parity.py` — `/api/parity/*` — catalog, latest (완료 런 매트릭스 + 직전 런 대비 changes diff, s-maxage=60, v2.39.0부터 현재 런 셀에 `visibility.visible_only` — 모니터링에서 뺀 모델이 다음 런 전에도 매트릭스와 배너에 남지 않는다, 직전 런에만 있는 셀은 `diff_statuses`가 원래 무시), evidence (셀별 증거), trigger (JWT, backend 내 백그라운드 스레드 — 스케줄 런과 달리 Fargate 아님)
 - `gptbench.py` — `/api/gptbench/*` — latest (최신 **완료** 사이클 채널 스코어 카드 — 시작 후 14분 지난 사이클만 완료 — 호스트별 갈래 병렬(v2.32.0 두 갈래, v2.32.1 네 갈래, v2.38.0 Mantle us-east-1 일원화로 `cris`와 `mantle-us-east-1` 두 갈래) 뒤에도 그대로(15분이면 화면 사이클 나이가 프런트 `STALE_AFTER_MS` 30분을 넘는다), 18채널 v2.39.0(19채널 v2.38.0, 21채널 v2.32.0~v2.37.x), `fam_rank` 6.1 Sol, 6.1 Terra(v2.38.0), Astra, Sol, Luna, 5.6 Terra, 5.5(5.4는 v2.39.0에 뺐다), latest와 trend 모두 `visibility.visible_only` — v2.39.0, 지난 GPT 5.4 사이클을 숨긴다), trend?hours= (사이클×채널 median 시계열, `hours` 1~168 — UI 최대 7일, 집계 7컬럼만 튜플 조회. 공개 엔드포인트라 상한이 곧 1요청 메모리 상한이다: 720h 전체 ORM 로드는 18채널에서 ~1 GB RSS로 1 GiB 태스크 OOM 위험) (public, v2.18.0)
+- `explorer.py` — `/api/explorer/latest` (public, `s-maxage=60`: every visible model's examples from `model_explorer.examples` with KO and EN text, the latest completed run's result per `(model_id, api_id)` with `stale_code` when the stored `code_sha` differs from the current example, `changes` against the previous completed run through `model_explorer.diff`, hidden labels filtered with `visible_only`, `running` from a `running` row younger than 30 minutes or this process's manual run) and `POST /api/explorer/trigger` (JWT, daemon thread `explorer-run`, refuses while this process or the DB has a run in progress, closes the request session before the thread starts) (v2.40.0, ADR-035)
 - `features.py` — `/api/features/*` — catalog (39행×5 surface 정의), latest (완료 런 매트릭스 + 직전 런 대비 diff(kind: catalog|measured — 신규 셀, 사전판정 행은 catalog, v2.24.0) + drift), evidence (셀별 요청 스냅샷·응답 신호), trigger (JWT, backend 내 백그라운드 스레드, 7모델 1365셀 약 13분 — v2.33.0) (v2.23.0)
 
 ## Conventions
diff --git a/backend/tests/CLAUDE.md b/backend/tests/CLAUDE.md
index 025b2b2..6dbb91a 100644
--- a/backend/tests/CLAUDE.md
+++ b/backend/tests/CLAUDE.md
@@ -34,6 +34,8 @@ No network beyond 127.0.0.1, no AWS credentials, no PostgreSQL (the PostgreSQL p
   - `test_gptbench.py` since v2.38.0 — the catalog tests pin the production 18-channel spec since v2.39.0 (two lanes, `cris` 11 and `mantle-us-east-1` 7, `test_bench_lanes_production_spec_has_two_lanes`; 19 channels and `mantle-us-east-1` 8 in v2.38.0 — `BENCH_ENV` keeps `BEDROCK_OPENAI_GPT_54_MODEL_ID` because the four-lane spec still reads it, and the production spec ignores it; router fixtures label their rows GPT 5.5, and the ordering test keeps a hidden GPT 5.4 row), while the lane-mechanism tests (several Mantle-region lanes in parallel, a slow host cutting only its own lane, the wait cap, a lane crash, the per-host client cache) run on the frozen v2.32.1~v2.37.x four-lane spec `FOUR_LANE_SPECS` through the `lane_env` fixture, because restoring a Mantle region brings that behaviour back. `test_cost_time_effective.py` keeps its v2.29.1 equivalence on the channels still seeded and pins the nine retired Mantle channels (`RETIRED_V238`) and, since v2.39.0, the twelve channels of the five families left out of monitoring (`RETIRED_V239`, no longer classified — four of them were corrected channels) at no price in a fresh database (production keeps their stored rows)
   - `test_pricing_sources.py`, `test_pricing_seed.py`, `test_pricing_parsers.py`, `test_pricing_sync.py`, `test_pricing_sync_runner.py`, `test_price_history.py`, `test_cost_time_effective.py`, `test_openai_pricing.py`, `test_pricing_payload.py`, `test_pricing_export.py`, `test_pricing_router.py`, `test_pricing_columns.py` (v2.31.0: `ensure_price_columns` idempotence, the PostgreSQL `SET LOCAL` + `ADD COLUMN IF NOT EXISTS` path, the lifespan block-order guard, the background retry: no thread on a first-attempt success, `price-schema-retry` on a column or seed failure, both steps rerun with the same active set, stop at the first success, give up after the last attempt), `test_pricing_seed_extras.py` (v2.31.0: `seed_extra` values, extras on new seed rows, the `COALESCE` fill of NULL extra columns on existing seed rows) — unit prices (v2.30.0, ADR-030; cache, long-context and OpenAI official prices v2.31.0): offline parser fixtures in `fixtures/pricing/` (regenerated from the 2026-09-27 sources, with `openai_pricing.md`; the Claude Opus 5, Sonnet 5, Sonnet 5.5 and GPT 6.1 Sol offers and the Sonnet 5.5 and gpt-6.1-sol doc rows are 2026-09-30; `offers_claude-haiku-5-5.json` and `offers_claude-sonnet-5-5_20261007.json` are 2026-10-07, trimmed to the APN2, EU, USE1, USE2, USW2 and UGE1 dimensions, and `anthropic_pricing.md` has the two Haiku 5.5 rows (up to and over 100,000 tokens) in the standard and batch tables, v2.33.0; `offers_gpt-6.1-terra.json` is the 2026-10-27 offer, `openai_pricing.md` got a gpt-6.1-terra row in its standard and batch tables in the fixture's older column layout (cache writes = the doc's 30m write), and `openai_pricing_20261027.md` is the whole live OpenAI doc of that day with the renamed cache-write columns, v2.38.0; no `offerToken`, `legalTerm.url` or presigned URLs), offer cache and `_long_ctx` dimensions with `cache_read_tokens` over `cached_input_tokens`, `enriched` fills and the per-field 50% gate, `ensure_price_columns` idempotence, sync thresholds (0.5 inclusive: 22 → 33 verified, 22 → 33.01 pending), 6-decimal quantization and zero-rounding rejection, any parser exception → `skipped:parse_failed`, seed coverage of every active channel, time-effective cost joins and the v2.29.1 equivalence copy, `/api/pricing` and export goldens, backend `FAMILY_ORDER` = `frontend/src/lib/sortModels.ts`, `OFFICIAL_LINKS` = `frontend/src/components/PricingPanel.tsx` `OFFICIAL_LINKS` (v2.31.1), the cited-references invariant on a production-shaped payload built from the real seeds of the 49 active channels plus the 9 OpenAI official prices (reference numbers = cell footnotes plus note references, 1..N, 20 references with 17 offers, v2.39.0; 25 in v2.38.0, 24 in v2.33.0, 23 in v2.32.0, 21 in v2.31.1; every OpenAI In Region cell is `["us-east-1"]`), `_plausible_long` (an offer or doc long-context price below the short-context price drops the long fields with a warning, no run error, v2.32.0), Seoul in-region `APN2_*_standard` from the real 2026-09-30 rate cards, GPT US CRIS seed = In Region seed on every price (v2.31.1). Shared data modules `pricing_catalog.py` (the 49 active channels since v2.39.0 — OpenAI Mantle in-region us-east-1 only since v2.38.0 — `RETIRED_V239_MODELS`, the twelve labels left out in v2.39.0, and `CP_MODEL_IDS_20261007`, v2.33.0), `_pricing_dataset.py` (payload and export golden dataset; v2.39.0 moved its families up one name to keep the order and footnote numbers: the former GPT 5.5 rows are GPT 5.6 Luna with `offer-luna0example`, the former GPT 5.4 rows are GPT 5.5 with the real `offer-rtwlbb46hcxpw`, prices unchanged and so fictional for those two) and `_legacy_pricing_v2291.py` (frozen v2.29.1 price table, equivalence test only) are not collected; neither are `_read_dataset.py` (the fixed-clock probe_results dataset behind the read and insights goldens), `_golden_compare.py` (the golden comparison helper) and `_fake_bedrock.py` (the local fake Bedrock runtime, v2.32.2)
   - `test_claude_features.py`, `test_parity_logic.py`, `test_parity_openai_client.py` — verification engines (cell-count pins 1079 + 286 since v2.33.0, Sonnet 5.5 and Haiku 5.5 133 + 62 each; `structured_outputs` and `strict_tool_use` documented `ga` on all five surfaces and `CATALOG_VERSION` `2026-10-20`, v2.34.0)
+  - `test_explorer_examples.py`, `test_explorer_execute.py`, `test_explorer_runner.py`, `test_explorer_router.py` (v2.40.0, ADR-035) — Model Explorer daily verification: the backend examples equal the v2.39.0 frontend `codeExamples` output byte for byte (`fixtures/explorer_examples_v2390.json`, nine ids × KO/EN, dumped by node importing `frontend/src/lib/modelExplorer.ts` at c96a592 — regenerate only for an intended example change), KO and EN differ only in comment lines, `api_id` sets per channel type, 85 examples for the 49 active channels, every placeholder in `execute.PLACEHOLDERS`; real child processes on fake scripts (pass, exception line first, blank output, the timeout kill, the retry, a missing key and an unknown placeholder skipped, no `DB_PASSWORD`/`JWT_SECRET_KEY`/`PYTHONPATH` in the child, secrets masked in stdout and stderr, the temp dir removed); the runner with a fake executor on SQLite (rows and totals, hidden models, the `running` row committed first — the DB-reading fake runs with one worker because the shared in-memory connection is not thread-safe, the run deadline, an executor exception as a failed row, a failed run, 60 runs kept, a prune failure, four at a time) and the CLI; `/api/explorer/latest` (no run, results and `stale_code`, the three change kinds, failed and running runs, the 30-minute running window, hidden models) and the trigger (401, busy in-process and from the DB)
+  - `test_pricing_changes.py` (v2.40.0, ADR-035) — run-to-run price changes from snapshots: price, first-time value, pending start and end, check failure and recovery, other results as ok, a new and a removed channel as one item each, table order, `select_runs` skipping failed runs, `available: false` until the previous run has a snapshot. `test_pricing_sync.py` pins the snapshot `run_sync` stores (shown = `current_rows` at the run end, pending only where it differs, `no_baseline`, two unchanged runs → no change, one change → field items, a failed run without a snapshot); `test_pricing_router.py` the `/api/pricing` `changes` block and the JSON export without it
   - `test_parity_structured_outputs.py` (v2.34.0, AWS structured outputs docs 2026-10-19) — parity `json_schema` sends `output_config.format` (Converse `outputConfig.textFormat` with the schema as a JSON string) and no beta header, a reply with the prompt's `name` key instead of the schema's `city` is broken, `strict_tool_use` sends `strict: true` on all five executors, a string in the integer `count` and a truncated input are broken, the type-conflict prompt goes only to forced-`tool_choice` models, and the 2026-10-20 rejections (Seoul in-region FMs, Nova, GPT Chat Completions function tools) classify as unsupported; fake clients only. `test_parity_logic.py` pins `mantle_fm_id` dropping the Bedrock version suffix (Mantle serves `anthropic.claude-haiku-4-5`, 2026-10-21)
 
 ## Gotchas
diff --git a/cdk/CLAUDE.md b/cdk/CLAUDE.md
index a4b1f69..6fc6a58 100644
--- a/cdk/CLAUDE.md
+++ b/cdk/CLAUDE.md
@@ -13,17 +13,17 @@ services + internal ALB, CloudFront, EventBridge Scheduler tasks and alarms. Cov
 - `lib/stacks/agentcore-stack.ts` — `CfnMemory` (30-day event expiry), memory access policy, SSM `/bedrock-monitor/agentcore-memory-id`
 - `lib/stacks/app-services-stack.ts` — backend (8000, `/api/health`, 300 s health-check grace) and frontend (3000) services, internal ALB with HTTPS:443 and a temporary HTTP:80 listener, `/api/*` → backend at priority 10, backend env + SSM secrets, `ENABLE_OPENAI_1P = false`
 - `lib/stacks/edge-stack.ts` — CloudFront → VPC Origin (currently `HTTP_ONLY` port 80 until the ALB cert is settled), alias `monitorDomain` (default `llm-monitor.whchoi.net`) + `monitorCertArn`; `/api/auto-probe/*` (short edge cache, compression) must stay declared before `/api/*` (no cache, no compression for SSE). No WAF is attached (cdk-nag CFR2 suppressed, deferred to a us-east-1 stack)
-- `lib/stacks/scheduler-stack.ts` — 6 schedules (AutoProber and Insights `rate(5 minutes)`, ParityRun 12 h, GptBench 15 min, FeaturesVerify `cron(30 17 * * ? *)` UTC, PricingSync 12 h); `buildTaskDef` reuses the backend image with a CMD override (512 CPU / 1024 MiB, ARM64); `ANTHROPIC_CP_PROBE_INTERVAL_S=300` (every cycle, v2.29.1; 600 = every other cycle) only on the AutoProber task. PricingSync (v2.30.0, ADR-030) runs `python -m pricing_sync_runner --once` with its own `PricingSyncTaskRole` — only `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts` on `*`, no model invocation — and the same env and secrets as AutoProber (CP discovery and OpenAI registration), log group `/ecs/pricingsync`, output `PricingSyncScheduleName`
+- `lib/stacks/scheduler-stack.ts` — 7 schedules (AutoProber and Insights `rate(5 minutes)`, ParityRun 12 h, GptBench 15 min, FeaturesVerify `cron(30 17 * * ? *)` UTC, PricingSync 12 h, ExplorerVerify `cron(0 18 * * ? *)` UTC since v2.40.0 — `python -m explorer_runner --once` with the autoprober task role and the default env and secrets, log group `/ecs/explorer`, ADR-035); `buildTaskDef` reuses the backend image with a CMD override (512 CPU / 1024 MiB, ARM64); `ANTHROPIC_CP_PROBE_INTERVAL_S=300` (every cycle, v2.29.1; 600 = every other cycle) only on the AutoProber task. PricingSync (v2.30.0, ADR-030) runs `python -m pricing_sync_runner --once` with its own `PricingSyncTaskRole` — only `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts` on `*`, no model invocation — and the same env and secrets as AutoProber (CP discovery and OpenAI registration), log group `/ecs/pricingsync`, output `PricingSyncScheduleName`
 - `lib/stacks/observability-stack.ts` — SNS topic (+ email subscription when `alarmEmail` is set), ALB/ECS/RDS alarms, dashboard
 - `lib/constructs/fargate-service.ts` — task def (default 512/1024, ARM64), circuit breaker with rollback, target group, CPU 70% autoscaling 1..3; `imageOverride` switches to a pinned URI but keeps the legacy repo `grantPull`
 - `lib/constructs/pinned-image.ts` — `repoNameFromImageUri`, `pinnedContainerImage` (`ContainerImage.fromRegistry` + explicit `grantPull` on the parsed repo)
 
 ## Rules
-- Visitor heartbeats require `PRESENCE_ALLOWED_ORIGINS` on the backend and all six shared-image tasks. It comes from the `presenceAllowedOrigins` context (the checked-in value includes the canonical and CloudFront domains); without that context it follows `monitorDomain`. CloudFront replaces Host, so the application cannot infer the public aliases from the origin request.
+- Visitor heartbeats require `PRESENCE_ALLOWED_ORIGINS` on the backend and all seven shared-image tasks. It comes from the `presenceAllowedOrigins` context (the checked-in value includes the canonical and CloudFront domains); without that context it follows `monitorDomain`. CloudFront replaces Host, so the application cannot infer the public aliases from the origin request.
 - Always pass the running images: `-c backendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:<tag>@sha256:<digest>` and `-c frontendImage=…/bedrock-monitor-frontend:<tag>@sha256:<digest>`. Without them AppServices and Scheduler synth `:latest` of the CDK-managed repos (legacy backend repo included — only a synth warning) and a deploy reverts production. Use the full registry host — a bare repo name resolves to docker.io and the deploy rolls back
 - Deploy app changes with `npx cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never -c backendImage=… -c frontendImage=…`; without `--exclusively` CDK also deploys upstream stacks that have diffs. Never `npm run deploy` (`cdk deploy --all` with no image context). Procedure: `docs/runbooks/deploy.md`
 - Scheduler `ecs:RunTask` stays on task-def family `:*` (ADR-011) — a pinned revision fails silently after the next deploy. A new scheduled task adds its family to `RunTaskFamilyWildcard` and its task role to `PassTaskRoles`
-- Backend env is defined twice (`backendEnv` in app-services-stack, `buildTaskDef` in scheduler-stack), and `ENABLE_OPENAI_1P` exists in both files — change both, deploy both stacks (model id envs such as `BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID`, v2.32.0, and `BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID`, v2.38.0, are pinned on the backend and all six scheduled task defs by jest; since v2.39.0 jest also pins that `BEDROCK_OPENAI_GPT_54_MODEL_ID` and the dormant `OPENAI_1P_GPT_54_MODEL_ID` are gone, because GPT 5.4 left monitoring, ADR-034 — a removed env also needs both stacks deployed so the task defs drop it). `OPENAI_US_EAST_2_BASE_URL` and `OPENAI_US_WEST_2_BASE_URL` stay injected although no channel uses them since v2.38.0 (OpenAI Mantle in-region is us-east-1 only, ADR-033), so a region comes back with a prober spec change only
+- Backend env is defined twice (`backendEnv` in app-services-stack, `buildTaskDef` in scheduler-stack), and `ENABLE_OPENAI_1P` exists in both files — change both, deploy both stacks (model id envs such as `BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID`, v2.32.0, and `BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID`, v2.38.0, are pinned on the backend and all seven scheduled task defs by jest; since v2.39.0 jest also pins that `BEDROCK_OPENAI_GPT_54_MODEL_ID` and the dormant `OPENAI_1P_GPT_54_MODEL_ID` are gone, because GPT 5.4 left monitoring, ADR-034 — a removed env also needs both stacks deployed so the task defs drop it). `OPENAI_US_EAST_2_BASE_URL` and `OPENAI_US_WEST_2_BASE_URL` stay injected although no channel uses them since v2.38.0 (OpenAI Mantle in-region is us-east-1 only, ADR-033), so a region comes back with a prober spec change only
 - Bedrock invoke resources stay `arn:aws:bedrock:*::foundation-model/*` — Seoul in-region on-demand channels (`bedrock:ap-northeast-2:…`, v2.32.0, ADR-031) rely on it; do not narrow by region
 - Some test names are stale ("immutable tag", "X86_64"); the assertions check MUTABLE and CPU/memory only
 
diff --git a/frontend/src/components/CLAUDE.md b/frontend/src/components/CLAUDE.md
index 9797930..17fde51 100644
--- a/frontend/src/components/CLAUDE.md
+++ b/frontend/src/components/CLAUDE.md
@@ -23,10 +23,10 @@ React UI components for the monitoring dashboard (monitoring panels, shared UI p
 - `ComparisonView.tsx` — 수동 프로브(`/?view=manual`)의 "비교 분석" 탭: 해당 프로브 결과 비교
 - `ComparePanel.tsx` — Comparison Lab UI (`compareStream` → `/api/compare/run`, N-model parallel invoke); cost per result from `/api/pricing` `models` via `lib/pricingTable.ts` `costFromPrices` (null → "—", left out of the cheapest highlight, v2.30.0); currently not mounted by any page
 - `CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx` — per-page analytical panels (`CostDashboardPanel.CHANNEL_COLORS` and `ReliabilityPanel.CHANNEL_BG` carry the backend channel `"Bedrock ap-northeast-2"` for the Seoul in-region channels, v2.32.0; `ReliabilityPanel` orders families with `sortModels.sortByFamily` (dashboard `FAMILY_ORDER`, unknown families after, alphabetically) because the backend sends them alphabetically, pinned by `e2e/analytics.spec.ts`, v2.32.0; the cost methodology text and the note under the per-model table say prices come from official sources refreshed every 12 hours, the methodology text adds that each probe is costed at the price in effect at its time, and both link to `/pricing`, v2.30.0)
-- `PricingPanel.tsx` — Unit Prices page (`/pricing`, v2.30.0): amber-bordered disclaimer box (`disclaimer[lang]` from the API) with Amazon Bedrock, Anthropic and OpenAI pricing links (OpenAI since v2.31.0), last official price sync ("마지막 공식 단가 동기화" / "Last official price sync" — the shared `RefreshControls` keeps its own "마지막 확인" label for the page fetch) and pending-review count (an `sr-only` comma separates them for screen readers), CSV / Markdown / JSON download links (`pricingExportUrl`), a unit legend once above the tables ("각 단가 셀: 입력 / 출력, 1M 토큰당 USD. 둘째 줄: 프롬프트 캐싱. GPT와 Claude Haiku 5.5 셋째 줄: 긴 컨텍스트" since v2.33.0, `data-unit-legend`), one table per provider in API order (Anthropic Claude → OpenAI → Amazon Nova since v2.31.0) with the columns of `lib/pricingTable.ts` `PROVIDER_COLUMNS` — Anthropic Claude: model | Claude Platform on AWS | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region; OpenAI: model | OpenAI official price ("OpenAI 공식 가격", the display-only `openai_list` tier) | the same three AWS Bedrock columns; Amazon Nova: model | a blank column (`<td aria-hidden="true" data-tier="none">` in the header and every row, no "—") | the same three; a provider the frontend does not know gets `columnsFor`'s default columns (the blank first column and the three AWS Bedrock columns) and is titled by its provider string. Header text is `headerParts(tierLabel(key, lang))`: a two-part title keeps each part `whitespace-nowrap` ("AWS Bedrock -" / "Global CRIS"), while a title without " - " (Claude Platform on AWS, OpenAI 공식 가격 / OpenAI official price) renders through `Runs` and wraps between words as in v2.30.0, so a larger text size does not push it into the next column (e2e: root font size 110% at 390px). Each table has an `sr-only` caption naming it and the unit, e.g. "Anthropic Claude 단가 (입력 / 출력, 1M 토큰당 USD)"; `table-fixed` with one shared `colgroup` (model `w-36` + four equal price columns, `min-w-[800px]`) so all three tables keep the same column positions. A price entry renders `$in / $out` + footnote `[n]` jumping to `#ref-n` with a 1.5 s highlight, then a cache line (`data-cache-line`, `cacheItems`, "캐시 읽기 $0.20, 쓰기 $5.00, 1시간 쓰기 $8.00") and on GPT and Claude Haiku 5.5 rows (v2.33.0) a long-context line (`data-long-line`, `longItems`, "긴 컨텍스트 $20.00 / $75.00, 캐시 읽기 $2.00, 쓰기 $25.00"), both `text-[11px] text-gray-400`, then the model ids and the badges from `tierBadges` with their `detail` as visible gray text beside each badge (the pending detail from `pendingDetail`), and the promo badge footnoting the note's `source_id` reference (the OpenAI pricing page for the GPT-5.6 Sol promotion since v2.31.0); the orange `doc_conflict` badge (`BADGE_CLASS`, v2.33.0, "문서 불일치" / "Source mismatch" on the Claude Sonnet 5.5 Claude Platform on AWS cell, detail "문서 본문과 발표: 캐시 읽기 $0.10") footnotes the Anthropic pricing reference the same way — no `title`-only tooltips), a "모델 ID 보기" / "Show model IDs" `aria-pressed` toggle that lists each price's `model_ids` under it (`data-model-ids`; the price keeps its `title` for mouse hover), notes list (9 items without a trailing period; item 3 since v2.31.1 says GPT's AWS Bedrock - US CRIS and In Region prices are the same, AWS adding 10% to the OpenAI official price on both, and Global CRIS equals the OpenAI official price; item 5 since v2.33.0 says long context applies to GPT requests above OpenAI's short-context limit and to Claude Haiku 5.5 prompts over 100K tokens), references list (`rel="noopener noreferrer"`, manual notes marked; every reference is cited by a footnote and numbered 1..N, cited sources first and manual notes after them — the backend no longer sends the uncited Amazon Bedrock pricing page and OpenAI model card references; the Amazon Bedrock, Anthropic and OpenAI pricing pages stay as links in the top box, and the model cards are not linked anywhere) and the disclaimer again. Wrapping: prose (disclaimer, notes, references, headings, badge details) is `break-keep` so Korean words never split, with `[overflow-wrap:anywhere]` as the fallback for over-long tokens; price pairs, region ids, ISO dates, offer ids and other hyphenated tokens are `whitespace-nowrap` runs (`Runs` over `textRuns`), each region is its own nowrap span so a region list wraps only between items, and a footnote (or reference "↗") is glued to the token before it. Short badges and the pending count never wrap; promotion badges wrap only between words. Only the table container scrolls horizontally on phones (model column fixed, opaque `bg-gray-900` in both themes with a `border-r-gray-800` divider); `PriceTableScroll` (`tableScrollCue`, vitest) shows a hint above an overflowing table ("표를 옆으로 스크롤하면 AWS Bedrock 단가가 보입니다" / "Scroll the table sideways for the AWS Bedrock prices", `data-scroll-hint`, made `invisible` once scrolled so the table does not jump) and a right-edge fade while columns remain on the right (`data-scroll-fade`), because on a phone only the first price column (Claude Platform on AWS, OpenAI official price or the blank Nova column) is in view and the AWS Bedrock prices sit off screen. Inline `L(en, ko)` like the analysis panels
+- `PricingPanel.tsx` — Unit Prices page (`/pricing`, v2.30.0): amber-bordered disclaimer box (`disclaimer[lang]` from the API) with Amazon Bedrock, Anthropic and OpenAI pricing links (OpenAI since v2.31.0), last official price sync ("마지막 공식 단가 동기화" / "Last official price sync" — the shared `RefreshControls` keeps its own "마지막 확인" label for the page fetch) and pending-review count (an `sr-only` comma separates them for screen readers), CSV / Markdown / JSON download links (`pricingExportUrl`), a unit legend once above the tables ("각 단가 셀: 입력 / 출력, 1M 토큰당 USD. 둘째 줄: 프롬프트 캐싱. GPT와 Claude Haiku 5.5 셋째 줄: 긴 컨텍스트" since v2.33.0, `data-unit-legend`), one table per provider in API order (Anthropic Claude → OpenAI → Amazon Nova since v2.31.0) with the columns of `lib/pricingTable.ts` `PROVIDER_COLUMNS` — Anthropic Claude: model | Claude Platform on AWS | AWS Bedrock - Global CRIS | AWS Bedrock - US CRIS | AWS Bedrock - In Region; OpenAI: model | OpenAI official price ("OpenAI 공식 가격", the display-only `openai_list` tier) | the same three AWS Bedrock columns; Amazon Nova: model | a blank column (`<td aria-hidden="true" data-tier="none">` in the header and every row, no "—") | the same three; a provider the frontend does not know gets `columnsFor`'s default columns (the blank first column and the three AWS Bedrock columns) and is titled by its provider string. Header text is `headerParts(tierLabel(key, lang))`: a two-part title keeps each part `whitespace-nowrap` ("AWS Bedrock -" / "Global CRIS"), while a title without " - " (Claude Platform on AWS, OpenAI 공식 가격 / OpenAI official price) renders through `Runs` and wraps between words as in v2.30.0, so a larger text size does not push it into the next column (e2e: root font size 110% at 390px). Each table has an `sr-only` caption naming it and the unit, e.g. "Anthropic Claude 단가 (입력 / 출력, 1M 토큰당 USD)"; `table-fixed` with one shared `colgroup` (model `w-36` + four equal price columns, `min-w-[800px]`) so all three tables keep the same column positions. A price entry renders `$in / $out` + footnote `[n]` jumping to `#ref-n` with a 1.5 s highlight, then a cache line (`data-cache-line`, `cacheItems`, "캐시 읽기 $0.20, 쓰기 $5.00, 1시간 쓰기 $8.00") and on GPT and Claude Haiku 5.5 rows (v2.33.0) a long-context line (`data-long-line`, `longItems`, "긴 컨텍스트 $20.00 / $75.00, 캐시 읽기 $2.00, 쓰기 $25.00"), both `text-[11px] text-gray-400`, then the model ids and the badges from `tierBadges` with their `detail` as visible gray text beside each badge (the pending detail from `pendingDetail`), and the promo badge footnoting the note's `source_id` reference (the OpenAI pricing page for the GPT-5.6 Sol promotion since v2.31.0); the orange `doc_conflict` badge (`BADGE_CLASS`, v2.33.0, "문서 불일치" / "Source mismatch" on the Claude Sonnet 5.5 Claude Platform on AWS cell, detail "문서 본문과 발표: 캐시 읽기 $0.10") footnotes the Anthropic pricing reference the same way — no `title`-only tooltips), a "모델 ID 보기" / "Show model IDs" `aria-pressed` toggle that lists each price's `model_ids` under it (`data-model-ids`; the price keeps its `title` for mouse hover), notes list (9 items without a trailing period; item 3 since v2.31.1 says GPT's AWS Bedrock - US CRIS and In Region prices are the same, AWS adding 10% to the OpenAI official price on both, and Global CRIS equals the OpenAI official price; item 5 since v2.33.0 says long context applies to GPT requests above OpenAI's short-context limit and to Claude Haiku 5.5 prompts over 100K tokens), references list (`rel="noopener noreferrer"`, manual notes marked; every reference is cited by a footnote and numbered 1..N, cited sources first and manual notes after them — the backend no longer sends the uncited Amazon Bedrock pricing page and OpenAI model card references; the Amazon Bedrock, Anthropic and OpenAI pricing pages stay as links in the top box, and the model cards are not linked anywhere) and the disclaimer again. Run-to-run changes (v2.40.0, ADR-035): `ChangesBanner` under the last sync line — gray `data-price-changes="unavailable"` "변경 비교는 다음 동기화부터 표시됩니다." before two snapshot runs exist, `"none"` "이전 동기화(#N, <time>) 대비 변경 없음.", or an amber `<details data-price-changes="list">` (tags `data-change-tag`, 10 items then "외 N건"); an item whose cell is on the page is a button that scrolls to `#price-<family_key>-<tier>` and sets `data-highlighted` for 1.5 s, a removed channel stays text; every price cell has that id (`data-tier` stays its first attribute — `PricingPanel.test.tsx` reads the markup) and a changed cell gets the `changed` badge "이전 대비 변경" (amber) or `new_channel` "신규 채널" (emerald) with its detail as text. No banner when the backend sends no `changes` (older backend). Wrapping: prose (disclaimer, notes, references, headings, badge details) is `break-keep` so Korean words never split, with `[overflow-wrap:anywhere]` as the fallback for over-long tokens; price pairs, region ids, ISO dates, offer ids and other hyphenated tokens are `whitespace-nowrap` runs (`Runs` over `textRuns`), each region is its own nowrap span so a region list wraps only between items, and a footnote (or reference "↗") is glued to the token before it. Short badges and the pending count never wrap; promotion badges wrap only between words. Only the table container scrolls horizontally on phones (model column fixed, opaque `bg-gray-900` in both themes with a `border-r-gray-800` divider); `PriceTableScroll` (`tableScrollCue`, vitest) shows a hint above an overflowing table ("표를 옆으로 스크롤하면 AWS Bedrock 단가가 보입니다" / "Scroll the table sideways for the AWS Bedrock prices", `data-scroll-hint`, made `invisible` once scrolled so the table does not jump) and a right-edge fade while columns remain on the right (`data-scroll-fade`), because on a phone only the first price column (Claude Platform on AWS, OpenAI official price or the blank Nova column) is in view and the AWS Bedrock prices sit off screen. Inline `L(en, ko)` like the analysis panels
 - `InsightsPanel.tsx` — SSE stream-regenerate AI insights
 - `PromptsPanel.tsx` — prompt CRUD + Bedrock OptimizePrompt target selector (17 Bedrock targets since v2.39.0 removed the Global and US Claude Opus 4.7, Opus 4.6, Sonnet 4.6 and Haiku 4.5 entries; includes "Bedrock Claude Sonnet 5.5 (Global)" since v2.32.0, and "Bedrock Claude Haiku 5.5 (Global)", "Bedrock Claude Sonnet 5.5 (US)" and "Bedrock Claude Haiku 5.5 (US)" since v2.33.0 — us-east-1 OptimizePrompt accepts `anthropic.claude-haiku-5-5` and `anthropic.claude-sonnet-5-5`, 2026-10-07)
-- `ModelExplorer.tsx` — 모델 카드 그리드 + 상세 모달 (API 탭: Converse/InvokeModel/Messages/Responses, `lib/modelExplorer.ts` 유도, v2.9.x). 카드 배지는 `ChannelInfo.badge`(Global, US, In-Region, CP, 1P, Mantle 리전 — v2.32.0, 삼항식 대체)다. 카드 단가는 `/api/pricing` `models`를 `lib/pricingTable.ts` 포맷터로 표시("1M in/out" KO/EN 번역, v2.30.0)
+- `ModelExplorer.tsx` — 모델 카드 그리드 + 상세 모달 (API 탭: Converse/InvokeModel/Messages/Responses, `lib/modelExplorer.ts` 유도, v2.9.x). v2.40.0(ADR-035)부터 예제와 검증 결과는 `/api/explorer/latest`(`useAsyncResource` `explorer-latest`)에서 온다: 머리글 "최근 검증 런 #N"(시각, 소요, 통과, 실패, 건너뜀, 실행 중 표시)과 "검증 런 실행" 버튼(비로그인이면 공용 로그인 대화상자), 26시간 경고, 이전 런 대비 변경 배너(`data-explorer-changes`, 항목 → 그 API 탭으로 모달, 카드에 없는 모델은 비활성), 카드 검증 배지(`data-verify-badge` passed/failed/none, `badgeLabel`)와 "변경" 표지(`data-verify-changed`), "검증 실패만" `aria-pressed` 토글(필터 초기화 포함), 모달 탭마다 설명 아래 검증 상자(`data-verify` passed/failed/skipped/none — 통과 소요, 시각, 런, 출력 앞부분; 실패 예외 한 줄과 `<details>` stderr 꼬리, 2회면 "다시 시도 뒤에도 실패"; `stale_code` 안내). explorer API가 실패하면 카드는 그대로 그리고 모달 코드 영역에 `DataError` 재시도를 둔다. 문구는 인라인 `L(en, ko)`. 카드 배지는 `ChannelInfo.badge`(Global, US, In-Region, CP, 1P, Mantle 리전 — v2.32.0, 삼항식 대체)다. 카드 단가는 `/api/pricing` `models`를 `lib/pricingTable.ts` 포맷터로 표시("1M in/out" KO/EN 번역, v2.30.0)
 - `ParityPanel.tsx` — 패리티: provider 요약 카드(세그먼트 막대 `HealthBar`)+Key Findings 드로어, 직전 런 대비 변경 배너, 모델 콤보박스, 피처별 접이식 그룹(분포 바, Broken 자동 펼침), `EvidenceModal`(Request/Response JSON 접이식) + 수동 트리거 (v2.15.x)
 - `ClaudeFeaturesPanel.tsx` — Claude API Features: 5열(CP/Mantle/Bedrock runtime Messages API·InvokeModel·Converse) 매트릭스; 헬스 카드(문서 기준 헬스 docHealth + 6상태 분포 막대 + "{total} 셀" 칩, 클릭 → `SurfaceDrawer` Key Findings 6섹션 — 헤더 sticky, Escape 닫기, 폰 탭아웃 여백); 모델 칩(전체/Fable 5.1/Fable 5/Opus 5.5/Opus 5/Sonnet 5.5/Sonnet 5/Haiku 5.5 — 카탈로그 `models` 순서, Sonnet 5.5 v2.32.0, Haiku 5.5 v2.33.0, `buildGroups(..., modelKey, modelOrder)`·`surfaceFindings(..., modelKey)`, 카드·배너·드로어 동일 필터, 드로어 메타 줄에 모델 라벨); 문서 드리프트 배너(0건이면 "문서 드리프트 없음" 카드); 직전 런 대비 변경 배너(`kind` 카탈로그 규칙/실측 태그, 항목 클릭 → 증거 모달, 0건이면 "변경 없음" 카드); 셀 툴팁 모델별 프로브 소요 시간 + 드롭다운 ms/mono model_id; 상태/드리프트 필터 활성 시 그룹 강제 펼침 + 모두 펼치기/접기; 증거 모달(요청 스냅샷·응답 신호·문서 링크·검증 강도 툴팁); 수동 트리거 (`lib/claudeFeatures.ts` 순수 로직 + vitest, v2.24.0). Mantle에서 측정 불가한 모델(Fable 5.1, Sonnet 5.5, Haiku 5.5)의 사유는 카탈로그 `mantle_reason`(KO)과 `mantle_reason_en`(EN)을 그대로 쓴다 — 표 아래 참조 블록, 안내 문구, Key Findings 모두 US GovCloud를 하드코딩하지 않고, 키가 없는 카탈로그에서는 일반 문구로 떨어진다(v2.32.0). **i18n 예외**: 이 패널과 `ParityPanel`은 `src/lib/i18n.ts` 대신 인라인 `L(en, ko)`/삼항 헬퍼를 쓴다(하위 컴포넌트는 `useLang()` + 로컬 `T`). 라벨은 카탈로그(`labelMaps`)가 단일 출처, 한글 문장은 쉼표 열거·"1." 번호·단정형 판정 문구.
 - `ThemeToggle.tsx` — dark/light theme toggle in `AppHeader` (`lib/theme.ts` `setTheme`/`useTheme`, `aria-pressed`)
diff --git a/frontend/src/lib/CLAUDE.md b/frontend/src/lib/CLAUDE.md
index c877bdf..50ae1c3 100644
--- a/frontend/src/lib/CLAUDE.md
+++ b/frontend/src/lib/CLAUDE.md
@@ -14,12 +14,13 @@ Framework-light modules shared by components: the API client, auth/language prov
 - `monitoring.ts` — card rows and health: `channelKey` (model_id prefix before `:`), `cadenceResolver` (per-channel seconds from `/status` `channel_intervals`, base otherwise), `getFreshness` (stale after cadence + min(cadence, 300 s)), `buildMonitoringRows`, `summarizeMonitoring`, `filterMonitoringRows`
 - `metricGrade.ts` — only source of card grade thresholds (`LATENCY_THRESHOLDS` per workload category, `FALLBACK_LATENCY_THRESHOLDS`, `TPS_THRESHOLD` warn < 40 / crit < 15), `roundForDisplay` (grade what is shown), `GRADE_TEXT_CLASS`, `GRADE_MARKER` (ADR-029). `WORKLOAD_CATEGORY_IDS` mirrors `backend/auto_prober.py` `WORKLOAD_PRESETS`
 - `pricing.ts` — `formatCost` only. v2.30.0 removed `PRICE_TABLE`, `getPricing` and `estimateCost`: unit prices come from `GET /api/pricing` (ADR-030)
-- `pricingTable.ts` — pure helpers for `/pricing` and price display: `tierLabel(key, lang)` (column titles: Claude Platform on AWS, OpenAI 공식 가격 / OpenAI official price, AWS Bedrock - Global CRIS, AWS Bedrock - US CRIS, AWS Bedrock - In Region; `TIER_LABELS` is gone since v2.31.0), `PROVIDER_COLUMNS` (the four price columns of each provider table, `null` = the blank first Nova column) and `columnsFor(provider)` (those columns, or `[null, "global", "us", "in_region"]` for a provider the frontend does not know), `headerParts` ("AWS Bedrock - Global CRIS" → "AWS Bedrock -", "Global CRIS"; a title without " - " is one part, which `PricingPanel` leaves free to wrap between words), `formatUnitPrice` (2 to 6 decimals, zeros past the second trimmed: `$4.00`, `$12.50`, `$1.375`, `$0.0825`; never throws: NaN, ±Infinity and values of 1e21 or more are shown as `$${v}`), `formatPricePair` (`$4.00 / $20.00`), `cacheItems` and `longItems` (the cache and long-context line items of a cell — long context on GPT and, since v2.33.0, Claude Haiku 5.5 — set fields only; `longItems` is empty when `long` is null), `pendingDetail` ("새 값 " / "New value " + the changed items; without the cache read the first cache item gets the cache noun, "새 값 캐시 1시간 쓰기 $17.60" / "New value cache 1h write $17.60", while the cell's cache line keeps "쓰기" / "write"; the Markdown export's pending text follows the same rule), `textRuns(text, glueLast)` (splits display text into runs; price pairs and hyphen-joined tokens up to 32 chars — region ids, ISO dates, offer ids — are `nowrap`, and `glueLast` makes the final word `nowrap` so a footnote stays with it), `tierBadges` (each badge has a `label` and a `detail` the page shows as text next to it, not as a `title` tooltip: "unverified" for `stale` / `seed_only` — detail "공식 출처 확인 <date>" / "Confirmed at source <date>" for `stale`, "공식 출처 확인일 없음" when a `stale` tier has no `observed_at`, "초기값" for `seed_only`; "pending" — detail from `pendingDetail`; promo note — "프로모션 이전 단가 $x / $y" plus `ref` = `note.source_id` (the backend reference id: `openai-pricing` for the GPT-5.6 Sol promotion since v2.31.0, `note:<family_key>` for a manual note; `noteReferenceId` is gone) so the page links the note's footnote; "promo_check" after `min_until`; `doc_conflict` note (v2.33.0) — label "문서 불일치" / "Source mismatch", detail "문서 본문과 발표: 캐시 읽기 $0.10" / "Page text and announcement: cache read $0.10" from the note's `expected`, `ref` = `anthropic-pricing`), `notesForTier` (narrows a promo note's `prior_price` or a doc-conflict note's `expected` to one tier, v2.33.0), `costFromPrices(models, modelId, inputTokens, outputTokens)` (null without a price, Comparison Lab); Model Explorer cards use `formatPricePair`. No sorting and no footnote numbering: the backend sends the order and `n`
+- `explorerVerify.ts` — Model Explorer verification view logic (v2.40.0, ADR-035): `summarizeModel` (passed, failed, skipped, total, grade `passed` | `failed` | `none`), `badgeLabel` ("✓ 3/3 통과", "✗ 1/3 실패", "검증 전", "✓ 2/3 통과, 1 건너뜀"), `statusLabel` (null = "신규"), `changeKindLabel` (신규, 예제 변경, 실측), `summarizeChanges`, `changedModelIds`, `hasFailure` (the "검증 실패만" filter), `splitError` (exception line, stderr tail), `reasonText` (EN text of the backend's Korean messages — "출력 없음", "시간 초과 N초", "자격 증명 미주입: X", "알 수 없는 플레이스홀더", "런 시간 상한"), `formatLatency`
+- `pricingTable.ts` — pure helpers for `/pricing` and price display: `tierLabel(key, lang)` (column titles: Claude Platform on AWS, OpenAI 공식 가격 / OpenAI official price, AWS Bedrock - Global CRIS, AWS Bedrock - US CRIS, AWS Bedrock - In Region; `TIER_LABELS` is gone since v2.31.0), `PROVIDER_COLUMNS` (the four price columns of each provider table, `null` = the blank first Nova column) and `columnsFor(provider)` (those columns, or `[null, "global", "us", "in_region"]` for a provider the frontend does not know), `headerParts` ("AWS Bedrock - Global CRIS" → "AWS Bedrock -", "Global CRIS"; a title without " - " is one part, which `PricingPanel` leaves free to wrap between words), `formatUnitPrice` (2 to 6 decimals, zeros past the second trimmed: `$4.00`, `$12.50`, `$1.375`, `$0.0825`; never throws: NaN, ±Infinity and values of 1e21 or more are shown as `$${v}`), `formatPricePair` (`$4.00 / $20.00`), `cacheItems` and `longItems` (the cache and long-context line items of a cell — long context on GPT and, since v2.33.0, Claude Haiku 5.5 — set fields only; `longItems` is empty when `long` is null), `pendingDetail` ("새 값 " / "New value " + the changed items; without the cache read the first cache item gets the cache noun, "새 값 캐시 1시간 쓰기 $17.60" / "New value cache 1h write $17.60", while the cell's cache line keeps "쓰기" / "write"; the Markdown export's pending text follows the same rule), `textRuns(text, glueLast)` (splits display text into runs; price pairs and hyphen-joined tokens up to 32 chars — region ids, ISO dates, offer ids — are `nowrap`, and `glueLast` makes the final word `nowrap` so a footnote stays with it), `tierBadges` (each badge has a `label` and a `detail` the page shows as text next to it, not as a `title` tooltip: "unverified" for `stale` / `seed_only` — detail "공식 출처 확인 <date>" / "Confirmed at source <date>" for `stale`, "공식 출처 확인일 없음" when a `stale` tier has no `observed_at`, "초기값" for `seed_only`; "pending" — detail from `pendingDetail`; promo note — "프로모션 이전 단가 $x / $y" plus `ref` = `note.source_id` (the backend reference id: `openai-pricing` for the GPT-5.6 Sol promotion since v2.31.0, `note:<family_key>` for a manual note; `noteReferenceId` is gone) so the page links the note's footnote; "promo_check" after `min_until`; `doc_conflict` note (v2.33.0) — label "문서 불일치" / "Source mismatch", detail "문서 본문과 발표: 캐시 읽기 $0.10" / "Page text and announcement: cache read $0.10" from the note's `expected`, `ref` = `anthropic-pricing`), `notesForTier` (narrows a promo note's `prior_price` or a doc-conflict note's `expected` to one tier, v2.33.0), `costFromPrices(models, modelId, inputTokens, outputTokens)` (null without a price, Comparison Lab); run-to-run changes (v2.40.0): `changeKindTag` (`applied`, `pending`, `released`, `check_failed`, `check_recovered`, `new_channel`, `left_channel`), `changeTagLabel` (적용, 검토 대기, 검토 해제, 확인 실패, 확인 복구, 신규 채널, 제외 채널), `changeItemText` ("Claude Sonnet 5.5, AWS Bedrock - Global CRIS, 캐시 읽기 $0.20 → $0.10"; In Region names its region; a CP or OpenAI official price parse failure is "문서 파싱 실패"), `priceCellId` (`price-<family_key>-<tier>`), `cellChangeBadge` (kind `changed` "이전 대비 변경" with the cell's first change and ", 외 N건", or `new_channel`); Model Explorer cards use `formatPricePair`. No sorting and no footnote numbering: the backend sends the order and `n`
 - `fabVisibility.ts` — the floating chat button's show/hide rule (v2.31.1, user decision "스크롤 시 숨김"), pure and vitest-covered: `nextFabState(state, event)` over `window` scroll (8px `FAB_SCROLL_DELTA_PX` down hides, 8px up shows, accumulated since the last direction change; top `scrollY <= FAB_TOP_PX` 16 and bottom `innerHeight + scrollY >= scrollHeight - FAB_BOTTOM_SLACK_PX` 4 always show), `horizontal` (a horizontal scroll inside `<main>` — the hook ignores elements outside it, such as the header menu scrolling to its active item; hides, except at the page bottom, where `<main>`'s bottom padding keeps the button off the content and a page that cannot scroll would otherwise lose the button) and `show` (focus, modal open or closed); `isFabVisible` adds focus and an open modal; `isHorizontalScroll(previousLeft, scrollLeft)`. Wired by `hooks/useChatFabVisibility.ts`
 - `pivotTrend.ts` — `pivotTrend` to Recharts wide rows + per-series data; `cadenceSeconds` (number or per-model function) breaks a line after a longer silence; `isolatedSampleTimes` keeps lone samples visible
 - `trendSelection.ts` — `defaultTrendSelection` (one line per family), `buildTrendQuery` / `parseTrendQuery` (models/hours/category in the URL, `models=all` sentinel)
 - `claudeFeatures.ts` — `/claude-features` types and pure logic (`aggregateCell`, `buildGroups`, `surfaceSummary`, `surfaceFindings`, `labelMaps`, change-kind summary, latency helpers); mirrors `backend/claude_features/engine.py` status/verdict vocabulary. `ModelDef.mantle_reason_en?` (v2.32.0): the EN Mantle N/A reason comes from the catalog, with a generic fallback when the key is absent
-- `modelExplorer.ts` — `channelOf`, `nativeId`, `codeExamples`, `modelLinks` per model-id scheme (Bedrock profile, Bedrock in-region `bedrock:<region>:<fm id>` since v2.32.0 — type `bedrock`, endpoint `https://bedrock-runtime.<region>.amazonaws.com`, `nativeId` keeps `:` inside the FM id, code examples and the console link use the key's region, `anthropic:`, `openai:<region|global|us|1p>:`), `ChannelInfo.badge` (card badge: Global, US, In-Region, CP, 1P or the Mantle region, v2.32.0), KO/EN via `lang`. Every example must run as pasted — all 118 for the 66 active channels were run live on 2026-10-19 (49 active since v2.39.0): profile keys call from the prober `_REGION_MAP` region (`profileRegion` — `global.*` ap-northeast-2, `us.*` us-east-1; a `us.*` profile called from ap-northeast-2 is "The provided model identifier is invalid"), and the endpoint and console link follow it; the CP header is `anthropic-workspace-id` (`prober._anthropic_default_headers`; `anthropic-workspace` is a 400); the InvokeModel example joins the `text` blocks, because Opus 5 and Fable 5 return a signature-only `thinking` block first
+- `modelExplorer.ts` — `channelOf`, `nativeId`, `modelLinks` per model-id scheme (`codeExamples` moved to the backend in v2.40.0: `backend/model_explorer/examples.py` is the single source and `/api/explorer/latest` sends the examples, ADR-035 — the rules below now live there and are pinned by `backend/tests/test_explorer_examples.py`) (Bedrock profile, Bedrock in-region `bedrock:<region>:<fm id>` since v2.32.0 — type `bedrock`, endpoint `https://bedrock-runtime.<region>.amazonaws.com`, `nativeId` keeps `:` inside the FM id, code examples and the console link use the key's region, `anthropic:`, `openai:<region|global|us|1p>:`), `ChannelInfo.badge` (card badge: Global, US, In-Region, CP, 1P or the Mantle region, v2.32.0), KO/EN via `lang`. Every example must run as pasted — all 118 for the 66 active channels were run live on 2026-10-19 (49 active since v2.39.0): profile keys call from the prober `_REGION_MAP` region (`profileRegion` — `global.*` ap-northeast-2, `us.*` us-east-1; a `us.*` profile called from ap-northeast-2 is "The provided model identifier is invalid"), and the endpoint and console link follow it; the CP header is `anthropic-workspace-id` (`prober._anthropic_default_headers`; `anthropic-workspace` is a 400); the InvokeModel example joins the `text` blocks, because Opus 5 and Fable 5 return a signature-only `thinking` block first
 - `format.ts` (`parseTimestamp` treats offset-less DB timestamps as UTC, `formatDateTime`, `formatAge`), `costProjection.ts` (30-day projection), `theme.ts` (`html.light` + `localStorage.theme`, `useTheme`), `chartTheme.ts` (Recharts colors per theme), `types.ts` (shared API types; `PricingNote` is the union `PricingPromoNote | PricingDocConflictNote` since v2.33.0 — narrow on `kind` before reading `prior_price`, `min_until` or `expected`)
 - `dialogFocus.ts` — shared modal Tab containment for search/detail, login and chat. `theme.ts` defaults to light, honors saved settings before hydration, synchronizes tabs and preserves session-only changes when storage writes fail.
 - `version.ts` — `APP_VERSION`, canonical app version shown in every header (bump list in root CLAUDE.md)
````
- [ ] **Step 4:** Run:

```bash
grep -c "ExplorerVerify" docs/architecture.md docs/runbooks/deploy.md cdk/CLAUDE.md CLAUDE.md && grep -n "·" docs/decisions/ADR-035-pricing-changes-and-explorer-verify.md | head -3
```

Expected: every count ≥ 1; the second grep prints nothing (no middle dots in the new Korean text).
- [ ] **Step 5:** Commit:

```bash
git add docs/decisions/ADR-035-pricing-changes-and-explorer-verify.md \
  docs/architecture.md \
  docs/api-reference.md \
  docs/runbooks/deploy.md \
  CLAUDE.md \
  backend/CLAUDE.md \
  backend/routers/CLAUDE.md \
  backend/tests/CLAUDE.md \
  cdk/CLAUDE.md \
  frontend/src/lib/CLAUDE.md \
  frontend/src/components/CLAUDE.md
git commit -m "docs: ADR-035, explorer API, pricing changes, ExplorerVerify runbook and module notes"
```
---

### Task 12: Release v2.40.0 — version strings and CHANGELOG

**Files:**
- Modify: `frontend/src/lib/version.ts`, `backend/main.py` (`version=`), `frontend/package.json`, `frontend/package-lock.json` (2 places), `README.md` (badge), `CLAUDE.md` (overview), `CHANGELOG.md` (the `Unreleased` History-dialog entry moves under v2.40.0 with the new entries)
- [ ] **Step 1:** Apply this change to `frontend/src/lib/version.ts`, `frontend/package.json`, `frontend/package-lock.json`, `README.md`, `CHANGELOG.md` (unified diff against `c96a592`; apply with `git apply` from the repo root or edit by hand — the hunks are exact).

````diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 7c183fd..451cd26 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -7,12 +7,26 @@
 - 카테고리: `Added` / `Changed` / `Fixed` / `Removed` / `Security` / `Infra` / `Docs`
 - 매 commit 시 PR 또는 작업 종료 시 한 항목 추가.
 
-## Unreleased
+## v2.40.0 — 2026-11-05
+
+### Added
+- Model Explorer runs every code example once a day and shows the result, by user request on 2026-11-05: the ExplorerVerify task (daily at 18:00 UTC, 03:00 KST) executes the 85 examples of the 49 monitored channels as shown (Converse, InvokeModel, Messages, Responses), and `/models` shows the latest run, a verification badge per card ("✓ 3/3 passed", "✗ 1/3 failed", "Not verified"), a "Failures only" filter, the changes since the previous run (new, example changed, measured) and, in the detail dialog, each example's result (time, output, the exception line and stderr tail of a failure). New `GET /api/explorer/latest` and `POST /api/explorer/trigger`.
+- `/pricing` shows what changed since the previous price sync, by user request on 2026-11-05: applied prices, pending reviews and their end, source check failures and recoveries, and new or removed channels, under the last sync line. An item scrolls to its price cell, and a changed cell carries a "Changed since last sync" badge. `/api/pricing` adds `changes`; the CSV, Markdown and JSON exports are unchanged.
+- 사용자 요청(2026-11-05)으로 모델 탐색이 코드 예제를 매일 한 번 실행해 결과를 보여 준다. ExplorerVerify 태스크(매일 18:00 UTC, 03:00 KST)가 모니터링 중인 49채널의 예제 85개(Converse, InvokeModel, Messages, Responses)를 화면에 보이는 그대로 실행하고, `/models`에 최근 런, 카드마다 검증 배지("✓ 3/3 통과", "✗ 1/3 실패", "검증 전"), "검증 실패만" 필터, 이전 런 대비 변경(신규, 예제 변경, 실측), 상세 모달의 예제별 결과(소요, 출력, 실패의 예외 한 줄과 stderr 꼬리)를 보인다. 새 API `GET /api/explorer/latest`, `POST /api/explorer/trigger`.
+- 사용자 요청(2026-11-05)으로 `/pricing`이 이전 동기화 대비 바뀐 내용을 마지막 동기화 상자 아래에 보인다. 적용된 단가, 검토 대기와 해제, 출처 확인 실패와 복구, 신규, 제외 채널이다. 항목을 누르면 그 단가 셀로 이동하고, 바뀐 셀에는 "이전 대비 변경" 배지가 붙는다. `/api/pricing`에 `changes`를 더했고 CSV, Markdown, JSON 내보내기는 그대로다.
 
 ### Changed
+- The Model Explorer code examples are generated by the backend (`backend/model_explorer/examples.py`), so the page shows the code the daily run executes. They are byte-identical to the v2.39.0 frontend examples (pinned by a golden test); the frontend `codeExamples` is removed.
+- Every price sync run stores the table it ends with (`price_sync_runs.summary.snapshot`), which the change list compares. The first comparison appears after the second sync that follows the deploy.
+- 모델 탐색 코드 예제를 백엔드(`backend/model_explorer/examples.py`)가 만든다. 그래서 화면의 코드가 매일 검증 런이 실행하는 코드다. v2.39.0 프런트 예제와 바이트 단위로 같고(골든 테스트로 고정), 프런트 `codeExamples`는 지웠다.
+- 단가 동기화 런마다 끝난 시점의 표를 저장한다(`price_sync_runs.summary.snapshot`). 변경 목록은 이것을 비교하며, 배포 뒤 두 번째 동기화부터 나온다.
 - The History dialog lists the same channels as the dashboard's model monitoring, by user request on 2026-10-29: it asks `/api/results/stats?active_only=true`, which keeps only the channels of the current catalog (`/api/models`, 49). Before, its 7-day and 30-day ranges also showed the seven OpenAI Mantle us-east-2 and us-west-2 channels whose collection stopped in v2.38.0 (56 in production). Without `active_only` the endpoint answers as before, and the stored rows are kept.
 - 사용자 요청(2026-10-29)으로 이력 조회 화면이 대시보드 모델 모니터링과 같은 채널만 보인다. `/api/results/stats?active_only=true`로 현행 카탈로그(`/api/models`, 49개) 채널만 집계한다. 전에는 7일, 30일 범위에 v2.38.0에서 수집을 멈춘 OpenAI Mantle us-east-2, us-west-2 채널 7개가 함께 나왔다(운영 56개). `active_only`를 보내지 않으면 응답은 예전과 같고, 저장 행은 그대로 둔다.
 
+### Infra
+- New scheduled task ExplorerVerify (`python -m explorer_runner --once`, `cron(0 18 * * ? *)` Etc/UTC, autoprober task role, log group `/ecs/explorer`) and its family in the scheduler role's RunTask wildcard — deploy both the AppServices and the Scheduler stacks. New tables `explorer_runs` and `explorer_results` come from `create_all`. No new environment variable or IAM policy (ADR-035).
+- 새 스케줄 태스크 ExplorerVerify(`python -m explorer_runner --once`, `cron(0 18 * * ? *)` Etc/UTC, autoprober task role, 로그 그룹 `/ecs/explorer`)와 Scheduler 역할 RunTask 와일드카드의 새 family를 더했다. AppServices와 Scheduler 두 스택을 함께 배포한다. 새 테이블 `explorer_runs`, `explorer_results`는 `create_all`이 만든다. 새 환경 변수와 IAM 정책은 없다(ADR-035).
+
 ## v2.39.0 — 2026-10-27
 
 ### Removed
diff --git a/README.md b/README.md
index bd5effd..62762e1 100644
--- a/README.md
+++ b/README.md
@@ -1,7 +1,7 @@
 # Amazon Bedrock LLM Monitor
 
 ![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
-[![Version](https://img.shields.io/badge/version-2.39.0-blue.svg)](CHANGELOG.md)
+[![Version](https://img.shields.io/badge/version-2.40.0-blue.svg)](CHANGELOG.md)
 [![Build](https://img.shields.io/badge/build-CDK%20%7C%20Docker-success)](docs/runbooks/deploy.md)
 <a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
 <a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>
diff --git a/frontend/package-lock.json b/frontend/package-lock.json
index 2ffe48d..7b5d93f 100644
--- a/frontend/package-lock.json
+++ b/frontend/package-lock.json
@@ -1,12 +1,12 @@
 {
   "name": "bedrock-monitor",
-  "version": "2.39.0",
+  "version": "2.40.0",
   "lockfileVersion": 3,
   "requires": true,
   "packages": {
     "": {
       "name": "bedrock-monitor",
-      "version": "2.39.0",
+      "version": "2.40.0",
       "dependencies": {
         "next": "16.3.5",
         "react": "^18.3.0",
diff --git a/frontend/package.json b/frontend/package.json
index ba2ef95..b5e54ab 100644
--- a/frontend/package.json
+++ b/frontend/package.json
@@ -1,6 +1,6 @@
 {
   "name": "bedrock-monitor",
-  "version": "2.39.0",
+  "version": "2.40.0",
   "private": true,
   "scripts": {
     "dev": "next dev -p 3000",
diff --git a/frontend/src/lib/version.ts b/frontend/src/lib/version.ts
index 44bfd13..fabed77 100644
--- a/frontend/src/lib/version.ts
+++ b/frontend/src/lib/version.ts
@@ -1,3 +1,3 @@
 // 단일 source of truth — CHANGELOG.md의 최신 release와 동기화.
 // 새 버전 release 시 이 파일을 갱신하면 모든 페이지 헤더에 즉시 반영된다.
-export const APP_VERSION = "v2.39.0";
+export const APP_VERSION = "v2.40.0";
````
- [ ] **Step 2:** Bump the backend and the root CLAUDE.md overview:

````diff
diff --git a/backend/main.py b/backend/main.py
index 6302c34..f325db2 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -319,7 +320,7 @@ app = FastAPI(
     title="Bedrock Model Monitoring",
     description="Monitor latency, throughput, and reliability of AWS Bedrock LLM models.",
     # OpenAPI(/docs)에 노출되는 런타임 버전 — 릴리스 시 CLAUDE.md "Version strings" 목록과 함께 범프.
-    version="2.39.0",
+    version="2.40.0",
     lifespan=lifespan,
 )
 
diff --git a/CLAUDE.md b/CLAUDE.md
index 384a5e0..fc482f3 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -2,7 +2,7 @@
 
 ## Project Overview / 프로젝트 개요
 
-**Amazon Bedrock LLM Monitor** (v2.39.0 — 현재 버전은 `frontend/src/lib/version.ts`가 source of truth) — A real-time dashboard for response speed, throughput, reliability, cost, and output-quality monitoring of AWS Bedrock + Anthropic CP on AWS + OpenAI (Mantle/1P) LLM channels.
+**Amazon Bedrock LLM Monitor** (v2.40.0 — 현재 버전은 `frontend/src/lib/version.ts`가 source of truth) — A real-time dashboard for response speed, throughput, reliability, cost, and output-quality monitoring of AWS Bedrock + Anthropic CP on AWS + OpenAI (Mantle/1P) LLM channels.
 
 **Amazon Bedrock LLM 모니터** — Bedrock + Anthropic CP on AWS 채널의 응답 속도·처리량·신뢰성·비용·출력 품질을 실시간으로 모니터링하는 대시보드.
 
@@ -12,7 +12,7 @@
 - **Frontend**: Next.js 16 standalone + React + Tailwind + Recharts + react-markdown + FloatingChat + PWA(iPhone/iPad 홈 화면 설치 — manifest.ts·앱 아이콘·safe-area, v2.21.0)
 - **Infra**: CDK v2 TypeScript / 8 stacks (Network, Data, Cluster, AgentCore, AppServices, Edge, Scheduler, Observability)
 - **Edge**: CloudFront VPC Origin → Internal ALB → ECS Fargate × 2 (backend, frontend). VPC Origin → ALB는 현재 VPC 내부 HTTP:80(`edge-stack.ts` `HTTP_ONLY`, 운영 cert 정착 전 임시 — ALB는 internal + private subnet + VPC CIDR SG), ALB에는 HTTPS:443 리스너도 있음
-- **Scheduling**: EventBridge Scheduler → AutoProber + Insights (`rate(5 minutes)`, Claude Platform on AWS 채널도 매 사이클 — v2.29.1에서 v2.29.0의 10분 주기를 되돌림) + ParityRun (12시간 주기) + GptBench (`rate(15 minutes)`) + FeaturesVerify (매일 17:30 UTC) + PricingSync (`rate(12 hours)`, 공식 단가 동기화 — v2.30.0, OpenAI 공식 문서 출처와 캐시, 긴 컨텍스트 단가 v2.31.0) Fargate Tasks — `cdk/lib/stacks/scheduler-stack.ts`
+- **Scheduling**: EventBridge Scheduler → AutoProber + Insights (`rate(5 minutes)`, Claude Platform on AWS 채널도 매 사이클 — v2.29.1에서 v2.29.0의 10분 주기를 되돌림) + ParityRun (12시간 주기) + GptBench (`rate(15 minutes)`) + FeaturesVerify (매일 17:30 UTC) + PricingSync (`rate(12 hours)`, 공식 단가 동기화 — v2.30.0, OpenAI 공식 문서 출처와 캐시, 긴 컨텍스트 단가 v2.31.0) + ExplorerVerify (매일 18:00 UTC, 모델 탐색 코드 예제 실행 검증 — v2.40.0) Fargate Tasks — `cdk/lib/stacks/scheduler-stack.ts`
 - **AI**: Claude Haiku 5.5 공개 챗봇 (4 tools) + Haiku 5.5 dynamic followups + Haiku 5.5 인사이트 잡 (KO·EN 요약) — 모델 ID는 `backend/agent/bedrock.py` `CHAT_MODEL_ID`/`INSIGHTS_MODEL_ID`, followups는 `backend/routers/chat.py` `_generate_followups`가 source of truth. Haiku 5.5 요청은 temperature를 보내지 않는다(v2.37.0). 인사이트는 확장 추론을 끄고 `INSIGHTS_MAX_TOKENS=16384`로 전체 표·설명을 완성한다. 챗봇도 확장 추론을 끄고 `CHAT_MAX_TOKENS=4096`을 쓰며, 출력 한도에서 끝난 답은 `warning` 이벤트로 알린다(2026-10-25 — 기본 추론이 도구 결과 뒤 1024토큰을 다 써 본문 없이 끝났다). 후속 질문은 기본 설정 그대로다
 
 자세한 v2 설계는 [`docs/architecture.md`](./docs/architecture.md) / [`docs/decisions/ADR-*.md`](./docs/decisions/) / [`.kiro/specs/v2-upgrade/`](./.kiro/specs/v2-upgrade/) (v2.0.0 당시 설계 기록 — 9개 모델, 인사이트 30분 주기 기준이라 현행과 다름).
@@ -32,11 +32,11 @@ Internal ALB
                 ├── /chat         — 챗봇 팝업 창 진입점 (Firefox/Safari, FloatingChat이 연다)
                 ├── /prompts      — Prompt CRUD + Bedrock OptimizePrompt (auth)
                 ├── /cost         — 30-day projection + per-model + channel compare (프로브 시각의 단가로 계산, v2.30.0)
-                ├── /pricing      — 비용 단가 (표 순서 Anthropic → OpenAI → Amazon Nova, 모델 패밀리 × 채널 Standard 입력/출력 단가 + 셀 둘째 줄 프롬프트 캐싱, GPT와 Claude Haiku 5.5 셋째 줄 긴 컨텍스트(표시 전용, Haiku 5.5 v2.33.0) + OpenAI 표 첫 열 OpenAI 공식 가격, Nova 표 첫 열 빈칸 + 번호 각주 출처 + CSV/Markdown/JSON 다운로드 + 면책 문구, 12시간 자동 갱신, v2.30.0, 열 이름과 캐시 v2.31.0)
+                ├── /pricing      — 비용 단가 (표 순서 Anthropic → OpenAI → Amazon Nova, 모델 패밀리 × 채널 Standard 입력/출력 단가 + 셀 둘째 줄 프롬프트 캐싱, GPT와 Claude Haiku 5.5 셋째 줄 긴 컨텍스트(표시 전용, Haiku 5.5 v2.33.0) + OpenAI 표 첫 열 OpenAI 공식 가격, Nova 표 첫 열 빈칸 + 번호 각주 출처 + CSV/Markdown/JSON 다운로드 + 면책 문구, 12시간 자동 갱신, v2.30.0, 열 이름과 캐시 v2.31.0, 이전 동기화 대비 변경 배너와 셀 배지 v2.40.0)
                 ├── /reliability  — Family/channel success rate + error buckets
                 ├── /efficiency   — 0-100 Token Efficiency Score (weighted)
                 ├── /analysis     — Stop reason 분포 + Output length 분포
-                ├── /models       — Model Explorer (모델 카드 + 코드 예제 + 링크, v2.9.0)
+                ├── /models       — Model Explorer (모델 카드 + 코드 예제 + 링크, v2.9.0; 코드 예제는 백엔드 단일 출처, 매일 실행 검증 배지, 이전 런 대비 변경 배너, 검증 실패만 필터 v2.40.0)
                 ├── /parity       — Parity Run (모델×surface×피처 실행-증거 매트릭스, v2.11.0)
                 ├── /gpt-on-aws   — GPT on AWS (GPT 18채널 TTFB/TTFT 벤치 — Mantle 인리전 us-east-1 7 + CRIS 11 — Terra Global 포함 v2.20.1, GPT-6 Astra 3채널 v2.25.1, GPT-6 Sol/Luna 6채널 v2.28.0, GPT-6.1 Sol 3채널 v2.32.0, CRIS와 Mantle 두 갈래 병렬 v2.32.0, Mantle 리전별 갈래 분할(cris + mantle-<region>, 네 갈래) v2.32.1, GPT-6.1 Terra 3채널과 Mantle 인리전 us-east-1 일원화(cris, mantle-us-east-1 두 갈래) v2.38.0, GPT 5.4 제외 v2.39.0, 15분 주기)
                 └── /claude-features — Claude API Features (33 문서 피처 × CP/Mantle/Bedrock(Messages API·InvokeModel·Converse) × 대표 7모델 실행-증거 + 문서 드리프트, v2.23.0; Opus 5.5 편입 v2.28.0, Sonnet 5.5 편입 v2.32.0, Haiku 5.5 편입 v2.33.0)
@@ -52,7 +52,8 @@ EventBridge Scheduler (rate 5 min)
   │                              v2.38.0부터 Mantle 인리전이 us-east-1 하나라 갈래도 둘이다(cris 11 = Global 6 + US 5, mantle-us-east-1 8 — 로그 `GPT bench lanes: cris=11 mantle-us-east-1=8`, 사용자 결정 2026-10-27, ADR-033). 리전을 되살리면 코드 수정 없이 그 리전 갈래가 다시 생긴다
   │                              v2.39.0에서 GPT 5.4(mantle-us-east-1 첫 채널)를 빼 mantle-us-east-1은 7채널이다(로그 `GPT bench lanes: cris=11 mantle-us-east-1=7`, 사이클당 180행, 사용자 결정 2026-10-27, ADR-034)
   ├── FeaturesVerify Fargate Task → 일 1회(cron 17:30 UTC = 02:30 KST 고정, v2.29.0) Claude API Features 39행(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1) × 5 surface × 대표 7모델 = 1365셀 실행-증거 스윕 (v2.23.0; Opus 5.5 편입 v2.28.0, Sonnet 5.5 편입 v2.32.0, Haiku 5.5 편입 v2.33.0)
-  └── PricingSync Fargate Task → 12시간 주기(rate(12 hours)) 공식 단가 동기화 — Bedrock agreement offer rate card + AWS Price List + Anthropic pricing.md + OpenAI pricing.md(v2.31.0) → price_history, 활성 49채널 + OpenAI 공식 가격 9채널(`openai-list:<family_key>`, 표시 전용, v2.39.0 — 로그 `58 active channels`)의 입력, 출력, 캐시, 긴 컨텍스트 단가 (어느 필드든 50% 초과 변경은 관리자 승인 대기, 빈 필드 첫 관측은 현재 행 채움 `enriched`, v2.30.0, ADR-030)
+  ├── ExplorerVerify Fargate Task → 일 1회(cron 18:00 UTC = 03:00 KST 고정, v2.40.0) 모델 탐색 코드 예제 85건(활성 49채널)을 예제마다 자식 Python(-I, 허용 목록 env)에서 실행 — explorer_runs/explorer_results, 동시 4, 호출당 90초, 실패 1회 재시도 (ADR-035)
+  └── PricingSync Fargate Task → 12시간 주기(rate(12 hours)) 공식 단가 동기화 — Bedrock agreement offer rate card + AWS Price List + Anthropic pricing.md + OpenAI pricing.md(v2.31.0) → price_history, 활성 49채널 + OpenAI 공식 가격 9채널(`openai-list:<family_key>`, 표시 전용, v2.39.0 — 로그 `58 active channels`)의 입력, 출력, 캐시, 긴 컨텍스트 단가 (어느 필드든 50% 초과 변경은 관리자 승인 대기, 빈 필드 첫 관측은 현재 행 채움 `enriched`, v2.30.0, ADR-030; 런마다 화면 값 스냅샷 `summary.snapshot` → `/api/pricing` `changes`, v2.40.0, ADR-035)
 
 Backend ↔ Bedrock (Seoul region inference profiles us.*, global.* + 서울 in-region 온디맨드 FM bedrock:ap-northeast-2:* (v2.32.0)) + Anthropic CP on AWS + OpenAI (Bedrock Mantle + 1P direct api.openai.com)
                                   (aws-external-anthropic.us-east-2.api.aws, workspace-id header)
@@ -86,6 +87,7 @@ model-monitoring/
 │   ├── pricing_sync.py      # 12시간 동기화 — 가져오기, 관측 값 소수 6자리 정규화, 비교(classify_change — 9필드 필드별, CHANGE_THRESHOLD 0.5 경계 포함, 빈 필드 첫 관측은 새 행 없이 현재 행 채움 `enriched`), pending_review, price_sync_runs 기록, 상한 300초. 파서 예외는 종류와 상관없이 그 출처 채널만 skipped:parse_failed(v2.31.0: 문서 표는 찾는 모델 행만 하나씩 정규화해 값이 이상한 추적 모델은 자기 채널만 skipped:parse_failed, 긴 컨텍스트 필드는 `_long_context_gate`(v2.33.0, 구 `_gpt_long_only`)가 OpenAI 채널과 Claude Haiku 5.5 채널만 남김 — offer, 문서, Price List 경로 공통)
 │   ├── pricing_sync_runner.py # CLI entry: `python -m pricing_sync_runner --once` (PricingSync Fargate task) — create_tables → ensure_price_columns(v2.31.0) → CP/OpenAI 등록 → ensure_seed → run_sync(pg_try_advisory_lock(917350004) — 점유 중이면 즉시 exit 1) → os._exit
 │   ├── price_history.py     # 유효 단가 조회, 행 단위 비용 서브쿼리(with_row_cost — /api/cost/*, /api/efficiency/score), verification(seed_only/verified/stale)
+│   ├── pricing_changes.py   # 런 대비 단가 변경 (v2.40.0, ADR-035) — build_snapshot(run_sync가 커밋 전에 저장하는 화면 값), compare_snapshots(channel, price, pending, check 항목, 표 순서), select_runs, latest_changes(/api/pricing `changes`)
 │   ├── pricing_payload.py   # /api/pricing 응답 조립(표시 순서, tiers 5키 cp, openai_list, global, us, in_region, 셀 확장 필드 cache_read, cache_write, cache_write_1h, long, 각주 번호, 참고 자료 — 셀 각주나 메모가 인용한 출처만, 1..N 빈칸 없음, 운영 20개(오퍼 17, v2.39.0 — v2.38.0은 25개, 오퍼 22, v2.33.0은 24개, 오퍼 21), v2.31.1, v2.32.0) + 숫자 직렬화
 │   ├── pricing_export.py    # CSV(BOM + 따옴표로 감싼 면책 첫 줄, 확장 단가 7열), Markdown(머리말 공식 요금 페이지 링크 한 줄 v2.31.1, 제공사별 열 머리글, 셀 안 `<br>` 캐시와 긴 컨텍스트 줄, 고정 안내 9개 — 3번째 GPT US CRIS = In Region v2.31.1), JSON 내보내기 순수 함수
 │   ├── chat_access.py       # 공개 챗봇의 서명 쿠키·사용자별 actor·Origin 검사·요청 제한 (v2.37.0)
@@ -103,6 +105,8 @@ model-monitoring/
 │   ├── parity/              # 패리티 런 엔진: catalog.py(6 surface×20 피처), engine.py(판정 순수 로직), probes.py(surface별 실행기+요청 스냅샷), runner.py(오케스트레이터)
 │   ├── claude_features/     # Claude API Features 검증 엔진: catalog.py(39행×5 surface), transports.py(raw httpx/boto3), probes.py, engine.py(판정 순수 로직), runner.py (v2.23.0)
 │   ├── features_runner.py   # CLI entry: `python -m features_runner --once` (FeaturesVerify Fargate task)
+│   ├── model_explorer/      # 모델 탐색 검증 (v2.40.0, ADR-035): examples.py(코드 예제 단일 출처 — v2.39.0 TS codeExamples와 바이트 일치, 골든 tests/fixtures/explorer_examples_v2390.json), execute.py(플레이스홀더 → os.environ, 자식 `python -I`, 허용 목록 env, 90초, 1회 재시도, 비밀 값 가림), runner.py(모델 × 예제, ThreadPoolExecutor 4, 런 상한 1200초, 60런 보존), diff.py(catalog, example, measured)
+│   ├── explorer_runner.py   # CLI entry: `python -m explorer_runner --once` (ExplorerVerify Fargate task) / `--smoke [--models] [--json]` (DB 없이, venv에서)
 │   └── routers/
 │       ├── auth.py          # /api/auth/* — login(공개), register(EmailStr 강제), approve(이메일 토큰), me(인증)
 │       ├── admin.py         # /api/admin/* — reset-monitoring-data, users CRUD (admin only)
@@ -114,7 +118,8 @@ model-monitoring/
 │       ├── chat.py          # /api/chat/stream — Haiku 5.5 + 4 tools + dynamic followups (public)
 │       ├── insights.py      # /api/insights/* — list/latest/stream-regenerate
 │       ├── cost.py          # /api/cost/* — summary, channel-compare, trend (행 단위 시점 단가, v2.30.0)
-│       ├── pricing.py       # /api/pricing(60초 캐시), /api/pricing/export(csv|md|json) 공개 + admin_router /api/admin/pricing/pending, approve, reject (v2.30.0)
+│       ├── pricing.py       # /api/pricing(60초 캐시, `changes` v2.40.0), /api/pricing/export(csv|md|json, `changes` 제외) 공개 + admin_router /api/admin/pricing/pending, approve, reject (v2.30.0)
+│       ├── explorer.py      # /api/explorer/latest(예제 KO/EN + 최근 완료 런 결과 + 변경 + DB 기준 running, s-maxage=60), /api/explorer/trigger(JWT) (v2.40.0)
 │       ├── reliability.py   # /api/reliability/multi-channel — family/channel grouped
 │       ├── efficiency.py    # /api/efficiency/score — 0-100 weighted score per category
 │       ├── analysis.py      # /api/analysis/* — stop-reasons, output-length (v2.1.0)
@@ -151,13 +156,13 @@ model-monitoring/
 │   │   │   ├── ModelStatusGrid.tsx      # family-grouped 49 cards (Bedrock prefix) + 지표 값 등급 색(양호 파랑/경고 호박 ▲/위험 장미 ◆, data-grade, 범례 + 접이식 기준표 — lib/metricGrade.ts, ADR-029, v2.28.0)
 │   │   │   ├── TrendChart.tsx           # MODEL_COLORS 라벨 (19 Bedrock — Global 8 + US 9(Claude 8 + Nova 1) + 서울 in-region 2 — + 8 Anthropic CP + 22 OpenAI Mantle us-east-1/Global/US 활성; 1P 4개는 휴면, v2.39.0에 Claude Opus 4.7, 4.6, Sonnet 4.6, Haiku 4.5와 GPT 5.4 색을 지움, Haiku 5.5 따뜻한 계열 3색과 Sonnet 5.5 US 올리브 v2.33.0, GPT 6.1 Terra 보라 3색과 GPT 6 Astra (us-east-1) 세룰리안 v2.38.0, 수집을 멈춘 Mantle us-east-2/us-west-2 라벨은 지난 데이터용으로 색 유지)
 │   │   │   ├── CostDashboardPanel.tsx   # 방법론 문단이 /pricing으로 연결 (v2.30.0)
-│   │   │   ├── PricingPanel.tsx         # 비용 단가 표(제공사 섹션 Anthropic → OpenAI → Amazon, PROVIDER_COLUMNS 4열 — OpenAI 첫 열 OpenAI 공식 가격, Nova 첫 열 빈칸, 모르는 제공사는 columnsFor 기본 열, 셀 둘째 줄 캐시, GPT와 Claude Haiku 5.5 셋째 줄 긴 컨텍스트, 각주 → #ref-n, 검토 배지 프로모션과 문서 불일치 v2.33.0) + 면책 상자 + 마지막 공식 단가 동기화 + 다운로드 3종 + 참고 자료 (v2.30.0, 열과 캐시 v2.31.0)
+│   │   │   ├── PricingPanel.tsx         # 비용 단가 표(제공사 섹션 Anthropic → OpenAI → Amazon, PROVIDER_COLUMNS 4열 — OpenAI 첫 열 OpenAI 공식 가격, Nova 첫 열 빈칸, 모르는 제공사는 columnsFor 기본 열, 셀 둘째 줄 캐시, GPT와 Claude Haiku 5.5 셋째 줄 긴 컨텍스트, 각주 → #ref-n, 검토 배지 프로모션과 문서 불일치 v2.33.0) + 면책 상자 + 마지막 공식 단가 동기화 + 이전 동기화 대비 변경 배너(항목 → 셀 스크롤과 1.5초 강조, 셀 "이전 대비 변경" 배지, v2.40.0) + 다운로드 3종 + 참고 자료 (v2.30.0, 열과 캐시 v2.31.0)
 │   │   │   ├── ReliabilityPanel.tsx
 │   │   │   ├── EfficiencyPanel.tsx
 │   │   │   ├── AnalysisPanel.tsx        # v2.1.0
 │   │   │   ├── InsightsPanel.tsx        # SSE stream-regenerate
 │   │   │   ├── PromptsPanel.tsx         # OptimizePrompt (대상 Bedrock 17개 — v2.39.0에 Claude 4.x 네 패밀리 8개를 뺐다)
-│   │   │   ├── ModelExplorer.tsx        # 모델 카드 + API 탭(Converse/InvokeModel/Messages/Responses) 코드 예제 (v2.9.x)
+│   │   │   ├── ModelExplorer.tsx        # 모델 카드 + API 탭(Converse/InvokeModel/Messages/Responses) 코드 예제 (v2.9.x) — v2.40.0부터 예제와 검증 결과는 /api/explorer/latest: 머리글 최근 검증 런, 검증 배지, 변경 표지와 배너(항목 → 해당 API 탭 모달), 검증 실패만 필터, 모달 검증 상자
 │   │   │   ├── ParityPanel.tsx          # 패리티 매트릭스 + 증거 모달 + 수동 트리거 (v2.11.0)
 │   │   │   ├── ClaudeFeaturesPanel.tsx  # Claude API Features 5열(CP/Mantle/Bedrock 3서브열) 매트릭스 + 헬스 카드(docHealth, 클릭 → Key Findings 드로어) + 모델 칩 + 드리프트/변경(kind) 배너 + 증거 모달 + 수동 트리거 (v2.24.0)
 │   │   │   └── chat/                    # FloatingChat + ChatModal/Panel/Input
@@ -171,7 +176,8 @@ model-monitoring/
 │   │       ├── pricing.ts               # formatCost만 (v2.30.0부터 단가 표는 backend /api/pricing — 프런트 미러 없음)
 │   │       ├── pricingTable.ts          # /pricing 순수 함수 — tierLabel, PROVIDER_COLUMNS, columnsFor, headerParts, formatUnitPrice(소수 2~6자리, 예외 없음 — NaN, ±Infinity, 1e21 이상은 그대로), formatPricePair, cacheItems, longItems, pendingDetail, tierBadges, costFromPrices (정렬과 번호 매기기 없음, v2.30.0, v2.31.0)
 │   │       ├── theme.ts + chartTheme.ts # 다크/화이트 테마 (v2.8.0)
-│   │       ├── modelExplorer.ts         # 채널/네이티브ID/코드예제/링크 유도 (lang 파라미터로 KO/EN, v2.16.2)
+│   │       ├── modelExplorer.ts         # 채널/네이티브ID/링크 유도 (lang 파라미터로 KO/EN, v2.16.2; 코드 예제는 v2.40.0부터 백엔드)
+│   │       ├── explorerVerify.ts        # 모델 탐색 검증 순수 로직 — summarizeModel, badgeLabel, 변경 라벨, hasFailure, splitError, reasonText (v2.40.0)
 │   │       ├── claudeFeatures.ts        # Claude API Features 매트릭스 순수 로직 — 셀 집계·그룹 구성(modelKey, modelOrder)·surfaceSummary/surfaceFindings·labelMaps·지연시간 헬퍼 (v2.24.0)
 │   │       ├── fabVisibility.ts         # 챗봇 버튼 스크롤 숨김 규칙 nextFabState, isFabVisible (v2.31.1)
 │   │       ├── metricGrade.ts           # 대시보드 카드 지표 등급 단일 출처 — 카테고리별 TTFT/총 응답시간 임계치, TPS 공통(<40 경고, <15 위험), roundForDisplay, 색·표지 (v2.28.0, ADR-029)
@@ -425,6 +431,7 @@ Scheduler role의 `ecs:RunTask` Resource는 **task def family `:*` wildcard** 
 | `PROBE_WALL_CLOCK_S` | `90` (선택, 미주입) | 프로브 1회(재시도 포함) wall-clock 상한 — 만료 시 그 모델만 `WallClockTimeout` 오류 행, 모델별 사이클 타임아웃은 max(120, 값 + 30)초로 따라감 (v2.28.2) |
 | `MANTLE_ANTHROPIC_REGION` | `us-east-1` (CDK 주입) | Claude API Features + 패리티 런 `messages_mantle` 공용 Mantle `/anthropic` surface 리전. ap-northeast-1은 Opus 4.8만 서빙(2026-09-05 실측) → 대표 모델이 서빙되는 us-east-1로 전환(사용자 결정, v2.23.0). env 미주입 시 코드 기본값은 패리티 ap-northeast-1(`parity/runner.py`), Claude API Features us-east-1(`claude_features/catalog.py`) |
 | `FEATURES_MCP_SERVER_URL` | (선택) | Claude API Features MCP connector 프로브용 공개 MCP 서버 URL (v2.23.0, 장애 시 inconclusive로 격리) |
+| `EXPLORER_CALL_TIMEOUT_S` / `EXPLORER_RUN_DEADLINE_S` | `90` / `1200` (선택, 미주입) | 모델 탐색 검증 런의 예제 1건 실행 상한(초, 넘으면 자식 프로세스를 죽이고 failed "시간 초과") / 런 전체 상한(초, 넘으면 시작하지 못한 예제를 skipped "런 시간 상한") (v2.40.0, ADR-035) |
 | `OPENAI_API_KEY` | (CDK 주입, SSM `/bedrock-monitor/openai-api-key` secret) | Bedrock bearer 키(`ABSK-…`) — Mantle 인리전·Global·US CRIS·gptbench 공용. 미설정 시 OpenAI Mantle 채널 전체 skip |
 | `OPENAI_US_EAST_1_BASE_URL` / `OPENAI_US_EAST_2_BASE_URL` / `OPENAI_US_WEST_2_BASE_URL` | `https://bedrock-mantle.<region>.api.aws/openai/v1` (CDK 주입) | Mantle 인리전 엔드포인트 (`prober._OPENAI_REGION_ENV`) — 미주입 리전의 채널은 조용히 skip. v2.38.0부터 us-east-2, us-west-2를 쓰는 채널은 없지만(Mantle 인리전 us-east-1 일원화, ADR-033) 리전을 되살릴 때를 위해 주입은 남긴다 |
 | `OPENAI_GLOBAL_BASE_URL` | `https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1` (CDK 주입) | OpenAI Global CRIS(`global.openai.*`) 유사 리전 `global` 라우팅 (v2.20.0, ADR-025). 미주입 시 Global 채널 skip |
````
- [ ] **Step 3:** Run:

```bash
grep -rn "2\.39\.0" frontend/src/lib/version.ts backend/main.py frontend/package.json README.md | grep -v CHANGELOG; grep -c '"version": "2.40.0"' frontend/package-lock.json; make verify
```

Expected: the first grep prints nothing, the count is `2`, and `make verify` (CDK lint, typecheck, test, synth + backend + frontend unit) passes.
- [ ] **Step 4:** Commit:

```bash
git add frontend/src/lib/version.ts \
  backend/main.py \
  frontend/package.json \
  frontend/package-lock.json \
  README.md \
  CLAUDE.md \
  CHANGELOG.md
git commit -m "chore(release): v2.40.0 — CHANGELOG entry and version strings"
```
---

### Task 13: Pre-deploy live smoke of all 85 examples (real providers)

This is the first step that reaches Bedrock, Claude Platform on AWS and OpenAI on Bedrock. It reads keys from SSM into the shell environment only; never echo them.

- [ ] **Step 1:** Follow `docs/runbooks/deploy.md` §5-12 "배포 전 로컬 스모크": create `/tmp/explorer-venv` from `backend/requirements.txt`, export the three SSM keys and the OpenAI base URL and model id envs, then `cd backend && /tmp/explorer-venv/bin/python -m explorer_runner --smoke`. (`-I` in the child turns off the user site-packages, so the venv is required — the dev host's `python3.12` keeps anthropic and openai in `~/.local`.)
- [ ] **Step 2:** Expected: 85 lines (Bedrock Claude 18 × 3, Nova 1, CP 8, OpenAI 22), all `passed`, exit code 0. For a `failed` line, decide before going on: the same API failing on every model is an example defect (fix `examples.py`, update the golden in the same commit, rerun Tasks 2–5 tests); one model failing after its retry is a service-side result — report it with the exception line.
- [ ] **Step 3:** Report to the user: pass/fail counts, any failure with its exception line, total wall time. No commit unless an example was fixed.

---

### Task 14: Release and deploy (only after the user approves)

Ask the user before this task; it publishes the release and changes production. Then follow `docs/runbooks/deploy.md`:

- [ ] **Step 1:** Push the branch, open the PR, wait for CI (4 checks), merge, tag `v2.40.0` on the merge commit.
- [ ] **Step 2:** Build backend and frontend images from the merge commit with an immutable tag (`v<merge short sha>`), `--platform linux/arm64`, frontend with the RUM build args (or the same empty key as v2.39.0 if RUM stays off — say which in the report); push; record both `@sha256` digests. Run `docker build --platform linux/arm64 frontend/` before pushing (the v2.30.0 `.dockerignore` lesson).
- [ ] **Step 3:** `cd cdk && npx cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never -c backendImage=<full URI>:<tag>@sha256:<digest> -c frontendImage=<full URI>:<tag>@sha256:<digest>`, then invalidate CloudFront `E3JNKTNZGS3NX2` `/*`.
- [ ] **Step 4:** Check the backend and frontend services and all seven scheduled task defs run the new digests (2026-07-09 revert lesson).
- [ ] **Step 5:** §5-12 "배포 뒤 확인": the ExplorerVerify schedule (`cron(0 18 * * ? *)`, Etc/UTC), one manual ExplorerVerify run (`/api/explorer/latest` → totals sum 85, models 49, `failed` empty, `previous_run_id` null), two manual PricingSync runs one after the other (`changes.available` false, then true with 0 items), the JSON export without `changes`.
- [ ] **Step 6:** Playwright against production (KO and EN, 1280 px and 390 px): `/models` header "최근 검증 런 #N", card badges, the modal verification box; `/pricing` "이전 동기화(#N, …) 대비 변경 없음." card; no console errors, no API response ≥ 400.
- [ ] **Step 7:** Record the first run's token usage against ADR-035's "하루 $1 미만" estimate, write the deployment record like `docs/reviews/2026-10-27-v238-deployment.md`, and report the rollback point (v2.39.0 images and task def revisions).

---

## Self-Review

**Spec coverage:** A1 examples → Tasks 1–2 · A2 execution → Task 3 · A3 runner and CLI → Task 4 · A4 tables → Task 4 · A5 diff → Task 4 · A6 API → Task 5 · A7 `/models` → Tasks 8–9 · B1 snapshot → Task 6 · B2 comparison → Task 6 · B3 API → Task 6 · B4 `/pricing` → Tasks 8, 10 · CDK schedule → Task 7 · tests (pytest, vitest, e2e, jest) → in each task · release v2.40.0 and docs → Tasks 11–12 · pre-deploy smoke → Task 13 · deploy order 1–6 → Task 14.

**Placeholder scan:** every code step carries the full file or an exact diff taken from the verified worktree; commands have expected outputs.

**Type consistency:** `code_examples`/`API_NAMES` (Task 2) are what Tasks 4–5 import; `Outcome` fields (Task 3) are what `runner` stores; `diff_cells` input keys (`status`, `code_sha`, `model_name`, `api`) are what `routers/explorer._cells` builds; `PricingChangeItem` fields equal `compare_snapshots` item keys including `region`; `PricingBadge.kind` additions are covered by `BADGE_CLASS`/`BADGE_WRAP` in Task 10.
