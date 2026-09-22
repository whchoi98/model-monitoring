import { describe, expect, test } from "vitest";
import { projectMonthlyCost } from "./costProjection";

describe("projectMonthlyCost", () => {
  test.each([
    { window: "1h", total_cost_usd: 2 },
    { window: "6h", total_cost_usd: 12 },
    { window: "24h", total_cost_usd: 48 },
    { window: "7d", total_cost_usd: 336 },
    { window: "30d", total_cost_usd: 1440 },
  ])("uses the loaded $window summary to project a $2/hour rate", (summary) => {
    expect(projectMonthlyCost(summary)).toBe(1440);
  });

  test("has no estimate before a summary arrives", () => {
    expect(projectMonthlyCost(null)).toBeNull();
  });

  test("preserves a successful zero-cost result", () => {
    expect(projectMonthlyCost({ window: "7d", total_cost_usd: 0 })).toBe(0);
  });

  test("does not divide by a zero-length window", () => {
    expect(projectMonthlyCost({ window: "0h", total_cost_usd: 24 })).toBeNull();
  });
});
