import { create } from "zustand";
import { persist } from "zustand/middleware";

interface DiscoveryState {
  activeTab: "documents" | "search" | "graph" | "tags" | "discover";
  target: string;
  tool: string;
  scope: string[];
  collection: string;
  instructions: string;
  activeWfId: string | null;
  activeRunId: string | null;
  setActiveTab: (tab: DiscoveryState["activeTab"]) => void;
  setTarget: (v: string) => void;
  setTool: (v: string) => void;
  setScope: (v: string[]) => void;
  setCollection: (v: string) => void;
  setInstructions: (v: string) => void;
  setActiveWorkflow: (wfId: string | null, runId: string | null) => void;
}

export const useDiscoveryStore = create<DiscoveryState>()(
  persist(
    (set) => ({
      activeTab: "documents",
      target: "",
      tool: "wasabi",
      scope: ["wiki", "code", "quip", "web"],
      collection: "",
      instructions: "",
      activeWfId: null,
      activeRunId: null,
      setActiveTab: (t) => set({ activeTab: t }),
      setTarget: (v) => set({ target: v }),
      setTool: (v) => set({ tool: v }),
      setScope: (v) => set({ scope: v }),
      setCollection: (v) => set({ collection: v }),
      setInstructions: (v) => set({ instructions: v }),
      setActiveWorkflow: (wfId, runId) => set({ activeWfId: wfId, activeRunId: runId }),
    }),
    { name: "bridge-discovery-store", version: 1 },
  ),
);
