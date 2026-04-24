import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle, Badge } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { Activity, Bell, Calendar, Eye } from "lucide-react";
import { useSessionStore } from "@/stores/sessionStore";

export function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: 10_000,
  });
  const { setView, setActiveSessionId } = useSessionStore();

  if (isLoading) {
    return <div className="p-8 text-muted-foreground">Loading…</div>;
  }

  const sessions = data?.sessions?.sessions ?? [];
  const busy = data?.sessions?.busy ?? 0;
  const reminders = data?.reminders?.upcoming ?? [];
  const schedules = data?.schedules?.active ?? [];
  const watches = data?.watches?.active ?? [];

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {busy} running · {sessions.length} total sessions
        </p>
      </div>

      {/* Sessions */}
      <section>
        <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          <Activity className="w-3.5 h-3.5" />
          Sessions
        </div>
        {sessions.length === 0 ? (
          <Card>
            <CardContent className="py-6 text-center text-sm text-muted-foreground">
              No active sessions. Create one in the Chat view.
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sessions.map((s: any) => (
              <button
                key={s.id}
                onClick={() => {
                  setActiveSessionId(s.id);
                  setView("chat");
                }}
                className="text-left"
              >
                <Card className="hover:border-primary/50 transition-colors cursor-pointer h-full">
                  <CardHeader>
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle className="truncate">{s.title}</CardTitle>
                      <StatusBadge status={s.status} />
                    </div>
                    <div className="text-xs text-muted-foreground flex items-center gap-2">
                      <span>{s.tool}</span>
                      <span>·</span>
                      <span>{formatRelativeTime(s.updated_at)}</span>
                    </div>
                  </CardHeader>
                  {s.current_task && (
                    <CardContent>
                      <p className="text-xs text-muted-foreground truncate">{s.current_task}</p>
                    </CardContent>
                  )}
                </Card>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Upcoming grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="w-3.5 h-3.5" />
              Reminders
            </CardTitle>
          </CardHeader>
          <CardContent>
            {reminders.length === 0 ? (
              <p className="text-xs text-muted-foreground">None scheduled</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {reminders.map((r: any) => (
                  <li key={r.id} className="border-l-2 border-primary/50 pl-2">
                    <div className="font-medium truncate">{r.message || r.text}</div>
                    <div className="text-muted-foreground">{r.human || "scheduled"}</div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Calendar className="w-3.5 h-3.5" />
              Schedules
            </CardTitle>
          </CardHeader>
          <CardContent>
            {schedules.length === 0 ? (
              <p className="text-xs text-muted-foreground">None active</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {schedules.map((s: any) => (
                  <li key={s.id} className="border-l-2 border-success/50 pl-2">
                    <div className="font-medium truncate">{s.prompt?.slice(0, 50)}</div>
                    <div className="text-muted-foreground">{s.human}</div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Eye className="w-3.5 h-3.5" />
              Watches
            </CardTitle>
          </CardHeader>
          <CardContent>
            {watches.length === 0 ? (
              <p className="text-xs text-muted-foreground">None running</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {watches.map((w: any) => (
                  <li key={w.id} className="border-l-2 border-warning/50 pl-2">
                    <div className="font-medium truncate">{w.description || w.target}</div>
                    <div className="text-muted-foreground">{w.interval_minutes}m interval</div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "busy") return <Badge variant="warning">running</Badge>;
  if (status === "completed") return <Badge variant="success">done</Badge>;
  if (status === "failed") return <Badge variant="destructive">failed</Badge>;
  return <Badge variant="secondary">idle</Badge>;
}
