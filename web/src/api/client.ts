const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs, ...rest } = options || {};
  const controller = new AbortController();
  const timer = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: { "Content-Type": "application/json", ...rest.headers },
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }
    return (await res.json()) as T;
  } catch (e: any) {
    if (e.name === "AbortError") {
      throw new Error(`Request timed out after ${timeoutMs}ms`);
    }
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
  }
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
    setTool: (id: string, tool: string) =>
      request<{ updated: boolean; tool: string }>(`/sessions/${id}/set-tool`, {
        method: "POST", body: JSON.stringify({ tool }),
      }),
    delete: (id: string) =>
      request<{ deleted: boolean }>(`/sessions/${id}`, { method: "DELETE" }),
  },

  reminders: {
    list: () => request<{ reminders: any[] }>("/reminders"),
    parse: (text: string) =>
      request<{ iso: string; human: string; message: string }>("/reminders/parse", {
        method: "POST",
        body: JSON.stringify({ text }),
        timeoutMs: 90000,
      }),
    create: (body: { message: string; fire_at_epoch: number; human?: string }) =>
      request<any>("/reminders", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request<{ deleted: boolean }>(`/reminders/${id}`, { method: "DELETE" }),
  },
  schedules: {
    list: () => request<{ schedules: any[] }>("/schedules"),
    parse: (text: string) =>
      request<{ cron: string; human: string }>("/schedules/parse", {
        method: "POST",
        body: JSON.stringify({ text }),
        timeoutMs: 90000,
      }),
    create: (body: { cron: string; human: string; prompt: string; tool?: string; cwd?: string }) =>
      request<any>("/schedules", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: number) => request<{ deleted: boolean }>(`/schedules/${id}`, { method: "DELETE" }),
    pause: (id: number) => request<any>(`/schedules/${id}/pause`, { method: "POST" }),
    resume: (id: number) => request<any>(`/schedules/${id}/resume`, { method: "POST" }),
  },
  watches: {
    list: () => request<{ watches: any[] }>("/watches"),
    parse: (text: string) => request<any>("/watches/parse", { method: "POST", body: JSON.stringify({ text }), timeoutMs: 90000 }),
    create: (body: any) => request<any>("/watches", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: number) => request<{ deleted: boolean }>(`/watches/${id}`, { method: "DELETE" }),
    pause: (id: number) => request<any>(`/watches/${id}/pause`, { method: "POST" }),
    resume: (id: number) => request<any>(`/watches/${id}/resume`, { method: "POST" }),
  },
  activity: () => request<{ events: any[] }>("/activity"),
  operations: () => request<any>("/operations"),

  cr: {
    pull: (cr_id: string, tool?: string) =>
      request<{ workspace: string; packages: string[]; files: any[]; raw_diff: string; cr_id: string }>("/cr/pull", {
        method: "POST", body: JSON.stringify({ cr_id, tool }), timeoutMs: 300_000,
      }),
    loadWorkspace: (workspace: string, cr_id: string) =>
      request<{ workspace: string; packages: string[]; files: any[]; raw_diff: string; cr_id: string }>("/cr/load-workspace", {
        method: "POST", body: JSON.stringify({ workspace, cr_id }),
      }),
    analyze: (body: { cr_id: string; workspace: string; raw_diff: string; packages: string[]; tool?: string }) =>
      request<{ sessions: Record<string, string> }>("/cr/analyze", {
        method: "POST", body: JSON.stringify(body),
      }),
    comment: (body: { cr_id: string; workspace: string; packages: string[]; tool?: string; file: string; line: number; content: string; question: string }) =>
      request<{ session_id: string }>("/cr/comment", {
        method: "POST", body: JSON.stringify(body),
      }),
    chat: (body: { cr_id: string; workspace: string; packages: string[]; tool?: string; question: string }) =>
      request<{ session_id: string }>("/cr/chat", {
        method: "POST", body: JSON.stringify(body),
      }),
    sessionStatus: (sessionId: string) =>
      request<{ status: string; output: string | null; error: string | null }>(`/cr/session/${sessionId}`),
    fetchComments: (body: { cr_id: string; workspace: string; packages: string[]; tool?: string }) =>
      request<{ session_id: string }>("/cr/fetch-comments", {
        method: "POST", body: JSON.stringify(body),
      }),
    parseComments: (output: string, diff_files: string[]) =>
      request<{ comments: any[] }>("/cr/parse-comments", {
        method: "POST", body: JSON.stringify({ output, diff_files }),
      }),
    cleanup: (body: { workspace: string; session_ids: string[] }) =>
      request<{ deleted: boolean }>("/cr/cleanup", {
        method: "DELETE", body: JSON.stringify(body),
      }),
  },

  agent: {
    createTask: (body: { title: string; description: string; mode?: string }) =>
      request<any>("/agent/tasks", { method: "POST", body: JSON.stringify(body), timeoutMs: 10000 }),
    listTasks: (params?: { status?: string; limit?: number }) =>
      request<{ tasks: any[] }>(
        `/agent/tasks${params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])).toString() : ""}`,
      ),
    getTask: (id: string) => request<any>(`/agent/tasks/${id}`),
    approve: (id: string) => request<any>(`/agent/tasks/${id}/approve`, { method: "POST" }),
    reject: (id: string) => request<any>(`/agent/tasks/${id}/reject`, { method: "POST" }),
    cancel: (id: string) => request<any>(`/agent/tasks/${id}/cancel`, { method: "POST" }),
    pause: (id: string) => request<any>(`/agent/tasks/${id}/pause`, { method: "POST" }),
    resume: (id: string) => request<any>(`/agent/tasks/${id}/resume`, { method: "POST" }),
    sendMessage: (id: string, text: string) =>
      request<any>(`/agent/tasks/${id}/message`, { method: "POST", body: JSON.stringify({ text }) }),
    getMode: () => request<{ mode: string }>("/agent/mode"),
    setMode: (mode: string) =>
      request<{ mode: string }>("/agent/mode", { method: "POST", body: JSON.stringify({ mode }) }),
    status: () => request<any>("/agent/status"),
  },

  chat: {
    send: (message: string, history: { role: string; text: string }[]) =>
      request<{ response: string; sources: any[]; actions: any[]; status_included: boolean }>("/chat", {
        method: "POST",
        body: JSON.stringify({ message, history }),
        timeoutMs: 120_000,
      }),
    execute: (action_type: string, params: Record<string, any>) =>
      request<{ result: string; success: boolean; navigate?: string }>("/chat/execute", {
        method: "POST",
        body: JSON.stringify({ action_type, params }),
        timeoutMs: 120_000,
      }),
  },

  personas: {
    list: () => request<{ personas: any[] }>("/personas"),
    create: (body: any) => request<any>("/personas", { method: "POST", body: JSON.stringify(body) }),
    delete: (name: string) => request<any>(`/personas/${encodeURIComponent(name)}`, { method: "DELETE" }),
  },

  memory: {
    collections: () => request<{ collections: any[] }>("/memory/collections"),
    createCollection: (name: string, description?: string) =>
      request<any>("/memory/collections", { method: "POST", body: JSON.stringify({ name, description }) }),
    deleteCollection: (name: string) => request<any>(`/memory/collections/${encodeURIComponent(name)}`, { method: "DELETE" }),
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
    entries: (collection: string) => request<{ entries: any[] }>(`/memory/entries/${encodeURIComponent(collection)}`),
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
    refreshDocumentWorkflow: (id: string) =>
      request<{ workflow_id: string; run_id: string; workflow: any }>(`/knowledge/documents/${id}/refresh-workflow`, { method: "POST" }),
    refreshAll: () => request<any>("/knowledge/refresh-all", { method: "POST" }),
    purgeAll: () => request<any>("/knowledge/purge", { method: "DELETE" }),
    refreshAllWorkflow: () =>
      request<{ workflow_id: string; run_id: string; workflow: any }>("/knowledge/refresh-all-workflow", { method: "POST" }),
    refreshAllParallel: (parallelism: number) =>
      request<{ job_id: string; total: number; cleaned: any; status: string }>("/knowledge/refresh-all-parallel", {
        method: "POST", body: JSON.stringify({ parallelism }),
      }),
    refreshStatus: (jobId: string) =>
      request<{ total: number; completed: number; failed: number; active: string[]; errors: any[]; status: string }>(
        `/knowledge/refresh-status/${jobId}`
      ),
    tags: () => request<{ tags: any[] }>("/knowledge/tags"),
    graph: () => request<{ nodes: any[]; edges: any[] }>("/knowledge/graph"),
    createEdge: (body: any) => request<any>("/knowledge/graph/edges", { method: "POST", body: JSON.stringify(body) }),
    deleteEdge: (id: number) => request<any>(`/knowledge/graph/edges/${id}`, { method: "DELETE" }),
    discover: (body: { target: string; tool?: string; scope?: string[]; collection?: string; auto_ingest?: boolean; instructions?: string }) =>
      request<{ job_id: string; status: string; target: string }>("/knowledge/discover", { method: "POST", body: JSON.stringify(body) }),
    getDiscoveryJob: (jobId: string) =>
      request<any>(`/knowledge/discover/${jobId}`),
    listDiscoveryJobs: () =>
      request<{ jobs: any[] }>("/knowledge/discover"),
    ingestFromDiscovery: (jobId: string, urls: string[]) =>
      request<{ ingested: number; links: any[] }>(`/knowledge/discover/${jobId}/ingest`, { method: "POST", body: JSON.stringify({ urls }) }),
    dedupCheck: (urls: string[]) =>
      request<{ new: string[]; existing: string[] }>("/knowledge/dedup-check", { method: "POST", body: JSON.stringify({ urls }) }),
    discoverWorkflow: (body: { target: string; tool?: string; scope?: string[]; collection?: string; instructions?: string }) =>
      request<{ workflow_id: string; run_id: string; workflow: any }>("/knowledge/discover-workflow", { method: "POST", body: JSON.stringify(body) }),
  },
  logs: {
    query: (params: Record<string, any>) =>
      request<{ rows: any[]; total: number }>(`/logs?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])).toString()}`),
    requests: (params: Record<string, any>) =>
      request<{ rows: any[]; total: number }>(`/logs/requests?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])).toString()}`),
    events: (params: Record<string, any>) =>
      request<{ rows: any[]; total: number }>(`/logs/events?${new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])).toString()}`),
    stats: () => request<any>("/logs/stats"),
    clear: () => request<any>("/logs", { method: "DELETE" }),
    correlation: (id: string) => request<any>(`/logs/correlation/${id}`),
    reportFrontend: (body: any) =>
      request<{ stored: boolean }>("/logs/frontend", { method: "POST", body: JSON.stringify(body) }),
  },
  docs: {
    list: () => request<{ documents: any[] }>("/docs"),
    tree: () => request<{ tree: any[] }>("/docs/tree"),
    create: (body: { path: string; title: string; content?: string; tags?: string[]; collection?: string }) =>
      request<any>("/docs", { method: "POST", body: JSON.stringify(body) }),
    get: (id: string) => request<any>(`/docs/${encodeURIComponent(id)}`),
    update: (id: string, body: { content?: string; title?: string; tags?: string[] }) =>
      request<any>(`/docs/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) => request<{ deleted: boolean }>(`/docs/${encodeURIComponent(id)}`, { method: "DELETE" }),
    rename: (id: string, new_name: string) =>
      request<any>(`/docs/${encodeURIComponent(id)}/rename`, { method: "POST", body: JSON.stringify({ new_name }) }),
    move: (id: string, new_parent: string) =>
      request<any>(`/docs/${encodeURIComponent(id)}/move`, { method: "POST", body: JSON.stringify({ new_parent }) }),
    createFolder: (path: string) =>
      request<{ created: boolean }>("/docs/folder", { method: "POST", body: JSON.stringify({ path }) }),
    generate: (id: string, prompt: string, insert_at?: number) =>
      request<{ generation_id: string; doc_id: string }>(
        `/docs/${encodeURIComponent(id)}/generate`,
        { method: "POST", body: JSON.stringify({ prompt, insert_at }) },
      ),
    diagram: (id: string, prompt: string, diagram_type?: string) =>
      request<{ diagram_id: string }>(
        `/docs/${encodeURIComponent(id)}/diagram`,
        { method: "POST", body: JSON.stringify({ prompt, diagram_type: diagram_type || "mermaid" }) },
      ),
    editSelection: (id: string, body: { selected_text: string; line_start: number; line_end: number; feedback: string }) =>
      request<{ generation_id: string; doc_id: string }>(
        `/docs/${encodeURIComponent(id)}/edit-selection`,
        { method: "POST", body: JSON.stringify(body) },
      ),
    uploadImage: async (id: string, file: File): Promise<{ url: string; filename: string }> => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`/api/docs/${encodeURIComponent(id)}/upload-image`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      return res.json();
    },
    saveToMemory: (id: string) =>
      request<{ kb_doc_id: string; chunks: number; status: string }>(
        `/docs/${encodeURIComponent(id)}/save-to-memory`,
        { method: "POST" },
      ),
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

  // --- Email fetcher / calendar (Phase D) ---
  calendar: {
    list: (start: string, end: string, types?: string) => {
      const q = new URLSearchParams({ start, end });
      if (types) q.set("types", types);
      return request<BankCalendarEvent[]>(`/calendar?${q.toString()}`);
    },
    exportIcsUrl: (start: string, end: string) => `/api/calendar/export.ics?start=${start}&end=${end}`,
  },
  emails: {
    list: (limit = 50, offset = 0) =>
      request<{ total: number; offset: number; limit: number; items: any[] }>(
        `/emails?limit=${limit}&offset=${offset}`,
      ),
    stats: () => request<{ total: number }>("/emails/stats"),
  },
};

export interface BankCalendarEvent {
  id: string;
  title: string;
  start: string;
  event_type: "tls_rotation" | "pgp_key_rotation" | "outage" | "endpoint_migration" | "noise";
  confidence: number;
  source_message_id: string;
  subject: string;
  from_addr: string;
}

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
