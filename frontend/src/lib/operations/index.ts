// Agent operations — every change to an agent is one of these.
//
// Edits from the canvas, the inspector, JSON import, undo/redo and ProsperO all go
// through `applyOp`. Keeping operations as plain, serialisable data with a
// readable label is what makes a batch of changes reviewable ("Renamed node 'a'
// to 'b'", "Edited transition ..."), no matter who made it.

import type { Agent } from "../types";
import { agentOps, type AgentOp } from "./agent";
import { edgeOps, type EdgeOp } from "./edge";
import { nodeOps, type NodeOp } from "./node";
import { OperationError, type OpDef, type OpDefs } from "./registry";

export type Op = AgentOp | NodeOp | EdgeOp;

// Leaving any operation out of this object is a type error.
const DEFINITIONS: OpDefs<Op> = { ...agentOps, ...nodeOps, ...edgeOps };

function definition(op: Op): OpDef<Op> {
  const def = (DEFINITIONS as Record<string, OpDef<Op> | undefined>)[op?.type];
  if (!def) throw new OperationError(`Unknown operation '${op?.type}'.`);
  for (const field of def.required) {
    if (!(field in op)) throw new OperationError(`Operation '${op.type}' is missing '${String(field)}'.`);
  }
  return def;
}

/** Pure: returns a new agent with `op` applied. Throws OperationError if the op doesn't fit. */
export function applyOp(agent: Agent, op: Op): Agent {
  return definition(op).apply(agent, op);
}

/** A short, human-readable label, for undo/redo and for reviewing changes. */
export function describeOp(op: Op): string {
  return definition(op).describe(op);
}

export { OperationError } from "./registry";
export { blankAgent, newEdge, newNode, uniqueName } from "./helpers";
