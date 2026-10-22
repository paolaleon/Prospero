// Automatic left-to-right layout of the node graph (dagre).

import dagre from "@dagrejs/dagre";
import type { Agent, AgentNode, Position } from "./types";

export const NODE_WIDTH = 280;

/** Rough rendered height of a node card, so dagre leaves enough room. */
export function nodeHeight(node: AgentNode): number {
  return 118 + 30 * ((node.edges?.length ?? 0) + (node.end ? 0 : 1));
}

/** Top-left positions for every node, laid out from the start node outwards. */
export function autoLayout(agent: Agent): Record<string, Position> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 110, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));

  const names = new Set(agent.nodes.map((n) => n.name));
  for (const node of agent.nodes) {
    g.setNode(node.name, { width: NODE_WIDTH, height: nodeHeight(node) });
  }
  for (const node of agent.nodes) {
    for (const edge of node.edges ?? []) {
      if (names.has(edge.target) && edge.target !== node.name) g.setEdge(node.name, edge.target);
    }
  }
  dagre.layout(g);

  const out: Record<string, Position> = {};
  for (const node of agent.nodes) {
    const { x, y } = g.node(node.name);
    out[node.name] = { x: Math.round(x - NODE_WIDTH / 2), y: Math.round(y - nodeHeight(node) / 2) };
  }
  return out;
}

/** Positions only for the nodes that don't have one yet (e.g. agents written by hand). */
export function missingPositions(agent: Agent): Record<string, Position> {
  const missing = agent.nodes.filter((n) => !n.position);
  if (missing.length === 0) return {};
  const laid = autoLayout(agent);
  if (missing.length === agent.nodes.length) return laid;

  // Keep existing nodes where they are; put new ones below everything else.
  const bottom = Math.max(...agent.nodes.filter((n) => n.position).map((n) => n.position!.y + nodeHeight(n)));
  const out: Record<string, Position> = {};
  missing.forEach((n, i) => {
    out[n.name] = { x: i * (NODE_WIDTH + 40), y: bottom + 80 };
  });
  return out;
}
