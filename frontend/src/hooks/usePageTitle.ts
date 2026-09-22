"use client";

import { useEffect } from "react";

/** Streamed fallback metadata must not overwrite the active, localized view title. */
export function usePageTitle(title: string) {
  useEffect(() => {
    const update = () => {
      if (document.title !== title) document.title = title;
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.head, { childList: true, characterData: true, subtree: true });
    return () => observer.disconnect();
  }, [title]);
}
