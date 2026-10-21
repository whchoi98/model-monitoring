"use client";

import { useEffect, useRef } from "react";
import { useT } from "@/lib/i18n-context";
import ModelName from "./ModelName";

/** The footer and keyboard focus viewport share this dock's measured clearance. */
export default function ModelComparisonDock({ names, onCompare, onClear }: {
  names: string[];
  onCompare: () => void;
  onClear: () => void;
}) {
  const m = useT().monitoring;
  const dock = useRef<HTMLElement>(null);

  useEffect(() => {
    const element = dock.current;
    if (!element) return;
    const root = document.documentElement;
    const measure = () => {
      const measured = element.getBoundingClientRect().height;
      root.style.setProperty("--comparison-dock-clearance", `calc(${measured}px + 2rem + env(safe-area-inset-bottom))`);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--comparison-dock-clearance");
    };
  }, []);

  return (
      <section ref={dock} aria-label={m.comparisonDock}
        className="fixed bottom-[calc(1rem_+_env(safe-area-inset-bottom))] left-4 right-20 z-30 mx-auto flex max-w-4xl flex-col gap-2 rounded-xl border border-blue-500/50 bg-gray-900 p-3 shadow-2xl sm:bottom-[calc(1.5rem_+_env(safe-area-inset-bottom))] sm:left-6 sm:right-28 sm:flex-row sm:items-center sm:gap-4">
        <details className="group min-w-0 flex-1">
          <summary className="cursor-pointer list-none rounded-md [&::-webkit-details-marker]:hidden">
            <span className="flex items-center gap-2 text-xs font-semibold text-blue-300">
              <span role="status">{m.selection(names.length)}</span>
              <span aria-hidden="true" className="text-gray-500 transition-transform group-open:rotate-180">⌃</span>
            </span>
            <span className="mt-1 block truncate text-xs text-gray-300">{names[0]}</span>
            {names.length > 1 && <span className="text-[11px] text-gray-500">{m.moreSelected(names.length - 1)}</span>}
          </summary>
          <div className="absolute bottom-[calc(100%_+_0.5rem)] left-0 right-0 max-h-[min(16rem,40dvh)] overflow-auto rounded-xl border border-gray-700 bg-gray-900 p-4 shadow-xl">
            <p className="mb-3 text-xs font-semibold text-gray-300">{m.selectionNames}</p>
            <ul className="space-y-2">
              {names.map((name) => <li key={name} className="text-xs leading-relaxed text-gray-300"><ModelName name={name} /></li>)}
            </ul>
          </div>
        </details>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button type="button" className="ui-button-primary flex-1 sm:flex-none"
            aria-label={m.jumpToTrends} aria-controls="performance-trends" onClick={onCompare}>
            {m.compareShort} <span aria-hidden="true">↑</span>
          </button>
          <button type="button" className="ui-button flex-1 sm:flex-none" onClick={onClear}>{m.clearSelection}</button>
        </div>
      </section>
  );
}
