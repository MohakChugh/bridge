import { useState } from "react";
import { Button, Input, Badge } from "./ui";
import { Plus, Trash2, Variable } from "lucide-react";

export interface WorkflowVariable {
  name: string;
  type: "string" | "date" | "number";
  default: string;
  description: string;
}

interface Props {
  variables: WorkflowVariable[];
  onChange: (vars: WorkflowVariable[]) => void;
  onClose: () => void;
}

export function VariablesPanel({ variables, onChange, onClose }: Props) {
  const [newName, setNewName] = useState("");

  const addVariable = () => {
    if (!newName.trim()) return;
    const name = newName.trim().replace(/\s+/g, "_").toLowerCase();
    if (variables.some((v) => v.name === name)) return;
    onChange([...variables, { name, type: "string", default: "", description: "" }]);
    setNewName("");
  };

  const updateVar = (idx: number, field: string, value: string) => {
    const updated = [...variables];
    (updated[idx] as any)[field] = value;
    onChange(updated);
  };

  const removeVar = (idx: number) => {
    onChange(variables.filter((_, i) => i !== idx));
  };

  return (
    <div className="absolute right-0 top-0 bottom-0 w-80 bg-card border-l border-border shadow-xl z-10 flex flex-col">
      <div className="flex items-center justify-between px-4 h-12 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Variable className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">Variables</span>
          <Badge variant="secondary" className="text-[9px]">{variables.length}</Badge>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xs">Close</button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {variables.length === 0 && (
          <div className="text-center text-xs text-muted-foreground py-6">
            No variables defined. Add one to parameterize your workflow.
            <br /><br />
            Use <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{variable_name}}"}</code> in prompt text.
          </div>
        )}

        {variables.map((v, i) => (
          <div key={v.name} className="bg-accent/30 border border-border rounded-md p-3 space-y-2">
            <div className="flex items-center justify-between">
              <code className="text-xs font-mono text-primary">{`{{${v.name}}}`}</code>
              <button onClick={() => removeVar(i)} className="text-muted-foreground hover:text-destructive">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-muted-foreground">Type</label>
                <select
                  value={v.type}
                  onChange={(e) => updateVar(i, "type", e.target.value)}
                  className="w-full h-7 rounded border border-border bg-transparent px-2 text-xs"
                >
                  <option value="string">String</option>
                  <option value="date">Date</option>
                  <option value="number">Number</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Default</label>
                <Input
                  value={v.default}
                  onChange={(e) => updateVar(i, "default", e.target.value)}
                  placeholder={v.type === "date" ? "today - 7d" : "value"}
                  className="h-7 text-xs"
                />
              </div>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Description</label>
              <Input
                value={v.description}
                onChange={(e) => updateVar(i, "description", e.target.value)}
                placeholder="What this variable is for"
                className="h-7 text-xs"
              />
            </div>
            {v.type === "date" && v.default && (
              <div className="text-[10px] text-muted-foreground">
                Expressions: today, today-7d, yesterday, start_of_week, last_tuesday, etc.
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="border-t border-border p-3 shrink-0">
        <div className="flex gap-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="variable_name"
            className="h-8 text-xs font-mono"
            onKeyDown={(e) => { if (e.key === "Enter") addVariable(); }}
          />
          <Button size="sm" onClick={addVariable} disabled={!newName.trim()}>
            <Plus className="w-3 h-3" />
          </Button>
        </div>
      </div>
    </div>
  );
}
