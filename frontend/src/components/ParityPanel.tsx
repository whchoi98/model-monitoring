"use client";

// 패리티 런 (v2.10.0) — Bedrock Feature Parity 런의 동작 방식 설명(한국어 번역) +
// 결과 스크린샷 갤러리. 이미지는 public/parity/의 최적화된 WebP (썸네일 + 풀사이즈).

import { useState } from "react";
import { useLang } from "@/lib/i18n-context";

const IMAGE_COUNT = 20;
const IMAGES = Array.from({ length: IMAGE_COUNT }, (_, i) => `parity-${String(i + 1).padStart(2, "0")}`);

interface Step {
  no: string;
  titleKo: string;
  titleEn: string;
  bodyKo: string;
  bodyEn: string;
}

const STEPS: Step[] = [
  {
    no: "1",
    titleKo: "예약 스윕 (Scheduled sweep)",
    titleEn: "Scheduled sweep",
    bodyKo:
      "EventBridge 스케줄이 Step Functions 상태 머신을 시작합니다. 첫 단계(plan)는 라이브 /v1/models 엔드포인트에서 Bedrock Mantle 엔진이 현재 서빙 중인 모델을 발견합니다 — 신규 모델은 자동으로 반영되고, 날짜 스냅샷과 safeguard 변형은 필터링됩니다.",
    bodyEn:
      "An EventBridge schedule starts a Step Functions state machine. The first step (plan) discovers the models currently served by Bedrock's Mantle engine from the live /v1/models endpoint — new models are picked up automatically, dated snapshots and safeguard variants are filtered out.",
  },
  {
    no: "2",
    titleKo: "에이전트가 관리하는 피처 카탈로그",
    titleEn: "Agent-maintained feature catalog",
    bodyKo:
      "프로빙 전에 리서치 에이전트(Bedrock 위의 Claude — provider 문서와 AWS Knowledge MCP 서버에 그라운딩)가 각 provider의 공개 기능을 검토하고, 새로 발표된 기능을 카탈로그에 추가합니다. Bedrock이 아직 지원하지 않는 기능도 의도적으로 포함해 격차를 첫날부터 추적합니다. 카탈로그는 DynamoDB에 저장되며, 시드 목록은 부트스트랩일 뿐입니다.",
    bodyEn:
      "Before probing, a research agent (Claude on Bedrock, grounded in provider docs and the AWS Knowledge MCP server) reviews each provider's public capabilities and adds newly announced features to the catalog — deliberately including capabilities Bedrock does not support yet, so gaps are tracked from day one. The catalog lives in DynamoDB; the seed list is only its bootstrap.",
  },
  {
    no: "3",
    titleKo: "매트릭스 팬아웃",
    titleEn: "Fan-out across the matrix",
    bodyKo:
      "상태 머신이 모델 × 리전 × API surface 조합마다 러너 호출을 하나씩 팬아웃합니다. 5개 surface를 프로빙합니다: Anthropic Messages, OpenAI Chat Completions와 Responses(bearer 토큰), 그리고 InvokeModel / Converse(SigV4, CRIS inference profile) — 15개 Mantle 프로덕션 리전 전체에 걸쳐서.",
    bodyEn:
      "The state machine fans out one runner invocation per model × region × API surface. Five surfaces are probed: Anthropic Messages, OpenAI Chat Completions and Responses (bearer token), and InvokeModel / Converse (SigV4, CRIS inference profiles) — across all 15 Mantle production regions.",
  },
  {
    no: "4",
    titleKo: "실행-증거 프로브 (Execution-evidence probes)",
    titleEn: "Execution-evidence probes",
    bodyKo:
      "각 기능은 실제 요청으로 검증되며, 프로브는 응답의 내용을 검사합니다 — HTTP 200만으로는 절대 충분하지 않습니다. 예: MCP 프로브는 전용 픽스처 Lambda(실제 MCP 서버)를 커넥터로 연결하고, echo 카나리가 왕복하는 실행된 mcp_call을 요구합니다. system-instructions 프로브는 instructions 필드가 실제로 usage 토큰에 계산되는지 확인합니다. 캐싱 프로브는 동일 프롬프트 반복 시 cached_tokens를 확인합니다. 서버사이드 도구는 tool_choice: required를 강제해 — 모델의 기분이 아니라 능력을 측정합니다.",
    bodyEn:
      "Each feature is exercised with a real request, and the probe inspects the response content — an HTTP 200 is never enough. Examples: the MCP probe wires a purpose-built fixture Lambda (a real MCP server) as the connector and requires an executed mcp_call whose echo canary round-trips; the system-instructions probe verifies the instructions field is actually counted in usage tokens; the caching probe checks cached_tokens on repeat identical prompts; server-side tools force tool_choice: required so results measure capability, not model mood.",
  },
  {
    no: "5",
    titleKo: "분류 및 저장",
    titleEn: "Classification & storage",
    bodyKo:
      "원시 증거(요청, 응답, 지연시간, 오류)가 분류되어 DynamoDB에 저장된 뒤 대시보드에 제공됩니다. 매트릭스의 어떤 셀이든 클릭하면 그 뒤에 있는 리전별 증거를 확인할 수 있습니다.",
    bodyEn:
      "Raw evidence (request, response, latency, error) is classified and persisted to DynamoDB, then served to this dashboard. Click any cell in the matrix to see the per-region evidence behind it.",
  },
];

