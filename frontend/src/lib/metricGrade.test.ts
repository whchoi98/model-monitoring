/**
 * 대시보드 카드 지표 등급 (v2.28.0) 회귀.
 *
 * 경계값 규칙: 지연시간은 warn 이상 → warning, crit 이상 → critical.
 * TPS는 반대(낮을수록 나쁨): warn 미만 → warning, crit 미만 → critical.
 * 측정값 없음(null/undefined/NaN/Infinity) → none.
 */
import { describe, expect, test } from "vitest";
import {
  FALLBACK_LATENCY_THRESHOLDS,
  GRADE_MARKER,
  GRADE_TEXT_CLASS,
  LATENCY_THRESHOLDS,
  TPS_THRESHOLD,
  WORKLOAD_CATEGORY_IDS,
  describeGrade,
  formatMetricValue,
  gradeTotalLatency,
  gradeTps,
  gradeTtft,
  latencyThresholdsFor,
  roundForDisplay,
} from "./metricGrade";
import { en, ko } from "./i18n";

// 사용자 승인 설계값(2026-09-23)을 그대로 고정 — 표가 바뀌면 이 테스트가 먼저 알려준다.
const EXPECTED = {
  "chat-short": { ttft: [3000, 8000], total: [4000, 10000] },
  structured: { ttft: [3500, 8000], total: [4000, 10000] },
  summarize: { ttft: [3000, 8000], total: [5000, 10000] },
  translate: { ttft: [3500, 8000], total: [8000, 12000] },
  "code-gen": { ttft: [5000, 12000], total: [7500, 14000] },
  reasoning: { ttft: [9000, 16000], total: [11000, 24000] },
} as const;

describe("임계치 표 형태", () => {
  test("backend WORKLOAD_PRESETS의 6개 카테고리를 모두 가진다", () => {
    expect([...WORKLOAD_CATEGORY_IDS].sort()).toEqual(Object.keys(EXPECTED).sort());
    expect(Object.keys(LATENCY_THRESHOLDS).sort()).toEqual(Object.keys(EXPECTED).sort());
  });

  test.each(Object.entries(EXPECTED))("%s 설계값 고정", (category, expected) => {
    const t = LATENCY_THRESHOLDS[category as keyof typeof LATENCY_THRESHOLDS];
    expect([t.ttft.warn, t.ttft.crit]).toEqual(expected.ttft);
    expect([t.total.warn, t.total.crit]).toEqual(expected.total);
  });

  test("지연시간은 warn < crit (카테고리 전체 + fallback)", () => {
    for (const t of [...Object.values(LATENCY_THRESHOLDS), FALLBACK_LATENCY_THRESHOLDS]) {
      expect(t.ttft.warn).toBeLessThan(t.ttft.crit);
      expect(t.total.warn).toBeLessThan(t.total.crit);
      expect(t.ttft.warn).toBeGreaterThan(0);
      expect(t.total.warn).toBeGreaterThan(0);
    }
  });

  test("TPS는 낮을수록 나쁘므로 crit < warn", () => {
    expect(TPS_THRESHOLD).toEqual({ warn: 40, crit: 15 });
    expect(TPS_THRESHOLD.crit).toBeLessThan(TPS_THRESHOLD.warn);
  });

  test("fallback 설계값 고정", () => {
    expect(FALLBACK_LATENCY_THRESHOLDS).toEqual({ ttft: { warn: 5000, crit: 12000 }, total: { warn: 10000, crit: 24000 } });
  });

  test("모든 등급에 색 클래스가 있고, 경고/위험만 모양 표지가 서로 다르다", () => {
    for (const grade of ["normal", "warning", "critical", "none"] as const) expect(GRADE_TEXT_CLASS[grade]).toBeTruthy();
    expect(GRADE_TEXT_CLASS.normal).toContain("blue");
    expect(GRADE_TEXT_CLASS.warning).toContain("amber");
    expect(GRADE_TEXT_CLASS.critical).toContain("rose");
    expect(GRADE_TEXT_CLASS.none).toContain("gray");
    expect(GRADE_MARKER.warning).not.toBe(GRADE_MARKER.critical);
    expect(GRADE_MARKER.none).toBe("");
  });
});

