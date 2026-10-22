import { describe, expect, it } from "vitest";
import { diffAgents } from "./diff";
import { blankAgent } from "./operations";
import type { Agent } from "./types";

const base = (): Agent => blankAgent("Clinic");

describe("diffAgents", () => {
  it("finds no changes between equal agents, ignoring positions", () => {
    const moved = base();
    moved.nodes[0].position = { x: 999, y: 999 };
    expect(diffAgents(base(), moved)).toEqual({ nodes: {}, edges: {}, agentFields: [] });
  });

  it("marks added, changed and removed nodes", () => {
    const next = base();
    next.nodes[0].task_messages = [{ role: "developer", content: "Different." }];
    next.nodes = next.nodes.filter((n) => n.name !== "goodbye");
    next.nodes.push({ name: "intake", task_messages: [] });
    expect(diffAgents(base(), next).nodes).toEqual({ greeting: "changed", intake: "added", goodbye: "removed" });
  });

  it("marks added and changed transitions by their position in the new agent", () => {
    const next = base();
    next.nodes[0].edges = [
      { function: "urgent", description: "Emergency.", target: "goodbye" },
      { ...next.nodes[0].edges![0], description: "Changed." },
    ];
    expect(diffAgents(base(), next).edges).toEqual({ "greeting#0": "added", "greeting#1": "changed" });
  });

  it("lists changed agent fields", () => {
    const next = { ...base(), persona: "New persona.", initial_node: "goodbye" };
    expect(diffAgents(base(), next).agentFields).toEqual(["persona", "initial_node"]);
  });

  it("treats every node of a new agent as added", () => {
    const empty: Agent = { name: "New", initial_node: "", nodes: [] };
    expect(diffAgents(empty, base()).nodes).toEqual({ greeting: "added", goodbye: "added" });
  });
});
