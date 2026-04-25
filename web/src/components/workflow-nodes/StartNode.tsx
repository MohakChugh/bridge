import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Play } from "lucide-react";

export function StartNode({ selected }: NodeProps) {
  return (
    <BaseNode shape="circle" selected={selected} className="bg-success/20 flex items-center justify-center" handles={{ top: false, bottom: true }}>
      <Play className="w-5 h-5 text-success" />
    </BaseNode>
  );
}
