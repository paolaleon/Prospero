// ProsperO's chat panel: describe an agent or a change, watch it being drawn,
// then accept or reject the proposal from the bar above the canvas.

import { ArrowUp, Loader2, Sparkles, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useCopilot, type Activity, type ChatMessage } from "../lib/copilot";
import { useEditor } from "../lib/store";

const NEW_AGENT_IDEAS = [
  "Build an agent that books cleanings and checkups for a dental clinic, and asks new patients for their insurance.",
  "Build an intake agent for a family practice that registers new patients and books their first visit.",
  "Build an agent that takes prescription refill requests and routes urgent calls.",
];
const EDIT_IDEAS = [
  "Add an after-hours message with our opening hours.",
  "Let existing patients reschedule an appointment.",
  "Make the greeting shorter and warmer.",
];

/** Where a description typed on the agent list waits for the editor to open. */
export const pendingPromptKey = (agentId: string) => `prospero:pending:${agentId}`;

export default function CopilotPanel({ onClose }: { onClose: () => void }) {
  const agentId = useEditor((s) => s.agentId);
  const empty = useEditor((s) => (s.draft?.nodes.length ?? 0) === 0);
  const { messages, activity, busy, send, stop } = useCopilot();
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);

  // A description typed on the agent list is sent as soon as the editor opens.
  useEffect(() => {
    if (!agentId) return;
    let prompt: string | null = null;
    try {
      prompt = sessionStorage.getItem(pendingPromptKey(agentId));
      sessionStorage.removeItem(pendingPromptKey(agentId));
    } catch {
      // Storage can be unavailable (e.g. private mode); the user can type it again.
    }
    if (prompt) send(prompt);
  }, [agentId, send]);

  // A block body on purpose: scrollIntoView returns a promise in current browsers,
  // and an effect must return nothing or a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length, activity]);

  function submit(value = text) {
    if (!value.trim() || busy) return;
    send(value);
    setText("");
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2.5">
        <Sparkles size={16} className="text-violet-600" />
        <span className="flex-1 text-sm font-semibold">ProsperO</span>
        <button onClick={onClose} title="Close" className="rounded p-1 text-slate-400 hover:bg-slate-100">
          <X size={14} />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <div className="space-y-3 text-sm text-slate-600">
            <p>
              {empty
                ? "Describe the voice agent you need. I'll draw it on the canvas for you to review."
                : "Ask me to change this agent. I'll show the changes on the canvas for you to review."}
            </p>
            <div className="space-y-1.5">
              {(empty ? NEW_AGENT_IDEAS : EDIT_IDEAS).map((idea) => (
                <button
                  key={idea}
                  onClick={() => submit(idea)}
                  className="w-full rounded-lg border border-slate-200 px-2.5 py-2 text-left text-xs text-slate-700 hover:border-violet-300 hover:bg-violet-50"
                >
                  {idea}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <Message key={i} message={m} />
        ))}
        {busy && <ActivityLine activity={activity} />}
        <div ref={end} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="border-t border-slate-200 p-2"
      >
        <div className="flex items-end gap-1.5 rounded-lg border border-slate-300 bg-white p-1.5 focus-within:border-violet-500">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={3}
            placeholder={empty ? "e.g. An agent that books physio appointments…" : "Describe a change…"}
            className="min-h-0 flex-1 resize-none px-1 text-sm outline-none"
          />
          {busy ? (
            <button type="button" onClick={stop} title="Stop" className="rounded-md bg-slate-700 p-1.5 text-white hover:bg-slate-800">
              <Square size={14} />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!text.trim()}
              title="Send (Enter)"
              className="rounded-md bg-violet-600 p-1.5 text-white hover:bg-violet-700 disabled:bg-slate-200"
            >
              <ArrowUp size={14} />
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}

function Message({ message: m }: { message: ChatMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[90%] rounded-2xl rounded-br-sm bg-violet-600 px-3 py-1.5 text-sm text-white">{m.content}</div>
      </div>
    );
  }
  if (m.kind === "outcome") return <p className="text-center text-xs text-slate-400">{m.content}</p>;
  if (m.kind === "note") return <p className="text-xs italic text-slate-500">{m.content}</p>;
  if (m.kind === "error") return <p className="rounded-md bg-red-50 px-2.5 py-1.5 text-xs text-red-700">{m.content}</p>;
  return (
    <div className="rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2 text-sm text-slate-800">
      <p>{m.content}</p>
      {m.kind === "summary" && (
        <>
          {m.assumptions && m.assumptions.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-slate-600">Assumptions to check</p>
              <ul className="mt-0.5 list-inside list-disc text-xs text-slate-600">
                {m.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-2 text-xs text-violet-700">Review it on the canvas, then accept or reject it above.</p>
        </>
      )}
    </div>
  );
}

function ActivityLine({ activity }: { activity: Activity }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (activity.phase !== "thinking") return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [activity.phase]);

  const label =
    activity.phase === "thinking"
      ? `Thinking… ${Math.round((Date.now() - activity.since) / 1000)}s`
      : activity.phase === "drawing"
        ? `Drawing… ${activity.edits} edit${activity.edits === 1 ? "" : "s"}`
        : activity.phase === "checking"
          ? "Checking its work…"
          : "";
  return (
    <p className="flex items-center gap-1.5 text-xs text-violet-700">
      <Loader2 size={12} className="animate-spin" /> {label}
    </p>
  );
}
