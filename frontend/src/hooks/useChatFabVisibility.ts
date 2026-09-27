"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  initialFabState, isFabVisible, isHorizontalScroll, nextFabState,
  type FabEvent, type FabState, type WindowMetrics,
} from "@/lib/fabVisibility";

function windowMetrics(): WindowMetrics {
  const root = document.scrollingElement ?? document.documentElement;
  return { scrollY: window.scrollY, innerHeight: window.innerHeight, scrollHeight: root.scrollHeight };
}

/**
 * Whether the floating chat button shows (rule: `lib/fabVisibility.ts`). One passive capture listener for `scroll` on
 * the document: an event aimed at the document is the window scrolling, an event aimed at an element whose scrollLeft
 * changed is a horizontal scroll (the price tables). Hidden, the button stays in the DOM and in the tab order; spread
 * `onFocus` / `onBlur` on it so focus always shows it. The state lives in a ref and re-renders only when `hidden` flips.
 */
export function useChatFabVisibility(modalOpen: boolean) {
  const stateRef = useRef<FabState | null>(null);
  const [hidden, setHidden] = useState(false);
  const [focused, setFocused] = useState(false);

  const apply = useCallback((event: FabEvent) => {
    const next = nextFabState(stateRef.current ?? initialFabState(window.scrollY), event);
    stateRef.current = next;
    setHidden(next.hidden);
  }, []);

  useEffect(() => {
    stateRef.current = initialFabState(window.scrollY);
    const lefts = new WeakMap<Element, number>();
    const onScroll = (event: Event) => {
      const target = event.target;
      if (target instanceof Element) {
        const left = target.scrollLeft;
        const previous = lefts.get(target);
        lefts.set(target, left);
        if (isHorizontalScroll(previous, left)) apply({ type: "horizontal", ...windowMetrics() });
        return;
      }
      apply({ type: "window", ...windowMetrics() });
    };
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => document.removeEventListener("scroll", onScroll, { capture: true });
  }, [apply]);

  // Opening the chat window shows the button (it stays while open), and so does closing it.
  useEffect(() => {
    apply({ type: "show" });
  }, [apply, modalOpen]);

  const onFocus = useCallback(() => {
    setFocused(true);
    apply({ type: "show" });
  }, [apply]);
  const onBlur = useCallback(() => setFocused(false), []);

  return { visible: isFabVisible({ hidden }, { focused, modalOpen }), onFocus, onBlur };
}
