import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Textarea, Badge } from "./ui";
import { X, Sparkles, RefreshCw, ArrowRight, MessageSquare, GitBranch, Bell, ShieldCheck, Clock, Play, Square } from "lucide-react";
import { ToolSelect } from "./ToolSelect";

const NODE_ICONS: Record<string, any> = {
  start: Play,
  end: Square,
  prompt: MessageSquare,
  branch: GitBranch,
  merge: GitBranch,
  delay: Clock,
  approval: ShieldCheck,
  notify: Bell,
};

const NODE_COLORS: Record<string, string> = {
  start: "text-success",
  end: "text-destructive",
  prompt: "text-primary",
  branch: "text-warning",
  merge: "text-warning",
  delay: "text-muted-foreground",
  approval: "text-destructive",
  notify: "text-primary",
};

interface Props {
  open: boolean;
  onClose: () => void;
  onGenerated: (workflow: any) => void;
  defaultTool?: string;
}

export function GenerateWorkflowDialog({ open, onClose, onGenerated, defaultTool }: Props) {
  const [text, setText] = useState("");
  const [tool, setTool] = useState(defaultTool || "wasabi");
  const [cwdAlias, setCwdAlias] = useState("default");
  const [generated, setGenerated] = useState<any | null>(null);

  const { data: dirsData } = useQuery({ queryKey: ["directories"], queryFn: api.directories });
  const dirs = dirsData ?? {};

  const generateMut = useMutation({
    mutationFn: () =>
      api.workflows.generate({
        text,
        tool,
        cwd: dirs[cwdAlias] || Object.values(dirs)[0] || "/tmp",
      }),
    onSuccess: (data) => setGenerated(data),
  });

  function reset() {
    setText("");
    setGenerated(null);
    generateMut.reset();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-lg p-5 relative max-h-[85vh] overflow-y-auto">
        <button onClick={() => { reset(); onClose(); }} className="absolute right-3 top-3 text-muted-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="w-5 h-5 text-primary" />
          <h2 className="font-semibold">Generate Workflow with AI</h2>
        </div>

        {!generated ? (
          <>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">
              Describe what you want the workflow to do
            </label>
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={"Every morning check my pipeline status. If any pipeline is blocked, diagnose the root cause and get ADA credentials for the failing account. Send me a summary on iMessage with the issue and suggested fix."}
              rows={5}
              autoFocus
            />

            <div className="flex gap-3 mt-4">
              <div className="flex-1">
                <label className="text-[10px] font-medium text-muted-foreground block mb-1">Tool</label>
                <ToolSelect value={tool} onChange={setTool} className="w-full h-8 rounded-md border border-border bg-transparent px-2 text-xs" />
              </div>
              <div className="flex-1">
                <label className="text-[10px] font-medium text-muted-foreground block mb-1">Directory</label>
                <select
                  value={cwdAlias}
                  onChange={(e) => setCwdAlias(e.target.value)}
                  className="w-full h-8 rounded-md border border-border bg-transparent px-2 text-xs"
                >
                  {Object.entries(dirs).map(([alias, path]) => (
                    <option key={alias} value={alias} className="bg-card">
                      {alias}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex justify-end mt-4">
              <Button
                onClick={() => generateMut.mutate()}
                disabled={!text.trim() || generateMut.isPending}
              >
                <Sparkles className="w-3.5 h-3.5" />
                {generateMut.isPending ? "Generating..." : "Generate"}
              </Button>
            </div>

            {generateMut.isError && (
              <div className="text-xs text-destructive mt-2">
                Generation failed — try simplifying your description or try again
              </div>
            )}
          </>
        ) : (
          <>
            <div className="bg-accent/50 border border-border rounded-md p-4 space-y-3">
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Workflow</div>
                <div className="text-sm font-medium">{generated.name}</div>
                {generated.description && (
                  <div className="text-xs text-muted-foreground mt-0.5">{generated.description}</div>
                )}
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">
                  {generated.nodes?.length || 0} nodes · {generated.edges?.length || 0} edges
                </div>
                <ul className="space-y-1.5">
                  {(generated.nodes || []).map((node: any, i: number) => {
                    const Icon = NODE_ICONS[node.type] || MessageSquare;
                    const color = NODE_COLORS[node.type] || "text-muted-foreground";
                    const label =
                      node.type === "start" ? "Start" :
                      node.type === "end" ? "End" :
                      node.type === "merge" ? "Merge" :
                      node.data?.prompt?.slice(0, 60) ||
                      node.data?.condition?.slice(0, 60) ||
                      node.data?.message?.slice(0, 60) ||
                      node.type;
                    return (
                      <li key={node.id} className="flex items-center gap-2 text-xs">
                        <span className="text-muted-foreground w-4 text-right">{i + 1}.</span>
                        <Icon className={`w-3.5 h-3.5 shrink-0 ${color}`} />
                        <Badge variant="secondary" className="text-[9px] shrink-0">{node.type}</Badge>
                        <span className="truncate text-foreground/80">{label}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>

            <div className="flex justify-between mt-4 gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setGenerated(null);
                  generateMut.reset();
                }}
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Regenerate
              </Button>
              <Button
                onClick={() => {
                  onGenerated(generated);
                  reset();
                  onClose();
                }}
              >
                <ArrowRight className="w-3.5 h-3.5" />
                Open in Editor
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
