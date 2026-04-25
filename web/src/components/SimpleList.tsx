import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Card, CardContent, Badge } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { Plus, Trash2, Pause, Play, Bell, Calendar, Eye } from "lucide-react";
import { ReminderDialog, ScheduleDialog, WatchDialog } from "./CreateDialog";

// ---- Reminders ----
export function RemindersList() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["reminders"], queryFn: api.reminders.list });
  const items = data?.reminders ?? [];

  const deleteMut = useMutation({
    mutationFn: (idx: number) => api.reminders.delete(idx),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reminders"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  return (
    <ListPage
      title="Reminders"
      icon={Bell}
      count={items.length}
      onCreate={() => setDialogOpen(true)}
      isLoading={isLoading}
      emptyText="No reminders. Click + to create one."
    >
      {items.map((r: any) => (
        <Card key={r.id ?? r.message} className="hover:border-primary/30 transition-colors">
          <CardContent className="py-3 flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate">{r.message}</div>
              <div className="text-xs text-muted-foreground flex items-center gap-3 mt-0.5">
                <span>
                  {r.fire_at
                    ? new Date(r.fire_at * 1000).toLocaleString()
                    : r.human || "scheduled"}
                </span>
                {r.fire_at && (
                  <span className="text-[10px] opacity-70">
                    {r.fire_at > Date.now() / 1000
                      ? `in ${formatDistance(r.fire_at)}`
                      : "past"}
                  </span>
                )}
              </div>
            </div>
            <Button size="icon" variant="ghost" onClick={() => deleteMut.mutate(r.id)}>
              <Trash2 className="w-3.5 h-3.5 text-destructive" />
            </Button>
          </CardContent>
        </Card>
      ))}
      <ReminderDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </ListPage>
  );
}

