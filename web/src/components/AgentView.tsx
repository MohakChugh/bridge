import { useState, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAgentStore, type AgentEvent } from "@/stores/agentStore";
import { Card, CardContent, Badge, Button, Input, Textarea } from "./ui";
import { cn, formatRelativeTime, formatDuration } from "@/lib/utils";
import {
  Bot,
  Plus,
  Send,
  Loader2,
  CheckCircle2,
  XCircle,
  Pause,
  Play,
  Square,
  ShieldCheck,
  ShieldAlert,
  Clock,
  Wrench,
  MessageCircle,
  AlertTriangle,
  ChevronRight,
  Activity,
  Zap,
  BarChart3,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Status badge config                                                */
/* ------------------------------------------------------------------ */
const STATUS_STYLES: Record<string, string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-primary/20 text-primary",
  waiting_approval: "bg-amber-500/20 text-amber-500",
  completed: "bg-emerald-500/20 text-emerald-500",
  failed: "bg-destructive/20 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
  paused: "bg-amber-500/20 text-amber-500",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        STATUS_STYLES[status] || "bg-muted text-muted-foreground",
      )}
    >
      {status === "running" && <Loader2 className="w-3 h-3 animate-spin" />}
      {status === "waiting_approval" && <AlertTriangle className="w-3 h-3" />}
      {status === "completed" && <CheckCircle2 className="w-3 h-3" />}
      {status === "failed" && <XCircle className="w-3 h-3" />}
      {status === "paused" && <Pause className="w-3 h-3" />}
      {status.replace(/_/g, " ")}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Main AgentView                                                     */
