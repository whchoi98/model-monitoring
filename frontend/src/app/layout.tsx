import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import RumProvider from "@/components/RumProvider";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Amazon Bedrock LLM Monitor",
  description: "AWS Bedrock LLM model real-time performance monitoring dashboard",
  applicationName: "LLM Monitor",
  // iPhone/iPad 홈 화면 설치(PWA, v2.21.0) — standalone 전체화면 + 반투명 상태바.
  // 상태바가 콘텐츠 위에 겹치므로 globals.css의 safe-area 패딩과 세트로 동작한다.
  appleWebApp: {
    capable: true,
    title: "LLM Monitor",
    statusBarStyle: "black-translucent",
  },
  formatDetection: { telephone: false }, // 지표 숫자를 전화번호로 오인해 링크화하는 것 방지
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // 노치/Dynamic Island 영역까지 배경을 채우기 위해 필수 — env(safe-area-inset-*)의 전제.
  viewportFit: "cover",
  themeColor: "#030712", // gray-950 — 다크 기본 테마 (화이트 토글은 수동이라 정적 값 유지)
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="dark">
      <head>
        {/* 테마 FOUC 방지 — 하이드레이션 전에 localStorage의 화이트 테마 선택을 복원.
            React 렌더 밖에서 실행되어야 하므로 인라인 스크립트가 표준 패턴 (v2.8.0). */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{if(localStorage.getItem('theme')==='light')document.documentElement.classList.add('light')}catch(e){}",
          }}
        />
      </head>
      <body className={inter.className}>
        <div className="min-h-screen bg-gray-950">{children}</div>
        <RumProvider />
      </body>
    </html>
  );
}
