"use client";

// /chat — Firefox/Safari popup window가 여는 진입점.
// 동일 origin이라 localStorage 인증 토큰 공유됨.
import { usePageTitle } from "@/hooks/usePageTitle";
import { useLang } from "@/lib/i18n-context";
import ChatPanel from "@/components/chat/ChatPanel";

export default function ChatPage() {
  const { lang } = useLang();
  usePageTitle(`${lang === "en" ? "Chat" : "챗봇"} | LLM Monitor`);

  return (
    <main className="h-dvh w-full overflow-hidden bg-gray-950">
      <ChatPanel variant="popup" />
    </main>
  );
}
