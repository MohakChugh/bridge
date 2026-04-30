import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface LogEntry {
  id: number;
  timestamp: number;
  level: string;
  logger: string;
  message: string;
  data: string;
  correlation_id: string | null;
  source: string;
}

export interface RequestEntry {
  id: number;
  timestamp: number;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  request_body: string;
  response_body: string;
  correlation_id: string | null;
}

export interface EventEntry {
  id: number;
  timestamp: number;
  type: string;
  data: string;
  source: string;
}

interface LogFilters {
  level: string | null;
  logger: string | null;
  source: "backend" | "frontend" | null;
  q: string;
  tab: "logs" | "requests" | "events";
  since: number | null;
}

interface LogState {
  liveEntries: LogEntry[];
  filters: LogFilters;
  autoScroll: boolean;
  addLiveEntry: (entry: LogEntry) => void;
  setFilters: (filters: Partial<LogFilters>) => void;
  setAutoScroll: (on: boolean) => void;
  clearLive: () => void;
}

export const useLogStore = create<LogState>()(
  persist(
    (set) => ({
      liveEntries: [],
      filters: {
        level: null,
        logger: null,
        source: null,
        q: "",
        tab: "logs",
        since: null,
      },
      autoScroll: true,
      addLiveEntry: (entry) =>
        set((state) => ({
          liveEntries: [entry, ...state.liveEntries].slice(0, 500),
        })),
      setFilters: (filters) =>
        set((state) => ({
          filters: { ...state.filters, ...filters },
        })),
      setAutoScroll: (on) => set({ autoScroll: on }),
      clearLive: () => set({ liveEntries: [] }),
    }),
    {
      name: "bridge-log-store",
      version: 1,
      partialize: (state) => ({
        filters: state.filters,
        autoScroll: state.autoScroll,
      }),
    },
  ),
);
