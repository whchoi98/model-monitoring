import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Next.js용 tsconfig는 jsx: "preserve"(SWC가 변환)라서 vite가 .tsx를 그대로 읽으면 파싱이
// 깨진다 — 테스트 실행에서만 automatic runtime으로 변환하고 "@/" 별칭을 src로 해석한다.
// 순수 로직(src/lib/*.test.ts)만 있던 시절에는 설정 없이 동작했으나, 컴포넌트에서 export한
// 순수 헬퍼(GptOnAwsPanel의 regionOf/familyOf, v2.25.1)를 테스트하려면 둘 다 필요하다.
export default defineConfig({
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
