import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Sparkles } from "lucide-react";

export function DiscoverNode({ data, selected }: NodeProps) {
  const d = data as any;
  const target = d?.target;
  const tool = d?.tool;
  return (
    <BaseNode selected={selected} className="bg-card p-3">
      <div className="flex items-start gap-2">
        <Sparkles className="w-4 h-4 text-primary shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">Discover</div>
          {target && (
            <div className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{target}</div>
          )}
          {tool && (
            <div className="text-[9px] text-muted-foreground mt-0.5 line-clamp-1">tool: {tool}</div>
          )}
        </div>
      </div>
    </BaseNode>
  );
}