describe("gradeTtft — 카테고리별 경계", () => {
  test.each(Object.entries(EXPECTED))("%s", (category, { ttft: [warn, crit] }) => {
    expect(gradeTtft(0, category)).toBe("normal");
    expect(gradeTtft(warn - 1, category)).toBe("normal");
    expect(gradeTtft(warn - 0.5, category)).toBe("normal");
    expect(gradeTtft(warn, category)).toBe("warning");
    expect(gradeTtft(crit - 1, category)).toBe("warning");
    expect(gradeTtft(crit, category)).toBe("critical");
    expect(gradeTtft(crit * 10, category)).toBe("critical");
  });
});

describe("gradeTotalLatency — 카테고리별 경계", () => {
  test.each(Object.entries(EXPECTED))("%s", (category, { total: [warn, crit] }) => {
    expect(gradeTotalLatency(0, category)).toBe("normal");
    expect(gradeTotalLatency(warn - 1, category)).toBe("normal");
    expect(gradeTotalLatency(warn, category)).toBe("warning");
    expect(gradeTotalLatency(crit - 1, category)).toBe("warning");
    expect(gradeTotalLatency(crit, category)).toBe("critical");
  });
});

describe("알 수 없는 카테고리 → fallback 기준", () => {
  test.each([null, undefined, "", "manual", "Chat-Short", "unknown"])("%s", (category) => {
    expect(latencyThresholdsFor(category)).toBe(FALLBACK_LATENCY_THRESHOLDS);
    expect(gradeTtft(4999, category)).toBe("normal");
    expect(gradeTtft(5000, category)).toBe("warning");
    expect(gradeTtft(11999, category)).toBe("warning");
    expect(gradeTtft(12000, category)).toBe("critical");
    expect(gradeTotalLatency(9999, category)).toBe("normal");
    expect(gradeTotalLatency(10000, category)).toBe("warning");
    expect(gradeTotalLatency(23999, category)).toBe("warning");
    expect(gradeTotalLatency(24000, category)).toBe("critical");
  });

  test("같은 값이라도 카테고리에 따라 등급이 달라진다", () => {
    expect(gradeTtft(6000, "chat-short")).toBe("warning");
    expect(gradeTtft(6000, "reasoning")).toBe("normal");
    expect(gradeTotalLatency(10000, "chat-short")).toBe("critical");
    expect(gradeTotalLatency(10000, "translate")).toBe("warning");
  });
});

describe("gradeTps — 낮을수록 나쁨 (카테고리 무관)", () => {
  test("경계", () => {
    expect(gradeTps(200)).toBe("normal");
    expect(gradeTps(40)).toBe("normal");
    expect(gradeTps(39.9)).toBe("warning");
    expect(gradeTps(15)).toBe("warning");
    expect(gradeTps(14.9)).toBe("critical");
    expect(gradeTps(0)).toBe("critical");
  });
});

describe("측정값 없음 → none", () => {
  test.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])("%s", (value) => {
    expect(gradeTtft(value, "chat-short")).toBe("none");
    expect(gradeTtft(value, null)).toBe("none");
    expect(gradeTotalLatency(value, "reasoning")).toBe("none");
    expect(gradeTps(value)).toBe("none");
  });
});

