import type { CostSummary } from "./api";

/** Extrapolate the loaded summary's rate, independently of any pending filter change. */
export function projectMonthlyCost(summary: Pick<CostSummary, "window" | "total_cost_usd"> | null): number | null {
  if (!summary) return null;
  const hours = summary.window.endsWith("d")
    ? parseInt(summary.window) * 24
    : summary.window.endsWith("h")
      ? parseInt(summary.window)
      : 1;
  if (hours === 0) return null;
  return (summary.total_cost_usd / hours) * 24 * 30;
}
