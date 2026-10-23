// Operations on transitions (edges), addressed by their node and position.

import type { Agent, Edge } from "../types";
import { findNode, mapNode, OperationError, type OpDefs } from "./registry";

export type EdgeOp =
  | { type: "addEdge"; node: string; edge: Edge }
  | { type: "updateEdge"; node: string; index: number; patch: Partial<Edge> }
  | { type: "deleteEdge"; node: string; index: number };

/** Replace a node's transitions, after checking `index` points at one of them. */
function withEdge(agent: Agent, node: string, index: number, fn: (edges: Edge[]) => Edge[]): Agent {
  const edges = findNode(agent, node).edges ?? [];
  if (!Number.isInteger(index) || index < 0 || index >= edges.length) {
    throw new OperationError(`Node '${node}' has no transition #${index + 1}.`);
  }
  return mapNode(agent, node, (n) => ({ ...n, edges: fn(edges) }));
}

export const edgeOps: OpDefs<EdgeOp> = {
  addEdge: {
    required: ["node", "edge"],
    apply: (agent, op) => mapNode(agent, op.node, (n) => ({ ...n, edges: [...(n.edges ?? []), op.edge] })),
    describe: (op) => `Added transition '${op.edge.function}' from '${op.node}'`,
  },

  updateEdge: {
    required: ["node", "index", "patch"],
    apply: (agent, op) =>
      withEdge(agent, op.node, op.index, (edges) => edges.map((e, i) => (i === op.index ? { ...e, ...op.patch } : e))),
    describe: (op) => `Edited a transition of '${op.node}'`,
  },

  deleteEdge: {
    required: ["node", "index"],
    apply: (agent, op) => withEdge(agent, op.node, op.index, (edges) => edges.filter((_, i) => i !== op.index)),
    describe: (op) => `Deleted a transition of '${op.node}'`,
  },
};
