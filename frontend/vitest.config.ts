import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// 컴포넌트에서 export한 순수 헬퍼도 검사한다. 테스트의 JSX 런타임과 @/ 경로 해석을
// 명시해 Next.js 빌드 설정과 같은 방식으로 TSX를 읽고, 브라우저 테스트는 별도로 실행한다.
export default defineConfig({
  test: { include: ["src/**/*.test.{ts,tsx}"] },
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
