import { History, Pencil, Phone } from "lucide-react";
import { useEffect } from "react";
import { useCall } from "../lib/call";
import type { CallRecord } from "../lib/types";
import HistoryPanel from "./HistoryPanel";
import Inspector from "./Inspector";
import TestCallPanel from "./TestCallPanel";

export type Tab = "edit" | "call" | "history";

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
        <TabButton active={tab === "history"} onClick={() => onTab("history")} icon={<History size={14} />} label="History" />
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "edit" && <Inspector />}
        {tab === "call" && (
          <TestCallPanel
            onOpenCall={(id) => {
              onOpenCall(id);
              onTab("history");
            }}
          />
        )}
        {tab === "history" && <HistoryPanel openCall={openCall} onOpenCall={onOpenCall} />}
      </div>
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
