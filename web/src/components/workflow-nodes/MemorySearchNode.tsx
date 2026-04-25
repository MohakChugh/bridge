import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Brain } from "lucide-react";

export function MemorySearchNode({ data, selected }: NodeProps) {
  const d = data as any;
  const query = d?.query || "Search query...";
  const collections = d?.collections?.join(", ") || "all";
  return (
    <BaseNode selected={selected} className="bg-card p-3">
      <div className="flex items-start gap-2">
        <Brain className="w-4 h-4 text-primary shrink-0 mt-0.5" />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">Memory Search</div>
          <div className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{query}</div>
          <div className="text-[9px] text-muted-foreground mt-0.5">Collections: {collections}</div>
        </div>
      </div>
    </BaseNode>
  );
}
