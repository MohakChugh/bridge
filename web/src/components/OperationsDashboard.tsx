import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button } from "./ui";
import { formatRelativeTime, cn } from "@/lib/utils";
import {
  Activity,
  GitBranch,
  MessageSquare,
  Eye,
  Calendar,
  Bell,
  Play,
  CheckCircle2,
  XCircle,
  Loader2,
  Pause,
  ArrowRight,
} from "lucide-react";

export function OperationsDashboard() {
  const { setView, setActiveWorkflowId, setActiveRunId, setActiveSessionId } = useSessionStore();

  const { data, isLoading } = useQuery({
    queryKey: ["operations"],
    queryFn: () => api.activity().then(() => null).catch(() => null),
    enabled: false,
  });

  const { data: ops } = useQuery({
    queryKey: ["operations-data"],
    queryFn: async () => {
      const res = await fetch("/api/operations");
      return res.json();
    },
    refetchInterval: 5000,
  });

  if (!ops) return <div className="p-8 text-muted-foreground">Loading...</div>;

  const runningWfs = ops.running_workflows ?? [];
  const recentRuns = ops.recent_runs ?? [];
  const scheduledWfs = ops.scheduled_workflows ?? [];
  const sessions = ops.sessions ?? { total: 0, busy: 0, items: [] };
  const watches = ops.watches ?? { total: 0, active: [] };
  const schedules = ops.schedules ?? { total: 0, active: [] };

  const totalRunning = runningWfs.length + sessions.busy;

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Operations</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {totalRunning > 0 ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin text-warning" />
              <span className="text-warning font-medium">{totalRunning} running</span> across workflows + sessions
            </span>
          ) : (
            "All systems idle"
          )}
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MiniStat icon={GitBranch} label="Workflows" value={recentRuns.length} sub={`${runningWfs.length} running`} />
        <MiniStat icon={MessageSquare} label="Sessions" value={sessions.total} sub={`${sessions.busy} busy`} />
        <MiniStat icon={Eye} label="Watches" value={watches.total} sub={`${watches.active.length} active`} />
        <MiniStat icon={Calendar} label="Schedules" value={schedules.total} sub={`${schedules.active.length} active`} />
        <MiniStat icon={Bell} label="Reminders" value={ops.reminders?.total ?? 0} sub="" />
      </div>

      {/* Running Now */}
      {(runningWfs.length > 0 || sessions.busy > 0) && (
        <section>
          <SectionHead icon={Activity} title="Running Now" count={totalRunning} />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {runningWfs.map((r: any) => {
              const total = Object.keys(r.node_states || {}).length;
              const done = Object.values(r.node_states || {}).filter((ns: any) => ns.status === "completed").length;
              const pct = total > 0 ? Math.round((done / total) * 100) : 0;
              const currentNode = Object.entries(r.node_states || {}).find(([_, ns]: any) => ns.status === "running");
              return (
                <button key={r.id} className="text-left" onClick={() => {
                  setActiveWorkflowId(r.workflow_id);
                  setActiveRunId(r.id);
                  setView("workflow-runner");
                }}>
                  <Card className="hover:border-primary/50 transition-colors h-full">
                    <CardContent className="pt-4">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium truncate">{r.workflow_name}</span>
                        <Badge variant={r.status === "paused" ? "warning" : "warning"}>
                          {r.status === "paused" ? <><Pause className="w-3 h-3" /> paused</> : <><Loader2 className="w-3 h-3 animate-spin" /> running</>}
                        </Badge>
                      </div>
                      <div className="mt-2 h-1.5 rounded-full bg-muted overflow-hidden">
                        <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${pct}%` }} />
                      </div>
                      <div className="flex items-center justify-between mt-1.5 text-[10px] text-muted-foreground">
                        <span>{done}/{total} nodes ({pct}%)</span>
                        {currentNode && <span>→ {currentNode[0]}</span>}
                      </div>
                    </CardContent>
                  </Card>
                </button>
              );
            })}
            {sessions.items.filter((s: any) => s.status === "busy").map((s: any) => (
              <button key={s.id} className="text-left" onClick={() => {
                setActiveSessionId(s.id);
                setView("chat");
              }}>
                <Card className="hover:border-primary/50 transition-colors h-full">
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium truncate">{s.title}</span>
                      <Badge variant="secondary">{s.tool}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1.5 truncate">{s.current_task || "Working..."}</p>
                  </CardContent>
                </Card>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Run History */}
      <section>
        <SectionHead icon={GitBranch} title="Workflow Run History" count={recentRuns.length} />
        <Card>
          <CardContent className="py-0">
            {recentRuns.length === 0 ? (
              <div className="py-8 text-center text-xs text-muted-foreground">No workflow runs yet</div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="text-left py-2 font-medium">Workflow</th>
                    <th className="text-left py-2 font-medium">Params</th>
                    <th className="text-left py-2 font-medium">Status</th>
                    <th className="text-left py-2 font-medium">Nodes</th>
                    <th className="text-left py-2 font-medium">Duration</th>
                    <th className="text-left py-2 font-medium">When</th>
                    <th className="py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.map((r: any) => {
                    const total = Object.keys(r.node_states || {}).length;
                    const done = Object.values(r.node_states || {}).filter((ns: any) => ["completed", "skipped"].includes(ns.status)).length;
                    const dur = r.completed_at && r.started_at ? Math.round(r.completed_at - r.started_at) : null;
                    return (
                      <tr key={r.id} className="border-b border-border/50 hover:bg-accent/30 cursor-pointer"
                        onClick={() => {
                          setActiveWorkflowId(r.workflow_id);
                          setActiveRunId(r.id);
                          setView("workflow-runner");
                        }}
                      >
                        <td className="py-2 font-medium">
                          {r.workflow_name}
                          {r.schedule_label && <span className="text-[10px] text-muted-foreground ml-1">({r.schedule_label})</span>}
                        </td>
                        <td className="py-2">
                          <div className="flex gap-1 flex-wrap">
                            {r.params && Object.entries(r.params).slice(0, 3).map(([k, v]: [string, any]) => (
                              <span key={k} className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] font-medium">
                                {String(v).length > 15 ? String(v).slice(0, 15) + "…" : String(v)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2"><RunBadge status={r.status} /></td>
                        <td className="py-2 text-muted-foreground">{done}/{total}</td>
                        <td className="py-2 text-muted-foreground">{dur ? `${Math.floor(dur / 60)}m ${dur % 60}s` : "—"}</td>
                        <td className="py-2 text-muted-foreground">{formatRelativeTime(r.started_at)}</td>
                        <td className="py-2"><ArrowRight className="w-3 h-3 text-muted-foreground" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </section>

      {/* Scheduled Workflows */}
      {scheduledWfs.length > 0 && (
        <section>
          <SectionHead icon={Calendar} title="Scheduled Workflows" count={scheduledWfs.length} />
          <div className="space-y-2">
            {scheduledWfs.map((wf: any) => (
              <Card key={wf.id}>
                <CardContent className="py-3 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">{wf.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {wf.schedule?.human || wf.schedule?.cron} · {wf.tool}
                    </div>
                  </div>
                  <Badge variant="success">scheduled</Badge>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      {/* Active watches + schedules summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {watches.active.length > 0 && (
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Eye className="w-3.5 h-3.5" /> Active Watches</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-1.5 text-xs">
                {watches.active.map((w: any) => (
                  <li key={w.id} className="flex items-center justify-between">
                    <span className="truncate">{w.description || w.target}</span>
                    <span className="text-muted-foreground">{w.interval_minutes}m</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
        {schedules.active.length > 0 && (
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Calendar className="w-3.5 h-3.5" /> Active Schedules</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-1.5 text-xs">
                {schedules.active.map((s: any) => (
                  <li key={s.id} className="flex items-center justify-between">
                    <span className="truncate">{s.prompt?.slice(0, 50)}</span>
                    <span className="text-muted-foreground">{s.human}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function MiniStat({ icon: Icon, label, value, sub }: { icon: any; label: string; value: number; sub: string }) {
  return (
    <Card>
      <CardContent className="pt-3 pb-3 flex items-center gap-3">
        <Icon className="w-4 h-4 text-muted-foreground shrink-0" />
        <div>
          <div className="text-lg font-bold leading-none">{value}</div>
          <div className="text-[10px] text-muted-foreground">{label}{sub ? ` · ${sub}` : ""}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function SectionHead({ icon: Icon, title, count }: { icon: any; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
      <Icon className="w-3.5 h-3.5" />
      {title}
      {count !== undefined && <span className="text-[10px] opacity-70">({count})</span>}
    </div>
  );
}

function RunBadge({ status }: { status: string }) {
  if (status === "completed") return <span className="inline-flex items-center gap-1 text-success"><CheckCircle2 className="w-3 h-3" /> done</span>;
  if (status === "failed") return <span className="inline-flex items-center gap-1 text-destructive"><XCircle className="w-3 h-3" /> failed</span>;
  if (status === "running") return <span className="inline-flex items-center gap-1 text-warning"><Loader2 className="w-3 h-3 animate-spin" /> running</span>;
  if (status === "paused") return <span className="inline-flex items-center gap-1 text-warning"><Pause className="w-3 h-3" /> paused</span>;
  if (status === "aborted") return <span className="inline-flex items-center gap-1 text-destructive"><XCircle className="w-3 h-3" /> aborted</span>;
  return <span className="text-muted-foreground">{status}</span>;
}
