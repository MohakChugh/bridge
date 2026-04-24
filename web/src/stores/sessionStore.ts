import { create } from "zustand";

interface SessionStore {
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  view: "chat" | "dashboard" | "reminders" | "schedules" | "watches";
  setView: (view: SessionStore["view"]) => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  activeSessionId: null,
  setActiveSessionId: (id) => set({ activeSessionId: id }),
  view: "dashboard",
  setView: (view) => set({ view }),
}));
