"use client";

import { useState } from "react";
import { ProbeConfig, PromptSet } from "@/lib/types";
import { createPromptSet, deletePromptSet } from "@/lib/api";
import { useLang } from "@/lib/i18n-context";

const SUGGESTED_PROMPTS_KO: { l: string; p: string }[] = [
  {
    l: "💻 코드 생성",
    p:
      "AWS S3 bucket을 생성하는 최소 CDK TypeScript 코드를 작성하세요. " +
      "KMS 암호화(AWS managed key), Versioning 활성화, public access 차단을 포함하고, " +
      "cdk-nag 통과를 위한 필요 최소 suppressions만 추가하세요. " +
      "import문을 포함한 완전한 TypeScript 코드와 각 옵션의 보안 의미를 한 줄 주석으로 작성하세요.",
  },
  {
    l: "📋 JSON 추출",
    p:
      "다음 자유 형식 텍스트에서 회사명·직책·이메일·전화번호를 추출해 JSON으로만 응답하세요. " +
      "찾을 수 없는 필드는 null로 두세요.\n\n" +
      "텍스트: 안녕하세요, ACME Corporation의 시니어 클라우드 아키텍트 김철수입니다. " +
      "프로젝트 문의는 kim.cs@acme-corp.com 또는 02-1234-5678로 연락 주세요. " +
      "주말에는 응답이 늦을 수 있습니다.",
  },
  {
    l: "🧠 추론",
    p:
      "다음 문제를 단계별로 풀어 최종 답을 제시하세요.\n\n" +
      "지수와 영희가 같은 회사에서 일합니다. 지수는 매주 평일 9시에 출근하고, " +
      "영희는 화·목요일은 재택근무(정확히 7시간 30분 일함)하고 나머지 평일에는 8시 30분에 출근합니다. " +
      "두 사람 모두 점심에 1시간을 쓰고, 지수는 18시에, 영희는 17시 30분에 퇴근합니다. " +
      "한 달(평일 22일)에 두 사람의 총 근무시간 차이는 몇 시간 몇 분입니까?",
  },
  {
    l: "📝 요약",
    p:
      "다음 텍스트를 한국어로 3문장 이내로 요약하세요.\n\n" +
      "Amazon Bedrock은 Anthropic, Cohere, AI21 Labs, Meta, Mistral AI, Stability AI, " +
      "Amazon Titan/Nova 같은 선도 AI 회사의 고성능 foundation model을 단일 API로 제공하는 완전관리형 서비스입니다. " +
      "개발자는 모델 호스팅 인프라를 직접 관리하지 않고도 RAG, agent, fine-tuning, guardrails, " +
      "model evaluation 같은 기능을 활용해 enterprise-grade 생성형 AI 애플리케이션을 빠르게 구축할 수 있습니다. " +
      "또한 cross-region inference profile로 가용성을 높이고, Provisioned Throughput으로 안정적 capacity를 확보하며, " +
      "VPC endpoint와 KMS 통합으로 enterprise 보안 요구사항을 충족합니다.",
  },
  {
    l: "🌐 번역",
    p:
      "다음 영문 기술 문서를 한국어로 자연스럽게 번역하세요. 기술 용어는 한국어로 통용되는 표현 사용:\n\n" +
      "Server-Sent Events (SSE) is a unidirectional protocol that allows a server to push real-time updates " +
      "to a client over a single long-lived HTTP connection. Unlike WebSockets, SSE only flows from server to client " +
      "and uses standard HTTP, making it simpler to proxy, cache, and secure.",
  },
];

