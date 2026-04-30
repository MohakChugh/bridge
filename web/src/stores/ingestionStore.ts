import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface IngestionPhase {
  phase: string;
  current?: number;
  total?: number;
  chunks?: number;
  edges?: number;
}

export interface ActiveIngestion {
  docId: string;
  name: string;
  phase: string;
  current: number;
  total: number;
  startedAt: number;
  sourceType?: string;
}

export interface IngestionEvent {
  id: string;
  type: "registered" | "deleted" | "ingested" | "refresh.started" | "refresh.cleared" | "duplicate";
  docId: string;
  name: string;
  message: string;
  timestamp: number;
  chunks?: number;
  edges?: number;
}

interface IngestionState {
  active: Map<string, ActiveIngestion>;
  recentEvents: IngestionEvent[];
  totalsToday: { chunks: number; docs: number; deletions: number };

  handleEvent: (eventType: string, data: any) => void;
  clearEvent: (id: string) => void;
  clearAllEvents: () => void;
}

export const useIngestionStore = create<IngestionState>()(
  persist(
    (set, get) => ({
      active: new Map(),
      recentEvents: [],
      totalsToday: { chunks: 0, docs: 0, deletions: 0 },

      handleEvent: (eventType, data) => {
        const state = get();
        const now = Date.now();

        if (eventType === "ingestion.phase") {
          const docId = data.doc_id;
          const phase = data.phase;
          const name = data.name || docId;

          if (phase === "completed") {
            const newActive = new Map(state.active);
            newActive.delete(docId);
            set({
              active: newActive,
              totalsToday: { ...state.totalsToday, docs: state.totalsToday.docs + 1, chunks: state.totalsToday.chunks + (data.chunks || 0) },
              recentEvents: [
                {
                  id: `${now}-${docId}`, type: "ingested", docId, name,
                  message: `Ingested ${data.chunks || 0} chunks, ${data.edges || 0} edges`,
                  timestamp: now, chunks: data.chunks, edges: data.edges,
                },
                ...state.recentEvents,
              ].slice(0, 50),
            });
          } else {
            const newActive = new Map(state.active);
            const existing = newActive.get(docId);
            newActive.set(docId, {
              docId, name,
              phase,
              current: data.current || existing?.current || 0,
              total: data.total || data.chunks || existing?.total || 0,
              startedAt: existing?.startedAt || now,
              sourceType: data.source_type || existing?.sourceType,
            });
            set({ active: newActive });
          }
        } else if (eventType === "document.registered") {
          set({
            recentEvents: [
              {
                id: `${now}-${data.doc_id}`, type: "registered", docId: data.doc_id, name: data.name,
                message: `Registered ${data.source_type}: ${data.name}`, timestamp: now,
              },
              ...state.recentEvents,
            ].slice(0, 50),
          });
        } else if (eventType === "document.register.duplicate") {
          set({
            recentEvents: [
              {
                id: `${now}-${data.doc_id}`, type: "duplicate", docId: data.doc_id, name: data.source_url,
                message: `Already in KB: ${data.source_url}`, timestamp: now,
              },
              ...state.recentEvents,
            ].slice(0, 50),
          });
        } else if (eventType === "document.deleted") {
          set({
            totalsToday: { ...state.totalsToday, deletions: state.totalsToday.deletions + 1 },
            recentEvents: [
              {
                id: `${now}-${data.doc_id}`, type: "deleted", docId: data.doc_id, name: data.name || "Document",
                message: `Deleted: ${data.chunks_deleted} chunks, ${data.edges_deleted} edges removed`,
                timestamp: now, chunks: data.chunks_deleted, edges: data.edges_deleted,
              },
              ...state.recentEvents,
            ].slice(0, 50),
          });
        } else if (eventType === "document.refresh.started") {
          set({
            recentEvents: [
              {
                id: `${now}-${data.doc_id}`, type: "refresh.started", docId: data.doc_id, name: data.name || data.doc_id,
                message: `Clearing ${data.chunks_clearing} old chunks, ${data.edges_clearing} edges`,
                timestamp: now, chunks: data.chunks_clearing, edges: data.edges_clearing,
              },
              ...state.recentEvents,
            ].slice(0, 50),
          });
        } else if (eventType === "document.refresh.cleared") {
          set({
            recentEvents: [
              {
                id: `${now}-${data.doc_id}`, type: "refresh.cleared", docId: data.doc_id, name: data.doc_id,
                message: `Old data cleared: ${data.chunks_deleted} chunks removed`,
                timestamp: now, chunks: data.chunks_deleted,
              },
              ...state.recentEvents,
            ].slice(0, 50),
          });
        }
      },

      clearEvent: (id) => set((state) => ({ recentEvents: state.recentEvents.filter((e) => e.id !== id) })),
      clearAllEvents: () => set({ recentEvents: [] }),
    }),
    {
      name: "bridge-ingestion-store",
      version: 1,
      partialize: (state) => ({
        recentEvents: state.recentEvents,
        totalsToday: state.totalsToday,
        // skip active Map — transient runtime state
      }),
    },
  ),
);
