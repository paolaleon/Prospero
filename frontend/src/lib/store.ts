// Editor store — the agent being edited, its history and its validation state.
//
// The draft only changes through `dispatch(op)` (see operations/), which keeps
// undo/redo and labels on one path. Saving appends a new version on the
// backend; validation runs in the background on every change.
//
// A ProsperO proposal is held separately from the draft: the edits ProsperO
// streams are applied to a copy, shown on the canvas for review, and only reach
// the draft (as one undoable step, saved as a copilot version) when accepted.

import { create } from "zustand";
import { api, ApiError } from "./api";
import { missingPositions } from "./layout";
import { applyOp, describeOp, type Op } from "./operations";
import type { Agent, Issue, VersionSource } from "./types";

export type Selection =
  | { kind: "node"; node: string }
  | { kind: "edge"; node: string; index: number }
  | null;

/** ProsperO's proposed changes, layered over the draft until accepted or rejected. */
export interface Proposal {
  base: Agent; // the draft when ProsperO started
  agent: Agent; // base with ProsperO's edits applied
  edits: { op: Op; label: string }[];
  status: "building" | "ready" | "question" | "error";
  summary?: string; // the latest turn's
  summaries: string[]; // every turn's, for the version message on accept
  assumptions?: string[];
  issues: Issue[];
  error?: string;
}

interface HistoryEntry {
  agent: Agent;
  label: string;
}

interface EditorState {
  agentId: string | null;
  version: number | null; // the saved version the draft is based on
  draft: Agent | null;
  saved: Agent | null; // that version's content, to know if the draft is dirty
  issues: Issue[];
  selection: Selection;
  past: HistoryEntry[];
  future: HistoryEntry[];
  loading: boolean;
  saving: boolean;
  error: string | null;
  proposal: Proposal | null;

  load: (agentId: string) => Promise<void>;
  dispatch: (op: Op, opts?: { coalesce?: string }) => void;
  undo: () => void;
  redo: () => void;
  select: (selection: Selection) => void;
  save: (message?: string, source?: VersionSource) => Promise<boolean>;
  clearError: () => void;

  /** Start (or continue) a proposal: follow-up turns keep building on it. */
  startProposal: () => void;
  proposeEdit: (op: Op, label: string) => void;
  settleProposal: (outcome: Pick<Proposal, "status" | "summary" | "assumptions" | "issues" | "error">) => void;
  acceptProposal: () => Promise<boolean>;
  rejectProposal: () => void;
}

// Consecutive ops with the same coalesce key (e.g. typing in one field) within
// this window become a single undo step.
const COALESCE_MS = 1200;
const VALIDATE_DEBOUNCE_MS = 250;
const MAX_HISTORY = 200;

let lastCoalesce: { key: string; at: number } | null = null;
let validateTimer: ReturnType<typeof setTimeout> | undefined;
let validateSeq = 0;

