/**
 * 대시보드 모델 카드 지표 등급 (v2.28.0) — TTFT, 총 응답시간, TPS 값을 양호/경고/위험으로 분류.
 * (KO 이름 "양호"는 채널 건강 배지의 "정상"과 구분하려는 것 — i18n.ts koGradeNames, ADR-029.)
 *
 * 기준값은 워크로드 카테고리별 절대 임계치다. 카테고리마다 프롬프트와 max_tokens가 달라
 * (예: reasoning은 긴 사고 출력, chat-short는 짧은 응답) 같은 TTFT라도 의미가 다르기 때문.
 * 도출: 2026-09-23 운영 자동 프로브 48시간치의 카테고리별 p90/p99를 근거로 읽기 쉬운 값으로
 * 정했다(사용자 승인 설계). 같은 48시간 데이터에 적용하면 카드에 보이는 분포(표시 정밀도 반올림 후 판정)는
 * 양호 89.0%, 경고 9.6%, 위험 1.4%다(원값 판정 89.2 / 9.4 / 1.4%, ADR-029). 기준을 바꿀 때는 이 표만 수정한다
 * (카드 색, 툴팁, 범례 기준표가 모두 여기서 읽는다).
 *
 * 경계: 지연시간(TTFT, 총 응답시간)은 값 ≥ warn → 경고, 값 ≥ crit → 위험.
 * TPS는 낮을수록 나쁘므로 반대로 값 < warn → 경고, 값 < crit → 위험 (전 카테고리 공통).
 * null, undefined, NaN, ±Infinity는 "none"(측정값 없음, 회색 유지).
 * 카드는 원값이 아니라 roundForDisplay로 표시 정밀도에 맞춘 값을 판정한다(보이는 숫자와 색이 항상 일치).
 */

export type MetricGrade = "normal" | "warning" | "critical" | "none";
export type GradedMetric = "ttft" | "total" | "tps";

/** 자동 프로브 워크로드 카테고리 id — backend/auto_prober.py WORKLOAD_PRESETS와 동일. */
export const WORKLOAD_CATEGORY_IDS = ["chat-short", "structured", "summarize", "translate", "code-gen", "reasoning"] as const;
export type WorkloadCategoryId = (typeof WORKLOAD_CATEGORY_IDS)[number];

export interface GradeThreshold {
  /** 이 값 이상(TPS는 미만)이면 경고 */
  warn: number;
  /** 이 값 이상(TPS는 미만)이면 위험 */
  crit: number;
}

export interface LatencyThresholds {
  ttft: GradeThreshold;
  total: GradeThreshold;
}

/** 카테고리별 지연시간 임계치 (ms) — 단일 출처. */
export const LATENCY_THRESHOLDS: Readonly<Record<WorkloadCategoryId, LatencyThresholds>> = {
  "chat-short": { ttft: { warn: 3000, crit: 8000 }, total: { warn: 4000, crit: 10000 } },
  structured: { ttft: { warn: 3500, crit: 8000 }, total: { warn: 4000, crit: 10000 } },
  summarize: { ttft: { warn: 3000, crit: 8000 }, total: { warn: 5000, crit: 10000 } },
  translate: { ttft: { warn: 3500, crit: 8000 }, total: { warn: 8000, crit: 12000 } },
  "code-gen": { ttft: { warn: 5000, crit: 12000 }, total: { warn: 7500, crit: 14000 } },
  reasoning: { ttft: { warn: 9000, crit: 16000 }, total: { warn: 11000, crit: 24000 } },
};

/** 카테고리가 없거나(수동 프로브 등) 표에 없는 값일 때 쓰는 기본 임계치 (ms). */
export const FALLBACK_LATENCY_THRESHOLDS: Readonly<LatencyThresholds> = {
  ttft: { warn: 5000, crit: 12000 },
  total: { warn: 10000, crit: 24000 },
};

/** TPS 임계치 (tok/s, 전 카테고리 공통) — 낮을수록 나쁨: warn > crit. */
export const TPS_THRESHOLD: Readonly<GradeThreshold> = { warn: 40, crit: 15 };

export function isWorkloadCategory(category: string | null | undefined): category is WorkloadCategoryId {
  return typeof category === "string" && (WORKLOAD_CATEGORY_IDS as readonly string[]).includes(category);
}

/** 카테고리 id → 적용 임계치. 알 수 없는 카테고리는 fallback. */
export function latencyThresholdsFor(category: string | null | undefined): LatencyThresholds {
  return isWorkloadCategory(category) ? LATENCY_THRESHOLDS[category] : FALLBACK_LATENCY_THRESHOLDS;
}

