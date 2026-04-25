const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string; timestamp: number }>("/health"),
  dashboard: () => request<any>("/dashboard"),
  config: () => request<any>("/config"),
  tools: () => request<{ tools: string[]; active: string }>("/tools"),
  directories: () => request<Record<string, string>>("/directories"),

  sessions: {
    list: () => request<{ sessions: Session[] }>("/sessions"),
    archived: () => request<{ sessions: Session[] }>("/sessions/archived"),
    resume: (id: string) => request<Session>(`/sessions/archived/${id}/resume`, { method: "POST" }),
    deleteArchived: (id: string) => request<{ deleted: boolean }>(`/sessions/archived/${id}`, { method: "DELETE" }),
    get: (id: string) => request<Session>(`/sessions/${id}`),
    create: (body: { tool: string; cwd: string; title?: string }) =>
      request<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
    sendMessage: (id: string, text: string) =>
      request<{ status: string }>(`/sessions/${id}/message`, {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    cancel: (id: string) =>
      request<{ cancelled: boolean }>(`/sessions/${id}/cancel`, { method: "POST" }),
    delete: (id: string) =>
      request<{ deleted: boolean }>(`/sessions/${id}`, { method: "DELETE" }),
  },

  reminders: {
    list: () => request<{ reminders: any[] }>("/reminders"),
    parse: (text: string) =>
      request<{ iso: string; human: string; message: string }>("/reminders/parse", {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    create: (body: { message: string; fire_at_epoch: number; human?: string }) =>
      request<any>("/reminders", { method: "POST", body: JSON.stringify(body) }),
    delete: (idx: number) =>
      request<{ deleted: boolean }>(`/reminders/${idx}`, { method: "DELETE" }),
  },
  schedules: {
    list: () => request<{ schedules: any[] }>("/schedules"),
    parse: (text: string) =>
      request<{ cron: string; human: string }>("/schedules/parse", {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    create: (body: { cron: string; human: string; prompt: string; tool?: string; cwd?: string }) =>
      request<any>("/schedules", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: number) => request<{ deleted: boolean }>(`/schedules/${id}`, { method: "DELETE" }),
    pause: (id: number) => request<any>(`/schedules/${id}/pause`, { method: "POST" }),
    resume: (id: number) => request<any>(`/schedules/${id}/resume`, { method: "POST" }),
  },
  watches: {
    list: () => request<{ watches: any[] }>("/watches"),
    parse: (text: string) => request<any>("/watches/parse", { method: "POST", body: JSON.stringify({ text }) }),
    create: (body: any) => request<any>("/watches", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: number) => request<{ deleted: boolean }>(`/watches/${id}`, { method: "DELETE" }),
    pause: (id: number) => request<any>(`/watches/${id}/pause`, { method: "POST" }),
    resume: (id: number) => request<any>(`/watches/${id}/resume`, { method: "POST" }),
  },
  activity: () => request<{ events: any[] }>("/activity"),

  personas: {
    list: () => request<{ personas: any[] }>("/personas"),
    create: (body: any) => request<any>("/personas", { method: "POST", body: JSON.stringify(body) }),
    delete: (name: string) => request<any>(`/personas/${name}`, { method: "DELETE" }),
  },

  memory: {
    collections: () => request<{ collections: any[] }>("/memory/collections"),
    createCollection: (name: string, description?: string) =>
      request<any>("/memory/collections", { method: "POST", body: JSON.stringify({ name, description }) }),
    deleteCollection: (name: string) => request<any>(`/memory/collections/${name}`, { method: "DELETE" }),
    search: (query: string, collections?: string[], limit?: number) =>
      request<{ results: any[]; query: string }>("/memory/search", {
        method: "POST", body: JSON.stringify({ query, collections, limit }),
      }),
    add: (text: string, collection: string, metadata?: any, source?: string) =>
      request<{ id: number }>("/memory/add", {
        method: "POST", body: JSON.stringify({ text, collection, metadata, source }),
      }),
    delete: (id: number) => request<any>(`/memory/${id}`, { method: "DELETE" }),
    stats: () => request<any>("/memory/stats"),
    entries: (collection: string) => request<{ entries: any[] }>(`/memory/entries/${collection}`),
    import_: (path: string, collection: string) =>
      request<{ imported: number }>("/memory/import", {
        method: "POST", body: JSON.stringify({ path, collection }),
      }),
  },

  knowledge: {
    documents: () => request<{ documents: any[] }>("/knowledge/documents"),
    registerDocument: (body: any) => request<any>("/knowledge/documents", { method: "POST", body: JSON.stringify(body) }),
    deleteDocument: (id: string) => request<any>(`/knowledge/documents/${id}`, { method: "DELETE" }),
    refreshDocument: (id: string) => request<any>(`/knowledge/documents/${id}/refresh`, { method: "POST" }),
    refreshAll: () => request<any>("/knowledge/refresh-all", { method: "POST" }),
    tags: () => request<{ tags: any[] }>("/knowledge/tags"),
    graph: () => request<{ nodes: any[]; edges: any[] }>("/knowledge/graph"),
    createEdge: (body: any) => request<any>("/knowledge/graph/edges", { method: "POST", body: JSON.stringify(body) }),
    deleteEdge: (id: number) => request<any>(`/knowledge/graph/edges/${id}`, { method: "DELETE" }),
  },
  settings: {
    get: () => request<any>("/settings"),
    save: (body: any) => request<any>("/settings", { method: "POST", body: JSON.stringify(body) }),
  },

  workflows: {
    list: () => request<{ workflows: Workflow[] }>("/workflows"),
    get: (id: string) => request<Workflow>(`/workflows/${id}`),
    create: (body: any) => request<Workflow>("/workflows", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: any) => request<Workflow>(`/workflows/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    delete: (id: string) => request<{ deleted: boolean }>(`/workflows/${id}`, { method: "DELETE" }),
    run: (id: string) => request<WorkflowRun>(`/workflows/${id}/run`, { method: "POST" }),
    listRuns: (id: string) => request<{ runs: WorkflowRun[] }>(`/workflows/${id}/runs`),
    getRun: (wfId: string, runId: string) => request<WorkflowRun>(`/workflows/${wfId}/runs/${runId}`),
    approve: (wfId: string, runId: string) => request<any>(`/workflows/${wfId}/runs/${runId}/approve`, { method: "POST" }),
    abort: (wfId: string, runId: string) => request<any>(`/workflows/${wfId}/runs/${runId}/abort`, { method: "POST" }),
    schedule: (id: string, body: { text?: string; cron?: string; human?: string }) =>
      request<any>(`/workflows/${id}/schedule`, { method: "POST", body: JSON.stringify(body) }),
    unschedule: (id: string) => request<any>(`/workflows/${id}/schedule`, { method: "DELETE" }),
    generate: (body: { text: string; tool?: string; cwd?: string }) =>
      request<any>("/workflows/generate", { method: "POST", body: JSON.stringify(body) }),
    listSchedules: (id: string) => request<{ schedules: any[] }>(`/workflows/${id}/schedules`),
    addSchedule: (id: string, body: any) =>
      request<any>(`/workflows/${id}/schedules`, { method: "POST", body: JSON.stringify(body) }),
    deleteSchedule: (wfId: string, schedId: string) =>
      request<any>(`/workflows/${wfId}/schedules/${schedId}`, { method: "DELETE" }),
    resolveVariables: (body: { variables: any[]; overrides?: any }) =>
      request<{ resolved: Record<string, string> }>("/variables/resolve", { method: "POST", body: JSON.stringify(body) }),
    analytics: (id: string) => request<any>(`/workflows/${id}/analytics`),
    listArtifacts: (wfId: string, runId: string) =>
      request<{ artifacts: string[] }>(`/workflows/${wfId}/runs/${runId}/artifacts`),
    refine: (id: string, body: { feedback: string; node_id?: string | null; scope?: string }) =>
      request<{ workflow: Workflow; diff: { added: string[]; removed: string[]; changed: string[] } }>(
        `/workflows/${id}/refine`,
        { method: "POST", body: JSON.stringify(body) },
      ),
  },
};

export interface Workflow {
  id: string;
  name: string;
  description: string;
  tool: string;
  cwd: string;
  require_approval: boolean;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  schedule: any | null;
  created_at: number;
  updated_at: number;
}

export interface WorkflowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, any>;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: "pending" | "running" | "paused" | "completed" | "failed" | "aborted";
  node_states: Record<string, { status: string; output: string | null; error: string | null }>;
  session_id: string | null;
  started_at: number;
  completed_at: number | null;
}

export interface Session {
  id: string;
  title: string;
  tool: string;
  cwd: string;
  status: "idle" | "busy" | "completed" | "failed";
  tool_session_id: string | null;
  created_at: number;
  updated_at: number;
  message_history: Array<{ role: string; text: string; timestamp: number }>;
  current_task: string | null;
  last_output: string | null;
  last_error: string | null;
  meta: Record<string, any>;
}
