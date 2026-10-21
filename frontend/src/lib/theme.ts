"use client";

import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
export const DEFAULT_THEME: Theme = "light";
const STORAGE_KEY = "theme";
const EVENT = "themechange";
let sessionSelection: Theme | null = null;
const COLORS: Record<Theme, string> = { light: "#f5f7fb", dark: "#101827" };

export function getTheme(): Theme {
  if (typeof document === "undefined") return DEFAULT_THEME;
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("light", theme === "light");
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", COLORS[theme]);
}

export function setTheme(theme: Theme): void {
  sessionSelection = theme;
  applyTheme(theme);
  try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* Session-only switching still works. */ }
  window.dispatchEvent(new CustomEvent(EVENT));
}

function subscribe(callback: () => void): () => void {
  const storage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    sessionSelection = event.newValue === "dark" ? "dark" : DEFAULT_THEME;
    applyTheme(sessionSelection);
    callback();
  };
  window.addEventListener(EVENT, callback);
  window.addEventListener("storage", storage);
  // A different tab may change storage between the bootstrap script and hydration.
  // Keep a session choice when storage writes are unavailable.
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    const selected = sessionSelection ?? (stored === "dark" ? "dark" : DEFAULT_THEME);
    if (getTheme() !== selected) { applyTheme(selected); callback(); }
  } catch { /* Keep the currently rendered theme when storage is unavailable. */ }
  return () => {
    window.removeEventListener(EVENT, callback);
    window.removeEventListener("storage", storage);
  };
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, () => DEFAULT_THEME);
}
