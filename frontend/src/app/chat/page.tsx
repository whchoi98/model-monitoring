"use client";

// /chat — Firefox/Safari popup window가 여는 진입점.
// 동일 origin이라 localStorage 인증 토큰 공유됨.
import ChatPanel from "@/components/chat/ChatPanel";

export default function ChatPage() {
  return (
    <main className="h-screen w-screen overflow-hidden bg-gray-950">
      <ChatPanel variant="popup" />
    </main>
  );
}
