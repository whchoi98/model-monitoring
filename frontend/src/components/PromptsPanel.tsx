"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  createPromptSet,
  deletePromptSet,
  fetchPromptSets,
  optimizePrompt,
} from "@/lib/api";
import { PromptSet, AuthUser } from "@/lib/types";
import { useLang, useT } from "@/lib/i18n-context";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import Dialog from "./Dialog";
import RefreshControls from "./RefreshControls";

// 대시보드에서 모니터링 중인 모델과 동일한 채널/ID로 매핑.
// Bedrock OptimizePrompt는 inference profile / foundation-model ARN 모두 시도.
// Anthropic CP on AWS 채널은 Bedrock OptimizePrompt 대상이 아니므로 동일 family의
// Bedrock US inference profile로 fallback.
const OPTIMIZE_TARGET_MODELS: { id: string; label: string }[] = [
  // Bedrock Global Anthropic
  { id: "global.anthropic.claude-fable-5-1", label: "Bedrock Claude Fable 5.1 (Global)" },
  { id: "global.anthropic.claude-fable-5", label: "Bedrock Claude Fable 5 (Global)" },
  { id: "global.anthropic.claude-opus-5", label: "Bedrock Claude Opus 5 (Global)" },
  { id: "global.anthropic.claude-opus-4-8", label: "Bedrock Claude Opus 4.8 (Global)" },
  { id: "global.anthropic.claude-opus-4-7", label: "Bedrock Claude Opus 4.7 (Global)" },
  { id: "global.anthropic.claude-opus-4-6-v1", label: "Bedrock Claude Opus 4.6 (Global)" },
  { id: "global.anthropic.claude-sonnet-5", label: "Bedrock Claude Sonnet 5 (Global)" },
  { id: "global.anthropic.claude-sonnet-4-6", label: "Bedrock Claude Sonnet 4.6 (Global)" },
  { id: "global.anthropic.claude-haiku-4-5-20251001-v1:0", label: "Bedrock Claude Haiku 4.5 (Global)" },
  // Bedrock US Anthropic
  { id: "us.anthropic.claude-fable-5-1", label: "Bedrock Claude Fable 5.1 (US)" },
  { id: "us.anthropic.claude-fable-5", label: "Bedrock Claude Fable 5 (US)" },
  { id: "us.anthropic.claude-opus-5", label: "Bedrock Claude Opus 5 (US)" },
  { id: "us.anthropic.claude-opus-4-8", label: "Bedrock Claude Opus 4.8 (US)" },
  { id: "us.anthropic.claude-opus-4-7", label: "Bedrock Claude Opus 4.7 (US)" },
  { id: "us.anthropic.claude-opus-4-6-v1", label: "Bedrock Claude Opus 4.6 (US)" },
  { id: "us.anthropic.claude-sonnet-5", label: "Bedrock Claude Sonnet 5 (US)" },
  { id: "us.anthropic.claude-sonnet-4-6", label: "Bedrock Claude Sonnet 4.6 (US)" },
  { id: "us.anthropic.claude-haiku-4-5-20251001-v1:0", label: "Bedrock Claude Haiku 4.5 (US)" },
  // Bedrock Nova
  { id: "us.amazon.nova-2-lite-v1:0", label: "Bedrock Nova 2.0 Lite (US)" },
];

interface Props {
  user: AuthUser | null;
  onLoginClick: () => void;
}

function ActionNotice({ error = false, children }: { error?: boolean; children: ReactNode }) {
  return (
    <div role={error ? "alert" : "status"} aria-atomic="true"
      className={`rounded-lg border px-3 py-2 text-sm ${
        error ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      }`}>
      {children}
    </div>
  );
}

