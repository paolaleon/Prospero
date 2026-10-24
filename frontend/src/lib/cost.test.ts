import { describe, expect, it } from "vitest";
import { averageCost, usd } from "./cost";
import type { CallSummary } from "./types";

const call = (version: number | null, total: number | null): CallSummary => ({
  id: Math.random().toString(),
  source: "test",
  agent_id: "a",
  agent_name: "A",
  agent_version: version,
  started_at: "",
  ended_at: null,
  ended_by: null,
  outcome: "completed",
  final_node: null,
  turns: 0,
  model: null,
  usage: total === null ? null : {},
  cost: total === null ? null : { total, complete: true },
});

describe("averageCost", () => {
  it("averages only calls with recorded usage, overall and by version", () => {
    const result = averageCost([call(9, 0.02), call(9, 0.04), call(null, 0.06), call(8, null)])!;
    expect(result.calls).toBe(3);
    expect(result.average).toBeCloseTo(0.04);
    expect(result.groups).toEqual([
      { label: "v9", average: expect.closeTo(0.03), calls: 2 },
      { label: "drafts", average: expect.closeTo(0.06), calls: 1 },
    ]);
  });

  it("has nothing to say without usage", () => {
    expect(averageCost([call(1, null)])).toBeNull();
  });
});

describe("usd", () => {
  it("shows cents with three significant digits", () => {
    expect(usd(0.012345)).toBe("$0.0123");
    expect(usd(0.5)).toBe("$0.5");
    expect(usd(2.345)).toBe("$2.35");
    expect(usd(0)).toBe("$0");
  });
});
