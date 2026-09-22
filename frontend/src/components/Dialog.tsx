"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { useLang } from "@/lib/i18n-context";

/** Native modal semantics provide focus containment, Escape and an inert background. */
export default function Dialog({ title, onClose, children, className = "max-w-2xl" }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const { lang } = useLang();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog ref={ref} aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}
      className={`m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] overflow-y-auto rounded-xl border border-gray-700 bg-gray-900 p-0 text-gray-100 shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm ${className}`}
    >
      <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-gray-800 bg-gray-900 px-4 py-3 sm:px-6">
        <h2 id={titleId} className="self-center break-words text-base font-semibold">{title}</h2>
        <button type="button" onClick={onClose} aria-label={lang === "en" ? "Close dialog" : "닫기"} className="ui-button h-9 w-9 shrink-0 p-0">
          <span aria-hidden="true" className="text-xl leading-none">×</span>
        </button>
      </div>
      <div className="space-y-4 p-4 sm:p-6">{children}</div>
    </dialog>
  );
}
