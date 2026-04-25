import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Input } from "./ui";
import { X, Play } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  workflow: any;
  onStarted: (run: any) => void;
}

export function RunWorkflowDialog({ open, onClose, workflow, onStarted }: Props) {
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [resolved, setResolved] = useState<Record<string, string>>({});
  const qc = useQueryClient();

  const variables = workflow?.variables || [];

  useEffect(() => {
    if (!open || !variables.length) return;
    const defaults: Record<string, string> = {};
    variables.forEach((v: any) => { defaults[v.name] = v.default || ""; });
    setParamValues(defaults);
    // Resolve defaults to show preview
    api.workflows.resolveVariables({ variables, overrides: {} })
      .then((r) => setResolved(r.resolved))
      .catch(() => {});
  }, [open]);

  const runMut = useMutation({
    mutationFn: () => api.sessions.list().then(() =>
      fetch(`/api/workflows/${workflow.id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: paramValues }),
      }).then(r => r.json())
    ),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["workflow-runs"] });
      onStarted(run);
      onClose();
    },
  });

  if (!open) return null;

  // No variables → run immediately
  if (!variables.length) {
    return null; // Caller should run directly
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md p-5 relative">
        <button onClick={onClose} className="absolute right-3 top-3 text-muted-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>
        <h2 className="font-semibold mb-1">Run: {workflow.name}</h2>
        <p className="text-xs text-muted-foreground mb-4">Configure parameters for this run</p>

        <div className="space-y-3">
          {variables.map((v: any) => (
            <div key={v.name}>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                {v.name}
                {v.description && <span className="text-[10px] opacity-70 ml-1">— {v.description}</span>}
              </label>
              <Input
                value={paramValues[v.name] || ""}
                onChange={(e) => setParamValues({ ...paramValues, [v.name]: e.target.value })}
                placeholder={v.default || `Enter ${v.name}`}
                className="h-8 text-sm"
              />
              {v.type === "date" && resolved[v.name] && (
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  Resolves to: <span className="text-foreground font-mono">{resolved[v.name]}</span>
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="flex justify-end mt-5 gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            <Play className="w-3.5 h-3.5" />
            {runMut.isPending ? "Starting..." : "Execute"}
          </Button>
        </div>
      </div>
    </div>
  );
}
