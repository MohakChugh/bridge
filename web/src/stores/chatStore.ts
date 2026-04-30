import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ChatAction {
  type: string;
  params: Record<string, any>;
  label: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: number;
  sources?: { collection: string; text_preview: string; score: number }[];
  actions?: ChatAction[];
}

interface ChatStore {
  isOpen: boolean;
  messages: ChatMessage[];
  isLoading: boolean;

  toggle: () => void;
  open: () => void;
  close: () => void;
  addMessage: (msg: Omit<ChatMessage, "id" | "timestamp">) => void;
  setLoading: (v: boolean) => void;
  clearHistory: () => void;
}

const MAX_MESSAGES = 50;

export const useChatStore = create<ChatStore>()(
  persist(
    (set) => ({
      isOpen: false,
      messages: [],
      isLoading: false,

      toggle: () => set((s) => ({ isOpen: !s.isOpen })),
      open: () => set({ isOpen: true }),
      close: () => set({ isOpen: false }),

      addMessage: (msg) =>
        set((s) => ({
          messages: [
            ...s.messages,
            {
              ...msg,
              id: crypto.randomUUID(),
              timestamp: Date.now(),
            },
          ].slice(-MAX_MESSAGES),
        })),

      setLoading: (v) => set({ isLoading: v }),
      clearHistory: () => set({ messages: [] }),
    }),
    {
      name: "bridge-chat-store",
      partialize: (s) => ({ messages: s.messages }),
    },
  ),
);
