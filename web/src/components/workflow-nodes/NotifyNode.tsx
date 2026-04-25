import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Bell } from "lucide-react";

const CHANNEL_BADGE: Record<string, string> = {
  imessage: "iMsg",
  slack: "Slack",
  both: "Both",
};

export function NotifyNode({ data, selected }: NodeProps) {
  const d = data as any;
  const channel = d?.channel || "imessage";
  const message = d?.message || "Notification";
  const waitForAck = d?.wait_for_ack || false;
  return (
    <BaseNode selected={selected} className="bg-card p-3">
      <div className="flex items-start gap-2">
        <Bell className="w-4 h-4 text-primary shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-primary">Notify</span>
            <span className="text-[9px] px-1 py-0.5 rounded bg-primary/20 text-primary font-medium">
              {CHANNEL_BADGE[channel] || channel}
            </span>
            {waitForAck && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-warning/20 text-warning font-medium">wait</span>
            )}
          </div>
          <div className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{message}</div>
        </div>
      </div>
    </BaseNode>
  );
}
