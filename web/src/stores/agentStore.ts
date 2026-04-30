import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface AgentEvent {
  id: string;
  type: string;
  task_id: string;
  data: any;
  timestamp: number;
}

interface AgentState {
  mode: "safe" | "yellow";
  liveEvents: AgentEvent[];
  setMode: (m: "safe" | "yellow") => void;
  addLiveEvent: (e: AgentEvent) => void;
  clearLiveEvents: (taskId: string) => void;
  clearAllEvents: () => void;
}

export const useAgentStore = create<AgentState>()(
  persist(
    (set) => ({
      mode: "safe",
      liveEvents: [],
      setMode: (m) => set({ mode: m }),
      addLiveEvent: (e) =>
        set((s) => ({ liveEvents: [...s.liveEvents, e].slice(-500) })),
      clearLiveEvents: (taskId) =>
        set((s) => ({
          liveEvents: s.liveEvents.filter((e) => e.task_id !== taskId),
        })),
      clearAllEvents: () => set({ liveEvents: [] }),
    }),
    { name: "bridge-agent-store", partialize: (s) => ({ mode: s.mode }) },
  ),
);
