import { ArrowLeft, Bot, PhoneIncoming, RotateCcw, Sparkles, User } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useCall } from "../lib/call";
import { timeAgo } from "../lib/format";
import { isDirty, useEditor } from "../lib/store";
import type { CallRecord, CallSummary, VersionMeta } from "../lib/types";
import Transcript from "./Transcript";

export default function HistoryPanel({
  openCall,
  onOpenCall,
}: {
  openCall: CallRecord | null;
  onOpenCall: (id: string | null) => void;
}) {
  if (openCall) return <CallDetail call={openCall} onBack={() => onOpenCall(null)} />;
  return (
    <div>
      <CallList onOpen={onOpenCall} />
      <VersionList />
    </div>
  );
}

function CallList({ onOpen }: { onOpen: (id: string) => void }) {
  const agentId = useEditor((s) => s.agentId)!;
  const status = useCall((s) => s.status);
  const [calls, setCalls] = useState<CallSummary[] | null>(null);

  // Refresh when a call ends, since that's when it gets recorded.
  useEffect(() => {
    if (status === "connecting" || status === "live") return;
    const t = setTimeout(() => api.listCalls(agentId).then(setCalls, () => setCalls([])), 500);
    return () => clearTimeout(t);
  }, [agentId, status]);

  return (
    <section className="border-b border-slate-200 px-4 py-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Calls</h3>
      {calls === null ? (
        <p className="text-xs text-slate-400">Loading…</p>
      ) : calls.length === 0 ? (
        <p className="text-xs text-slate-500">No calls yet. Place a test call to record one.</p>
      ) : (
        <ul className="space-y-1">
          {calls.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => onOpen(c.id)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-slate-50"
              >
                <PhoneIncoming size={14} className="shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">
                    Ended at <span className="font-mono">{c.final_node}</span>
                  </span>
                  <span className="block text-xs text-slate-500">
                    {timeAgo(c.started_at)} · {c.turns} turns ·{" "}
                    {c.agent_version ? `v${c.agent_version}` : "unsaved draft"}
                  </span>
                </span>
                <Outcome endedBy={c.ended_by} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Outcome({ endedBy }: { endedBy: CallSummary["ended_by"] }) {
  // "caller" before an end node usually means a drop-off: the most useful signal to iterate on.
  return endedBy === "agent" ? (
    <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">completed</span>
  ) : (
    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">caller hung up</span>
  );
}

function CallDetail({ call, onBack }: { call: CallRecord; onBack: () => void }) {
  const version = useEditor((s) => s.version);
  const collected = Object.entries(call.collected ?? {});
  const seconds = call.ended_at ? Math.round((+new Date(call.ended_at) - +new Date(call.started_at)) / 1000) : null;

  return (
    <div>
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
        <button onClick={onBack} className="rounded p-1 text-slate-500 hover:bg-slate-100">
          <ArrowLeft size={16} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Call {call.id}</div>
          <div className="text-xs text-slate-500">
            {new Date(call.started_at).toLocaleString()}
            {seconds !== null && ` · ${seconds}s`}
          </div>
        </div>
        <Outcome endedBy={call.ended_by} />
      </div>

      <div className="space-y-3 border-b border-slate-100 px-4 py-3 text-xs">
        <p className="text-slate-600">
          Ran {call.agent_version ? `version ${call.agent_version}` : "an unsaved draft"}
          {call.agent_version !== version && " (the canvas shows your current draft, which may differ)"}. The path it
          took is highlighted on the canvas.
        </p>
        {collected.length > 0 && (
          <div>
            <div className="mb-1 font-medium text-slate-700">Collected</div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              {collected.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-mono text-slate-500">{k}</dt>
                  <dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <div className="px-4 py-4">
        {call.events.length ? <Transcript events={call.events} /> : <p className="text-xs text-slate-500">Nothing was said.</p>}
      </div>
    </div>
  );
}

function VersionList() {
  const agentId = useEditor((s) => s.agentId)!;
  const current = useEditor((s) => s.version);
  const load = useEditor((s) => s.load);
  const dirty = useEditor(isDirty);
  const [versions, setVersions] = useState<VersionMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listVersions(agentId).then(setVersions, (e: Error) => setError(e.message));
  }, [agentId, current]);

  async function restore(v: VersionMeta) {
    const lose = dirty ? " Your unsaved changes will be lost." : "";
    if (!confirm(`Restore version ${v.version}? It will be saved as a new version.${lose}`)) return;
    try {
      await api.restoreVersion(agentId, v.version);
      await load(agentId);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="px-4 py-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Versions</h3>
      {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
      <ol className="space-y-1">
        {versions?.map((v) => (
          <li key={v.version} className="group flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50">
            <SourceIcon source={v.source} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm">
                <span className="font-medium">v{v.version}</span> {v.message || <span className="text-slate-400">No message</span>}
              </div>
              <div className="text-xs text-slate-500">
                {timeAgo(v.created_at)} · {v.node_count} nodes{v.version === current && " · current"}
              </div>
            </div>
            {v.version !== current && (
              <button
                onClick={() => restore(v)}
                title="Restore this version"
                className="rounded p-1 text-slate-400 opacity-0 hover:bg-slate-200 hover:text-slate-800 group-hover:opacity-100"
              >
                <RotateCcw size={14} />
              </button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function SourceIcon({ source }: { source: VersionMeta["source"] }) {
  const common = "mt-0.5 shrink-0";
  if (source === "copilot") return <Sparkles size={14} className={`${common} text-indigo-500`} />;
  if (source === "restore") return <RotateCcw size={14} className={`${common} text-slate-400`} />;
  return source === "human" ? <User size={14} className={`${common} text-slate-400`} /> : <Bot size={14} className={common} />;
}
