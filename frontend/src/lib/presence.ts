export interface PresenceSnapshot {
  active_visitors: number;
  total_visitors: number;
  initial_total: number;
  window_seconds: number;
  as_of: string;
  counting_since: string | null;
}

export interface PresenceState {
  snapshot: PresenceSnapshot | null;
  status: "loading" | "live" | "unavailable" | "stale";
}

const validCount = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const validTime = (value: unknown): value is string => typeof value === "string"
  && /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

export function parsePresenceSnapshot(value: unknown): PresenceSnapshot {
  const data = value as Partial<PresenceSnapshot> | null;
  if (!data || !validCount(data.active_visitors) || !validCount(data.total_visitors) || !validCount(data.initial_total)
    || data.total_visitors < data.initial_total || data.active_visitors > data.total_visitors - data.initial_total
    || data.window_seconds !== 90 || !validTime(data.as_of)
    || (data.counting_since !== null && !validTime(data.counting_since))) {
    throw new Error("Invalid visitor counts");
  }
  return data as PresenceSnapshot;
}

export function presenceIsStale(snapshot: PresenceSnapshot, now = Date.now()): boolean {
  return Math.abs(now - Date.parse(snapshot.as_of)) > snapshot.window_seconds * 1000;
}
