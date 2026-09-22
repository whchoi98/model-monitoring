import type { Lang } from "./i18n";

/** Database timestamps without an explicit offset are UTC, never browser-local. */
export function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const normalized = /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(value) && !/(?:z|[+-]\d\d:\d\d)$/i.test(value)
    ? `${value}Z`
    : value;
  const timestamp = Date.parse(normalized);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function formatDateTime(value: string | number | null | undefined, lang: Lang): string {
  const timestamp = typeof value === "number" ? value : parseTimestamp(value);
  if (timestamp == null || !Number.isFinite(timestamp)) return "—";
  return new Intl.DateTimeFormat(lang === "ko" ? "ko-KR" : "en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    second: "2-digit", hour12: false, timeZoneName: "short",
  }).format(timestamp);
}

export function formatAge(value: string | number | null | undefined, lang: Lang, now = Date.now()): string {
  const timestamp = typeof value === "number" ? value : parseTimestamp(value);
  if (timestamp == null || !Number.isFinite(timestamp)) return "—";
  const seconds = Math.round((timestamp - now) / 1000);
  if (Math.abs(seconds) < 60) return lang === "ko" ? "방금 전" : "Just now";
  const formatter = new Intl.RelativeTimeFormat(lang === "ko" ? "ko-KR" : "en-US", { numeric: "auto" });
  if (Math.abs(seconds) < 3600) return formatter.format(Math.round(seconds / 60), "minute");
  if (Math.abs(seconds) < 86400) return formatter.format(Math.round(seconds / 3600), "hour");
  return formatter.format(Math.round(seconds / 86400), "day");
}
