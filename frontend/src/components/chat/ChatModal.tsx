"use client";

import { useLang } from "@/lib/i18n-context";
import FloatingWindow from "../FloatingWindow";
import ChatPanel from "./ChatPanel";

export default function ChatModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { lang } = useLang();
  return (
    <FloatingWindow open={open} onClose={onClose} className="chat-dialog" initialFocus="textarea"
      title={lang === "en" ? "AI assistant" : "AI 어시스턴트"} closeLabel={lang === "en" ? "Close chat" : "챗봇 닫기"}>
      <ChatPanel variant="modal" />
    </FloatingWindow>
  );
}
