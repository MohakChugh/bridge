import { type NodeTypes } from "@xyflow/react";
import { StartNode } from "./StartNode";
import { PromptNode } from "./PromptNode";
import { BranchNode } from "./BranchNode";
import { MergeNode } from "./MergeNode";
import { DelayNode } from "./DelayNode";
import { ApprovalNode } from "./ApprovalNode";
import { NotifyNode } from "./NotifyNode";
import { EndNode } from "./EndNode";
import { MemorySearchNode } from "./MemorySearchNode";

export const nodeTypes: NodeTypes = {
  start: StartNode,
  prompt: PromptNode,
  branch: BranchNode,
  merge: MergeNode,
  delay: DelayNode,
  approval: ApprovalNode,
  notify: NotifyNode,
  "memory-search": MemorySearchNode,
  end: EndNode,
};

export const NODE_MENU = [
  { type: "prompt", label: "Prompt", color: "bg-primary/20 text-primary" },
  { type: "notify", label: "Notify", color: "bg-primary/20 text-primary" },
  { type: "memory-search", label: "Memory", color: "bg-primary/20 text-primary" },
  { type: "branch", label: "Branch", color: "bg-warning/20 text-warning" },
  { type: "delay", label: "Delay", color: "bg-muted text-muted-foreground" },
  { type: "approval", label: "Approval", color: "bg-destructive/20 text-destructive" },
  { type: "end", label: "End", color: "bg-destructive/20 text-destructive" },
] as const;
