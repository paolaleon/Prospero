// Estimated call costs (AD-19): formatting, and averages over recorded calls.

import type { CallSummary } from "./types";

/** "$0.0123" below a dollar (calls cost cents), "$1.23" above. */
export function usd(value: number): string {
  if (value >= 1) return `$${value.toFixed(2)}`;
  if (value === 0) return "$0";
  return `$${value.toPrecision(3).replace(/0+$/, "")}`;
}

export function tokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export interface CostGroup {
  label: string; // "v9", or "drafts"
  average: number;
  calls: number;
}

/**
 * The average cost per call, over the calls whose usage was recorded, overall
 * and by version (unsaved drafts together). Calls without usage are left out
 * rather than guessed, so the average isn't skewed.
 */
export function averageCost(calls: CallSummary[]): { average: number; calls: number; groups: CostGroup[] } | null {
  const priced = calls.filter((c) => c.cost);
  if (!priced.length) return null;
  const sum = (cs: CallSummary[]) => cs.reduce((total, c) => total + c.cost!.total, 0);
  const byLabel = new Map<string, CallSummary[]>();
  for (const c of priced) {
    const label = c.agent_version ? `v${c.agent_version}` : "drafts";
    byLabel.set(label, [...(byLabel.get(label) ?? []), c]);
  }
  const groups = [...byLabel].map(([label, cs]) => ({ label, average: sum(cs) / cs.length, calls: cs.length }));
  return { average: sum(priced) / priced.length, calls: priced.length, groups };
}
