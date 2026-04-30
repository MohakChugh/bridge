import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, Badge, Button, Input } from "./ui";
import { cn } from "@/lib/utils";
import { ScrollText, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { useLogStore, type LogEntry, type RequestEntry, type EventEntry } from "@/stores/logStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTs(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString("en", {
    hour12: false,
    fractionalSecondDigits: 3,
  } as Intl.DateTimeFormatOptions);
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}

function tryFormatJson(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return raw;
  }
}

const LEVEL_VARIANT: Record<string, "destructive" | "warning" | "default" | "secondary"> = {
  CRITICAL: "destructive",
  ERROR: "destructive",
  WARNING: "warning",
  INFO: "default",
  DEBUG: "secondary",
};

const METHOD_VARIANT: Record<string, "secondary" | "default" | "warning" | "destructive"> = {
  GET: "secondary",
  POST: "default",
  PUT: "warning",
  DELETE: "destructive",
};

function statusVariant(status: number): "success" | "warning" | "destructive" | "secondary" {
  if (status >= 200 && status < 300) return "success";
  if (status >= 400 && status < 500) return "warning";
  if (status >= 500) return "destructive";
  return "secondary";
}

const TIME_RANGES: { label: string; seconds: number | null }[] = [
  { label: "Last 1m", seconds: 60 },
  { label: "Last 5m", seconds: 300 },
  { label: "Last 15m", seconds: 900 },
  { label: "Last 1h", seconds: 3600 },
  { label: "All", seconds: null },
];

// ---------------------------------------------------------------------------
// Inner tables
// ---------------------------------------------------------------------------

