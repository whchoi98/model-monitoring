"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useLang } from "@/lib/i18n-context";
import ChatPanel from "./ChatPanel";
import { trapDialogFocus } from "@/lib/dialogFocus";

interface ChatModalProps {
  open: boolean;
  onClose: () => void;
}
type Position = { x: number; y: number };

export default function ChatModal({ open, onClose }: ChatModalProps) {
  const { lang } = useLang();
  const dialog = useRef<HTMLDialogElement>(null);
  const [pos, setPos] = useState<Position | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);

  const clamp = (position: Position): Position => {
    const bounds = dialog.current?.getBoundingClientRect();
    return {
      x: Math.max(8, Math.min(window.innerWidth - (bounds?.width ?? 504) - 8, position.x)),
      y: Math.max(8, Math.min(window.innerHeight - (bounds?.height ?? 640) - 8, position.y)),
    };
  };

  useEffect(() => {
    if (!open || !dialog.current) return;
    const element = dialog.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    element.querySelector<HTMLTextAreaElement>("textarea")?.focus({ preventScroll: true });
    setPos(previous => previous ? clamp(previous) : null);
    const resize = () => setPos(previous => previous ? clamp(previous) : null);
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      drag.current = null;
      element.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open]);

  if (!open) return null;

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
    const bounds = dialog.current?.getBoundingClientRect();
    if (!bounds) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, left: bounds.left, top: bounds.top };
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setPos(clamp({
      x: drag.current.left + event.clientX - drag.current.x,
      y: drag.current.top + event.clientY - drag.current.y,
    }));
  };

  return (
    <dialog ref={dialog} tabIndex={-1} className="chat-dialog" onKeyDown={trapDialogFocus}
      aria-label={lang === "en" ? "AI assistant" : "AI 어시스턴트"}
      style={pos ? { left: pos.x, top: pos.y, right: "auto", bottom: "auto" } : undefined}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}>
      <div className="chat-drag-handle" onPointerDown={startDrag} onPointerMove={move}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <span><span aria-hidden="true">⠿ </span>{lang === "en" ? "Drag to move" : "드래그해서 이동"}</span>
        {pos && <button type="button" className="min-h-8 rounded px-2 hover:text-gray-100"
          onClick={() => setPos(null)}>{lang === "en" ? "Reset position" : "위치 초기화"}</button>}
      </div>
      <div className="min-h-0 flex-1"><ChatPanel variant="modal" onClose={onClose} /></div>
    </dialog>
  );
}
