// Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·문서 링크를 유도.
// 코드 예제는 v2.40.0부터 백엔드 단일 출처다(backend/model_explorer/examples.py, GET /api/explorer/latest — ADR-035):
// 화면에 보이는 코드와 매일 검증 런이 실행하는 코드가 같은 함수에서 나온다.
//
// 7개 provider path의 키 스킴 (ADR-019/020/027, backend prober.py와 동일):
//   global.* / us.*            → Bedrock inference profile (boto3 converse_stream)
//   bedrock:<region>:<fm id>   → Bedrock In-Region 온디맨드 (기본 모델 ID, 추론 프로파일 없음 — v2.32.0, ADR-031)
//   anthropic:<id>             → Anthropic CP on AWS (anthropic SDK + vendor endpoint)
//   openai:<region>:openai.<m> → OpenAI via Bedrock Mantle (openai SDK + mantle base_url)
//   openai:global:global.openai.<m> → OpenAI Bedrock global CRIS (openai SDK +
//                                 bedrock-runtime Seoul OpenAI-compat base_url, v2.20.0)
//   openai:us:us.openai.<m>    → OpenAI Bedrock US CRIS (openai SDK +
//                                 us-east-1 bedrock-runtime OpenAI-compat base_url, v2.25.0)
//   openai:1p:<m>              → OpenAI 1P direct (openai SDK + api.openai.com)

export type ChannelType = "bedrock" | "anthropic-cp" | "openai-mantle" | "openai-1p";

export interface ChannelInfo {
  type: ChannelType;
  /** 화면 표시용 채널명 */
  label: string;
  /** API 엔드포인트 (Bedrock은 리전 런타임) */
  endpoint: string;
  /** 참고 리전 표기 */
  region: string;
  /** 카드 배지 — Global / US / In-Region / CP / 1P / Mantle 리전 */
  badge: string;
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
      badge: "CP",
    };
  }
  if (modelId.startsWith("openai:1p:")) {
    return {
      type: "openai-1p",
      label: "OpenAI 1P (direct)",
      endpoint: "https://api.openai.com/v1",
      region: "글로벌 라우팅 (리전 없음)",
      badge: "1P",
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
      badge: "Global",
    };
  }
  if (modelId.startsWith("openai:us:")) {
    // us. cross-region 프로파일도 global과 같은 이유로 bedrock-mantle 호스트가 지원하지 않음 —
    // us-east-1 bedrock-runtime OpenAI-compat 엔드포인트로만 호출 가능 (prober와 동일 경로, v2.25.0).
    return {
      type: "openai-mantle",
      label: "OpenAI (Bedrock US CRIS)",
      endpoint: "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
      // 카드 배지에 그대로 노출되므로 다른 채널("Global"/"us-east-1"/"1P")처럼 짧은 식별자 유지.
      region: "US",
      badge: "US",
    };
  }
  if (modelId.startsWith("openai:")) {
    const region = modelId.split(":")[1];
    return {
      type: "openai-mantle",
      label: `OpenAI (Bedrock Mantle, ${region})`,
      endpoint: `https://bedrock-mantle.${region}.api.aws/openai/v1`,
      region,
      badge: region,
    };
  }
  if (modelId.startsWith("bedrock:")) {
    // In-Region 온디맨드(v2.32.0) — 추론 프로파일 없이 기본 모델 ID를 그 리전 bedrock-runtime에 직접 호출 (prober와 동일).
    const region = modelId.split(":")[1];
    return {
      type: "bedrock",
      label: `Bedrock (In-Region, ${region})`,
      endpoint: `https://bedrock-runtime.${region}.amazonaws.com`,
      region,
      badge: "In-Region",
    };
  }
  const isGlobal = modelId.startsWith("global.");
  return {
    type: "bedrock",
    label: isGlobal ? "Bedrock (Global CRIS)" : "Bedrock (US CRIS)",
    endpoint: `https://bedrock-runtime.${profileRegion(modelId)}.amazonaws.com`,
    region: isGlobal ? "global cross-region" : "us cross-region",
    badge: isGlobal ? "Global" : "US",
  };
}

/** Bedrock 추론 프로파일을 호출하는 리전 — backend prober `_REGION_MAP`과 같다.
 *  us.* 프로파일은 US 리전에서만 호출된다(ap-northeast-2에서 부르면 "The provided model identifier is invalid", 2026-10-19 실측). */
function profileRegion(modelId: string): string {
  return modelId.startsWith("us.") ? "us-east-1" : "ap-northeast-2";
}

/** 실제 API 호출에 넣는 모델 ID. */
export function nativeId(modelId: string): string {
  if (modelId.startsWith("anthropic:")) return modelId.slice("anthropic:".length);
  if (modelId.startsWith("openai:") || modelId.startsWith("bedrock:")) return modelId.split(":").slice(2).join(":");
  return modelId; // Bedrock 프로파일 ID 그대로
}

export type ExplorerLang = "ko" | "en";

export function modelLinks(modelId: string, modelName: string, lang: ExplorerLang = "ko"): ModelLink[] {
  const ch = channelOf(modelId);
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const links: ModelLink[] = [
    // 우리 대시보드의 해당 모델 트렌드 (v2.7.1 URL 공유 형식)
    { label: L("📈 View this model trend", "📈 이 모델 트렌드 보기"), url: `/?models=${encodeURIComponent(modelName)}&hours=24` },
  ];

  if (ch.type === "bedrock") {
    // In-Region 키는 그 리전 콘솔, 프로파일 키는 프로파일을 호출하는 리전(Global ap-northeast-2, US us-east-1) 콘솔.
    const consoleRegion = modelId.startsWith("bedrock:") ? ch.region : profileRegion(modelId);
    links.push(
      { label: L("AWS Bedrock supported models docs", "AWS Bedrock 지원 모델 문서"), url: "https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html" },
      { label: L("Bedrock console (model catalog)", "Bedrock 콘솔 (모델 카탈로그)"), url: `https://console.aws.amazon.com/bedrock/home?region=${consoleRegion}#/model-catalog` },
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
