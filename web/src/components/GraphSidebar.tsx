import { cn } from "@/lib/utils";
import { Badge } from "./ui";
import { Sparkles, GitBranch, Database, Tag } from "lucide-react";

interface GraphSidebarProps {
  clusters: Array<{ id: string; name: string; color: string; nodeIds: Set<number> }>;
  topNodes: Array<{ id: number; text: string; degree: number; cluster?: string; color?: string }>;
  stats: {
    nodes: number;
    edges: number;
    clusters: number;
    avgDegree: string;
    density: string;
  };
  selectedNode: any | null;
  onClusterClick: (clusterId: string | null) => void;
  onNodeClick: (nodeId: number) => void;
  highlightedCluster: string | null;
}

export function GraphSidebar({
  clusters,
  topNodes,
  stats,
  selectedNode,
  onClusterClick,
  onNodeClick,
  highlightedCluster,
}: GraphSidebarProps) {
  const totalNodes = stats.nodes || 1;

  return (
    <aside className="w-72 shrink-0 border-l border-border bg-card overflow-y-auto h-full flex flex-col">
      {/* Topic Clusters */}
      <section className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold tracking-tight">Topic Clusters</h3>
        </div>
        <div className="space-y-2">
          {clusters.map((cluster) => {
            const count = cluster.nodeIds.size;
            const pct = Math.round((count / totalNodes) * 100);
            const isActive = highlightedCluster === cluster.id;

            return (
              <button
                key={cluster.id}
                onClick={() => onClusterClick(isActive ? null : cluster.id)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-left transition-colors",
                  isActive
                    ? "bg-accent/50"
                    : "hover:bg-accent/30",
                )}
              >
                <span
                  className={cn(
                    "w-2 h-2 rounded-full shrink-0 transition-shadow",
                    isActive && "ring-2 ring-offset-1 ring-offset-card",
                  )}
                  style={{
                    backgroundColor: cluster.color,
                    boxShadow: isActive ? `0 0 6px ${cluster.color}` : undefined,
                  }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-sm truncate">{cluster.name}</span>
                    <span className="text-xs text-muted-foreground shrink-0">{count}</span>
                  </div>
                  <div className="mt-1 h-1 w-full rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${pct}%`, backgroundColor: cluster.color }}
                    />
                  </div>
                </div>
              </button>
            );
          })}
          {clusters.length === 0 && (
            <p className="text-xs text-muted-foreground">No clusters detected</p>
          )}
        </div>
      </section>

      {/* Most Connected */}
      <section className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <GitBranch className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold tracking-tight">Most Connected</h3>
        </div>
        <div className="space-y-1">
          {topNodes.slice(0, 10).map((node) => (
            <button
              key={node.id}
              onClick={() => onNodeClick(node.id)}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left hover:bg-accent/30 transition-colors"
            >
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ backgroundColor: node.color || "#6b7280" }}
              />
              <span className="text-sm truncate flex-1 min-w-0">
                {node.text.length > 40 ? `${node.text.slice(0, 40)}...` : node.text}
              </span>
              <Badge variant="secondary" className="shrink-0 text-[9px] px-1.5 py-0">
                {node.degree}
              </Badge>
            </button>
          ))}
          {topNodes.length === 0 && (
            <p className="text-xs text-muted-foreground">No nodes available</p>
          )}
        </div>
      </section>

      {/* Selected Node Detail */}
      {selectedNode && (
        <section className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 mb-3">
            <Database className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold tracking-tight">Selected Node</h3>
          </div>
          <div className="space-y-2">
            <p className="text-sm leading-relaxed">
              {typeof selectedNode.text === "string"
                ? selectedNode.text.length > 200
                  ? `${selectedNode.text.slice(0, 200)}...`
                  : selectedNode.text
                : "—"}
            </p>

            {selectedNode.collection && (
              <div className="flex items-center gap-1.5">
                <Database className="w-3 h-3 text-muted-foreground" />
                <Badge variant="outline" className="text-[9px]">
                  {selectedNode.collection}
                </Badge>
              </div>
            )}

            {selectedNode.tags && selectedNode.tags.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                <Tag className="w-3 h-3 text-muted-foreground shrink-0" />
                {selectedNode.tags.map((tag: string) => (
                  <Badge key={tag} variant="secondary" className="text-[9px]">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}

            {selectedNode.document && (
              <p className="text-xs text-muted-foreground truncate">
                {selectedNode.document}
              </p>
            )}

            {selectedNode.summary && (
              <p className="text-xs text-muted-foreground leading-relaxed">
                {selectedNode.summary}
              </p>
            )}
          </div>
        </section>
      )}

      {/* Graph Stats */}
      <section className="px-4 py-3 mt-auto">
        <div className="grid grid-cols-2 gap-2">
          <StatMini label="Nodes" value={stats.nodes} />
          <StatMini label="Edges" value={stats.edges} />
          <StatMini label="Clusters" value={stats.clusters} />
          <StatMini label="Avg Degree" value={stats.avgDegree} />
        </div>
      </section>
    </aside>
  );
}

function StatMini({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 px-2.5 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold tracking-tight">{value}</p>
    </div>
  );
}