// ---- Schedules ----
export function SchedulesList() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["schedules"], queryFn: api.schedules.list });
  const { data: wfData } = useQuery({ queryKey: ["workflows"], queryFn: api.workflows.list });

  // Merge prompt schedules + workflow schedules into one list
  const promptSchedules = (data?.schedules ?? []).map((s: any) => ({ ...s, _type: "prompt" }));
  const workflowSchedules: any[] = [];
  for (const wf of (wfData?.workflows ?? [])) {
    for (const sched of (wf.schedules || [])) {
      workflowSchedules.push({
        ...sched,
        _type: "workflow",
        _workflow_id: wf.id,
        _workflow_name: wf.name,
        prompt: wf.name,
        tool: wf.tool,
        params: sched.params,
      });
    }
  }
  const items = [...promptSchedules, ...workflowSchedules];

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.schedules.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const pauseMut = useMutation({
    mutationFn: (id: number) => api.schedules.pause(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const resumeMut = useMutation({
    mutationFn: (id: number) => api.schedules.resume(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  return (
    <ListPage
      title="Schedules"
      icon={Calendar}
      count={items.length}
      onCreate={() => setDialogOpen(true)}
      isLoading={isLoading}
      emptyText="No schedules. Click + to create one."
    >
      {items.map((s: any) => (
        <Card key={`${s._type}-${s.id}`} className="hover:border-primary/30 transition-colors">
          <CardContent className="py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge variant={s.status === "active" ? "success" : "secondary"}>{s.status}</Badge>
                  <span className="text-xs text-muted-foreground font-mono">{s.cron}</span>
                  {s._type === "workflow" && (
                    <Badge variant="outline" className="text-[9px]">workflow</Badge>
                  )}
                  {s.label && s._type === "workflow" && (
                    <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] font-medium">{s.label}</span>
                  )}
                </div>
                <div className="text-sm font-medium mt-1.5 truncate">
                  {s._type === "workflow" ? s._workflow_name : s.prompt}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-3 flex-wrap">
                  <span>{s.human}</span>
                  <span>·</span>
                  <span>{s.tool}</span>
                  {s.next_fire && (
                    <>
                      <span>·</span>
                      <span>next: {new Date(s.next_fire * 1000).toLocaleString()}</span>
                    </>
                  )}
                </div>
                {s.params && Object.keys(s.params).length > 0 && (
                  <div className="flex gap-1 mt-1.5 flex-wrap">
                    {Object.entries(s.params).map(([k, v]: [string, any]) => (
                      <span key={k} className="px-1.5 py-0.5 rounded bg-accent text-[9px] text-muted-foreground">
                        {k}={String(v).length > 20 ? String(v).slice(0, 20) + "…" : String(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex gap-1">
                {s._type === "prompt" && (
                  <>
                    {s.status === "active" ? (
                      <Button size="icon" variant="ghost" onClick={() => pauseMut.mutate(s.id)}>
                        <Pause className="w-3.5 h-3.5" />
                      </Button>
                    ) : (
                      <Button size="icon" variant="ghost" onClick={() => resumeMut.mutate(s.id)}>
                        <Play className="w-3.5 h-3.5" />
                      </Button>
                    )}
                    <Button size="icon" variant="ghost" onClick={() => deleteMut.mutate(s.id)}>
                      <Trash2 className="w-3.5 h-3.5 text-destructive" />
                    </Button>
                  </>
                )}
                {s._type === "workflow" && (
                  <Button size="icon" variant="ghost" onClick={() => {
                    api.workflows.deleteSchedule(s._workflow_id, s.id).then(() => {
                      qc.invalidateQueries({ queryKey: ["workflows"] });
                      qc.invalidateQueries({ queryKey: ["schedules"] });
                    });
                  }}>
                    <Trash2 className="w-3.5 h-3.5 text-destructive" />
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
      <ScheduleDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </ListPage>
  );
}

// ---- Watches ----
export function WatchesList() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["watches"], queryFn: api.watches.list });
  const items = data?.watches ?? [];

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.watches.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watches"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const pauseMut = useMutation({
    mutationFn: (id: number) => api.watches.pause(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }),
  });
  const resumeMut = useMutation({
    mutationFn: (id: number) => api.watches.resume(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }),
  });

  return (
    <ListPage
      title="Watches"
      icon={Eye}
      count={items.length}
      onCreate={() => setDialogOpen(true)}
      isLoading={isLoading}
      emptyText="No watches running. Click + to start one."
    >
      {items.map((w: any) => (
        <Card key={w.id} className="hover:border-primary/30 transition-colors">
          <CardContent className="py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge variant={w.status === "active" ? "success" : "secondary"}>{w.status}</Badge>
                  <span className="text-xs text-muted-foreground">{w.check_type}</span>
                  {w.alert_count > 0 && (
                    <Badge variant="warning">{w.alert_count} alerts</Badge>
                  )}
                </div>
                <div className="text-sm font-medium mt-1.5 truncate">{w.description || w.target}</div>
                <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-3">
                  <span>every {w.interval_minutes}m</span>
                  {w.last_check && (
                    <>
                      <span>·</span>
                      <span>last: {formatRelativeTime(w.last_check)}</span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex gap-1">
                {w.status === "active" ? (
                  <Button size="icon" variant="ghost" onClick={() => pauseMut.mutate(w.id)}>
                    <Pause className="w-3.5 h-3.5" />
                  </Button>
                ) : (
                  <Button size="icon" variant="ghost" onClick={() => resumeMut.mutate(w.id)}>
                    <Play className="w-3.5 h-3.5" />
                  </Button>
                )}
                <Button size="icon" variant="ghost" onClick={() => deleteMut.mutate(w.id)}>
                  <Trash2 className="w-3.5 h-3.5 text-destructive" />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
      <WatchDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </ListPage>
  );
}

// ---- Layout ----
function ListPage({
  title,
  icon: Icon,
  count,
  onCreate,
  isLoading,
  emptyText,
  children,
}: {
  title: string;
  icon: any;
  count: number;
  onCreate: () => void;
  isLoading: boolean;
  emptyText: string;
  children: React.ReactNode;
}) {
  const hasItems = count > 0;
  return (
    <div className="p-6 max-w-4xl space-y-4 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Icon className="w-5 h-5 text-muted-foreground" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            <p className="text-xs text-muted-foreground mt-0.5">{count} total</p>
          </div>
        </div>
        <Button size="sm" onClick={onCreate}>
          <Plus className="w-3.5 h-3.5" />
          New {title.toLowerCase().replace(/s$/, "")}
        </Button>
      </div>
      {isLoading ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">Loading…</CardContent>
        </Card>
      ) : !hasItems ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">{emptyText}</CardContent>
        </Card>
      ) : (
        <div className="space-y-2">{children}</div>
      )}
    </div>
  );
}

function formatDistance(epochSeconds: number): string {
  const diff = epochSeconds - Date.now() / 1000;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}
