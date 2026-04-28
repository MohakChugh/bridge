import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SessionStore {
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  view: "chat" | "dashboard" | "reminders" | "schedules" | "watches" | "workflows" | "workflow-editor" | "workflow-runner" | "operations" | "sessions" | "workflow-analytics" | "settings" | "memory" | "logs" | "code-review" | "docs" | "agent" | "calendar" | "todos";
  setView: (view: SessionStore["view"]) => void;
  activeWorkflowId: string | null;
  setActiveWorkflowId: (id: string | null) => void;
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
}

export const useSessionStore = create<SessionStore>()(
  persist(
    (set) => ({
      activeSessionId: null,
      setActiveSessionId: (id) => set({ activeSessionId: id }),
      view: "dashboard",
      setView: (view) => set({ view }),
      activeWorkflowId: null,
      setActiveWorkflowId: (id) => set({ activeWorkflowId: id }),
      activeRunId: null,
      setActiveRunId: (id) => set({ activeRunId: id }),
    }),
    {
      name: "bridge-session-store",
      version: 2,
      partialize: (s) => ({
        activeSessionId: s.activeSessionId,
        activeWorkflowId: s.activeWorkflowId,
        activeRunId: s.activeRunId,
      }),
    },
  ),
);