const SUGGESTED_PROMPTS_EN: { l: string; p: string }[] = [
  {
    l: "💻 Code generation",
    p:
      "Write minimal AWS CDK TypeScript code to create an S3 bucket with KMS encryption (AWS-managed key), " +
      "versioning enabled, and public access blocked. " +
      "Include only the cdk-nag suppressions strictly needed. " +
      "Output a complete TypeScript file with imports and a one-line comment per option explaining its security intent.",
  },
  {
    l: "📋 JSON extraction",
    p:
      "Extract company, title, email, and phone from the free-form text below as JSON only. " +
      "Use null for fields that cannot be found.\n\n" +
      "Text: Hi, I'm Charles Kim, Senior Cloud Architect at ACME Corporation. " +
      "For project inquiries, please reach me at kim.cs@acme-corp.com or +1-555-1234. " +
      "Responses may be slower on weekends.",
  },
  {
    l: "🧠 Reasoning",
    p:
      "Solve step by step and give the final answer.\n\n" +
      "Alice and Bob work at the same company. Alice arrives at 9 AM every weekday. " +
      "Bob works from home on Tuesdays and Thursdays (works exactly 7 hours 30 minutes); " +
      "on other weekdays he arrives at 8:30 AM. Both take 1 hour for lunch. " +
      "Alice leaves at 6 PM; Bob leaves at 5:30 PM on office days. " +
      "In a month with 22 weekdays, what is the difference in total work hours between Alice and Bob?",
  },
  {
    l: "📝 Summarization",
    p:
      "Summarize the text below in at most 3 sentences.\n\n" +
      "Amazon Bedrock is a fully managed service that offers high-performing foundation models from " +
      "Anthropic, Cohere, AI21 Labs, Meta, Mistral AI, Stability AI, and Amazon Titan/Nova through a single API. " +
      "Developers build enterprise-grade generative AI applications without managing model hosting, " +
      "leveraging RAG, agents, fine-tuning, guardrails, and model evaluation. " +
      "Cross-region inference profiles increase availability, Provisioned Throughput secures steady capacity, " +
      "and VPC endpoints with KMS integration meet enterprise security requirements.",
  },
  {
    l: "🌐 Translation",
    p:
      "Translate the following Korean technical text into natural English, preserving technical nuance:\n\n" +
      "Server-Sent Events(SSE)는 단방향 프로토콜로, 단일 장기 HTTP 연결을 통해 서버가 클라이언트에 " +
      "실시간 업데이트를 푸시할 수 있도록 합니다. WebSocket과 달리 서버→클라이언트로만 흐르고 " +
      "표준 HTTP를 사용하기 때문에 프록시·캐싱·보안 적용이 단순합니다.",
  },
];

interface ProbeConfigPanelProps {
  config: ProbeConfig;
  onChange: (config: ProbeConfig) => void;
  onRun: () => void;
  onStop: () => void;
  isRunning: boolean;
  promptSets: PromptSet[];
  onPromptSetsChange: () => void;
}

