import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Session } from "@/api/client";
import { Button, Textarea, Badge, Card } from "./ui";
import { useSessionStore } from "@/stores/sessionStore";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Send, X, Trash2, StopCircle, Plus } from "lucide-react";
import { NewSessionDialog } from "./NewSessionDialog";

export function ChatView() {
  const qc = useQueryClient();
  const { activeSessionId, setActiveSessionId } = useSessionStore();

  const { data: sessionsData } = useQuery({ queryKey: ["sessions"], queryFn: api.sessions.list });
  const sessions = sessionsData?.sessions ?? [];

  // Auto-pick first session if none active
  useEffect(() => {
    if (!activeSessionId && sessions.length > 0) {
      setActiveSessionId(sessions[0].id);
    }
    if (activeSessionId && !sessions.find((s) => s.id === activeSessionId)) {
      setActiveSessionId(sessions[0]?.id ?? null);
    }
  }, [activeSessionId, sessions, setActiveSessionId]);

  return (
    <div className="flex flex-col h-full">
      {/* Tabs header */}
      <div className="flex items-center gap-1 px-3 h-12 border-b border-border overflow-x-auto bg-card/30">
        {sessions.map((s) => (
          <SessionTab key={s.id} session={s} />
        ))}
        <div className="ml-1">
          <NewSessionDialog onCreated={(id) => setActiveSessionId(id)} />
        </div>
      </div>

      {activeSessionId ? (
        <ActiveChatPane sessionId={activeSessionId} />
      ) : (
        <EmptyState />
      )}
    </div>
  );
}

function SessionTab({ session }: { session: Session }) {
  const { activeSessionId, setActiveSessionId } = useSessionStore();
  const qc = useQueryClient();
  const active = activeSessionId === session.id;

  const deleteMut = useMutation({
    mutationFn: () => api.sessions.delete(session.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });

  return (
    <div
      className={cn(
        "group flex items-center gap-2 px-3 py-1.5 rounded-md cursor-pointer text-sm whitespace-nowrap shrink-0",
        active ? "bg-accent text-foreground" : "hover:bg-accent/50 text-muted-foreground",
      )}
      onClick={() => setActiveSessionId(session.id)}
    >
      <StatusDot status={session.status} />
      <span className="max-w-[200px] truncate">{session.title}</span>
      <button
        onClick={(e) => {
          e.stopPropagation();
          if (confirm(`Delete session "${session.title}"?`)) deleteMut.mutate();
        }}
        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "busy"
      ? "bg-warning animate-pulse-slow"
      : status === "failed"
        ? "bg-destructive"
        : status === "completed"
          ? "bg-success"
          : "bg-muted-foreground/50";
  return <span className={cn("w-1.5 h-1.5 rounded-full", color)} />;
}

function ActiveChatPane({ sessionId }: { sessionId: string }) {
  const qc = useQueryClient();
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: session, isLoading } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.sessions.get(sessionId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "busy" ? 2_000 : false;
    },
  });

  const sendMut = useMutation({
    mutationFn: (text: string) => api.sessions.sendMessage(sessionId, text),
    onSuccess: () => {
      setInput("");
      qc.invalidateQueries({ queryKey: ["session", sessionId] });
    },
  });

  const cancelMut = useMutation({
    mutationFn: () => api.sessions.cancel(sessionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session", sessionId] }),
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [session?.message_history?.length]);

  if (isLoading || !session) {
    return <div className="flex-1 p-6 text-muted-foreground">Loading…</div>;
  }

  const busy = session.status === "busy";

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Session header */}
      <div className="flex items-center justify-between px-5 py-2.5 border-b border-border">
        <div className="flex items-center gap-3 min-w-0">
          <StatusDot status={session.status} />
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{session.title}</div>
            <div className="text-xs text-muted-foreground truncate">
              {session.tool} · {session.cwd}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={busy ? "warning" : "secondary"}>{session.status}</Badge>
          {busy && (
            <Button size="sm" variant="outline" onClick={() => cancelMut.mutate()}>
              <StopCircle className="w-3.5 h-3.5" />
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {session.message_history.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground mt-8">
            Start the conversation…
          </div>
        ) : (
          session.message_history.map((msg, i) => <MessageBubble key={i} msg={msg} />)
        )}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
            <span>{session.current_task || "Working…"}</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border p-4">
        <div className="flex gap-2 items-end">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={busy ? "Session is busy…" : "Type a message…"}
            disabled={busy}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (input.trim()) sendMut.mutate(input.trim());
              }
            }}
            rows={2}
          />
          <Button
            size="icon"
            onClick={() => input.trim() && sendMut.mutate(input.trim())}
            disabled={!input.trim() || busy || sendMut.isPending}
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
        <div className="mt-1.5 text-[10px] text-muted-foreground">
          Enter to send · Shift+Enter for newline
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: { role: string; text: string; timestamp: number } }) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words",
          isUser ? "bg-primary text-primary-foreground" : "bg-accent text-foreground",
        )}
      >
        {msg.text}
        <div className={cn("text-[10px] mt-1 opacity-60", isUser ? "text-right" : "")}>
          {formatRelativeTime(msg.timestamp)}
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center flex-col gap-3 text-center px-6">
      <div className="w-12 h-12 rounded-full bg-accent flex items-center justify-center">
        <Plus className="w-5 h-5 text-muted-foreground" />
      </div>
      <div>
        <div className="text-sm font-medium">No session selected</div>
        <div className="text-xs text-muted-foreground mt-1">
          Create a session to start chatting
        </div>
      </div>
    </div>
  );
}
