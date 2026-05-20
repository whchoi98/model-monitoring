"use client";

import { useEffect, useMemo, useState } from "react";
import { ModelInfo, AuthUser } from "@/lib/types";
import { compareStream, CompareResult, fetchModels } from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { groupByFamily, sortResults } from "@/lib/sortModels";
import { estimateCost, formatCost } from "@/lib/pricing";
import MessageMarkdown from "./chat/MessageMarkdown";

interface Props {
  user: AuthUser | null;
  onLoginClick: () => void;
}

// 추천 비교 프롬프트 — 모델별 강·약점이 잘 드러나는 다양한 task type.
const SUGGESTED_COMPARE_PROMPTS_KO: { label: string; prompt: string }[] = [
  {
    label: "💻 코드 생성 (CDK)",
    prompt:
      "AWS S3 bucket을 만드는 최소 CDK TypeScript 코드를 작성하세요. 다음 요구사항 포함:\n" +
      "- KMS 암호화 (AWS managed key)\n" +
      "- Versioning 활성화\n" +
      "- public access 차단\n" +
      "- cdk-nag 통과를 위한 필요 최소 suppressions만\n\n" +
      "출력: import문 포함 완전한 TypeScript 코드 + 한 줄 주석으로 각 옵션의 보안 의미 설명.",
  },
  {
    label: "📋 JSON 추출",
    prompt:
      "다음 자유 형식 텍스트에서 회사명·직책·이메일·전화번호를 추출해 JSON으로만 응답하세요. " +
      "찾을 수 없는 필드는 null로 두세요.\n\n" +
      "텍스트: 안녕하세요, ACME Corporation의 시니어 클라우드 아키텍트 김철수입니다. " +
      "프로젝트 문의는 kim.cs@acme-corp.com 또는 02-1234-5678로 연락 주세요. " +
      "주말에는 응답이 늦을 수 있습니다.",
  },
  {
    label: "🧠 추론/계산",
    prompt:
      "다음 문제를 단계별로 풀어 최종 답을 제시하세요.\n\n" +
      "지수와 영희가 같은 회사에서 일합니다. 지수는 매주 평일 9시에 출근하고, " +
      "영희는 화·목요일은 재택근무하고 나머지 평일에는 8시 30분에 출근합니다. " +
      "둘 다 점심에 1시간을 쓰고, 지수는 18시에, 영희는 17시 30분에 퇴근합니다. " +
      "재택 근무일에는 영희는 정확히 7시간 30분 일합니다. " +
      "한 달(평일 22일)에 두 사람의 총 근무시간 차이는?",
  },
  {
    label: "📝 요약",
    prompt:
      "다음 텍스트를 한국어로 3문장 이내로 요약하세요.\n\n" +
      "Amazon Bedrock은 Anthropic, Cohere, AI21 Labs, Meta, Mistral AI, Stability AI, Amazon Titan/Nova 같은 " +
      "선도 AI 회사의 고성능 foundation model을 단일 API로 제공하는 완전관리형 서비스입니다. " +
      "개발자는 모델 호스팅 인프라를 직접 관리하지 않고도 RAG, agent, fine-tuning, guardrails, " +
      "model evaluation 같은 기능을 활용해 enterprise-grade 생성형 AI 애플리케이션을 빠르게 구축할 수 있습니다. " +
      "또한 cross-region inference profile을 통해 가용성을 높이고, " +
      "Provisioned Throughput으로 안정적 capacity를 확보할 수 있으며, " +
      "VPC endpoint와 KMS 통합으로 enterprise 보안 요구사항을 충족합니다.",
  },
  {
    label: "🌐 번역",
    prompt:
      "다음 영문 기술 문서를 한국어로 자연스럽게 번역하세요. 기술 용어는 한국어로 통용되는 표현 사용:\n\n" +
      "Server-Sent Events (SSE) is a unidirectional protocol that allows a server to push real-time updates " +
      "to a client over a single long-lived HTTP connection. Unlike WebSockets, SSE only flows from server to client " +
      "and uses standard HTTP, making it simpler to proxy, cache, and secure. SSE is particularly well-suited for " +
      "streaming LLM token outputs because each event boundary is clearly defined and the connection automatically " +
      "reconnects on transient network failures. Modern browsers natively support SSE via the EventSource API.",
  },
];

