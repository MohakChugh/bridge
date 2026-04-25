import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { ShieldCheck } from "lucide-react";

export function ApprovalNode({ data, selected }: NodeProps) {
  const message = (data as any)?.message || "Approval required";
  return (
    <BaseNode selected={selected} className="bg-card p-3 border-dashed">
      <div className="flex items-start gap-2">
        <ShieldCheck className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-destructive">Approval</div>
          <div className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{message}</div>
        </div>
      </div>
    </BaseNode>
  );
}
