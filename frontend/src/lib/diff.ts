// What changed between two versions of an agent: used to highlight a ProsperO
// proposal against the draft it started from.

import type { Agent, AgentNode, Edge } from "./types";

export type Change = "added" | "changed" | "removed";

export interface AgentDiff {
  /** By node name. Removed nodes exist only in `base`. */
  nodes: Record<string, Change>;
  /** By edge id `${node}#${index}` in the new agent (added or changed only). */
  edges: Record<string, Change>;
  /** Top-level fields that differ: name, persona, voice_id, model, initial_node. */
  agentFields: string[];
}

// Canvas positions aren't part of what an agent does, so moves aren't changes.
const content = ({ position: _position, ...rest }: AgentNode) => JSON.stringify(rest);
const same = (a: Edge, b: Edge) => JSON.stringify(a) === JSON.stringify(b);

export function diffAgents(base: Agent, next: Agent): AgentDiff {
  const diff: AgentDiff = { nodes: {}, edges: {}, agentFields: [] };
  const before = new Map(base.nodes.map((n) => [n.name, n]));
  const after = new Set(next.nodes.map((n) => n.name));

  for (const node of next.nodes) {
    const old = before.get(node.name);
    if (!old) diff.nodes[node.name] = "added";
    else if (content(old) !== content(node)) diff.nodes[node.name] = "changed";

    // Transitions are matched by function name, which is unique within a node.
    const oldEdges = new Map((old?.edges ?? []).map((e) => [e.function, e]));
    (node.edges ?? []).forEach((edge, index) => {
      const previous = oldEdges.get(edge.function);
      if (!previous) diff.edges[`${node.name}#${index}`] = "added";
      else if (!same(previous, edge)) diff.edges[`${node.name}#${index}`] = "changed";
    });
  }
  for (const node of base.nodes) if (!after.has(node.name)) diff.nodes[node.name] = "removed";

  for (const field of ["name", "persona", "voice_id", "model", "initial_node"] as const) {
    if (base[field] !== next[field]) diff.agentFields.push(field);
  }
  return diff;
}

export function changeCount(diff: AgentDiff): number {
  return Object.keys(diff.nodes).length + Object.keys(diff.edges).length + diff.agentFields.length;
}
