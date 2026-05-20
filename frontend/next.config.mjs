/** @type {import('next').NextConfig} */
const nextConfig = {
  // ECS 컨테이너에서 단일 서버로 실행하기 위한 standalone 출력.
  output: "standalone",

  // v2: backend 컨테이너의 실제 호스트로 향하도록 환경변수로 주입한다.
  // 미설정 시 로컬 개발 기본값 localhost:8000.
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },

  // 영구 해결: HTML 응답을 절대 캐시하지 않게 강제.
  // CloudFront 기본 동작이 SSR HTML도 s-maxage=31536000(1년)으로 받아 edge에 stale HTML이
  // 남는 문제 회피. 새 deploy 시 옛 buildId chunk URL이 박힌 옛 HTML을 캐시해
  // chunk 404 + 빈 화면이 반복되는 root cause.
  // _next/static (hash-based filename)은 immutable로 강하게 캐시 유지.
  async headers() {
    return [
      {
        source: "/((?!_next/static|api|favicon).*)",
        headers: [
          { key: "Cache-Control", value: "no-store, no-cache, must-revalidate, max-age=0" },
        ],
      },
      {
        source: "/_next/static/:path*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
    ];
  },
};

export default nextConfig;
