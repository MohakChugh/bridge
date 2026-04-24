import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, Badge } from "./ui";
import { formatRelativeTime } from "@/lib/utils";

export function RemindersList() {
  const { data } = useQuery({ queryKey: ["reminders"], queryFn: api.reminders.list });
  const items = data?.reminders ?? [];
  return (
    <ListPage title="Reminders" items={items} emptyText="No reminders set" render={(r) => (
      <Card>
        <CardContent className="py-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{r.message || r.text}</div>
            <div className="text-xs text-muted-foreground">{r.human || "scheduled"}</div>
          </div>
          <Badge variant="secondary">{r.status || "pending"}</Badge>
        </CardContent>
      </Card>
    )} />
  );
}

export function SchedulesList() {
  const { data } = useQuery({ queryKey: ["schedules"], queryFn: api.schedules.list });
  const items = data?.schedules ?? [];
  return (
    <ListPage title="Schedules" items={items} emptyText="No schedules created" render={(s) => (
      <Card>
        <CardContent className="py-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{s.prompt}</div>
            <div className="text-xs text-muted-foreground">{s.human} · {s.cron}</div>
          </div>
          <Badge variant={s.status === "active" ? "success" : "secondary"}>{s.status}</Badge>
        </CardContent>
      </Card>
    )} />
  );
}

export function WatchesList() {
  const { data } = useQuery({ queryKey: ["watches"], queryFn: api.watches.list });
  const items = data?.watches ?? [];
  return (
    <ListPage title="Watches" items={items} emptyText="No watches running" render={(w) => (
      <Card>
        <CardContent className="py-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{w.description || w.target}</div>
            <div className="text-xs text-muted-foreground">
              {w.check_type} · {w.interval_minutes}m
            </div>
          </div>
          <Badge variant={w.status === "active" ? "success" : "secondary"}>{w.status}</Badge>
        </CardContent>
      </Card>
    )} />
  );
}

function ListPage<T>({
  title,
  items,
  emptyText,
  render,
}: {
  title: string;
  items: T[];
  emptyText: string;
  render: (item: T) => React.ReactNode;
}) {
  return (
    <div className="p-6 max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {items.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">{emptyText}</CardContent>
        </Card>
      ) : (
        <div className="space-y-2">{items.map((item, i) => <div key={(item as any).id ?? i}>{render(item)}</div>)}</div>
      )}
    </div>
  );
}
