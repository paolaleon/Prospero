// Editor store — the agent being edited, its history and its validation state.
//
// The draft only changes through `dispatch(op)` (see operations.ts), which keeps
// undo/redo, labels and (later) copilot edits on one path. Saving appends a new
// version on the backend; validation runs in the background on every change.

import { create } from "zustand";
import { api, ApiError } from "./api";
import { applyOp, describeOp, type Op } from "./operations";
import type { Agent, Issue } from "./types";

export type Selection =
  | { kind: "node"; node: string }
  | { kind: "edge"; node: string; index: number }
  | null;

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

  load: (agentId: string) => Promise<void>;
  dispatch: (op: Op, opts?: { coalesce?: string }) => void;
  undo: () => void;
  redo: () => void;
  select: (selection: Selection) => void;
  save: (message?: string) => Promise<boolean>;
  clearError: () => void;
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

    async load(agentId) {
      set({ loading: true, error: null, agentId, draft: null, selection: null, past: [], future: [] });
      try {
        const record = await api.getAgent(agentId);
        lastCoalesce = null;
        set({
          version: record.version,
          draft: record.agent,
          saved: record.agent,
          issues: record.issues,
          loading: false,
        });
      } catch (e) {
        set({ loading: false, error: (e as Error).message });
      }
    },

    dispatch(op, opts) {
      const { draft, past, selection } = get();
      if (!draft) return;
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
      const { past, future, draft } = get();
      const entry = past.at(-1);
      if (!entry || !draft) return;
      lastCoalesce = null;
      set({
        past: past.slice(0, -1),
        future: [{ agent: draft, label: entry.label }, ...future],
        selection: keepSelectionIfValid(get().selection, entry.agent),
      });
      setDraft(entry.agent);
    },

    redo() {
      const { past, future, draft } = get();
      const entry = future[0];
      if (!entry || !draft) return;
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

    async save(message) {
      const { agentId, draft, version } = get();
      if (!agentId || !draft) return false;
      set({ saving: true, error: null });
      try {
        const record = await api.saveAgent(agentId, draft, { message, baseVersion: version ?? undefined });
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
