"use client";

import { useState, useMemo } from "react";
import { ProbeResult } from "@/lib/types";

interface ResultsTableProps {
  results: ProbeResult[];
}

type SortField =
  | "model_name"
  | "iteration"
  | "ttft_ms"
  | "total_latency_ms"
  | "server_latency_ms"
  | "tps"
  | "input_tokens"
  | "output_tokens"
  | "status";

type SortDir = "asc" | "desc";

function getTTFTColor(ttft: number | null): string {
  if (ttft === null) return "text-gray-500";
  if (ttft < 300) return "text-emerald-400";
  if (ttft < 800) return "text-amber-400";
  return "text-rose-400";
}

function getTPSColor(tps: number | null): string {
  if (tps === null) return "text-gray-500";
  if (tps > 80) return "text-emerald-400";
  if (tps > 40) return "text-amber-400";
  return "text-rose-400";
}

function getLatencyColor(latency: number | null): string {
  if (latency === null) return "text-gray-500";
  if (latency < 3000) return "text-emerald-400";
  if (latency < 8000) return "text-amber-400";
  return "text-rose-400";
}

function formatNum(val: number | null, decimals: number = 0): string {
  if (val === null || val === undefined) return "-";
  return val.toFixed(decimals);
}

export default function ResultsTable({ results }: ResultsTableProps) {
  const [sortField, setSortField] = useState<SortField>("model_name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const sortedResults = useMemo(() => {
    const sorted = [...results].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];

      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      const aNum = Number(aVal);
      const bNum = Number(bVal);
      return sortDir === "asc" ? aNum - bNum : bNum - aNum;
    });
    return sorted;
  }, [results, sortField, sortDir]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  };

  if (results.length === 0) return null;

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field)
      return <span className="text-gray-700 ml-1">&uarr;&darr;</span>;
    return (
      <span className="text-blue-400 ml-1">
        {sortDir === "asc" ? "\u2191" : "\u2193"}
      </span>
    );
  };

  const columns: { field: SortField; label: string; shortLabel?: string }[] = [
    { field: "model_name", label: "Model" },
    { field: "iteration", label: "Iter", shortLabel: "#" },
    { field: "ttft_ms", label: "TTFT (ms)" },
    { field: "total_latency_ms", label: "Latency (ms)" },
    { field: "server_latency_ms", label: "Server (ms)" },
    { field: "tps", label: "TPS" },
    { field: "input_tokens", label: "In Tok" },
    { field: "output_tokens", label: "Out Tok" },
    { field: "status", label: "Status" },
  ];

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-gray-200">Results</h2>
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                {columns.map((col) => (
                  <th
                    key={col.field}
                    onClick={() => handleSort(col.field)}
                    className="px-3 py-2.5 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider cursor-pointer hover:text-gray-200 select-none whitespace-nowrap"
                  >
                    {col.shortLabel || col.label}
                    <SortIcon field={col.field} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {sortedResults.map((result, idx) => (
                <>
                  <tr
                    key={`row-${idx}`}
                    className="hover:bg-gray-800/30 transition-colors cursor-pointer"
                    onClick={() =>
                      setExpandedRow(expandedRow === idx ? null : idx)
                    }
                  >
                    <td className="px-3 py-2 text-gray-200 font-medium whitespace-nowrap">
                      {result.model_name}
                    </td>
                    <td className="px-3 py-2 text-gray-400 tabular-nums">
                      {result.iteration}
                    </td>
                    <td
                      className={`px-3 py-2 tabular-nums font-mono ${getTTFTColor(
                        result.ttft_ms
                      )}`}
                    >
                      {formatNum(result.ttft_ms)}
                    </td>
                    <td
                      className={`px-3 py-2 tabular-nums font-mono ${getLatencyColor(
                        result.total_latency_ms
                      )}`}
                    >
                      {formatNum(result.total_latency_ms)}
                    </td>
                    <td className="px-3 py-2 text-gray-300 tabular-nums font-mono">
                      {formatNum(result.server_latency_ms)}
                    </td>
                    <td
                      className={`px-3 py-2 tabular-nums font-mono ${getTPSColor(
                        result.tps
                      )}`}
                    >
                      {formatNum(result.tps, 1)}
                    </td>
                    <td className="px-3 py-2 text-gray-400 tabular-nums">
                      {formatNum(result.input_tokens)}
                    </td>
                    <td className="px-3 py-2 text-gray-400 tabular-nums">
                      {formatNum(result.output_tokens)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          result.status === "success"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                        }`}
                      >
                        {result.status}
                      </span>
                    </td>
                  </tr>
                  {expandedRow === idx && (
                    <tr key={`expanded-${idx}`} className="bg-gray-800/20">
                      <td colSpan={9} className="px-4 py-3">
                        {result.error_message && (
                          <div className="mb-2">
                            <span className="text-xs text-rose-400 font-semibold">
                              Error:{" "}
                            </span>
                            <span className="text-xs text-rose-300">
                              {result.error_message}
                            </span>
                          </div>
                        )}
                        {result.output_text && (
                          <div>
                            <span className="text-xs text-gray-400 font-semibold">
                              Output:{" "}
                            </span>
                            <span className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words">
                              {result.output_text.slice(0, 500)}
                              {(result.output_text?.length || 0) > 500
                                ? "..."
                                : ""}
                            </span>
                          </div>
                        )}
                        {!result.error_message && !result.output_text && (
                          <span className="text-xs text-gray-500 italic">
                            No additional details
                          </span>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
