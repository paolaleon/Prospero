// Operations on nodes.

import type { AgentNode, Position } from "../types";
import { findNode, mapNode, requireFreeName, type OpDefs } from "./registry";

type NodeFields = Partial<Omit<AgentNode, "name" | "edges">>;

export type NodeOp =
  | { type: "addNode"; node: AgentNode }
  | { type: "updateNode"; node: string; patch: NodeFields }
  | { type: "renameNode"; from: string; to: string }
  | { type: "deleteNode"; node: string }
  | { type: "moveNodes"; positions: Record<string, Position> };

export const nodeOps: OpDefs<NodeOp> = {
  addNode: {
    required: ["node"],
    apply: (agent, op) => {
      requireFreeName(agent, op.node.name);
      return { ...agent, nodes: [...agent.nodes, op.node] };
    },
    describe: (op) => `Added node '${op.node.name}'`,
  },

  updateNode: {
    required: ["node", "patch"],
    apply: (agent, op) => mapNode(agent, op.node, (n) => ({ ...n, ...op.patch })),
    describe: (op) => `Edited node '${op.node}'`,
  },

  renameNode: {
    required: ["from", "to"],
    apply: (agent, op) => {
      if (op.from === op.to) return agent;
      requireFreeName(agent, op.to);
      // A rename rewrites every reference, so the graph stays connected.
      const renamed = mapNode(agent, op.from, (n) => ({ ...n, name: op.to }));
      return {
        ...renamed,
        initial_node: agent.initial_node === op.from ? op.to : agent.initial_node,
        nodes: renamed.nodes.map((n) =>
          n.edges ? { ...n, edges: n.edges.map((e) => (e.target === op.from ? { ...e, target: op.to } : e)) } : n,
        ),
      };
    },
    describe: (op) => `Renamed node '${op.from}' to '${op.to}'`,
  },

  deleteNode: {
    required: ["node"],
    apply: (agent, op) => {
      findNode(agent, op.node);
      // Transitions into the deleted node keep their configuration but lose their
      // target, so validation points at each one instead of it silently vanishing.
      return {
        ...agent,
        initial_node: agent.initial_node === op.node ? "" : agent.initial_node,
        nodes: agent.nodes
          .filter((n) => n.name !== op.node)
          .map((n) =>
            n.edges ? { ...n, edges: n.edges.map((e) => (e.target === op.node ? { ...e, target: "" } : e)) } : n,
          ),
      };
    },
    describe: (op) => `Deleted node '${op.node}'`,
  },

  moveNodes: {
    required: ["positions"],
    apply: (agent, op) => ({
      ...agent,
      nodes: agent.nodes.map((n) => (op.positions[n.name] ? { ...n, position: op.positions[n.name] } : n)),
    }),
    describe: () => "Moved nodes",
  },
};
