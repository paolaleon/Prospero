import { describe, expect, it } from "vitest";
import { autoLayout, needsLayout, nodeHeight, NODE_WIDTH, placeBelow } from "./layout";
import { blankAgent } from "./operations";
import type { Agent, AgentNode } from "./types";

const node = (name: string, targets: string[] = [], end = false): AgentNode => ({
  name,
  task_messages: [{ role: "developer", content: `Do the ${name} step.` }],
  edges: targets.map((target) => ({ function: `to_${target}`, description: "x", target })),
  end,
});

// A clinic-shaped graph: one start fanning out, paths merging, an emergency edge
// from several nodes, and a loop back to the start.
const clinic: Agent = {
  name: "Clinic",
  initial_node: "greet",
  nodes: [
    node("greet", ["emergency", "book", "cancel"]),
    node("book", ["emergency", "confirm"]),
    node("cancel", ["emergency", "confirm", "greet"]),
    node("confirm", [], true),
    node("emergency", [], true),
  ],
};

describe("autoLayout (ELK)", () => {
  it("places every node without overlaps", async () => {
    const pos = await autoLayout(clinic);
    expect(Object.keys(pos).sort()).toEqual(clinic.nodes.map((n) => n.name).sort());
    const boxes = clinic.nodes.map((n) => [pos[n.name].x, pos[n.name].y, pos[n.name].x + NODE_WIDTH, pos[n.name].y + nodeHeight(n)]);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const [a, b] = [boxes[i], boxes[j]];
        expect(a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3], `${clinic.nodes[i].name} overlaps ${clinic.nodes[j].name}`).toBe(false);
      }
  });

  it("flows left to right from the start node", async () => {
    const pos = await autoLayout(clinic);
    expect(pos.book.x).toBeGreaterThan(pos.greet.x);
    expect(pos.confirm.x).toBeGreaterThan(pos.book.x);
  });

  it("is deterministic and uses measured sizes when given", async () => {
    expect(await autoLayout(clinic)).toEqual(await autoLayout(clinic));
    // Taller cards (as measured on the canvas) must spread the layout out.
    const tall = await autoLayout(clinic, Object.fromEntries(clinic.nodes.map((n) => [n.name, { height: 500 }])));
    const normal = await autoLayout(clinic);
    const span = (pos: typeof normal) => Math.max(...Object.values(pos).map((p) => p.y)) - Math.min(...Object.values(pos).map((p) => p.y));
    expect(span(tall)).toBeGreaterThan(span(normal));
  });

  it("ignores transitions to nodes that don't exist", async () => {
    const broken: Agent = { ...clinic, nodes: [...clinic.nodes, node("orphan", ["nowhere"])] };
    expect(Object.keys(await autoLayout(broken))).toContain("orphan");
  });
});

describe("partial layouts", () => {
  it("lays out only agents with no positions at all", () => {
    expect(needsLayout(clinic)).toBe(true);
    expect(needsLayout(blankAgent())).toBe(false); // positioned
    expect(needsLayout({ name: "x", initial_node: "", nodes: [] })).toBe(false);
  });

  it("puts unpositioned nodes in a row below the others", () => {
    const agent = blankAgent();
    agent.nodes.push(node("intake"));
    const below = placeBelow(agent);
    expect(Object.keys(below)).toEqual(["intake"]);
    expect(below.intake.y).toBeGreaterThan(Math.max(...agent.nodes.slice(0, 2).map((n) => n.position!.y)));
  });
});
