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
      <body className={inter.className}>
        <div className="min-h-screen bg-gray-950">{children}</div>
      </body>
    </html>
  );
}
