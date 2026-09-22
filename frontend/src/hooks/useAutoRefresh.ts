"use client";

import { useState, useEffect, useRef, useCallback } from "react";

export function useAutoRefresh(callback: () => void | Promise<unknown>, intervalMs = 30000) {
  const [enabled, setEnabled] = useState(true);
  const [countdown, setCountdown] = useState(Math.floor(intervalMs / 1000));
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const deadlineRef = useRef(Date.now() + intervalMs);
  const inFlightRef = useRef(false);

  const reset = useCallback(() => {
    deadlineRef.current = Date.now() + intervalMs;
    setCountdown(Math.floor(intervalMs / 1000));
  }, [intervalMs]);

  useEffect(() => {
    if (!enabled) return;
    reset();

    const refresh = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try { await callbackRef.current(); }
      catch { /* Each consumer owns its visible error state. */ }
      finally { inFlightRef.current = false; }
    };
    const tick = () => {
      if (document.visibilityState === "hidden") return;
      const remaining = Math.max(0, Math.ceil((deadlineRef.current - Date.now()) / 1000));
      setCountdown(remaining);
      if (remaining === 0) {
        reset();
        void refresh();
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        reset();
        void refresh();
      }
    };
    const tickId = setInterval(tick, 1000);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearInterval(tickId);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, intervalMs, reset]);

  return { countdown, enabled, setEnabled, reset };
}
