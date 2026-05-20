import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Cache-Control 응답 헤더를 모든 HTML route에 `no-store`로 강제.
//
// 이유: Next.js 14 standalone이 "use client" 페이지에도 자동으로
//   cache-control: s-maxage=31536000, stale-while-revalidate
// 를 박아 CloudFront/브라우저/회사 프록시가 옛 HTML을 1년 캐시.
// 매 deploy 시 새 buildId의 chunk URL이 박힌 새 HTML이 즉시 전파되어야
// chunk 404 + 빈 화면 문제가 재발하지 않음.
//
// `_next/static/*` (hash-based filename)와 `/api/*`는 matcher에서 제외해
// 정적 자산 immutable 캐시와 API SSE 스트리밍이 영향받지 않게 한다.
export function middleware(request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set(
    "Cache-Control",
    "no-store, no-cache, must-revalidate, max-age=0",
  );
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|api|favicon.ico).*)"],
};
