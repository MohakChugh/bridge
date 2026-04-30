import { useState, useRef, useEffect, useCallback } from "react";
import { MessageSquarePlus, Brain, X, Trash2, Send, Loader2, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui";
import { Badge } from "@/components/ui";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChatStore, type ChatAction } from "@/stores/chatStore";
import { useSessionStore } from "@/stores/sessionStore";
import { api } from "@/api/client";

function ThinkingIndicator() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t1 = setTimeout(() => setStage(1), 3000);
    const t2 = setTimeout(() => setStage(2), 8000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);
  const labels = ["Thinking...", "Searching knowledge base...", "Generating answer..."];
  return (
    <div className="flex items-center gap-2 px-4 py-2">
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
      <span className="text-xs text-muted-foreground">{labels[stage]}</span>
    </div>
  );
}

function SourceBadges({ sources }: { sources: { collection: string; text_preview: string; score: number }[] }) {
  if (!sources?.length) return null;
  return (
    <div className="mt-2.5 pt-2 border-t border-border/30">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Sources</span>
      <div className="flex flex-wrap gap-1 mt-1">
        {sources.map((s, i) => (
          <Badge key={i} variant="outline" className="text-[10px] py-0.5 px-2 gap-1" title={s.text_preview}>
            <span className="text-primary/80">{s.collection}</span>
            <span className="opacity-50">{(s.score * 100).toFixed(0)}%</span>
          </Badge>
        ))}
      </div>
    </div>
  );
}

function ActionButtons({
  actions,
  onExecute,
}: {
  actions: ChatAction[];
  onExecute: (a: ChatAction) => void;
}) {
  const [loading, setLoading] = useState<string | null>(null);
  if (!actions?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {actions.map((a, i) => (
        <Button
          key={i}
          variant="secondary"
          size="sm"
          disabled={loading !== null}
          onClick={async () => {
            setLoading(a.label);
            await onExecute(a);
            setLoading(null);
          }}
        >
          {loading === a.label && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
          {a.label}
        </Button>
      ))}
    </div>
  );
}

const SUGGESTIONS = [
  "What's in my knowledge base?",
  "Show running jobs",
  "Refresh all documents",
];

export function RagChatOverlay() {
  const { isOpen, messages, isLoading, toggle, close, addMessage, setLoading, clearHistory } =
    useChatStore();
  const setView = useSessionStore((s) => s.setView);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, isLoading]);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        toggle();
      }
      if (e.key === "Escape" && isOpen) {
        close();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, toggle, close]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isLoading) return;
      addMessage({ role: "user", text: text.trim() });
      setInput("");
      setLoading(true);
      try {
        const history = useChatStore
          .getState()
          .messages.map((m) => ({ role: m.role, text: m.text }));
        const res = await api.chat.send(text.trim(), history);
        addMessage({
          role: "assistant",
          text: res.response,
          sources: res.sources,
          actions: res.actions,
        });
      } catch (e: any) {
        addMessage({
          role: "assistant",
          text: `Error: ${e.message || "Request failed"}`,
        });
      } finally {
        setLoading(false);
      }
    },
    [isLoading, addMessage, setLoading],
  );

  const executeAction = useCallback(
    async (action: ChatAction) => {
      try {
        const res = await api.chat.execute(action.type, action.params);
        if (res.navigate) {
          setView(res.navigate as any);
        }
        addMessage({ role: "assistant", text: res.result });
      } catch (e: any) {
        addMessage({ role: "assistant", text: `Action failed: ${e.message}` });
      }
    },
    [addMessage, setView],
  );

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <>
      {/* FAB toggle */}
      <button
        onClick={toggle}
        className="fixed bottom-6 right-6 z-50 w-12 h-12 rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-all hover:scale-105 flex items-center justify-center"
        title="Ask Bridge (⌘K)"
      >
        {isOpen ? <X className="w-5 h-5" /> : <MessageSquarePlus className="w-5 h-5" />}
      </button>

      {/* Chat panel */}
      <div
        className="fixed bottom-20 right-6 z-40 w-[420px] h-[560px] flex flex-col border border-border rounded-xl bg-card shadow-2xl transition-all duration-200 ease-out"
        style={{
          transform: isOpen ? "translateY(0)" : "translateY(20px)",
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? "auto" : "none",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-primary" />
            <span className="font-medium text-sm">Ask Bridge</span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => {
                if (messages.length && confirm("Clear chat history?")) clearHistory();
              }}
              title="Clear history"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={close} title="Close">
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
          {messages.length === 0 && !isLoading && (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
              <Brain className="w-10 h-10 opacity-30" />
              <p className="text-sm">Ask anything about your knowledge base</p>
              <div className="flex flex-wrap gap-2 justify-center">
                {SUGGESTIONS.map((s) => (
                  <Button
                    key={s}
                    variant="outline"
                    size="sm"
                    className="text-xs"
                    onClick={() => sendMessage(s)}
                  >
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {m.role === "user" ? (
                <div className="max-w-[85%] rounded-2xl px-3.5 py-2 text-sm bg-primary text-primary-foreground">
                  <div className="whitespace-pre-wrap break-words">{m.text}</div>
                </div>
              ) : (
                <div className="max-w-[90%] rounded-2xl px-3.5 py-2.5 bg-accent text-foreground">
                  <ReactMarkdown
                    className="chat-markdown"
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ href, children }) => (
                        <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5">
                          {children}
                          <ExternalLink className="w-2.5 h-2.5 inline opacity-50" />
                        </a>
                      ),
                    }}
                  >
                    {m.text}
                  </ReactMarkdown>
                  {m.sources && <SourceBadges sources={m.sources} />}
                  {m.actions && (
                    <ActionButtons actions={m.actions} onExecute={executeAction} />
                  )}
                </div>
              )}
            </div>
          ))}

          {isLoading && <ThinkingIndicator />}
        </div>

        {/* Input */}
        <div className="px-3 pb-3 pt-1 border-t border-border shrink-0">
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask a question..."
              disabled={isLoading}
              rows={1}
              className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50 max-h-24"
              style={{ minHeight: "36px" }}
            />
            <Button
              size="icon"
              disabled={isLoading || !input.trim()}
              onClick={() => sendMessage(input)}
              className="shrink-0"
            >
              <Send className="w-4 h-4" />
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground mt-1 text-center">
            Enter to send · Shift+Enter for newline · ⌘K to toggle
          </p>
        </div>
      </div>
    </>
  );
}
