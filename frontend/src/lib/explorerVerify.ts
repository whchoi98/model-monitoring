// Model Explorer verification (v2.40.0, ADR-035) — pure view logic for /models over GET /api/explorer/latest:
// card badge summary, change labels, failure filter and the texts of a verification result. vitest covers it.
// The backend stores result messages in Korean ("출력 없음", "시간 초과 90초", skip reasons); `reasonText` gives the
// English text for the ones it knows and leaves an exception line as it is.

import type { ExplorerChange, ExplorerExample, ExplorerStatus } from "./types";

type Lang = "ko" | "en";

export type ModelGrade = "passed" | "failed" | "skipped" | "none";

export interface ModelSummary {
  passed: number;
  failed: number;
  skipped: number;
  total: number;
  grade: ModelGrade;
}

/** Counts of a model's examples by result; examples without a result count only in `total`. */
export function summarizeModel(examples: ExplorerExample[]): ModelSummary {
  const count = (status: ExplorerStatus) => examples.filter((example) => example.result?.status === status).length;
  const passed = count("passed");
  const failed = count("failed");
  const skipped = count("skipped");
  const grade: ModelGrade = failed > 0 ? "failed" : passed > 0 ? "passed" : skipped > 0 ? "skipped" : "none";
  return { passed, failed, skipped, total: examples.length, grade };
}

/** Card badge: "✓ 3/3 통과", "✗ 1/3 실패", "검증 전", "✓ 2/3 통과, 1 건너뜀", "1/1 건너뜀". */
export function badgeLabel(summary: ModelSummary, lang: Lang): string {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  if (summary.grade === "none") return L("Not verified", "검증 전");
  if (summary.grade === "failed") return L(`✗ ${summary.failed}/${summary.total} failed`, `✗ ${summary.failed}/${summary.total} 실패`);
  if (summary.grade === "skipped") return L(`${summary.skipped}/${summary.total} skipped`, `${summary.skipped}/${summary.total} 건너뜀`);
  const skipped = summary.skipped > 0 ? L(`, ${summary.skipped} skipped`, `, ${summary.skipped} 건너뜀`) : "";
  return L(`✓ ${summary.passed}/${summary.total} passed${skipped}`, `✓ ${summary.passed}/${summary.total} 통과${skipped}`);
}

export function hasFailure(examples: ExplorerExample[]): boolean {
  return examples.some((example) => example.result?.status === "failed");
}

/** "통과" / "실패" / "건너뜀"; null (a cell the previous run did not have) is "신규". */
export function statusLabel(status: ExplorerStatus | null, lang: Lang): string {
  const labels: Record<ExplorerStatus, { en: string; ko: string }> = {
    passed: { en: "Passed", ko: "통과" },
    failed: { en: "Failed", ko: "실패" },
    skipped: { en: "Skipped", ko: "건너뜀" },
  };
  if (status === null) return lang === "en" ? "New" : "신규";
  return labels[status][lang];
}

const CHANGE_KIND: Record<ExplorerChange["kind"], { en: string; ko: string }> = {
  catalog: { en: "New", ko: "신규" },
  example: { en: "Example changed", ko: "예제 변경" },
  measured: { en: "Measured", ko: "실측" },
};

export function changeKindLabel(kind: ExplorerChange["kind"], lang: Lang): string {
  return CHANGE_KIND[kind][lang];
}

export function summarizeChanges(changes: ExplorerChange[]): Record<ExplorerChange["kind"], number> {
  const out = { catalog: 0, example: 0, measured: 0 };
  for (const change of changes) out[change.kind] += 1;
  return out;
}

export function changedModelIds(changes: ExplorerChange[]): Set<string> {
  return new Set(changes.map((change) => change.model_id));
}

/** A failed result's exception line and the stderr tail (after the first newline). */
export function splitError(message: string | null): { head: string; tail: string } {
  if (!message) return { head: "", tail: "" };
  const at = message.indexOf("\n");
  return at < 0 ? { head: message, tail: "" } : { head: message.slice(0, at), tail: message.slice(at + 1) };
}

/** The English text of the backend's Korean result messages; anything else (an exception line) is returned as is. */
export function reasonText(message: string, lang: Lang): string {
  if (lang === "ko") return message;
  if (message === "출력 없음") return "No output";
  if (message === "알 수 없는 플레이스홀더") return "Unknown placeholder";
  if (message === "런 시간 상한") return "Run time limit reached";
  const timeout = /^시간 초과 ([\d.]+)초$/.exec(message);
  if (timeout) return `Timed out after ${timeout[1]} s`;
  const missing = /^자격 증명 미주입: (.+)$/.exec(message);
  if (missing) return `Credentials not injected: ${missing[1]}`;
  return message;
}

/** "1.2초" / "1.2 s" — one decimal under a minute. */
export function formatLatency(ms: number | null, lang: Lang): string {
  if (ms === null || !Number.isFinite(ms)) return "";
  const seconds = (ms / 1000).toFixed(1);
  return lang === "en" ? `${seconds} s` : `${seconds}초`;
}
