import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Session } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";
import { Card, CardContent, Badge, Button } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { History, Play, Trash2, MessageSquare } from "lucide-react";

export function SessionHistory() {
  const qc = useQueryClient();
  const { setView, setActiveSessionId } = useSessionStore();

  const { data, isLoading } = useQuery({
    queryKey: ["sessions-archived"],
    queryFn: api.sessions.archived,
  });
  const archived = data?.sessions ?? [];

  const resumeMut = useMutation({
    mutationFn: (id: string) => api.sessions.resume(id),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["sessions-archived"] });
      setActiveSessionId(session.id);
      setView("chat");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.sessions.deleteArchived(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions-archived"] }),
  });

  return (
    <div className="p-6 max-w-4xl space-y-4 overflow-y-auto h-full">
      <div className="flex items-center gap-3">
        <History className="w-5 h-5 text-muted-foreground" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Past Sessions</h1>
          <p className="text-xs text-muted-foreground mt-0.5">{archived.length} sessions saved</p>
        </div>
      </div>

      {isLoading ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Loading...</CardContent></Card>
      ) : archived.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <History className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <div className="text-sm font-medium">No past sessions</div>
            <div className="text-xs text-muted-foreground mt-1">Sessions are saved automatically after each conversation</div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {archived.map((s: any) => {
            const lastMsg = s.message_history?.[s.message_history.length - 1];
            return (
              <Card key={s.id} className="hover:border-primary/30 transition-colors">
                <CardContent className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">{s.title}</span>
                        <Badge variant="secondary" className="text-[9px] shrink-0">{s.tool}</Badge>
                        <Badge variant="outline" className="text-[9px] shrink-0">
                          <MessageSquare className="w-2.5 h-2.5 mr-0.5" />
                          {s.message_count || s.message_history?.length || 0}
                        </Badge>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {s.cwd} · {formatRelativeTime(s.updated_at || s.created_at)}
                      </div>
                      {lastMsg && (
                        <div className="text-xs text-foreground/60 mt-1.5 truncate">
                          <span className="text-muted-foreground">{lastMsg.role === "user" ? "You" : "AI"}:</span>{" "}
                          {lastMsg.text?.slice(0, 120)}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => resumeMut.mutate(s.id)}
                        disabled={resumeMut.isPending}
                      >
                        <Play className="w-3 h-3" />
                        Resume
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => deleteMut.mutate(s.id)}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
