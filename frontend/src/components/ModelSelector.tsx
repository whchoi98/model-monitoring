"use client";

import { ModelInfo } from "@/lib/types";

interface ModelSelectorProps {
  selectedModels: string[];
  onChange: (ids: string[]) => void;
  models: ModelInfo[];
}

interface ModelGroup {
  label: string;
  prefix: string;
  models: ModelInfo[];
}

function groupModels(models: ModelInfo[]): ModelGroup[] {
  const groups: ModelGroup[] = [
    { label: "Anthropic (US)", prefix: "us.anthropic", models: [] },
    { label: "Anthropic (Global)", prefix: "global.anthropic", models: [] },
    { label: "Amazon", prefix: "us.amazon", models: [] },
    { label: "Other", prefix: "", models: [] },
  ];

  for (const model of models) {
    let placed = false;
    for (const group of groups) {
      if (group.prefix && model.id.startsWith(group.prefix)) {
        group.models.push(model);
        placed = true;
        break;
      }
    }
    if (!placed) {
      groups[groups.length - 1].models.push(model);
    }
  }

  return groups.filter((g) => g.models.length > 0);
}

export default function ModelSelector({
  selectedModels,
  onChange,
  models,
}: ModelSelectorProps) {
  const groups = groupModels(models);

  const toggleModel = (id: string) => {
    if (selectedModels.includes(id)) {
      onChange(selectedModels.filter((m) => m !== id));
    } else {
      onChange([...selectedModels, id]);
    }
  };

  const selectAllInGroup = (group: ModelGroup) => {
    const groupIds = group.models.map((m) => m.id);
    const allSelected = groupIds.every((id) => selectedModels.includes(id));

    if (allSelected) {
      onChange(selectedModels.filter((id) => !groupIds.includes(id)));
    } else {
      const newSelected = new Set([...selectedModels, ...groupIds]);
      onChange(Array.from(newSelected));
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        Models
      </h3>
      {groups.map((group) => {
        const groupIds = group.models.map((m) => m.id);
        const allSelected = groupIds.every((id) => selectedModels.includes(id));
        const someSelected =
          !allSelected && groupIds.some((id) => selectedModels.includes(id));

        return (
          <div key={group.label} className="space-y-1">
            <button
              onClick={() => selectAllInGroup(group)}
              className="flex items-center gap-2 text-xs font-medium text-gray-400 hover:text-gray-200 transition-colors w-full text-left"
            >
              <div
                className={`w-3.5 h-3.5 rounded border flex items-center justify-center transition-colors ${
                  allSelected
                    ? "bg-blue-500 border-blue-500"
                    : someSelected
                    ? "bg-blue-500/40 border-blue-500"
                    : "border-gray-600"
                }`}
              >
                {allSelected && (
                  <svg
                    className="w-2.5 h-2.5 text-white"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                )}
                {someSelected && (
                  <div className="w-1.5 h-1.5 bg-white rounded-sm" />
                )}
              </div>
              {group.label}
            </button>
            <div className="ml-2 space-y-0.5">
              {group.models.map((model) => (
                <label
                  key={model.id}
                  className="flex items-center gap-2 py-0.5 px-2 rounded-md hover:bg-gray-800/50 cursor-pointer transition-colors group"
                >
                  <input
                    type="checkbox"
                    checked={selectedModels.includes(model.id)}
                    onChange={() => toggleModel(model.id)}
                    className="sr-only"
                  />
                  <div
                    className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 transition-colors ${
                      selectedModels.includes(model.id)
                        ? "bg-blue-500 border-blue-500"
                        : "border-gray-600 group-hover:border-gray-400"
                    }`}
                  >
                    {selectedModels.includes(model.id) && (
                      <svg
                        className="w-2.5 h-2.5 text-white"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={3}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    )}
                  </div>
                  <span className="text-sm text-gray-300 group-hover:text-gray-100 truncate">
                    {model.name}
                  </span>
                </label>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
