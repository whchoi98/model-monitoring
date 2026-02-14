"use client";

import { useState } from "react";
import { ProbeConfig, PromptSet } from "@/lib/types";
import { createPromptSet, deletePromptSet } from "@/lib/api";

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
