import { describe, expect, it } from "vitest";
import { applyOp, blankAgent, describeOp, newEdge, newNode, uniqueName } from "./operations";
import type { Agent } from "./types";

const agent = (): Agent => blankAgent("Test");

describe("applyOp", () => {
  it("does not mutate its input", () => {
    const a = agent();
    const before = JSON.stringify(a);
    applyOp(a, { type: "updateNode", node: "greeting", patch: { end: true } });
    applyOp(a, { type: "renameNode", from: "greeting", to: "hello" });
    applyOp(a, { type: "deleteNode", node: "goodbye" });
    expect(JSON.stringify(a)).toBe(before);
  });

  it("rename rewrites the start node and every edge target", () => {
    const a = applyOp(agent(), { type: "renameNode", from: "goodbye", to: "farewell" });
    expect(a.nodes.map((n) => n.name)).toEqual(["greeting", "farewell"]);
    expect(a.nodes[0].edges![0].target).toBe("farewell");

    const b = applyOp(a, { type: "renameNode", from: "greeting", to: "hello" });
    expect(b.initial_node).toBe("hello");
  });

  it("rename refuses a name that is taken", () => {
    expect(() => applyOp(agent(), { type: "renameNode", from: "greeting", to: "goodbye" })).toThrow(
      /already exists/,
    );
  });

  it("delete keeps incoming transitions but clears their target", () => {
    const a = applyOp(agent(), { type: "deleteNode", node: "goodbye" });
    expect(a.nodes).toHaveLength(1);
    expect(a.nodes[0].edges![0]).toMatchObject({ function: "finish", target: "" });
  });

  it("deleting the start node clears initial_node", () => {
    expect(applyOp(agent(), { type: "deleteNode", node: "greeting" }).initial_node).toBe("");
  });

  it("adds, edits and deletes transitions by index", () => {
    let a = agent();
    a = applyOp(a, { type: "addEdge", node: "greeting", edge: newEdge(a.nodes[0], "greeting") });
    expect(a.nodes[0].edges!.map((e) => e.function)).toEqual(["finish", "go_to_greeting"]);

    a = applyOp(a, { type: "updateEdge", node: "greeting", index: 1, patch: { description: "loop" } });
    expect(a.nodes[0].edges![1].description).toBe("loop");

    a = applyOp(a, { type: "deleteEdge", node: "greeting", index: 0 });
    expect(a.nodes[0].edges!.map((e) => e.function)).toEqual(["go_to_greeting"]);
  });

  it("throws on ops that don't fit the agent", () => {
    expect(() => applyOp(agent(), { type: "updateNode", node: "nope", patch: {} })).toThrow();
    expect(() => applyOp(agent(), { type: "updateEdge", node: "greeting", index: 5, patch: {} })).toThrow();
    expect(() => applyOp(agent(), { type: "addNode", node: { name: "greeting", task_messages: [] } })).toThrow();
  });

  it("moves only the nodes it names", () => {
    const a = applyOp(agent(), { type: "moveNodes", positions: { goodbye: { x: 1, y: 2 } } });
    expect(a.nodes[0].position).toEqual({ x: 0, y: 0 });
    expect(a.nodes[1].position).toEqual({ x: 1, y: 2 });
  });
});

describe("helpers", () => {
  it("uniqueName appends a counter", () => {
    expect(uniqueName("a", [])).toBe("a");
    expect(uniqueName("a", ["a", "a_2"])).toBe("a_3");
  });

  it("newNode never collides", () => {
    let a = agent();
    a = applyOp(a, { type: "addNode", node: newNode(a) });
    a = applyOp(a, { type: "addNode", node: newNode(a) });
    expect(a.nodes.map((n) => n.name)).toEqual(["greeting", "goodbye", "new_node", "new_node_2"]);
  });

  it("describeOp gives readable labels", () => {
    expect(describeOp({ type: "renameNode", from: "a", to: "b" })).toBe("Renamed node 'a' to 'b'");
  });
});
