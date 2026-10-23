import { FlaskConical, History, Pencil, Phone } from "lucide-react";
import { useEffect } from "react";
import { useCall } from "../lib/call";
import { useEditor } from "../lib/store";
import type { CallRecord } from "../lib/types";
import HistoryPanel from "./HistoryPanel";
import Inspector from "./Inspector";
import TestCallPanel from "./TestCallPanel";
import TestsPanel from "./TestsPanel";

export type Tab = "edit" | "call" | "tests" | "history";

export default function RightPanel({
  tab,
  onTab,
  openCall,
  onOpenCall,
}: {
  tab: Tab;
  onTab: (tab: Tab) => void;
  openCall: CallRecord | null;
  onOpenCall: (id: string | null) => void;
}) {
  const status = useCall((s) => s.status);
  const reviewing = useEditor((s) => s.proposal !== null);

  // Jump to the call tab when a call starts, wherever it was started from.
  useEffect(() => {
    if (status === "connecting") onTab("call");
  }, [status, onTab]);

  const inCall = status === "connecting" || status === "live";

  return (
    <div className="flex h-full flex-col">
      <nav className="flex shrink-0 border-b border-slate-200">
        <TabButton active={tab === "edit"} onClick={() => onTab("edit")} icon={<Pencil size={14} />} label="Edit" />
        <TabButton
          active={tab === "call"}
          onClick={() => onTab("call")}
          icon={<Phone size={14} />}
          label="Test call"
          dot={inCall}
        />
        <TabButton active={tab === "tests"} onClick={() => onTab("tests")} icon={<FlaskConical size={14} />} label="Tests" />
        <TabButton active={tab === "history"} onClick={() => onTab("history")} icon={<History size={14} />} label="History" />
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "edit" && (reviewing ? <ReviewNotice /> : <Inspector />)}
        {tab === "call" && (
          <TestCallPanel
            onOpenCall={(id) => {
              onOpenCall(id);
              onTab("history");
            }}
          />
        )}
        {tab === "tests" && <TestsPanel />}
        {tab === "history" && (
          <HistoryPanel openCall={openCall} onOpenCall={onOpenCall} onSavedTest={() => onTab("tests")} />
        )}
      </div>
    </div>
  );
}

function ReviewNotice() {
  return (
    <div className="p-4 text-sm text-slate-600">
      <p className="font-medium text-slate-800">Reviewing ProsperO's proposal</p>
      <p className="mt-1">
        Editing is paused so your changes and ProsperO's can't collide. Accept or reject the proposal to keep editing;
        meanwhile you can place a test call to try it.
      </p>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  dot,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  dot?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs font-medium ${
        active ? "border-b-2 border-indigo-600 text-indigo-700" : "text-slate-500 hover:text-slate-800"
      }`}
    >
      {icon} {label}
      {dot && <span className="absolute right-3 top-2 h-2 w-2 animate-pulse rounded-full bg-emerald-500" />}
    </button>
  );
}
