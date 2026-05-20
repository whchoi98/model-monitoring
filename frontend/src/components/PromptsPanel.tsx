"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createPromptSet,
  deletePromptSet,
  fetchPromptSets,
  optimizePrompt,
} from "@/lib/api";
import { PromptSet, AuthUser } from "@/lib/types";
import { useLang } from "@/lib/i18n-context";

// 대시보드에서 모니터링 중인 모델과 동일한 채널/ID로 매핑.
// Bedrock OptimizePrompt는 inference profile / foundation-model ARN 모두 시도.
// Anthropic CP on AWS 채널은 Bedrock OptimizePrompt 대상이 아니므로 동일 family의
// Bedrock US inference profile로 fallback.
const OPTIMIZE_TARGET_MODELS: { id: string; label: string }[] = [
  // Bedrock Global Anthropic
  { id: "global.anthropic.claude-opus-4-7", label: "Bedrock Claude Opus 4.7 (Global)" },
  { id: "global.anthropic.claude-opus-4-6-v1", label: "Bedrock Claude Opus 4.6 (Global)" },
  { id: "global.anthropic.claude-sonnet-4-6", label: "Bedrock Claude Sonnet 4.6 (Global)" },
  { id: "global.anthropic.claude-haiku-4-5-20251001-v1:0", label: "Bedrock Claude Haiku 4.5 (Global)" },
  // Bedrock US Anthropic
  { id: "us.anthropic.claude-opus-4-7", label: "Bedrock Claude Opus 4.7 (US)" },
  { id: "us.anthropic.claude-opus-4-6-v1", label: "Bedrock Claude Opus 4.6 (US)" },
  { id: "us.anthropic.claude-sonnet-4-6", label: "Bedrock Claude Sonnet 4.6 (US)" },
  { id: "us.anthropic.claude-haiku-4-5-20251001-v1:0", label: "Bedrock Claude Haiku 4.5 (US)" },
  // Bedrock Nova
  { id: "us.amazon.nova-2-lite-v1:0", label: "Bedrock Nova 2.0 Lite (US)" },
];

interface Props {
  user: AuthUser | null;
  onLoginClick: () => void;
}