/* ------------------------------------------------------------------ */
export function AgentView() {
  const qc = useQueryClient();
  const { mode, setMode, liveEvents } = useAgentStore();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");

  /* ---- Queries ---- */
  const { data: tasksData } = useQuery({
    queryKey: ["agent-tasks"],
    queryFn: () => api.agent.listTasks({ limit: 50 }),
    refetchInterval: 5000,
  });
  const tasks = tasksData?.tasks ?? [];

  const { data: selectedTask } = useQuery({
    queryKey: ["agent-task", selectedTaskId],
    queryFn: () => api.agent.getTask(selectedTaskId!),
    enabled: !!selectedTaskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" || status === "waiting_approval" ? 2000 : 10000;
    },
  });

  /* ---- Mutations ---- */
  const createTask = useMutation({
    mutationFn: (body: { title: string; description: string; mode?: string }) =>
      api.agent.createTask(body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      setSelectedTaskId(data.id);
      setShowNewForm(false);
      setNewTitle("");
      setNewDesc("");
    },
  });

  const approveTask = useMutation({
    mutationFn: (id: string) => api.agent.approve(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      if (selectedTaskId) qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
    },
  });

  const rejectTask = useMutation({
    mutationFn: (id: string) => api.agent.reject(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      if (selectedTaskId) qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
    },
  });

  const cancelTask = useMutation({
    mutationFn: (id: string) => api.agent.cancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      if (selectedTaskId) qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
    },
  });

  const pauseTask = useMutation({
    mutationFn: (id: string) => api.agent.pause(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      if (selectedTaskId) qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
    },
  });

  const resumeTask = useMutation({
    mutationFn: (id: string) => api.agent.resume(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      if (selectedTaskId) qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
    },
  });

  const setModeMutation = useMutation({
    mutationFn: (m: string) => api.agent.setMode(m),
    onSuccess: (data) => {
      setMode(data.mode as "safe" | "yellow");
    },
  });

  /* ---- Filtered events for selected task ---- */
  const taskEvents = useMemo(
    () =>
      selectedTaskId
        ? liveEvents.filter((e) => e.task_id === selectedTaskId)
        : [],
    [liveEvents, selectedTaskId],
  );

  /* ---- Audit log: last 10 tool calls ---- */
  const auditLog = useMemo(() => {
    return taskEvents
      .filter((e) => e.type === "agent.tool.start" || e.type === "agent.tool.result")
      .slice(-20)
      .reduce<{ tool: string; timestamp: number; success: boolean | null }[]>((acc, e) => {
        if (e.type === "agent.tool.start") {
          acc.push({ tool: e.data?.tool || "unknown", timestamp: e.timestamp, success: null });
        } else if (e.type === "agent.tool.result") {
          const last = [...acc].reverse().find((a) => a.success === null);
          if (last) last.success = e.data?.success !== false;
        }
        return acc;
      }, [])
      .slice(-10);
  }, [taskEvents]);

  return (
    <div className="h-full flex overflow-hidden">
      {/* ============ LEFT PANEL: task list ============ */}
      <div className="w-64 shrink-0 border-r border-border flex flex-col bg-card/20">
        {/* Header + mode toggle */}
        <div className="p-3 border-b border-border space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot className="w-4 h-4 text-primary" />
              <span className="font-semibold text-sm">Agent Brain</span>
            </div>
            <button
              onClick={() => setModeMutation.mutate(mode === "safe" ? "yellow" : "safe")}
              className={cn(
                "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold transition-colors",
                mode === "safe"
                  ? "bg-emerald-500/20 text-emerald-500"
                  : "bg-amber-500/20 text-amber-500",
              )}
              title={mode === "safe" ? "Safe mode: requires approval" : "Yellow mode: auto-approve safe tools"}
            >
              {mode === "safe" ? (
                <><ShieldCheck className="w-3 h-3" /> Safe</>
              ) : (
                <><ShieldAlert className="w-3 h-3" /> Yellow</>
              )}
            </button>
          </div>

          <Button
            size="sm"
            className="w-full"
            onClick={() => setShowNewForm(!showNewForm)}
          >
            <Plus className="w-3.5 h-3.5" />
            New Task
          </Button>

          {/* Inline new task form */}
          {showNewForm && (
            <div className="space-y-2">
              <Input
                placeholder="Task title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                className="text-xs"
              />
              <Textarea
                placeholder="Description..."
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                rows={3}
                className="text-xs"
              />
              <div className="flex gap-1">
                <Button
                  size="sm"
                  className="flex-1"
                  disabled={!newTitle.trim() || createTask.isPending}
                  onClick={() =>
                    createTask.mutate({
                      title: newTitle.trim(),
                      description: newDesc.trim(),
                      mode,
                    })
                  }
                >
                  {createTask.isPending ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Send className="w-3 h-3" />
                  )}
                  Create
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setShowNewForm(false);
                    setNewTitle("");
                    setNewDesc("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Task list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {tasks.length === 0 && (
            <div className="text-center text-xs text-muted-foreground py-8">
              No tasks yet
            </div>
          )}
          {tasks.map((task: any) => {
            const active = task.id === selectedTaskId;
            const progress = task.progress?.percentage ?? 0;
            return (
              <button
                key={task.id}
                onClick={() => setSelectedTaskId(task.id)}
                className={cn(
                  "w-full text-left rounded-md p-2 transition-colors",
                  active
                    ? "bg-primary/15 border border-primary/30"
                    : "hover:bg-accent/50 border border-transparent",
                )}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-medium truncate flex-1">
                    {task.title}
                  </span>
                  <StatusBadge status={task.status} />
                </div>
                {task.turns != null && (
                  <div className="text-[10px] text-muted-foreground mt-1">
                    {task.turns} turns
                  </div>
                )}
                {task.status === "running" && progress > 0 && (
                  <div className="mt-1.5 h-1 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ============ CENTER PANEL: task detail + event stream ============ */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {!selectedTaskId || !selectedTask ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center space-y-2">
              <Bot className="w-10 h-10 mx-auto opacity-30" />
              <p className="text-sm">Select or create a task</p>
            </div>
          </div>
        ) : (
          <>
            {/* Task header */}
            <div className="p-4 border-b border-border bg-card/30 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <h2 className="font-semibold text-sm truncate">{selectedTask.title}</h2>
                  <StatusBadge status={selectedTask.status} />
                </div>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground shrink-0">
                  {selectedTask.turns != null && (
                    <span className="flex items-center gap-0.5">
                      <Activity className="w-3 h-3" /> {selectedTask.turns} turns
                    </span>
                  )}
                  {selectedTask.created_at && (
                    <span className="flex items-center gap-0.5">
                      <Clock className="w-3 h-3" /> {formatDuration(selectedTask.created_at)}
                    </span>
                  )}
                  {selectedTask.cost != null && (
                    <span className="flex items-center gap-0.5">
                      <Zap className="w-3 h-3" /> ${selectedTask.cost.toFixed(4)}
                    </span>
                  )}
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-1.5">
                {(selectedTask.status === "running" || selectedTask.status === "waiting_approval") && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => pauseTask.mutate(selectedTask.id)}
                    disabled={pauseTask.isPending}
                  >
                    <Pause className="w-3 h-3" /> Pause
                  </Button>
                )}
                {selectedTask.status === "paused" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => resumeTask.mutate(selectedTask.id)}
                    disabled={resumeTask.isPending}
                  >
                    <Play className="w-3 h-3" /> Resume
                  </Button>
                )}
                {(selectedTask.status === "running" || selectedTask.status === "paused" || selectedTask.status === "waiting_approval") && (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => cancelTask.mutate(selectedTask.id)}
                    disabled={cancelTask.isPending}
                  >
                    <Square className="w-3 h-3" /> Cancel
                  </Button>
                )}
              </div>
            </div>

            {/* Event stream */}
            <EventStream
              events={taskEvents}
              task={selectedTask}
              onApprove={() => approveTask.mutate(selectedTask.id)}
              onReject={() => rejectTask.mutate(selectedTask.id)}
              approving={approveTask.isPending}
              rejecting={rejectTask.isPending}
            />
          </>
        )}
      </div>

      {/* ============ RIGHT PANEL: context ============ */}
      {selectedTask && (
        <div className="w-72 shrink-0 border-l border-border bg-card/20 overflow-y-auto">
          {/* Description */}
          <div className="p-4 border-b border-border">
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              Description
            </h4>
            <p className="text-xs text-foreground whitespace-pre-wrap">
              {selectedTask.description || "No description provided"}
            </p>
          </div>

          {/* Progress */}
          {selectedTask.progress && (
            <div className="p-4 border-b border-border">
              <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                Progress
              </h4>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span>{selectedTask.progress.percentage ?? 0}%</span>
                  <span className="text-muted-foreground">{selectedTask.progress.message || ""}</span>
                </div>
                <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all"
                    style={{ width: `${selectedTask.progress.percentage ?? 0}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Audit log */}
          <div className="p-4 border-b border-border">
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              Audit Log
            </h4>
            {auditLog.length === 0 ? (
              <p className="text-[10px] text-muted-foreground">No tool calls yet</p>
            ) : (
              <div className="space-y-1">
                {auditLog.map((entry, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[10px]">
                    {entry.success === null ? (
                      <Loader2 className="w-2.5 h-2.5 animate-spin text-primary shrink-0" />
                    ) : entry.success ? (
                      <CheckCircle2 className="w-2.5 h-2.5 text-emerald-500 shrink-0" />
                    ) : (
                      <XCircle className="w-2.5 h-2.5 text-destructive shrink-0" />
                    )}
                    <span className="font-mono truncate flex-1">{entry.tool}</span>
                    <span className="text-muted-foreground shrink-0">
                      {new Date(entry.timestamp * 1000).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Stats */}
          <div className="p-4">
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              Stats
            </h4>
            <div className="space-y-1.5 text-xs">
              <StatRow label="Turns" value={selectedTask.turns ?? 0} icon={Activity} />
              <StatRow
                label="Cost"
                value={selectedTask.cost != null ? `$${selectedTask.cost.toFixed(4)}` : "--"}
                icon={BarChart3}
              />
              <StatRow
                label="Elapsed"
                value={selectedTask.created_at ? formatDuration(selectedTask.created_at) : "--"}
                icon={Clock}
              />
              <StatRow label="Mode" value={selectedTask.mode || mode} icon={ShieldCheck} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Conversation stream — shows persisted messages + audit from API    */
/* ------------------------------------------------------------------ */
function EventStream({
  events,
  task,
  onApprove,
  onReject,
  approving,
  rejecting,
}: {
  events: AgentEvent[];
  task: any;
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
  rejecting: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [expandedIdx, setExpandedIdx] = useState<Set<number>>(new Set());

  const messages: any[] = task.messages || [];
  const audit: any[] = task.audit || [];

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length, events.length, autoScroll]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  }

  function toggleExpand(idx: number) {
    setExpandedIdx((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  }

  const isTerminal = ["completed", "failed", "cancelled"].includes(task.status);
  const isRunning = task.status === "running" || task.status === "waiting_approval";

  return (
    <div className="flex-1 relative flex flex-col overflow-hidden">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-4 space-y-2"
      >
        {messages.length === 0 && !isTerminal && (
          <div className="text-center text-xs text-muted-foreground py-8">
            {task.status === "pending"
              ? "Waiting for agent to start..."
              : isRunning
              ? "Agent is thinking..."
              : "No conversation yet."}
          </div>
        )}

        {/* Render each message from the stored conversation */}
        {messages.map((msg: any, idx: number) => {
          const role = msg.role || "";
          const content = msg.content || "";
          const isExpanded = expandedIdx.has(idx);
          const isLong = content.length > 400;
          const displayText = isExpanded || !isLong ? content : content.slice(0, 400) + "…";

          if (role === "system") {
            return (
              <div key={idx} className="p-2 rounded-md bg-muted/30 border border-border/50">
                <div className="flex items-center gap-1.5 mb-1">
                  <Bot className="w-3 h-3 text-muted-foreground" />
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">System Prompt</span>
                  <button onClick={() => toggleExpand(idx)} className="text-[10px] text-primary ml-auto">
                    {isExpanded ? "Collapse" : "Expand"}
                  </button>
                </div>
                {isExpanded && (
                  <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap max-h-60 overflow-y-auto font-mono">
                    {content}
                  </pre>
                )}
              </div>
            );
          }

          if (role === "user") {
            return (
              <div key={idx} className="p-3 rounded-lg bg-primary/10 border border-primary/20">
                <div className="flex items-center gap-1.5 mb-1">
                  <Send className="w-3 h-3 text-primary" />
                  <span className="text-[10px] font-semibold text-primary">Task Input</span>
                </div>
                <p className="text-xs text-foreground whitespace-pre-wrap">{displayText}</p>
                {isLong && (
                  <button onClick={() => toggleExpand(idx)} className="text-[10px] text-primary mt-1">
                    {isExpanded ? "Show less" : "Show more"}
                  </button>
                )}
              </div>
            );
          }

          if (role === "assistant") {
            return (
              <div key={idx} className="p-3 rounded-lg bg-card border border-border">
                <div className="flex items-center gap-1.5 mb-1">
                  <MessageCircle className="w-3 h-3 text-muted-foreground" />
                  <span className="text-[10px] font-semibold text-muted-foreground">Agent Thought · Turn {Math.ceil((idx) / 2)}</span>
                </div>
                <p className="text-xs text-foreground whitespace-pre-wrap">{displayText}</p>
                {isLong && (
                  <button onClick={() => toggleExpand(idx)} className="text-[10px] text-primary mt-1">
                    {isExpanded ? "Show less" : "Show more"}
                  </button>
                )}
              </div>
            );
          }

          if (role === "tool_result") {
            const isError = msg.is_error;
            return (
              <div key={idx} className={cn(
                "p-2 rounded-md border ml-6",
                isError ? "bg-destructive/5 border-destructive/20" : "bg-emerald-500/5 border-emerald-500/20",
              )}>
                <div className="flex items-center gap-1.5 mb-1">
                  {isError ? (
                    <XCircle className="w-3 h-3 text-destructive" />
                  ) : (
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                  )}
                  <span className={cn("text-[10px] font-semibold", isError ? "text-destructive" : "text-emerald-500")}>
                    Tool Result {msg.tool_use_id ? `[${msg.tool_use_id}]` : ""}
                  </span>
                </div>
                <pre className={cn(
                  "text-[10px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto",
                  isError ? "text-destructive/80" : "text-emerald-400/80",
                )}>
                  {displayText}
                </pre>
                {isLong && (
                  <button onClick={() => toggleExpand(idx)} className="text-[10px] text-primary mt-1">
                    {isExpanded ? "Show less" : "Show more"}
                  </button>
                )}
              </div>
            );
          }

          return (
            <div key={idx} className="p-2 rounded-md bg-muted/20 border border-border/30 text-[10px] text-muted-foreground font-mono">
              {role}: {displayText.slice(0, 200)}
            </div>
          );
        })}

        {/* Live events overlay for real-time updates not yet in messages */}
        {isRunning && events.length > 0 && (
          <div className="mt-2 space-y-1 border-t border-border/30 pt-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-semibold mb-1">Live</div>
            {events.slice(-10).map((e) => (
              <LiveEventItem key={e.id} event={e} onApprove={onApprove} onReject={onReject} approving={approving} rejecting={rejecting} />
            ))}
          </div>
        )}

        {/* Approval prompt at bottom if waiting */}
        {task.status === "waiting_approval" && (
          <div className="my-3 p-3 rounded-md bg-amber-500/10 border border-amber-500/20">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500 mb-2">
              <AlertTriangle className="w-3.5 h-3.5" /> Waiting for Approval
            </div>
            {audit.length > 0 && audit[0].tool && (
              <div className="text-xs space-y-1 mb-3">
                <div>
                  <span className="text-muted-foreground">Tool:</span>{" "}
                  <span className="font-mono font-medium">{audit[0].tool}</span>
                </div>
                {audit[0].args && (
                  <pre className="text-[10px] font-mono text-muted-foreground bg-background/50 rounded p-1.5 overflow-x-auto max-h-24 overflow-y-auto">
                    {audit[0].args}
                  </pre>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <Button size="sm" onClick={onApprove} disabled={approving} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                {approving ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                Approve
              </Button>
              <Button size="sm" variant="destructive" onClick={onReject} disabled={rejecting}>
                {rejecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
                Reject
              </Button>
            </div>
          </div>
        )}

        {/* Terminal results */}
        {task.status === "completed" && task.result && (
          <div className="mt-3 p-3 rounded-md bg-emerald-500/10 border border-emerald-500/20">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-500 mb-1">
              <CheckCircle2 className="w-3.5 h-3.5" /> Task Completed
            </div>
            <p className="text-xs text-foreground whitespace-pre-wrap">
              {typeof task.result === "string" ? task.result : JSON.stringify(task.result, null, 2)}
            </p>
          </div>
        )}

        {task.status === "failed" && task.error && (
          <div className="mt-3 p-3 rounded-md bg-destructive/10 border border-destructive/20">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-destructive mb-1">
              <XCircle className="w-3.5 h-3.5" /> Task Failed
            </div>
            <p className="text-xs text-destructive whitespace-pre-wrap">
              {typeof task.error === "string" ? task.error : JSON.stringify(task.error, null, 2)}
            </p>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Auto-scroll indicator */}
      {!autoScroll && (
        <button
          onClick={() => {
            setAutoScroll(true);
            bottomRef.current?.scrollIntoView({ behavior: "smooth" });
          }}
          className="absolute bottom-4 right-4 bg-primary text-primary-foreground rounded-full px-3 py-1 text-xs shadow-lg"
        >
          Scroll to bottom
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Live event item (for real-time WS events not yet in messages)      */
/* ------------------------------------------------------------------ */
function LiveEventItem({
  event,
  onApprove,
  onReject,
  approving,
  rejecting,
}: {
  event: AgentEvent;
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
  rejecting: boolean;
}) {
  const t = event.type;
  const ts = new Date(event.timestamp * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  if (t === "agent.thought") {
    return (
      <div className="flex items-start gap-2 py-0.5">
        <MessageCircle className="w-3 h-3 text-muted-foreground mt-0.5 shrink-0" />
        <p className="text-[10px] text-muted-foreground flex-1 truncate">
          {(event.data?.text || "").slice(0, 120)}
        </p>
        <span className="text-[9px] text-muted-foreground shrink-0">{ts}</span>
      </div>
    );
  }

  if (t === "agent.tool.start") {
    return (
      <div className="flex items-start gap-2 py-0.5">
        <Wrench className="w-3 h-3 text-primary mt-0.5 shrink-0" />
        <span className="text-[10px] font-mono text-primary flex-1 truncate">
          {event.data?.tool}({JSON.stringify(event.data?.args || {}).slice(0, 80)})
        </span>
        <span className="text-[9px] text-muted-foreground shrink-0">{ts}</span>
      </div>
    );
  }

  if (t === "agent.tool.result") {
    const ok = event.data?.success !== false;
    return (
      <div className="flex items-start gap-2 py-0.5">
        {ok ? <CheckCircle2 className="w-3 h-3 text-emerald-500 mt-0.5 shrink-0" /> : <XCircle className="w-3 h-3 text-destructive mt-0.5 shrink-0" />}
        <p className={cn("text-[10px] font-mono flex-1 truncate", ok ? "text-emerald-400" : "text-destructive")}>
          {(event.data?.preview || event.data?.error || "done").slice(0, 120)}
        </p>
        <span className="text-[9px] text-muted-foreground shrink-0">{ts}</span>
      </div>
    );
  }

  if (t === "agent.progress") {
    return (
      <div className="flex items-center gap-2 py-0.5">
        <Loader2 className="w-3 h-3 text-primary animate-spin shrink-0" />
        <span className="text-[10px] text-muted-foreground flex-1">{event.data?.msg || event.data?.message || `${event.data?.pct || 0}%`}</span>
        <span className="text-[9px] text-muted-foreground shrink-0">{ts}</span>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2 py-0.5 opacity-50">
      <ChevronRight className="w-3 h-3 text-muted-foreground mt-0.5 shrink-0" />
      <span className="text-[10px] font-mono text-muted-foreground flex-1 truncate">
        {t}: {JSON.stringify(event.data).slice(0, 80)}
      </span>
      <span className="text-[9px] text-muted-foreground shrink-0">{ts}</span>
    </div>
  );
}


/* ------------------------------------------------------------------ */
/*  Stat row helper                                                    */
/* ------------------------------------------------------------------ */
function StatRow({ label, value, icon: Icon }: { label: string; value: string | number; icon: any }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-1.5 text-muted-foreground">
        <Icon className="w-3 h-3" /> {label}
      </span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
