import { ArrowLeft, CircleAlert, Redo2, Save, Sparkles, Undo2, X, AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { pathOf, useCall } from "../lib/call";
import { navigate } from "../lib/router";
import { isDirty, useEditor } from "../lib/store";
import type { CallRecord } from "../lib/types";
import Canvas from "./Canvas";
import RightPanel, { type Tab } from "./RightPanel";

export default function Editor({ agentId }: { agentId: string }) {
  const load = useEditor((s) => s.load);
  const draft = useEditor((s) => s.draft);
  const loading = useEditor((s) => s.loading);
  const error = useEditor((s) => s.error);
  const dirty = useEditor(isDirty);

  useEffect(() => {
    load(agentId);
  }, [agentId, load]);

  useKeyboardShortcuts();

  const [tab, setTab] = useState<Tab>("edit");
  const [openCall, setOpenCall] = useState<CallRecord | null>(null);
  const callStatus = useCall((s) => s.status);
  const callPath = useCall((s) => s.path);
  const selection = useEditor((s) => s.selection);

  // Selecting something on the canvas means "edit it".
  useEffect(() => {
    if (selection) setTab("edit");
  }, [selection]);

  const onOpenCall = useCallback(async (id: string | null) => {
    if (!id) return setOpenCall(null);
    // The bot writes the record just after the call disconnects, so a call
    // opened right as it ends may need a moment to appear.
    for (let attempt = 0; attempt < 8; attempt++) {
      try {
        return setOpenCall(await api.getCall(id));
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) break;
        await new Promise((r) => setTimeout(r, 400));
      }
    }
    setOpenCall(null);
  }, []);

  // The canvas shows the live call while there is one, then a call opened from
  // history, then the call that just ended.
  const overlay = useMemo(() => {
    if (callStatus === "connecting" || callStatus === "live") return callPath;
    if (tab === "history" && openCall) return pathOf(openCall);
    return callStatus === "ended" ? callPath : undefined;
  }, [callStatus, callPath, tab, openCall]);

  // Warn before leaving with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (!draft) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        {loading ? "Loading agent…" : error ?? "Agent not found."}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <ErrorBanner />
      <div className="flex min-h-0 flex-1">
        <CopilotPanel />
        <main className="relative min-w-0 flex-1">
          <Canvas live={overlay} />
        </main>
        <aside className="w-96 shrink-0 border-l border-slate-200 bg-white">
          <RightPanel tab={tab} onTab={setTab} openCall={openCall} onOpenCall={onOpenCall} />
        </aside>
      </div>
    </div>
  );
}

function TopBar() {
  const draft = useEditor((s) => s.draft)!;
  const version = useEditor((s) => s.version);
  const issues = useEditor((s) => s.issues);
  const past = useEditor((s) => s.past);
  const future = useEditor((s) => s.future);
  const undo = useEditor((s) => s.undo);
  const redo = useEditor((s) => s.redo);
  const dirty = useEditor(isDirty);

  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.length - errors;

  function leave() {
    if (dirty && !confirm("You have unsaved changes. Leave anyway?")) return;
    navigate("/");
  }

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-3">
      <button onClick={leave} title="All agents" className="rounded p-1.5 text-slate-500 hover:bg-slate-100">
        <ArrowLeft size={18} />
      </button>
      <div className="min-w-0">
        <div className="truncate font-semibold">{draft.name}</div>
        <div className="text-xs text-slate-500">
          Version {version}
          {dirty && <span className="text-amber-600"> · unsaved changes</span>}
        </div>
      </div>

      <div className="ml-4 flex items-center gap-2 text-xs">
        {errors > 0 && (
          <span className="flex items-center gap-1 rounded bg-red-50 px-2 py-1 text-red-700">
            <CircleAlert size={14} /> {errors} error{errors > 1 && "s"}
          </span>
        )}
        {warnings > 0 && (
          <span className="flex items-center gap-1 rounded bg-amber-50 px-2 py-1 text-amber-700">
            <AlertTriangle size={14} /> {warnings} warning{warnings > 1 && "s"}
          </span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-1">
        <IconButton onClick={undo} disabled={!past.length} title={past.length ? `Undo: ${past.at(-1)!.label} (⌘Z)` : "Undo"}>
          <Undo2 size={16} />
        </IconButton>
        <IconButton onClick={redo} disabled={!future.length} title={future.length ? `Redo: ${future[0].label} (⇧⌘Z)` : "Redo"}>
          <Redo2 size={16} />
        </IconButton>
        <SaveButton />
      </div>
    </header>
  );
}

function SaveButton() {
  const save = useEditor((s) => s.save);
  const saving = useEditor((s) => s.saving);
  const past = useEditor((s) => s.past);
  const dirty = useEditor(isDirty);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    // Default message: the most recent change, so history stays readable.
    if (await save(message.trim() || past.at(-1)?.label || "Saved")) {
      setOpen(false);
      setMessage("");
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={!dirty || saving}
        className="ml-2 flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-500"
      >
        <Save size={14} /> {saving ? "Saving…" : "Save"}
      </button>
      {open && (
        <form
          onSubmit={submit}
          className="absolute right-0 top-10 z-20 w-80 rounded-lg border border-slate-200 bg-white p-3 shadow-lg"
        >
          <label className="mb-1 block text-xs font-medium text-slate-600">Describe this version (optional)</label>
          <input
            ref={input}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
            placeholder={past.at(-1)?.label ?? "What changed?"}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-indigo-500"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={() => setOpen(false)} className="px-2 py-1 text-xs text-slate-600">
              Cancel
            </button>
            <button type="submit" className="rounded bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white">
              Save version
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function ErrorBanner() {
  const error = useEditor((s) => s.error);
  const clearError = useEditor((s) => s.clearError);
  if (!error) return null;
  return (
    <div className="flex items-center gap-2 border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
      <CircleAlert size={16} /> <span className="flex-1">{error}</span>
      <button onClick={clearError} className="rounded p-0.5 hover:bg-red-100">
        <X size={14} />
      </button>
    </div>
  );
}

/** Reserved for the Phase 2 copilot. */
function CopilotPanel() {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="Copilot"
        className="flex w-11 shrink-0 flex-col items-center gap-2 border-r border-slate-200 bg-white pt-3 text-slate-400 hover:text-indigo-600"
      >
        <Sparkles size={18} />
        <span className="text-[10px] font-medium [writing-mode:vertical-rl]">Copilot</span>
      </button>
    );
  }
  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2.5">
        <Sparkles size={16} className="text-indigo-600" />
        <span className="flex-1 text-sm font-semibold">Copilot</span>
        <button onClick={() => setOpen(false)} className="rounded p-1 text-slate-400 hover:bg-slate-100">
          <X size={14} />
        </button>
      </div>
      <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-slate-400">
        Build and improve this agent from instructions and call data. Coming in Phase 2.
      </div>
    </aside>
  );
}

function useKeyboardShortcuts() {
  const undo = useEditor((s) => s.undo);
  const redo = useEditor((s) => s.redo);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      const el = e.target as HTMLElement;
      // Inside text fields, let the browser's own undo work on the text.
      const typing = el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
      const key = e.key.toLowerCase();
      if (key === "z" && !typing) {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if (key === "y" && !typing) {
        e.preventDefault();
        redo();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
}

function IconButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="rounded p-1.5 text-slate-600 hover:bg-slate-100 disabled:text-slate-300 disabled:hover:bg-transparent"
    />
  );
}
