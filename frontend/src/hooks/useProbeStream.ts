"use client";

import { useState, useCallback, useRef } from "react";
import { ProbeConfig, ProbeResult } from "@/lib/types";
import { runProbe } from "@/lib/api";

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
  const tokensRef = useRef<Map<string, string>>(new Map());
  const ttftsRef = useRef<Map<string, number>>(new Map());
  const resultsRef = useRef<ProbeResult[]>([]);

  const run = useCallback((config: ProbeConfig) => {
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
        const key = `${data.model_id}:${data.iteration}`;
        const current = tokensRef.current.get(key) || "";
        tokensRef.current.set(key, current + data.token);
        setState((prev) => ({
          ...prev,
          tokens: new Map(tokensRef.current),
        }));
      },

      onTTFT: (data) => {
        const key = `${data.model_id}:${data.iteration}`;
        ttftsRef.current.set(key, data.ttft_ms);
        setState((prev) => ({
          ...prev,
          ttfts: new Map(ttftsRef.current),
        }));
      },

      onResult: (data) => {
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
        setState((prev) => ({
          ...prev,
          isRunning: false,
          runId: data.run_id,
          progress: { completed: data.total, total: data.total },
        }));
      },

      onError: (error) => {
        setState((prev) => ({
          ...prev,
          isRunning: false,
          error: error.message,
        }));
      },
    });

    abortControllerRef.current = controller;
  }, []);

  const stop = useCallback(() => {
    if (abortControllerRef.current) {
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
