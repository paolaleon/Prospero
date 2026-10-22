// Operations on the agent as a whole.

import type { Agent } from "../types";
import { findNode, type OpDefs } from "./registry";

type AgentFields = Partial<Pick<Agent, "name" | "persona" | "voice_id" | "model">>;

export type AgentOp =
  | { type: "updateAgent"; patch: AgentFields }
  | { type: "setInitialNode"; node: string }
  | { type: "replaceAgent"; agent: Agent; reason: string };

export const agentOps: OpDefs<AgentOp> = {
  updateAgent: {
    required: ["patch"],
    apply: (agent, op) => ({ ...agent, ...op.patch }),
    describe: (op) => `Edited agent ${Object.keys(op.patch).join(", ")}`,
  },

  setInitialNode: {
    required: ["node"],
    apply: (agent, op) => {
      findNode(agent, op.node);
      return { ...agent, initial_node: op.node };
    },
    describe: (op) => `Set start node to '${op.node}'`,
  },

  replaceAgent: {
    required: ["agent", "reason"],
    apply: (_agent, op) => op.agent,
    describe: (op) => op.reason,
  },
};
