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
};

export default nextConfig;
