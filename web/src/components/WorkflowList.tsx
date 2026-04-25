import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Workflow } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { Plus, Play, Pencil, Trash2, GitBranch, Calendar } from "lucide-react";

export function WorkflowList() {
  const qc = useQueryClient();
  const { setView, setActiveWorkflowId, setActiveRunId } = useSessionStore();
  const { data, isLoading } = useQuery({ queryKey: ["workflows"], queryFn: api.workflows.list });
  const workflows = data?.workflows ?? [];

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
    </div>
  );
}
