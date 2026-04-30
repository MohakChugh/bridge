import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ReviewComment {
  id: string;
  file: string;
  line: number;
  content: string;
  author: "user" | "ai" | "auto" | "sde";
  authorName?: string;
  severity?: "error" | "warning" | "info";
  suggestion?: string;
  timestamp: number;
  sessionId?: string;
  replies: Array<{ author: "user" | "ai"; text: string; timestamp: number; sessionId?: string }>;
}

export interface DiffFile {
  path: string;
  ext: string;
  language: string;
  status: "modified" | "added" | "deleted" | "renamed";
  old_path?: string;
  additions: number;
  deletions: number;
  hunks: Array<{
    header: string;
    old_start: number;
    new_start: number;
    context: string;
    lines: Array<{
      type: "add" | "del" | "ctx";
      content: string;
      old_num: number | null;
      new_num: number | null;
    }>;
  }>;
}

export interface AnalysisSession {
  id: string;
  name: string;
  status: "busy" | "completed" | "failed" | "idle";
  error?: string;
}

export interface ReviewState {
  crId: string | null;
  tool: string | null;
  workspace: string | null;
  rawDiff: string;
  packages: string[];
  files: DiffFile[];
  comments: ReviewComment[];
  isPulling: boolean;
  loadingSteps: Array<{ label: string; status: "pending" | "active" | "done" | "error" }>;
  analysisSessions: Record<string, AnalysisSession>;
  chatSessions: string[];
  chatMessages: Array<{ role: "user" | "assistant"; text: string; timestamp: number; sessionId?: string }>;
  viewMode: "side-by-side" | "inline";
  showWhitespace: boolean;
  selectedFile: string | null;
  commentingLine: { file: string; line: number } | null;
  buildStatus: "pending" | "building" | "pass" | "fail" | null;
  buildErrors: string;
  pullError: string | null;
  savedComments: Record<string, ReviewComment[]>;
  fetchCommentsSessionId: string | null;
  fetchCommentsStatus: "idle" | "fetching" | "done" | "failed";

  setReview: (data: Partial<ReviewState>) => void;
  addComment: (comment: ReviewComment) => void;
  updateCommentSession: (commentId: string, sessionId: string) => void;
  addReply: (commentId: string, reply: { author: "user" | "ai"; text: string }) => void;
  addChatMessage: (msg: { role: "user" | "assistant"; text: string; sessionId?: string }) => void;
  setAnalysisSession: (key: string, session: AnalysisSession) => void;
  setLoadingSteps: (steps: ReviewState["loadingSteps"]) => void;
  setViewMode: (mode: "side-by-side" | "inline") => void;
  setShowWhitespace: (v: boolean) => void;
  setSelectedFile: (path: string | null) => void;
  setCommentingLine: (v: { file: string; line: number } | null) => void;
  reset: () => void;
}

const INITIAL = {
  crId: null as string | null,
  tool: null as string | null,
  workspace: null as string | null,
  rawDiff: "",
  packages: [] as string[],
  files: [] as DiffFile[],
  comments: [] as ReviewComment[],
  isPulling: false,
  loadingSteps: [] as ReviewState["loadingSteps"],
  analysisSessions: {} as Record<string, AnalysisSession>,
  chatSessions: [] as string[],
  chatMessages: [] as ReviewState["chatMessages"],
  viewMode: "side-by-side" as const,
  showWhitespace: false,
  selectedFile: null as string | null,
  commentingLine: null as { file: string; line: number } | null,
  buildStatus: null as ReviewState["buildStatus"],
  buildErrors: "",
  pullError: null as string | null,
  savedComments: {} as Record<string, ReviewComment[]>,
  fetchCommentsSessionId: null as string | null,
  fetchCommentsStatus: "idle" as "idle" | "fetching" | "done" | "failed",
};

export const useReviewStore = create<ReviewState>()(
  persist(
    (set) => ({
      ...INITIAL,

      setReview: (data) => set((s) => {
        const next = { ...s, ...data };
        // Restore saved comments when loading a new CR
        if (data.crId && data.crId !== s.crId && next.comments.length === 0) {
          const saved = s.savedComments[data.crId];
          if (saved?.length) next.comments = saved;
        }
        return next;
      }),

      addComment: (comment) =>
        set((s) => ({ comments: [...s.comments, comment] })),

      updateCommentSession: (commentId, sessionId) =>
        set((s) => ({
          comments: s.comments.map((c) =>
            c.id === commentId ? { ...c, sessionId } : c,
          ),
        })),

      addReply: (commentId, reply) =>
        set((s) => ({
          comments: s.comments.map((c) =>
            c.id === commentId
              ? { ...c, replies: [...c.replies, { ...reply, timestamp: Date.now() }] }
              : c,
          ),
        })),

      addChatMessage: (msg) =>
        set((s) => ({
          chatMessages: [...s.chatMessages, { ...msg, timestamp: Date.now() }].slice(-100),
        })),

      setAnalysisSession: (key, session) =>
        set((s) => ({
          analysisSessions: { ...s.analysisSessions, [key]: session },
        })),

      setLoadingSteps: (steps) => set({ loadingSteps: steps }),
      setViewMode: (mode) => set({ viewMode: mode }),
      setShowWhitespace: (v) => set({ showWhitespace: v }),
      setSelectedFile: (path) => set({ selectedFile: path }),
      setCommentingLine: (v) => set({ commentingLine: v }),

      reset: () => set((s) => {
        const saved = { ...s.savedComments };
        if (s.crId && s.comments.length > 0) {
          saved[s.crId] = s.comments;
        }
        return { ...INITIAL, savedComments: saved, viewMode: s.viewMode, showWhitespace: s.showWhitespace };
      }),
    }),
    {
      name: "bridge-review-store",
      partialize: (s) => ({
        crId: s.crId,
        tool: s.tool,
        workspace: s.workspace,
        rawDiff: s.rawDiff,
        packages: s.packages,
        files: s.files,
        comments: s.comments,
        analysisSessions: s.analysisSessions,
        chatSessions: s.chatSessions,
        chatMessages: s.chatMessages,
        viewMode: s.viewMode,
        showWhitespace: s.showWhitespace,
        selectedFile: s.selectedFile,
        buildStatus: s.buildStatus,
        buildErrors: s.buildErrors,
        savedComments: s.savedComments,
        fetchCommentsStatus: s.fetchCommentsStatus,
      }),
    },
  ),
);
