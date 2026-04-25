import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Workflow } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button, Input } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { Plus, Play, Pencil, Trash2, GitBranch, Calendar, X, Sparkles, CalendarOff } from "lucide-react";
import { layoutDagre } from "@/lib/dagre-layout";

export function WorkflowList() {
  const qc = useQueryClient();
  const { setView, setActiveWorkflowId, setActiveRunId } = useSessionStore();
  const { data, isLoading } = useQuery({ queryKey: ["workflows"], queryFn: api.workflows.list });
  const workflows = data?.workflows ?? [];
  const [scheduleDialogId, setScheduleDialogId] = useState<string | null>(null);

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.workflows.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });

  const runMut = useMutation({
    mutationFn: (id: string) => api.workflows.run(id),
    onSuccess: (run) => {
      setActiveWorkflowId(run.workflow_id);
      setActiveRunId(run.id);
      setView("workflow-runner");
    },
  });

  const unscheduleMut = useMutation({
    mutationFn: (id: string) => api.workflows.unschedule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });

  return (
    <div className="p-6 max-w-5xl space-y-4 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GitBranch className="w-5 h-5 text-muted-foreground" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Workflows</h1>
            <p className="text-xs text-muted-foreground mt-0.5">{workflows.length} total</p>
          </div>
        </div>
        <Button size="sm" onClick={() => { setActiveWorkflowId(null); setView("workflow-editor"); }}>
          <Plus className="w-3.5 h-3.5" />
          New workflow
        </Button>
      </div>

      {isLoading ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Loading...</CardContent></Card>
      ) : workflows.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <GitBranch className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <div className="text-sm font-medium">No workflows yet</div>
            <div className="text-xs text-muted-foreground mt-1">Create a visual DAG of prompts that execute in sequence</div>
            <Button size="sm" className="mt-4" onClick={() => { setActiveWorkflowId(null); setView("workflow-editor"); }}>
              <Plus className="w-3.5 h-3.5" /> Create first workflow
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {workflows.map((wf) => (
            <Card key={wf.id} className="hover:border-primary/30 transition-colors">
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="truncate">{wf.name}</CardTitle>
                  <Badge variant="secondary">{wf.tool}</Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  {wf.nodes?.length || 0} nodes · {wf.edges?.length || 0} edges
                </div>
                {wf.schedule && (
                  <div className="text-xs text-success flex items-center gap-1 mt-1">
                    <Calendar className="w-3 h-3" /> {wf.schedule.human || wf.schedule.cron}
                  </div>
                )}
              </CardHeader>
              <CardContent>
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" className="flex-1" onClick={() => runMut.mutate(wf.id)}>
                    <Play className="w-3 h-3" /> Run
                  </Button>
                  {wf.schedule ? (
                    <Button size="sm" variant="ghost" onClick={() => unscheduleMut.mutate(wf.id)} title="Remove schedule">
                      <CalendarOff className="w-3 h-3 text-warning" />
                    </Button>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => setScheduleDialogId(wf.id)} title="Schedule">
                      <Calendar className="w-3 h-3" />
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => { setActiveWorkflowId(wf.id); setView("workflow-editor"); }}>
                    <Pencil className="w-3 h-3" />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => { if (confirm("Delete?")) deleteMut.mutate(wf.id); }}>
                    <Trash2 className="w-3 h-3 text-destructive" />
                  </Button>
                </div>
                {wf.updated_at && (
                  <div className="text-[10px] text-muted-foreground mt-2">Updated {formatRelativeTime(wf.updated_at)}</div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {scheduleDialogId && (
        <WorkflowScheduleDialog
          workflowId={scheduleDialogId}
          onClose={() => setScheduleDialogId(null)}
        />
      )}
    </div>
  );
}

function WorkflowScheduleDialog({ workflowId, onClose }: { workflowId: string; onClose: () => void }) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<{ cron: string; human: string } | null>(null);
  const qc = useQueryClient();

  const parseMut = useMutation({
    mutationFn: (t: string) => api.schedules.parse(t),
    onSuccess: (data) => setParsed(data),
  });

  const scheduleMut = useMutation({
    mutationFn: () => api.workflows.schedule(workflowId, { cron: parsed!.cron, human: parsed!.human }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md p-5 relative">
        <button onClick={onClose} className="absolute right-3 top-3 text-muted-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>
        <h2 className="font-semibold mb-4">Schedule workflow</h2>
        {!parsed ? (
          <>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">When should it run?</label>
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="every morning at 9am · weekdays at 5pm · every 2 hours"
              autoFocus
            />
            <div className="flex justify-end mt-4">
              <Button onClick={() => parseMut.mutate(text)} disabled={!text.trim() || parseMut.isPending}>
                <Sparkles className="w-3.5 h-3.5" />
                {parseMut.isPending ? "Parsing..." : "Parse"}
              </Button>
            </div>
            {parseMut.isError && <div className="text-xs text-destructive mt-2">Could not parse — try different phrasing</div>}
          </>
        ) : (
          <>
            <div className="bg-accent/50 border border-border rounded-md p-3 space-y-2">
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Schedule</div>
                <div className="text-sm font-medium">{parsed.human}</div>
                <div className="text-xs text-muted-foreground font-mono mt-0.5">{parsed.cron}</div>
              </div>
            </div>
            <div className="flex justify-between mt-4 gap-2">
              <Button variant="ghost" size="sm" onClick={() => setParsed(null)}>← Edit</Button>
              <Button onClick={() => scheduleMut.mutate()} disabled={scheduleMut.isPending}>
                <Calendar className="w-3.5 h-3.5" />
                {scheduleMut.isPending ? "Scheduling..." : "Schedule"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
