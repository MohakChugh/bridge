import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Clock } from "lucide-react";

export function DelayNode({ data, selected }: NodeProps) {
  const seconds = (data as any)?.seconds || 0;
  const label = seconds >= 60 ? `${Math.floor(seconds / 60)}m` : `${seconds}s`;
  return (
    <BaseNode selected={selected} className="bg-card p-3 !min-w-[100px]">
      <div className="flex items-center gap-2 justify-center">
        <Clock className="w-4 h-4 text-muted-foreground" />
        <span className="text-xs text-foreground">{label}</span>
      </div>
    </BaseNode>
  );
}
