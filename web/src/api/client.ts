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
};

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
