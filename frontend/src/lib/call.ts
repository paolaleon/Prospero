// Test calls — one Pipecat WebRTC session at a time, from the browser.
//
// The call runs the agent exactly as it is on screen. With no unsaved changes it
// runs the saved version by reference, so the call record is tied to that
// version; otherwise it sends the draft itself (see store.resolve_call_agent). The bot
// streams each event it records (turns and transitions) as an RTVI server
// message, so the live transcript is the same data that ends up in the call
// record (backend/bot.py, CallRecorder).

import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { create } from "zustand";
import { API_URL, api } from "./api";
import type { Agent, CallEvent, CallRecord } from "./types";

export type CallStatus = "idle" | "connecting" | "live" | "ended" | "error";

/** Where a call is (or was) in the graph. Edge ids are `${node}#${index}`. */
export interface Path {
  activeNode: string | null;
  visitedNodes: Set<string>;
  traversedEdges: Set<string>;
}

interface CallState {
  status: CallStatus;
  callId: string | null;
  agent: Agent | null; // snapshot the call is running
  events: CallEvent[];
  path: Path;
  userSpeaking: boolean;
  botSpeaking: boolean;
  error: string | null;

  /** `version` is the saved version the agent matches, or null for an unsaved draft. */
  start: (agent: Agent, agentId: string | null, version: number | null) => Promise<void>;
  hangUp: () => Promise<void>;
  reset: () => void;
}

type RequestData = Parameters<PipecatClient["startBotAndConnect"]>[0]["requestData"];

const emptyPath = (): Path => ({ activeNode: null, visitedNodes: new Set(), traversedEdges: new Set() });

let client: PipecatClient | null = null;
let audio: HTMLAudioElement | null = null;

export const useCall = create<CallState>((set, get) => ({
  status: "idle",
  callId: null,
  agent: null,
  events: [],
  path: emptyPath(),
  userSpeaking: false,
  botSpeaking: false,
  error: null,

  async start(agent, agentId, version) {
    if (client) return;
    set({ status: "connecting", callId: null, agent, events: [], path: emptyPath(), error: null });

    audio ??= Object.assign(document.createElement("audio"), { autoplay: true });

    client = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onBotReady: () => set({ status: "live" }),
        onTrackStarted: (track, participant) => {
          if (!participant?.local && track.kind === "audio") audio!.srcObject = new MediaStream([track]);
        },
        onUserStartedSpeaking: () => set({ userSpeaking: true }),
        onUserStoppedSpeaking: () => set({ userSpeaking: false }),
        onBotStartedSpeaking: () => set({ botSpeaking: true }),
        onBotStoppedSpeaking: () => set({ botSpeaking: false }),
        onServerMessage: (msg) => handleServerMessage(msg),
        onDisconnected: () => finish(),
        onError: (msg) => set({ error: String((msg.data as { message?: string })?.message ?? "Call error") }),
      },
    });

    try {
      await client.startBotAndConnect({
        endpoint: `${API_URL}/start`,
        // The SDK's JSON type has no room for interfaces; the payload is plain JSON.
        requestData: {
          body:
            agentId && version !== null
              ? { agent_id: agentId, version, source: "test" }
              : { agent, agent_id: agentId, source: "test" },
        } as unknown as RequestData,
      });
    } catch (e) {
      client = null;
      set({ status: "error", error: describeStartError(e) });
    }
  },

  async hangUp() {
    await client?.disconnect();
    finish();
  },

  reset() {
    if (get().status === "connecting" || get().status === "live") return;
    set({ status: "idle", callId: null, agent: null, events: [], path: emptyPath(), error: null });
  },
}));

function handleServerMessage(msg: unknown) {
  const m = msg as { type?: string } & Record<string, unknown>;
  if (m.type === "call.started") {
    useCall.setState({ callId: m.call_id as string });
  } else if (m.type === "flow.node") {
    useCall.setState((s) => ({ path: advance(s.path, s.agent, m.node as string, m.from_node as string, m.function as string) }));
  } else if (m.type === "call.event") {
    useCall.setState((s) => ({ events: [...s.events, m.event as CallEvent] }));
  }
}

function finish() {
  if (!client) return;
  client = null;
  if (audio) audio.srcObject = null;
  useCall.setState((s) => ({
    status: s.status === "error" ? "error" : "ended",
    userSpeaking: false,
    botSpeaking: false,
    path: { ...s.path, activeNode: null },
  }));
}

/** Move the path to `node`, marking the transition taken to get there. */
function advance(path: Path, agent: Agent | null, node: string, fromNode?: string, fn?: string): Path {
  const visitedNodes = new Set(path.visitedNodes).add(node);
  const traversedEdges = new Set(path.traversedEdges);
  if (fromNode && fn && agent) {
    const index = agent.nodes.find((n) => n.name === fromNode)?.edges?.findIndex((e) => e.function === fn) ?? -1;
    if (index >= 0) traversedEdges.add(`${fromNode}#${index}`);
  }
  return { activeNode: node, visitedNodes, traversedEdges };
}

/** The path a recorded call took, for replaying it on the canvas. */
export function pathOf(record: CallRecord): Path {
  let path = advance(emptyPath(), record.agent, record.agent.initial_node);
  for (const e of record.events) {
    if (e.type === "transition") path = advance(path, record.agent, e.to_node, e.from_node, e.function);
  }
  return { ...path, activeNode: null };
}

function describeStartError(e: unknown): string {
  // startBotAndConnect rejects with the fetch Response when /start refuses.
  if (e instanceof Response) {
    return e.status === 422
      ? "The agent has errors, so the call was refused. Fix the issues shown on the canvas."
      : `The backend refused the call (HTTP ${e.status}).`;
  }
  const message = (e as Error)?.message ?? String(e);
  if (/permission|NotAllowed/i.test(message)) return "Microphone access was blocked. Allow it in the browser and try again.";
  return `Couldn't start the call: ${message}`;
}

export const loadCall = (id: string) => api.getCall(id);
