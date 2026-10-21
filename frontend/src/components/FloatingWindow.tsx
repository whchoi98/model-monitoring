"use client";

import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { trapDialogFocus } from "@/lib/dialogFocus";
import { useLang } from "@/lib/i18n-context";

type Position = { x: number; y: number };

/** A movable reading window with native modality and a reversible full-screen view. */
export default function FloatingWindow({
  open, onClose, title, children, className = "", initialFocus, closeLabel,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
  initialFocus?: string;
  closeLabel?: string;
}) {
  const { lang } = useLang();
  const dialog = useRef<HTMLDialogElement>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [maximized, setMaximized] = useState(false);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);

  const clamp = (point: Position): Position => {
    const bounds = dialog.current?.getBoundingClientRect();
    return {
      x: Math.max(8, Math.min(window.innerWidth - (bounds?.width ?? 880) - 8, point.x)),
      y: Math.max(8, Math.min(window.innerHeight - (bounds?.height ?? 720) - 8, point.y)),
    };
  };

  useEffect(() => {
    if (!open || !dialog.current) return;
    const element = dialog.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    const target = initialFocus ? element.querySelector<HTMLElement>(initialFocus) : element;
    target?.focus({ preventScroll: true });
    const resize = () => setPosition(previous => previous ? clamp(previous) : null);
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      drag.current = null;
      element.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open, initialFocus]);

  useEffect(() => {
    if (!maximized) setPosition(previous => previous ? clamp(previous) : null);
  }, [maximized]);

  if (!open) return null;

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (maximized || event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
    const bounds = dialog.current?.getBoundingClientRect();
    if (!bounds) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, left: bounds.left, top: bounds.top };
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setPosition(clamp({
      x: drag.current.left + event.clientX - drag.current.x,
      y: drag.current.top + event.clientY - drag.current.y,
    }));
  };
  const stopDrag = () => { drag.current = null; };

  return (
    <dialog ref={dialog} tabIndex={-1} aria-label={title}
      className={`floating-window ${className}`} data-maximized={maximized}
      style={!maximized && position ? { left: position.x, top: position.y, right: "auto", bottom: "auto", margin: 0 } : undefined}
      onKeyDown={event => {
        trapDialogFocus(event);
        if (event.key === "Escape" && !event.nativeEvent.isComposing) {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}>
      <div className="floating-window-bar" data-window-drag onPointerDown={startDrag} onPointerMove={move}
        onPointerUp={stopDrag} onPointerCancel={stopDrag} onLostPointerCapture={stopDrag}>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-gray-100">{title}</p>
          <p className="mt-0.5 text-[11px] text-gray-500">
            {maximized ? (lang === "en" ? "Full-screen view" : "전체 화면으로 보는 중") : (lang === "en" ? "Drag this bar to move" : "상단을 드래그해 이동하세요")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {position && !maximized && (
            <button type="button" className="window-control" onClick={() => setPosition(null)}
              aria-label={lang === "en" ? "Reset position" : "위치 초기화"} title={lang === "en" ? "Reset position" : "위치 초기화"}>
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 10a8 8 0 1 1 1 7M4 4v6h6" /></svg>
            </button>
          )}
          <button type="button" className="window-control" onClick={() => { stopDrag(); setMaximized(value => !value); }}
            aria-label={lang === "en" ? (maximized ? "Restore size" : "Full screen") : (maximized ? "원래 크기로" : "전체 화면")}
            title={lang === "en" ? (maximized ? "Restore size" : "Full screen") : (maximized ? "원래 크기로" : "전체 화면")}>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              {maximized ? <><path d="M9 9V4h11v11h-5" /><rect x="4" y="9" width="11" height="11" rx="1" /></> : <path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5" />}
            </svg>
          </button>
          <button type="button" className="window-control" onClick={onClose}
            aria-label={closeLabel ?? (lang === "en" ? "Close window" : "창 닫기")}
            title={closeLabel ?? (lang === "en" ? "Close window" : "창 닫기")}>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m6 6 12 12M6 18 18 6" /></svg>
          </button>
        </div>
      </div>
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </dialog>
  );
}