export const useEditor = create<EditorState>((set, get) => {
  function scheduleValidation() {
    clearTimeout(validateTimer);
    validateTimer = setTimeout(async () => {
      const draft = get().draft;
      if (!draft) return;
      const seq = ++validateSeq;
      try {
        const { issues } = await api.validate(draft);
        if (seq === validateSeq) set({ issues }); // ignore stale responses
      } catch {
        // Validation is advisory while editing; the save and the call re-check.
      }
    }, VALIDATE_DEBOUNCE_MS);
  }

  function setDraft(draft: Agent) {
    set({ draft });
    scheduleValidation();
  }

  return {
    agentId: null,
    version: null,
    draft: null,
    saved: null,
    issues: [],
    selection: null,
    past: [],
    future: [],
    loading: false,
    saving: false,
    error: null,
    proposal: null,

    async load(agentId) {
      set({ loading: true, error: null, agentId, draft: null, selection: null, past: [], future: [], proposal: null });
      try {
        const record = await api.getAgent(agentId);
        lastCoalesce = null;
        // Nodes without a position (e.g. hand-written JSON) are laid out as part
        // of loading, not as an edit: the layout is stored with the next save.
        const agent = applyOp(record.agent, { type: "moveNodes", positions: missingPositions(record.agent) });
        set({
          version: record.version,
          draft: agent,
          saved: agent,
          issues: record.issues,
          loading: false,
        });
      } catch (e) {
        set({ loading: false, error: (e as Error).message });
      }
    },

    dispatch(op, opts) {
      const { draft, past, selection, proposal } = get();
      if (!draft) return;
      if (proposal) {
        set({ error: "Accept or reject ProsperO's proposal before editing." });
        return;
      }
      let next: Agent;
      try {
        next = applyOp(draft, op);
      } catch (e) {
        set({ error: (e as Error).message });
        return;
      }
      if (next === draft) return;

      const now = Date.now();
      const merge =
        opts?.coalesce && lastCoalesce?.key === opts.coalesce && now - lastCoalesce.at < COALESCE_MS;
      lastCoalesce = opts?.coalesce ? { key: opts.coalesce, at: now } : null;

      set({
        past: merge ? past : [...past.slice(-MAX_HISTORY + 1), { agent: draft, label: describeOp(op) }],
        future: [],
        selection: followSelection(selection, op, next),
      });
      setDraft(next);
    },

    undo() {
      const { past, future, draft, proposal } = get();
      const entry = past.at(-1);
      if (!entry || !draft || proposal) return;
      lastCoalesce = null;
      set({
        past: past.slice(0, -1),
        future: [{ agent: draft, label: entry.label }, ...future],
        selection: keepSelectionIfValid(get().selection, entry.agent),
      });
      setDraft(entry.agent);
    },

    redo() {
      const { past, future, draft, proposal } = get();
      const entry = future[0];
      if (!entry || !draft || proposal) return;
      lastCoalesce = null;
      set({
        past: [...past, { agent: draft, label: entry.label }],
        future: future.slice(1),
        selection: keepSelectionIfValid(get().selection, entry.agent),
      });
      setDraft(entry.agent);
    },

    select(selection) {
      set({ selection });
    },

    async save(message, source = "human") {
      const { agentId, draft, version } = get();
      if (!agentId || !draft) return false;
      set({ saving: true, error: null });
      try {
        const record = await api.saveAgent(agentId, draft, { message, source, baseVersion: version ?? undefined });
        set({ saving: false, version: record.version, saved: record.agent, issues: record.issues });
        return true;
      } catch (e) {
        const msg =
          e instanceof ApiError && e.status === 409
            ? `${e.message} Reload to see the newer version (your draft will be lost), or copy your changes first.`
            : (e as Error).message;
        set({ saving: false, error: msg });
        return false;
      }
    },

    clearError() {
      set({ error: null });
    },

    startProposal() {
      const { draft, proposal } = get();
      if (!draft) return;
      set({
        selection: null,
        proposal: proposal
          ? { ...proposal, status: "building", error: undefined }
          : { base: draft, agent: draft, edits: [], status: "building", issues: [], summaries: [] },
      });
    },

    proposeEdit(op, label) {
      const { proposal } = get();
      if (!proposal) return;
      try {
        set({ proposal: { ...proposal, agent: applyOp(proposal.agent, op), edits: [...proposal.edits, { op, label }] } });
      } catch (e) {
        // The backend applied this edit successfully, so a failure here means
        // the two implementations disagree (AD-12): surface it, don't hide it.
        set({ proposal: { ...proposal, status: "error", error: `Couldn't show an edit: ${(e as Error).message}` } });
      }
    },

    settleProposal(outcome) {
      const { proposal } = get();
      if (!proposal) return;
      const summaries = outcome.summary ? [...proposal.summaries, outcome.summary] : proposal.summaries;
      set({ proposal: { ...proposal, ...outcome, summaries } });
    },

    async acceptProposal() {
      const { proposal, draft, past } = get();
      if (!proposal || !draft) return false;
      // Give ProsperO's new nodes the positions they're shown at, then apply the
      // whole proposal as one undoable step.
      const agent = applyOp(proposal.agent, { type: "moveNodes", positions: missingPositions(proposal.agent) });
      // A proposal can span several turns; the version message covers all of them.
      const label = `ProsperO: ${proposal.summaries.join(" ") || `${proposal.edits.length} edits`}`;
      lastCoalesce = null;
      set({
        proposal: null,
        past: [...past.slice(-MAX_HISTORY + 1), { agent: draft, label }],
        future: [],
        selection: null,
      });
      setDraft(agent);
      return get().save(label, "copilot");
    },

    rejectProposal() {
      set({ proposal: null });
    },
  };
});

/** Keep the selection pointing at the same thing after renames and deletions. */
function followSelection(selection: Selection, op: Op, next: Agent): Selection {
  if (!selection) return null;
  if (op.type === "renameNode" && selection.node === op.from) {
    return { ...selection, node: op.to };
  }
  if (op.type === "deleteEdge" && selection.kind === "edge" && selection.node === op.node) {
    if (selection.index === op.index) return { kind: "node", node: op.node };
    if (selection.index > op.index) return { ...selection, index: selection.index - 1 };
  }
  return keepSelectionIfValid(selection, next);
}

function keepSelectionIfValid(selection: Selection, agent: Agent): Selection {
  if (!selection) return null;
  const node = agent.nodes.find((n) => n.name === selection.node);
  if (!node) return null;
  if (selection.kind === "edge" && !node.edges?.[selection.index]) return { kind: "node", node: node.name };
  return selection;
}

/** True when the draft differs from the version it is based on. */
export function isDirty(state: Pick<EditorState, "draft" | "saved">): boolean {
  return JSON.stringify(state.draft) !== JSON.stringify(state.saved);
}

export function issuesFor(issues: Issue[], node: string, edge?: number): Issue[] {
  return issues.filter((i) => i.node === node && (edge === undefined || i.edge === edge));
}
