import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import {
  Activity,
  Bell,
  Calendar,
  Eye,
  Plus,
  Zap,
  MessageSquare,
  Play,
  Pause,
  AlertCircle,
  CheckCircle2,
  Loader2,
  TrendingUp,
} from "lucide-react";
import { useSessionStore } from "@/stores/sessionStore";
import { useState } from "react";
import { ReminderDialog, ScheduleDialog, WatchDialog } from "./CreateDialog";
import { NewSessionDialog } from "./NewSessionDialog";

export function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: 5_000,
  });
  const { data: activityData } = useQuery({
    queryKey: ["activity"],
    queryFn: api.activity,
    refetchInterval: 8_000,
  });
  const { setView, setActiveSessionId } = useSessionStore();

  const [remOpen, setRemOpen] = useState(false);
  const [schedOpen, setSchedOpen] = useState(false);
  const [watchOpen, setWatchOpen] = useState(false);

  if (isLoading) {
    return <div className="p-8 text-muted-foreground">Loading…</div>;
  }

  const sessions = data?.sessions?.sessions ?? [];
  const busy = data?.sessions?.busy ?? 0;
  const total = data?.sessions?.total ?? 0;
  const completed = sessions.filter((s: any) => s.status === "completed").length;
  const failed = sessions.filter((s: any) => s.status === "failed").length;
  const reminders = data?.reminders?.upcoming ?? [];
  const schedules = data?.schedules?.active ?? [];
  const watches = data?.watches?.active ?? [];
  const events = activityData?.events ?? [];

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {busy > 0 ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin text-warning" />
                <span className="text-warning font-medium">{busy} running</span> · {total} total sessions
              </span>
            ) : (
              <span>{total} sessions · all idle</span>
            )}
          </p>
        </div>
        <NewSessionDialog onCreated={(id) => { setActiveSessionId(id); setView("chat"); }} />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Sessions" value={total} icon={MessageSquare} sub={`${busy} running`} onClick={() => setView("chat")} />
        <StatCard label="Reminders" value={data?.reminders?.total ?? 0} icon={Bell} sub={`${reminders.length} upcoming`} onClick={() => setView("reminders")} />
        <StatCard label="Schedules" value={data?.schedules?.total ?? 0} icon={Calendar} sub={`${schedules.length} active`} onClick={() => setView("schedules")} />
        <StatCard label="Watches" value={data?.watches?.total ?? 0} icon={Eye} sub={`${watches.length} active`} onClick={() => setView("watches")} />
      </div>

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => setRemOpen(true)}>
          <Bell className="w-3.5 h-3.5" /> Add reminder
        </Button>
        <Button size="sm" variant="outline" onClick={() => setSchedOpen(true)}>
          <Calendar className="w-3.5 h-3.5" /> Add schedule
        </Button>
        <Button size="sm" variant="outline" onClick={() => setWatchOpen(true)}>
          <Eye className="w-3.5 h-3.5" /> Start watch
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Active sessions — 2 cols */}
        <div className="lg:col-span-2 space-y-4">
          <SectionHeader icon={Activity} title="Active sessions" count={sessions.length} />
          {sessions.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                No active sessions. Click <b>New session</b> above to start.
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {sessions.map((s: any) => (
                <SessionCard key={s.id} session={s} onClick={() => { setActiveSessionId(s.id); setView("chat"); }} />
              ))}
            </div>
          )}

          {/* Activity feed */}
          <SectionHeader icon={TrendingUp} title="Recent activity" count={events.length} />
          <Card>
            <CardContent className="py-0">
              {events.length === 0 ? (
                <div className="py-6 text-center text-xs text-muted-foreground">No recent activity</div>
              ) : (
                <ul className="divide-y divide-border">
                  {events.slice(0, 15).map((e: any, i: number) => (
                    <li key={i} className="py-2 text-xs flex items-start gap-2">
                      <div className="shrink-0 pt-0.5">
                        {e.role === "user" ? (
                          <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
                        ) : (
                          <span className="w-1.5 h-1.5 rounded-full bg-success inline-block" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <span className="truncate font-medium text-foreground/80">{e.session_title}</span>
                          <span>·</span>
                          <span className="capitalize">{e.role}</span>
                          <span>·</span>
                          <span>{formatRelativeTime(e.timestamp)}</span>
                        </div>
                        <div className="text-foreground/90 mt-0.5 truncate">{e.text}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right column — upcoming */}
        <div className="space-y-4">
          <UpcomingCard
            icon={Bell}
            title="Reminders"
            emptyText="No reminders"
            items={reminders.map((r: any) => ({
              key: r.id ?? r.message,
              primary: r.message,
              secondary: r.fire_at ? new Date(r.fire_at * 1000).toLocaleString() : r.human,
              accent: "primary",
            }))}
            onCreate={() => setRemOpen(true)}
            onView={() => setView("reminders")}
          />
          <UpcomingCard
            icon={Calendar}
            title="Schedules"
            emptyText="No schedules"
            items={schedules.map((s: any) => ({
              key: s.id,
              primary: s.prompt?.slice(0, 60),
              secondary: s.human,
              accent: "success",
            }))}
            onCreate={() => setSchedOpen(true)}
            onView={() => setView("schedules")}
          />
          <UpcomingCard
            icon={Eye}
            title="Watches"
            emptyText="No watches"
            items={watches.map((w: any) => ({
              key: w.id,
              primary: w.description || w.target,
              secondary: `every ${w.interval_minutes}m`,
              accent: "warning",
            }))}
            onCreate={() => setWatchOpen(true)}
            onView={() => setView("watches")}
          />
        </div>
      </div>

      <ReminderDialog open={remOpen} onClose={() => setRemOpen(false)} />
      <ScheduleDialog open={schedOpen} onClose={() => setSchedOpen(false)} />
      <WatchDialog open={watchOpen} onClose={() => setWatchOpen(false)} />
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  sub,
  onClick,
}: {
  label: string;
  value: number;
  icon: any;
  sub: string;
  onClick: () => void;
}) {
  return (
    <button onClick={onClick} className="text-left">
      <Card className="hover:border-primary/50 transition-colors h-full">
        <CardContent className="pt-4">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
              <div className="text-2xl font-bold mt-1">{value}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>
            </div>
            <Icon className="w-4 h-4 text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

function SectionHeader({ icon: Icon, title, count }: { icon: any; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
      <Icon className="w-3.5 h-3.5" />
      {title}
      {count !== undefined && <span className="text-[10px] text-muted-foreground/70">({count})</span>}
    </div>
  );
}

function SessionCard({ session, onClick }: { session: any; onClick: () => void }) {
  return (
    <button onClick={onClick} className="text-left">
      <Card className="hover:border-primary/50 transition-colors cursor-pointer h-full">
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="truncate">{session.title}</CardTitle>
            <StatusBadge status={session.status} />
          </div>
          <div className="text-xs text-muted-foreground flex items-center gap-2">
            <span className="capitalize">{session.tool}</span>
            <span>·</span>
            <span>{formatRelativeTime(session.updated_at)}</span>
          </div>
        </CardHeader>
        {session.current_task && (
          <CardContent>
            <p className="text-xs text-muted-foreground truncate flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" />
              {session.current_task}
            </p>
          </CardContent>
        )}
        {!session.current_task && session.last_output && (
          <CardContent>
            <p className="text-xs text-muted-foreground line-clamp-2">{session.last_output}</p>
          </CardContent>
        )}
      </Card>
    </button>
  );
}

function UpcomingCard({
  icon: Icon,
  title,
  emptyText,
  items,
  onCreate,
  onView,
}: {
  icon: any;
  title: string;
  emptyText: string;
  items: Array<{ key: any; primary: string; secondary: string; accent: string }>;
  onCreate: () => void;
  onView: () => void;
}) {
  const accentColor: Record<string, string> = {
    primary: "border-l-primary/50",
    success: "border-l-success/50",
    warning: "border-l-warning/50",
  };
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Icon className="w-3.5 h-3.5" />
            {title}
          </CardTitle>
          <Button size="icon" variant="ghost" onClick={onCreate}>
            <Plus className="w-3.5 h-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-xs text-muted-foreground">{emptyText}</p>
        ) : (
          <ul className="space-y-2 text-xs">
            {items.map((item) => (
              <li
                key={item.key}
                className={`border-l-2 ${accentColor[item.accent] ?? "border-l-primary/50"} pl-2`}
              >
                <div className="font-medium truncate">{item.primary}</div>
                <div className="text-muted-foreground">{item.secondary}</div>
              </li>
            ))}
          </ul>
        )}
        {items.length > 0 && (
          <button onClick={onView} className="text-[10px] text-muted-foreground mt-2 hover:text-foreground">
            View all →
          </button>
        )}
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "busy") return <Badge variant="warning">running</Badge>;
  if (status === "completed") return <Badge variant="success">done</Badge>;
  if (status === "failed") return <Badge variant="destructive">failed</Badge>;
  return <Badge variant="secondary">idle</Badge>;
}
