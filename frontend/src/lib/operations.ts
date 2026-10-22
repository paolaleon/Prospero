// Agent operations — every change to an agent is one of these.
//
// Edits from the canvas, the inspector, JSON import and undo/redo all go through
// `applyOp`, and a copilot will produce the same operations. Keeping them as
// plain, serialisable data with a readable label is what makes a batch of
// changes reviewable ("Renamed node 'a' to 'b'", "Edited transition ..."), no
// matter who made it.

import type { Agent, AgentNode, Edge, Position } from "./types";

type AgentFields = Partial<Pick<Agent, "name" | "persona" | "voice_id" | "model">>;
type NodeFields = Partial<Omit<AgentNode, "name" | "edges">>;

export type Op =
  | { type: "updateAgent"; patch: AgentFields }
  | { type: "setInitialNode"; node: string }
  | { type: "addNode"; node: AgentNode }
  | { type: "updateNode"; node: string; patch: NodeFields }
  | { type: "renameNode"; from: string; to: string }
  | { type: "deleteNode"; node: string }
  | { type: "moveNodes"; positions: Record<string, Position> }
  | { type: "addEdge"; node: string; edge: Edge }
  | { type: "updateEdge"; node: string; index: number; patch: Partial<Edge> }
  | { type: "deleteEdge"; node: string; index: number }
  | { type: "replaceAgent"; agent: Agent; reason: string };

function mapNode(agent: Agent, name: string, fn: (n: AgentNode) => AgentNode): Agent {
  if (!agent.nodes.some((n) => n.name === name)) throw new Error(`No node named '${name}'.`);
  return { ...agent, nodes: agent.nodes.map((n) => (n.name === name ? fn(n) : n)) };
}

function mapEdges(agent: Agent, name: string, fn: (edges: Edge[]) => Edge[]): Agent {
  return mapNode(agent, name, (n) => ({ ...n, edges: fn(n.edges ?? []) }));
}

/** Pure: returns a new agent with `op` applied. Throws if the op doesn't fit the agent. */
export function applyOp(agent: Agent, op: Op): Agent {
  switch (op.type) {
    case "updateAgent":
      return { ...agent, ...op.patch };

    case "setInitialNode":
      return { ...agent, initial_node: op.node };

    case "addNode":
      if (agent.nodes.some((n) => n.name === op.node.name)) {
        throw new Error(`A node named '${op.node.name}' already exists.`);
      }
      return { ...agent, nodes: [...agent.nodes, op.node] };

    case "updateNode":
      return mapNode(agent, op.node, (n) => ({ ...n, ...op.patch }));

    case "renameNode": {
      if (op.from === op.to) return agent;
      if (agent.nodes.some((n) => n.name === op.to)) {
        throw new Error(`A node named '${op.to}' already exists.`);
      }
      // A rename rewrites every reference, so the graph stays connected.
      const renamed = mapNode(agent, op.from, (n) => ({ ...n, name: op.to }));
      return {
        ...renamed,
        initial_node: agent.initial_node === op.from ? op.to : agent.initial_node,
        nodes: renamed.nodes.map((n) => ({
          ...n,
          edges: n.edges?.map((e) => (e.target === op.from ? { ...e, target: op.to } : e)),
        })),
      };
    }

    case "deleteNode": {
      mapNode(agent, op.node, (n) => n); // throws if missing
      // Transitions into the deleted node keep their configuration but lose their
      // target, so validation points at each one instead of it silently vanishing.
      return {
        ...agent,
        initial_node: agent.initial_node === op.node ? "" : agent.initial_node,
        nodes: agent.nodes
          .filter((n) => n.name !== op.node)
          .map((n) => ({
            ...n,
            edges: n.edges?.map((e) => (e.target === op.node ? { ...e, target: "" } : e)),
          })),
      };
    }

    case "moveNodes":
      return {
        ...agent,
        nodes: agent.nodes.map((n) =>
          op.positions[n.name] ? { ...n, position: op.positions[n.name] } : n,
        ),
      };

    case "addEdge":
      return mapEdges(agent, op.node, (edges) => [...edges, op.edge]);

    case "updateEdge":
      return mapEdges(agent, op.node, (edges) => {
        if (!edges[op.index]) throw new Error(`Node '${op.node}' has no transition #${op.index + 1}.`);
        return edges.map((e, i) => (i === op.index ? { ...e, ...op.patch } : e));
      });

    case "deleteEdge":
      return mapEdges(agent, op.node, (edges) => edges.filter((_, i) => i !== op.index));

    case "replaceAgent":
      return op.agent;
  }
}

/** A short, human-readable label, for undo/redo and for reviewing changes. */
export function describeOp(op: Op): string {
  switch (op.type) {
    case "updateAgent":
      return `Edited agent ${Object.keys(op.patch).join(", ")}`;
    case "setInitialNode":
      return `Set start node to '${op.node}'`;
    case "addNode":
      return `Added node '${op.node.name}'`;
    case "updateNode":
      return `Edited node '${op.node}'`;
    case "renameNode":
      return `Renamed node '${op.from}' to '${op.to}'`;
    case "deleteNode":
      return `Deleted node '${op.node}'`;
    case "moveNodes":
      return "Moved nodes";
    case "addEdge":
      return `Added transition '${op.edge.function}' from '${op.node}'`;
    case "updateEdge":
      return `Edited a transition of '${op.node}'`;
    case "deleteEdge":
      return `Deleted a transition of '${op.node}'`;
    case "replaceAgent":
      return op.reason;
  }
}

// ---- helpers for creating things with unique names ----------------------------
export function uniqueName(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  let n = 2;
  while (used.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}

export function newNode(agent: Agent, position?: Position): AgentNode {
  return {
    name: uniqueName("new_node", agent.nodes.map((n) => n.name)),
    task_messages: [{ role: "developer", content: "" }],
    edges: [],
    ...(position ? { position } : {}),
  };
}

export function newEdge(node: AgentNode, target = ""): Edge {
  return {
    function: uniqueName(target ? `go_to_${target}` : "next_step", (node.edges ?? []).map((e) => e.function)),
    description: "",
    target,
    properties: {},
    required: [],
  };
}

export function blankAgent(name = "New agent"): Agent {
  return {
    name,
    initial_node: "greeting",
    persona:
      "You are a friendly voice assistant. Your responses are spoken aloud, so avoid emojis, lists, or anything that can't be read out. Keep replies to one or two short sentences.",
    nodes: [
      {
        name: "greeting",
        task_messages: [{ role: "developer", content: "Greet the caller and ask how you can help." }],
        edges: [
          {
            function: "finish",
            description: "Call once the caller's request has been handled.",
            target: "goodbye",
            properties: {},
            required: [],
          },
        ],
        position: { x: 0, y: 0 },
      },
      {
        name: "goodbye",
        task_messages: [{ role: "developer", content: "Thank the caller and say goodbye." }],
        end: true,
        position: { x: 380, y: 0 },
      },
    ],
  };
}
