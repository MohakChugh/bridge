import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ActiveGeneration {
  id: string;
  doc_id: string;
  status: "streaming" | "complete" | "error";
  chunks: string[];
  fullText: string;
  error?: string;
  mode: "generate" | "edit_selection";
}

interface DocStore {
  activeDocId: string | null;
  expandedFolders: Set<string>;
  isDirty: boolean;
  editorContent: string;
  activeGeneration: ActiveGeneration | null;
  commandPaletteOpen: boolean;

  setActiveDocId: (id: string | null) => void;
  toggleFolder: (id: string) => void;
  setExpandedFolders: (ids: Set<string>) => void;
  setIsDirty: (v: boolean) => void;
  setEditorContent: (content: string) => void;
  setCommandPaletteOpen: (v: boolean) => void;

  startGeneration: (id: string, doc_id: string, mode?: "generate" | "edit_selection") => void;
  appendChunk: (chunk: string) => void;
  completeGeneration: () => void;
  failGeneration: (error: string) => void;
  clearGeneration: () => void;
}

export const useDocStore = create<DocStore>()(
  persist(
    (set) => ({
      activeDocId: null,
      expandedFolders: new Set<string>(),
      isDirty: false,
      editorContent: "",
      activeGeneration: null,
      commandPaletteOpen: false,

      setActiveDocId: (id) => set({ activeDocId: id, isDirty: false }),
      toggleFolder: (id) =>
        set((s) => {
          const next = new Set(s.expandedFolders);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return { expandedFolders: next };
        }),
      setExpandedFolders: (ids) => set({ expandedFolders: ids }),
      setIsDirty: (v) => set({ isDirty: v }),
      setEditorContent: (content) => set({ editorContent: content, isDirty: true }),
      setCommandPaletteOpen: (v) => set({ commandPaletteOpen: v }),

      startGeneration: (id, doc_id, mode = "generate") =>
        set({
          activeGeneration: { id, doc_id, status: "streaming", chunks: [], fullText: "", mode },
        }),
      appendChunk: (chunk) =>
        set((s) => {
          if (!s.activeGeneration) return s;
          const chunks = [...s.activeGeneration.chunks, chunk];
          return {
            activeGeneration: {
              ...s.activeGeneration,
              chunks,
              fullText: s.activeGeneration.fullText + chunk,
            },
          };
        }),
      completeGeneration: () =>
        set((s) => {
          if (!s.activeGeneration) return s;
          return {
            activeGeneration: { ...s.activeGeneration, status: "complete" },
          };
        }),
      failGeneration: (error) =>
        set((s) => {
          if (!s.activeGeneration) return s;
          return {
            activeGeneration: { ...s.activeGeneration, status: "error", error },
          };
        }),
      clearGeneration: () => set({ activeGeneration: null }),
    }),
    {
      name: "bridge-doc-store",
      partialize: (s) => ({
        activeDocId: s.activeDocId,
        expandedFolders: Array.from(s.expandedFolders),
      }),
      merge: (persisted: any, current) => ({
        ...current,
        ...(persisted || {}),
        expandedFolders: new Set(persisted?.expandedFolders || []),
      }),
    },
  ),
);
