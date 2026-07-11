"use client";

// Model Explorer (v2.9.0) — 모니터링 중인 전체 모델 카드 그리드 + 상세 모달.
// 참조 UX: aws-samples Bedrock Central의 Explore Models (검색/필터 + 카드 + 상세).
// 데이터는 /api/models(공개)에서 — 모델 추가 시 자동 반영, 하드코딩 없음.

import { useEffect, useMemo, useState } from "react";
import { ModelInfo } from "@/lib/types";
import { fetchModels } from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { getPricing } from "@/lib/pricing";
import { sortResults, isExcludedModel } from "@/lib/sortModels";
import {
  ChannelType,
  channelOf,
  codeExamples,
  modelLinks,
  nativeId,
} from "@/lib/modelExplorer";

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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="px-2 py-1 text-[10px] font-medium rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200 transition-colors"
    >
      {copied ? "✓ 복사됨" : "복사"}
    </button>
  );
}

function DetailModal({ model, onClose }: { model: ModelInfo; onClose: () => void }) {
  const { lang } = useLang();
  const ch = channelOf(model.id);
  const price = getPricing(model.id);
  const examples = codeExamples(model.id);
  const links = modelLinks(model.id, model.name);
  const [tab, setTab] = useState(0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="overlay"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
      />
      <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-gray-900 light:bg-white border border-gray-800 rounded-xl shadow-2xl p-6 space-y-5">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-3 right-3 text-gray-400 hover:text-gray-200 text-xl leading-none"
          aria-label="close"
        >
          ×
        </button>

        {/* 헤더 */}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-bold text-gray-100">{model.name}</h2>
            <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
              {ch.label}
            </span>
          </div>
          <code className="text-xs text-blue-300 break-all">{model.id}</code>
        </div>

        {/* 모델 정보 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div className="bg-gray-950/50 light:bg-gray-950 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{lang === "en" ? "Invoke model ID" : "호출 모델 ID"}</div>
            <div className="flex items-center gap-2">
              <code className="text-gray-200 break-all">{nativeId(model.id)}</code>
              <CopyButton text={nativeId(model.id)} />
            </div>
            <div className="text-gray-500 pt-1">{lang === "en" ? "Endpoint" : "엔드포인트"}</div>
            <code className="text-gray-300 break-all">{ch.endpoint}</code>
            <div className="text-gray-500 pt-1">{lang === "en" ? "Region" : "리전"}</div>
            <div className="text-gray-300">{ch.region}</div>
          </div>
          <div className="bg-gray-950/50 light:bg-gray-950 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{lang === "en" ? "Pricing (per 1M tokens)" : "토큰 단가 (1M 기준)"}</div>
            {price ? (
              <div className="text-gray-200 tabular-nums">
                Input <span className="font-semibold">${price.input}</span> / Output{" "}
                <span className="font-semibold">${price.output}</span>
              </div>
            ) : (
              <div className="text-gray-500">-</div>
            )}
            <div className="text-gray-500 pt-2">{lang === "en" ? "Links" : "연결 링크"}</div>
            <ul className="space-y-1">
              {links.map((l) => (
                <li key={l.url}>
                  <a
                    href={l.url}
                    target={l.url.startsWith("/") ? undefined : "_blank"}
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline"
                  >
                    {l.label} {l.url.startsWith("/") ? "" : "↗"}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 코드 예제 */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-gray-200">
              {lang === "en" ? "Code Examples" : "코드 예제"}
            </h3>
            <CopyButton text={examples[tab].code} />
          </div>
          {examples.length > 1 && (
            <div className="flex gap-1 mb-2">
              {examples.map((ex, i) => (
                <button
                  key={ex.label}
                  onClick={() => setTab(i)}
                  className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                    tab === i
                      ? "bg-blue-600 text-white"
                      : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                  }`}
                >
                  {ex.label}
                </button>
              ))}
            </div>
          )}
          {examples.length === 1 && (
            <div className="text-[10px] text-gray-500 mb-1">{examples[0].label}</div>
          )}
          <pre className="bg-gray-950 light:bg-gray-950 border border-gray-800 rounded-md p-3 overflow-x-auto text-xs text-gray-200 leading-relaxed">
            <code>{examples[tab].code}</code>
          </pre>
        </div>
      </div>
    </div>
  );
}

export default function ModelExplorer() {
  const { lang } = useLang();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<ChannelType | "all">("all");
  const [selected, setSelected] = useState<ModelInfo | null>(null);

  useEffect(() => {
    fetchModels()
      .then((m) => setModels(sortResults(m.filter((x) => !isExcludedModel(x.name)).map((x) => ({ ...x, model_name: x.name })))
        .map(({ model_name: _unused, ...rest }) => rest as ModelInfo)))
      .catch((e) => console.error("Failed to fetch models:", e))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return models.filter((m) => {
      if (channel !== "all" && channelOf(m.id).type !== channel) return false;
      if (q && !m.name.toLowerCase().includes(q) && !m.id.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [models, search, channel]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h2 className="text-xl font-bold text-gray-100">
          {lang === "en" ? "Model Explorer" : "모델 탐색"}
        </h2>
        <p className="text-sm text-gray-500 mt-1">
          {lang === "en"
            ? `${models.length} monitored models — click a card for invoke IDs, code examples, and links.`
            : `모니터링 중인 ${models.length}개 모델 — 카드를 선택하면 호출 ID·코드 예제·연결 링크를 볼 수 있습니다.`}
        </p>
      </div>

      {/* 검색 + 채널 필터 */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={lang === "en" ? "Search models..." : "모델 검색..."}
          className="px-3 py-1.5 text-sm rounded-lg bg-gray-900 light:bg-white border border-gray-800 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 w-64"
        />
        <div className="flex gap-1 flex-wrap">
          {CHANNEL_FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setChannel(f.id)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                channel === f.id
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
              }`}
            >
              {lang === "en" ? f.en : f.ko}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-500">{filtered.length} / {models.length}</span>
      </div>

      {/* 카드 그리드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((m) => {
          const ch = channelOf(m.id);
          const price = getPricing(m.id);
          return (
            <button
              key={m.id}
              onClick={() => setSelected(m)}
              className="text-left bg-gray-900/50 border border-gray-800 rounded-xl p-4 hover:border-blue-500/50 transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-gray-100 group-hover:text-blue-300 transition-colors">
                  {m.name}
                </h3>
                <span className={`shrink-0 px-2 py-0.5 text-[10px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
                  {ch.type === "bedrock" ? (m.id.startsWith("global.") ? "Global" : "US") : ch.type === "anthropic-cp" ? "CP" : ch.type === "openai-1p" ? "1P" : ch.region}
                </span>
              </div>
              <code className="block text-[11px] text-gray-500 break-all mt-1.5">{m.id}</code>
              <div className="text-[11px] text-gray-500 mt-2 tabular-nums">
                {price ? `$${price.input} / $${price.output} (1M in/out)` : ""}
              </div>
            </button>
          );
        })}
      </div>

      {selected && <DetailModal model={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
