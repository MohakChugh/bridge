import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { MessageSquare } from "lucide-react";

export function PromptNode({ data, selected }: NodeProps) {
  const prompt = (data as any)?.prompt || "Click to edit prompt...";
  return (
    <BaseNode selected={selected} className="bg-card p-3">
      <div className="flex items-start gap-2">
        <MessageSquare className="w-4 h-4 text-primary shrink-0 mt-0.5" />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">Prompt</div>
          <div className="text-xs text-foreground/80 mt-0.5 line-clamp-3">{prompt}</div>
        </div>
      </div>
    </BaseNode>
  );
}
