import { create } from "zustand";

interface SessionStore {
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  view: "chat" | "dashboard" | "reminders" | "schedules" | "watches" | "workflows" | "workflow-editor" | "workflow-runner" | "operations" | "sessions";
  setView: (view: SessionStore["view"]) => void;
  activeWorkflowId: string | null;
  setActiveWorkflowId: (id: string | null) => void;
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  activeSessionId: null,
  setActiveSessionId: (id) => set({ activeSessionId: id }),
  view: "dashboard",
  setView: (view) => set({ view }),
  activeWorkflowId: null,
  setActiveWorkflowId: (id) => set({ activeWorkflowId: id }),
  activeRunId: null,
  setActiveRunId: (id) => set({ activeRunId: id }),
}));
