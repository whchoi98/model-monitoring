// Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·코드 예제·문서 링크를 유도.
//
// 5개 provider path의 키 스킴 (ADR-019/020, backend prober.py와 동일):
//   global.* / us.*            → Bedrock inference profile (boto3 converse_stream)
//   anthropic:<id>             → Anthropic CP on AWS (anthropic SDK + vendor endpoint)
//   openai:<region>:openai.<m> → OpenAI via Bedrock Mantle (openai SDK + mantle base_url)
//   openai:global:global.openai.<m> → OpenAI Bedrock global CRIS (openai SDK +
//                                 bedrock-runtime Seoul OpenAI-compat base_url, v2.20.0)
//   openai:1p:<m>              → OpenAI 1P direct (openai SDK + api.openai.com)
// 코드 예제는 실제 prober가 쓰는 호출 방식과 일치시킨다 — 복붙해서 바로 동작하는 것이 목표.

export type ChannelType = "bedrock" | "anthropic-cp" | "openai-mantle" | "openai-1p";

export interface ChannelInfo {
  type: ChannelType;
  /** 화면 표시용 채널명 */
  label: string;
  /** API 엔드포인트 (Bedrock은 리전 런타임) */
  endpoint: string;
  /** 참고 리전 표기 */
  region: string;
}

export interface CodeExample {
  label: string;
  /** API 종류 표기 — Converse API / InvokeModel API / Messages API / Responses API */
  api: string;
  /** 이 API가 의미하는 바 (카드 상세에서 탭 아래 표시) */
  description: string;
  language: string;
  code: string;
}

export interface ModelLink {
  label: string;
  url: string;
}

export function channelOf(modelId: string): ChannelInfo {
  if (modelId.startsWith("anthropic:")) {
    return {
      type: "anthropic-cp",
      label: "Anthropic (CP on AWS)",
      endpoint: "https://aws-external-anthropic.us-east-2.api.aws",
      region: "us-east-2",
    };
  }
  if (modelId.startsWith("openai:1p:")) {
    return {
      type: "openai-1p",
      label: "OpenAI 1P (direct)",
      endpoint: "https://api.openai.com/v1",
      region: "글로벌 라우팅 (리전 없음)",
    };
  }
  if (modelId.startsWith("openai:global:")) {
    // global CRIS 프로파일(global.openai.*)은 bedrock-mantle 호스트가 지원하지 않음 —
    // bedrock-runtime OpenAI-compat 엔드포인트(Seoul)로만 호출 가능 (prober와 동일 경로).
    return {
      type: "openai-mantle",
      label: "OpenAI (Bedrock Global CRIS)",
      endpoint: "https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1",
      // 카드 배지에 그대로 노출되므로 다른 채널("us-east-1"/"1P")처럼 짧은 식별자 유지.
      region: "Global",
    };
  }
  if (modelId.startsWith("openai:")) {
    const region = modelId.split(":")[1];
    return {
      type: "openai-mantle",
      label: `OpenAI (Bedrock Mantle, ${region})`,
      endpoint: `https://bedrock-mantle.${region}.api.aws/openai/v1`,
      region,
    };
  }
  const isGlobal = modelId.startsWith("global.");
  return {
    type: "bedrock",
    label: isGlobal ? "Bedrock (Global 프로파일)" : "Bedrock (US 프로파일)",
    endpoint: "bedrock-runtime (ap-northeast-2에서 호출)",
    region: isGlobal ? "global cross-region" : "us cross-region",
  };
}

/** 실제 API 호출에 넣는 모델 ID. */
export function nativeId(modelId: string): string {
  if (modelId.startsWith("anthropic:")) return modelId.slice("anthropic:".length);
  if (modelId.startsWith("openai:")) return modelId.split(":").slice(2).join(":");
  return modelId; // Bedrock 프로파일 ID 그대로
}

export type ExplorerLang = "ko" | "en";

