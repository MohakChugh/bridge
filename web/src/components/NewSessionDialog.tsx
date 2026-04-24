import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button, Input } from "./ui";
import { cn } from "@/lib/utils";
import { Plus, X } from "lucide-react";

export function NewSessionDialog({ onCreated }: { onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [tool, setTool] = useState("wasabi");
  const [cwdAlias, setCwdAlias] = useState("default");
  const qc = useQueryClient();

  const { data: dirsData } = useQuery({ queryKey: ["directories"], queryFn: api.directories });
  const { data: toolsData } = useQuery({ queryKey: ["tools"], queryFn: api.tools });

  const dirs = dirsData ?? {};
  const tools = toolsData?.tools ?? ["claude", "wasabi", "kiro"];
  const defaultTool = toolsData?.active ?? "wasabi";

  const createMut = useMutation({
    mutationFn: () =>
      api.sessions.create({
        tool,
        cwd: dirs[cwdAlias] || Object.values(dirs)[0] || "/tmp",
        title: title || undefined,
      }),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onCreated(session.id);
      setOpen(false);
      setTitle("");
    },
  });

  if (!open) {
    return (
      <Button
        size="sm"
        onClick={() => {
          setTool(defaultTool);
          const firstAlias = Object.keys(dirs)[0];
          if (firstAlias) setCwdAlias(firstAlias);
          setOpen(true);
        }}
      >
        <Plus className="w-3.5 h-3.5" />
        New session
      </Button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md p-5 relative">
        <button
          onClick={() => setOpen(false)}
          className="absolute right-3 top-3 text-muted-foreground hover:text-foreground"
        >
          <X className="w-4 h-4" />
        </button>
        <h2 className="font-semibold mb-4">New session</h2>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Title (optional)</label>
            <Input placeholder="centralis debug" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Tool</label>
            <div className="flex gap-2">
              {tools.map((t) => (
                <button
                  key={t}
                  onClick={() => setTool(t)}
                  className={cn(
                    "flex-1 h-9 rounded-md text-sm font-medium border transition-colors capitalize",
                    tool === t
                      ? "bg-primary/15 border-primary text-primary"
                      : "border-border hover:bg-accent",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Directory</label>
            <select
              value={cwdAlias}
              onChange={(e) => setCwdAlias(e.target.value)}
              className="w-full h-9 rounded-md border border-border bg-transparent px-3 text-sm"
            >
              {Object.entries(dirs).map(([alias, path]) => (
                <option key={alias} value={alias} className="bg-card">
                  {alias} — {path as string}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 justify-end pt-2">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending || !Object.keys(dirs).length}
            >
              {createMut.isPending ? "Creating…" : "Create"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
