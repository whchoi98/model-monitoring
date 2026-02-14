import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Bedrock LLM 모니터",
  description: "AWS Bedrock LLM 모델 실시간 성능 모니터링 대시보드",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="dark">
      <body className={inter.className}>
        <div className="min-h-screen bg-gray-950">{children}</div>
      </body>
    </html>
  );
}
