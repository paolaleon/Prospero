// ProsperO, from the editor's side: the conversation, and the link between the
// backend's event stream (POST /api/copilot) and the proposal in the editor
// store (see store.ts).
//
// Edits often arrive in bursts (the model plans many at once), so they're
// played onto the canvas one by one: the user watches the agent being drawn.

import { create } from "zustand";
import { API_URL } from "./api";
import type { Op } from "./operations";
import { useEditor } from "./store";
import type { Agent, Issue } from "./types";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** How to show an assistant message; `note`s are not sent back as history. */
  kind?: "summary" | "question" | "note" | "error" | "outcome";
  assumptions?: string[];
}

export type Activity =
  | { phase: "idle" }
  | { phase: "thinking"; since: number }
  | { phase: "drawing"; edits: number }
  | { phase: "checking" };

type ServerEvent =
  | { type: "op"; op: Op; label: string }
  | { type: "note"; text: string }
  | { type: "validation"; errors: number; warnings: number }
  | { type: "done"; summary: string; assumptions: string[]; agent: Agent; issues: Issue[] }
  | { type: "reply"; text: string; agent: Agent; issues: Issue[] }
  | { type: "error"; message: string };

interface CopilotState {
  messages: ChatMessage[];
  activity: Activity;
  busy: boolean;
  send: (text: string) => Promise<void>;
  stop: () => void;
  /** Tell ProsperO what happened to its proposal, in the next turn's history. */
  recordOutcome: (outcome: "accepted" | "rejected") => void;
  reset: () => void;
}

const EDIT_INTERVAL_MS = 150;
let controller: AbortController | null = null;

export const useCopilot = create<CopilotState>((set, get) => ({
  messages: [],
  activity: { phase: "idle" },
  busy: false,

  async send(text) {
    const editor = useEditor.getState();
    if (get().busy || !editor.draft || !text.trim()) return;

    // Follow-ups build on the open proposal; otherwise start one from the draft.
    editor.startProposal();
    const agent = useEditor.getState().proposal!.agent;
    const history = get()
      .messages.filter((m) => m.kind !== "note" && m.kind !== "error")
      .map(({ role, content }) => ({ role, content }));

    set((s) => ({
      busy: true,
      activity: { phase: "thinking", since: Date.now() },
      messages: [...s.messages, { role: "user", content: text.trim() }],
    }));
    controller = new AbortController();
    const playback = new Playback((edits) => set({ activity: { phase: "drawing", edits } }));

    try {
      const res = await fetch(`${API_URL}/api/copilot`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent, history, message: text.trim() }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`ProsperO is unavailable (HTTP ${res.status}).`);

      for await (const event of readEvents(res.body)) {
        await handle(event, playback, set);
      }
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      await playback.finished();
      const message = stopped ? "Stopped. The edits so far are kept in the proposal." : (e as Error).message;
      useEditor.getState().settleProposal({ status: "error", error: message, issues: useEditor.getState().proposal?.issues ?? [] });
      set((s) => ({ messages: [...s.messages, { role: "assistant", content: message, kind: "error" }] }));
    } finally {
      controller = null;
      set({ busy: false, activity: { phase: "idle" } });
    }
  },

  stop() {
    controller?.abort();
  },

  recordOutcome(outcome) {
    const content =
      outcome === "accepted"
        ? "The user accepted the proposal; it is now saved as the agent."
        : "The user rejected the proposal; it was discarded.";
    set((s) => ({ messages: [...s.messages, { role: "assistant", content, kind: "outcome" }] }));
  },

  reset() {
    controller?.abort();
    set({ messages: [], activity: { phase: "idle" }, busy: false });
  },
}));

async function handle(
  event: ServerEvent,
  playback: Playback,
  set: (partial: Partial<CopilotState> | ((s: CopilotState) => Partial<CopilotState>)) => void,
) {
  const editor = useEditor.getState();
  switch (event.type) {
    case "op":
      playback.push(() => editor.proposeEdit(event.op, event.label));
      return;
    case "note":
      set((s) => ({ messages: [...s.messages, { role: "assistant", content: event.text, kind: "note" }] }));
      return;
    case "validation":
      await playback.finished();
      set({ activity: { phase: "checking" } });
      return;
    case "done":
      await playback.finished();
      useEditor.getState().settleProposal({
        status: "ready",
        summary: event.summary,
        assumptions: event.assumptions,
        issues: event.issues,
      });
      set((s) => ({
        messages: [
          ...s.messages,
          { role: "assistant", content: event.summary, kind: "summary", assumptions: event.assumptions },
        ],
      }));
      return;
    case "reply":
      await playback.finished();
      useEditor.getState().settleProposal({ status: "question", issues: event.issues });
      set((s) => ({ messages: [...s.messages, { role: "assistant", content: event.text, kind: "question" }] }));
      return;
    case "error":
      await playback.finished();
      useEditor.getState().settleProposal({ status: "error", error: event.message, issues: [] });
      set((s) => ({ messages: [...s.messages, { role: "assistant", content: event.message, kind: "error" }] }));
      return;
  }
}

/** Plays queued edits one at a time, so a burst of edits is drawn visibly. */
class Playback {
  private queue: (() => void)[] = [];
  private applied = 0;
  private running: Promise<void> | null = null;
  private onProgress: (applied: number) => void;

  constructor(onProgress: (applied: number) => void) {
    this.onProgress = onProgress;
  }

  push(apply: () => void) {
    this.queue.push(apply);
    // Cleared only once the run has settled, so finished() can't wait on a
    // stale promise (run() may complete before this assignment otherwise).
    this.running ??= this.run().finally(() => (this.running = null));
  }

  async finished() {
    while (this.running) await this.running;
  }

  private async run() {
    while (this.queue.length) {
      this.queue.shift()!();
      this.onProgress(++this.applied);
      if (this.queue.length) await new Promise((r) => setTimeout(r, EDIT_INTERVAL_MS));
    }
  }
}

/** Server-sent events from a fetch body: one JSON object per `data:` line. */
async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ServerEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) yield JSON.parse(line.slice(6)) as ServerEvent;
      }
    }
  }
}