const SUGGESTED_COMPARE_PROMPTS_EN: { label: string; prompt: string }[] = [
  {
    label: "💻 Code generation (CDK)",
    prompt:
      "Write minimal AWS CDK TypeScript code to create an S3 bucket with:\n" +
      "- KMS encryption (AWS-managed key)\n" +
      "- Versioning enabled\n" +
      "- Public access blocked\n" +
      "- Only the cdk-nag suppressions strictly needed\n\n" +
      "Output: complete TypeScript with imports + one-line comment per option explaining its security intent.",
  },
  {
    label: "📋 JSON extraction",
    prompt:
      "Extract company name, job title, email, and phone number from the free-form text below as JSON only. " +
      "Use null for fields that cannot be found.\n\n" +
      "Text: Hi, I'm Charles Kim, Senior Cloud Architect at ACME Corporation. " +
      "For project inquiries, please reach me at kim.cs@acme-corp.com or +1-555-1234. " +
      "Responses may be slower on weekends.",
  },
  {
    label: "🧠 Reasoning",
    prompt:
      "Solve step by step and give the final answer.\n\n" +
      "Alice and Bob work at the same company. Alice arrives at 9 AM every weekday. " +
      "Bob works from home on Tuesdays and Thursdays; on other weekdays he arrives at 8:30 AM. " +
      "Both take 1 hour for lunch. Alice leaves at 6 PM; Bob leaves at 5:30 PM on office days. " +
      "On WFH days Bob works exactly 7 hours 30 minutes. " +
      "In a month with 22 weekdays, what is the difference in total work hours between Alice and Bob?",
  },
  {
    label: "📝 Summarization",
    prompt:
      "Summarize the text below in at most 3 sentences.\n\n" +
      "Amazon Bedrock is a fully managed service that offers high-performing foundation models from leading AI " +
      "companies like Anthropic, Cohere, AI21 Labs, Meta, Mistral AI, Stability AI, and Amazon Titan/Nova through " +
      "a single API. Developers can build enterprise-grade generative AI applications without managing model " +
      "hosting infrastructure, leveraging features like RAG, agents, fine-tuning, guardrails, and model evaluation. " +
      "Cross-region inference profiles increase availability, Provisioned Throughput secures steady capacity, " +
      "and VPC endpoints with KMS integration meet enterprise security requirements.",
  },
  {
    label: "🌐 Translation",
    prompt:
      "Translate the following Korean text into natural English, preserving technical nuance:\n\n" +
      "Server-Sent Events(SSE)는 단방향 프로토콜로, 단일 장기 HTTP 연결을 통해 서버가 클라이언트에 " +
      "실시간 업데이트를 푸시할 수 있도록 합니다. WebSocket과 달리 서버→클라이언트로만 흐르고 " +
      "표준 HTTP를 사용하기 때문에 프록시·캐싱·보안 적용이 단순합니다. LLM 토큰 출력 스트리밍에 " +
      "특히 적합하며, 일시적 네트워크 장애에도 EventSource API가 자동 재연결합니다.",
  },
];

interface RunningState {
  model_id: string;
  model_name: string;
  text: string;
  ttft_ms?: number | null;
  result?: CompareResult;
  error?: string;
}

