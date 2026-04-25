import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { ArrowLeft, BarChart3, CheckCircle2, XCircle, Clock, TrendingUp, AlertTriangle } from "lucide-react";

export function WorkflowAnalytics() {
  const { activeWorkflowId, setView } = useSessionStore();

  const { data: wf } = useQuery({
    queryKey: ["workflow", activeWorkflowId],
    queryFn: () => activeWorkflowId ? api.workflows.get(activeWorkflowId) : null,
    enabled: !!activeWorkflowId,
  });

  const { data: analytics, isLoading } = useQuery({
    queryKey: ["workflow-analytics", activeWorkflowId],
    queryFn: () => activeWorkflowId ? api.workflows.analytics(activeWorkflowId) : null,
    enabled: !!activeWorkflowId,
  });

  if (isLoading || !analytics) {
    return <div className="p-8 text-muted-foreground">Loading analytics...</div>;
  }

  const maxDayRuns = Math.max(...(analytics.runs_by_day || []).map((d: any) => d.success + d.failed), 1);

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full max-w-5xl">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => setView("workflows")}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{wf?.name || "Workflow"} — Analytics</h1>
          <p className="text-xs text-muted-foreground">{analytics.total_runs} total runs</p>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={BarChart3} label="Total Runs" value={analytics.total_runs} />
        <StatCard
          icon={CheckCircle2}
          label="Success Rate"
          value={`${analytics.success_rate}%`}
          color={analytics.success_rate >= 80 ? "text-success" : analytics.success_rate >= 50 ? "text-warning" : "text-destructive"}
        />
        <StatCard
          icon={Clock}
          label="Avg Duration"
          value={analytics.avg_duration_seconds >= 60 ? `${Math.floor(analytics.avg_duration_seconds / 60)}m ${analytics.avg_duration_seconds % 60}s` : `${analytics.avg_duration_seconds}s`}
        />
        <StatCard
          icon={AlertTriangle}
          label="Last Failure"
          value={analytics.last_failure ? formatRelativeTime(analytics.last_failure.when) : "None"}
          color={analytics.last_failure ? "text-destructive" : "text-success"}
        />
      </div>

      {/* Run timeline */}
      {analytics.runs_by_day?.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4" />
              Run Timeline
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-end gap-1 h-32">
              {analytics.runs_by_day.map((day: any) => {
                const total = day.success + day.failed;
                const height = (total / maxDayRuns) * 100;
                const successPct = total > 0 ? (day.success / total) * 100 : 0;
                return (
                  <div key={day.date} className="flex-1 flex flex-col items-center gap-0.5" title={`${day.date}: ${day.success} ok, ${day.failed} fail`}>
                    <div className="w-full relative" style={{ height: `${height}%`, minHeight: total > 0 ? 4 : 0 }}>
                      <div className="absolute bottom-0 w-full rounded-t" style={{ height: `${successPct}%`, backgroundColor: "hsl(142 70% 45%)" }} />
                      <div className="absolute top-0 w-full rounded-t" style={{ height: `${100 - successPct}%`, backgroundColor: "hsl(0 72% 51%)" }} />
                    </div>
                    <span className="text-[8px] text-muted-foreground">{day.date.slice(5)}</span>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-success" /> Success</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-destructive" /> Failed</span>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Failure reasons */}
        {analytics.failure_reasons?.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <XCircle className="w-4 h-4 text-destructive" />
                Failure Reasons
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {analytics.failure_reasons.map((f: any, i: number) => (
                  <li key={i} className="flex items-center justify-between text-xs">
                    <span className="truncate text-foreground/80 flex-1">{f.error}</span>
                    <Badge variant="destructive" className="ml-2 shrink-0">{f.count}</Badge>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {/* Parameter distribution */}
        {Object.keys(analytics.param_distribution || {}).length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Parameter Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              {Object.entries(analytics.param_distribution).map(([param, values]: [string, any]) => (
                <div key={param} className="mb-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">{param}</div>
                  <div className="flex gap-1 flex-wrap">
                    {Object.entries(values).map(([val, count]: [string, any]) => (
                      <span key={val} className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] font-medium">
                        {val}: {count}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Last failure detail */}
      {analytics.last_failure && (
        <Card>
          <CardContent className="py-3">
            <div className="flex items-center gap-2 text-xs">
              <XCircle className="w-3.5 h-3.5 text-destructive shrink-0" />
              <span className="font-medium">Last failure:</span>
              <span className="text-muted-foreground">{analytics.last_failure.error}</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">{formatRelativeTime(analytics.last_failure.when)}</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }: { icon: any; label: string; value: any; color?: string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
            <div className={`text-2xl font-bold mt-1 ${color || ""}`}>{value}</div>
          </div>
          <Icon className="w-4 h-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}
