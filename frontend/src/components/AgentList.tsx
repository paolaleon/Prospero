import { AudioLines, Copy, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { blankAgent } from "../lib/operations";
import { navigate } from "../lib/router";
import type { AgentSummary } from "../lib/types";
import { timeAgo } from "../lib/format";

export default function AgentList() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    api.listAgents().then(setAgents, (e: Error) => setError(`Can't reach the backend: ${e.message}`));

  useEffect(() => {
    refresh();
  }, []);

  async function create() {
    setBusy(true);
    try {
      const record = await api.createAgent(blankAgent());
      navigate(`/agents/${record.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function duplicate(id: string) {
    setBusy(true);
    try {
      const { agent } = await api.getAgent(id);
      const record = await api.createAgent({ ...agent, name: `${agent.name} (copy)` }, `Duplicated from ${id}`);
      navigate(`/agents/${record.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function remove(agent: AgentSummary) {
    if (!confirm(`Delete "${agent.name}" and all ${agent.version} of its versions? This can't be undone.`)) return;
    try {
      await api.deleteAgent(agent.id);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <header className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white">
            <AudioLines size={20} />
          </div>
          <div>
            <h1 className="text-xl font-semibold">Voice agents</h1>
            <p className="text-sm text-slate-500">Each agent is a graph of conversation steps.</p>
          </div>
        </div>
        <button
          onClick={create}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          <Plus size={16} /> New agent
        </button>
      </header>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {agents === null && !error && <p className="text-sm text-slate-500">Loading…</p>}

      {agents?.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
          No agents yet. Create one to start.
        </div>
      )}

      <ul className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white">
        {agents?.map((a) => (
          <li key={a.id} className="group flex items-center hover:bg-slate-50">
            <button onClick={() => navigate(`/agents/${a.id}`)} className="flex flex-1 flex-col px-4 py-3 text-left">
              <span className="font-medium">{a.name}</span>
              <span className="text-xs text-slate-500">
                {a.node_count} nodes · version {a.version} · saved {timeAgo(a.updated_at)}
              </span>
            </button>
            <div className="flex gap-1 pr-3 opacity-0 transition group-hover:opacity-100">
              <IconButton title="Duplicate" onClick={() => duplicate(a.id)} disabled={busy}>
                <Copy size={16} />
              </IconButton>
              <IconButton title="Delete" onClick={() => remove(a)}>
                <Trash2 size={16} />
              </IconButton>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function IconButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="rounded p-1.5 text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-40"
    />
  );
}
