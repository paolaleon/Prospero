import { Mic, Phone, PhoneOff } from "lucide-react";
import { useCall } from "../lib/call";
import { isDirty, useEditor } from "../lib/store";
import Transcript from "./Transcript";

export default function TestCallPanel({ onOpenCall }: { onOpenCall: (id: string) => void }) {
  const draft = useEditor((s) => s.draft)!;
  const agentId = useEditor((s) => s.agentId);
  const version = useEditor((s) => s.version);
  const issues = useEditor((s) => s.issues);
  const dirty = useEditor(isDirty);
  const { status, events, error, callId, userSpeaking, botSpeaking, start, hangUp, reset } = useCall();

  const errors = issues.filter((i) => i.severity === "error").length;
  const inCall = status === "connecting" || status === "live";

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 border-b border-slate-200 px-4 py-4">
        {!inCall ? (
          <>
            <button
              onClick={() => start(draft, agentId, dirty ? null : version)}
              disabled={errors > 0}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:bg-slate-200 disabled:text-slate-500"
            >
              <Phone size={16} /> {status === "ended" ? "Call again" : "Start test call"}
            </button>
            <p className="text-xs text-slate-500">
              {errors > 0
                ? `Fix ${errors} error${errors > 1 ? "s" : ""} first; an agent with errors can't run.`
                : dirty
                  ? `Runs your unsaved draft (based on version ${version}). Talk through your microphone.`
                  : `Runs version ${version}. Talk through your microphone.`}
            </p>
          </>
        ) : (
          <>
            <button
              onClick={hangUp}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-3 py-2.5 text-sm font-medium text-white hover:bg-red-700"
            >
              <PhoneOff size={16} /> Hang up
            </button>
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-1.5 text-slate-600">
                <span className={`h-2 w-2 rounded-full ${status === "live" ? "animate-pulse bg-emerald-500" : "bg-amber-400"}`} />
                {status === "live" ? "Live" : "Connecting…"}
              </span>
              <span className="flex gap-3">
                <Speaking label="You" active={userSpeaking} icon />
                <Speaking label="Agent" active={botSpeaking} />
              </span>
            </div>
          </>
        )}
        {error && <p className="rounded-md bg-red-50 px-2 py-1.5 text-xs text-red-700">{error}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {events.length === 0 ? (
          <p className="text-center text-xs text-slate-400">
            {inCall
              ? "Waiting for the conversation…"
              : "The transcript appears here, with each transition the agent takes. The active node lights up on the canvas."}
          </p>
        ) : (
          <Transcript events={events} follow={inCall} />
        )}
      </div>

      {status === "ended" && (
        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-2 text-xs">
          <span className="text-slate-500">Call ended and recorded.</span>
          <span className="flex gap-2">
            {callId && (
              <button onClick={() => onOpenCall(callId)} className="font-medium text-indigo-600 hover:underline">
                Open in history
              </button>
            )}
            <button onClick={reset} className="text-slate-500 hover:underline">
              Clear
            </button>
          </span>
        </div>
      )}
    </div>
  );
}

function Speaking({ label, active, icon }: { label: string; active: boolean; icon?: boolean }) {
  return (
    <span className={`flex items-center gap-1 ${active ? "font-medium text-emerald-700" : "text-slate-400"}`}>
      {icon && <Mic size={12} />}
      {label}
      {active ? " speaking" : ""}
    </span>
  );
}
