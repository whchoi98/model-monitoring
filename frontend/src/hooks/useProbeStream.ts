"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { ProbeConfig, ProbeResult } from "@/lib/types";
import { runProbe } from "@/lib/api";
import { useT } from "@/lib/i18n-context";

interface ProbeStreamState {
  tokens: Map<string, string>;
  ttfts: Map<string, number>;
  results: ProbeResult[];
  isRunning: boolean;
  progress: { completed: number; total: number };
  error: string | null;
  runId: number | null;
}

export function useProbeStream() {
  const t = useT();
  const [state, setState] = useState<ProbeStreamState>({
    tokens: new Map(),
    ttfts: new Map(),
    results: [],
    isRunning: false,
    progress: { completed: 0, total: 0 },
    error: null,
    runId: null,
  });

  const abortControllerRef = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const tokensRef = useRef<Map<string, string>>(new Map());
  const ttftsRef = useRef<Map<string, number>>(new Map());
  const resultsRef = useRef<ProbeResult[]>([]);
  useEffect(() => () => {
    generation.current += 1;
    abortControllerRef.current?.abort();
  }, []);

  const run = useCallback((config: ProbeConfig) => {
    abortControllerRef.current?.abort();
    const currentGeneration = ++generation.current;
    const active = () => generation.current === currentGeneration;
    // Reset state
    tokensRef.current = new Map();
    ttftsRef.current = new Map();
    resultsRef.current = [];

    setState({
      tokens: new Map(),
      ttfts: new Map(),
      results: [],
      isRunning: true,
      progress: { completed: 0, total: config.model_ids.length * config.repeat_count },
      error: null,
      runId: null,
    });

    const controller = runProbe(config, {
      onToken: (data) => {
        if (!active()) return;
        const key = `${data.model_id}:${data.iteration}`;
        const current = tokensRef.current.get(key) || "";
        tokensRef.current.set(key, current + data.token);
        setState((prev) => ({
          ...prev,
          tokens: new Map(tokensRef.current),
        }));
      },

      onTTFT: (data) => {
        if (!active()) return;
        const key = `${data.model_id}:${data.iteration}`;
        ttftsRef.current.set(key, data.ttft_ms);
        setState((prev) => ({
          ...prev,
          ttfts: new Map(ttftsRef.current),
        }));
      },

      onResult: (data) => {
        if (!active()) return;
        resultsRef.current = [...resultsRef.current, data];
        setState((prev) => ({
          ...prev,
          results: resultsRef.current,
          progress: {
            ...prev.progress,
            completed: resultsRef.current.length,
          },
        }));
      },

      onComplete: (data) => {
        if (!active()) return;
        setState((prev) => ({
          ...prev,
          isRunning: false,
          runId: data.run_id,
          progress: { completed: data.total, total: data.total },
        }));
      },

      onError: (error) => {
        if (!active()) return;
        setState((prev) => ({
          ...prev,
          isRunning: false,
          error: error.name === "StreamInterruptedError" ? t.common.streamInterrupted : error.message,
        }));
      },
    });

    abortControllerRef.current = controller;
  }, [t]);

  const stop = useCallback(() => {
    if (abortControllerRef.current) {
      generation.current += 1;
      abortControllerRef.current.abort();
      setState((prev) => ({ ...prev, isRunning: false }));
    }
  }, []);

  return {
    ...state,
    run,
    stop,
  };
}
