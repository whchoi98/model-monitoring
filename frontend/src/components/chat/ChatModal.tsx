"use client";

import { useEffect, useRef, useState } from "react";
import ChatPanel from "./ChatPanel";

interface ChatModalProps {
  open: boolean;
  onClose: () => void;
}

// Draggable Chat Modal — 헤더 드래그로 위치 이동 가능.
// 처음 열 때는 우측 하단 정착 위치. 사용자가 드래그한 후 위치는 모달 닫혀도 유지.
export default function ChatModal({ open, onClose }: ChatModalProps) {
  // 화면 우측 하단 기본 위치. null이면 sm:items-end / sm:justify-end CSS 사용.
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const dragState = useRef<{ ox: number; oy: number; sx: number; sy: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragState.current) return;
      const { ox, oy, sx, sy } = dragState.current;
      const nx = ox + (e.clientX - sx);
      const ny = oy + (e.clientY - sy);
      // 뷰포트 경계 보호
      const maxX = window.innerWidth - 100;
      const maxY = window.innerHeight - 50;
      setPos({
        x: Math.max(0, Math.min(maxX, nx)),
        y: Math.max(0, Math.min(maxY, ny)),
      });
    };
    const onUp = () => {
      dragState.current = null;
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (!open) return null;

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    document.body.style.userSelect = "none";
    // 현재 modal 위치 계산 — pos가 null이면 우측 하단으로 가정
    const w = 504;
    const h = 640;
    const cx = pos?.x ?? window.innerWidth - w - 24;
    const cy = pos?.y ?? window.innerHeight - h - 24;
    dragState.current = { ox: cx, oy: cy, sx: e.clientX, sy: e.clientY };
  };

  // pos가 설정되면 자유 위치, null이면 기본 우측 하단 anchor.
  const containerStyle: React.CSSProperties = pos
    ? { position: "fixed", left: pos.x, top: pos.y, zIndex: 50 }
    : {};

  return (
    <>
      {/* overlay - 드래그 모드에서는 클릭으로 닫기 비활성 (실수 방지) */}
      <button
        type="button"
        aria-label="overlay"
        onClick={onClose}
        className="fixed inset-0 bg-black/50 z-40"
      />
      <div
        className={
          pos
            ? "w-[504px] h-[640px] bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl overflow-hidden flex flex-col"
            : "fixed bottom-6 right-6 z-50 w-[504px] h-[640px] bg-gray-900 rounded-2xl border border-gray-800 shadow-2xl overflow-hidden flex flex-col"
        }
        style={containerStyle}
      >
        {/* Drag handle - 헤더 전체에 mousedown 바인딩 */}
        <div
          onMouseDown={startDrag}
          className="cursor-move select-none bg-gray-950/70 border-b border-gray-800 px-3 py-1.5 text-[10px] text-gray-500 flex items-center justify-between"
          title="드래그해서 이동"
        >
          <span>⋮⋮  드래그해서 이동</span>
          {pos && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setPos(null);
              }}
              className="text-gray-500 hover:text-gray-300 underline text-[10px]"
            >
              위치 초기화
            </button>
          )}
        </div>
        <div className="flex-1 min-h-0">
          <ChatPanel variant="modal" onClose={onClose} />
        </div>
      </div>
    </>
  );
}
