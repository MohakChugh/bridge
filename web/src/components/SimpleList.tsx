import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Card, CardContent, Badge } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { Plus, Trash2, Pause, Play, Bell, Calendar, Eye, Zap, X, Loader } from "lucide-react";
import { ReminderDialog, ScheduleDialog, WatchDialog } from "./CreateDialog";

// ---- Reminders ----
export function RemindersList() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["reminders"], queryFn: api.reminders.list });
  const items = data?.reminders ?? [];

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.reminders.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reminders"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  return (
    <>
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
    </ListPage>
    <ReminderDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </>
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
    if (wf.schedule) {
      workflowSchedules.push({
        ...wf.schedule,
        id: `${wf.id}-legacy`,
        _type: "workflow",
        _workflow_id: wf.id,
        _workflow_name: wf.name,
        prompt: wf.name,
        tool: wf.tool,
        status: "active",
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
    <>
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
    </ListPage>
    <ScheduleDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </>
  );
}

// ---- Watches & Triggers ----
export function WatchesList() {
  const [tab, setTab] = useState<"watches" | "triggers">("watches");
  const [watchDialogOpen, setWatchDialogOpen] = useState(false);
  const [triggerDialogOpen, setTriggerDialogOpen] = useState(false);
  const qc = useQueryClient();

  const { data: watchData, isLoading: watchLoading } = useQuery({ queryKey: ["watches"], queryFn: api.watches.list, refetchInterval: 5000 });
  const { data: triggerData, isLoading: triggerLoading } = useQuery({ queryKey: ["triggers"], queryFn: api.triggers.list, refetchInterval: 3000 });
  const watches = watchData?.watches ?? [];
  const triggers = triggerData?.triggers ?? [];

  const deleteWatchMut = useMutation({ mutationFn: (id: number) => api.watches.delete(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["watches"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); } });
  const pauseWatchMut = useMutation({ mutationFn: (id: number) => api.watches.pause(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }) });
  const resumeWatchMut = useMutation({ mutationFn: (id: number) => api.watches.resume(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["watches"] }) });
  const deleteTriggerMut = useMutation({ mutationFn: (id: string) => api.triggers.delete(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["triggers"] }) });
  const toggleTriggerMut = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.triggers.toggle(id, enabled), onSuccess: () => qc.invalidateQueries({ queryKey: ["triggers"] }) });

  const activeWatches = watches.filter((w: any) => w.status === "active").length;
  const totalAlerts = watches.reduce((sum: number, w: any) => sum + (w.alert_count || 0), 0);
  const activeTriggers = triggers.filter((t: any) => t.enabled).length;
  const totalFires = triggers.reduce((sum: number, t: any) => sum + (t.fire_count || 0), 0);

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 max-w-5xl space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Eye className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Watches & Triggers</h1>
              <p className="text-xs text-muted-foreground">Monitor infrastructure and automate reactions</p>
            </div>
          </div>
          <div className="flex gap-2">
            {tab === "watches" && <Button size="sm" onClick={() => setWatchDialogOpen(true)}><Plus className="w-3.5 h-3.5 mr-1" /> New Watch</Button>}
            {tab === "triggers" && <Button size="sm" onClick={() => setTriggerDialogOpen(true)}><Plus className="w-3.5 h-3.5 mr-1" /> New Trigger</Button>}
          </div>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-4 gap-3">
          <StatCard label="Active Watches" value={activeWatches} total={watches.length} color="text-green-400" />
          <StatCard label="Total Alerts" value={totalAlerts} color="text-yellow-400" />
          <StatCard label="Active Triggers" value={activeTriggers} total={triggers.length} color="text-purple-400" />
          <StatCard label="Triggers Fired" value={totalFires} color="text-cyan-400" />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-accent/30 p-1 rounded-lg w-fit">
          <button onClick={() => setTab("watches")} className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${tab === "watches" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            <Eye className="w-3.5 h-3.5 inline mr-1.5" />Watches ({watches.length})
          </button>
          <button onClick={() => setTab("triggers")} className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${tab === "triggers" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            <Zap className="w-3.5 h-3.5 inline mr-1.5" />Triggers ({triggers.length})
          </button>
        </div>

        {/* Content */}
        {tab === "watches" && (
          <div className="space-y-2">
            {watchLoading && <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Loading watches...</CardContent></Card>}
            {!watchLoading && watches.length === 0 && (
              <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">
                No watches running. Click "New Watch" to monitor a pipeline, ticket queue, or URL.
              </CardContent></Card>
            )}
            {watches.map((w: any) => (
              <Card key={w.id} className="hover:border-primary/30 transition-colors">
                <CardContent className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Badge variant={w.status === "active" ? "success" : "secondary"}>{w.status}</Badge>
                        <span className="text-xs text-muted-foreground">{w.check_type}</span>
                        {w.alert_count > 0 && <Badge variant="warning" className="text-[10px]">{w.alert_count} alerts</Badge>}
                      </div>
                      <div className="text-sm font-medium mt-1.5 truncate">{w.description || w.target}</div>
                      <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-3">
                        <span>every {w.interval_minutes}m</span>
                        {w.last_check && <><span>·</span><span>last: {formatRelativeTime(w.last_check)}</span></>}
                      </div>
                    </div>
                    <div className="flex gap-1">
                      {w.status === "active" ? (
                        <Button size="icon" variant="ghost" onClick={() => pauseWatchMut.mutate(w.id)}><Pause className="w-3.5 h-3.5" /></Button>
                      ) : (
                        <Button size="icon" variant="ghost" onClick={() => resumeWatchMut.mutate(w.id)}><Play className="w-3.5 h-3.5" /></Button>
                      )}
                      <Button size="icon" variant="ghost" onClick={() => deleteWatchMut.mutate(w.id)}><Trash2 className="w-3.5 h-3.5 text-destructive" /></Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {tab === "triggers" && (
          <div className="space-y-2">
            {triggerLoading && <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Loading triggers...</CardContent></Card>}
            {!triggerLoading && triggers.length === 0 && (
              <Card><CardContent className="py-12 text-center space-y-3">
                <Zap className="w-8 h-8 text-muted-foreground/20 mx-auto" />
                <p className="text-sm text-muted-foreground">No triggers configured</p>
                <p className="text-xs text-muted-foreground/60">Triggers react to events automatically — "When X happens, do Y"</p>
              </CardContent></Card>
            )}
            {triggers.map((t: any) => (
              <Card key={t.id} className={`transition-colors ${t.enabled ? "hover:border-primary/30" : "opacity-50"}`}>
                <CardContent className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant={t.enabled ? "success" : "secondary"}>{t.enabled ? "active" : "paused"}</Badge>
                        <Badge variant="outline" className="text-[9px] font-mono">{t.event_pattern}</Badge>
                        <span className="text-[10px] text-muted-foreground">→</span>
                        <Badge variant={t.action === "session" ? "default" : t.action === "workflow" ? "outline" : "secondary"} className="text-[9px]">
                          {t.action === "session" ? "Run Prompt" : t.action === "workflow" ? "Run Workflow" : "Notify"}
                        </Badge>
                      </div>
                      <div className="text-sm font-medium mt-1.5">{t.name}</div>
                      <div className="text-xs text-muted-foreground mt-1 flex items-center gap-3 flex-wrap">
                        <span>cooldown: {t.cooldown_seconds}s</span>
                        <span>·</span>
                        <span>fired: {t.fire_count}×</span>
                        {t.last_fired && <><span>·</span><span>last: {formatRelativeTime(t.last_fired)}</span></>}
                      </div>
                      {Object.keys(t.data_filter || {}).length > 0 && (
                        <div className="flex gap-1 mt-1.5 flex-wrap">
                          {Object.entries(t.data_filter).map(([k, v]: [string, any]) => (
                            <span key={k} className="px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400 text-[9px] font-mono">{k}={String(v)}</span>
                          ))}
                        </div>
                      )}
                      {t.action_config?.prompt && (
                        <div className="mt-1.5 text-[11px] text-muted-foreground/70 truncate max-w-md">
                          Prompt: {t.action_config.prompt}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button size="icon" variant="ghost" title={t.enabled ? "Pause" : "Enable"}
                        onClick={() => toggleTriggerMut.mutate({ id: t.id, enabled: !t.enabled })}>
                        {t.enabled ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => deleteTriggerMut.mutate(t.id)}>
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
      <WatchDialog open={watchDialogOpen} onClose={() => setWatchDialogOpen(false)} />
      {triggerDialogOpen && <TriggerDialog onClose={() => setTriggerDialogOpen(false)} />}
    </div>
  );
}

function StatCard({ label, value, total, color }: { label: string; value: number; total?: number; color: string }) {
  return (
    <Card>
      <CardContent className="py-3 px-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className={`text-2xl font-bold mt-0.5 ${color}`}>
          {value}{total !== undefined && <span className="text-sm font-normal text-muted-foreground">/{total}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

const EVENT_PRESETS = [
  { label: "Workflow fails", pattern: "workflow\\.run\\.completed", filter: { status: "failed" } },
  { label: "Session completes", pattern: "session\\.completed", filter: {} },
  { label: "Agent task done", pattern: "agent\\.task\\.completed", filter: {} },
  { label: "Watch alerts", pattern: "watch\\.alert", filter: {} },
  { label: "Heartbeat alerts", pattern: "heartbeat\\.alerts", filter: {} },
  { label: "Document ingested", pattern: "document\\.ingested", filter: {} },
  { label: "Any event (custom)", pattern: ".*", filter: {} },
];

const ACTION_PRESETS = [
  { label: "Run a prompt", value: "session" },
  { label: "Run a workflow", value: "workflow" },
  { label: "Send notification", value: "notify" },
];

function TriggerDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [eventIdx, setEventIdx] = useState(0);
  const [customPattern, setCustomPattern] = useState("");
  const [action, setAction] = useState("session");
  const [prompt, setPrompt] = useState("");
  const [cooldown, setCooldown] = useState(60);
  const [saving, setSaving] = useState(false);
  const qc = useQueryClient();

  const selectedEvent = EVENT_PRESETS[eventIdx];
  const pattern = selectedEvent.pattern === ".*" ? customPattern : selectedEvent.pattern;

  const handleCreate = async () => {
    if (!name.trim() || !pattern) return;
    setSaving(true);
    try {
      await api.triggers.create({
        name: name.trim(),
        event_pattern: pattern,
        data_filter: selectedEvent.filter,
        action,
        action_config: action === "session" ? { prompt } : action === "notify" ? { message: prompt } : { workflow_id: prompt },
        cooldown_seconds: cooldown,
      });
      qc.invalidateQueries({ queryKey: ["triggers"] });
      onClose();
    } catch { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl border border-border bg-card shadow-2xl p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            <span className="font-semibold text-sm">New Trigger</span>
          </div>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}><X className="w-3.5 h-3.5" /></Button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Auto-diagnose pipeline failures"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" autoFocus />
          </div>

          <div>
            <label className="text-xs text-muted-foreground mb-1 block">When this event happens...</label>
            <div className="flex flex-wrap gap-1.5">
              {EVENT_PRESETS.map((ep, i) => (
                <button key={i} onClick={() => setEventIdx(i)}
                  className={`px-2.5 py-1 rounded-md text-xs transition-colors ${i === eventIdx ? "bg-primary text-primary-foreground" : "bg-accent text-muted-foreground hover:text-foreground"}`}>
                  {ep.label}
                </button>
              ))}
            </div>
            {selectedEvent.pattern === ".*" && (
              <input value={customPattern} onChange={(e) => setCustomPattern(e.target.value)} placeholder="event\\.type\\.pattern"
                className="w-full mt-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary" />
            )}
          </div>

          <div>
            <label className="text-xs text-muted-foreground mb-1 block">...then do this</label>
            <div className="flex gap-1.5">
              {ACTION_PRESETS.map((ap) => (
                <button key={ap.value} onClick={() => setAction(ap.value)}
                  className={`px-2.5 py-1 rounded-md text-xs transition-colors ${action === ap.value ? "bg-primary text-primary-foreground" : "bg-accent text-muted-foreground hover:text-foreground"}`}>
                  {ap.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground mb-1 block">
              {action === "session" ? "Prompt to run" : action === "notify" ? "Notification message" : "Workflow ID"}
            </label>
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder={action === "session" ? "Investigate what failed and suggest fixes..." : action === "notify" ? "Alert: something happened!" : "workflow-id-here"}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary resize-none h-20" />
          </div>

          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Cooldown</label>
            <div className="flex gap-1.5">
              {[30, 60, 300, 900, 3600].map((s) => (
                <button key={s} onClick={() => setCooldown(s)}
                  className={`px-2.5 py-1 rounded-md text-xs transition-colors ${cooldown === s ? "bg-primary text-primary-foreground" : "bg-accent text-muted-foreground hover:text-foreground"}`}>
                  {s < 60 ? `${s}s` : s < 3600 ? `${s / 60}m` : `${s / 3600}h`}
                </button>
              ))}
            </div>
          </div>
        </div>

        <Button className="w-full" disabled={!name.trim() || !pattern || saving} onClick={handleCreate}>
          {saving ? <Loader className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Zap className="w-3.5 h-3.5 mr-1.5" />}
          Create Trigger
        </Button>
      </div>
    </div>
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