export default function PromptsPanel({ user, onLoginClick }: Props) {
  const { lang } = useLang();
  const t = useT();
  const fieldId = useId();
  const resource = useAsyncResource("prompt-sets", fetchPromptSets);
  // Confirmed mutations remain visible if their follow-up GET fails. Reconcile
  // them once a successful GET reflects the write; these are not optimistic writes.
  const [createdSets, setCreatedSets] = useState<PromptSet[]>([]);
  const [deletedIds, setDeletedIds] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (resource.data === null) return;
    const ids = new Set(resource.data.map((item) => item.id));
    setCreatedSets((current) => {
      const remaining = current.filter((item) => !ids.has(item.id));
      return remaining.length === current.length ? current : remaining;
    });
    setDeletedIds((current) => {
      const remaining = new Set(Array.from(current).filter((id) => ids.has(id)));
      return remaining.size === current.size ? current : remaining;
    });
  }, [resource.data]);
  const savedIds = new Set(resource.data?.map((item) => item.id));
  const promptSets = [
    ...(resource.data ?? []),
    ...createdSets.filter((item) => !savedIds.has(item.id)),
  ].filter((item) => !deletedIds.has(item.id));
  const hasData = resource.data !== null || createdSets.length > 0;
  const mutationInFlight = useRef(false);
  const savedTitle = useRef<HTMLHeadingElement>(null);

  // Create form
  const [newName, setNewName] = useState("");
  const [newPrompt, setNewPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [createNotice, setCreateNotice] = useState<{ name: string; error: boolean } | null>(null);

  // Deletion is confirmed in a named modal; cancellation never sends a request.
  const [deleteTarget, setDeleteTarget] = useState<PromptSet | null>(null);
  const [deleting, setDeleting] = useState<PromptSet | null>(null);
  const [deleteNotice, setDeleteNotice] = useState<{ name: string; error: boolean } | null>(null);
  const deleteDialogOpen = useRef(false);
  const mutationBusy = creating || deleting !== null;

  // Optimize
  const [optInput, setOptInput] = useState("");
  const [optTarget, setOptTarget] = useState(OPTIMIZE_TARGET_MODELS[0].id);
  const [optBusy, setOptBusy] = useState(false);
  const [optAnalyze, setOptAnalyze] = useState<string | null>(null);
  const [optResult, setOptResult] = useState<string | null>(null);
  const [optError, setOptError] = useState<"optimize" | "copy" | null>(null);
  const [optNotice, setOptNotice] = useState<"copied" | "used" | null>(null);
  const optimizing = useRef(false);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!user) return onLoginClick();
    const name = newName.trim();
    const prompt = newPrompt.trim();
    if (mutationInFlight.current || !name || !prompt) return;
    mutationInFlight.current = true;
    setCreating(true);
    setCreateNotice(null);
    try {
      const created = await createPromptSet({
        name,
        prompts: [prompt],
        temperature: 0.1,
        max_tokens: 256,
      });
      setCreatedSets((current) => [...current.filter((item) => item.id !== created.id), created]);
      setNewName("");
      setNewPrompt("");
      setCreateNotice({ name: created.name, error: false });
      void resource.refresh();
    } catch {
      setCreateNotice({ name, error: true });
    } finally {
      mutationInFlight.current = false;
      setCreating(false);
    }
  };

  const openDeleteDialog = (prompt: PromptSet) => {
    if (!user) return onLoginClick();
    if (mutationInFlight.current) return;
    setDeleteNotice(null);
    deleteDialogOpen.current = true;
    setDeleteTarget(prompt);
  };

  const focusSavedTitle = () => {
    requestAnimationFrame(() => savedTitle.current?.focus());
  };

  const closeDeleteDialog = () => {
    deleteDialogOpen.current = false;
    setDeleteTarget(null);
    // Closing an in-flight dialog only dismisses its UI; progress remains in
    // the saved-list section and the disabled initiating button cannot take focus.
    if (deleting) focusSavedTitle();
  };

  const handleDelete = async () => {
    if (!user) return onLoginClick();
    if (!deleteTarget || mutationInFlight.current) return;
    const target = deleteTarget;
    mutationInFlight.current = true;
    setDeleting(target);
    setDeleteNotice(null);
    try {
      await deletePromptSet(target.id);
      setDeletedIds((current) => new Set(current).add(target.id));
      setCreatedSets((current) => current.filter((item) => item.id !== target.id));
      setDeleteNotice({ name: target.name, error: false });
      const wasOpen = deleteDialogOpen.current;
      deleteDialogOpen.current = false;
      setDeleteTarget(null);
      if (wasOpen) focusSavedTitle();
      void resource.refresh();
    } catch {
      setDeleteNotice({ name: target.name, error: true });
    } finally {
      mutationInFlight.current = false;
      setDeleting(null);
    }
  };

  const handleOptimize = async () => {
    if (!user) return onLoginClick();
    if (!optInput.trim() || optimizing.current) return;
    optimizing.current = true;
    setOptBusy(true);
    setOptAnalyze(null);
    setOptResult(null);
    setOptError(null);
    setOptNotice(null);
    try {
      const r = await optimizePrompt({ prompt: optInput.trim(), target_model_id: optTarget });
      setOptAnalyze(r.analyze_message);
      setOptResult(r.optimized_prompt);
    } catch {
      setOptError("optimize");
    } finally {
      optimizing.current = false;
      setOptBusy(false);
    }
  };

  const handleCopy = async () => {
    if (!optResult) return;
    setOptNotice(null);
    setOptError(null);
    try {
      await navigator.clipboard.writeText(optResult);
      setOptNotice("copied");
    } catch {
      setOptError("copy");
    }
  };

  const handleUseOptimized = () => {
    if (optResult) {
      setNewPrompt(optResult);
      setNewName((n) => n || `Optimized ${new Date().toISOString().slice(0, 16)}`);
      setOptNotice("used");
      // 스크롤은 사용자가 알아서.
    }
  };

  return (
    <div className="mx-auto min-w-0 max-w-6xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
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
      <section aria-labelledby={`${fieldId}-opt-title`} className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4 sm:p-5 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span aria-hidden>✨</span>
          <h2 id={`${fieldId}-opt-title`} className="text-sm font-semibold text-gray-200">
            {lang === "en" ? "Bedrock Prompt Optimization" : "Bedrock 프롬프트 최적화"}
          </h2>
          <span className="text-[10px] text-gray-500">
            ({lang === "en" ? "Powered by bedrock-agent-runtime · OptimizePrompt" : "bedrock-agent-runtime · OptimizePrompt"})
          </span>
        </div>

        <label htmlFor={`${fieldId}-opt-input`} className="block text-xs text-gray-400">
          {lang === "en" ? "Prompt to optimize" : "최적화할 프롬프트"}
        </label>
        <textarea id={`${fieldId}-opt-input`}
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
          className="ui-input w-full disabled:opacity-50"
        />

        <div className="flex min-w-0 flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1 space-y-2">
            <label htmlFor={`${fieldId}-opt-target`} className="block text-xs text-gray-400">
            {lang === "en" ? "Target model" : "타겟 모델"}
            </label>
            <select id={`${fieldId}-opt-target`}
              value={optTarget}
              onChange={(e) => setOptTarget(e.target.value)}
              disabled={!user || optBusy}
              className="ui-input w-full max-w-full text-xs disabled:opacity-50"
            >
              {OPTIMIZE_TARGET_MODELS.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={handleOptimize}
            disabled={!user || optBusy || !optInput.trim()}
            className="ui-button-primary shrink-0"
          >
            {optBusy
              ? (lang === "en" ? "Optimizing..." : "최적화 중...")
              : (lang === "en" ? "Optimize" : "최적화")}
          </button>
        </div>

        {optError && (
          <ActionNotice error>
            {optError === "copy"
              ? (lang === "en" ? "Could not copy the prompt. Select the text and copy it manually." : "복사하지 못했습니다. 프롬프트를 선택해 직접 복사해 주세요.")
              : (lang === "en" ? "Could not optimize the prompt. Your input has been kept; try again." : "프롬프트를 최적화하지 못했습니다. 입력한 내용은 유지됩니다. 다시 시도해 주세요.")}
          </ActionNotice>
        )}
        {optNotice && (
          <ActionNotice>
            {optNotice === "copied"
              ? (lang === "en" ? "Prompt copied." : "프롬프트를 복사했습니다.")
              : (lang === "en" ? "Optimized prompt added to the new prompt-set form." : "최적화된 프롬프트를 새 프롬프트 세트 입력란에 넣었습니다.")}
          </ActionNotice>
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
            <div className="flex flex-wrap gap-2">
              <button
                type="button" onClick={handleCopy}
                className="ui-button"
              >
                {lang === "en" ? "Copy" : "복사"}
              </button>
              <button
                type="button" disabled={mutationBusy}
                onClick={handleUseOptimized}
                className="ui-button-primary"
              >
                {lang === "en" ? "Use in new prompt set" : "프롬프트 세트 입력으로 사용"}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* 새 프롬프트 세트 생성 */}
      <section aria-labelledby={`${fieldId}-create-title`} className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4 sm:p-5 space-y-4">
        <h2 id={`${fieldId}-create-title`} className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "New prompt set" : "새 프롬프트 세트"}
        </h2>
        {createNotice && (
          <ActionNotice error={createNotice.error}>
            {createNotice.error
              ? (lang === "en" ? `Could not save “${createNotice.name}”. Try again.` : `“${createNotice.name}” 프롬프트 세트를 저장하지 못했습니다. 다시 시도해 주세요.`)
              : (lang === "en" ? `Created “${createNotice.name}”.` : `“${createNotice.name}” 프롬프트 세트를 저장했습니다.`)}
          </ActionNotice>
        )}
        <form onSubmit={handleCreate} className="space-y-3">
          <label htmlFor={`${fieldId}-name`} className="block text-xs text-gray-400">{lang === "en" ? "Name" : "이름"}</label>
          <input id={`${fieldId}-name`}
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={!user || mutationBusy}
            placeholder={lang === "en" ? "Name" : "이름"}
            className="ui-input w-full disabled:opacity-50"
          />
          <label htmlFor={`${fieldId}-prompt`} className="block text-xs text-gray-400">{lang === "en" ? "Prompt text" : "프롬프트 내용"}</label>
          <textarea id={`${fieldId}-prompt`}
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            rows={4}
            disabled={!user || mutationBusy}
            placeholder={lang === "en" ? "Prompt text" : "프롬프트 내용"}
            className="ui-input w-full disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!user || mutationBusy || !newName.trim() || !newPrompt.trim()}
            className="ui-button-primary"
          >
            {creating
              ? (lang === "en" ? "Saving..." : "저장 중...")
              : (lang === "en" ? "Save" : "저장")}
          </button>
        </form>
      </section>

      {/* 저장된 프롬프트 세트 목록 */}
      <section aria-labelledby={`${fieldId}-saved-title`} className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4 sm:p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 ref={savedTitle} tabIndex={-1} id={`${fieldId}-saved-title`} className="text-sm font-semibold text-gray-200">
            {lang === "en" ? "Saved prompt sets" : "저장된 프롬프트 세트"}
          </h2>
          <span className="text-xs text-gray-500">{resource.data === null ? "—" : promptSets.length}</span>
        </div>
        <RefreshControls refreshing={resource.refreshing} onRefresh={() => { void resource.refresh(); }} updatedAt={resource.updatedAt} />
        <DataError error={resource.error} resource={lang === "en" ? "saved prompt sets" : "저장된 프롬프트 세트"}
          onRetry={() => { void resource.refresh(); }} hasData={hasData} />
        {deleteNotice && !deleteTarget && (
          <ActionNotice error={deleteNotice.error}>
            {deleteNotice.error
              ? (lang === "en" ? `Could not delete “${deleteNotice.name}”. Try again.` : `“${deleteNotice.name}” 프롬프트 세트를 삭제하지 못했습니다. 다시 시도해 주세요.`)
              : (lang === "en" ? `Deleted “${deleteNotice.name}”.` : `“${deleteNotice.name}” 프롬프트 세트를 삭제했습니다.`)}
          </ActionNotice>
        )}
        {deleting && !deleteTarget && (
          <p role="status" className="text-sm text-gray-400">
            {lang === "en" ? `Deleting “${deleting.name}”…` : `“${deleting.name}” 삭제 중…`}
          </p>
        )}
        {resource.loading && !hasData && <DataLoading label={t.common.loading} />}
        {!resource.error && !resource.refreshing && resource.data !== null && promptSets.length === 0 && (
          <DataEmpty
            title={lang === "en" ? "No prompt sets saved yet." : "아직 저장된 프롬프트 세트가 없습니다."}
            description={lang === "en" ? "Create a prompt set using the form above." : "위 입력란에서 새 프롬프트 세트를 만들어 보세요."}
          />
        )}
        {promptSets.length > 0 && (
          <div className="space-y-2">
            {promptSets.map((p) => (
              <div
                key={p.id}
                className="flex items-start justify-between gap-3 bg-gray-950/50 border border-gray-800 rounded-md p-3"
              >
                <div className="min-w-0 flex-1">
                  <h3 className="break-words text-sm font-semibold text-gray-200">{p.name}</h3>
                  <div className="text-xs text-gray-500 mt-1">
                    {p.prompts.length} {lang === "en" ? "prompts" : "프롬프트"}
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-xs text-gray-400 mt-2 line-clamp-3">
                    {p.prompts[0]}
                  </pre>
                </div>
                <button
                  type="button" onClick={() => openDeleteDialog(p)}
                  disabled={!user || mutationBusy}
                  aria-label={lang === "en" ? `Delete ${p.name}` : `${p.name} 삭제`}
                  className="ui-button shrink-0 text-rose-400 hover:text-rose-300"
                >
                  {lang === "en" ? "Delete" : "삭제"}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
      {deleteTarget && (
        <Dialog title={lang === "en" ? "Delete prompt set" : "프롬프트 세트 삭제"} onClose={closeDeleteDialog}>
          <p className="break-words text-sm leading-relaxed text-gray-300">
            {lang === "en" ? "Delete “" : "“"}
            <strong>{deleteTarget.name}</strong>
            {lang === "en" ? "”?" : "” 프롬프트 세트를 삭제할까요?"}
          </p>
          {deleteNotice?.error && (
            <ActionNotice error>
              {lang === "en"
                ? `Could not delete “${deleteNotice.name}”. Try again.`
                : `“${deleteNotice.name}” 프롬프트 세트를 삭제하지 못했습니다. 다시 시도해 주세요.`}
            </ActionNotice>
          )}
          {deleting && <p role="status" className="text-sm text-gray-400">{lang === "en" ? "Deleting…" : "삭제 중…"}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={closeDeleteDialog} disabled={deleting !== null} className="ui-button">
              {lang === "en" ? "Cancel" : "취소"}
            </button>
            <button type="button" onClick={handleDelete} disabled={deleting !== null} className="ui-button border-rose-600 bg-rose-600 text-white hover:border-rose-500 hover:bg-rose-500">
              {deleting ? (lang === "en" ? "Deleting…" : "삭제 중…") : (lang === "en" ? "Delete" : "삭제")}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