export default function PromptsPanel({ user, onLoginClick }: Props) {
  const { lang } = useLang();
  const [promptSets, setPromptSets] = useState<PromptSet[]>([]);
  const [loading, setLoading] = useState(true);

  // Create form
  const [newName, setNewName] = useState("");
  const [newPrompt, setNewPrompt] = useState("");
  const [creating, setCreating] = useState(false);

  // Optimize
  const [optInput, setOptInput] = useState("");
  const [optTarget, setOptTarget] = useState(OPTIMIZE_TARGET_MODELS[0].id);
  const [optBusy, setOptBusy] = useState(false);
  const [optAnalyze, setOptAnalyze] = useState<string | null>(null);
  const [optResult, setOptResult] = useState<string | null>(null);
  const [optError, setOptError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const list = await fetchPromptSets();
      setPromptSets(list);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return onLoginClick();
    if (!newName.trim() || !newPrompt.trim()) return;
    setCreating(true);
    try {
      await createPromptSet({
        name: newName.trim(),
        prompts: [newPrompt.trim()],
        temperature: 0.1,
        max_tokens: 256,
      });
      setNewName("");
      setNewPrompt("");
      await reload();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!user) return onLoginClick();
    if (!confirm(lang === "en" ? "Delete this prompt set?" : "이 프롬프트 세트를 삭제할까요?")) return;
    try {
      await deletePromptSet(id);
      await reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const handleOptimize = async () => {
    if (!user) return onLoginClick();
    if (!optInput.trim()) return;
    setOptBusy(true);
    setOptAnalyze(null);
    setOptResult(null);
    setOptError(null);
    try {
      const r = await optimizePrompt({ prompt: optInput.trim(), target_model_id: optTarget });
      setOptAnalyze(r.analyze_message);
      setOptResult(r.optimized_prompt);
    } catch (e) {
      setOptError((e as Error).message);
    } finally {
      setOptBusy(false);
    }
  };

  const handleUseOptimized = () => {
    if (optResult) {
      setNewPrompt(optResult);
      setNewName((n) => n || `Optimized ${new Date().toISOString().slice(0, 16)}`);
      // 스크롤은 사용자가 알아서.
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Prompts" : "프롬프트"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Manage saved prompt sets and run Bedrock Simple Prompt Optimization."
              : "프롬프트 세트를 관리하고 Bedrock의 Simple Prompt Optimization으로 개선합니다."}
          </p>
        </div>
        {!user && (
          <button
            onClick={onLoginClick}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-blue-600 hover:bg-blue-500 text-white"
          >
            {lang === "en" ? "Login required" : "로그인 필요"}
          </button>
        )}
      </div>

      {/* Optimize 섹션 */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2">
          <span aria-hidden>✨</span>
          <h2 className="text-sm font-semibold text-gray-200">
            {lang === "en" ? "Bedrock Prompt Optimization" : "Bedrock 프롬프트 최적화"}
          </h2>
          <span className="text-[10px] text-gray-500">
            ({lang === "en" ? "Powered by bedrock-agent-runtime · OptimizePrompt" : "bedrock-agent-runtime · OptimizePrompt"})
          </span>
        </div>

        <textarea
          value={optInput}
          onChange={(e) => setOptInput(e.target.value)}
          rows={5}
          disabled={!user || optBusy}
          placeholder={
            user
              ? lang === "en"
                ? "Paste your prompt here..."
                : "최적화할 프롬프트를 입력하세요..."
              : lang === "en"
                ? "Login to use optimization"
                : "로그인 후 사용 가능"
          }
          className="w-full bg-gray-950 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
        />

        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-xs text-gray-400">
            {lang === "en" ? "Target model" : "타겟 모델"}
            <select
              value={optTarget}
              onChange={(e) => setOptTarget(e.target.value)}
              disabled={!user || optBusy}
              className="ml-2 bg-gray-950 border border-gray-700 rounded-md px-2 py-1 text-xs text-gray-100 disabled:opacity-50"
            >
              {OPTIMIZE_TARGET_MODELS.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </label>
          <button
            onClick={handleOptimize}
            disabled={!user || optBusy || !optInput.trim()}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {optBusy
              ? (lang === "en" ? "Optimizing..." : "최적화 중...")
              : (lang === "en" ? "Optimize" : "최적화")}
          </button>
        </div>

        {optError && (
          <div className="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400">
            {optError}
          </div>
        )}
        {optAnalyze && (
          <div className="px-3 py-2 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
            <span className="font-semibold">{lang === "en" ? "Analysis" : "분석"}: </span>
            {optAnalyze}
          </div>
        )}
        {optResult && (
          <div className="space-y-2">
            <div className="text-xs text-gray-400 font-semibold">
              {lang === "en" ? "Optimized prompt" : "최적화된 프롬프트"}
            </div>
            <pre className="whitespace-pre-wrap break-words bg-gray-950 border border-gray-700 rounded-md p-3 text-xs text-gray-100">
              {optResult}
            </pre>
            <div className="flex gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(optResult)}
                className="px-2.5 py-1 text-[11px] rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300"
              >
                {lang === "en" ? "Copy" : "복사"}
              </button>
              <button
                onClick={handleUseOptimized}
                className="px-2.5 py-1 text-[11px] rounded-md bg-blue-600 hover:bg-blue-500 text-white"
              >
                {lang === "en" ? "Use in new prompt set" : "프롬프트 세트 입력으로 사용"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 새 프롬프트 세트 생성 */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-4">
        <h2 className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "New prompt set" : "새 프롬프트 세트"}
        </h2>
        <form onSubmit={handleCreate} className="space-y-3">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={!user || creating}
            placeholder={lang === "en" ? "Name" : "이름"}
            className="w-full bg-gray-950 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
          />
          <textarea
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            rows={4}
            disabled={!user || creating}
            placeholder={lang === "en" ? "Prompt text" : "프롬프트 내용"}
            className="w-full bg-gray-950 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!user || creating || !newName.trim() || !newPrompt.trim()}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {creating
              ? (lang === "en" ? "Saving..." : "저장 중...")
              : (lang === "en" ? "Save" : "저장")}
          </button>
        </form>
      </div>

      {/* 저장된 프롬프트 세트 목록 */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-200">
            {lang === "en" ? "Saved prompt sets" : "저장된 프롬프트 세트"}
          </h2>
          <span className="text-xs text-gray-500">{promptSets.length}</span>
        </div>
        {loading ? (
          <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
        ) : promptSets.length === 0 ? (
          <div className="text-xs text-gray-500">
            {lang === "en" ? "No prompt sets saved yet." : "아직 저장된 프롬프트 세트가 없습니다."}
          </div>
        ) : (
          <div className="space-y-2">
            {promptSets.map((p) => (
              <div
                key={p.id}
                className="flex items-start justify-between gap-3 bg-gray-950/50 border border-gray-800 rounded-md p-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-gray-200 truncate">{p.name}</div>
                  <div className="text-xs text-gray-500 mt-1">
                    {p.prompts.length} {lang === "en" ? "prompts" : "프롬프트"}
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-xs text-gray-400 mt-2 line-clamp-3">
                    {p.prompts[0]}
                  </pre>
                </div>
                <button
                  onClick={() => handleDelete(p.id)}
                  disabled={!user}
                  className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50"
                >
                  {lang === "en" ? "Delete" : "삭제"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
