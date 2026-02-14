"use client";

interface ProgressBarProps {
  completed: number;
  total: number;
  isRunning: boolean;
}

export default function ProgressBar({
  completed,
  total,
  isRunning,
}: ProgressBarProps) {
  if (!isRunning && completed === 0) return null;

  const pct = total > 0 ? (completed / total) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">
          {isRunning ? "Running probes..." : "Complete"}
        </span>
        <span className="text-gray-300 tabular-nums font-mono">
          {completed} / {total}
        </span>
      </div>
      <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            isRunning ? "bg-blue-500" : "bg-emerald-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