export function codeExamples(modelId: string, lang: ExplorerLang = "ko"): CodeExample[] {
  const ch = channelOf(modelId);
  const id = nativeId(modelId);
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);

  if (ch.type === "bedrock") {
    const converse: CodeExample = {
      label: "Python (boto3)",
      api: "Converse API",
      description:
        L("Bedrock unified conversation API — every Bedrock model is called with the same request shape, so you can swap models without code changes. Use converse_stream for streaming. This monitor's prober uses this API.", "Bedrock의 통합 대화 API — 모든 Bedrock 모델을 동일한 요청 형식으로 호출하므로 코드 수정 없이 모델을 교체할 수 있습니다. 스트리밍은 converse_stream을 사용합니다. 이 모니터의 prober도 이 API를 사용합니다."),
      language: "python",
      code: `import boto3

client = boto3.client("bedrock-runtime", region_name="ap-northeast-2")

response = client.converse_stream(
    modelId="${id}",
    messages=[{"role": "user", "content": [{"text": "Hello!"}]}],
    inferenceConfig={"maxTokens": 512},
)
for event in response["stream"]:
    if "contentBlockDelta" in event:
        print(event["contentBlockDelta"]["delta"].get("text", ""), end="")`,
    };
    // InvokeModel은 모델 네이티브 페이로드가 필요 — Claude(Anthropic) 모델에만 예제 제공.
    if (!modelId.includes("anthropic")) {
      return [converse];
    }
    return [
      converse,
      {
        label: "Python (boto3)",
        api: "InvokeModel API",
        description:
          L("Low-level API that passes the model-native payload as-is — use it to control model-specific schemas (Anthropic Messages format for Claude) and fine-grained parameters. Changing the model means changing the request body too.", "모델 네이티브 페이로드를 그대로 전달하는 저수준 API — 모델 고유 스키마(Claude는 Anthropic Messages 형식)와 세부 파라미터를 직접 제어할 때 사용합니다. 모델을 바꾸면 요청 본문도 함께 바꿔야 합니다."),
        language: "python",
        code: `import boto3, json

client = boto3.client("bedrock-runtime", region_name="ap-northeast-2")

response = client.invoke_model(
    modelId="${id}",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "Hello!"}],
    }),
)
result = json.loads(response["body"].read())
print(result["content"][0]["text"])`,
      },
      {
        label: "Python (anthropic SDK)",
        api: "Messages API",
        description:
          L("Use the Anthropic-native API on top of Bedrock — the anthropic SDK AnthropicBedrock client signs Messages-format requests with SigV4 and forwards them to Bedrock (no Anthropic API key; billing and IAM stay in your AWS account). Note: the Bedrock Mantle /anthropic endpoint (bearer token, some regions e.g. us-east-1) also accepts the same Messages format.", "Anthropic 네이티브 API를 Bedrock 위에서 그대로 쓰는 방식 — anthropic SDK의 AnthropicBedrock 클라이언트가 Messages 형식 요청을 SigV4로 서명해 Bedrock으로 전달합니다. Claude 전용 파라미터를 Anthropic 문서 그대로 사용하면서 과금·권한은 AWS 계정으로 관리할 때 사용합니다. 참고: Bedrock Mantle /anthropic 엔드포인트(bearer 토큰, us-east-1 등 일부 리전)로도 동일한 Messages 형식 호출이 가능합니다."),
        language: "python",
        code: `from anthropic import AnthropicBedrock

${L("# Via Bedrock — AWS credentials (SigV4), no Anthropic API key required", "# Bedrock 경유 — AWS 자격 증명(SigV4) 사용, Anthropic API 키 불필요")}
client = AnthropicBedrock(aws_region="ap-northeast-2")

with client.messages.stream(
    model="${id}",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello!"}],
) as stream:
    for text in stream.text_stream:
        print(text, end="")`,
      },
    ];
  }

  if (ch.type === "anthropic-cp") {
    return [
      {
        label: "Python (anthropic SDK)",
        api: "Messages API",
        description:
          L("Anthropic-native API — the most complete support for Claude-specific features (extended thinking, prompt caching, ...). Called here via the Claude Platform on AWS endpoint with a workspace header.", "Anthropic 네이티브 API — Claude 전용 기능(확장 사고, 프롬프트 캐싱 등)을 가장 완전하게 지원합니다. 여기서는 Claude Platform on AWS 엔드포인트와 workspace 헤더로 호출합니다."),
        language: "python",
        code: `from anthropic import Anthropic

${L("# Claude Platform on AWS — vendor endpoint + workspace header", "# Claude Platform on AWS — vendor endpoint + workspace 헤더")}
client = Anthropic(
    api_key="<ANTHROPIC_API_KEY>",
    base_url="${ch.endpoint}",
    default_headers={"anthropic-workspace": "<ANTHROPIC_WORKSPACE_ID>"},
)

with client.messages.stream(
    model="${id}",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello!"}],
) as stream:
    for text in stream.text_stream:
        print(text, end="")`,
      },
    ];
  }

  if (ch.type === "openai-mantle") {
    // Global CRIS는 같은 openai SDK 호출이지만 엔드포인트가 bedrock-runtime(Seoul) OpenAI-compat —
    // 설명/주석의 "Bedrock Mantle" 표기가 실제 경로와 어긋나지 않게 분기.
    const isGlobalCris = modelId.startsWith("openai:global:");
    return [
      {
        label: "Python (openai SDK)",
        api: "Responses API",
        description: isGlobalCris
          ? L("OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Global cross-region profiles are served by the bedrock-runtime OpenAI-compatible endpoint (not the bedrock-mantle host); the call shape is identical and the key is a Bedrock bearer (ABSK-...).", "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. Global cross-region 프로파일은 bedrock-runtime OpenAI 호환 엔드포인트로 호출합니다(bedrock-mantle 호스트 미지원). 호출 형식은 동일하며 키는 Bedrock bearer(ABSK-…)를 사용합니다.")
          : L("OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Bedrock Mantle is an OpenAI-compatible endpoint, so the call shape is identical but the key is a Bedrock bearer (ABSK-...).", "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. Bedrock Mantle은 OpenAI 호환 엔드포인트라 동일한 형식으로 호출하되, 키는 Bedrock bearer(ABSK-…)를 사용합니다."),
        language: "python",
        code: `from openai import OpenAI

${isGlobalCris
  ? L("# Bedrock Global CRIS — bedrock-runtime OpenAI-compatible endpoint + Bedrock bearer key (ABSK-...)", "# Bedrock Global CRIS — bedrock-runtime OpenAI 호환 엔드포인트 + Bedrock bearer 키(ABSK-…)")
  : L("# Bedrock Mantle — OpenAI-compatible endpoint + Bedrock bearer key (ABSK-...)", "# Bedrock Mantle — OpenAI 호환 엔드포인트 + Bedrock bearer 키(ABSK-…)")}
client = OpenAI(
    api_key="<ABSK-...>",  # Bedrock long-term API key
    base_url="${ch.endpoint}",
)

stream = client.responses.create(
    model="${id}",
    input="Hello!",
    stream=True,
)
for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="")`,
      },
    ];
  }

  // openai-1p
  return [
    {
      label: "Python (openai SDK)",
      api: "Responses API",
      description:
        L("OpenAI unified Responses API (successor to Chat Completions) — event-stream based output. Calls api.openai.com directly and requires an OpenAI platform key (sk-proj-...).", "OpenAI의 통합 응답 API(Chat Completions의 후속) — 이벤트 스트리밍 기반 출력. api.openai.com 직접 호출이며 OpenAI platform 키(sk-proj-…)가 필요합니다."),
      language: "python",
      code: `from openai import OpenAI

${L("# OpenAI 1P direct — platform key (sk-proj-...), not interchangeable with Mantle bearer", "# OpenAI 1P direct — platform 키(sk-proj-…), Mantle bearer와 호환 불가")}
client = OpenAI(api_key="<OPENAI_API_KEY>")

stream = client.responses.create(
    model="${id}",
    input="Hello!",
    stream=True,
)
for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="")`,
    },
  ];
}