export default function ProbeConfigPanel({
  config,
  onChange,
  onRun,
  onStop,
  isRunning,
  promptSets,
  onPromptSetsChange,
}: ProbeConfigPanelProps) {
  const { lang } = useLang();
  const [saveName, setSaveName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);

  const handleSavePrompt = async () => {
    if (!saveName.trim() || !config.prompt.trim()) return;
    try {
      await createPromptSet({
        name: saveName.trim(),
        prompts: [config.prompt],
        temperature: config.temperature,
        max_tokens: config.max_tokens,
      });
      setSaveName("");
      setShowSaveInput(false);
      onPromptSetsChange();
    } catch (err) {
      console.error("Failed to save prompt set:", err);
    }
  };

  const handleDeletePromptSet = async (id: number) => {
    try {
      await deletePromptSet(id);
      onPromptSetsChange();
    } catch (err) {
      console.error("Failed to delete prompt set:", err);
    }
  };

  const handleLoadPromptSet = (ps: PromptSet) => {
    onChange({
      ...config,
      prompt: ps.prompts[0] || "",
      temperature: ps.temperature,
      max_tokens: ps.max_tokens,
    });
  };

  return (
    <div className="space-y-4">
      {/* Prompt Textarea */}
      <div>
        <label className="block text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Prompt
        </label>
        <textarea
          value={config.prompt}
          onChange={(e) => onChange({ ...config, prompt: e.target.value })}
          rows={4}
          placeholder="Enter your test prompt..."
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 resize-y"
        />
        {/* 추천 프롬프트 풍선말 - 한/영에 따라 prompt 내용이 해당 언어로 입력 */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(lang === "en" ? SUGGESTED_PROMPTS_EN : SUGGESTED_PROMPTS_KO).map((s) => (
            <button
              key={s.l}
              type="button"
              onClick={() => onChange({ ...config, prompt: s.p })}
              title={s.p.slice(0, 200)}
              className="px-2.5 py-1 text-[11px] rounded-full bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white border border-gray-700 transition-colors"
            >
              {s.l}
            </button>
          ))}
        </div>
      </div>

      {/* Saved Prompts */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
            Saved Prompts
          </label>
          <button
            onClick={() => setShowSaveInput(!showSaveInput)}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {showSaveInput ? "Cancel" : "Save Current"}
          </button>
        </div>
        {showSaveInput && (
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="Prompt set name..."
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
              onKeyDown={(e) => e.key === "Enter" && handleSavePrompt()}
            />
            <button
              onClick={handleSavePrompt}
              disabled={!saveName.trim()}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Save
            </button>
          </div>
        )}
        {promptSets.length > 0 ? (
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {promptSets.map((ps) => (
              <div
                key={ps.id}
                className="flex items-center justify-between px-2 py-1.5 rounded-md hover:bg-gray-800/60 group"
              >
                <button
                  onClick={() => handleLoadPromptSet(ps)}
                  className="text-sm text-gray-300 hover:text-gray-100 truncate text-left flex-1"
                  title={ps.prompts[0]}
                >
                  {ps.name}
                </button>
                <button
                  onClick={() => handleDeletePromptSet(ps.id)}
                  className="text-gray-600 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-all ml-2 flex-shrink-0"
                >
                  <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-600 italic">No saved prompts</p>
        )}
      </div>

      {/* Parameters */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Parameters
        </h3>

        {/* Temperature */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-gray-400">Temperature</label>
            <span className="text-xs text-gray-300 tabular-nums">
              {config.temperature.toFixed(1)}
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={config.temperature}
            onChange={(e) =>
              onChange({ ...config, temperature: parseFloat(e.target.value) })
            }
            className="w-full h-1.5 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
          />
          <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
            <span>Precise</span>
            <span>Creative</span>
          </div>
        </div>

        {/* Max Tokens */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">Max Tokens</label>
          <input
            type="number"
            min={64}
            max={4096}
            step={64}
            value={config.max_tokens}
            onChange={(e) =>
              onChange({
                ...config,
                max_tokens: Math.min(
                  4096,
                  Math.max(64, parseInt(e.target.value) || 64)
                ),
              })
            }
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-100 tabular-nums focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          />
        </div>

        {/* Concurrency */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">Concurrency</label>
          <input
            type="number"
            min={1}
            max={10}
            value={config.concurrency}
            onChange={(e) =>
              onChange({
                ...config,
                concurrency: Math.min(
                  10,
                  Math.max(1, parseInt(e.target.value) || 1)
                ),
              })
            }
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-100 tabular-nums focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          />
        </div>

        {/* Repeat Count */}
        <div>
          <label className="text-xs text-gray-400 block mb-1">Repeat Count</label>
          <input
            type="number"
            min={1}
            max={20}
            value={config.repeat_count}
            onChange={(e) =>
              onChange({
                ...config,
                repeat_count: Math.min(
                  20,
                  Math.max(1, parseInt(e.target.value) || 1)
                ),
              })
            }
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-100 tabular-nums focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          />
        </div>
      </div>

      {/* Run / Stop Button */}
      {isRunning ? (
        <button
          onClick={onStop}
          className="w-full py-2.5 bg-rose-600 hover:bg-rose-500 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <svg
            className="w-4 h-4"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <rect x="6" y="6" width="12" height="12" rx="1" />
          </svg>
          Stop
        </button>
      ) : (
        <button
          onClick={onRun}
          disabled={config.model_ids.length === 0 || !config.prompt.trim()}
          className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <svg
            className="w-4 h-4"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <path d="M8 5v14l11-7z" />
          </svg>
          Run Probe
        </button>
      )}

      {config.model_ids.length === 0 && (
        <p className="text-xs text-amber-500 text-center">
          Select at least one model
        </p>
      )}
    </div>
  );
}
