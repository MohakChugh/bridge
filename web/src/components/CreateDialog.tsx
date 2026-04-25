import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Textarea } from "./ui";
import { api } from "@/api/client";
import { X, Sparkles, Plus } from "lucide-react";

interface BaseProps {
  open: boolean;
  onClose: () => void;
}

// ---- Reminder Dialog ----
export function ReminderDialog({ open, onClose }: BaseProps) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<{ iso: string; human: string; message: string } | null>(null);
  const qc = useQueryClient();

  const parseMut = useMutation({
    mutationFn: (t: string) => api.reminders.parse(t),
    onSuccess: (data) => setParsed(data),
  });

  const createMut = useMutation({
    mutationFn: () =>
      api.reminders.create({
        message: parsed!.message,
        fire_at_epoch: new Date(parsed!.iso).getTime() / 1000,
        human: parsed!.human,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reminders"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      reset();
      onClose();
    },
  });

  function reset() {
    setText("");
    setParsed(null);
    parseMut.reset();
    createMut.reset();
  }

  if (!open) return null;

  return (
    <DialogShell title="New reminder" onClose={() => { reset(); onClose(); }}>
      {!parsed ? (
        <>
          <label className="text-xs font-medium text-muted-foreground block mb-1.5">Natural language</label>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="tomorrow 9am check deploy&#10;in 30 minutes call John&#10;friday 5pm submit timesheet"
            rows={3}
            autoFocus
          />
          <div className="flex justify-end mt-4">
            <Button onClick={() => parseMut.mutate(text)} disabled={!text.trim() || parseMut.isPending}>
              <Sparkles className="w-3.5 h-3.5" />
              {parseMut.isPending ? "Parsing…" : "Parse"}
            </Button>
          </div>
          {parseMut.isError && (
            <div className="text-xs text-destructive mt-2">Could not parse — try different phrasing</div>
          )}
        </>
      ) : (
        <>
          <div className="bg-accent/50 border border-border rounded-md p-3 space-y-2">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">When</div>
              <div className="text-sm font-medium">{parsed.human}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Message</div>
              <div className="text-sm">{parsed.message}</div>
            </div>
          </div>
          <div className="flex justify-between mt-4 gap-2">
            <Button variant="ghost" size="sm" onClick={() => setParsed(null)}>
              ← Edit
            </Button>
            <Button onClick={() => createMut.mutate()} disabled={createMut.isPending}>
              <Plus className="w-3.5 h-3.5" />
              {createMut.isPending ? "Creating…" : "Create reminder"}
            </Button>
          </div>
        </>
      )}
    </DialogShell>
  );
}

// ---- Schedule Dialog ----
export function ScheduleDialog({ open, onClose }: BaseProps) {
  const [scheduleText, setScheduleText] = useState("");
  const [prompt, setPrompt] = useState("");
  const [parsed, setParsed] = useState<{ cron: string; human: string } | null>(null);
  const qc = useQueryClient();

  const parseMut = useMutation({
    mutationFn: (t: string) => api.schedules.parse(t),
    onSuccess: (data) => setParsed(data),
  });

  const createMut = useMutation({
    mutationFn: () =>
      api.schedules.create({
        cron: parsed!.cron,
        human: parsed!.human,
        prompt,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      reset();
      onClose();
    },
  });

  function reset() {
    setScheduleText("");
    setPrompt("");
    setParsed(null);
    parseMut.reset();
    createMut.reset();
  }

  if (!open) return null;

  return (
    <DialogShell title="New schedule" onClose={() => { reset(); onClose(); }}>
      {!parsed ? (
        <>
          <label className="text-xs font-medium text-muted-foreground block mb-1.5">Schedule (natural language)</label>
          <Input
            value={scheduleText}
            onChange={(e) => setScheduleText(e.target.value)}
            placeholder="every morning at 9am"
            autoFocus
          />
          <label className="text-xs font-medium text-muted-foreground block mb-1.5 mt-4">Prompt to run</label>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="check pipeline status for centralis"
            rows={3}
          />
          <div className="flex justify-end mt-4">
            <Button
              onClick={() => parseMut.mutate(scheduleText)}
              disabled={!scheduleText.trim() || !prompt.trim() || parseMut.isPending}
            >
              <Sparkles className="w-3.5 h-3.5" />
              {parseMut.isPending ? "Parsing…" : "Parse"}
            </Button>
          </div>
          {parseMut.isError && <div className="text-xs text-destructive mt-2">Parse failed</div>}
        </>
      ) : (
        <>
          <div className="bg-accent/50 border border-border rounded-md p-3 space-y-2">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Schedule</div>
              <div className="text-sm font-medium">{parsed.human}</div>
              <div className="text-xs text-muted-foreground font-mono">{parsed.cron}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Prompt</div>
              <div className="text-sm">{prompt}</div>
            </div>
          </div>
          <div className="flex justify-between mt-4 gap-2">
            <Button variant="ghost" size="sm" onClick={() => setParsed(null)}>← Edit</Button>
            <Button onClick={() => createMut.mutate()} disabled={createMut.isPending}>
              <Plus className="w-3.5 h-3.5" />
              {createMut.isPending ? "Creating…" : "Create schedule"}
            </Button>
          </div>
        </>
      )}
    </DialogShell>
  );
}

// ---- Watch Dialog ----
export function WatchDialog({ open, onClose }: BaseProps) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<any | null>(null);
  const qc = useQueryClient();

  const parseMut = useMutation({
    mutationFn: (t: string) => api.watches.parse(t),
    onSuccess: (data) => setParsed(data),
  });

  const createMut = useMutation({
    mutationFn: () => api.watches.create(parsed!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watches"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      reset();
      onClose();
    },
  });

  function reset() {
    setText("");
    setParsed(null);
    parseMut.reset();
    createMut.reset();
  }

  if (!open) return null;

  return (
    <DialogShell title="New watch" onClose={() => { reset(); onClose(); }}>
      {!parsed ? (
        <>
          <label className="text-xs font-medium text-muted-foreground block mb-1.5">What to watch</label>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="new high sev tickets on MyTeam-Resolver&#10;pipeline MyServicePipeline&#10;all my pipelines"
            rows={3}
            autoFocus
          />
          <div className="flex justify-end mt-4">
            <Button onClick={() => parseMut.mutate(text)} disabled={!text.trim() || parseMut.isPending}>
              <Sparkles className="w-3.5 h-3.5" />
              {parseMut.isPending ? "Parsing…" : "Parse"}
            </Button>
          </div>
          {parseMut.isError && <div className="text-xs text-destructive mt-2">Parse failed</div>}
        </>
      ) : (
        <>
          <div className="bg-accent/50 border border-border rounded-md p-3 space-y-2">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Type</div>
              <div className="text-sm font-medium">{parsed.check_type}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Target</div>
              <div className="text-sm">{parsed.target || parsed.description}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Interval</div>
              <div className="text-sm">{parsed.interval_minutes || 5} minutes</div>
            </div>
          </div>
          <div className="flex justify-between mt-4 gap-2">
            <Button variant="ghost" size="sm" onClick={() => setParsed(null)}>← Edit</Button>
            <Button onClick={() => createMut.mutate()} disabled={createMut.isPending}>
              <Plus className="w-3.5 h-3.5" />
              {createMut.isPending ? "Creating…" : "Start watch"}
            </Button>
          </div>
        </>
      )}
    </DialogShell>
  );
}

function DialogShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md p-5 relative">
        <button onClick={onClose} className="absolute right-3 top-3 text-muted-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>
        <h2 className="font-semibold mb-4">{title}</h2>
        {children}
      </div>
    </div>
  );
}