function LogsTable({ rows, total, onLoadMore }: { rows: LogEntry[]; total: number; onLoadMore: () => void }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  if (rows.length === 0) {
    return (
      <Card><CardContent className="py-8 text-center text-muted-foreground text-sm">No logs yet</CardContent></Card>
    );
  }

  return (
    <div className="space-y-1">
      {rows.map((r) => {
        const open = expanded.has(r.id);
        return (
          <div key={r.id} className="rounded border border-border bg-card text-xs">
            <button
              onClick={() => toggle(r.id)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-accent/50 transition-colors"
            >
              {open ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
              <span className="text-muted-foreground font-mono w-[90px] shrink-0">{formatTs(r.timestamp)}</span>
              <Badge variant={LEVEL_VARIANT[r.level] ?? "secondary"} className="shrink-0">{r.level}</Badge>
              <span className="text-muted-foreground shrink-0 max-w-[120px] truncate">{r.logger}</span>
              <span className="truncate">{truncate(r.message, 100)}</span>
            </button>
            {open && (
              <div className="px-3 pb-2 pt-1 border-t border-border space-y-1 text-xs">
                <p className="whitespace-pre-wrap break-all">{r.message}</p>
                {r.data && r.data !== "{}" && (
                  <pre className="bg-muted rounded p-2 overflow-x-auto text-[11px] max-h-60">{tryFormatJson(r.data)}</pre>
                )}
                {r.correlation_id && (
                  <p className="text-muted-foreground">correlation_id: <span className="font-mono">{r.correlation_id}</span></p>
                )}
              </div>
            )}
          </div>
        );
      })}
      {total > rows.length && (
        <Button variant="outline" size="sm" className="w-full" onClick={onLoadMore}>
          Load more ({rows.length} / {total})
        </Button>
      )}
    </div>
  );
}

function RequestsTable({ rows, total, onLoadMore }: { rows: RequestEntry[]; total: number; onLoadMore: () => void }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  if (rows.length === 0) {
    return (
      <Card><CardContent className="py-8 text-center text-muted-foreground text-sm">No requests yet</CardContent></Card>
    );
  }

  return (
    <div className="space-y-1">
      {rows.map((r) => {
        const open = expanded.has(r.id);
        return (
          <div key={r.id} className="rounded border border-border bg-card text-xs">
            <button
              onClick={() => toggle(r.id)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-accent/50 transition-colors"
            >
              {open ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
              <span className="text-muted-foreground font-mono w-[90px] shrink-0">{formatTs(r.timestamp)}</span>
              <Badge variant={METHOD_VARIANT[r.method] ?? "secondary"} className="shrink-0">{r.method}</Badge>
              <span className="truncate font-mono">{r.path}</span>
              <Badge variant={statusVariant(r.status)} className="shrink-0">{r.status}</Badge>
              <span className="text-muted-foreground shrink-0">{r.duration_ms != null ? `${Math.round(r.duration_ms)}ms` : "-"}</span>
            </button>
            {open && (
              <div className="px-3 pb-2 pt-1 border-t border-border space-y-1 text-xs">
                {r.request_body && r.request_body !== "" && (
                  <div>
                    <p className="text-muted-foreground mb-0.5">Request body</p>
                    <pre className="bg-muted rounded p-2 overflow-x-auto text-[11px] max-h-40">{tryFormatJson(r.request_body)}</pre>
                  </div>
                )}
                {r.response_body && r.response_body !== "" && (
                  <div>
                    <p className="text-muted-foreground mb-0.5">Response body</p>
                    <pre className="bg-muted rounded p-2 overflow-x-auto text-[11px] max-h-40">{tryFormatJson(r.response_body)}</pre>
                  </div>
                )}
                {r.correlation_id && (
                  <p className="text-muted-foreground">correlation_id: <span className="font-mono">{r.correlation_id}</span></p>
                )}
              </div>
            )}
          </div>
        );
      })}
      {total > rows.length && (
        <Button variant="outline" size="sm" className="w-full" onClick={onLoadMore}>
          Load more ({rows.length} / {total})
        </Button>
      )}
    </div>
  );
}

function EventsTable({ rows, total, onLoadMore }: { rows: EventEntry[]; total: number; onLoadMore: () => void }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  if (rows.length === 0) {
    return (
      <Card><CardContent className="py-8 text-center text-muted-foreground text-sm">No events yet</CardContent></Card>
    );
  }

  return (
    <div className="space-y-1">
      {rows.map((r) => {
        const open = expanded.has(r.id);
        return (
          <div key={r.id} className="rounded border border-border bg-card text-xs">
            <button
              onClick={() => toggle(r.id)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-accent/50 transition-colors"
            >
              {open ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
              <span className="text-muted-foreground font-mono w-[90px] shrink-0">{formatTs(r.timestamp)}</span>
              <Badge variant="outline" className="shrink-0">{r.type}</Badge>
              <span className="truncate">{truncate(r.data || "", 100)}</span>
            </button>
            {open && (
              <div className="px-3 pb-2 pt-1 border-t border-border text-xs">
                <pre className="bg-muted rounded p-2 overflow-x-auto text-[11px] max-h-60">{tryFormatJson(r.data)}</pre>
              </div>
            )}
          </div>
        );
      })}
      {total > rows.length && (
        <Button variant="outline" size="sm" className="w-full" onClick={onLoadMore}>
          Load more ({rows.length} / {total})
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function LogViewer() {
  const { filters, setFilters } = useLogStore();
  const queryClient = useQueryClient();
  const searchRef = useRef<ReturnType<typeof setTimeout>>();

  const [localSearch, setLocalSearch] = useState(filters.q);
  const [limit, setLimit] = useState(200);

  const tab = filters.tab;

  // Compute `since` epoch from the selected time range
  const sinceEpoch = useMemo(() => {
    if (filters.since == null) return undefined;
    return filters.since;
  }, [filters.since]);

  // --- Queries ---

  const { data: stats } = useQuery({
    queryKey: ["log-stats"],
    queryFn: () => api.logs.stats(),
    refetchInterval: 5000,
  });

  const { data: logsData } = useQuery({
    queryKey: ["logs", filters.level, filters.logger, filters.source, sinceEpoch, filters.q, limit],
    queryFn: () =>
      api.logs.query({
        level: filters.level,
        logger: filters.logger,
        source: filters.source,
        since: sinceEpoch,
        q: filters.q || undefined,
        limit,
      }),
    refetchInterval: 3000,
    enabled: tab === "logs",
  });

  const { data: reqData } = useQuery({
    queryKey: ["log-requests", filters.source, sinceEpoch, limit],
    queryFn: () =>
      api.logs.requests({
        since: sinceEpoch,
        limit,
      }),
    refetchInterval: 3000,
    enabled: tab === "requests",
  });

  const { data: evtData } = useQuery({
    queryKey: ["log-events", sinceEpoch, limit],
    queryFn: () =>
      api.logs.events({
        since: sinceEpoch,
        limit,
      }),
    refetchInterval: 3000,
    enabled: tab === "events",
  });

  // --- Derived ---

  const totalLogs = useMemo(() => {
    if (!stats?.counts_by_level) return 0;
    return Object.values(stats.counts_by_level as Record<string, number>).reduce((a, b) => a + b, 0);
  }, [stats]);

  const errorCount = useMemo(() => {
    if (!stats?.counts_by_level) return 0;
    const cl = stats.counts_by_level as Record<string, number>;
    return (cl["ERROR"] ?? 0) + (cl["CRITICAL"] ?? 0);
  }, [stats]);

  const loggerOptions = useMemo(() => {
    if (!stats?.counts_by_logger) return [];
    return Object.keys(stats.counts_by_logger as Record<string, number>);
  }, [stats]);

  // --- Handlers ---

  const handleSearchChange = useCallback(
    (val: string) => {
      setLocalSearch(val);
      if (searchRef.current) clearTimeout(searchRef.current);
      searchRef.current = setTimeout(() => {
        setFilters({ q: val });
      }, 300);
    },
    [setFilters],
  );

  const setTimeRange = useCallback(
    (seconds: number | null) => {
      if (seconds == null) {
        setFilters({ since: null });
      } else {
        setFilters({ since: Date.now() / 1000 - seconds });
      }
    },
    [setFilters],
  );

  const handleClear = useCallback(() => {
    api.logs.clear().then(() => {
      queryClient.invalidateQueries({ queryKey: ["logs"] });
      queryClient.invalidateQueries({ queryKey: ["log-requests"] });
      queryClient.invalidateQueries({ queryKey: ["log-events"] });
      queryClient.invalidateQueries({ queryKey: ["log-stats"] });
    });
  }, [queryClient]);

  const handleLoadMore = useCallback(() => setLimit((prev) => prev + 200), []);

  // Reset limit when tab changes
  useEffect(() => {
    setLimit(200);
  }, [tab]);

  // Determine which time range is currently selected (approximate match)
  const activeTimeRange = useMemo(() => {
    if (filters.since == null) return null;
    const elapsed = Date.now() / 1000 - filters.since;
    for (const tr of TIME_RANGES) {
      if (tr.seconds != null && Math.abs(elapsed - tr.seconds) < 5) return tr.seconds;
    }
    return -1; // custom
  }, [filters.since]);

  return (
    <div className="p-6 space-y-4 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ScrollText className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-semibold">Logs</h1>
        </div>
        <div className="flex gap-2 items-center">
          <Badge variant="secondary">{totalLogs} logs</Badge>
          {errorCount > 0 && <Badge variant="destructive">{errorCount} errors</Badge>}
          <Badge variant="secondary">{stats?.total_requests ?? 0} reqs</Badge>
          <Button variant="ghost" size="icon" onClick={handleClear} title="Clear all logs">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        {(["logs", "requests", "events"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setFilters({ tab: t })}
            className={cn(
              "px-4 py-1.5 text-sm font-medium border-b-2 transition-colors capitalize",
              tab === t
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 items-center flex-wrap">
        {/* Level */}
        {tab === "logs" && (
          <select
            value={filters.level ?? ""}
            onChange={(e) => setFilters({ level: e.target.value || null })}
            className="h-8 rounded-md border border-border bg-transparent px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">All levels</option>
            {["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        )}

        {/* Logger */}
        {tab === "logs" && loggerOptions.length > 0 && (
          <select
            value={filters.logger ?? ""}
            onChange={(e) => setFilters({ logger: e.target.value || null })}
            className="h-8 rounded-md border border-border bg-transparent px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary max-w-[180px]"
          >
            <option value="">All loggers</option>
            {loggerOptions.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        )}

        {/* Source toggle */}
        {tab === "logs" && (
          <div className="flex gap-0.5">
            {([null, "backend", "frontend"] as const).map((s) => (
              <Button
                key={s ?? "all"}
                variant={filters.source === s ? "default" : "outline"}
                size="sm"
                className="text-xs h-8 px-2.5"
                onClick={() => setFilters({ source: s })}
              >
                {s === null ? "All" : s === "backend" ? "Backend" : "Frontend"}
              </Button>
            ))}
          </div>
        )}

        {/* Time range */}
        <select
          value={activeTimeRange === null ? "" : activeTimeRange === -1 ? "custom" : String(activeTimeRange)}
          onChange={(e) => {
            const v = e.target.value;
            setTimeRange(v === "" ? null : Number(v));
          }}
          className="h-8 rounded-md border border-border bg-transparent px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {TIME_RANGES.map((tr) => (
            <option key={tr.label} value={tr.seconds == null ? "" : String(tr.seconds)}>
              {tr.label}
            </option>
          ))}
        </select>

        {/* Search */}
        {tab === "logs" && (
          <Input
            placeholder="Search messages..."
            value={localSearch}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="h-8 text-xs w-48"
          />
        )}
      </div>

      {/* Content */}
      {tab === "logs" && (
        <LogsTable
          rows={(logsData?.rows ?? []) as LogEntry[]}
          total={logsData?.total ?? 0}
          onLoadMore={handleLoadMore}
        />
      )}
      {tab === "requests" && (
        <RequestsTable
          rows={(reqData?.rows ?? []) as RequestEntry[]}
          total={reqData?.total ?? 0}
          onLoadMore={handleLoadMore}
        />
      )}
      {tab === "events" && (
        <EventsTable
          rows={(evtData?.rows ?? []) as EventEntry[]}
          total={evtData?.total ?? 0}
          onLoadMore={handleLoadMore}
        />
      )}
    </div>
  );
}