function isMeasured(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * 카드에 표시되는 정밀도로 값을 반올림한다. 등급도 이 값으로 매겨야 색·툴팁이 화면의 숫자와 어긋나지 않는다
 * (예: chat-short 총 응답시간 3960ms는 "4.0 s"로 보이는데 원값 기준이면 양호 색이 된다).
 * TTFT는 ms 정수, 총 응답시간은 초 소수 1자리(= 100ms 단위), TPS는 소수 1자리. 측정값 없음은 null.
 */
export function roundForDisplay(metric: GradedMetric, value: number | null | undefined): number | null {
  if (!isMeasured(value)) return null;
  if (metric === "ttft") return Math.round(value);
  if (metric === "total") return Math.round(value / 100) * 100;
  return Math.round(value * 10) / 10;
}

/** roundForDisplay 결과 → 카드 값 텍스트 (단위 제외). TTFT "3200", 총 응답시간 "4.0"(초), TPS "12.0". */
export function formatMetricValue(metric: GradedMetric, rounded: number | null): string {
  if (rounded == null) return "—";
  if (metric === "ttft") return `${rounded}`;
  if (metric === "total") return (rounded / 1000).toFixed(1);
  return rounded.toFixed(1);
}

function gradeHigherIsWorse(value: number | null | undefined, { warn, crit }: GradeThreshold): MetricGrade {
  if (!isMeasured(value)) return "none";
  if (value >= crit) return "critical";
  if (value >= warn) return "warning";
  return "normal";
}

function gradeLowerIsWorse(value: number | null | undefined, { warn, crit }: GradeThreshold): MetricGrade {
  if (!isMeasured(value)) return "none";
  if (value < crit) return "critical";
  if (value < warn) return "warning";
  return "normal";
}

export function gradeTtft(ms: number | null | undefined, category: string | null | undefined): MetricGrade {
  return gradeHigherIsWorse(ms, latencyThresholdsFor(category).ttft);
}

export function gradeTotalLatency(ms: number | null | undefined, category: string | null | undefined): MetricGrade {
  return gradeHigherIsWorse(ms, latencyThresholdsFor(category).total);
}

export function gradeTps(tps: number | null | undefined): MetricGrade {
  return gradeLowerIsWorse(tps, TPS_THRESHOLD);
}

export interface GradeRule {
  grade: MetricGrade;
  warnAt: number;
  critAt: number;
  unit: "ms" | "tok/s";
  /** true면 낮을수록 나쁨(TPS) — 경계 문구가 "미만"으로 바뀐다 */
  lowerIsWorse: boolean;
  /** 적용된 카테고리 id. null이면 fallback 기준(지연시간) 또는 카테고리 무관(TPS) */
  category: WorkloadCategoryId | null;
}

/** 툴팁·보조 텍스트용: 값의 등급과 적용된 기준을 함께 돌려준다. */
export function describeGrade(metric: GradedMetric, value: number | null | undefined, category: string | null | undefined): GradeRule {
  if (metric === "tps") {
    return { grade: gradeTps(value), warnAt: TPS_THRESHOLD.warn, critAt: TPS_THRESHOLD.crit, unit: "tok/s", lowerIsWorse: true, category: null };
  }
  const threshold = latencyThresholdsFor(category)[metric];
  return {
    grade: gradeHigherIsWorse(value, threshold),
    warnAt: threshold.warn,
    critAt: threshold.crit,
    unit: "ms",
    lowerIsWorse: false,
    category: isWorkloadCategory(category) ? category : null,
  };
}

/**
 * 등급 → 값 텍스트 색. 라벨·단위는 회색 유지, 값에만 적용한다.
 * tailwind.config가 blue/amber/rose 200~400을 globals.css 변수로 재매핑하므로 두 테마 모두 대비를 확인했다
 * (카드 배경 gray-900/50에 hover 오버레이까지 얹은 최저값): blue-300 다크 10.1:1, 라이트 6.2:1,
 * amber-300 다크 12.6:1, 라이트 4.6:1. 위험은 다크에서 더 붉게 보이도록 rose-400(6.7:1)을 쓰고,
 * 라이트에서는 rose-400(4.3:1)이 4.5:1에 못 미쳐 light: 변형으로 rose-300(5.8:1)을 쓴다.
 */
export const GRADE_TEXT_CLASS: Readonly<Record<MetricGrade, string>> = {
  normal: "text-blue-300",
  warning: "text-amber-300",
  critical: "text-rose-400 light:text-rose-300",
  none: "text-gray-200",
};

/**
 * 색에만 의존하지 않도록 경고/위험 값 옆에 붙이는 모양 표지 (범례와 동일).
 * 양호 값에는 표지가 없으므로 normal은 빈 문자열이다 — 범례도 양호는 모양 없이 색 견본(swatch)만 보여 준다.
 */
export const GRADE_MARKER: Readonly<Record<MetricGrade, string>> = {
  normal: "",
  warning: "▲",
  critical: "◆",
  none: "",
};
