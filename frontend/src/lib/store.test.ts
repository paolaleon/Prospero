import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Op } from "./operations";
import type { Agent } from "./types";

const saveAgent = vi.fn();
vi.mock("./api", () => ({
  api: { validate: vi.fn(async () => ({ issues: [] })), saveAgent: (...args: unknown[]) => saveAgent(...args) },
  ApiError: class extends Error {},
}));

const { useEditor } = await import("./store");
const { blankAgent } = await import("./operations");

const draft = (): Agent => blankAgent("Clinic");
const state = () => useEditor.getState();
const intake: Op = { type: "addNode", node: { name: "intake", task_messages: [] } };

beforeEach(() => {
  saveAgent.mockReset();
  saveAgent.mockImplementation(async (_id: string, agent: Agent) => ({ version: 2, agent, issues: [] }));
  useEditor.setState({
    agentId: "clinic", version: 1, draft: draft(), saved: draft(), proposal: null,
    past: [], future: [], selection: null, error: null,
  });
});

describe("proposals", () => {
  it("apply ProsperO's edits to a copy, leaving the draft alone", () => {
    state().startProposal();
    state().proposeEdit(intake, "Added node 'intake'");

    expect(state().proposal!.agent.nodes.map((n) => n.name)).toEqual(["greeting", "goodbye", "intake"]);
    expect(state().proposal!.edits).toEqual([{ op: intake, label: "Added node 'intake'" }]);
    expect(state().draft).toEqual(draft());
  });

  it("pause editing and undo while open", () => {
    state().dispatch({ type: "updateAgent", patch: { name: "Before" } });
    state().startProposal();

    state().dispatch({ type: "updateAgent", patch: { name: "During" } });
    expect(state().draft!.name).toBe("Before");
    expect(state().error).toMatch(/Accept or reject/);

    state().undo();
    expect(state().draft!.name).toBe("Before");
  });

  it("are discarded by reject", () => {
    state().startProposal();
    state().proposeEdit(intake, "Added node 'intake'");
    state().rejectProposal();
    expect(state().proposal).toBeNull();
    expect(state().draft).toEqual(draft());
  });

  it("keep building across follow-up turns", () => {
    state().startProposal();
    state().proposeEdit(intake, "Added node 'intake'");
    state().settleProposal({ status: "ready", summary: "Added intake.", issues: [] });

    state().startProposal();
    expect(state().proposal!.status).toBe("building");
    expect(state().proposal!.edits).toHaveLength(1);
  });

  it("are applied as one undoable step and saved as a copilot version on accept", async () => {
    state().startProposal();
    state().proposeEdit(intake, "Added node 'intake'");
    state().settleProposal({ status: "ready", summary: "Added an intake step.", issues: [] });

    expect(await state().acceptProposal()).toBe(true);

    const accepted = state().draft!;
    expect(accepted.nodes.map((n) => n.name)).toEqual(["greeting", "goodbye", "intake"]);
    expect(accepted.nodes[2].position).toBeDefined(); // laid out where it was shown
    expect(state().proposal).toBeNull();
    expect(state().past.at(-1)!.label).toBe("ProsperO: Added an intake step.");
    expect(saveAgent).toHaveBeenCalledWith("clinic", accepted, {
      message: "ProsperO: Added an intake step.", source: "copilot", baseVersion: 1,
    });
    expect(state().version).toBe(2);

    state().undo();
    expect(state().draft).toEqual(draft());
  });

  it("report an edit the browser can't apply instead of hiding it", () => {
    state().startProposal();
    state().proposeEdit({ type: "deleteNode", node: "nope" }, "Deleted node 'nope'");
    expect(state().proposal!.status).toBe("error");
    expect(state().proposal!.error).toBe("Couldn't show an edit: No node named 'nope'.");
  });
});
