// PWA Web App Manifest (v2.21.0) — Next.js가 /manifest.webmanifest로 서빙 +
// <link rel="manifest"> 자동 주입. iPhone/iPad는 Safari 공유 → "홈 화면에 추가"로 설치되어
// 전체화면 standalone 앱으로 동작한다 (iOS 메타태그는 layout.tsx metadata.appleWebApp).
import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Amazon Bedrock LLM Monitor",
    short_name: "LLM Monitor",
    description:
      "Bedrock + Anthropic CP + OpenAI LLM 채널 실시간 성능·비용·신뢰성 모니터링",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "any", // iPad 가로/세로 모두 지원
    background_color: "#0b1220", // 스플래시/전환 배경 — 앱 아이콘·다크 테마와 동일 계열
    theme_color: "#030712", // gray-950 (다크 기본 테마)
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      // maskable — Android 적응형 아이콘용 안전영역(중앙 80%) 확보 변형
      { src: "/icons/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