describe("describeGrade — 툴팁용 규칙 설명", () => {
  test("지연시간은 적용 카테고리와 경계를 함께 돌려준다", () => {
    expect(describeGrade("ttft", 3200, "chat-short")).toEqual({
      grade: "warning", warnAt: 3000, critAt: 8000, unit: "ms", lowerIsWorse: false, category: "chat-short",
    });
    expect(describeGrade("total", 25000, "reasoning")).toEqual({
      grade: "critical", warnAt: 11000, critAt: 24000, unit: "ms", lowerIsWorse: false, category: "reasoning",
    });
  });

  test("fallback은 category null", () => {
    expect(describeGrade("ttft", 100, "manual")).toEqual({
      grade: "normal", warnAt: 5000, critAt: 12000, unit: "ms", lowerIsWorse: false, category: null,
    });
    expect(describeGrade("total", null, null).grade).toBe("none");
  });

  test("TPS는 카테고리를 무시하고 낮을수록 나쁨으로 표시", () => {
    expect(describeGrade("tps", 12, "reasoning")).toEqual({
      grade: "critical", warnAt: 40, critAt: 15, unit: "tok/s", lowerIsWorse: true, category: null,
    });
  });

  test("describeGrade 등급은 개별 함수와 항상 같다", () => {
    for (const category of [...WORKLOAD_CATEGORY_IDS, null]) {
      for (const value of [0, 2999, 3000, 7999, 8000, 15000, 30000, null]) {
        expect(describeGrade("ttft", value, category).grade).toBe(gradeTtft(value, category));
        expect(describeGrade("total", value, category).grade).toBe(gradeTotalLatency(value, category));
      }
    }
    for (const value of [0, 14.9, 15, 39.9, 40, 100, null]) expect(describeGrade("tps", value, "summarize").grade).toBe(gradeTps(value));
  });
});

describe("표시 정밀도 반올림 — 보이는 숫자와 등급이 어긋나지 않는다", () => {
  test("TTFT는 ms 정수: 2999.6ms는 3000으로 보이므로 chat-short 경고", () => {
    expect(roundForDisplay("ttft", 2999.6)).toBe(3000);
    expect(formatMetricValue("ttft", roundForDisplay("ttft", 2999.6))).toBe("3000");
    expect(describeGrade("ttft", roundForDisplay("ttft", 2999.6), "chat-short").grade).toBe("warning");
    expect(describeGrade("ttft", roundForDisplay("ttft", 2999.4), "chat-short").grade).toBe("normal");
    expect(formatMetricValue("ttft", roundForDisplay("ttft", 2999.4))).toBe("2999");
  });

  test("총 응답시간은 초 소수 1자리(100ms 단위): 3960ms는 \"4.0 s\"로 보이므로 chat-short 경고", () => {
    expect(roundForDisplay("total", 3960)).toBe(4000);
    expect(formatMetricValue("total", roundForDisplay("total", 3960))).toBe("4.0");
    expect(describeGrade("total", roundForDisplay("total", 3960), "chat-short").grade).toBe("warning");
    expect(formatMetricValue("total", roundForDisplay("total", 3949))).toBe("3.9");
    expect(describeGrade("total", roundForDisplay("total", 3949), "chat-short").grade).toBe("normal");
  });

  test("9960ms는 \"10.0 s\"로 보이므로 chat-short 위험", () => {
    expect(roundForDisplay("total", 9960)).toBe(10000);
    expect(formatMetricValue("total", roundForDisplay("total", 9960))).toBe("10.0");
    expect(describeGrade("total", roundForDisplay("total", 9960), "chat-short").grade).toBe("critical");
  });

  test("TPS는 소수 1자리: 39.96은 40.0으로 보이므로 양호, 14.96은 15.0이므로 경고", () => {
    expect(roundForDisplay("tps", 39.96)).toBe(40);
    expect(formatMetricValue("tps", roundForDisplay("tps", 39.96))).toBe("40.0");
    expect(describeGrade("tps", roundForDisplay("tps", 39.96), null).grade).toBe("normal");
    expect(describeGrade("tps", roundForDisplay("tps", 39.94), null).grade).toBe("warning");
    expect(describeGrade("tps", roundForDisplay("tps", 14.96), null).grade).toBe("warning");
    expect(describeGrade("tps", roundForDisplay("tps", 14.94), null).grade).toBe("critical");
  });

  test("측정값 없음은 null → \"—\", 등급 none", () => {
    for (const metric of ["ttft", "total", "tps"] as const) {
      for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
        expect(roundForDisplay(metric, value)).toBeNull();
        expect(formatMetricValue(metric, roundForDisplay(metric, value))).toBe("—");
        expect(describeGrade(metric, roundForDisplay(metric, value), "chat-short").grade).toBe("none");
      }
    }
  });

  test("표시 문자열을 다시 읽은 값의 등급 = 반올림 값의 등급 (경계 주변 전수)", () => {
    const scale = { ttft: 1, total: 1000, tps: 1 } as const;
    for (const category of [...WORKLOAD_CATEGORY_IDS, null]) {
      const t = latencyThresholdsFor(category);
      const probes = {
        ttft: [t.ttft.warn, t.ttft.crit],
        total: [t.total.warn, t.total.crit],
        tps: [TPS_THRESHOLD.warn, TPS_THRESHOLD.crit],
      } as const;
      for (const metric of ["ttft", "total", "tps"] as const) {
        const step = metric === "tps" ? 0.01 : metric === "total" ? 7 : 0.1;
        for (const boundary of probes[metric]) {
          for (let i = -20; i <= 20; i += 1) {
            const raw = boundary + i * step;
            const shown = roundForDisplay(metric, raw);
            const reparsed = Number(formatMetricValue(metric, shown)) * scale[metric];
            expect(describeGrade(metric, shown, category).grade).toBe(describeGrade(metric, reparsed, category).grade);
          }
        }
      }
    }
  });
});

