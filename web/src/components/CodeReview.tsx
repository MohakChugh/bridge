import React, { useState, useRef, useEffect, useCallback, useMemo } from "react";
import {
  GitPullRequest, FileCode, MessageSquare, Send, Loader2, ChevronDown,
  ChevronRight, Plus, Minus, Eye, EyeOff, Columns, AlignJustify,
  AlertCircle, AlertTriangle, Info, Bot, User, Sparkles, Search,
  X, ArrowUp, ArrowDown, CheckCircle2, XCircle, Hammer, FolderOpen, Folder,
} from "lucide-react";
import { Button, Badge, Card, CardContent } from "@/components/ui";
import {
  useReviewStore,
  type DiffFile,
  type ReviewComment,
  type AnalysisSession,
} from "@/stores/reviewStore";
import { useSessionStore } from "@/stores/sessionStore";
import { api } from "@/api/client";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import hljs from "highlight.js/lib/core";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import java from "highlight.js/lib/languages/java";
import xml from "highlight.js/lib/languages/xml";
import css from "highlight.js/lib/languages/css";
import json_ from "highlight.js/lib/languages/json";
import bash from "highlight.js/lib/languages/bash";
import yaml from "highlight.js/lib/languages/yaml";
import sql from "highlight.js/lib/languages/sql";
import go from "highlight.js/lib/languages/go";
import kotlin from "highlight.js/lib/languages/kotlin";
import mdLang from "highlight.js/lib/languages/markdown";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("tsx", typescript);
hljs.registerLanguage("jsx", javascript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("java", java);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("css", css);
hljs.registerLanguage("json", json_);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("go", go);
hljs.registerLanguage("kotlin", kotlin);
hljs.registerLanguage("markdown", mdLang);

// highlight.js output is safe — it HTML-escapes input before adding span tags.
// The dangerouslySetInnerHTML usage below is intentional and safe for this reason.
function highlightCode(code: string, lang: string): string {
  try {
    if (hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value;
  } catch {}
  return code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const FILE_COLORS: Record<string, string> = {
  python: "text-yellow-400", typescript: "text-blue-400", javascript: "text-yellow-300",
  tsx: "text-blue-300", jsx: "text-yellow-200", java: "text-orange-400",
  kotlin: "text-purple-400", go: "text-cyan-400", html: "text-red-400",
  css: "text-blue-500", json: "text-green-400", yaml: "text-pink-400",
  bash: "text-green-300", sql: "text-blue-200", markdown: "text-gray-400",
};

const SEV = {
  error:   { icon: AlertCircle,   color: "text-red-400",    bg: "bg-red-500/10 border-red-500/30" },
  warning: { icon: AlertTriangle, color: "text-yellow-400", bg: "bg-yellow-500/10 border-yellow-500/30" },
  info:    { icon: Info,          color: "text-blue-400",   bg: "bg-blue-500/10 border-blue-500/30" },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Poll a session until it resolves. Returns {status, output, error}. */
function useSessionPoller(sessionId: string | null, interval = 2000) {
  return useQuery({
    queryKey: ["cr-session", sessionId],
    queryFn: () => api.cr.sessionStatus(sessionId!),
    enabled: !!sessionId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "busy" || s === "idle") return interval;
      return false;
    },
    retry: 2,
  });
}

// ---------------------------------------------------------------------------
// LoadCRDialog
// ---------------------------------------------------------------------------

function LoadCRDialog({ onLoad }: { onLoad: (crId: string, tool: string) => void }) {
  const [crId, setCrId] = useState("");
  const [tool, setTool] = useState("");
  const { data: toolsData } = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const tools = toolsData?.tools || [];
  const active = toolsData?.active || "wasabi";

  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 max-w-lg mx-auto">
      <div className="text-center space-y-3">
        <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto">
          <GitPullRequest className="w-8 h-8 text-primary" />
        </div>
        <h1 className="text-2xl font-bold">Code Review</h1>
        <p className="text-muted-foreground text-sm">Enter CR ID to pull, view diff, and review with AI</p>
      </div>
      <div className="w-full space-y-4">
        <div>
          <label className="text-xs text-muted-foreground mb-1.5 block">Code Review ID</label>
          <input value={crId} onChange={(e) => setCrId(e.target.value)}
            placeholder="CR-123456789"
            className="w-full rounded-lg border border-border bg-background px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            onKeyDown={(e) => e.key === "Enter" && crId.trim() && onLoad(crId.trim(), tool || active)}
            autoFocus
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1.5 block">AI Review Tool (for questions later)</label>
          <select value={tool || active} onChange={(e) => setTool(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary">
            {tools.map((t: string) => (
              <option key={t} value={t}>{t}{t === active ? " (default)" : ""}</option>
            ))}
          </select>
        </div>
        <Button className="w-full py-3" disabled={!crId.trim()} onClick={() => onLoad(crId.trim(), tool || active)}>
          <GitPullRequest className="w-4 h-4 mr-2" /> Review
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AnalysisStatusBar
// ---------------------------------------------------------------------------

function AnalysisStatusBar() {
  const { analysisSessions, buildStatus } = useReviewStore();

  const items: Array<{ key: string; label: string; status: AnalysisSession["status"] | null }> = [
    { key: "auto_review", label: "Auto Review", status: analysisSessions.auto_review?.status ?? null },
    { key: "fetch_comments", label: "CR Comments", status: analysisSessions.fetch_comments?.status ?? null },
    { key: "build_check", label: "Build", status: buildStatus === "pass" ? "completed" : buildStatus === "fail" ? "failed" : analysisSessions.build_check?.status ?? null },
  ];

  const hasAny = items.some((i) => i.status !== null);
  if (!hasAny) return null;

  return (
    <div className="px-4 py-2 border-b border-border bg-accent/20 flex items-center gap-4">
      {items.map((item) => {
        if (item.status === null) return null;
        const busy = item.status === "busy" || item.status === "idle";
        const done = item.status === "completed";
        const fail = item.status === "failed";
        return (
          <div key={item.key} className="flex items-center gap-1.5 text-xs" title={
            fail ? (analysisSessions[item.key]?.error || "Failed — check logs") : undefined
          }>
            {busy && <Loader2 className="w-3 h-3 animate-spin text-primary" />}
            {done && <CheckCircle2 className="w-3 h-3 text-green-400" />}
            {fail && <XCircle className="w-3 h-3 text-red-400" />}
            <span className={busy ? "text-muted-foreground" : done ? "text-green-400" : "text-red-400"}>
              {item.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FileTree — directory tree with collapsible folders
// ---------------------------------------------------------------------------

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  file?: DiffFile;
  children: TreeNode[];
  additions: number;
  deletions: number;
}

function buildTree(files: DiffFile[], packages?: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [], additions: 0, deletions: 0 };

  for (const f of files) {
    const parts = f.path.split("/");
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      const childPath = parts.slice(0, i + 1).join("/");

      let child = current.children.find((c) => c.name === part);
      if (!child) {
        child = {
          name: part, path: childPath, isDir: !isLast,
          file: isLast ? f : undefined, children: [], additions: 0, deletions: 0,
        };
        current.children.push(child);
      }
      if (isLast) {
        child.file = f;
        child.isDir = false;
      }
      current = child;
    }
  }

  // Propagate counts up
  function sumCounts(node: TreeNode): { a: number; d: number } {
    if (!node.isDir && node.file) {
      node.additions = node.file.additions;
      node.deletions = node.file.deletions;
      return { a: node.additions, d: node.deletions };
    }
    let a = 0, d = 0;
    for (const c of node.children) {
      const s = sumCounts(c);
      a += s.a; d += s.d;
    }
    node.additions = a; node.deletions = d;
    return { a, d };
  }
  sumCounts(root);

  // Collapse single-child directories (but never collapse package-level roots)
  function collapse(node: TreeNode, isPackageRoot = false): TreeNode {
    if (!isPackageRoot && node.isDir && node.children.length === 1 && node.children[0].isDir) {
      const child = node.children[0];
      return collapse({
        ...child,
        name: node.name ? `${node.name}/${child.name}` : child.name,
        path: child.path,
      });
    }
    return { ...node, children: node.children.map((c) => collapse(c)) };
  }

  // Don't collapse package-level roots (first-level dirs that match package names)
  const pkgSet = new Set(packages || []);
  const collapsed = { ...root, children: root.children.map((c) => collapse(c, pkgSet.has(c.name))) };
  // Sort: dirs first, then files alphabetically
  function sortTree(nodes: TreeNode[]): TreeNode[] {
    return nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    }).map((n) => ({ ...n, children: sortTree(n.children) }));
  }

  return sortTree(collapsed.children);
}

function FileTree({ files, selectedFile, onSelect, comments, packages }: {
  files: DiffFile[]; selectedFile: string | null; onSelect: (p: string) => void; comments: ReviewComment[]; packages?: string[];
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const tree = useMemo(() => buildTree(files, packages), [files, packages]);

  // Auto-expand all on first render
  useEffect(() => {
    const dirs = new Set<string>();
    function collect(nodes: TreeNode[]) {
      nodes.forEach((n) => { if (n.isDir) { dirs.add(n.path); collect(n.children); } });
    }
    collect(tree);
    setExpanded(dirs);
  }, [tree]);

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    comments.forEach((c) => { m[c.file] = (m[c.file] || 0) + 1; });
    return m;
  }, [comments]);

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  };

  function renderNode(node: TreeNode, depth: number) {
    if (node.isDir) {
      const isOpen = expanded.has(node.path);
      return (
        <div key={node.path}>
          <button onClick={() => toggle(node.path)}
            className="w-full text-left flex items-center gap-1.5 py-1 hover:bg-accent/50 transition-colors text-xs"
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
          >
            {isOpen ? <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" /> : <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />}
            <Folder className={`w-3.5 h-3.5 shrink-0 ${depth === 0 ? "text-primary" : "text-primary/50"}`} />
            <span className={`truncate ${depth === 0 ? "font-semibold text-foreground" : "text-muted-foreground"}`}>{node.name}</span>
            <span className="ml-auto flex items-center gap-1 shrink-0 pr-2">
              <span className="text-green-400/60 text-[10px]">+{node.additions}</span>
              <span className="text-red-400/60 text-[10px]">-{node.deletions}</span>
            </span>
          </button>
          {isOpen && node.children.map((c) => renderNode(c, depth + 1))}
        </div>
      );
    }

    const f = node.file!;
    const sel = f.path === selectedFile;
    const commentCount = counts[f.path] || 0;

    return (
      <button key={f.path} onClick={() => onSelect(f.path)}
        className={`w-full text-left flex items-center gap-1.5 py-1.5 transition-colors text-xs ${
          sel ? "bg-primary/10 border-l-2 border-primary" : "border-l-2 border-transparent hover:bg-accent/50"}`}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
      >
        <FileCode className={`w-3.5 h-3.5 shrink-0 ${FILE_COLORS[f.language] || "text-muted-foreground"}`} />
        <span className={`truncate ${sel ? "text-foreground font-medium" : ""}`}>{node.name}</span>
        <span className="ml-auto flex items-center gap-1 shrink-0 pr-2">
          {f.status === "added" && <Badge variant="success" className="text-[8px] px-1 py-0 leading-none">N</Badge>}
          {f.status === "deleted" && <Badge variant="destructive" className="text-[8px] px-1 py-0 leading-none">D</Badge>}
          <span className="text-green-400 text-[10px]">+{f.additions}</span>
          <span className="text-red-400 text-[10px]">-{f.deletions}</span>
          {commentCount > 0 && (
            <span className="w-3.5 h-3.5 rounded-full bg-primary text-[8px] flex items-center justify-center text-primary-foreground">{commentCount}</span>
          )}
        </span>
      </button>
    );
  }

  return (
    <div className="w-64 border-r border-border overflow-y-auto shrink-0">
      <div className="p-3 border-b border-border">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Files ({files.length})
        </span>
      </div>
      <div className="py-1">
        {tree.map((n) => renderNode(n, 0))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CommentBubble
// ---------------------------------------------------------------------------

function CommentBubble({ comment }: { comment: ReviewComment }) {
  const [replyText, setReplyText] = useState("");
  const [replying, setReplying] = useState(false);
  const store = useReviewStore();

  // Poll the per-comment session if it exists and is still in-flight
  const sessionQuery = useSessionPoller(comment.sessionId ?? null);
  const sessionBusy = comment.sessionId ? (sessionQuery.data?.status === "busy" || sessionQuery.data?.status === "idle") : false;

  // When the per-comment session completes, add its output as an AI reply
  useEffect(() => {
    if (!comment.sessionId || !sessionQuery.data) return;
    const { status, output } = sessionQuery.data;
    if (status !== "completed" && status !== "failed") return;
    // Dedup by sessionId — more reliable than text comparison
    const alreadyReplied = comment.replies.some((r: any) => r.sessionId === comment.sessionId);
    if (!alreadyReplied && output) {
      store.addReply(comment.id, { author: "ai", text: output, sessionId: comment.sessionId });
    }
  }, [sessionQuery.data?.status, comment.sessionId]);

  const handleReply = async () => {
    if (!replyText.trim()) return;
    const { crId, workspace, packages, tool } = store;
    if (!crId || !workspace) return;
    store.addReply(comment.id, { author: "user", text: replyText });
    try {
      const res = await api.cr.comment({
        cr_id: crId, workspace, packages, tool: tool || undefined,
        file: comment.file, line: comment.line, content: comment.content, question: replyText,
      });
      store.updateCommentSession(comment.id, res.session_id);
    } catch {}
    setReplyText("");
    setReplying(false);
  };

  const sev = comment.severity ? SEV[comment.severity] : null;
  const SevIcon = sev?.icon || MessageSquare;

  return (
    <div className={`mx-14 my-1.5 rounded-lg border ${sev?.bg || "bg-accent/50 border-border"} p-3`}>
      <div className="flex items-start gap-2">
        <SevIcon className={`w-4 h-4 mt-0.5 shrink-0 ${sev?.color || "text-muted-foreground"}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {comment.author === "auto" && <Badge variant="outline" className="text-[10px] px-1.5 py-0 gap-0.5"><Bot className="w-2.5 h-2.5" /> Auto</Badge>}
            {comment.author === "sde" && <Badge className="text-[10px] px-1.5 py-0 gap-0.5 bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"><User className="w-2.5 h-2.5" /> {comment.authorName || "SDE"}</Badge>}
            {comment.author === "user" && <Badge variant="secondary" className="text-[10px] px-1.5 py-0 gap-0.5"><User className="w-2.5 h-2.5" /> You</Badge>}
            {comment.severity && (
              <Badge variant={comment.severity === "error" ? "destructive" : comment.severity === "warning" ? "warning" : "outline"} className="text-[10px] px-1.5 py-0">
                {comment.severity}
              </Badge>
            )}
            {sessionBusy && <Loader2 className="w-3 h-3 animate-spin text-primary" />}
          </div>
          <div className="text-sm"><ReactMarkdown className="chat-markdown" remarkPlugins={[remarkGfm]}>{comment.content}</ReactMarkdown></div>
          {comment.suggestion && (
            <div className="mt-2 p-2 rounded bg-background/50 border border-border/50">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Suggestion</span>
              <pre className="text-xs font-mono mt-1 whitespace-pre-wrap text-green-300">{comment.suggestion}</pre>
            </div>
          )}
          {comment.replies.map((r, i) => (
            <div key={i} className="mt-2 pt-2 border-t border-border/30 flex items-start gap-2">
              {r.author === "ai" ? <Bot className="w-3 h-3 mt-1 text-primary" /> : <User className="w-3 h-3 mt-1" />}
              <div className="text-sm flex-1"><ReactMarkdown className="chat-markdown" remarkPlugins={[remarkGfm]}>{r.text}</ReactMarkdown></div>
            </div>
          ))}
          <div className="mt-2">
            {replying ? (
              <div className="flex gap-2">
                <input value={replyText} onChange={(e) => setReplyText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleReply()}
                  placeholder="Reply..." autoFocus
                  className="flex-1 rounded border border-border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary" />
                <Button size="sm" className="h-6 text-[10px] px-2" onClick={handleReply}>Send</Button>
                <Button size="sm" variant="ghost" className="h-6 text-[10px] px-2" onClick={() => setReplying(false)}>Cancel</Button>
              </div>
            ) : (
              <Button size="sm" variant="ghost" className="h-5 text-[10px] px-1.5 opacity-60 hover:opacity-100" onClick={() => setReplying(true)}>Reply</Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DiffLine
// ---------------------------------------------------------------------------

function DiffLine({ line, language, showWs, comments, onComment, file }: {
  line: { type: string; content: string; old_num: number | null; new_num: number | null };
  language: string; showWs: boolean; comments: ReviewComment[];
  onComment: (ln: number, f: string) => void; file: string;
}) {
  const ln = line.new_num || line.old_num || 0;
  const lineComments = comments.filter((c) => c.file === file && c.line === ln);
  let content = line.content;
  if (showWs) content = content.replace(/ /g, "·").replace(/\t/g, "→   ");
  // highlight.js escapes all HTML in input — safe to render via dangerouslySetInnerHTML
  const html = highlightCode(content, language);

  const bg = line.type === "add" ? "bg-green-500/8 hover:bg-green-500/15"
    : line.type === "del" ? "bg-red-500/8 hover:bg-red-500/15" : "hover:bg-accent/50";
  const gutter = line.type === "add" ? "bg-green-500/15 text-green-400"
    : line.type === "del" ? "bg-red-500/15 text-red-400" : "text-muted-foreground/50";

  return (
    <>
      <tr className={`${bg} group transition-colors text-[13px] leading-5`}>
        <td className={`${gutter} w-12 text-right pr-2 pl-1 select-none font-mono text-[11px] align-top`}>{line.old_num || ""}</td>
        <td className={`${gutter} w-12 text-right pr-2 select-none font-mono text-[11px] align-top`}>{line.new_num || ""}</td>
        <td className="w-5 text-center select-none align-top">
          {line.type === "add" && <span className="text-green-400 text-xs font-bold">+</span>}
          {line.type === "del" && <span className="text-red-400 text-xs font-bold">&minus;</span>}
        </td>
        <td className="font-mono whitespace-pre pr-4 align-top relative">
          {/* highlight.js escapes all HTML in input — safe to render */}
          <span dangerouslySetInnerHTML={{ __html: html }} />
          <button onClick={() => onComment(ln, file)}
            className="absolute right-2 top-0.5 opacity-0 group-hover:opacity-100 transition-opacity" title="Add comment">
            <Plus className="w-3.5 h-3.5 text-primary" />
          </button>
        </td>
      </tr>
      {lineComments.map((c) => (
        <tr key={c.id}><td colSpan={4} className="px-0"><CommentBubble comment={c} /></td></tr>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// InlineInput
// ---------------------------------------------------------------------------

function InlineInput({ file, line, onSubmit, onCancel }: {
  file: string; line: number; onSubmit: (t: string) => void; onCancel: () => void;
}) {
  const [text, setText] = useState("");
  return (
    <tr><td colSpan={4} className="px-0">
      <div className="mx-14 my-1.5 rounded-lg border border-primary/30 bg-primary/5 p-3">
        <div className="text-[10px] text-muted-foreground mb-1.5">Comment on line {line}</div>
        <textarea value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Ask a question or add a comment..."
          className="w-full rounded border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary min-h-[60px] resize-none" autoFocus />
        <div className="flex gap-2 mt-2 justify-end">
          <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button size="sm" disabled={!text.trim()} onClick={() => { onSubmit(text); setText(""); }}>
            <Send className="w-3 h-3 mr-1" /> Comment
          </Button>
        </div>
      </div>
    </td></tr>
  );
}

// ---------------------------------------------------------------------------
// ReviewChat — per-question sessions
// ---------------------------------------------------------------------------

function ReviewChat() {
  const store = useReviewStore();
  const [input, setInput] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Track the latest chat session (the most recent question's session)
  const latestChatSid = store.chatSessions.length > 0 ? store.chatSessions[store.chatSessions.length - 1] : null;
  const latestSession = useSessionPoller(latestChatSid);
  const busy = latestChatSid ? (latestSession.data?.status === "busy" || latestSession.data?.status === "idle") : false;

  // When a chat session completes, add the output as an assistant message
  useEffect(() => {
    if (!latestChatSid || !latestSession.data) return;
    const { status, output } = latestSession.data;
    if (status !== "completed" && status !== "failed") return;
    const msgs = store.chatMessages;
    const lastMsg = msgs.length > 0 ? msgs[msgs.length - 1] : null;
    // Avoid duplicate — only add if the last message is not already this output
    if (output && (!lastMsg || lastMsg.role !== "assistant" || lastMsg.text !== output)) {
      store.addChatMessage({ role: "assistant", text: output, sessionId: latestChatSid });
    }
  }, [latestSession.data?.status, latestChatSid]);

  useEffect(() => {
    scrollRef.current && (scrollRef.current.scrollTop = scrollRef.current.scrollHeight);
  }, [store.chatMessages.length, busy]);

  const send = useCallback(async () => {
    if (!input.trim()) return;
    const { crId, workspace, packages, tool } = store;
    if (!crId || !workspace) return;
    store.addChatMessage({ role: "user", text: input });
    try {
      const res = await api.cr.chat({
        cr_id: crId, workspace, packages, tool: tool || undefined, question: input,
      });
      store.setReview({ chatSessions: [...store.chatSessions, res.session_id] });
    } catch {}
    setInput("");
  }, [input, store.crId, store.workspace, store.packages, store.tool, store.chatSessions]);

  if (collapsed) {
    return (
      <div className="w-10 border-l border-border flex flex-col items-center shrink-0 py-3">
        <button onClick={() => setCollapsed(false)} title="Open Review Chat"
          className="p-2 rounded-md hover:bg-accent transition-colors">
          <MessageSquare className="w-4 h-4 text-primary" />
        </button>
        {busy && <Loader2 className="w-3 h-3 animate-spin text-primary mt-2" />}
        {store.chatMessages.length > 0 && (
          <span className="w-4 h-4 rounded-full bg-primary text-[9px] flex items-center justify-center text-primary-foreground mt-2">
            {store.chatMessages.length}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="w-80 border-l border-border flex flex-col shrink-0">
      <div className="p-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-primary" />
          <span className="text-xs font-semibold">Review Chat</span>
        </div>
        <div className="flex items-center gap-1.5">
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />}
          <button onClick={() => setCollapsed(true)} title="Collapse chat"
            className="p-0.5 rounded hover:bg-accent transition-colors">
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
          </button>
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
        {!store.chatMessages.length && (
          <div className="text-center text-muted-foreground text-xs mt-8 space-y-2">
            <Bot className="w-8 h-8 mx-auto opacity-30" />
            <p>Ask questions about this CR</p>
            <p className="text-[10px]">Full repo context available</p>
          </div>
        )}
        {store.chatMessages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`rounded-xl px-3 py-2 ${
              m.role === "user" ? "max-w-[85%] bg-primary text-primary-foreground text-xs" : "w-full bg-accent text-xs"}`}>
              {m.role === "assistant" ? (
                <ReactMarkdown className="chat-markdown" remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
              ) : <div className="whitespace-pre-wrap">{m.text}</div>}
            </div>
          </div>
        ))}
        {busy && <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="w-3 h-3 animate-spin" /> Thinking...</div>}
      </div>
      <div className="p-3 border-t border-border">
        <div className="flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Ask about this CR..." disabled={busy}
            className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50" />
          <Button size="icon" className="h-8 w-8" disabled={busy || !input.trim()} onClick={send}>
            <Send className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DiffViewer
// ---------------------------------------------------------------------------

function DiffViewer({ file }: { file: DiffFile }) {
  const store = useReviewStore();
  const { comments, showWhitespace, commentingLine, setCommentingLine, viewMode } = store;

  const submit = async (text: string) => {
    if (!commentingLine) return;
    const { crId, workspace, packages, tool } = store;
    if (!crId || !workspace) return;
    const c: ReviewComment = {
      id: crypto.randomUUID(), file: commentingLine.file, line: commentingLine.line,
      content: text, author: "user", timestamp: Date.now(), replies: [],
    };
    store.addComment(c);
    setCommentingLine(null);
    try {
      const res = await api.cr.comment({
        cr_id: crId, workspace, packages, tool: tool || undefined,
        file: c.file, line: c.line, content: "", question: text,
      });
      store.updateCommentSession(c.id, res.session_id);
    } catch {}
  };

  const doComment = (ln: number, f: string) => setCommentingLine({ file: f, line: ln });

  if (viewMode === "side-by-side") {
    return (
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <tbody>
            {file.hunks.map((hunk, hi) => {
              const leftLines: Array<typeof hunk.lines[0] & { type: string }> = [];
              const rightLines: Array<typeof hunk.lines[0] & { type: string }> = [];
              let i = 0;
              const lines = hunk.lines;
              while (i < lines.length) {
                if (lines[i].type === "ctx") {
                  leftLines.push(lines[i]);
                  rightLines.push(lines[i]);
                  i++;
                } else {
                  const delBlock: typeof lines = [];
                  const addBlock: typeof lines = [];
                  while (i < lines.length && lines[i].type === "del") { delBlock.push(lines[i]); i++; }
                  while (i < lines.length && lines[i].type === "add") { addBlock.push(lines[i]); i++; }
                  const max = Math.max(delBlock.length, addBlock.length);
                  const empty = { type: "empty", content: "", old_num: null, new_num: null } as any;
                  for (let j = 0; j < max; j++) {
                    leftLines.push(delBlock[j] || empty);
                    rightLines.push(addBlock[j] || empty);
                  }
                }
              }
              return (
                <React.Fragment key={hi}>
                  <tr className="bg-blue-500/5">
                    <td colSpan={6} className="px-4 py-1.5 text-xs font-mono text-blue-400/80">{hunk.header}</td>
                  </tr>
                  {leftLines.map((left, li) => {
                    const right = rightLines[li];
                    const ln = right?.new_num || left?.old_num || 0;
                    const commenting = commentingLine?.file === file.path && commentingLine?.line === ln;
                    const lBg = left.type === "del" ? "bg-red-500/8" : left.type === "empty" ? "bg-zinc-800/30" : "";
                    const rBg = right.type === "add" ? "bg-green-500/8" : right.type === "empty" ? "bg-zinc-800/30" : "";
                    const lGutter = left.type === "del" ? "bg-red-500/15 text-red-400" : "text-muted-foreground/50";
                    const rGutter = right.type === "add" ? "bg-green-500/15 text-green-400" : "text-muted-foreground/50";
                    let lC = left.content, rC = right.content;
                    if (showWhitespace) { lC = lC.replace(/ /g, "·").replace(/\t/g, "→   "); rC = rC.replace(/ /g, "·").replace(/\t/g, "→   "); }
                    // highlight.js escapes all HTML in input — safe to render
                    const lH = highlightCode(lC, file.language);
                    const rH = highlightCode(rC, file.language);
                    return (
                      <React.Fragment key={`${hi}-${li}`}>
                        <tr className="group text-[13px] leading-5">
                          <td className={`${lGutter} w-10 text-right pr-2 pl-1 select-none font-mono text-[11px] align-top border-r border-border/20`}>{left.old_num || ""}</td>
                          <td className={`${lBg} font-mono whitespace-pre pr-2 pl-2 align-top w-1/2 border-r border-border/30`}>
                            {left.type !== "empty" && <span dangerouslySetInnerHTML={{ __html: lH }} />}
                          </td>
                          <td className={`${rGutter} w-10 text-right pr-2 pl-1 select-none font-mono text-[11px] align-top`}>{right.new_num || ""}</td>
                          <td className={`${rBg} font-mono whitespace-pre pr-2 pl-2 align-top w-1/2 relative`}>
                            {right.type !== "empty" && <span dangerouslySetInnerHTML={{ __html: rH }} />}
                            <button onClick={() => doComment(ln, file.path)}
                              className="absolute right-2 top-0.5 opacity-0 group-hover:opacity-100 transition-opacity" title="Add comment">
                              <Plus className="w-3.5 h-3.5 text-primary" />
                            </button>
                          </td>
                        </tr>
                        {/* Inline comments for this line */}
                        {comments.filter((c) => c.file === file.path && c.line === ln).map((c) => (
                          <tr key={c.id}><td colSpan={6} className="px-0"><CommentBubble comment={c} /></td></tr>
                        ))}
                        {commenting && <InlineInput file={file.path} line={ln} onSubmit={submit} onCancel={() => setCommentingLine(null)} />}
                      </React.Fragment>
                    );
                  })}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  // Inline view (unified diff)
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <tbody>
          {file.hunks.map((hunk, hi) => (
            <React.Fragment key={hi}>
              <tr className="bg-blue-500/5">
                <td colSpan={4} className="px-4 py-1.5 text-xs font-mono text-blue-400/80">{hunk.header}</td>
              </tr>
              {hunk.lines.map((line, li) => {
                const ln = line.new_num || line.old_num || 0;
                const commenting = commentingLine?.file === file.path && commentingLine?.line === ln;
                return (
                  <React.Fragment key={`${hi}-${li}`}>
                    <DiffLine line={line} language={file.language} showWs={showWhitespace}
                      comments={comments} onComment={doComment} file={file.path} />
                    {commenting && <InlineInput file={file.path} line={ln} onSubmit={submit} onCancel={() => setCommentingLine(null)} />}
                  </React.Fragment>
                );
              })}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PullSpinner — shown during Phase 1 (cr-pull)
// ---------------------------------------------------------------------------

function PullSpinner({ crId }: { crId: string }) {
  const [elapsed, setElapsed] = useState(0);
  const { loadingSteps } = useReviewStore();
  useEffect(() => {
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const defaultSteps = [
    { label: "Resolving CR workspace", status: elapsed >= 0 ? (elapsed < 5 ? "active" : "done") as const : "pending" as const },
    { label: "Running cr-pull", status: elapsed >= 5 ? (elapsed < 40 ? "active" : "done") as const : "pending" as const },
    { label: "Parsing diff hunks", status: elapsed >= 40 ? (elapsed < 60 ? "active" : "done") as const : "pending" as const },
    { label: "Rendering file tree", status: elapsed >= 60 ? "active" as const : "pending" as const },
  ];
  const steps = loadingSteps.length > 0 ? loadingSteps : defaultSteps;
  const doneCount = steps.filter(s => s.status === "done").length;

  return (
    <div className="h-full flex flex-col items-center justify-center max-w-md mx-auto px-6">
      <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
        <GitPullRequest className="w-7 h-7 text-primary" />
      </div>
      <h2 className="text-xl font-bold mb-2">Loading {crId}</h2>
      <p className="text-sm text-muted-foreground mb-1">
        {doneCount} of {steps.length} steps completed · {elapsed}s
      </p>
      <div className="w-full bg-border/30 rounded-full h-1.5 mb-6 overflow-hidden">
        <div className="bg-primary h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.min(100, (doneCount / steps.length) * 100 + (elapsed > 0 ? 5 : 0))}%` }} />
      </div>
      <div className="w-full space-y-2.5 mb-6">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center gap-2.5 text-sm">
            {step.status === "done" && <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />}
            {step.status === "active" && <Loader2 className="w-4 h-4 animate-spin text-primary shrink-0" />}
            {step.status === "pending" && <div className="w-4 h-4 rounded-full border border-border/50 shrink-0" />}
            {step.status === "error" && <XCircle className="w-4 h-4 text-red-400 shrink-0" />}
            <span className={step.status === "done" ? "text-green-400" : step.status === "active" ? "text-foreground" : "text-muted-foreground/50"}>
              {step.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main CodeReview component
// ---------------------------------------------------------------------------

export function CodeReview() {
  const store = useReviewStore();
  const {
    crId, tool, workspace, rawDiff, packages, files, comments,
    isPulling, analysisSessions, selectedFile, buildStatus, buildErrors,
    chatSessions,
  } = store;

  // Collect all session IDs for cleanup
  const allSessionIds = useMemo(() => {
    const ids: string[] = [];
    Object.values(analysisSessions).forEach((s) => { if (s.id) ids.push(s.id); });
    chatSessions.forEach((sid) => ids.push(sid));
    comments.forEach((c) => { if (c.sessionId) ids.push(c.sessionId); });
    return ids;
  }, [analysisSessions, chatSessions, comments]);

  // ---- Phase 1: Find workspace on disk (instant, no network) ----
  const handleLoad = useCallback(async (id: string, selectedTool: string) => {
    if (workspace && allSessionIds.length > 0) {
      try { await api.cr.cleanup({ workspace, session_ids: allSessionIds }); } catch {}
    }
    store.reset();
    store.setReview({ crId: id, tool: selectedTool, isPulling: true, pullError: null });

    try {
      const res = await api.cr.pull(id, selectedTool);
      if (res.error) {
        store.setReview({ isPulling: false, pullError: res.error, workspace: res.workspace || null, packages: res.packages || [] });
        return;
      }
      if (res.files?.length > 0) {
        store.setReview({
          isPulling: false, pullError: null, workspace: res.workspace, packages: res.packages,
          files: res.files as DiffFile[], rawDiff: res.raw_diff,
          selectedFile: (res.files as DiffFile[])[0]?.path || null,
        });
        return;
      }
      store.setReview({ isPulling: false, pullError: "No files found in diff. Workspace may be empty or not checked out." });
    } catch (e: any) {
      let msg = e?.message || "Failed to pull CR. Check that the daemon is running.";
      try {
        const parsed = JSON.parse(msg.replace(/^\d+:\s*/, ""));
        if (parsed.detail) msg = parsed.detail;
      } catch {}
      store.setReview({ isPulling: false, pullError: msg });
    }
  }, [workspace, allSessionIds, store]);

  // ---- Load from existing workspace (no cr-pull) ----
  const handleLoadWorkspace = useCallback(async (wsPath: string, id: string, selectedTool: string) => {
    if (workspace && allSessionIds.length > 0) {
      try { await api.cr.cleanup({ workspace, session_ids: allSessionIds }); } catch {}
    }
    store.reset();
    store.setReview({ crId: id, tool: selectedTool, isPulling: true });

    try {
      const res = await api.cr.loadWorkspace(wsPath, id);
      store.setReview({
        isPulling: false,
        workspace: res.workspace,
        packages: res.packages,
        files: res.files as DiffFile[],
        rawDiff: res.raw_diff,
        selectedFile: (res.files as DiffFile[])[0]?.path || null,
      });
    } catch (e) {
      store.setReview({ isPulling: false });
    }
  }, [workspace, allSessionIds, store]);

  // ---- Auto-fetch existing CR comments after diff loads ----
  useEffect(() => {
    if (!crId || !workspace || files.length === 0) return;
    if (store.fetchCommentsStatus !== "idle") return;
    // Don't fetch if we already have SDE comments from savedComments
    if (comments.some((c) => c.author === "sde")) return;

    const fetchExisting = async () => {
      store.setReview({ fetchCommentsStatus: "fetching" });
      try {
        const res = await api.cr.fetchComments({
          cr_id: crId, workspace, packages, tool: tool || undefined,
        });
        store.setReview({ fetchCommentsSessionId: res.session_id });
      } catch {
        store.setReview({ fetchCommentsStatus: "failed" });
      }
    };
    fetchExisting();
  }, [crId, workspace, files.length]);

  // Poll fetch-comments session
  const fetchExistingSid = store.fetchCommentsSessionId;
  const fetchExistingQuery = useSessionPoller(
    fetchExistingSid && store.fetchCommentsStatus === "fetching" ? fetchExistingSid : null,
  );

  // When fetch-comments completes, parse and add as SDE comments
  useEffect(() => {
    if (!fetchExistingSid || !fetchExistingQuery.data) return;
    const { status, output } = fetchExistingQuery.data;
    if (status !== "completed" && status !== "failed" && status !== "not_found") return;
    if (store.fetchCommentsStatus !== "fetching") return;

    if (status === "completed" && output) {
      const diffFilePaths = files.map((f) => f.path);
      api.cr.parseComments(output, diffFilePaths).then((res) => {
        const existing = store.comments;
        (res.comments || []).forEach((c: any) => {
          if (!c.content) return;
          // Dedup: skip if same author+file+line+content already exists
          const isDup = existing.some((e) =>
            e.author === "sde" && e.file === (c.file || "") && e.line === (c.line || 0) &&
            e.content === c.content
          );
          if (isDup) return;
          store.addComment({
            id: crypto.randomUUID(),
            file: c.file || "",
            line: c.line || 0,
            content: c.content,
            author: "sde",
            authorName: c.author || "SDE",
            severity: c.importance === 1 ? "error" : undefined,
            timestamp: Date.now(),
            replies: [],
          });
        });
        store.setReview({ fetchCommentsStatus: "done" });
      }).catch(() => {
        store.setReview({ fetchCommentsStatus: "failed" });
      });
    } else {
      store.setReview({ fetchCommentsStatus: status === "not_found" ? "failed" : "failed" });
    }
  }, [fetchExistingQuery.data?.status, fetchExistingSid]);

  // ---- Phase 2: Analyze — only on explicit user action ----
  const handleAutoReview = useCallback(async () => {
    if (!crId || !workspace || !rawDiff) return;
    try {
      const res = await api.cr.analyze({
        cr_id: crId, workspace, raw_diff: rawDiff, packages, tool: tool || undefined,
      });
      Object.entries(res.sessions).forEach(([name, sid]) => {
        store.setAnalysisSession(name, { id: sid, name, status: "busy" });
      });
    } catch {}
  }, [crId, workspace, rawDiff, packages, tool]);

  // ---- Poll analysis sessions ----
  const autoReviewSid = analysisSessions.auto_review?.id ?? null;
  const fetchCommentsSid = analysisSessions.fetch_comments?.id ?? null;
  const buildCheckSid = analysisSessions.build_check?.id ?? null;

  const autoReviewQuery = useSessionPoller(
    autoReviewSid && analysisSessions.auto_review?.status === "busy" ? autoReviewSid : null,
  );
  const fetchCommentsQuery = useSessionPoller(
    fetchCommentsSid && analysisSessions.fetch_comments?.status === "busy" ? fetchCommentsSid : null,
  );
  const buildCheckQuery = useSessionPoller(
    buildCheckSid && analysisSessions.build_check?.status === "busy" ? buildCheckSid : null,
  );

  // Handle auto_review completion (including not_found from daemon restart)
  useEffect(() => {
    if (!autoReviewSid || !autoReviewQuery.data) return;
    const { status, output } = autoReviewQuery.data;
    if (status !== "completed" && status !== "failed" && status !== "not_found") return;
    if (analysisSessions.auto_review?.status !== "busy") return;

    store.setAnalysisSession("auto_review", {
      id: autoReviewSid, name: "auto_review", status: status as AnalysisSession["status"],
      error: status === "failed" ? (output?.slice(0, 200) || "Session failed") : undefined,
    });

    if (status === "completed" && output) {
      try {
        let reviews: any[] = [];
        // Try markdown code block first
        const codeBlockMatch = output.match(/```(?:json)?\s*\n([\s\S]*?)\n```/);
        const jsonStr = codeBlockMatch ? codeBlockMatch[1] : output;
        const s = jsonStr.indexOf("{");
        const e = jsonStr.lastIndexOf("}");
        if (s >= 0 && e > s) {
          const data = JSON.parse(jsonStr.slice(s, e + 1));
          reviews = data.reviews || [];
        }
        // Also try array format
        if (!reviews.length) {
          const as = jsonStr.indexOf("[");
          const ae = jsonStr.lastIndexOf("]");
          if (as >= 0 && ae > as) {
            reviews = JSON.parse(jsonStr.slice(as, ae + 1));
          }
        }
        reviews.forEach((r: any) => {
          const rFile = r.file || "";
          const matchedFile = files.find((f) =>
            f.path === rFile || rFile.endsWith(f.path) || f.path.endsWith(rFile) ||
            f.path.includes(rFile) || rFile.includes(f.path.split("/").pop() || "___")
          );
          store.addComment({
            id: crypto.randomUUID(), file: matchedFile?.path || rFile, line: r.line || 0,
            content: r.comment || r.description || r.text || "", author: "auto",
            severity: r.severity || "info",
            suggestion: r.suggestion || r.fix, timestamp: Date.now(), replies: [],
          });
        });
        if (!reviews.length && output.trim().length > 10) {
          // Fallback: LLM returned plain text review — add as single top-level comment
          store.addComment({
            id: crypto.randomUUID(), file: files[0]?.path || "", line: 0,
            content: output.trim(), author: "auto", severity: "info",
            timestamp: Date.now(), replies: [],
          });
        }
      } catch (parseErr) {
        // JSON parse failed — treat entire output as a single review comment
        if (output.trim().length > 10) {
          store.addComment({
            id: crypto.randomUUID(), file: files[0]?.path || "", line: 0,
            content: output.trim(), author: "auto", severity: "info",
            timestamp: Date.now(), replies: [],
          });
        }
        console.warn("Auto-review output parse failed:", parseErr);
      }
    }
  }, [autoReviewQuery.data?.status, autoReviewSid]);

  // Handle fetch_comments completion (including not_found from daemon restart)
  useEffect(() => {
    if (!fetchCommentsSid || !fetchCommentsQuery.data) return;
    const { status, output } = fetchCommentsQuery.data;
    if (status !== "completed" && status !== "failed" && status !== "not_found") return;
    if (analysisSessions.fetch_comments?.status !== "busy") return;

    store.setAnalysisSession("fetch_comments", {
      id: fetchCommentsSid, name: "fetch_comments", status: status as AnalysisSession["status"],
      error: status === "failed" ? (output?.slice(0, 200) || "Session failed") : undefined,
    });

    if (status === "completed" && output) {
      try {
        const s = output.indexOf("[");
        const e = output.lastIndexOf("]");
        if (s >= 0 && e > s) {
          const arr = JSON.parse(output.slice(s, e + 1));
          (arr as any[]).forEach((c: any) => {
            const cFile = c.file || "";
            const matched = files.find((f) =>
              f.path === cFile || cFile.endsWith(f.path) || f.path.endsWith(cFile) ||
              f.path.includes(cFile) || cFile.includes(f.path.split("/").pop() || "___")
            );
            store.addComment({
              id: crypto.randomUUID(),
              file: matched?.path || cFile, line: c.line || 0,
              content: c.text || c.content || "",
              author: "sde", authorName: c.author || "SDE",
              severity: c.severity || undefined,
              timestamp: Date.now(), replies: [],
            });
          });
        }
      } catch {
        // Also try object-wrapped format
        try {
          const s = output.indexOf("{");
          const e = output.lastIndexOf("}");
          if (s >= 0 && e > s) {
            const data = JSON.parse(output.slice(s, e + 1));
            (data.comments || []).forEach((c: any) => {
              const cFile = c.file || "";
              const matched = files.find((f) =>
                f.path === cFile || cFile.endsWith(f.path) || f.path.endsWith(cFile) ||
                f.path.includes(cFile) || cFile.includes(f.path.split("/").pop() || "___")
              );
              store.addComment({
                id: crypto.randomUUID(),
                file: matched?.path || cFile, line: c.line || 0,
                content: c.text || c.content || "",
                author: "sde", authorName: c.author || "SDE",
                severity: c.severity || undefined,
                timestamp: Date.now(), replies: [],
              });
            });
          }
        } catch {}
      }
    }
  }, [fetchCommentsQuery.data?.status, fetchCommentsSid]);

  // Handle build_check completion (including not_found from daemon restart)
  useEffect(() => {
    if (!buildCheckSid || !buildCheckQuery.data) return;
    const { status, output, error } = buildCheckQuery.data;
    if (status !== "completed" && status !== "failed" && status !== "not_found") return;
    if (analysisSessions.build_check?.status !== "busy") return;

    store.setAnalysisSession("build_check", {
      id: buildCheckSid, name: "build_check", status: status as AnalysisSession["status"],
    });

    if (status === "completed" && output) {
      const lower = output.toLowerCase();
      if (lower.includes("pass") || lower.includes("success") || lower.includes("build succeeded")) {
        store.setReview({ buildStatus: "pass" });
      } else if (lower.includes("fail") || lower.includes("error")) {
        store.setReview({ buildStatus: "fail", buildErrors: output });
      } else {
        store.setReview({ buildStatus: "pass" });
      }
    } else if (status === "failed") {
      store.setReview({ buildStatus: "fail", buildErrors: error || "Build check failed" });
    }
  }, [buildCheckQuery.data?.status, buildCheckSid]);

  // ---- Render states ----
  const currentFile = files.find((f) => f.path === selectedFile);
  const totalAdd = files.reduce((a, f) => a + f.additions, 0);
  const totalDel = files.reduce((a, f) => a + f.deletions, 0);

  // No CR loaded yet
  if (!crId && !isPulling) return <div className="h-full p-6"><LoadCRDialog onLoad={handleLoad} /></div>;

  // Phase 1: pulling
  if (isPulling) return <PullSpinner crId={crId!} />;

  // Error or empty diff — show actionable error
  if (!isPulling && crId && files.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-5 max-w-lg mx-auto px-6">
        <AlertCircle className="w-10 h-10 text-yellow-400" />
        <p className="font-semibold text-lg">Could not load {crId}</p>
        {store.pullError && (
          <div className="w-full bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-left">
            <p className="text-sm text-red-300 whitespace-pre-wrap">{store.pullError}</p>
          </div>
        )}
        {workspace && (
          <div className="w-full bg-zinc-800/50 border border-border/30 rounded-lg p-3 text-xs">
            <span className="text-muted-foreground">Workspace: </span>
            <code className="text-primary">{workspace}</code>
            <span className="text-muted-foreground"> (diff empty — branch may not have changes vs mainline)</span>
          </div>
        )}
        <div className="w-full space-y-2 text-sm text-muted-foreground">
          <p>Bridge tried <code className="text-primary">cr-pull -w {crId}</code> automatically but couldn't get a diff.</p>
          <p>Common causes:</p>
          <ul className="list-disc ml-5 space-y-1 text-xs">
            <li>CR doesn't exist or has been merged</li>
            <li>Network/VPN not connected (cr-pull needs GitFarm access)</li>
            <li>Version set mismatch — try from an existing workspace</li>
            <li>CR has no published revisions yet</li>
          </ul>
        </div>
        <div className="w-full bg-[#0d1117] rounded-lg p-3 font-mono text-xs text-green-400 select-all cursor-pointer border border-border/30"
          onClick={() => navigator.clipboard.writeText(`cr-pull -w ${crId}`)}>
          Manual: cr-pull -w {crId}
          <span className="text-muted-foreground ml-2">(click to copy)</span>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" onClick={() => store.reset()}>New CR</Button>
          <Button onClick={() => handleLoad(crId, tool || "wasabi")}>Retry</Button>
        </div>
      </div>
    );
  }

  // Main diff view
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-border flex items-center justify-between shrink-0 bg-card">
        <div className="flex items-center gap-3">
          <GitPullRequest className="w-4 h-4 text-primary" />
          <span className="font-semibold text-sm">{crId}</span>
          {packages.map((p) => <Badge key={p} variant="outline" className="text-[10px]">{p}</Badge>)}
          <span className="text-xs text-muted-foreground">
            {files.length} files · <span className="text-green-400">+{totalAdd}</span> <span className="text-red-400">-{totalDel}</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant={store.viewMode === "side-by-side" ? "default" : "outline"} className="h-7 text-[10px] px-2"
            onClick={() => store.setViewMode("side-by-side")}>
            <Columns className="w-3 h-3 mr-1" /> Side-by-Side
          </Button>
          <Button size="sm" variant={store.viewMode === "inline" ? "default" : "outline"} className="h-7 text-[10px] px-2"
            onClick={() => store.setViewMode("inline")}>
            <AlignJustify className="w-3 h-3 mr-1" /> Inline
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[10px] px-2"
            onClick={() => store.setShowWhitespace(!store.showWhitespace)}>
            {store.showWhitespace ? <EyeOff className="w-3 h-3 mr-1" /> : <Eye className="w-3 h-3 mr-1" />} Whitespace
          </Button>
          <Button size="sm" variant="secondary" className="h-7 text-[10px] px-2"
            disabled={Object.values(analysisSessions).some(s => s.status === "busy")}
            onClick={handleAutoReview}>
            <Sparkles className="w-3 h-3 mr-1" />
            {Object.values(analysisSessions).some(s => s.status === "busy") ? "Reviewing..." : "AI Review"}
          </Button>
          {store.fetchCommentsStatus === "fetching" && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 gap-0.5">
              <Loader2 className="w-2.5 h-2.5 animate-spin" /> Fetching CR comments...
            </Badge>
          )}
          {store.fetchCommentsStatus === "done" && (() => {
            const crComments = comments.filter(c => c.author === "sde");
            return (
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0 gap-0.5 ${crComments.length > 0 ? "text-cyan-400 border-cyan-500/30" : "text-muted-foreground border-border/50"}`}>
                <CheckCircle2 className="w-2.5 h-2.5" />
                {crComments.length > 0 ? `${crComments.length} CR comments` : "No CR comments"}
              </Badge>
            );
          })()}
          {buildStatus === "pass" && (
            <Badge variant="success" className="text-[10px] px-1.5 py-0 gap-0.5"><CheckCircle2 className="w-2.5 h-2.5" /> Build OK</Badge>
          )}
          {buildStatus === "fail" && (
            <Badge variant="destructive" className="text-[10px] px-1.5 py-0 gap-0.5"><XCircle className="w-2.5 h-2.5" /> Build Fail</Badge>
          )}
          <Button size="sm" variant="outline" className="h-7 text-[10px] px-2" onClick={() => store.reset()}>
            <FolderOpen className="w-3 h-3 mr-1" /> Load CR
          </Button>
          <Button size="sm" variant="ghost" className="h-7 text-[10px] px-2" onClick={() => store.reset()}>
            <X className="w-3 h-3 mr-1" /> Close
          </Button>
        </div>
      </div>

      {/* Analysis status bar */}
      <AnalysisStatusBar />

      {/* Build errors banner */}
      {buildStatus === "fail" && buildErrors && (
        <div className="px-4 py-2 border-b border-red-500/30 bg-red-500/5 text-xs text-red-400 font-mono whitespace-pre-wrap max-h-24 overflow-y-auto">
          {buildErrors.slice(0, 1000)}
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <FileTree files={files} selectedFile={selectedFile} onSelect={(p) => store.setSelectedFile(p)} comments={comments} packages={packages} />

        <div className="flex-1 overflow-auto bg-[#0d1117]">
          {currentFile ? (
            <div>
              <div className="sticky top-0 z-10 px-4 py-2 bg-[#161b22] border-b border-border/30 flex items-center gap-2 text-xs">
                <FileCode className={`w-3.5 h-3.5 ${FILE_COLORS[currentFile.language] || "text-muted-foreground"}`} />
                <span className="font-mono">{currentFile.path}</span>
                <span className="text-green-400">+{currentFile.additions}</span>
                <span className="text-red-400">-{currentFile.deletions}</span>
              </div>
              <DiffViewer file={currentFile} />
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">Select a file</div>
          )}
        </div>

        <ReviewChat />
      </div>
    </div>
  );
}
