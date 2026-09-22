"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface ResourceState<T> {
  key: string;
  data: T | null;
  error: Error | null;
  pending: boolean;
  updatedAt: number | null;
}

/**
 * Each result belongs to its query. Background refresh keeps that query's last
 * successful data; a changed filter never borrows data from the previous query.
 */
export function useAsyncResource<T>(key: string, loader: (signal: AbortSignal) => Promise<T>) {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const controllerRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<ResourceState<T>>({
    key, data: null, error: null, pending: true, updatedAt: null,
  });

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((previous) => ({
      key,
      data: previous.key === key ? previous.data : null,
      updatedAt: previous.key === key ? previous.updatedAt : null,
      error: null,
      pending: true,
    }));
    try {
      const data = await loaderRef.current(controller.signal);
      if (controllerRef.current !== controller || controller.signal.aborted) return;
      setState({ key, data, error: null, pending: false, updatedAt: Date.now() });
    } catch (error) {
      if (controllerRef.current !== controller || controller.signal.aborted) return;
      setState((previous) => ({
        ...previous, key, pending: false,
        error: error instanceof Error ? error : new Error(String(error)),
      }));
    }
  }, [key]);

  useEffect(() => {
    void refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  const current = state.key === key;
  const data = current ? state.data : null;
  const pending = !current || state.pending;
  return {
    data,
    error: current ? state.error : null,
    updatedAt: current ? state.updatedAt : null,
    loading: pending && data === null,
    refreshing: pending,
    refresh,
  };
}
