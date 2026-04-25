import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Merge } from "lucide-react";

export function MergeNode({ selected }: NodeProps) {
  return (
    <BaseNode selected={selected} className="bg-card p-3 !min-w-[100px]">
      <div className="flex items-center gap-2 justify-center">
        <Merge className="w-4 h-4 text-warning" />
        <span className="text-[10px] font-semibold uppercase tracking-wide text-warning">Merge</span>
      </div>
    </BaseNode>
  );
}
