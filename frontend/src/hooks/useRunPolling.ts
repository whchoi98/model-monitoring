"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const RUN_POLL_INTERVAL_MS = 15_000;
export const RUN_POLL_GRACE_MS = 5 * 60_000;

interface Options {
  /** The latest payload says a run is in progress. */
  running: boolean;
  /** The latest payload's run id (null while there is no run yet). */
  runId: number | null;
  refresh: () => Promise<unknown>;
  /** A refresh is in flight; a tick that finds one skips instead of overlapping it. */
  refreshing: boolean;
}

/**
 * Refresh a resource every 15 s while a run is in progress, and nothing otherwise.
 * `arm(runIdBeforeTrigger)` opens a 5 minute window after a trigger, because the backend commits its `running`
 * row from a thread and the first refresh can still say `running: false`. The window ends early once a payload
 * shows `running: true` (from then on `running` drives) or a run id other than the one before the trigger.
 */
export function useRunPolling({ running, runId, refresh, refreshing }: Options): (runIdBeforeTrigger: number | null) => void {
  const [baseRunId, setBaseRunId] = useState<number | null | undefined>(undefined); // undefined = no window open
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const refreshingRef = useRef(refreshing);
  refreshingRef.current = refreshing;
  const windowOpen = baseRunId !== undefined;

  const arm = useCallback((runIdBeforeTrigger: number | null) => setBaseRunId(runIdBeforeTrigger), []);

  useEffect(() => {
    if (windowOpen && (running || runId !== baseRunId)) setBaseRunId(undefined);
  }, [windowOpen, running, runId, baseRunId]);

  useEffect(() => {
    if (!windowOpen) return;
    const timer = setTimeout(() => setBaseRunId(undefined), RUN_POLL_GRACE_MS);
    return () => clearTimeout(timer);
  }, [windowOpen]);

  const active = running || windowOpen;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "hidden" || refreshingRef.current) return;
      void refreshRef.current();
    }, RUN_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [active]);

  return arm;
}
