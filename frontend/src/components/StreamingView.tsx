"use client";

import { useEffect, useRef } from "react";

interface StreamingViewProps {
  tokens: Map<string, string>;
  ttfts: Map<string, number>;
  isRunning: boolean;
}

const MODEL_COLORS: Record<string, string> = {
  "Claude Fable 5": "bg-teal-700",
  "Claude Fable 5 (Global)": "bg-teal-600",
  "Claude Opus 4.8": "bg-fuchsia-700",
  "Claude Opus 4.8 (Global)": "bg-fuchsia-600",
  "Claude Opus 4.7": "bg-rose-600",
  "Claude Opus 4.7 (Global)": "bg-rose-500",
  "Claude Opus 4.6": "bg-purple-600",
  "Claude Opus 4.6 (Global)": "bg-purple-500",
  "Claude Sonnet 5": "bg-indigo-600",
  "Claude Sonnet 5 (Global)": "bg-indigo-500",
  "Claude Sonnet 4.6": "bg-blue-600",
  "Claude Sonnet 4.6 (Global)": "bg-blue-500",
  "Claude Haiku 4.5": "bg-cyan-600",
  "Claude Haiku 4.5 (Global)": "bg-cyan-500",
  "Nova 2.0 Lite": "bg-amber-600",
  "GPT 5.5 (us-east-1)": "bg-emerald-600",
  "GPT 5.5 (us-east-2)": "bg-emerald-700",
  "GPT 5.5 (1P)": "bg-emerald-800",
  "GPT 5.4 (us-east-1)": "bg-green-600",
  "GPT 5.4 (us-east-2)": "bg-green-700",
  "GPT 5.4 (us-west-2)": "bg-green-800",
  "GPT 5.4 (1P)": "bg-green-500",
  "GPT 5.6 Sol (us-east-1)": "bg-lime-600",
  "GPT 5.6 Sol (us-east-2)": "bg-lime-700",
  "GPT 5.6 Sol (1P)": "bg-lime-800",
  "GPT 5.6 Terra (us-east-1)": "bg-emerald-500",
  "GPT 5.6 Terra (us-east-2)": "bg-emerald-400",
  "GPT 5.6 Terra (us-west-2)": "bg-teal-500",
  "GPT 5.6 Terra (1P)": "bg-teal-400",
  "GPT 5.6 Luna (us-east-1)": "bg-green-400",
  "GPT 5.6 Luna (us-east-2)": "bg-green-300",
  "GPT 5.6 Luna (us-west-2)": "bg-teal-300",
  "GPT 5.6 Luna (1P)": "bg-lime-500",
};

function getModelColor(name: string): string {
  return MODEL_COLORS[name] || "bg-gray-600";
}

function extractModelName(key: string, tokens: Map<string, string>): string {
  // The key is model_id:iteration. We need to figure out the model name.
  // We'll derive it from the key patterns
  const modelId = key.split(":").slice(0, -1).join(":");

  if (modelId.includes("fable-5")) {
    return modelId.startsWith("global") ? "Claude Fable 5 (Global)" : "Claude Fable 5";
  }
  if (modelId.includes("opus-4-8")) {
    return modelId.startsWith("global") ? "Claude Opus 4.8 (Global)" : "Claude Opus 4.8";
  }
  if (modelId.includes("opus-4-7")) {
    return modelId.startsWith("global") ? "Claude Opus 4.7 (Global)" : "Claude Opus 4.7";
  }
  if (modelId.includes("opus-4-6")) {
    return modelId.startsWith("global") ? "Claude Opus 4.6 (Global)" : "Claude Opus 4.6";
  }
  if (modelId.includes("sonnet-5")) {
    return modelId.startsWith("global") ? "Claude Sonnet 5 (Global)" : "Claude Sonnet 5";
  }
  if (modelId.includes("sonnet-4-6")) {
    return modelId.startsWith("global") ? "Claude Sonnet 4.6 (Global)" : "Claude Sonnet 4.6";
  }
  if (modelId.includes("haiku-4-5")) {
    return modelId.startsWith("global") ? "Claude Haiku 4.5 (Global)" : "Claude Haiku 4.5";
  }
  if (modelId.includes("nova")) return "Nova 2.0 Lite";
  if (modelId.startsWith("openai:")) {
    // openai:<region>:<actual_id> — region 직접 파싱. 1P direct는 pseudo-region "1p" → "1P" 표기.
    const rawRegion = modelId.split(":")[1] || "";
    const region = rawRegion === "1p" ? "1P" : rawRegion;
    const fam = modelId.includes("gpt-5.6-sol") ? "GPT 5.6 Sol"
      : modelId.includes("gpt-5.6-terra") ? "GPT 5.6 Terra"
      : modelId.includes("gpt-5.6-luna") ? "GPT 5.6 Luna"
      : modelId.includes("gpt-5.5") ? "GPT 5.5"
      : modelId.includes("gpt-5.4") ? "GPT 5.4" : "GPT";
    return `${fam} (${region})`;
  }
  return modelId;
}

function StreamCard({
  streamKey,
  text,
  ttft,
  isRunning,
  tokens,
}: {
  streamKey: string;
  text: string;
  ttft: number | undefined;
  isRunning: boolean;
  tokens: Map<string, string>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const modelName = extractModelName(streamKey, tokens);
  const iteration = streamKey.split(":").pop();
  const colorClass = getModelColor(modelName);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [text]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800 bg-gray-900/80">
        <div className="flex items-center gap-2">
          <span className={`${colorClass} text-white text-xs font-semibold px-2 py-0.5 rounded-full`}>
            {modelName}
          </span>
          <span className="text-xs text-gray-500">#{iteration}</span>
        </div>
        {ttft !== undefined && (
          <span className="text-xs font-mono tabular-nums text-emerald-400">
            TTFT: {ttft.toFixed(0)}ms
          </span>
        )}
      </div>
      <div
        ref={scrollRef}
        className="p-3 h-32 overflow-y-auto font-mono text-sm text-gray-300 leading-relaxed whitespace-pre-wrap break-words"
      >
        <span>{text}</span>
        {isRunning && text.length > 0 && (
          <span className="cursor-blink" />
        )}
        {isRunning && text.length === 0 && (
          <span className="text-gray-600 italic">Waiting for first token...</span>
        )}
      </div>
    </div>
  );
}

export default function StreamingView({
  tokens,
  ttfts,
  isRunning,
}: StreamingViewProps) {
  const entries = Array.from(tokens.entries());

  if (entries.length === 0 && !isRunning) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-gray-200">Streaming Output</h2>
        {isRunning && (
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            <span className="text-xs text-emerald-400">Live</span>
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {entries.map(([key, text]) => (
          <StreamCard
            key={key}
            streamKey={key}
            text={text}
            ttft={ttfts.get(key)}
            isRunning={isRunning}
            tokens={tokens}
          />
        ))}
      </div>
    </div>
  );
}
