// Helpers for creating things with unique names.

import type { Agent, AgentNode, Edge, Position } from "../types";

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
