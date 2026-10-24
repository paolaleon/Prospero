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
  /** Node a stuck call is moved to; absent or null: a built-in polite ending (AD-16). */
  fallback_node?: string | null;
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
      // Only in calls recorded while a language guard existed (since removed, AD-15):
      // the call locked to a language, or the caller's words in another weren't passed on.
      t: string;
      type: "language";
      action: "locked" | "blocked";
      language: string | null;
      text: string;
    }
  | {
      // The call got stuck in a node and was moved to its fallback (AD-16).
      t: string;
      type: "fallback";
      from_node: string;
      reason: "missing information" | "language"; // "language": older calls only
      to_node: string;
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

// What a call consumed (backend/usage.py), and its estimated cost in USD at
// today's prices (backend/pricing.py, AD-19). Calls recorded before usage was
// metered have neither.
export interface LlmUsage {
  calls: number;
  input_tokens: number; // includes the cached ones
  cached_tokens: number;
  output_tokens: number;
}

export interface Usage {
  llm?: LlmUsage;
  tts?: { requests: number; characters: number };
  stt?: { seconds: number };
}

export interface Cost {
  llm?: number | null; // null: the model has no price
  tts?: number;
  stt?: number;
  total: number;
  complete: boolean;
}

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
  model: string | null; // null: the default model
  usage: Usage | null;
  cost: Cost | null;
}

export interface CallRecord extends Omit<CallSummary, "turns" | "agent_name" | "model"> {
  agent: Agent;
  collected: Record<string, unknown>;
  events: CallEvent[];
}

// Regression tests: a recorded call's caller turns, replayed against the agent
// (backend/regression/, AD-18).
export interface TestExpect {
  final_node: string | null;
  collected: string[];
  checks: string[];
}

export interface RegressionTest {
  id: string;
  name: string;
  created_at: string;
  from_call: string | null;
  caller_turns: string[];
  expect: TestExpect;
  last_run: { at: string; agent_version: number | null; passed: number; total: number } | null;
}

export interface TestCheckResult {
  kind: "final_node" | "collected" | "check";
  label: string;
  passed: boolean;
  detail: string;
}

export interface TestRun {
  passed: boolean;
  error: string | null;
  final_node?: string;
  unused_turns?: number;
  events: CallEvent[];
  results: TestCheckResult[];
  usage?: { replay: LlmUsage; grader: LlmUsage };
  cost: { replay: number | null; grader: number | null; total: number; complete: boolean } | null;
}

export interface TestRunResult {
  at: string;
  agent_version: number | null;
  passed: number;
  total: number;
  cost: number; // all replays and their grading, USD
  runs: TestRun[];
}

export interface Voice {
  voice_id: string;
  name: string;
  labels: Record<string, string>;
  preview_url?: string | null;
}
