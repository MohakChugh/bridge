import { useCallback, useState, useRef } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Workflow } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { nodeTypes, NODE_MENU } from "./workflow-nodes";
import { Button, Input, Textarea } from "./ui";
import { Save, Play, Plus, ArrowLeft, Settings, X, Sparkles, LayoutGrid, MessageCircle, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { layoutDagre } from "@/lib/dagre-layout";
import { GenerateWorkflowDialog } from "./GenerateWorkflowDialog";
import { FeedbackPanel } from "./FeedbackPanel";
import { VariablesPanel, type WorkflowVariable } from "./VariablesPanel";

export function WorkflowEditor() {
  const { activeWorkflowId } = useSessionStore();

  const { data: initialWf, isLoading } = useQuery({
    queryKey: ["workflow", activeWorkflowId],
    queryFn: () => (activeWorkflowId ? api.workflows.get(activeWorkflowId) : null),
    enabled: !!activeWorkflowId,
  });

  if (activeWorkflowId && isLoading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
        Loading workflow...
      </div>
    );
  }

  // Key forces remount when workflow changes — ensures fresh hook state
  return <WorkflowEditorInner key={activeWorkflowId || "new"} initialWf={initialWf} />;
}

function WorkflowEditorInner({ initialWf }: { initialWf: any }) {
  const { activeWorkflowId, setView, setActiveWorkflowId, setActiveRunId } = useSessionStore();
  const qc = useQueryClient();
  const { data: dirsData } = useQuery({ queryKey: ["directories"], queryFn: api.directories });

  const rawNodes: Node[] = initialWf?.nodes?.map((n: any) => ({
    id: n.id,
    type: n.type,
    position: n.position || { x: 0, y: 0 },
    data: n.data || {},
  })) || [
    { id: "start-1", type: "start", position: { x: 250, y: 50 }, data: {} },
    { id: "end-1", type: "end", position: { x: 250, y: 400 }, data: {} },
  ];

  const rawEdges: Edge[] = initialWf?.edges?.map((e: any) => ({
    id: e.id || `e-${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    label: e.label,
    markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(240 5% 40%)" },
    style: { stroke: "hsl(240 5% 30%)" },
  })) || [];

  // Auto-layout if any node is missing a real position (x=0, y=0)
  const needsLayout = rawNodes.length > 2 && rawNodes.some((n) => n.position.x === 0 && n.position.y === 0);
  const { nodes: defaultNodes, edges: defaultEdges } = needsLayout
    ? layoutDagre(rawNodes, rawEdges)
    : { nodes: rawNodes, edges: rawEdges };

  const [nodes, setNodes, onNodesChange] = useNodesState(defaultNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(defaultEdges);
  const [wfName, setWfName] = useState(initialWf?.name || "New Workflow");
  const [wfTool, setWfTool] = useState(initialWf?.tool || "wasabi");
  const [wfCwd, setWfCwd] = useState(initialWf?.cwd || Object.values(dirsData || {})[0] || "/tmp");
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [variablesOpen, setVariablesOpen] = useState(false);
  const [variables, setVariables] = useState<WorkflowVariable[]>(initialWf?.variables || []);
  const [animatedNodes, setAnimatedNodes] = useState<Record<string, string>>({});
  const nodeIdCounter = useRef(10);

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => addEdge({
      ...params,
      markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(240 5% 40%)" },
      style: { stroke: "hsl(240 5% 30%)" },
    }, eds));
  }, [setEdges]);

  const addNode = (type: string) => {
    nodeIdCounter.current++;
    const id = `${type}-${nodeIdCounter.current}`;
    const newNode: Node = {
      id,
      type,
      position: { x: 250 + Math.random() * 100, y: 150 + nodes.length * 80 },
      data: type === "prompt" ? { prompt: "" } : type === "branch" ? { branch_type: "conditional", condition: "" } : type === "delay" ? { seconds: 60 } : type === "approval" ? { message: "Approval required" } : type === "notify" ? { channel: "imessage", message: "", wait_for_ack: false } : {},
    };
    setNodes((nds) => [...nds, newNode]);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        name: wfName,
        tool: wfTool,
        cwd: wfCwd,
        require_approval: nodes.some((n) => n.type === "approval"),
        variables,
        nodes: nodes.map((n) => ({ id: n.id, type: n.type, position: n.position, data: n.data })),
        edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: e.label })),
      };
      return activeWorkflowId
        ? api.workflows.update(activeWorkflowId, payload)
        : api.workflows.create(payload);
    },
    onSuccess: (wf) => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      setActiveWorkflowId(wf.id);
    },
  });

  const runMut = useMutation({
    mutationFn: async () => {
      let wfId = activeWorkflowId;
      if (!wfId) {
        const wf = await saveMut.mutateAsync();
        wfId = (wf as any).id;
      }
      return api.workflows.run(wfId!);
    },
    onSuccess: (run) => {
      setActiveRunId(run.id);
      setView("workflow-runner");
    },
  });

  const onNodeClick = useCallback((_: any, node: Node) => {
    setSelectedNode(node);
    if (feedbackOpen) {
      // Feedback panel handles node selection internally
    } else if (node.type !== "start" && node.type !== "end" && node.type !== "merge") {
      setConfigOpen(true);
    }
  }, [feedbackOpen]);

  const updateNodeData = (nodeId: string, newData: any) => {
    setNodes((nds) => nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...newData } } : n)));
    if (selectedNode?.id === nodeId) {
      setSelectedNode((prev) => prev ? { ...prev, data: { ...prev.data, ...newData } } : prev);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 h-12 border-b border-border bg-card/50">
        <Button variant="ghost" size="icon" onClick={() => setView("workflows")}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <Input value={wfName} onChange={(e) => setWfName(e.target.value)} className="w-48 h-8 text-sm font-medium" />
        <div className="border-l border-border h-6 mx-1" />
        {NODE_MENU.map((item) => (
          <button
            key={item.type}
            onClick={() => addNode(item.type)}
            className={cn("px-2 py-1 rounded text-[10px] font-semibold uppercase", item.color)}
          >
            + {item.label}
          </button>
        ))}
        <button
          onClick={() => {
            const result = layoutDagre(nodes, edges);
            setNodes(result.nodes);
          }}
          className="px-2 py-1 rounded text-[10px] font-semibold uppercase bg-muted text-muted-foreground hover:text-foreground"
          title="Auto-layout"
        >
          <LayoutGrid className="w-3 h-3 inline mr-1" />
          Layout
        </button>
        <button
          onClick={() => { setVariablesOpen(!variablesOpen); setConfigOpen(false); setFeedbackOpen(false); }}
          className={cn(
            "px-2 py-1 rounded text-[10px] font-semibold uppercase",
            variablesOpen ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:text-foreground"
          )}
        >
          {"{{x}}"} Vars{variables.length > 0 ? ` (${variables.length})` : ""}
        </button>
        <div className="flex-1" />
        <select value={wfTool} onChange={(e) => setWfTool(e.target.value)} className="h-8 rounded border border-border bg-transparent px-2 text-xs">
          <option value="claude">Claude</option>
          <option value="wasabi">Wasabi</option>
          <option value="kiro">Kiro</option>
        </select>
        <Button size="sm" variant="outline" onClick={() => setGenerateOpen(true)}>
          <Sparkles className="w-3.5 h-3.5" />
          AI
        </Button>
        <Button size="sm" variant={feedbackOpen ? "default" : "outline"} onClick={() => { setFeedbackOpen(!feedbackOpen); setConfigOpen(false); }}>
          <MessageCircle className="w-3.5 h-3.5" />
          Feedback
        </Button>
        <Button size="sm" variant="outline" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
          <Save className="w-3.5 h-3.5" />
          {saveMut.isPending ? "Saving..." : "Save"}
        </Button>
        {activeWorkflowId && (
          <Button size="sm" variant="outline" onClick={async () => {
            const payload = {
              name: `Copy of ${wfName}`,
              tool: wfTool,
              cwd: wfCwd,
              require_approval: nodes.some((n) => n.type === "approval"),
              nodes: nodes.map((n) => ({ id: n.id, type: n.type, position: n.position, data: n.data })),
              edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: e.label })),
              schedule: null,
            };
            const saved = await api.workflows.create(payload);
            qc.invalidateQueries({ queryKey: ["workflows"] });
            setActiveWorkflowId(saved.id);
            setView("workflow-editor");
          }}>
            <Copy className="w-3.5 h-3.5" />
            Copy to New
          </Button>
        )}
        <Button size="sm" onClick={() => runMut.mutate()} disabled={runMut.isPending}>
          <Play className="w-3.5 h-3.5" />
          {runMut.isPending ? "Starting..." : "Run"}
        </Button>
      </div>

      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          className="bg-background"
          defaultEdgeOptions={{
            markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(240 5% 40%)" },
            style: { stroke: "hsl(240 5% 30%)" },
          }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="hsl(240 5% 15%)" />
          <Controls className="!bg-card !border-border !rounded-lg [&>button]:!bg-card [&>button]:!border-border [&>button]:!text-foreground" />
          <MiniMap
            nodeColor="hsl(263 80% 65%)"
            maskColor="hsla(240 10% 4% / 0.8)"
            className="!bg-card !border-border !rounded-lg"
          />
        </ReactFlow>

        {/* Node config panel */}
        {configOpen && selectedNode && (
          <div className="absolute right-0 top-0 bottom-0 w-80 bg-card border-l border-border shadow-xl z-10 flex flex-col">
            <div className="flex items-center justify-between px-4 h-12 border-b border-border">
              <span className="text-sm font-semibold capitalize">{selectedNode.type} config</span>
              <button onClick={() => setConfigOpen(false)}><X className="w-4 h-4 text-muted-foreground" /></button>
            </div>
            <div className="p-4 space-y-4 overflow-y-auto flex-1">
              {selectedNode.type === "prompt" && (
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1.5">Prompt</label>
                  <Textarea
                    value={(selectedNode.data as any)?.prompt || ""}
                    onChange={(e) => updateNodeData(selectedNode.id, { prompt: e.target.value })}
                    placeholder="Enter prompt to execute..."
                    rows={6}
                  />
                </div>
              )}
              {selectedNode.type === "branch" && (
                <>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground block mb-1.5">Branch type</label>
                    <select
                      value={(selectedNode.data as any)?.branch_type || "conditional"}
                      onChange={(e) => updateNodeData(selectedNode.id, { branch_type: e.target.value })}
                      className="w-full h-9 rounded-md border border-border bg-transparent px-3 text-sm"
                    >
                      <option value="conditional">Conditional (LLM decides)</option>
                      <option value="parallel">Parallel (all paths)</option>
                    </select>
                  </div>
                  {(selectedNode.data as any)?.branch_type !== "parallel" && (
                    <div>
                      <label className="text-xs font-medium text-muted-foreground block mb-1.5">Condition</label>
                      <Textarea
                        value={(selectedNode.data as any)?.condition || ""}
                        onChange={(e) => updateNodeData(selectedNode.id, { condition: e.target.value })}
                        placeholder="e.g. any pipelines failing?"
                        rows={3}
                      />
                    </div>
                  )}
                </>
              )}
              {selectedNode.type === "delay" && (
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1.5">Delay (seconds)</label>
                  <Input
                    type="number"
                    value={(selectedNode.data as any)?.seconds || 60}
                    onChange={(e) => updateNodeData(selectedNode.id, { seconds: parseInt(e.target.value) || 0 })}
                  />
                </div>
              )}
              {selectedNode.type === "approval" && (
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1.5">Approval message</label>
                  <Textarea
                    value={(selectedNode.data as any)?.message || ""}
                    onChange={(e) => updateNodeData(selectedNode.id, { message: e.target.value })}
                    placeholder="What are you approving?"
                    rows={3}
                  />
                </div>
              )}
              {selectedNode.type === "notify" && (
                <>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground block mb-1.5">Channel</label>
                    <select
                      value={(selectedNode.data as any)?.channel || "imessage"}
                      onChange={(e) => updateNodeData(selectedNode.id, { channel: e.target.value })}
                      className="w-full h-9 rounded-md border border-border bg-transparent px-3 text-sm"
                    >
                      <option value="imessage">iMessage</option>
                      <option value="slack">Slack</option>
                      <option value="both">Both</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground block mb-1.5">Message</label>
                    <Textarea
                      value={(selectedNode.data as any)?.message || ""}
                      onChange={(e) => updateNodeData(selectedNode.id, { message: e.target.value })}
                      placeholder="Notification message..."
                      rows={4}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="wait-ack"
                      checked={(selectedNode.data as any)?.wait_for_ack || false}
                      onChange={(e) => updateNodeData(selectedNode.id, { wait_for_ack: e.target.checked })}
                      className="rounded border-border"
                    />
                    <label htmlFor="wait-ack" className="text-xs text-muted-foreground">Wait for acknowledgment</label>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Variables Panel */}
      {variablesOpen && (
        <div className="absolute right-0 top-0 bottom-0 z-20">
          <VariablesPanel
            variables={variables}
            onChange={setVariables}
            onClose={() => setVariablesOpen(false)}
          />
        </div>
      )}

      {/* Feedback Panel */}
      {feedbackOpen && (
        <div className="absolute right-0 top-0 bottom-0 z-20">
          <FeedbackPanel
            workflowId={activeWorkflowId}
            selectedNode={selectedNode ? { id: selectedNode.id, type: selectedNode.type, data: selectedNode.data } : null}
            onClose={() => setFeedbackOpen(false)}
            onRefined={(wf, diff) => {
              const rfNodes = (wf.nodes || []).map((n: any) => ({
                id: n.id,
                type: n.type,
                position: n.position || { x: 0, y: 0 },
                data: n.data || {},
              }));
              const rfEdges = (wf.edges || []).map((e: any) => ({
                id: e.id || `e-${e.source}-${e.target}`,
                source: e.source,
                target: e.target,
                label: e.label,
                markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(240 5% 40%)" },
                style: { stroke: "hsl(240 5% 30%)" },
              }));
              const needsLayout = rfNodes.some((n: any) => n.position.x === 0 && n.position.y === 0);
              const laid = needsLayout ? layoutDagre(rfNodes, rfEdges) : { nodes: rfNodes, edges: rfEdges };

              // Apply animation classes
              const anims: Record<string, string> = {};
              for (const id of diff.added || []) anims[id] = "node-added";
              for (const id of diff.changed || []) anims[id] = "node-updated";
              setAnimatedNodes(anims);
              setTimeout(() => setAnimatedNodes({}), 2500);

              setNodes(laid.nodes.map((n: any) => ({ ...n, className: anims[n.id] || "" })));
              setEdges(laid.edges);
              if (wf.name) setWfName(wf.name);
            }}
          />
        </div>
      )}

      <GenerateWorkflowDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        defaultTool={wfTool}
        onGenerated={(wf) => {
          const rfNodes = (wf.nodes || []).map((n: any) => ({
            id: n.id,
            type: n.type,
            position: n.position || { x: 250, y: 0 },
            data: n.data || {},
          }));
          const rfEdges = (wf.edges || []).map((e: any) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.label,
            markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(240 5% 40%)" },
            style: { stroke: "hsl(240 5% 30%)" },
          }));
          const laid = layoutDagre(rfNodes, rfEdges);
          setNodes(laid.nodes);
          setEdges(laid.edges);
          if (wf.name) setWfName(wf.name);
          if (wf.tool) setWfTool(wf.tool);
          if (wf.cwd) setWfCwd(wf.cwd);
        }}
      />
    </div>
  );
}
