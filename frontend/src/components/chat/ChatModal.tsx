"use client";

import { useEffect } from "react";
import ChatPanel from "./ChatPanel";

interface ChatModalProps {
  open: boolean;
  onClose: () => void;
}

// Chrome 계열 fallback — iframe 대신 ChatPanel을 직접 임베드한 modal.
// (iframe modal은 별도 page route 필요 — 우리는 같은 SPA에서 panel 재사용으로 단순화)
export default function ChatModal({ open, onClose }: ChatModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-end sm:justify-end p-0 sm:p-6">
      <button
        type="button"
        aria-label="overlay"
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
      />
      <div className="relative w-full sm:w-[420px] h-[80vh] sm:h-[640px] bg-gray-900 rounded-t-2xl sm:rounded-2xl border border-gray-800 shadow-2xl overflow-hidden">
        <ChatPanel variant="modal" onClose={onClose} />
      </div>
    </div>
  );
}
