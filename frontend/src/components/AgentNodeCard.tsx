import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { AlertTriangle, CircleAlert, Flag, Play, Plus } from "lucide-react";
import { useEditor } from "../lib/store";
import type { AgentNode, Issue } from "../lib/types";
import { NODE_WIDTH } from "../lib/layout";

export type LiveState = "active" | "visited";

export type AgentNodeData = {
  node: AgentNode;
  isStart: boolean;
  issues: Issue[];
  selectedEdge: number | null;
  live?: LiveState;
};

export type AgentFlowNode = Node<AgentNodeData, "agent">;

export default function AgentNodeCard({ data, selected }: NodeProps<AgentFlowNode>) {
  const { node, isStart, issues, selectedEdge, live } = data;
  const select = useEditor((s) => s.select);
  const nodeIssues = issues.filter((i) => i.edge === undefined);
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.length - errors;
  const task = node.task_messages.map((m) => m.content).join(" ").trim();

  const ring =
    live === "active"
      ? "ring-4 ring-emerald-400/70 border-emerald-500"
      : selected
        ? "ring-2 ring-indigo-500/60 border-indigo-500"
        : errors
          ? "border-red-300"
          : "border-slate-200";

  return (
    <div
      style={{ width: NODE_WIDTH }}
      className={`rounded-xl border bg-white shadow-sm transition-shadow ${ring} ${live === "visited" ? "bg-emerald-50/40" : ""}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-white !bg-slate-400"
        style={{ top: 22 }}
      />

      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-sm font-semibold" title={node.name}>
          {node.name}
        </span>
        {isStart && (
          <Badge className="bg-indigo-100 text-indigo-700">
            <Play size={10} /> Start
          </Badge>
        )}
        {node.end && (
          <Badge className="bg-slate-100 text-slate-600">
            <Flag size={10} /> End
          </Badge>
        )}
        {errors > 0 && (
          <span title={`${errors} error(s)`} className="flex items-center gap-0.5 text-xs text-red-600">
            <CircleAlert size={14} /> {errors}
          </span>
        )}
        {warnings > 0 && (
          <span title={`${warnings} warning(s)`} className="flex items-center gap-0.5 text-xs text-amber-600">
            <AlertTriangle size={14} /> {warnings}
          </span>
        )}
      </div>

      <div className="px-3 py-2">
        {/* Clamp on an unpadded element, or the cut-off line shows through the padding. */}
        <p className={`line-clamp-3 text-xs leading-relaxed ${task ? "text-slate-600" : "italic text-slate-400"}`}>
          {task || "No instructions yet"}
        </p>
      </div>
      {nodeIssues.length > 0 && (
        <p className={`px-3 pb-2 text-xs ${errors ? "text-red-600" : "text-amber-600"}`}>{nodeIssues[0].message}</p>
      )}

      {!node.end && (
        <div className="border-t border-slate-100 py-1">
          {(node.edges ?? []).map((edge, i) => {
            const edgeIssues = issues.filter((x) => x.edge === i);
            const broken = edgeIssues.some((x) => x.severity === "error");
            return (
              <div
                key={i}
                onClick={(e) => {
                  e.stopPropagation();
                  select({ kind: "edge", node: node.name, index: i });
                }}
                title={edgeIssues.map((x) => x.message).join("\n") || edge.description}
                className={`relative mx-1 flex h-7 cursor-pointer items-center gap-1.5 rounded px-2 text-xs ${
                  selectedEdge === i ? "bg-indigo-50" : "hover:bg-slate-50"
                }`}
              >
                <span className={`truncate font-mono ${broken ? "text-red-600" : "text-slate-700"}`}>
                  {edge.function || "unnamed"}
                </span>
                <span className="ml-auto shrink-0 truncate text-slate-400">
                  {edge.target ? `→ ${edge.target}` : "no target"}
                </span>
                <Handle
                  type="source"
                  id={`e-${i}`}
                  position={Position.Right}
                  className={`!-right-[13px] !h-3 !w-3 !border-2 !border-white ${broken ? "!bg-red-400" : "!bg-indigo-500"}`}
                />
              </div>
            );
          })}
          <div className="relative mx-1 flex h-7 items-center gap-1 rounded px-2 text-xs text-slate-400">
            <Plus size={12} /> Drag to add a transition
            <Handle
              type="source"
              id="new"
              position={Position.Right}
              className="!-right-[13px] !h-3 !w-3 !border-2 !border-dashed !border-slate-400 !bg-white"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={`flex shrink-0 items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium ${className}`}>
      {children}
    </span>
  );
}
