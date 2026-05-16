"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// LLM 응답 마크다운 렌더러 — 표/코드블럭 지원 (remark-gfm).
// 보안: react-markdown은 기본적으로 raw HTML을 비활성화 → XSS 안전.
export default function MessageMarkdown({ text }: { text: string }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 코드 블럭에 dark-friendly 배경.
          code({ className, children, ...props }) {
            const isBlock = /language-/.test(className ?? "");
            return isBlock ? (
              <code
                className="block bg-gray-950 border border-gray-800 rounded-md p-3 overflow-x-auto text-xs"
                {...props}
              >
                {children}
              </code>
            ) : (
              <code className="bg-gray-800 text-gray-200 px-1 py-0.5 rounded text-[0.85em]" {...props}>
                {children}
              </code>
            );
          },
          // 표는 가로 스크롤 가능하게 wrap.
          table({ children }) {
            return (
              <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">{children}</table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="border border-gray-700 bg-gray-900 px-2 py-1 text-left">{children}</th>
            );
          },
          td({ children }) {
            return <td className="border border-gray-800 px-2 py-1">{children}</td>;
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:underline"
              >
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
