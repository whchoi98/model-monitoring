"use client";

import { useState, useEffect, useRef, useCallback } from "react";

export function useAutoRefresh(callback: () => void, intervalMs = 30000) {
  const [enabled, setEnabled] = useState(true);
  const [countdown, setCountdown] = useState(Math.floor(intervalMs / 1000));
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const reset = useCallback(() => {
    setCountdown(Math.floor(intervalMs / 1000));
  }, [intervalMs]);

  useEffect(() => {
    if (!enabled) return;

    // Countdown every second
    const tickId = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          callbackRef.current();
          return Math.floor(intervalMs / 1000);
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(tickId);
  }, [enabled, intervalMs]);

  return { countdown, enabled, setEnabled, reset };
}
