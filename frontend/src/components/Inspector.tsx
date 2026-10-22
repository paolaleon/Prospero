// Right-hand panel: edits whatever is selected on the canvas, or the agent's own
// settings when nothing is. Every change is dispatched as an operation.

import { ChevronDown, ChevronRight, Flag, Play, Plus, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { newEdge } from "../lib/operations";
import { issuesFor, useEditor } from "../lib/store";
import type { Agent, AgentNode, Edge, Issue, LanguageOption, PropSchema, PropType, Voice } from "../lib/types";
import {
  CommitInput,
  IDENTIFIER_RE,
  Label,
  Section,
  Select,
  SmallButton,
  TextArea,
  TextInput,
  Toggle,
} from "./fields";

export default function Inspector() {
  const agent = useEditor((s) => s.draft)!;
  const selection = useEditor((s) => s.selection);
  const node = selection && agent.nodes.find((n) => n.name === selection.node);
  if (!node) return <AgentSettings agent={agent} />;
  return (
    <NodeInspector
      key={node.name}
      agent={agent}
      node={node}
      openEdge={selection.kind === "edge" ? selection.index : null}
    />
  );
}

// ---- agent ---------------------------------------------------------------------
const MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"];

function AgentSettings({ agent }: { agent: Agent }) {
  const dispatch = useEditor((s) => s.dispatch);
  const issues = useEditor((s) => s.issues);
  const select = useEditor((s) => s.select);
  const [voices, setVoices] = useState<Voice[]>([]);

  useEffect(() => {
    api.voices().then(setVoices, () => setVoices([]));
  }, []);

  const voiceKnown = voices.some((v) => v.voice_id === agent.voice_id);

  return (
    <div>
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold">Agent settings</h2>
        <p className="text-xs text-slate-500">Select a node or transition on the canvas to edit it.</p>
      </div>

      <Section title="Identity">
        <div>
          <Label>Name</Label>
          <TextInput
            value={agent.name}
            onChange={(e) => dispatch({ type: "updateAgent", patch: { name: e.target.value } }, { coalesce: "agent:name" })}
          />
        </div>
        <div>
          <Label hint="Applies to every node unless overridden">Persona</Label>
          <TextArea
            rows={7}
            value={agent.persona ?? ""}
            placeholder="Who the agent is and how it speaks."
            onChange={(e) =>
              dispatch({ type: "updateAgent", patch: { persona: e.target.value } }, { coalesce: "agent:persona" })
            }
          />
        </div>
      </Section>

      <Section title="Voice, language and model">
        <div>
          <Label>Voice (ElevenLabs)</Label>
          <Select
            value={agent.voice_id ?? ""}
            onChange={(e) => dispatch({ type: "updateAgent", patch: { voice_id: e.target.value } })}
          >
            {!voiceKnown && <option value={agent.voice_id ?? ""}>{agent.voice_id || "Default"}</option>}
            {voices.map((v) => (
              <option key={v.voice_id} value={v.voice_id}>
                {v.name}
                {v.labels.gender ? ` · ${v.labels.gender}` : ""}
                {v.labels.accent ? ` · ${v.labels.accent}` : ""}
              </option>
            ))}
          </Select>
        </div>
        <LanguagesPicker agent={agent} />
        <div>
          <Label>LLM (OpenAI)</Label>
          <TextInput
            list="models"
            value={agent.model ?? ""}
            placeholder="gpt-4o"
            onChange={(e) => dispatch({ type: "updateAgent", patch: { model: e.target.value } }, { coalesce: "agent:model" })}
          />
          <datalist id="models">
            {MODELS.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
      </Section>

      <Section title={`Issues (${issues.length})`}>
        {issues.length === 0 ? (
          <p className="text-xs text-slate-500">No problems found.</p>
        ) : (
          <ul className="space-y-1">
            {issues.map((issue, i) => (
              <li key={i}>
                <IssueRow
                  issue={issue}
                  onClick={
                    issue.node
                      ? () =>
                          select(
                            issue.edge !== undefined
                              ? { kind: "edge", node: issue.node!, index: issue.edge }
                              : { kind: "node", node: issue.node! },
                          )
                      : undefined
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

// ---- languages (AD-15) ----------------------------------------------------------
function LanguagesPicker({ agent }: { agent: Agent }) {
  const dispatch = useEditor((s) => s.dispatch);
  const [options, setOptions] = useState<LanguageOption[]>([]);
  useEffect(() => {
    api.languages().then(setOptions, () => setOptions([{ code: "en", name: "English" }]));
  }, []);

  const languages = agent.languages?.length ? agent.languages : ["en"];
  const name = (code: string) => options.find((o) => o.code === code)?.name ?? code;
  const set = (next: string[]) => dispatch({ type: "updateAgent", patch: { languages: next } });

  return (
    <div>
      <Label hint="The agent only speaks these">Languages</Label>
      <div className="flex flex-wrap gap-1.5">
        {languages.map((code, i) => (
          <span
            key={code}
            className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${
              i === 0 ? "border-indigo-300 bg-indigo-50 text-indigo-800" : "border-slate-300 bg-white text-slate-700"
            }`}
          >
            {i === 0 ? (
              <span>
                {name(code)} <span className="text-indigo-500">· default</span>
              </span>
            ) : (
              <button
                title="Make this the default language"
                onClick={() => set([code, ...languages.filter((c) => c !== code)])}
                className="hover:underline"
              >
                {name(code)}
              </button>
            )}
            {languages.length > 1 && (
              <button
                title={`Remove ${name(code)}`}
                onClick={() => set(languages.filter((c) => c !== code))}
                className="text-slate-400 hover:text-red-600"
              >
                <X size={11} />
              </button>
            )}
          </span>
        ))}
        <select
          value=""
          onChange={(e) => e.target.value && set([...languages, e.target.value])}
          className="rounded-full border border-dashed border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-500"
        >
          <option value="">+ Add</option>
          {options
            .filter((o) => !languages.includes(o.code))
            .map((o) => (
              <option key={o.code} value={o.code}>
                {o.name}
              </option>
            ))}
        </select>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {languages.length === 1
          ? `Callers are answered in ${name(languages[0])} only.`
          : `Starts in ${name(languages[0])} and offers ${languages.slice(1).map(name).join(", ")}.`}{" "}
        Callers in other languages are offered a call back from staff.
      </p>
    </div>
  );
}

// ---- node ----------------------------------------------------------------------
function NodeInspector({ agent, node, openEdge }: { agent: Agent; node: AgentNode; openEdge: number | null }) {
  const dispatch = useEditor((s) => s.dispatch);
  const select = useEditor((s) => s.select);
  const issues = useEditor((s) => s.issues);
  const nodeIssues = issuesFor(issues, node.name).filter((i) => i.edge === undefined);
  const isStart = agent.initial_node === node.name;
  const edges = node.edges ?? [];
  const tasks = node.task_messages.length ? node.task_messages : [{ role: "developer", content: "" }];
  const overridesPersona = node.role_message != null;

  const validateName = (name: string) =>
    !IDENTIFIER_RE.test(name)
      ? "Use letters, digits, '_' or '-' (no spaces)."
      : agent.nodes.some((n) => n.name === name)
        ? `A node named '${name}' already exists.`
        : null;

  function setTask(i: number, content: string) {
    const next = tasks.map((m, j) => (j === i ? { ...m, content } : m));
    dispatch({ type: "updateNode", node: node.name, patch: { task_messages: next } }, { coalesce: `${node.name}:task:${i}` });
  }

  function deleteNode() {
    const incoming = agent.nodes.flatMap((n) => (n.edges ?? []).filter((e) => e.target === node.name)).length;
    const note = incoming ? ` ${incoming} transition(s) pointing here will lose their target.` : "";
    if (confirm(`Delete node '${node.name}'?${note}`)) dispatch({ type: "deleteNode", node: node.name });
  }

  return (
    <div>
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
        <button onClick={() => select(null)} className="text-xs text-slate-500 hover:text-slate-900">
          Agent
        </button>
        <span className="text-xs text-slate-300">/</span>
        <h2 className="min-w-0 flex-1 truncate font-mono text-sm font-semibold">{node.name}</h2>
        <button onClick={deleteNode} title="Delete node" className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
          <Trash2 size={15} />
        </button>
      </div>

      {nodeIssues.length > 0 && (
        <div className="space-y-1 border-b border-slate-100 px-4 py-3">
          {nodeIssues.map((issue, i) => (
            <IssueRow key={i} issue={issue} />
          ))}
        </div>
      )}

      <Section title="Node">
        <div>
          <Label hint="Used by transitions to point here">Name</Label>
          <CommitInput
            value={node.name}
            validate={validateName}
            className="font-mono"
            onCommit={(to) => dispatch({ type: "renameNode", from: node.name, to })}
          />
        </div>
        <div className="flex flex-col gap-2">
          {isStart ? (
            <p className="flex items-center gap-1.5 text-sm text-indigo-700">
              <Play size={14} /> The call starts here.
            </p>
          ) : (
            <SmallButton
              className="self-start"
              onClick={() => dispatch({ type: "setInitialNode", node: node.name })}
            >
              <Play size={12} /> Make this the start node
            </SmallButton>
          )}
          <Toggle
            checked={!!node.end}
            onChange={(end) => dispatch({ type: "updateNode", node: node.name, patch: { end } })}
            label="End the call after this node"
            hint="The agent says its piece, then hangs up."
          />
        </div>
      </Section>

      <Section title="Instructions">
        {tasks.map((message, i) => (
          <div key={i}>
            {tasks.length > 1 && <Label>Message {i + 1} ({message.role})</Label>}
            <TextArea
              rows={6}
              value={message.content}
              placeholder="What the agent should do in this step, e.g. “Ask for the caller's date of birth.”"
              onChange={(e) => setTask(i, e.target.value)}
            />
          </div>
        ))}
        <Toggle
          checked={overridesPersona}
          onChange={(on) =>
            dispatch({
              type: "updateNode",
              node: node.name,
              patch: { role_message: on ? (agent.persona ?? "") : null },
            })
          }
          label="Override the agent's persona in this node"
        />
        {overridesPersona && (
          <TextArea
            rows={4}
            value={node.role_message ?? ""}
            onChange={(e) =>
              dispatch(
                { type: "updateNode", node: node.name, patch: { role_message: e.target.value } },
                { coalesce: `${node.name}:role` },
              )
            }
          />
        )}
      </Section>

      {node.end && edges.length === 0 ? null : (
        <Section
          title={`Transitions (${edges.length})`}
          actions={
            <SmallButton
              onClick={() => {
                dispatch({ type: "addEdge", node: node.name, edge: newEdge(node) });
                select({ kind: "edge", node: node.name, index: edges.length });
              }}
            >
              <Plus size={12} /> Add
            </SmallButton>
          }
        >
          {edges.length === 0 && (
            <p className="text-xs text-slate-500">
              No way out of this node yet. Add a transition, or drag from the node's “+” handle on the canvas.
            </p>
          )}
          {edges.map((edge, i) => (
            <EdgeEditor
              key={i}
              agent={agent}
              node={node}
              edge={edge}
              index={i}
              open={openEdge === i}
              issues={issuesFor(issues, node.name, i)}
            />
          ))}
        </Section>
      )}

      <AdvancedActions node={node} />
    </div>
  );
}

// ---- transition ----------------------------------------------------------------
function EdgeEditor({
  agent,
  node,
  edge,
  index,
  open,
  issues,
}: {
  agent: Agent;
  node: AgentNode;
  edge: Edge;
  index: number;
  open: boolean;
  issues: Issue[];
}) {
  const dispatch = useEditor((s) => s.dispatch);
  const select = useEditor((s) => s.select);
  const ref = useRef<HTMLDivElement>(null);
  const update = (patch: Partial<Edge>, coalesce?: string) =>
    dispatch({ type: "updateEdge", node: node.name, index, patch }, coalesce ? { coalesce } : undefined);
  const hasError = issues.some((i) => i.severity === "error");

  useEffect(() => {
    if (open) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [open]);

  const validateFunction = (fn: string) =>
    !IDENTIFIER_RE.test(fn)
      ? "Use letters, digits, '_' or '-' (no spaces)."
      : (node.edges ?? []).some((e, j) => j !== index && e.function === fn)
        ? `This node already has a transition called '${fn}'.`
        : null;

  return (
    <div
      ref={ref}
      className={`rounded-lg border ${open ? "border-indigo-300 ring-2 ring-indigo-500/10" : hasError ? "border-red-200" : "border-slate-200"}`}
    >
      <button
        onClick={() => select(open ? { kind: "node", node: node.name } : { kind: "edge", node: node.name, index })}
        className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left"
      >
        {open ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
        <span className={`truncate font-mono text-xs font-medium ${hasError ? "text-red-600" : ""}`}>
          {edge.function || "unnamed"}
        </span>
        <span className="ml-auto shrink-0 truncate text-xs text-slate-400">
          {edge.target ? `→ ${edge.target}` : "no target"}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-100 px-2.5 py-3">
          {issues.length > 0 && (
            <div className="space-y-1">
              {issues.map((issue, i) => (
                <IssueRow key={i} issue={issue} />
              ))}
            </div>
          )}
          <div>
            <Label hint="The tool the LLM calls">Function name</Label>
            <CommitInput
              value={edge.function}
              validate={validateFunction}
              className="font-mono"
              onCommit={(fn) => update({ function: fn })}
            />
          </div>
          <div>
            <Label hint="The LLM reads this to decide">When to take it</Label>
            <TextArea
              rows={3}
              value={edge.description}
              placeholder="e.g. “Call once the caller has said which day they prefer.”"
              onChange={(e) => update({ description: e.target.value }, `${node.name}:${index}:desc`)}
            />
          </div>
          <div>
            <Label>Go to</Label>
            <Select value={edge.target} onChange={(e) => update({ target: e.target.value })}>
              <option value="">Choose a node…</option>
              {agent.nodes.map((n) => (
                <option key={n.name} value={n.name}>
                  {n.name}
                  {n.name === node.name ? " (this node)" : ""}
                </option>
              ))}
            </Select>
          </div>
          <FieldsEditor edge={edge} update={update} coalescePrefix={`${node.name}:${index}`} />
          <div className="flex justify-end">
            <button
              onClick={() => dispatch({ type: "deleteEdge", node: node.name, index })}
              className="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-500 hover:bg-red-50 hover:text-red-600"
            >
              <Trash2 size={12} /> Delete transition
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---- fields a transition collects ----------------------------------------------
const PROP_TYPES: PropType[] = ["string", "number", "integer", "boolean", "array", "object"];

function FieldsEditor({
  edge,
  update,
  coalescePrefix,
}: {
  edge: Edge;
  update: (patch: Partial<Edge>, coalesce?: string) => void;
  coalescePrefix: string;
}) {
  const props = Object.entries(edge.properties ?? {});
  const required = new Set(edge.required ?? []);

  function setProps(entries: [string, PropSchema][], nextRequired = required, coalesce?: string) {
    const names = new Set(entries.map(([n]) => n));
    update(
      { properties: Object.fromEntries(entries), required: [...nextRequired].filter((r) => names.has(r)) },
      coalesce,
    );
  }

  function patchProp(i: number, patch: Partial<PropSchema>, coalesce?: string) {
    setProps(
      props.map(([n, p], j) => (j === i ? [n, { ...p, ...patch }] : [n, p])),
      required,
      coalesce,
    );
  }

  function renameProp(i: number, to: string) {
    const from = props[i][0];
    const nextRequired = new Set([...required].map((r) => (r === from ? to : r)));
    setProps(
      props.map(([n, p], j) => (j === i ? [to, p] : [n, p])),
      nextRequired,
    );
  }

  function addProp() {
    let name = "field";
    for (let n = 2; props.some(([p]) => p === name); n++) name = `field_${n}`;
    setProps([...props, [name, { type: "string", description: "" }]], new Set([...required, name]));
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <Label hint="The LLM fills these in">Information to collect</Label>
        <SmallButton onClick={addProp}>
          <Plus size={12} /> Field
        </SmallButton>
      </div>
      {props.length === 0 && <p className="text-xs text-slate-500">Nothing; the transition just moves on.</p>}
      <div className="space-y-2">
        {props.map(([name, schema], i) => (
          <div key={i} className="space-y-1.5 rounded-md bg-slate-50 p-2">
            <div className="flex gap-1.5">
              <div className="flex-1">
                <CommitInput
                  value={name}
                  className="font-mono !text-xs"
                  validate={(to) =>
                    !IDENTIFIER_RE.test(to)
                      ? "Letters, digits, '_' or '-'."
                      : props.some(([p], j) => j !== i && p === to)
                        ? "Already used."
                        : null
                  }
                  onCommit={(to) => renameProp(i, to)}
                />
              </div>
              <Select
                value={schema.type}
                className="!w-24 !text-xs"
                onChange={(e) => patchProp(i, { type: e.target.value as PropType, enum: undefined })}
              >
                {PROP_TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </Select>
              <button
                title="Remove field"
                onClick={() => setProps(props.filter((_, j) => j !== i))}
                className="rounded px-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
              >
                <Trash2 size={13} />
              </button>
            </div>
            <TextInput
              value={schema.description ?? ""}
              placeholder="What this field is"
              className="!text-xs"
              onChange={(e) => patchProp(i, { description: e.target.value }, `${coalescePrefix}:prop:${i}:desc`)}
            />
            {schema.type === "string" && (
              <CommitInput
                value={(schema.enum ?? []).join(", ")}
                placeholder="Allowed values, comma-separated (optional)"
                className="!text-xs"
                onCommit={(text) => {
                  const values = text.split(",").map((v) => v.trim()).filter(Boolean);
                  patchProp(i, { enum: values.length ? values : undefined });
                }}
              />
            )}
            <Toggle
              checked={required.has(name)}
              onChange={(on) => {
                const next = new Set(required);
                if (on) next.add(name);
                else next.delete(name);
                setProps(props, next);
              }}
              label="Required"
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- pre/post actions (raw JSON) -------------------------------------------------
function AdvancedActions({ node }: { node: AgentNode }) {
  const dispatch = useEditor((s) => s.dispatch);
  const [open, setOpen] = useState(!!(node.pre_actions?.length || node.post_actions?.length));
  return (
    <section className="px-4 py-4">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Advanced: actions
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-slate-500">
            Pipecat Flows actions, as JSON. Run before the node's instructions (pre) or after its reply (post).
            {node.end && (
              <span className="mt-1 flex items-center gap-1">
                <Flag size={11} /> End nodes hang up unless post actions are set here.
              </span>
            )}
          </p>
          {(["pre_actions", "post_actions"] as const).map((key) => (
            <JsonField
              key={key}
              label={key === "pre_actions" ? "Pre actions" : "Post actions"}
              value={node[key] ?? []}
              onCommit={(value) => dispatch({ type: "updateNode", node: node.name, patch: { [key]: value } })}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function JsonField({ label, value, onCommit }: { label: string; value: unknown[]; onCommit: (v: unknown[]) => void }) {
  const serialised = JSON.stringify(value, null, 2);
  const [text, setText] = useState(serialised);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setText(serialised), [serialised]);

  function commit() {
    try {
      const parsed = JSON.parse(text || "[]");
      if (!Array.isArray(parsed)) throw new Error("Must be a JSON array.");
      setError(null);
      if (JSON.stringify(parsed) !== JSON.stringify(value)) onCommit(parsed);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div>
      <Label>{label}</Label>
      <TextArea
        rows={3}
        value={text}
        spellCheck={false}
        className="font-mono !text-xs"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
      />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

function IssueRow({ issue, onClick }: { issue: Issue; onClick?: () => void }) {
  const color = issue.severity === "error" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800";
  const where = issue.node ? `${issue.node}${issue.edge !== undefined ? ` · transition ${issue.edge + 1}` : ""}: ` : "";
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`w-full rounded px-2 py-1 text-left text-xs ${color} ${onClick ? "hover:brightness-95" : "cursor-default"}`}
    >
      {onClick && <span className="font-mono">{where}</span>}
      {issue.message}
    </button>
  );
}
