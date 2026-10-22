import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge as FlowEdge,
  type FinalConnectionState,
  type NodeChange,
  type OnDelete,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { LayoutGrid, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { diffAgents, type AgentDiff } from "../lib/diff";
import { autoLayout, missingPositions, NODE_WIDTH } from "../lib/layout";
import { newEdge, newNode } from "../lib/operations";
import { useEditor } from "../lib/store";
import type { Agent } from "../lib/types";
import AgentNodeCard, { type AgentFlowNode, type LiveState } from "./AgentNodeCard";

const nodeTypes = { agent: AgentNodeCard };

/** Where a call currently is in the graph; shown while a test call runs or is replayed. */
export interface LiveView {
  activeNode: string | null;
  visitedNodes: Set<string>;
  traversedEdges: Set<string>; // edge ids, see edgeId()
}

export const edgeId = (node: string, index: number) => `${node}#${index}`;

export default function Canvas({ live }: { live?: LiveView }) {
  return (
    <ReactFlowProvider>
      <FlowCanvas live={live} />
    </ReactFlowProvider>
  );
}

function FlowCanvas({ live }: { live?: LiveView }) {
  const draft = useEditor((s) => s.draft)!;
  const proposal = useEditor((s) => s.proposal);
  // While a ProsperO proposal is open the canvas shows it, read-only, with its
  // changes highlighted against the draft it started from.
  const reviewing = proposal !== null;
  const agent = proposal?.agent ?? draft;
  const diff = useMemo(() => (proposal ? diffAgents(proposal.base, proposal.agent) : null), [proposal]);
  // ProsperO's new nodes have no position yet; lay them out for display.
  const layout = useMemo(() => missingPositions(agent), [agent]);
  const draftIssues = useEditor((s) => s.issues);
  const issues = proposal?.issues ?? draftIssues;
  const selection = useEditor((s) => s.selection);
  const dispatch = useEditor((s) => s.dispatch);
  const select = useEditor((s) => s.select);
  const { screenToFlowPosition, fitView } = useReactFlow();

  // React Flow owns node positions while dragging; everything else is derived
  // from the agent. A drag becomes one `moveNodes` op when it ends.
  const [nodes, setNodes] = useState<AgentFlowNode[]>([]);
  useEffect(() => {
    setNodes((prev) => {
      const measured = new Map(prev.map((n) => [n.id, n.measured]));
      const shown = agent.nodes.map((node, i) => {
        const liveState: LiveState | undefined =
          live?.activeNode === node.name ? "active" : live?.visitedNodes.has(node.name) ? "visited" : undefined;
        return {
          id: node.name,
          type: "agent",
          position: node.position ?? layout[node.name] ?? { x: i * (NODE_WIDTH + 80), y: 0 },
          measured: measured.get(node.name),
          selected: selection?.node === node.name,
          data: {
            node,
            isStart: agent.initial_node === node.name,
            issues: issues.filter((x) => x.node === node.name),
            selectedEdge: selection?.kind === "edge" && selection.node === node.name ? selection.index : null,
            live: liveState,
            change: diff?.nodes[node.name],
          },
        } satisfies AgentFlowNode;
      });
      // Nodes the proposal deletes stay visible, faded, where they were.
      const removed = (proposal?.base.nodes ?? [])
        .filter((node) => diff?.nodes[node.name] === "removed")
        .map(
          (node): AgentFlowNode => ({
            id: node.name,
            type: "agent",
            position: node.position ?? { x: 0, y: 0 },
            measured: measured.get(node.name),
            data: { node, isStart: false, issues: [], selectedEdge: null, change: "removed" },
          }),
        );
      return [...shown, ...removed];
    });
  }, [agent, issues, selection, live, diff, layout, proposal]);

  const edges = useMemo(() => toFlowEdges(agent, selection, live, diff), [agent, selection, live, diff]);

  // Keep a growing proposal in view: each edit can add nodes or move them
  // (new transitions change the layout), so re-fit after every one.
  useEffect(() => {
    if (reviewing) requestAnimationFrame(() => fitView({ padding: 0.2, duration: 300 }));
  }, [reviewing, agent, fitView]);

  const onNodesChange = useCallback((changes: NodeChange<AgentFlowNode>[]) => {
    // Selection is owned by the store; only apply geometry here.
    setNodes((ns) => applyNodeChanges(changes.filter((c) => c.type === "position" || c.type === "dimensions"), ns));
  }, []);

  const onNodeDragStop = useCallback(
    (_: unknown, __: AgentFlowNode, dragged: AgentFlowNode[]) => {
      const positions = Object.fromEntries(
        dragged.map((n) => [n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) }]),
      );
      dispatch({ type: "moveNodes", positions });
    },
    [dispatch],
  );

  const connect = useCallback(
    (source: string, handle: string | null, target: string) => {
      const node = agent.nodes.find((n) => n.name === source);
      if (!node) return;
      if (handle === "new" || handle === null) {
        dispatch({ type: "addEdge", node: source, edge: newEdge(node, target) });
        select({ kind: "edge", node: source, index: node.edges?.length ?? 0 });
      } else {
        const index = Number(handle.slice(2));
        dispatch({ type: "updateEdge", node: source, index, patch: { target } });
        select({ kind: "edge", node: source, index });
      }
    },
    [agent, dispatch, select],
  );

  const onConnect = useCallback((c: Connection) => connect(c.source, c.sourceHandle, c.target), [connect]);

  // React Flow only connects when the drop lands on a target handle. Dropping
  // anywhere on a node connects to that node; dropping on empty canvas creates a
  // node there and connects it.
  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
      if (state.isValid || !state.fromNode || state.fromHandle?.type !== "source") return;
      const point = "changedTouches" in event ? event.changedTouches[0] : event;
      const dropped = document
        .elementFromPoint(point.clientX, point.clientY)
        ?.closest<HTMLElement>(".react-flow__node")?.dataset.id;
      if (dropped) {
        connect(state.fromNode.id, state.fromHandle.id ?? null, dropped);
        return;
      }
      const pos = screenToFlowPosition({ x: point.clientX, y: point.clientY });
      const created = newNode(agent, { x: Math.round(pos.x), y: Math.round(pos.y - 20) });
      dispatch({ type: "addNode", node: created });
      connect(state.fromNode.id, state.fromHandle.id ?? null, created.name);
    },
    [agent, connect, dispatch, screenToFlowPosition],
  );

  const onDelete: OnDelete<AgentFlowNode, FlowEdge> = useCallback(
    ({ nodes: deletedNodes, edges: deletedEdges }) => {
      const gone = new Set(deletedNodes.map((n) => n.id));
      // React Flow also reports edges attached to deleted nodes; those are
      // handled by deleteNode itself, so only delete standalone edges.
      const standalone = deletedEdges
        .filter((e) => !gone.has(e.source) && !gone.has(e.target))
        .map((e) => ({ node: e.source, index: Number(e.sourceHandle!.slice(2)) }))
        .sort((a, b) => b.index - a.index); // highest index first, so the rest stay valid
      for (const e of standalone) dispatch({ type: "deleteEdge", node: e.node, index: e.index });
      for (const name of gone) dispatch({ type: "deleteNode", node: name });
    },
    [dispatch],
  );

  function addNodeAtCenter() {
    const pane = document.querySelector(".react-flow")!.getBoundingClientRect();
    const pos = screenToFlowPosition({ x: pane.left + pane.width / 2, y: pane.top + pane.height / 2 });
    const created = newNode(agent, { x: Math.round(pos.x - NODE_WIDTH / 2), y: Math.round(pos.y - 60) });
    dispatch({ type: "addNode", node: created });
    select({ kind: "node", node: created.name });
  }

  function tidyUp() {
    dispatch({ type: "moveNodes", positions: autoLayout(agent) });
    requestAnimationFrame(() => fitView({ padding: 0.2, duration: 300 }));
  }

  return (
    <ReactFlow<AgentFlowNode, FlowEdge>
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      nodesDraggable={!reviewing}
      nodesConnectable={!reviewing}
      elementsSelectable={!reviewing}
      onNodeDragStart={(_, n) => select({ kind: "node", node: n.id })}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={(_, n) => !reviewing && select({ kind: "node", node: n.id })}
      onEdgeClick={(_, e) =>
        !reviewing && select({ kind: "edge", node: e.source, index: Number(e.sourceHandle!.slice(2)) })
      }
      onPaneClick={() => select(null)}
      onConnect={onConnect}
      onConnectEnd={onConnectEnd}
      onDelete={onDelete}
      deleteKeyCode={reviewing ? null : ["Backspace", "Delete"]}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.2}
    >
      <Background gap={20} color="#cbd5e1" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable className="!bg-white" nodeColor={(n) => (n.selected ? "#6366f1" : "#cbd5e1")} />
      <Panel position="top-left" className={`flex gap-2 ${reviewing ? "hidden" : ""}`}>
        <ToolButton onClick={addNodeAtCenter} title="Add a node">
          <Plus size={14} /> Node
        </ToolButton>
        <ToolButton onClick={tidyUp} title="Lay out the graph automatically">
          <LayoutGrid size={14} /> Tidy up
        </ToolButton>
      </Panel>
    </ReactFlow>
  );
}

function toFlowEdges(
  agent: Agent,
  selection: ReturnType<typeof useEditor.getState>["selection"],
  live?: LiveView,
  diff?: AgentDiff | null,
) {
  const names = new Set(agent.nodes.map((n) => n.name));
  const out: FlowEdge[] = [];
  for (const node of agent.nodes) {
    (node.edges ?? []).forEach((edge, index) => {
      if (!names.has(edge.target)) return; // unconnected transitions show as errors on the card
      const id = edgeId(node.name, index);
      const selected = selection?.kind === "edge" && selection.node === node.name && selection.index === index;
      const traversed = live?.traversedEdges.has(id) ?? false;
      const proposed = diff?.edges[id] !== undefined;
      const color = selected ? "#6366f1" : traversed ? "#10b981" : proposed ? "#8b5cf6" : "#94a3b8";
      out.push({
        id,
        source: node.name,
        sourceHandle: `e-${index}`,
        target: edge.target,
        type: "smoothstep",
        selected,
        animated: traversed,
        style: { stroke: color, strokeWidth: selected || traversed || proposed ? 2.5 : 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color },
      });
    });
  }
  return out;
}

function ToolButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50"
    />
  );
}
