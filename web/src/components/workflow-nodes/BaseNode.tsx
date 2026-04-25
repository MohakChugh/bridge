import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";

export function BaseNode({
  children,
  className,
  shape = "rounded",
  statusColor,
  selected,
  handles = { top: true, bottom: true },
}: {
  children: React.ReactNode;
  className?: string;
  shape?: "rounded" | "diamond" | "circle";
  statusColor?: string;
  selected?: boolean;
  handles?: { top?: boolean; bottom?: boolean; left?: boolean; right?: boolean };
}) {
  const shapeClass =
    shape === "diamond"
      ? "rotate-45 w-16 h-16"
      : shape === "circle"
        ? "rounded-full w-14 h-14"
        : "rounded-lg min-w-[180px]";

  return (
    <div
      className={cn(
        "border-2 transition-all duration-200",
        selected ? "border-primary shadow-lg shadow-primary/20" : "border-border",
        statusColor,
        shapeClass,
        className,
      )}
    >
      {handles.top && <Handle type="target" position={Position.Top} className="!w-2.5 !h-2.5 !bg-muted-foreground !border-2 !border-background" />}
      {handles.bottom && <Handle type="source" position={Position.Bottom} className="!w-2.5 !h-2.5 !bg-muted-foreground !border-2 !border-background" />}
      {handles.left && <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !bg-muted-foreground !border-2 !border-background" />}
      {handles.right && <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !bg-muted-foreground !border-2 !border-background" />}
      {children}
    </div>
  );
}