describe("i18n 등급 문구 — 이름은 한 곳에서 정의", () => {
  test.each([["ko", ko], ["en", en]] as const)("%s: 툴팁 문구가 범례 이름을 그대로 쓴다", (_lang, t) => {
    const g = t.monitoring.grade;
    const base = { metric: "TTFT", scope: "S", warnAt: 3000, critAt: 8000, unit: "ms" as const, lowerIsWorse: false };
    for (const grade of ["normal", "warning", "critical"] as const) {
      expect(g.hint({ ...base, grade }).startsWith(`${g.names[grade]} — `)).toBe(true);
    }
    expect(g.hint({ ...base, grade: "warning" }).toLowerCase()).toContain(g.names.critical.toLowerCase());
  });

  test("KO 문구 고정", () => {
    expect(ko.monitoring.grade.hint({ grade: "warning", metric: "TTFT", scope: "짧은 대화", warnAt: 3000, critAt: 8000, unit: "ms", lowerIsWorse: false }))
      .toBe("경고 — 짧은 대화 기준 TTFT 3초 이상, 위험 8초 이상");
    expect(ko.monitoring.grade.hint({ grade: "normal", metric: "TTFT", scope: "짧은 대화", warnAt: 3000, critAt: 8000, unit: "ms", lowerIsWorse: false }))
      .toBe("양호 — 짧은 대화 기준 TTFT 3초 미만");
  });

  test("KO 등급 이름: 양호/경고/위험 — 채널 건강 배지 이름과 겹치지 않는다", () => {
    expect(ko.monitoring.grade.names).toEqual({ normal: "양호", warning: "경고", critical: "위험" });
    expect(en.monitoring.grade.names.normal).toBe("Normal");
    for (const [t] of [[ko], [en]] as const) {
      const healthNames = new Set(Object.values(t.monitoring.health));
      for (const name of Object.values(t.monitoring.grade.names)) expect(healthNames.has(name)).toBe(false);
    }
  });

  test("EN 문구 고정", () => {
    expect(en.monitoring.grade.hint({ grade: "warning", metric: "TPS", scope: "All workloads", warnAt: 40, critAt: 15, unit: "tok/s", lowerIsWorse: true }))
      .toBe("Warning — All workloads: TPS below 40 tok/s, critical below 15 tok/s");
  });
});
