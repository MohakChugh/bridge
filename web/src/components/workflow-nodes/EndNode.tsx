import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Square } from "lucide-react";

export function EndNode({ selected }: NodeProps) {
  return (
    <BaseNode shape="circle" selected={selected} className="bg-destructive/20 flex items-center justify-center" handles={{ top: true, bottom: false }}>
      <Square className="w-4 h-4 text-destructive" />
    </BaseNode>
  );
}
