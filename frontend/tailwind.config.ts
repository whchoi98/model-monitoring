import type { Config } from "tailwindcss";
import plugin from "tailwindcss/plugin";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // gray 스케일을 CSS 변수로 재매핑 (v2.8.0 테마 토글) — globals.css의 :root(다크) /
        // html.light(화이트) 팔레트를 따라간다. <alpha-value>로 bg-gray-900/50 같은
        // 투명도 변형도 그대로 동작. 기존 컴포넌트 클래스 무수정 전체 테마화의 핵심.
        gray: {
          100: "rgb(var(--tw-gray-100) / <alpha-value>)",
          200: "rgb(var(--tw-gray-200) / <alpha-value>)",
          300: "rgb(var(--tw-gray-300) / <alpha-value>)",
          400: "rgb(var(--tw-gray-400) / <alpha-value>)",
          500: "rgb(var(--tw-gray-500) / <alpha-value>)",
          600: "rgb(var(--tw-gray-600) / <alpha-value>)",
          700: "rgb(var(--tw-gray-700) / <alpha-value>)",
          800: "rgb(var(--tw-gray-800) / <alpha-value>)",
          900: "rgb(var(--tw-gray-900) / <alpha-value>)",
          950: "rgb(var(--tw-gray-950) / <alpha-value>)",
        },
        // 액센트 밝은 톤(200/300/400)만 변수화 — 라이트에서 진한 톤으로 교체 (v2.8.3).
        // 500+ 단계는 Tailwind 기본값 유지 (extend라 여기 없는 step은 원본 그대로).
        blue: {
          200: "rgb(var(--tw-blue-200) / <alpha-value>)",
          300: "rgb(var(--tw-blue-300) / <alpha-value>)",
          400: "rgb(var(--tw-blue-400) / <alpha-value>)",
        },
        emerald: {
          200: "rgb(var(--tw-emerald-200) / <alpha-value>)",
          300: "rgb(var(--tw-emerald-300) / <alpha-value>)",
          400: "rgb(var(--tw-emerald-400) / <alpha-value>)",
        },
        amber: {
          200: "rgb(var(--tw-amber-200) / <alpha-value>)",
          300: "rgb(var(--tw-amber-300) / <alpha-value>)",
          400: "rgb(var(--tw-amber-400) / <alpha-value>)",
        },
        rose: {
          200: "rgb(var(--tw-rose-200) / <alpha-value>)",
          300: "rgb(var(--tw-rose-300) / <alpha-value>)",
          400: "rgb(var(--tw-rose-400) / <alpha-value>)",
        },
        purple: {
          200: "rgb(var(--tw-purple-200) / <alpha-value>)",
          300: "rgb(var(--tw-purple-300) / <alpha-value>)",
          400: "rgb(var(--tw-purple-400) / <alpha-value>)",
        },
        orange: {
          200: "rgb(var(--tw-orange-200) / <alpha-value>)",
          300: "rgb(var(--tw-orange-300) / <alpha-value>)",
          400: "rgb(var(--tw-orange-400) / <alpha-value>)",
        },
        cyan: {
          200: "rgb(var(--tw-cyan-200) / <alpha-value>)",
          300: "rgb(var(--tw-cyan-300) / <alpha-value>)",
          400: "rgb(var(--tw-cyan-400) / <alpha-value>)",
        },
        indigo: {
          200: "rgb(var(--tw-indigo-200) / <alpha-value>)",
          300: "rgb(var(--tw-indigo-300) / <alpha-value>)",
          400: "rgb(var(--tw-indigo-400) / <alpha-value>)",
        },
        teal: {
          200: "rgb(var(--tw-teal-200) / <alpha-value>)",
          300: "rgb(var(--tw-teal-300) / <alpha-value>)",
          400: "rgb(var(--tw-teal-400) / <alpha-value>)",
        },
        green: {
          200: "rgb(var(--tw-green-200) / <alpha-value>)",
          300: "rgb(var(--tw-green-300) / <alpha-value>)",
          400: "rgb(var(--tw-green-400) / <alpha-value>)",
        },
        red: {
          200: "rgb(var(--tw-red-200) / <alpha-value>)",
          300: "rgb(var(--tw-red-300) / <alpha-value>)",
          400: "rgb(var(--tw-red-400) / <alpha-value>)",
        },
        yellow: {
          200: "rgb(var(--tw-yellow-200) / <alpha-value>)",
          300: "rgb(var(--tw-yellow-300) / <alpha-value>)",
          400: "rgb(var(--tw-yellow-400) / <alpha-value>)",
        },
        lime: {
          200: "rgb(var(--tw-lime-200) / <alpha-value>)",
          300: "rgb(var(--tw-lime-300) / <alpha-value>)",
          400: "rgb(var(--tw-lime-400) / <alpha-value>)",
        },
        fuchsia: {
          200: "rgb(var(--tw-fuchsia-200) / <alpha-value>)",
          300: "rgb(var(--tw-fuchsia-300) / <alpha-value>)",
          400: "rgb(var(--tw-fuchsia-400) / <alpha-value>)",
        },
        sky: {
          200: "rgb(var(--tw-sky-200) / <alpha-value>)",
          300: "rgb(var(--tw-sky-300) / <alpha-value>)",
          400: "rgb(var(--tw-sky-400) / <alpha-value>)",
        },
        violet: {
          200: "rgb(var(--tw-violet-200) / <alpha-value>)",
          300: "rgb(var(--tw-violet-300) / <alpha-value>)",
          400: "rgb(var(--tw-violet-400) / <alpha-value>)",
        },
        pink: {
          200: "rgb(var(--tw-pink-200) / <alpha-value>)",
          300: "rgb(var(--tw-pink-300) / <alpha-value>)",
          400: "rgb(var(--tw-pink-400) / <alpha-value>)",
        },
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "Liberation Mono",
          "Courier New",
          "monospace",
        ],
      },
      fontVariantNumeric: {
        tabular: "tabular-nums",
      },
    },
  },
  plugins: [
    require("@tailwindcss/typography"),
    // light: 변형 — html.light일 때만 적용 (다크 기본이라 dark:가 아닌 light:가 예외 처리 방향).
    plugin(({ addVariant }) => addVariant("light", "html.light &")),
  ],
};

export default config;
