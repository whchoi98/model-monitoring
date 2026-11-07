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
