// Automatic left-to-right layout of the node graph, with ELK's layered algorithm.
//
// Each transition leaves its card from its own row, so every row is given to ELK
// as a separate connection point (port) at the exact height its handle is drawn.
// That lets ELK order nodes to minimise crossings between the real edges, which a
// layout treating each card as one point can't do. ELK (~1.5 MB) is loaded the
// first time a layout is needed.

import type { ElkNode } from "elkjs/lib/elk-api";
import type { Agent, AgentNode, Position } from "./types";

export const NODE_WIDTH = 280;

// Card geometry, matching AgentNodeCard: a header, up to three lines of
// instructions, then one 28px row per transition and an "add" row.
const HEADER = 37;
const TEXT_PADDING = 16;
const LINE = 19.5;
const CHARS_PER_LINE = 48;
const ROWS_TOP = 5; // border + padding above the first row
const ROW = 28;
const TARGET_HANDLE_Y = 22;

function textLines(node: AgentNode): number {
  const text = node.task_messages.map((m) => m.content).join(" ").trim();
  return Math.min(3, Math.max(1, Math.ceil(text.length / CHARS_PER_LINE)));
}

/** Estimated rendered height of a node's card. */
export function nodeHeight(node: AgentNode): number {
  const body = HEADER + TEXT_PADDING + LINE * textLines(node);
  return Math.round(body + (node.end ? 2 : ROWS_TOP + ROW * ((node.edges?.length ?? 0) + 1) + 6));
}

/** Where transition `index`'s handle sits, from the top of the card. */
function rowCenter(node: AgentNode, index: number): number {
  return Math.round(HEADER + TEXT_PADDING + LINE * textLines(node) + ROWS_TOP + ROW * index + ROW / 2);
}

type ElkInstance = { layout: (graph: ElkNode) => Promise<ElkNode> };
let elk: Promise<ElkInstance> | null = null;
const loadElk = () =>
  (elk ??= import("elkjs/lib/elk.bundled.js").then((m) => new m.default() as unknown as ElkInstance));

/**
 * Top-left positions for every node. `sizes` (e.g. measured on the canvas)
 * replaces the estimated size of any node it lists.
 */
export async function autoLayout(
  agent: Agent,
  sizes: Record<string, { width?: number; height?: number }> = {},
): Promise<Record<string, Position>> {
  const nodes = agent.nodes;
  const names = new Set(nodes.map((n) => n.name));
  const graph: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": "50",
      "elk.layered.spacing.nodeNodeBetweenLayers": "110",
      "elk.layered.spacing.edgeNodeBetweenLayers": "30",
      // Keep the agent's own order as a tie-breaker, so layouts are stable.
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: nodes.map((node) => {
      const width = sizes[node.name]?.width ?? NODE_WIDTH;
      const height = sizes[node.name]?.height ?? nodeHeight(node);
      return {
        id: node.name,
        width,
        height,
        layoutOptions: { "elk.portConstraints": "FIXED_POS" },
        ports: [
          { id: `${node.name}::in`, x: 0, y: TARGET_HANDLE_Y, width: 1, height: 1, layoutOptions: { "elk.port.side": "WEST" } },
          ...(node.edges ?? []).map((_, i) => ({
            id: `${node.name}::${i}`,
            x: width,
            y: rowCenter(node, i),
            width: 1,
            height: 1,
            layoutOptions: { "elk.port.side": "EAST" },
          })),
        ],
      };
    }),
    edges: agent.nodes.flatMap((node) =>
      (node.edges ?? []).flatMap((edge, i) =>
        names.has(edge.target)
          ? [{ id: `${node.name}::${i}->${edge.target}`, sources: [`${node.name}::${i}`], targets: [`${edge.target}::in`] }]
          : [],
      ),
    ),
  };

  const laid = await (await loadElk()).layout(graph);
  const out: Record<string, Position> = {};
  for (const child of laid.children ?? []) out[child.id] = { x: Math.round(child.x ?? 0), y: Math.round(child.y ?? 0) };
  return out;
}

/** True when no node has a position yet, e.g. an agent written by hand or by ProsperO. */
export function needsLayout(agent: Agent): boolean {
  return agent.nodes.length > 0 && agent.nodes.every((n) => !n.position);
}

/** Positions for nodes that lack one, without moving the others: a row below them. */
export function placeBelow(agent: Agent): Record<string, Position> {
  const placed = agent.nodes.filter((n) => n.position);
  const bottom = placed.length ? Math.max(...placed.map((n) => n.position!.y + nodeHeight(n))) : 0;
  const out: Record<string, Position> = {};
  agent.nodes
    .filter((n) => !n.position)
    .forEach((n, i) => {
      out[n.name] = { x: i * (NODE_WIDTH + 40), y: bottom + 80 };
    });
  return out;
}
