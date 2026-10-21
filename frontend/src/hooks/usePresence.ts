"use client";

import { useEffect, useState } from "react";
import { parsePresenceSnapshot, presenceIsStale, type PresenceSnapshot, type PresenceState } from "@/lib/presence";

const INTERVAL_MS = 30_000;
const RESUME_GAP_MS = 5_000;

/** One root-owned poller; bootstrap is serialized across tabs sharing the visitor cookie. */
export function usePresence(): PresenceState {
  const [state, setState] = useState<PresenceState>({ snapshot: null, status: "loading" });
  useEffect(() => {
    let last: PresenceSnapshot | null = null;
    let failed = false;
    let disposed = false;
    let pageHidden = false;
    let ready = false;
    let request: AbortController | undefined;
    let timer: number | undefined;
    let lastAttempt = -Infinity;
    let retryAfter = -Infinity;
    let resumeNeeded = false;
    const locks = typeof navigator.locks?.request === "function" ? navigator.locks : undefined;
    const usable = () => !disposed && !pageHidden && !document.hidden && navigator.onLine !== false;
    let paused = !usable();

    function paint() {
      if (disposed) return;
      const stale = last && (failed || !usable() || presenceIsStale(last));
      setState({ snapshot: last, status: last ? stale ? "stale" : "live" : failed || !usable() ? "unavailable" : "loading" });
    }
    function clearTimer() {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
    }
    function schedule(at: number) {
      clearTimer();
      if (usable()) timer = window.setTimeout(() => { timer = undefined; void poll(); }, Math.max(0, at - Date.now()));
    }
    function send(method: "GET" | "POST", signal: AbortSignal, credentials: RequestCredentials = "same-origin") {
      return fetch("/api/presence", {
        method, signal, credentials, cache: "no-store",
        headers: method === "POST"
          ? { Accept: "application/json", "Content-Type": "application/json", "x-llm-monitor-client": "1" }
          : { Accept: "application/json" },
        ...(method === "POST" ? { body: "{}" } : {}),
      });
    }
    async function read(signal: AbortSignal, credentials: RequestCredentials) {
      const response = await send("GET", signal, credentials);
      if (!response.ok) throw new Error("Visitor counts unavailable");
      const snapshot = parsePresenceSnapshot(await response.json());
      signal.throwIfAborted();
      if (!usable()) return false;
      last = snapshot;
      failed = false;
      paint();
      return true;
    }
    async function poll() {
      if (request || !usable()) return;
      lastAttempt = Date.now();
      const controller = new AbortController();
      request = controller;
      const { signal } = controller;
      const deadline = window.setTimeout(() => controller.abort(new DOMException("Presence timeout", "TimeoutError")), 8000);
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          signal.throwIfAborted();
          if (!usable()) return;
          if (!locks) {
            // Read the real aggregate without racing shared cookie creation in older browsers.
            await read(signal, "omit");
            retryAfter = -Infinity;
            return;
          }
          const response = ready ? await send("POST", signal) : await locks.request(
            "llm-monitor-presence-bootstrap", { mode: "exclusive", signal }, async () => {
              signal.throwIfAborted();
              if (!usable() || !await read(signal, "same-origin")) return undefined;
              ready = true;
              return send("POST", signal);
            },
          );
          if (!response) return;
          if ((response.status === 401 || response.status === 403) && attempt === 0) {
            ready = false;
            continue;
          }
          if (!response.ok) throw new Error("Visitor heartbeat unavailable");
          const snapshot = parsePresenceSnapshot(await response.json());
          signal.throwIfAborted();
          if (!usable()) return;
          last = snapshot;
          failed = false;
          retryAfter = -Infinity;
          paint();
          return;
        }
      } catch {
        if (disposed) return;
        if (usable() && !(signal.aborted && signal.reason?.name === "AbortError")) {
          failed = true;
          retryAfter = Date.now() + INTERVAL_MS;
        }
        paint();
      } finally {
        window.clearTimeout(deadline);
        if (request === controller) request = undefined;
        if (usable()) schedule(Math.max(lastAttempt + (resumeNeeded ? RESUME_GAP_MS : INTERVAL_MS), retryAfter));
        resumeNeeded = false;
      }
    }
    function pause() {
      paused = true;
      if (last) failed = true;
      clearTimer();
      request?.abort(new DOMException("Presence paused", "AbortError"));
      paint();
    }
    function resume() {
      if (!usable()) { pause(); return; }
      const wasPaused = paused;
      paused = false;
      paint();
      if (!wasPaused) return;
      if (request) { resumeNeeded = true; return; }
      schedule(Math.max(lastAttempt + RESUME_GAP_MS, retryAfter));
    }
    const visibility = () => document.hidden ? pause() : resume();
    const pageHide = () => { pageHidden = true; pause(); };
    const pageShow = () => { pageHidden = false; resume(); };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("online", resume);
    window.addEventListener("offline", pause);
    window.addEventListener("pagehide", pageHide);
    window.addEventListener("pageshow", pageShow);
    paint();
    if (usable()) schedule(Date.now());
    return () => {
      disposed = true;
      clearTimer();
      request?.abort(new DOMException("Presence disposed", "AbortError"));
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("online", resume);
      window.removeEventListener("offline", pause);
      window.removeEventListener("pagehide", pageHide);
      window.removeEventListener("pageshow", pageShow);
    };
  }, []);
  return state;
}