export default function ParityPanel() {
  const { lang } = useLang();
  const [lightbox, setLightbox] = useState<string | null>(null);

  return (
    <div className="p-6 space-y-8 max-w-7xl mx-auto">
      {/* 개요 */}
      <div>
        <h2 className="text-xl font-bold text-gray-100">
          {lang === "en" ? "Parity Run" : "패리티 런"}
        </h2>
        <p className="text-sm text-gray-400 mt-2 leading-relaxed max-w-3xl">
          {lang === "en"
            ? "Every result on the parity dashboard is backed by a real API call against Bedrock — nothing is asserted from documentation alone."
            : "패리티 대시보드의 모든 결과는 Bedrock에 대한 실제 API 호출로 검증됩니다 — 문서만으로 단정하는 항목은 없습니다."}
        </p>
        <a
          href="/parity/parity-report-2026-07-08.html"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block mt-3 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          {lang === "en" ? "Open full report (2026-07-08) ↗" : "전체 리포트 열기 (2026-07-08) ↗"}
        </a>
      </div>

      {/* 동작 방식 5단계 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "How a parity run works" : "패리티 런은 어떻게 동작하나"}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {STEPS.map((s) => (
            <div key={s.no} className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-6 h-6 shrink-0 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">
                  {s.no}
                </span>
                <h4 className="text-sm font-semibold text-gray-100">
                  {lang === "en" ? s.titleEn : s.titleKo}
                </h4>
              </div>
              <p className="text-xs text-gray-400 leading-relaxed">
                {lang === "en" ? s.bodyEn : s.bodyKo}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* 결과 갤러리 */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-200">
          {lang === "en" ? `Run results (${IMAGE_COUNT} captures)` : `실행 결과 (${IMAGE_COUNT}장)`}
        </h3>
        <p className="text-xs text-gray-500">
          {lang === "en" ? "Click an image to enlarge." : "이미지를 클릭하면 크게 볼 수 있습니다."}
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {IMAGES.map((name) => (
            <button
              key={name}
              onClick={() => setLightbox(name)}
              className="bg-gray-900/50 border border-gray-800 rounded-xl overflow-hidden hover:border-blue-500/50 transition-colors"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/parity/${name}-thumb.webp`}
                alt={name}
                loading="lazy"
                className="w-full h-40 object-cover object-top"
              />
            </button>
          ))}
        </div>
      </div>

      {/* 라이트박스 */}
      {lightbox && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            aria-label="overlay"
            onClick={() => setLightbox(null)}
            className="absolute inset-0 bg-black/80 backdrop-blur-sm"
          />
          <div className="relative max-w-5xl max-h-[90vh] overflow-auto rounded-xl border border-gray-700 shadow-2xl">
            <button
              type="button"
              onClick={() => setLightbox(null)}
              className="sticky top-2 float-right mr-2 w-8 h-8 rounded-full bg-black/60 text-white text-xl leading-none z-10"
              aria-label="close"
            >
              ×
            </button>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/parity/${lightbox}.webp`} alt={lightbox} className="w-full" />
          </div>
        </div>
      )}
    </div>
  );
}
