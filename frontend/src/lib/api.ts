// Client for the backend's editor API (backend/api.py).

import type {
  Agent,
  AgentSummary,
  CallRecord,
  CallSummary,
  Issue,
  VersionMeta,
  VersionRecord,
  VersionSource,
  Voice,
  LanguageOption,
} from "./types";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:7860";

export class ApiError extends Error {
  status: number;
  issues?: Issue[];

  constructor(status: number, message: string, issues?: Issue[]) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, detail, body.issues);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  listAgents: () => request<AgentSummary[]>("/api/agents"),

  getAgent: (id: string) => request<VersionRecord>(`/api/agents/${id}`),

  createAgent: (agent: Agent, message = "Created") =>
    request<VersionRecord>("/api/agents", { method: "POST", body: json({ agent, message }) }),

  /** Appends a version. Fails with 409 if someone saved after `baseVersion`. */
  saveAgent: (
    id: string,
    agent: Agent,
    opts: { message?: string; source?: VersionSource; baseVersion?: number },
  ) =>
    request<VersionRecord>(`/api/agents/${id}`, {
      method: "PUT",
      body: json({
        agent,
        message: opts.message ?? "",
        source: opts.source ?? "human",
        base_version: opts.baseVersion ?? null,
      }),
    }),

  deleteAgent: (id: string) => request<void>(`/api/agents/${id}`, { method: "DELETE" }),

  listVersions: (id: string) => request<VersionMeta[]>(`/api/agents/${id}/versions`),

  getVersion: (id: string, version: number) =>
    request<VersionRecord>(`/api/agents/${id}/versions/${version}`),

  restoreVersion: (id: string, version: number) =>
    request<VersionRecord>(`/api/agents/${id}/versions/${version}/restore`, { method: "POST" }),

  listCalls: (agentId?: string) =>
    request<CallSummary[]>(`/api/calls${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""}`),

  getCall: (id: string) => request<CallRecord>(`/api/calls/${id}`),

  validate: (agent: Agent) =>
    request<{ issues: Issue[] }>("/api/validate", { method: "POST", body: json(agent) }),

  voices: () => request<Voice[]>("/api/voices"),

  languages: () => request<LanguageOption[]>("/api/languages"),
};
