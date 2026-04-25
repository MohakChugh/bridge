import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

export function useEventStream() {
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let closed = false;

    function connect() {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/events`);
      wsRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
      };

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          const t = event.type;
          if (t === "ping") return;

          if (
            t === "session.created" ||
            t === "session.deleted" ||
            t === "session.updated" ||
            t === "session.busy" ||
            t === "session.completed" ||
            t === "session.failed" ||
            t === "session.cancelled"
          ) {
            qc.invalidateQueries({ queryKey: ["sessions"] });
            qc.invalidateQueries({ queryKey: ["dashboard"] });
            if (event.data?.id) {
              qc.invalidateQueries({ queryKey: ["session", event.data.id] });
            }
          }
          if (t === "message.appended") {
            const sid = event.data?.session_id;
            if (sid) qc.invalidateQueries({ queryKey: ["session", sid] });
          }
          if (t.startsWith("workflow.")) {
            qc.invalidateQueries({ queryKey: ["workflows"] });
            qc.invalidateQueries({ queryKey: ["workflow-runs"] });
            if (event.data?.run_id) {
              qc.invalidateQueries({ queryKey: ["workflow-run", event.data.run_id] });
            }
          }
        } catch {}
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (closed) return;
        retryRef.current++;
        const delay = Math.min(30_000, 500 * 2 ** retryRef.current);
        setTimeout(connect, delay);
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {}
      };
    }

    connect();

    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, [qc]);
}
