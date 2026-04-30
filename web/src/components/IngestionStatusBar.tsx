import { useIngestionStore } from "@/stores/ingestionStore";
import { Card, CardContent } from "./ui";
import { cn } from "@/lib/utils";
import { RefreshCw, CheckCircle2, XCircle, Trash2, Copy } from "lucide-react";

export function IngestionStatusBar() {
  const { active, recentEvents, totalsToday } = useIngestionStore();
  const activeList = Array.from(active.values());

  if (activeList.length === 0 && recentEvents.length === 0) return null;

  const PHASE_LABELS: Record<string, string> = {
    fetching: "Fetching content",
    chunked: "Chunking",
    processing: "Summarize + Tag + Embed",
    completed: "Done",
  };

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="py-3 space-y-2">
        {activeList.length > 0 && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs font-medium text-foreground">
              <RefreshCw className="w-3.5 h-3.5 text-primary animate-spin" />
              <span>{activeList.length} ingesting</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">
                Today: {totalsToday.docs} docs, {totalsToday.chunks} chunks, {totalsToday.deletions} deleted
              </span>
            </div>
            {activeList.slice(0, 5).map((a) => {
              const pct = a.total > 0 ? Math.round((a.current / a.total) * 100) : 0;
              return (
                <div key={a.docId} className="flex items-center gap-2 text-[11px]">
                  <span className="w-32 truncate text-foreground/90">{a.name}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-muted-foreground shrink-0">
                    {PHASE_LABELS[a.phase] || a.phase} {a.total > 0 ? `${a.current}/${a.total}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {recentEvents.length > 0 && (
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {recentEvents.slice(0, 8).map((e) => {
              const Icon = e.type === "ingested" ? CheckCircle2
                : e.type === "deleted" ? Trash2
                : e.type === "duplicate" ? Copy
                : e.type === "refresh.started" || e.type === "refresh.cleared" ? RefreshCw
                : CheckCircle2;
              const color = e.type === "ingested" ? "text-green-400"
                : e.type === "deleted" ? "text-destructive"
                : e.type === "duplicate" ? "text-warning"
                : "text-muted-foreground";
              return (
                <div key={e.id} className="flex items-center gap-2 text-[11px]">
                  <Icon className={cn("w-3 h-3 shrink-0", color)} />
                  <span className="text-foreground/80 truncate">{e.message}</span>
                  <span className="text-muted-foreground/60 shrink-0">
                    {new Date(e.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