export function modelLinks(modelId: string, modelName: string, lang: ExplorerLang = "ko"): ModelLink[] {
  const ch = channelOf(modelId);
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const links: ModelLink[] = [
    // 우리 대시보드의 해당 모델 트렌드 (v2.7.1 URL 공유 형식)
    { label: L("📈 View this model trend", "📈 이 모델 트렌드 보기"), url: `/?models=${encodeURIComponent(modelName)}&hours=24` },
  ];

  if (ch.type === "bedrock") {
    links.push(
      { label: L("AWS Bedrock supported models docs", "AWS Bedrock 지원 모델 문서"), url: "https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html" },
      { label: L("Bedrock console (model catalog)", "Bedrock 콘솔 (모델 카탈로그)"), url: "https://console.aws.amazon.com/bedrock/home?region=ap-northeast-2#/model-catalog" },
      { label: L("Bedrock pricing", "Bedrock 요금"), url: "https://aws.amazon.com/bedrock/pricing/" },
    );
    if (modelId.includes("anthropic")) {
      links.push({ label: L("Anthropic model docs", "Anthropic 모델 문서"), url: "https://docs.claude.com/en/docs/about-claude/models/overview" });
    }
    if (modelId.includes("nova")) {
      links.push({ label: L("Amazon Nova docs", "Amazon Nova 문서"), url: "https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html" });
    }
  } else if (ch.type === "anthropic-cp") {
    links.push(
      { label: L("Anthropic model docs", "Anthropic 모델 문서"), url: "https://docs.claude.com/en/docs/about-claude/models/overview" },
      { label: L("Claude API reference", "Claude API 레퍼런스"), url: "https://docs.claude.com/en/api/messages" },
      { label: L("Anthropic pricing", "Anthropic 요금"), url: "https://claude.com/pricing" },
    );
  } else {
    // openai-mantle / openai-1p
    links.push(
      { label: L("OpenAI model docs", "OpenAI 모델 문서"), url: "https://platform.openai.com/docs/models" },
      { label: "OpenAI Responses API", url: "https://platform.openai.com/docs/api-reference/responses" },
    );
    if (ch.type === "openai-mantle") {
      links.push({ label: L("OpenAI models on AWS Bedrock", "AWS Bedrock의 OpenAI 모델"), url: "https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html" });
    } else {
      links.push({ label: L("OpenAI pricing", "OpenAI 요금"), url: "https://platform.openai.com/docs/pricing" });
    }
  }
  return links;
}
