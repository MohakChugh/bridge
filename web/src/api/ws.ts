import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useIngestionStore } from "@/stores/ingestionStore";
import { useLogStore } from "@/stores/logStore";
import { useDocStore } from "@/stores/docStore";
import { useAgentStore } from "@/stores/agentStore";
import { useReviewStore } from "@/stores/reviewStore";

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
        qc.invalidateQueries({ queryKey: ["dashboard"] });
        qc.invalidateQueries({ queryKey: ["operations"] });
        qc.invalidateQueries({ queryKey: ["sessions"] });
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
            qc.invalidateQueries({ queryKey: ["operations"] });
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
            qc.invalidateQueries({ queryKey: ["operations"] });
            if (event.data?.run_id) {
              qc.invalidateQueries({ queryKey: ["workflow-run", event.data.run_id] });
            }
          }
          if (t.startsWith("agent.")) {
            useAgentStore.getState().addLiveEvent({
              id: crypto.randomUUID?.() || String(Date.now()),
              type: t,
              task_id: event.data?.task_id || "",
              data: event.data || {},
              timestamp: event.timestamp || Date.now() / 1000,
            });
            qc.invalidateQueries({ queryKey: ["agent-tasks"] });
            if (event.data?.task_id) {
              qc.invalidateQueries({ queryKey: ["agent-task", event.data.task_id] });
            }
          }
          if (t === "ingestion.phase" || t.startsWith("document.")) {
            useIngestionStore.getState().handleEvent(t, event.data);
            qc.invalidateQueries({ queryKey: ["kb-documents"] });
            qc.invalidateQueries({ queryKey: ["memory-stats"] });
          }
          if (t === "log.entry") {
            useLogStore.getState().addLiveEntry(event.data);
          }
          if (t === "log.batch") {
            qc.invalidateQueries({ queryKey: ["logs"] });
            qc.invalidateQueries({ queryKey: ["log-stats"] });
          }
          if (t.startsWith("doc.")) {
            qc.invalidateQueries({ queryKey: ["docs"] });
            qc.invalidateQueries({ queryKey: ["doc-tree"] });
            const docId = event.data?.doc_id || event.data?.id;
            if (docId) qc.invalidateQueries({ queryKey: ["doc", docId] });
          }
          if (t === "cr.build.done") {
            const d = event.data || {};
            useReviewStore.getState().setReview({
              buildStatus: d.success ? "pass" : "fail",
              buildErrors: d.errors || d.stderr || "",
            });
          }
          if (t === "doc.generation.started") {
            useDocStore.getState().startGeneration(event.data.generation_id, event.data.doc_id, event.data.mode === "edit_selection" ? "edit_selection" : "generate");
          }
          if (t === "doc.generation.chunk") {
            useDocStore.getState().appendChunk(event.data.chunk);
          }
          if (t === "doc.generation.completed") {
            useDocStore.getState().completeGeneration();
          }
          if (t === "doc.generation.failed") {
            useDocStore.getState().failGeneration(event.data.error);
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
