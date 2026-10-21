import { describe, expect, it } from "vitest";
import { parsePresenceSnapshot, presenceIsStale } from "./presence";

const snapshot = {
  active_visitors: 2, total_visitors: 10008, initial_total: 10000,
  as_of: "2026-10-21T08:00:00+00:00", counting_since: "2026-10-21T07:00:00+00:00",
  window_seconds: 90,
};

describe("presence snapshots", () => {
  it("keeps the server total and opening balance without adding another client offset", () => {
    expect(parsePresenceSnapshot(snapshot)).toEqual(snapshot);
    expect(parsePresenceSnapshot({ ...snapshot, active_visitors: 0, total_visitors: 10000, counting_since: null }).total_visitors).toBe(10000);
  });

  it.each([
    null, [], {}, { ...snapshot, active_visitors: -1 },
    { ...snapshot, active_visitors: 1.5 }, { ...snapshot, total_visitors: "10008" },
    { ...snapshot, total_visitors: 9999 }, { ...snapshot, active_visitors: 9 },
    { ...snapshot, total_visitors: Number.MAX_SAFE_INTEGER + 1 },
    { ...snapshot, as_of: "yesterday" }, { ...snapshot, counting_since: "invalid" },
    { ...snapshot, window_seconds: 0 },
  ])("rejects invalid or inconsistent server counts: %j", (value) => {
    expect(() => parsePresenceSnapshot(value)).toThrow();
  });

  it("stops describing old or future-dated counts as current", () => {
    const now = Date.parse(snapshot.as_of);
    expect(presenceIsStale(snapshot, now + 89000)).toBe(false);
    expect(presenceIsStale(snapshot, now + 91000)).toBe(true);
    expect(presenceIsStale(snapshot, now - 91000)).toBe(true);
  });
});
