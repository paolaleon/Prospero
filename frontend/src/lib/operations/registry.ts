// Operation registry types and shared helpers.
//
// Each area module (agent.ts, node.ts, edge.ts) defines its operations as one
// entry each: the fields it requires, how it's applied and how it's labelled.
// index.ts assembles them, and the `OpDefs` mapped type makes the build fail if
// any operation is missing an entry. The Python side (backend/agent_builder/
// operations/) mirrors this, and both run shared/operation-cases.json.

import type { Agent, AgentNode } from "../types";

export class OperationError extends Error {}

export interface OpDef<O extends { type: string }> {
  /** Fields that must be present; checked at runtime for operations arriving as JSON. */
  required: readonly Exclude<keyof O, "type">[];
  /** Pure: returns a new agent; throws OperationError if the op doesn't fit. */
  apply: (agent: Agent, op: O) => Agent;
  /** A short, human-readable label, for undo/redo and for reviewing changes. */
  describe: (op: O) => string;
}

/** One entry per operation type in the union `U`; a missing one is a type error. */
export type OpDefs<U extends { type: string }> = { [K in U["type"]]: OpDef<Extract<U, { type: K }>> };

export function findNode(agent: Agent, name: string): AgentNode {
  const node = agent.nodes.find((n) => n.name === name);
  if (!node) throw new OperationError(`No node named '${name}'.`);
  return node;
}

export function requireFreeName(agent: Agent, name: string): void {
  if (agent.nodes.some((n) => n.name === name)) throw new OperationError(`A node named '${name}' already exists.`);
}

export function mapNode(agent: Agent, name: string, fn: (n: AgentNode) => AgentNode): Agent {
  findNode(agent, name);
  return { ...agent, nodes: agent.nodes.map((n) => (n.name === name ? fn(n) : n)) };
}
