import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Amazon Bedrock LLM Monitor",
  description: "AWS Bedrock LLM model real-time performance monitoring dashboard",
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
      </body>
    </html>
  );
}
