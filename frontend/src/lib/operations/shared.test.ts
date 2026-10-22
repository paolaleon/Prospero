// Runs shared/operation-cases.json, the same cases backend/tests/test_operations.py
// runs, so the TypeScript and Python operations must agree.

import { describe, expect, it } from "vitest";
import shared from "../../../../shared/operation-cases.json";
import type { Agent } from "../types";
import { applyOp, describeOp, OperationError, type Op } from ".";

interface Case {
  name: string;
  agent: string;
  op: Op;
  label?: string;
  same?: boolean;
  error?: string;
  expect?: Record<string, unknown>;
}

const fixtures = shared.fixtures as unknown as Record<string, Agent>;
const cases = shared.cases as unknown as Case[];
const MISSING = Symbol("missing");

function get(value: unknown, path: string): unknown {
  for (const part of path.split(".")) {
    if (Array.isArray(value) && /^\d+$/.test(part)) value = Number(part) < value.length ? value[Number(part)] : MISSING;
    else if (value && typeof value === "object") value = part in value ? (value as Record<string, unknown>)[part] : MISSING;
    else return MISSING;
    if (value === MISSING) return MISSING;
  }
  return value;
}

describe("shared operation cases", () => {
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_, c) => {
    const agent = structuredClone(fixtures[c.agent]);
    const before = structuredClone(agent);

    if (c.error !== undefined) {
      let thrown: unknown;
      try {
        applyOp(agent, c.op);
      } catch (e) {
        thrown = e;
      }
      expect(thrown).toBeInstanceOf(OperationError);
      expect((thrown as Error).message).toBe(c.error);
    } else {
      const result = applyOp(agent, c.op);
      if (c.same) expect(result).toEqual(before);
      for (const [path, expected] of Object.entries(c.expect ?? {})) {
        const actual = get(result, path);
        if (JSON.stringify(expected) === '{"$absent":true}') expect(actual, path).toBe(MISSING);
        else expect(actual, path).toEqual(expected);
      }
      if (c.label !== undefined) expect(describeOp(c.op)).toBe(c.label);
    }

    expect(agent).toEqual(before); // the input agent must not change
  });
});
