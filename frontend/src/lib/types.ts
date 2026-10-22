// Mirrors the agent format in backend/agent_builder/schema.py and the API
// payloads in backend/api.py and backend/store.py.

export type PropType = "string" | "number" | "integer" | "boolean" | "array" | "object";

export interface PropSchema {
  type: PropType;
  description?: string;
  enum?: string[];
}

export interface Edge {
  function: string;
  description: string;
  target: string;
  properties?: Record<string, PropSchema>;
  required?: string[];
}

export interface TaskMessage {
  role: string;
  content: string;
}

export interface Position {
  x: number;
  y: number;
}

export interface AgentNode {
  name: string;
  task_messages: TaskMessage[];
  role_message?: string | null;
  edges?: Edge[];
  pre_actions?: unknown[];
  post_actions?: unknown[];
  end?: boolean;
  position?: Position;
}

export interface Agent {
  name: string;
  initial_node: string;
  nodes: AgentNode[];
  persona?: string;
  voice_id?: string;
  model?: string;
  /** ISO 639-1 codes, default first; English only when absent (AD-15). */
  languages?: string[];
}

export interface Issue {
  severity: "error" | "warning";
  message: string;
  node?: string;
  edge?: number;
}

export type VersionSource = "human" | "copilot" | "restore";

export interface VersionMeta {
  version: number;
  created_at: string;
  message: string;
  source: VersionSource;
  node_count: number;
}

export interface VersionRecord {
  id: string;
  version: number;
  created_at: string;
  message: string;
  source: VersionSource;
  agent: Agent;
  issues: Issue[];
}

export interface AgentSummary {
  id: string;
  name: string;
  version: number;
  node_count: number;
  updated_at: string;
}

export type CallEvent =
  | { t: string; type: "user"; text: string }
  | { t: string; type: "agent"; text: string; interrupted?: boolean }
  | {
      t: string;
      type: "transition";
      from_node: string;
      function: string;
      to_node: string;
      args: Record<string, unknown>;
    }
  | {
      // The LLM tried a transition without the data it requires; the call stayed put.
      t: string;
      type: "refused";
      node: string;
      function: string;
      args: Record<string, unknown>;
      problems: string[];
    };

export interface CallSummary {
  id: string;
  source: "test" | "production" | "mock";
  agent_id: string | null;
  agent_name: string | null;
  agent_version: number | null;
  started_at: string;
  ended_at: string | null;
  ended_by: "agent" | "caller" | null;
  final_node: string | null;
  turns: number;
}

export interface CallRecord extends Omit<CallSummary, "turns" | "agent_name"> {
  agent: Agent;
  collected: Record<string, unknown>;
  events: CallEvent[];
}

export interface LanguageOption {
  code: string;
  name: string;
}

export interface Voice {
  voice_id: string;
  name: string;
  labels: Record<string, string>;
  preview_url?: string | null;
}
