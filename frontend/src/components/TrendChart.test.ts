/** 대시보드 추세 차트 선 인코딩 (v2.32.0) — 색 × 선 패턴(채널 티어).
 *
 * 서울 In-Region 선("(ap-northeast-2)")은 리전 티어가 실선이던 때 다른 family의 Global 실선과 색으로만 구분됐다
 * (Opus 5 서울 대 Opus 5.5 Global ΔE 5.8). CP Sonnet 5.5는 CP Sonnet 5와 같은 점선에 ΔE 4.7이었고, GPT 6.1 Sol
 * Global은 Haiku 4.5 Global과 같은 청록 실선(ΔE 6.3)이었다. 색 차이는 테마 보정(getColor)을 거친 값으로 잰다.
 * CP Sonnet 5.5를 떼어 놓은 짙은 보라(#3b0764)는 다크 차트 카드에서 대비 3.05:1로 묻혀서 대비 하한도 고정한다.
 */
import { describe, expect, test } from "vitest";
import { isExcludedModel } from "@/lib/sortModels";
import { defaultTrendSelection } from "@/lib/trendSelection";
import { MODEL_COLORS, getColor, lineDash } from "./TrendChart";

const THEMES = ["dark", "light"] as const;
const CATALOG = Object.keys(MODEL_COLORS).filter((name) => !isExcludedModel(name));
const MIN_DELTA_E = 15;

// Chart card backgrounds: bg-gray-900/50 over the page's bg-gray-950 (globals.css), plus the bare white card in light.
const CARD_BACKGROUNDS = { dark: ["#0a101d"], light: ["#fafbfd", "#ffffff"] } as const;
const MIN_CONTRAST = { dark: 4.5, light: 3 } as const;

type Lab = [number, number, number];

