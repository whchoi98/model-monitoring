"use client";

import Script from "next/script";

// RUM(Real User Monitoring) 수집 — aws-rum-pipeline 연동.
// NEXT_PUBLIC_* 값은 빌드 시점에 주입되며, 미설정 시 수집이 완전히 비활성화된다(개발 환경 기본).
const RUM_ENDPOINT = process.env.NEXT_PUBLIC_RUM_ENDPOINT;
const RUM_API_KEY = process.env.NEXT_PUBLIC_RUM_API_KEY;

declare global {
  interface Window {
    RumSDK?: {
      init(config: {
        endpoint: string;
        apiKey: string;
        appName: string;
        appVersion: string;
      }): void;
    };
  }
}

export default function RumProvider() {
  if (!RUM_ENDPOINT || !RUM_API_KEY) return null;

  return (
    <Script
      src="/rum-sdk.min.js"
      strategy="afterInteractive"
      // onLoad는 preload 캐시에서 스크립트가 먼저 실행되면 누락될 수 있어
      // onReady 사용 (마운트마다 호출되지만 RumSDK.init은 멱등).
      onReady={() => {
        window.RumSDK?.init({
          endpoint: RUM_ENDPOINT,
          apiKey: RUM_API_KEY,
          appName: "llm-monitor", // rum-pipeline 파티션 식별자 (^[a-z0-9-]{1,64}$)
          appVersion: "2.16.2",
        });
      }}
    />
  );
}
