import { Check, ChevronDown, ChevronRight, Loader2, Play, ShieldCheck, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { usd } from "../lib/cost";
import { timeAgo } from "../lib/format";
import { isDirty, useEditor } from "../lib/store";
import type { Agent, RegressionTest, TestExpect, TestRun, TestRunResult } from "../lib/types";
import { CommitInput, Label, Select, TextArea } from "./fields";
import Transcript from "./Transcript";

type TestFields = Partial<{ name: string; caller_turns: string[]; expect: TestExpect }>;

/** Regression tests: recorded calls replayed against the agent (AD-18). */
export default function TestsPanel() {
  const agentId = useEditor((s) => s.agentId)!;
  const draft = useEditor((s) => s.draft)!;
  const version = useEditor((s) => s.version);
  const dirty = useEditor(isDirty);
  // While reviewing a ProsperO proposal, tests run the proposal, like test calls.
  const proposal = useEditor((s) => s.proposal);
  const draftIssues = useEditor((s) => s.issues);
  const issues = proposal?.issues ?? draftIssues;
  const errors = issues.filter((i) => i.severity === "error").length;

  const [tests, setTests] = useState<RegressionTest[] | null>(null);
  const [results, setResults] = useState<Record<string, TestRunResult>>({});
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setTests(null);
    api.listTests(agentId).then(
      (t) => current && setTests(t),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [agentId]);

  // The saved version runs by name, so its result is recorded against it.
  const target: Agent | null = proposal ? proposal.agent : dirty ? draft : null;
  const shown = proposal?.agent ?? draft;
  const blocked = errors > 0 || proposal?.status === "building";

  const replace = (test: RegressionTest) => setTests((ts) => ts?.map((t) => (t.id === test.id ? test : t)) ?? null);

  async function run(test: RegressionTest) {
    setRunning((r) => new Set(r).add(test.id));
    setError(null);
    try {
      const result = await api.runTest(agentId, test.id, target);
      setResults((r) => ({ ...r, [test.id]: result }));
      const { at, agent_version, passed, total } = result;
      setTests((ts) => ts?.map((t) => (t.id === test.id ? { ...t, last_run: { at, agent_version, passed, total } } : t)) ?? null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning((r) => {
        const next = new Set(r);
        next.delete(test.id);
        return next;
      });
    }
  }

  async function update(test: RegressionTest, fields: TestFields) {
    try {
      replace(await api.updateTest(agentId, test.id, fields));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(test: RegressionTest) {
    if (!confirm(`Delete the test "${test.name}"?`)) return;
    try {
      await api.deleteTest(agentId, test.id);
      setTests((ts) => ts?.filter((t) => t.id !== test.id) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div>
      <div className="space-y-2 border-b border-slate-200 px-4 py-4">
        <button
          onClick={() => tests?.forEach((t) => !running.has(t.id) && run(t))}
          disabled={blocked || !tests?.length || running.size > 0}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-500"
        >
          {running.size > 0 ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          {running.size > 0 ? `Running ${running.size}…` : "Run all tests"}
        </button>
        <p className="text-xs text-slate-500">
          {errors > 0
            ? `Fix ${errors} error${errors > 1 ? "s" : ""} first; an agent with errors can't run.`
            : `Replays what the caller said, as text, 3 times each, against ${
                proposal ? "ProsperO's proposal" : dirty ? `your unsaved draft (based on version ${version})` : `version ${version}`
              }. Each test checks where the call ends, what it collects, and what the agent says.`}
        </p>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>

      <div className="px-4 py-4">
        {tests === null ? (
          <p className="text-xs text-slate-400">Loading…</p>
        ) : tests.length === 0 ? (
          <p className="text-xs text-slate-500">
            No tests yet. Open a call in History and choose <span className="font-medium">Save as test</span>: what the
            caller said is replayed against every change you make.
          </p>
        ) : (
          <ul className="space-y-2">
            {tests.map((t) => (
              <TestCard
                key={t.id}
                test={t}
                agent={shown}
                result={results[t.id]}
                running={running.has(t.id)}
                canRun={!blocked}
                onRun={() => run(t)}
                onUpdate={(fields) => update(t, fields)}
                onDelete={() => remove(t)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function TestCard({
  test,
  agent,
  result,
  running,
  canRun,
  onRun,
  onUpdate,
  onDelete,
}: {
  test: RegressionTest;
  agent: Agent;
  result?: TestRunResult;
  running: boolean;
  canRun: boolean;
  onRun: () => void;
  onUpdate: (fields: TestFields) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const last = result ?? test.last_run;
  const nodes = agent.nodes.map((n) => n.name);
  const fields = [
    ...new Set([
      ...agent.nodes.flatMap((n) => n.edges ?? []).flatMap((e) => Object.keys(e.properties ?? {})),
      ...test.expect.collected,
    ]),
  ];
  const expect = (patch: Partial<TestExpect>) => onUpdate({ expect: { ...test.expect, ...patch } });

  return (
    <li className="rounded-lg border border-slate-200">
      <div className="flex items-center gap-1.5 px-2 py-2">
        <button onClick={() => setOpen(!open)} className="rounded p-0.5 text-slate-400 hover:bg-slate-100">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <button onClick={() => setOpen(!open)} className="min-w-0 flex-1 text-left">
          <span className="block truncate text-sm">{test.name}</span>
          <span className="block text-xs text-slate-500">
            {test.caller_turns.length} caller turn{test.caller_turns.length === 1 ? "" : "s"}
            {last && ` · ran ${timeAgo(last.at)} on ${last.agent_version ? `v${last.agent_version}` : "a draft"}`}
          </span>
        </button>
        {running ? (
          <span className="flex items-center gap-1 text-[10px] text-slate-500">
            <Loader2 size={12} className="animate-spin" /> running
          </span>
        ) : (
          last && <Score passed={last.passed} total={last.total} />
        )}
        <button
          onClick={onRun}
          disabled={!canRun || running}
          title="Run this test"
          className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-indigo-700 disabled:opacity-40"
        >
          <Play size={14} />
        </button>
        <button onClick={onDelete} title="Delete this test" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600">
          <Trash2 size={14} />
        </button>
      </div>

      {open && (
        <div className="space-y-3 border-t border-slate-100 px-3 py-3">
          <div>
            <Label>Name</Label>
            <CommitInput
              value={test.name}
              onCommit={(name) => onUpdate({ name })}
              validate={(v) => (v.trim() ? null : "A test needs a name.")}
            />
          </div>
          <div>
            <Label hint="one turn per line">The caller says</Label>
            <LinesInput value={test.caller_turns} required rows={4} onCommit={(caller_turns) => onUpdate({ caller_turns })} />
          </div>
          <div>
            <Label>Ends at</Label>
            <Select value={test.expect.final_node ?? ""} onChange={(e) => expect({ final_node: e.target.value || null })}>
              <option value="">Anywhere (not checked)</option>
              {nodes.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
              {test.expect.final_node && !nodes.includes(test.expect.final_node) && (
                <option value={test.expect.final_node}>{test.expect.final_node} (not in this agent)</option>
              )}
            </Select>
          </div>
          {fields.length > 0 && (
            <div>
              <Label>Collects</Label>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {fields.map((f) => (
                  <label key={f} className="flex items-center gap-1.5 text-xs">
                    <input
                      type="checkbox"
                      checked={test.expect.collected.includes(f)}
                      onChange={(e) =>
                        expect({
                          collected: e.target.checked
                            ? [...test.expect.collected, f]
                            : test.expect.collected.filter((x) => x !== f),
                        })
                      }
                    />
                    <span className="font-mono">{f}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          <div>
            <Label hint="one per line, checked by a grader">What the agent should do</Label>
            <LinesInput
              value={test.expect.checks}
              rows={3}
              placeholder="e.g. Offers to book an appointment."
              onCommit={(checks) => expect({ checks })}
            />
            <p className="mt-1 flex items-center gap-1 text-[11px] text-slate-500">
              <ShieldCheck size={12} /> Always checked: the agent gives no medical advice.
            </p>
          </div>
          {result && <Runs result={result} />}
        </div>
      )}
    </li>
  );
}

function Score({ passed, total }: { passed: number; total: number }) {
  const tone =
    passed === total ? "bg-emerald-50 text-emerald-700" : passed === 0 ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${tone}`}>
      {passed}/{total} passed
    </span>
  );
}

function Runs({ result }: { result: TestRunResult }) {
  return (
    <div className="space-y-2">
      <Label hint={`cost ${usd(result.cost)}, replays and grading`}>Latest run</Label>
      {result.runs.map((run, i) => (
        <RunDetail key={i} index={i + 1} run={run} />
      ))}
    </div>
  );
}

function RunDetail({ index, run }: { index: number; run: TestRun }) {
  const [showTranscript, setShowTranscript] = useState(false);
  return (
    <div className={`rounded-md border px-2.5 py-2 text-xs ${run.passed ? "border-emerald-200" : "border-red-200"}`}>
      <div className="flex items-center justify-between">
        <span className={`font-medium ${run.passed ? "text-emerald-700" : "text-red-700"}`}>
          Replay {index}: {run.passed ? "passed" : "failed"}
        </span>
        {run.events.length > 0 && (
          <button onClick={() => setShowTranscript(!showTranscript)} className="text-indigo-600 hover:underline">
            {showTranscript ? "Hide transcript" : "Transcript"}
          </button>
        )}
      </div>
      {run.error && <p className="mt-1 text-red-600">{run.error}</p>}
      <ul className="mt-1 space-y-1">
        {run.results.map((r, i) => (
          <li key={i} className="flex gap-1.5">
            {r.passed ? (
              <Check size={12} className="mt-0.5 shrink-0 text-emerald-600" />
            ) : (
              <X size={12} className="mt-0.5 shrink-0 text-red-600" />
            )}
            <span>
              <span className="text-slate-800">{r.label}</span>
              {r.detail && <span className="block text-slate-500">{r.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
      {!!run.unused_turns && (
        <p className="mt-1 text-slate-500">
          The call ended before the last {run.unused_turns} caller turn{run.unused_turns > 1 ? "s were" : " was"} used.
        </p>
      )}
      {showTranscript && (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <Transcript events={run.events} />
        </div>
      )}
    </div>
  );
}

/** A list of sentences edited as lines; commits on blur. */
function LinesInput({
  value,
  onCommit,
  required = false,
  rows,
  placeholder,
}: {
  value: string[];
  onCommit: (lines: string[]) => void;
  required?: boolean;
  rows: number;
  placeholder?: string;
}) {
  const joined = value.join("\n");
  const [text, setText] = useState(joined);
  useEffect(() => setText(joined), [joined]);

  function commit() {
    const lines = text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (required && lines.length === 0) return setText(joined);
    if (lines.join("\n") !== joined) onCommit(lines);
    else setText(joined);
  }

  return <TextArea rows={rows} value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} onBlur={commit} />;
}
