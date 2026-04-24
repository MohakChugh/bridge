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

  reminders: { list: () => request<{ reminders: any[] }>("/reminders") },
  schedules: { list: () => request<{ schedules: any[] }>("/schedules") },
  watches: { list: () => request<{ watches: any[] }>("/watches") },
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