/** Linear-light sRGB channels of a #rrggbb colour. */
function linearRgb(hex: string): number[] {
  return [1, 3, 5].map((index) => {
    const c = parseInt(hex.slice(index, index + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
}

/** WCAG 2 contrast ratio from relative luminance. */
function contrastRatio(first: string, second: string): number {
  const [hi, lo] = [first, second].map((hex) => {
    const [r, g, b] = linearRgb(hex);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }).sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function hexToLab(hex: string): Lab {
  const [r, g, b] = linearRgb(hex);
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const x = f((0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047);
  const y = f(0.2126729 * r + 0.7151522 * g + 0.072175 * b);
  const z = f((0.0193339 * r + 0.119192 * g + 0.9503041 * b) / 1.08883);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}

/** CIEDE2000 (Sharma, Wu, Dalal 2005). */
function deltaE2000([l1, a1, b1]: Lab, [l2, a2, b2]: Lab): number {
  const rad = Math.PI / 180;
  const cBar = (Math.hypot(a1, b1) + Math.hypot(a2, b2)) / 2;
  const g = 0.5 * (1 - Math.sqrt(cBar ** 7 / (cBar ** 7 + 25 ** 7)));
  const a1p = (1 + g) * a1;
  const a2p = (1 + g) * a2;
  const c1p = Math.hypot(a1p, b1);
  const c2p = Math.hypot(a2p, b2);
  const hue = (b: number, a: number) => (b === 0 && a === 0 ? 0 : ((Math.atan2(b, a) / rad) + 360) % 360);
  const h1p = hue(b1, a1p);
  const h2p = hue(b2, a2p);
  let dh = c1p * c2p === 0 ? 0 : h2p - h1p;
  if (dh > 180) dh -= 360;
  else if (dh < -180) dh += 360;
  const dL = l2 - l1;
  const dC = c2p - c1p;
  const dH = 2 * Math.sqrt(c1p * c2p) * Math.sin((dh / 2) * rad);
  const lBar = (l1 + l2) / 2;
  const cBarP = (c1p + c2p) / 2;
  let hBar = h1p + h2p;
  if (c1p * c2p !== 0) {
    hBar = Math.abs(h1p - h2p) <= 180 ? hBar / 2 : hBar < 360 ? (hBar + 360) / 2 : (hBar - 360) / 2;
  }
  const t = 1 - 0.17 * Math.cos((hBar - 30) * rad) + 0.24 * Math.cos(2 * hBar * rad)
    + 0.32 * Math.cos((3 * hBar + 6) * rad) - 0.2 * Math.cos((4 * hBar - 63) * rad);
  const rc = 2 * Math.sqrt(cBarP ** 7 / (cBarP ** 7 + 25 ** 7));
  const rt = -Math.sin(2 * 30 * Math.exp(-(((hBar - 275) / 25) ** 2)) * rad) * rc;
  const sl = 1 + (0.015 * (lBar - 50) ** 2) / Math.sqrt(20 + (lBar - 50) ** 2);
  const sc = 1 + 0.045 * cBarP;
  const sh = 1 + 0.015 * cBarP * t;
  return Math.sqrt((dL / sl) ** 2 + (dC / sc) ** 2 + (dH / sh) ** 2 + rt * (dC / sc) * (dH / sh));
}

const distance = (a: string, b: string, theme: "dark" | "light") =>
  deltaE2000(hexToLab(getColor(a, theme)), hexToLab(getColor(b, theme)));

/** The closest same-pattern series to `name` outside `skip`, in either theme. */
function nearestSamePattern(name: string, skip: (other: string) => boolean) {
  let nearest = { delta: Infinity, other: "", theme: "" };
  for (const theme of THEMES) {
    for (const other of CATALOG) {
      if (other === name || skip(other) || lineDash(other) !== lineDash(name)) continue;
      const delta = distance(name, other, theme);
      if (delta < nearest.delta) nearest = { delta, other, theme };
    }
  }
  return nearest;
}

describe("deltaE2000", () => {
  test("matches the Sharma reference pair", () => {
    expect(deltaE2000([50, 2.6772, -79.7751], [50, 0, -82.7485])).toBeCloseTo(2.0425, 4);
  });
});

describe("contrastRatio", () => {
  test("matches the WCAG extremes", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 6);
    expect(contrastRatio("#777777", "#777777")).toBe(1);
  });
});

describe("lineDash — one pattern per channel tier", () => {
  test("CP dotted, Global solid, US dashed", () => {
    expect(lineDash("Anthropic Claude Opus 5 (US)")).toBe("2 3");
    expect(lineDash("Bedrock Claude Opus 5 (Global)")).toBeUndefined();
    expect(lineDash("OpenAI GPT 6.1 Sol (Global)")).toBeUndefined();
    expect(lineDash("Bedrock Claude Opus 5 (US)")).toBe("6 3");
    expect(lineDash("OpenAI GPT 6.1 Sol (US)")).toBe("6 3");
  });

  test("Bedrock In-Region gets its own dash-dot pattern, and OpenAI Mantle regions share it", () => {
    expect(lineDash("Bedrock Claude Opus 5 (ap-northeast-2)")).toBe("1 2 6 2");
    expect(lineDash("Bedrock Claude Sonnet 5 (ap-northeast-2)")).toBe("1 2 6 2");
    expect(lineDash("OpenAI GPT 6.1 Sol (us-east-1)")).toBe("1 2 6 2");
    expect(lineDash("OpenAI GPT 5.4 (us-west-2)")).toBe("1 2 6 2");
  });

  test("the four tiers use four different patterns", () => {
    const tiers = ["Anthropic Claude Opus 5 (US)", "Bedrock Claude Opus 5 (Global)", "Bedrock Claude Opus 5 (US)", "Bedrock Claude Opus 5 (ap-northeast-2)"];
    expect(new Set(tiers.map(lineDash)).size).toBe(4);
  });
});

describe("trend chart line encoding", () => {
  const selection = [...defaultTrendSelection(CATALOG)];

  test("no two default-selected series share both colour and pattern, in either theme", () => {
    expect(selection.length).toBeGreaterThan(15);
    for (const theme of THEMES) {
      const encodings = selection.map((name) => `${getColor(name, theme)}|${lineDash(name) ?? "solid"}`);
      expect(new Set(encodings).size).toBe(selection.length);
    }
  });

  test("CP Sonnet 5.5 stays clear of every dotted series, every Sonnet channel and every default-selected series", () => {
    const name = "Anthropic Claude Sonnet 5.5 (US)";
    expect(selection).toContain(name);
    expect(nearestSamePattern(name, () => false).delta).toBeGreaterThanOrEqual(MIN_DELTA_E);
    for (const theme of THEMES) {
      for (const other of CATALOG.filter((label) => label !== name && label.includes("Sonnet"))) {
        expect(distance(name, other, theme), `${other} (${theme})`).toBeGreaterThanOrEqual(MIN_DELTA_E);
      }
      for (const other of selection.filter((label) => label !== name)) {
        expect(distance(name, other, theme), `${other} (${theme}, default selection)`).toBeGreaterThanOrEqual(MIN_DELTA_E);
      }
    }
  });

  test("CP Sonnet 5.5 keeps a contrast floor on the chart card in both themes", () => {
    const name = "Anthropic Claude Sonnet 5.5 (US)";
    for (const theme of THEMES) {
      for (const card of CARD_BACKGROUNDS[theme]) {
        expect(contrastRatio(getColor(name, theme), card), `${getColor(name, theme)} on ${card} (${theme})`)
          .toBeGreaterThanOrEqual(MIN_CONTRAST[theme]);
      }
    }
  });

  test("GPT 6.1 Sol channels stay clear of other families with the same pattern, Haiku 4.5 Global included", () => {
    for (const name of ["OpenAI GPT 6.1 Sol (Global)", "OpenAI GPT 6.1 Sol (US)", "OpenAI GPT 6.1 Sol (us-east-1)"]) {
      const nearest = nearestSamePattern(name, (other) => other.includes("GPT 6.1 Sol"));
      expect(nearest.delta, `${name} vs ${nearest.other} (${nearest.theme})`).toBeGreaterThanOrEqual(MIN_DELTA_E);
    }
    for (const theme of THEMES) {
      expect(distance("OpenAI GPT 6.1 Sol (Global)", "Bedrock Claude Haiku 4.5 (Global)", theme)).toBeGreaterThanOrEqual(MIN_DELTA_E);
    }
  });

  test("GPT 6.1 Sol channels read as one family (one hue, three lightness steps)", () => {
    const hues = ["(Global)", "(US)", "(us-east-1)"].map((channel) => {
      const [, a, b] = hexToLab(MODEL_COLORS[`OpenAI GPT 6.1 Sol ${channel}`]);
      return Math.atan2(b, a) * 180 / Math.PI;
    });
    expect(Math.max(...hues) - Math.min(...hues)).toBeLessThan(10);
  });
});