export default function ComparePanel({ user, onLoginClick }: Props) {
  const { lang } = useLang();

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [maxTokens, setMaxTokens] = useState(512);
  const [temperature, setTemperature] = useState(0.1);
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<Map<string, RunningState>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [controller, setController] = useState<AbortController | null>(null);

  useEffect(() => {
    fetchModels().then(setModels).catch((e) => console.error(e));
  }, []);

  const sortedModels = useMemo(
    () => sortResults(models.map((m) => ({ ...m, model_name: m.name }))) as (ModelInfo & { model_name: string })[],
    [models],
  );
  const modelGroups = useMemo(
    () => groupByFamily(models.map((m) => ({ ...m, model_name: m.name }))) as (ModelInfo & { model_name: string })[][],
    [models],
  );

  const toggleModel = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectAll = () => setSelected(new Set(sortedModels.map((m) => m.id)));
  const clearSelection = () => setSelected(new Set());

  const handleRun = () => {
    if (!user) return onLoginClick();
    if (!prompt.trim() || selected.size === 0 || running) return;
    setRunning(true);
    setError(null);
    // 초기화 - 선택된 모델 각각의 빈 state.
    const init = new Map<string, RunningState>();
    selected.forEach((id) => {
      const m = models.find((x) => x.id === id);
      init.set(id, { model_id: id, model_name: m?.name ?? id, text: "" });
    });
    setRuns(init);

    const ac = compareStream(
      {
        prompt: prompt.trim(),
        model_ids: Array.from(selected),
        max_tokens: maxTokens,
        temperature,
      },
      {
        onToken: (d) => {
          setRuns((prev) => {
            const next = new Map(prev);
            const cur = next.get(d.model_id);
            if (cur) next.set(d.model_id, { ...cur, text: cur.text + d.token });
            return next;
          });
        },
        onTtft: (d) => {
          setRuns((prev) => {
            const next = new Map(prev);
            const cur = next.get(d.model_id);
            if (cur) next.set(d.model_id, { ...cur, ttft_ms: d.ttft_ms });
            return next;
          });
        },
        onResult: (r) => {
          setRuns((prev) => {
            const next = new Map(prev);
            const cur = next.get(r.model_id);
            if (cur) next.set(r.model_id, { ...cur, result: r, text: r.output_text });
            return next;
          });
        },
        onModelError: (d) => {
          setRuns((prev) => {
            const next = new Map(prev);
            const cur = next.get(d.model_id);
            if (cur) next.set(d.model_id, { ...cur, error: d.error });
            return next;
          });
        },
        onComplete: () => {
          setRunning(false);
        },
        onError: (e) => {
          setError(e.message);
          setRunning(false);
        },
      },
    );
    setController(ac);
  };

  const handleCancel = () => {
    controller?.abort();
    setRunning(false);
  };

  const runArray = Array.from(runs.values()).sort((a, b) => a.model_name.localeCompare(b.model_name));

  // 비교 매트릭스 - 최단 TTFT / 최단 latency / 최고 TPS / 최저 비용 강조.
  const matrix = useMemo(() => {
    const list = runArray
      .filter((r) => r.result?.status === "success")
      .map((r) => {
        const cost = estimateCost(r.model_id, r.result!.input_tokens, r.result!.output_tokens);
        return { ...r, cost };
      });
    if (list.length === 0) return null;
    const min = (sel: (x: (typeof list)[0]) => number | null): number | null =>
      list.reduce<number | null>((acc, x) => {
        const v = sel(x);
        if (v === null) return acc;
        return acc === null || v < acc ? v : acc;
      }, null);
    const max = (sel: (x: (typeof list)[0]) => number | null): number | null =>
      list.reduce<number | null>((acc, x) => {
        const v = sel(x);
        if (v === null) return acc;
        return acc === null || v > acc ? v : acc;
      }, null);
    return {
      list,
      bestTtft: min((x) => x.result!.ttft_ms),
      bestLatency: min((x) => x.result!.total_latency_ms),
      bestTps: max((x) => x.result!.tps),
      bestCost: min((x) => x.cost),
    };
  }, [runArray]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">
          {lang === "en" ? "Comparison Lab" : "비교 랩"}
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          {lang === "en"
            ? "Send one prompt to N models in parallel and compare responses, latency, and cost."
            : "한 프롬프트를 여러 모델에 동시 호출해 응답·지연·비용을 비교합니다."}
        </p>
      </div>

      {/* 입력 영역 */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 space-y-3">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          disabled={running}
          placeholder={lang === "en" ? "Enter the prompt to compare..." : "비교할 프롬프트를 입력하세요..."}
          className="w-full bg-gray-950 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
        />

        {/* 추천 비교 프롬프트 풍선말 - 모델별 강·약점이 잘 드러나는 task type 5종 */}
        <div className="flex flex-col gap-2">
          <span className="text-[10px] uppercase tracking-wider text-gray-500">
            {lang === "en" ? "Suggested prompts" : "추천 비교 프롬프트"}
          </span>
          <div className="flex flex-wrap gap-1.5">
            {(lang === "en" ? SUGGESTED_COMPARE_PROMPTS_EN : SUGGESTED_COMPARE_PROMPTS_KO).map(
              (item) => (
                <button
                  key={item.label}
                  type="button"
                  disabled={running}
                  onClick={() => setPrompt(item.prompt)}
                  className="px-2.5 py-1 text-[11px] rounded-full bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white border border-gray-700 transition-colors disabled:opacity-50"
                  title={item.prompt.slice(0, 200)}
                >
                  {item.label}
                </button>
              ),
            )}
          </div>
        </div>

        <div className="flex items-center gap-4 flex-wrap text-xs text-gray-400">
          <label className="flex items-center gap-2">
            max_tokens
            <input
              type="number"
              value={maxTokens}
              onChange={(e) => setMaxTokens(Number(e.target.value) || 512)}
              min={1}
              max={8192}
              disabled={running}
              className="w-20 bg-gray-950 border border-gray-700 rounded-md px-2 py-1 text-gray-100 disabled:opacity-50"
            />
          </label>
          <label className="flex items-center gap-2">
            temperature
            <input
              type="number"
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
              min={0}
              max={2}
              step={0.1}
              disabled={running}
              className="w-20 bg-gray-950 border border-gray-700 rounded-md px-2 py-1 text-gray-100 disabled:opacity-50"
            />
          </label>
        </div>

        {/* 모델 선택 */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-400">
              {lang === "en" ? "Models" : "모델"} ({selected.size}/{sortedModels.length})
            </span>
            <button
              type="button"
              onClick={selectAll}
              disabled={running}
              className="text-blue-400 hover:text-blue-300 underline disabled:opacity-50"
            >
              {lang === "en" ? "Select all" : "전체 선택"}
            </button>
            <button
              type="button"
              onClick={clearSelection}
              disabled={running}
              className="text-gray-500 hover:text-gray-300 underline disabled:opacity-50"
            >
              {lang === "en" ? "Clear" : "전체 해제"}
            </button>
          </div>
          <div className="space-y-2">
            {modelGroups.map((grp, gi) => (
              <div key={gi} className="flex flex-wrap gap-1.5">
                {grp.map((m) => {
                  const isSel = selected.has(m.id);
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => toggleModel(m.id)}
                      disabled={running}
                      className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                        isSel
                          ? "bg-blue-600 text-white"
                          : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                      } disabled:opacity-50`}
                    >
                      {isSel ? "✓ " : ""}{m.name}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          {running ? (
            <button
              type="button"
              onClick={handleCancel}
              className="px-4 py-2 text-sm font-medium rounded-md bg-rose-600 hover:bg-rose-500 text-white"
            >
              {lang === "en" ? "Cancel" : "중지"}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleRun}
              disabled={!user || !prompt.trim() || selected.size === 0}
              className="px-4 py-2 text-sm font-medium rounded-md bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {lang === "en" ? "Run" : "실행"}
            </button>
          )}
          {error && <span className="text-xs text-rose-400">{error}</span>}
        </div>
      </div>

      {/* 비교 매트릭스 */}
      {matrix && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 overflow-x-auto">
          <h2 className="text-sm font-semibold text-gray-200 mb-3">
            {lang === "en" ? "Metrics Matrix" : "지표 비교"}
          </h2>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 pr-3">Model</th>
                <th className="text-right py-2 px-2">TTFT</th>
                <th className="text-right py-2 px-2">Latency</th>
                <th className="text-right py-2 px-2">TPS</th>
                <th className="text-right py-2 px-2">In tok</th>
                <th className="text-right py-2 px-2">Out tok</th>
                <th className="text-right py-2 pl-2">Cost</th>
              </tr>
            </thead>
            <tbody>
              {matrix.list.map((r) => {
                const cls = (v: number | null, best: number | null, lower = true) =>
                  v !== null && best !== null && (lower ? v === best : v === best)
                    ? "text-emerald-400 font-semibold"
                    : "text-gray-200";
                return (
                  <tr key={r.model_id} className="border-b border-gray-800/50">
                    <td className="py-2 pr-3 text-gray-300 truncate max-w-[280px]" title={r.model_id}>
                      {r.model_name}
                    </td>
                    <td className={`text-right py-2 px-2 tabular-nums ${cls(r.result!.ttft_ms, matrix.bestTtft)}`}>
                      {r.result!.ttft_ms !== null ? `${r.result!.ttft_ms.toFixed(0)} ms` : "—"}
                    </td>
                    <td className={`text-right py-2 px-2 tabular-nums ${cls(r.result!.total_latency_ms, matrix.bestLatency)}`}>
                      {(r.result!.total_latency_ms / 1000).toFixed(2)} s
                    </td>
                    <td className={`text-right py-2 px-2 tabular-nums ${cls(r.result!.tps, matrix.bestTps, false)}`}>
                      {r.result!.tps !== null ? r.result!.tps.toFixed(1) : "—"}
                    </td>
                    <td className="text-right py-2 px-2 tabular-nums text-gray-400">{r.result!.input_tokens}</td>
                    <td className="text-right py-2 px-2 tabular-nums text-gray-400">{r.result!.output_tokens}</td>
                    <td className={`text-right py-2 pl-2 tabular-nums ${cls(r.cost, matrix.bestCost)}`}>
                      {formatCost(r.cost)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="text-[10px] text-gray-600 mt-2">
            {lang === "en"
              ? "Best value per column shown in green. Cost is estimated from public Bedrock/Anthropic pricing."
              : "각 컬럼의 최적 값을 녹색으로 강조. 비용은 Bedrock/Anthropic 공개 단가 기반 추정치입니다."}
          </p>
        </div>
      )}

      {/* 응답 카드 grid */}
      {runArray.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {runArray.map((r) => (
            <div
              key={r.model_id}
              className={`rounded-xl border p-4 ${
                r.error
                  ? "bg-rose-950/20 border-rose-900/30"
                  : "bg-gray-900/50 border-gray-800"
              }`}
            >
              <div className="flex items-start justify-between mb-2 gap-2">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-gray-200 truncate">{r.model_name}</h3>
                  <code className="text-[10px] text-gray-500 truncate block">{r.model_id}</code>
                </div>
                {r.result?.status === "success" ? (
                  <div className="text-[10px] text-gray-500 text-right shrink-0">
                    <div>TTFT {r.result.ttft_ms !== null ? `${r.result.ttft_ms.toFixed(0)}ms` : "—"}</div>
                    <div>Total {(r.result.total_latency_ms / 1000).toFixed(2)}s</div>
                  </div>
                ) : r.error ? (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/30">
                    {lang === "en" ? "ERROR" : "에러"}
                  </span>
                ) : (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    {r.ttft_ms ? `TTFT ${r.ttft_ms.toFixed(0)}ms` : "..."}
                  </span>
                )}
              </div>
              {r.error ? (
                <div className="text-xs text-rose-400 break-words">{r.error}</div>
              ) : (
                <div className="text-xs text-gray-100 max-h-96 overflow-y-auto">
                  {r.text ? <MessageMarkdown text={r.text} /> : (
                    <span className="text-gray-500">
                      {r.ttft_ms ? "" : (lang === "en" ? "Waiting..." : "대기 중...")}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
