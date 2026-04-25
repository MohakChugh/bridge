import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { GitBranch } from "lucide-react";

export function BranchNode({ data, selected }: NodeProps) {
  const d = data as any;
  const branchType = d?.branch_type || "conditional";
  const condition = d?.condition || "";
  return (
    <BaseNode selected={selected} className="bg-card p-3">
      <div className="flex items-start gap-2">
        <GitBranch className="w-4 h-4 text-warning shrink-0 mt-0.5" />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-warning">
            {branchType === "parallel" ? "Parallel" : "Branch"}
          </div>
          {condition && <div className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{condition}</div>}
        </div>
      </div>
    </BaseNode>
  );
}
