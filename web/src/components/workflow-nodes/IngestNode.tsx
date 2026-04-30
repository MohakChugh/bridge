import { type NodeProps } from "@xyflow/react";
import { BaseNode } from "./BaseNode";
import { Database } from "lucide-react";

export function IngestNode({ data, selected }: NodeProps) {
  const d = data as any;
  const collection = d?.collection;
  const autoDedup = d?.auto_dedup === true;
  const docName = d?.doc_name;
  return (
    <BaseNode selected={selected} className="bg-card p-3">
      <div className="flex items-start gap-2">
        <Database className="w-4 h-4 text-primary shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-primary">Ingest</span>
            {autoDedup && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-primary/20 text-primary font-medium">dedup</span>
            )}
          </div>
          {collection && (
            <div className="text-xs text-foreground/80 mt-0.5 line-clamp-2">→ {collection}</div>
          )}
          {docName && (
            <div className="text-[9px] text-muted-foreground mt-0.5 line-clamp-1">doc: {docName}</div>
          )}
        </div>
      </div>
    </BaseNode>
  );
}
