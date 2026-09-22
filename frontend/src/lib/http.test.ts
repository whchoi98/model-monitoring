import { afterEach, describe, expect, test, vi } from "vitest";
import { ApiError, fetchJson } from "./http";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("fetchJson", () => {
  test("keeps structured HTTP status for recoverable error messages", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "A cycle is already running" }), { status: 409 })));
    await expect(fetchJson("/api/auto-probe/trigger")).rejects.toMatchObject({
      status: 409, message: "A cycle is already running",
    });
  });

  test("handles a non-JSON error response without leaking an HTML error page into the UI", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Proxy failure</html>", { status: 502 })));
    await expect(fetchJson("/api/auto-probe/latest")).rejects.toMatchObject({ status: 502 });
  });

  test("cancels a hanging request at the deadline instead of leaving a permanent spinner", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    const pending = fetchJson("/api/auto-probe/latest", {}, 1000);
    const rejection = expect(pending).rejects.toMatchObject({ name: "TimeoutError" });
    await vi.advanceTimersByTimeAsync(1000);
    await rejection;
  });

  test("preserves caller cancellation so obsolete filters do not create an error banner", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    const pending = fetchJson("/api/auto-probe/trend", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  test("rejects invalid successful JSON instead of treating it as an empty result", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("bad JSON", { status: 200 })));
    await expect(fetchJson("/api/auto-probe/latest")).rejects.toBeInstanceOf(ApiError);
  });
});
