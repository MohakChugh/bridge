import { useState } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  MarkerType,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { nodeTypes } from "./workflow-nodes";
import { Button, Badge, Card, CardContent } from "./ui";
import { ArrowLeft, CheckCircle2, XCircle, Loader2, Pause, X } from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  pending: "opacity-40",
  running: "ring-2 ring-warning animate-pulse-slow",
  completed: "ring-2 ring-success",
  failed: "ring-2 ring-destructive",
  skipped: "opacity-25 border-dashed",
};

export function WorkflowRunner() {
  const { activeWorkflowId, activeRunId, setView } = useSessionStore();
  const qc = useQueryClient();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const { data: workflow } = useQuery({
    queryKey: ["workflow", activeWorkflowId],
    queryFn: () => (activeWorkflowId ? api.workflows.get(activeWorkflowId) : null),
    enabled: !!activeWorkflowId,
  });

  const { data: run } = useQuery({
    queryKey: ["workflow-run", activeRunId],
    queryFn: () => (activeWorkflowId && activeRunId ? api.workflows.getRun(activeWorkflowId, activeRunId) : null),
    enabled: !!activeWorkflowId && !!activeRunId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" || status === "paused" ? 1000 : false;
    },
  });

  const approveMut = useMutation({
    mutationFn: () => api.workflows.approve(activeWorkflowId!, activeRunId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflow-run", activeRunId] }),
  });

  const abortMut = useMutation({
    mutationFn: () => api.workflows.abort(activeWorkflowId!, activeRunId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflow-run", activeRunId] }),
  });

  if (!workflow || !run) {
    return <div className="p-8 text-muted-foreground">Loading...</div>;
  }

  const nodeStates = run.node_states || {};

  const nodes: Node[] = (workflow.nodes || []).map((n: any) => ({
    id: n.id,
    type: n.type,
    position: n.position,
    data: n.data || {},
    className: STATUS_STYLES[nodeStates[n.id]?.status || "pending"] || "",
    draggable: false,
    connectable: false,
  }));

  const edges: Edge[] = (workflow.edges || []).map((e: any) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
    markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(240 5% 40%)" },
    style: { stroke: "hsl(240 5% 30%)" },
    animated: nodeStates[e.source]?.status === "completed",
  }));

  const selectedState = selectedNodeId ? nodeStates[selectedNodeId] : null;
  const isPaused = run.status === "paused";

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 h-12 border-b border-border bg-card/50">
        <Button variant="ghost" size="icon" onClick={() => setView("workflows")}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <span className="text-sm font-semibold">{workflow.name}</span>
        <RunStatusBadge status={run.status} />
        <div className="flex-1" />
        {isPaused && (
          <>
            <Button size="sm" onClick={() => approveMut.mutate()} disabled={approveMut.isPending}>
              <CheckCircle2 className="w-3.5 h-3.5" /> Continue
            </Button>
            <Button size="sm" variant="destructive" onClick={() => abortMut.mutate()} disabled={abortMut.isPending}>
              <XCircle className="w-3.5 h-3.5" /> Abort
            </Button>
          </>
        )}
        {run.status === "running" && (
          <Button size="sm" variant="outline" onClick={() => abortMut.mutate()}>
            <X className="w-3.5 h-3.5" /> Stop
          </Button>
        )}
      </div>

      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          onNodeClick={(_, node) => setSelectedNodeId(node.id)}
          fitView
          className="bg-background"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="hsl(240 5% 15%)" />
          <Controls className="!bg-card !border-border !rounded-lg [&>button]:!bg-card [&>button]:!border-border [&>button]:!text-foreground" />
          <MiniMap nodeColor={(n) => {
            const s = nodeStates[n.id]?.status;
            if (s === "completed") return "hsl(142 70% 45%)";
            if (s === "running") return "hsl(38 92% 50%)";
            if (s === "failed") return "hsl(0 72% 51%)";
            return "hsl(240 5% 30%)";
          }} maskColor="hsla(240 10% 4% / 0.8)" className="!bg-card !border-border !rounded-lg" />
        </ReactFlow>

        {/* Output panel */}
        {selectedNodeId && selectedState && (
          <div className="absolute right-0 top-0 bottom-0 w-80 bg-card border-l border-border shadow-xl z-10 flex flex-col">
            <div className="flex items-center justify-between px-4 h-12 border-b border-border">
              <div className="flex items-center gap-2">
                <NodeStatusIcon status={selectedState.status} />
                <span className="text-sm font-semibold">Node output</span>
              </div>
              <button onClick={() => setSelectedNodeId(null)}><X className="w-4 h-4 text-muted-foreground" /></button>
            </div>
            <div className="p-4 overflow-y-auto flex-1">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Status</div>
              <Badge variant={selectedState.status === "completed" ? "success" : selectedState.status === "failed" ? "destructive" : "secondary"}>
                {selectedState.status}
              </Badge>
              {selectedState.output && (
                <div className="mt-4">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Output</div>
                  <pre className="text-xs bg-muted rounded-md p-3 whitespace-pre-wrap break-words max-h-96 overflow-y-auto">
                    {selectedState.output}
                  </pre>
                </div>
              )}
              {selectedState.error && (
                <div className="mt-4">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Error</div>
                  <pre className="text-xs bg-destructive/10 text-destructive rounded-md p-3 whitespace-pre-wrap">
                    {selectedState.error}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-8 border-t border-border bg-card/50 flex items-center px-4 gap-4 text-xs text-muted-foreground">
        {Object.entries(nodeStates).map(([nid, ns]) => (
          <span key={nid} className="flex items-center gap-1">
            <NodeStatusIcon status={(ns as any).status} size={8} />
            <span className="truncate max-w-[80px]">{nid}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function RunStatusBadge({ status }: { status: string }) {
  if (status === "running") return <Badge variant="warning"><Loader2 className="w-3 h-3 animate-spin mr-1" />Running</Badge>;
  if (status === "paused") return <Badge variant="warning"><Pause className="w-3 h-3 mr-1" />Paused</Badge>;
  if (status === "completed") return <Badge variant="success">Completed</Badge>;
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>;
  if (status === "aborted") return <Badge variant="destructive">Aborted</Badge>;
  return <Badge variant="secondary">{status}</Badge>;
}

function NodeStatusIcon({ status, size = 12 }: { status: string; size?: number }) {
  const s = size;
  if (status === "completed") return <CheckCircle2 style={{ width: s, height: s }} className="text-success" />;
  if (status === "running") return <Loader2 style={{ width: s, height: s }} className="text-warning animate-spin" />;
  if (status === "failed") return <XCircle style={{ width: s, height: s }} className="text-destructive" />;
  return <span style={{ width: s, height: s }} className="rounded-full bg-muted-foreground/30 inline-block" />;
}
