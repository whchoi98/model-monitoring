"use client";

import { createContext, useContext, type ReactNode } from "react";
import { usePresence } from "@/hooks/usePresence";
import type { PresenceState } from "./presence";

const PresenceContext = createContext<PresenceState>({ snapshot: null, status: "loading" });

export function PresenceProvider({ children }: { children: ReactNode }) {
  const state = usePresence();
  return <PresenceContext.Provider value={state}>{children}</PresenceContext.Provider>;
}

export function useVisitorCounts() {
  return useContext(PresenceContext);
}
