import { describe, expect, test } from "vitest";
import {
  badgeLabel, changedModelIds, changeKindLabel, formatLatency, hasFailure, reasonText, splitError, statusLabel,
  summarizeChanges, summarizeModel,
} from "./explorerVerify";
import type { ExplorerChange, ExplorerExample, ExplorerStatus } from "./types";

function example(status: ExplorerStatus | null, apiId: ExplorerExample["api_id"] = "converse"): ExplorerExample {
  return {
    api_id: apiId, api: "Converse API", label: "Python (boto3)", language: "python",
    description: { ko: "설명", en: "desc" }, code: { ko: "print(1)", en: "print(1)" }, code_sha: "x",
    result: status === null ? null : {
      status, latency_ms: 1200, attempts: 1, error_message: null, output_excerpt: "Hello!", run_id: 3,
      verified_at: "2026-11-05T18:02:00Z", stale_code: false,
    },
  };
}

function change(kind: ExplorerChange["kind"], modelId = "m1"): ExplorerChange {
  return { model_id: modelId, model_name: "M", api_id: "converse", api: "Converse API", before: "passed", after: "failed", kind };
}

describe("summarizeModel and badgeLabel — card verification badge", () => {
  test("all passed", () => {
    const summary = summarizeModel([example("passed"), example("passed"), example("passed")]);
    expect(summary).toEqual({ passed: 3, failed: 0, skipped: 0, total: 3, grade: "passed" });
    expect(badgeLabel(summary, "ko")).toBe("✓ 3/3 통과");
    expect(badgeLabel(summary, "en")).toBe("✓ 3/3 passed");
  });
  test("a failure wins over passes", () => {
    const summary = summarizeModel([example("passed"), example("failed"), example("passed")]);
    expect(summary.grade).toBe("failed");
    expect(badgeLabel(summary, "ko")).toBe("✗ 1/3 실패");
    expect(badgeLabel(summary, "en")).toBe("✗ 1/3 failed");
  });
  test("passes and skips name the skips", () => {
    const summary = summarizeModel([example("passed"), example("passed"), example("skipped")]);
    expect(badgeLabel(summary, "ko")).toBe("✓ 2/3 통과, 1 건너뜀");
    expect(badgeLabel(summary, "en")).toBe("✓ 2/3 passed, 1 skipped");
  });
  test("no result is not verified", () => {
    const summary = summarizeModel([example(null), example(null)]);
    expect(summary.grade).toBe("none");
    expect(badgeLabel(summary, "ko")).toBe("검증 전");
    expect(badgeLabel(summary, "en")).toBe("Not verified");
    expect(summarizeModel([]).grade).toBe("none");
  });
});

describe("labels", () => {
  test("statuses and the new cell", () => {
    expect(["passed", "failed", "skipped"].map((s) => statusLabel(s as ExplorerStatus, "ko"))).toEqual(["통과", "실패", "건너뜀"]);
    expect(statusLabel(null, "ko")).toBe("신규");
    expect(statusLabel(null, "en")).toBe("New");
  });
  test("change kinds", () => {
    expect(changeKindLabel("catalog", "ko")).toBe("신규");
    expect(changeKindLabel("example", "ko")).toBe("예제 변경");
    expect(changeKindLabel("measured", "ko")).toBe("실측");
    expect(changeKindLabel("example", "en")).toBe("Example changed");
  });
});

describe("changes and failures", () => {
  test("summarizeChanges counts each kind", () => {
    expect(summarizeChanges([change("catalog"), change("measured"), change("measured")]))
      .toEqual({ catalog: 1, example: 0, measured: 2 });
  });
  test("changedModelIds", () => {
    expect([...changedModelIds([change("measured", "a"), change("example", "b"), change("catalog", "a")])]).toEqual(["a", "b"]);
  });
  test("hasFailure", () => {
    expect(hasFailure([example("passed"), example("failed")])).toBe(true);
    expect(hasFailure([example("passed"), example("skipped"), example(null)])).toBe(false);
  });
});

describe("result texts", () => {
  test("splitError keeps the exception line apart from the stderr tail", () => {
    expect(splitError("KeyError: 'text'\nTraceback (most recent call last):\n  ...")).toEqual({
      head: "KeyError: 'text'", tail: "Traceback (most recent call last):\n  ..." });
    expect(splitError("출력 없음")).toEqual({ head: "출력 없음", tail: "" });
    expect(splitError(null)).toEqual({ head: "", tail: "" });
  });
  test("reasonText translates the backend messages and leaves exceptions", () => {
    expect(reasonText("출력 없음", "en")).toBe("No output");
    expect(reasonText("시간 초과 90초", "en")).toBe("Timed out after 90 s");
    expect(reasonText("자격 증명 미주입: OPENAI_1P_API_KEY", "en")).toBe("Credentials not injected: OPENAI_1P_API_KEY");
    expect(reasonText("알 수 없는 플레이스홀더", "en")).toBe("Unknown placeholder");
    expect(reasonText("런 시간 상한", "en")).toBe("Run time limit reached");
    expect(reasonText("KeyError: 'text'", "en")).toBe("KeyError: 'text'");
    expect(reasonText("시간 초과 90초", "ko")).toBe("시간 초과 90초");
  });
  test("formatLatency", () => {
    expect(formatLatency(1180, "ko")).toBe("1.2초");
    expect(formatLatency(1180, "en")).toBe("1.2 s");
    expect(formatLatency(null, "ko")).toBe("");
  });
});
