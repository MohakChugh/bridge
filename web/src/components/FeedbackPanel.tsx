import { useState, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Textarea, Badge } from "./ui";
import { Send, MessageSquare, GitBranch, Bell, Clock, ShieldCheck, Sparkles, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface FeedbackEntry {
  role: "user" | "ai";
  text: string;
  nodesChanged?: number;
}

const NODE_ICONS: Record<string, any> = {
  start: () => <span className="w-3 h-3 rounded-full bg-success inline-block" />,
  end: () => <span className="w-3 h-3 rounded-full bg-destructive inline-block" />,
  prompt: MessageSquare,
  branch: GitBranch,
  merge: GitBranch,
  delay: Clock,
  approval: ShieldCheck,
  notify: Bell,
};

interface Props {
  workflowId: string | null;
  selectedNode: any | null;
  onRefined: (workflow: any, diff: any) => void;
  onClose: () => void;
}

export function FeedbackPanel({ workflowId, selectedNode, onRefined, onClose }: Props) {
  const [input, setInput] = useState("");
  const [scope, setScope] = useState<"node_and_downstream" | "node_only">("node_and_downstream");
  const [history, setHistory] = useState<FeedbackEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refineMut = useMutation({
    mutationFn: (feedback: string) => {
      if (!workflowId) throw new Error("No workflow");
      return api.workflows.refine(workflowId, {
        feedback,
        node_id: selectedNode?.id || null,
        scope: selectedNode ? scope : "whole",
      });
    },
    onSuccess: (data) => {
      const diff = data.diff;
      const changes = (diff.added?.length || 0) + (diff.changed?.length || 0) + (diff.removed?.length || 0);
      setHistory((prev) => [
        ...prev,
        {
          role: "ai",
          text: `Updated workflow: ${diff.added?.length || 0} added, ${diff.removed?.length || 0} removed, ${diff.changed?.length || 0} modified`,
          nodesChanged: changes,
        },
      ]);
      onRefined(data.workflow, data.diff);
    },
    onError: () => {
      setHistory((prev) => [...prev, { role: "ai", text: "Refinement failed — try rephrasing" }]);
    },
  });

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    setHistory((prev) => [...prev, { role: "user", text }]);
    setInput("");
    refineMut.mutate(text);
  };

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [history.length]);

  // Reset history when node changes
  useEffect(() => {
    setHistory([]);
  }, [selectedNode?.id]);

  const isNodeMode = !!selectedNode;
  const Icon = selectedNode ? (NODE_ICONS[selectedNode.type] || MessageSquare) : Sparkles;

  return (
    <div className="absolute right-0 top-0 bottom-0 w-80 bg-card border-l border-border shadow-xl z-10 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-12 border-b border-border shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          {typeof Icon === "function" && Icon.length === 0 ? (
            <Icon />
          ) : (
            <Icon className="w-4 h-4 text-primary shrink-0" />
          )}
          <span className="text-sm font-semibold truncate">
            {isNodeMode ? selectedNode.data?.prompt?.slice(0, 25) || selectedNode.type : "Refine Workflow"}
          </span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Node details (when node selected) */}
      {isNodeMode && (
        <div className="px-4 py-3 border-b border-border shrink-0 space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-[9px]">{selectedNode.type}</Badge>
            <span className="text-[10px] text-muted-foreground">{selectedNode.id}</span>
          </div>
          {selectedNode.data?.prompt && (
            <div className="text-xs text-foreground/80 bg-accent/50 rounded p-2 max-h-20 overflow-y-auto">
              {selectedNode.data.prompt}
            </div>
          )}
          {selectedNode.data?.condition && (
            <div className="text-xs text-foreground/80">
              <span className="text-muted-foreground">Condition: </span>{selectedNode.data.condition}
            </div>
          )}
          {selectedNode.data?.message && selectedNode.type !== "prompt" && (
            <div className="text-xs text-foreground/80">
              <span className="text-muted-foreground">Message: </span>{selectedNode.data.message}
            </div>
          )}
        </div>
      )}

      {/* Chat history */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {history.length === 0 && (
          <div className="text-center text-xs text-muted-foreground mt-8">
            {isNodeMode
              ? "Give feedback on this node. AI will update it + downstream nodes."
              : "Describe changes to the whole workflow. AI will modify the DAG."}
          </div>
        )}
        {history.map((entry, i) => (
          <div
            key={i}
            className={cn(
              "text-xs rounded-lg px-3 py-2 max-w-[95%]",
              entry.role === "user"
                ? "bg-primary text-primary-foreground ml-auto"
                : "bg-accent text-foreground",
            )}
          >
            {entry.text}
            {entry.nodesChanged !== undefined && (
              <div className="text-[10px] opacity-70 mt-0.5">
                {entry.nodesChanged} node(s) affected
              </div>
            )}
          </div>
        ))}
        {refineMut.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" />
            Refining workflow...
          </div>
        )}
      </div>

      {/* Scope selector (node mode only) */}
      {isNodeMode && (
        <div className="px-4 pb-2 shrink-0">
          <div className="flex gap-2 text-[10px]">
            <button
              onClick={() => setScope("node_only")}
              className={cn(
                "px-2 py-1 rounded border transition-colors",
                scope === "node_only" ? "bg-primary/15 border-primary text-primary" : "border-border text-muted-foreground",
              )}
            >
              This node only
            </button>
            <button
              onClick={() => setScope("node_and_downstream")}
              className={cn(
                "px-2 py-1 rounded border transition-colors",
                scope === "node_and_downstream" ? "bg-primary/15 border-primary text-primary" : "border-border text-muted-foreground",
              )}
            >
              Node + downstream
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-border p-3 shrink-0">
        <div className="flex gap-2 items-end">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={isNodeMode ? "Add deploy checks too..." : "Add error handling between steps 2 and 3..."}
            rows={2}
            disabled={refineMut.isPending}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <Button
            size="icon"
            onClick={handleSend}
            disabled={!input.trim() || refineMut.isPending || !workflowId}
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
