import { useEffect, useMemo, useState } from "react";
import { api, BankCalendarEvent } from "../api/client";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button } from "./ui";
import { BankEventCard } from "./BankEventCard";

type EventType = BankCalendarEvent["event_type"];

const TYPE_COLORS: Record<EventType, string> = {
  tls_rotation: "bg-red-500/20 text-red-400 border-red-500/40",
  pgp_key_rotation: "bg-orange-500/20 text-orange-400 border-orange-500/40",
  outage: "bg-purple-500/20 text-purple-400 border-purple-500/40",
  endpoint_migration: "bg-blue-500/20 text-blue-400 border-blue-500/40",
  noise: "bg-zinc-500/20 text-zinc-400 border-zinc-500/40",
};

const TYPE_LABELS: Record<EventType, string> = {
  tls_rotation: "TLS",
  pgp_key_rotation: "PGP",
  outage: "Outage",
  endpoint_migration: "Migration",
  noise: "Noise",
};

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}
function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}
function daysIn(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

export default function CalendarPage() {
  const [anchor, setAnchor] = useState<Date>(new Date());
  const [events, setEvents] = useState<BankCalendarEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<BankCalendarEvent | null>(null);
  const [typeFilter, setTypeFilter] = useState<Set<EventType>>(new Set());

  const [startStr, endStr] = useMemo(() => {
    return [isoDate(startOfMonth(anchor)), isoDate(endOfMonth(anchor))];
  }, [anchor]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const types = Array.from(typeFilter).join(",");
    api.calendar
      .list(startStr, endStr, types || undefined)
      .then((data) => {
        if (!cancelled) setEvents(data);
      })
      .catch(() => !cancelled && setEvents([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [startStr, endStr, typeFilter]);

  const byDay = useMemo(() => {
    const map: Record<string, BankCalendarEvent[]> = {};
    for (const ev of events) {
      const key = ev.start;
      if (!key) continue;
      if (!map[key]) map[key] = [];
      map[key].push(ev);
    }
    return map;
  }, [events]);

  const year = anchor.getFullYear();
  const month = anchor.getMonth();
  const firstDow = new Date(year, month, 1).getDay();
  const totalDays = daysIn(year, month);
  const cells: { date: string | null; day: number | null }[] = [];
  for (let i = 0; i < firstDow; i++) cells.push({ date: null, day: null });
  for (let d = 1; d <= totalDays; d++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ date: dateStr, day: d });
  }

  const toggleType = (t: EventType) => {
    const next = new Set(typeFilter);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setTypeFilter(next);
  };

  return (
    <div className="flex gap-4 h-full">
      <div className="flex-1 flex flex-col">
        <Card className="mb-4">
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Button onClick={() => setAnchor(new Date(year, month - 1, 1))}>←</Button>
              <CardTitle>
                {anchor.toLocaleString(undefined, { month: "long", year: "numeric" })}
              </CardTitle>
              <Button onClick={() => setAnchor(new Date(year, month + 1, 1))}>→</Button>
              <Button onClick={() => setAnchor(new Date())}>Today</Button>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {(Object.keys(TYPE_LABELS) as EventType[]).map((t) => (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={`px-2 py-1 rounded text-xs border ${
                    typeFilter.has(t) || typeFilter.size === 0
                      ? TYPE_COLORS[t]
                      : "bg-zinc-900 text-zinc-500 border-zinc-800"
                  }`}
                >
                  {TYPE_LABELS[t]}
                </button>
              ))}
              <a
                href={api.calendar.exportIcsUrl(startStr, endStr)}
                className="px-2 py-1 rounded text-xs border border-zinc-700 hover:bg-zinc-800"
              >
                Export .ics
              </a>
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-sm text-zinc-500">Loading…</div>
            ) : (
              <div className="grid grid-cols-7 gap-1">
                {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
                  <div key={d} className="text-xs text-zinc-500 text-center py-1">
                    {d}
                  </div>
                ))}
                {cells.map((c, i) =>
                  c.date ? (
                    <div
                      key={i}
                      className="min-h-24 border border-zinc-800 rounded p-1 flex flex-col gap-1"
                    >
                      <div className="text-xs text-zinc-500">{c.day}</div>
                      {(byDay[c.date] || []).map((ev) => (
                        <button
                          key={ev.id}
                          onClick={() => setSelected(ev)}
                          className={`text-xs text-left truncate px-1 py-0.5 rounded border ${
                            TYPE_COLORS[ev.event_type]
                          }`}
                          title={ev.title}
                        >
                          {TYPE_LABELS[ev.event_type]}: {ev.subject || ev.title}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div key={i} className="min-h-24" />
                  ),
                )}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Agenda — {events.length} events</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 text-sm">
              {events.length === 0 && (
                <div className="text-zinc-500">No bank events in this window.</div>
              )}
              {events.map((ev) => (
                <button
                  key={ev.id}
                  onClick={() => setSelected(ev)}
                  className="w-full text-left flex items-center gap-2 px-2 py-1 rounded hover:bg-zinc-900"
                >
                  <span className="text-zinc-500 w-24">{ev.start}</span>
                  <Badge className={TYPE_COLORS[ev.event_type]}>
                    {TYPE_LABELS[ev.event_type]}
                  </Badge>
                  <span className="truncate flex-1">{ev.subject}</span>
                  <span className="text-xs text-zinc-500">
                    {(ev.confidence * 100).toFixed(0)}%
                  </span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      {selected && (
        <BankEventCard event={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
