import { AudioLines, Copy, Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { blankAgent } from "../lib/operations";
import { navigate } from "../lib/router";
import type { AgentSummary } from "../lib/types";
import { pendingPromptKey } from "./CopilotPanel";
import { timeAgo } from "../lib/format";

export default function AgentList() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The name is asked for up front because it also becomes the agent's id
  // (its URL and folder), which stays fixed even if the agent is renamed later.
  const [naming, setNaming] = useState<NameRequest | null>(null);

  const refresh = () =>
    api.listAgents().then(setAgents, (e: Error) => setError(`Can't reach the backend: ${e.message}`));

  useEffect(() => {
    refresh();
  }, []);

  function create() {
    setNaming({
      title: "New agent",
      initial: "",
      submit: (name) => api.createAgent(blankAgent(name)),
    });
  }

  // An empty agent that ProsperO builds from the description once the editor opens.
  function describe() {
    setNaming({
      title: "Describe a new agent",
      initial: "",
      describe: true,
      submit: async (name, description) => {
        const record = await api.createAgent({ name, initial_node: "", nodes: [] }, "Created for ProsperO");
        try {
          sessionStorage.setItem(pendingPromptKey(record.id), description!);
        } catch {
          // Without storage the editor opens empty; the description can be typed in the panel.
        }
        return record;
      },
    });
  }

  function duplicate(source: AgentSummary) {
    setNaming({
      title: `Duplicate “${source.name}”`,
      initial: `${source.name} (copy)`,
      submit: async (name) => {
        const { agent } = await api.getAgent(source.id);
        return api.createAgent({ ...agent, name }, `Duplicated from ${source.id}`);
      },
    });
  }

  async function submitName(name: string, description?: string) {
    if (!naming) return;
    setBusy(true);
    try {
      const record = await naming.submit(name, description);
      navigate(`/agents/${record.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
      setNaming(null);
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
        <div className="flex gap-2">
          <button
            onClick={create}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <Plus size={16} /> New agent
          </button>
          <button
            onClick={describe}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            <Sparkles size={16} /> Describe a new agent
          </button>
        </div>
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
              <IconButton title="Duplicate" onClick={() => duplicate(a)} disabled={busy}>
                <Copy size={16} />
              </IconButton>
              <IconButton title="Delete" onClick={() => remove(a)}>
                <Trash2 size={16} />
              </IconButton>
            </div>
          </li>
        ))}
      </ul>

      {naming && (
        <NameDialog request={naming} busy={busy} onSubmit={submitName} onCancel={() => setNaming(null)} />
      )}
    </div>
  );
}

interface NameRequest {
  title: string;
  initial: string;
  /** Also ask for a description for ProsperO. */
  describe?: boolean;
  submit: (name: string, description?: string) => Promise<{ id: string }>;
}

function NameDialog({
  request,
  busy,
  onSubmit,
  onCancel,
}: {
  request: NameRequest;
  busy: boolean;
  onSubmit: (name: string, description?: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(request.initial);
  const [description, setDescription] = useState("");
  const complete = name.trim() && (!request.describe || description.trim());
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.select();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/30 pt-32" onMouseDown={onCancel}>
      <form
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (complete) onSubmit(name.trim(), request.describe ? description.trim() : undefined);
        }}
        className="w-96 rounded-xl bg-white p-5 shadow-xl"
      >
        <h2 className="mb-3 font-semibold">{request.title}</h2>
        <label className="mb-1 block text-xs font-medium text-slate-600">Name</label>
        <input
          ref={input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onCancel()}
          placeholder="e.g. Dental appointment reminders"
          className="w-full rounded-md border border-slate-300 px-2.5 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
        />
        <p className="mt-1.5 text-xs text-slate-500">You can rename it any time; its link stays the same.</p>
        {request.describe && (
          <>
            <label className="mb-1 mt-3 block text-xs font-medium text-slate-600">What should it do?</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => e.key === "Escape" && onCancel()}
              rows={5}
              placeholder="e.g. Book cleanings and checkups for our dental clinic. Ask new patients for their insurance. Existing patients can cancel."
              className="w-full resize-none rounded-md border border-slate-300 px-2.5 py-2 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20"
            />
            <p className="mt-1 text-xs text-slate-500">ProsperO will draw the agent for you to review.</p>
          </>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!complete || busy}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
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
