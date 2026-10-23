import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent } from "./types";

vi.mock("./api", () => ({
  API_URL: "http://backend",
  api: { validate: vi.fn(async () => ({ issues: [] })), saveAgent: vi.fn() },
  ApiError: class extends Error {},
}));

const { useCopilot } = await import("./copilot");
const { useEditor } = await import("./store");

const empty: Agent = { name: "Clinic", initial_node: "", nodes: [] };
const node = (name: string) => ({ type: "addNode", node: { name, task_messages: [] } });

/** A fetch Response whose body streams the given events, split into odd chunks. */
function stream(events: object[], status = 200) {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream({
    start(c) {
      for (let i = 0; i < bytes.length; i += 37) c.enqueue(bytes.slice(i, i + 37));
      c.close();
    },
  });
  return new Response(body, { status });
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  useCopilot.getState().reset();
  useEditor.setState({ agentId: "clinic", version: 1, draft: empty, saved: empty, proposal: null, past: [], future: [] });
});
afterEach(() => vi.unstubAllGlobals());

describe("ProsperO in the editor", () => {
  it("turns a streamed build into a ready proposal", async () => {
    fetchMock.mockResolvedValue(
      stream([
        { type: "op", op: node("greeting"), label: "Added node 'greeting'" },
        { type: "op", op: node("goodbye"), label: "Added node 'goodbye'" },
        { type: "validation", errors: 0, warnings: 0 },
        { type: "done", summary: "A two-step agent.", assumptions: ["Hours unknown."], agent: empty, issues: [] },
      ]),
    );

    await useCopilot.getState().send("Build a clinic agent");

    const { proposal, draft } = useEditor.getState();
    expect(proposal!.agent.nodes.map((n) => n.name)).toEqual(["greeting", "goodbye"]);
    expect(proposal!.status).toBe("ready");
    expect(proposal!.summary).toBe("A two-step agent.");
    expect(draft).toEqual(empty); // nothing reaches the draft until accepted
    expect(useCopilot.getState().messages.map((m) => [m.role, m.kind])).toEqual([
      ["user", undefined],
      ["assistant", "summary"],
    ]);
    expect(useCopilot.getState().busy).toBe(false);

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend/api/copilot");
    expect(body).toEqual({ agent: empty, history: [], message: "Build a clinic agent" });
  });

  it("sends the open proposal and the chat on follow-ups, and records outcomes", async () => {
    fetchMock.mockResolvedValueOnce(
      stream([{ type: "op", op: node("greeting"), label: "x" }, { type: "done", summary: "First.", assumptions: [], agent: empty, issues: [] }]),
    );
    await useCopilot.getState().send("Build it");
    fetchMock.mockResolvedValueOnce(stream([{ type: "done", summary: "Second.", assumptions: [], agent: empty, issues: [] }]));
    await useCopilot.getState().send("Make it shorter");

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.agent.nodes.map((n: { name: string }) => n.name)).toEqual(["greeting"]);
    expect(body.history).toEqual([
      { role: "user", content: "Build it" },
      { role: "assistant", content: "First." },
    ]);

    useCopilot.getState().recordOutcome("rejected");
    expect(useCopilot.getState().messages.at(-1)).toMatchObject({ kind: "outcome", content: expect.stringMatching(/rejected/) });
  });

  it("shows a question as a question", async () => {
    fetchMock.mockResolvedValue(stream([{ type: "reply", text: "Which emergency number?", agent: empty, issues: [] }]));
    await useCopilot.getState().send("Build it");
    expect(useEditor.getState().proposal!.status).toBe("question");
    expect(useCopilot.getState().messages.at(-1)).toMatchObject({ kind: "question", content: "Which emergency number?" });
  });

  it("reports failures without losing the edits so far", async () => {
    fetchMock.mockResolvedValue(stream([{ type: "op", op: node("greeting"), label: "x" }, { type: "error", message: "The LLM request failed: rate limited" }]));
    await useCopilot.getState().send("Build it");
    expect(useEditor.getState().proposal).toMatchObject({ status: "error", error: "The LLM request failed: rate limited" });
    expect(useEditor.getState().proposal!.edits).toHaveLength(1);

    fetchMock.mockResolvedValue(new Response(null, { status: 503 }));
    await useCopilot.getState().send("Try again");
    expect(useCopilot.getState().messages.at(-1)).toMatchObject({ kind: "error", content: "ProsperO is unavailable (HTTP 503)." });
  });
});
