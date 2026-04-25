import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button, Input, Textarea } from "./ui";
import { formatRelativeTime, cn } from "@/lib/utils";
import { Brain, Search, Plus, Trash2, Database, RefreshCw, FileText, Code, Globe, BookOpen, Tag, GitBranch, X } from "lucide-react";

type Tab = "documents" | "search" | "graph" | "tags";

export function MemoryBrowser() {
  const [tab, setTab] = useState<Tab>("documents");

  return (
    <div className="p-6 max-w-6xl space-y-4 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-semibold tracking-tight">Knowledge Base</h1>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {([
          { id: "documents" as Tab, label: "Documents", icon: FileText },
          { id: "search" as Tab, label: "Search", icon: Search },
          { id: "graph" as Tab, label: "Graph", icon: GitBranch },
          { id: "tags" as Tab, label: "Tags", icon: Tag },
        ]).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 -mb-px transition-colors",
              tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {tab === "documents" && <DocumentsTab />}
      {tab === "search" && <SearchTab />}
      {tab === "graph" && <GraphTab />}
      {tab === "tags" && <TagsTab />}
    </div>
  );
}

// ---- Documents Tab ----
function DocumentsTab() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["kb-documents"], queryFn: api.knowledge.documents });
  const { data: statsData } = useQuery({ queryKey: ["memory-stats"], queryFn: api.memory.stats });
  const docs = data?.documents ?? [];
  const [addOpen, setAddOpen] = useState(false);

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.knowledge.deleteDocument(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["kb-documents"] }); qc.invalidateQueries({ queryKey: ["memory-stats"] }); },
  });
  const refreshMut = useMutation({
    mutationFn: (id: string) => api.knowledge.refreshDocument(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["kb-documents"] }); qc.invalidateQueries({ queryKey: ["memory-stats"] }); },
  });
  const refreshAllMut = useMutation({
    mutationFn: () => api.knowledge.refreshAll(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["kb-documents"] }); qc.invalidateQueries({ queryKey: ["memory-stats"] }); },
  });

  const ICONS: Record<string, any> = { wiki: BookOpen, code: Code, web: Globe, quip: FileText, file: FileText };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {docs.length} documents · {statsData?.total_entries ?? 0} total entries · {((statsData?.db_size_bytes ?? 0) / 1024 / 1024).toFixed(1)}MB
        </p>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => refreshAllMut.mutate()} disabled={refreshAllMut.isPending}>
            <RefreshCw className={cn("w-3.5 h-3.5", refreshAllMut.isPending && "animate-spin")} />
            {refreshAllMut.isPending ? "Refreshing..." : "Refresh All"}
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="w-3.5 h-3.5" />
            Add Document
          </Button>
        </div>
      </div>

      {docs.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">
          No documents ingested. Click "Add Document" to import wikis, code, or files.
        </CardContent></Card>
      ) : (
        <div className="space-y-2">
          {docs.map((doc: any) => {
            const Icon = ICONS[doc.source_type] || FileText;
            const tags = JSON.parse(doc.tags || "[]");
            return (
              <Card key={doc.id} className="hover:border-primary/30 transition-colors">
                <CardContent className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <Icon className="w-5 h-5 text-muted-foreground shrink-0 mt-0.5" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{doc.name}</div>
                        <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                          <span>{doc.source_type}</span>
                          <span>·</span>
                          <span>{doc.chunk_count} chunks</span>
                          <span>·</span>
                          <span className="truncate max-w-[300px]">{doc.source_url}</span>
                          {doc.last_refreshed && (
                            <>
                              <span>·</span>
                              <span>refreshed {formatRelativeTime(doc.last_refreshed)}</span>
                            </>
                          )}
                        </div>
                        {tags.length > 0 && (
                          <div className="flex gap-1 mt-1.5 flex-wrap">
                            {tags.map((t: string) => (
                              <span key={t} className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px]">{t}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button size="icon" variant="ghost" onClick={() => refreshMut.mutate(doc.id)} disabled={refreshMut.isPending}>
                        <RefreshCw className={cn("w-3.5 h-3.5", refreshMut.isPending && "animate-spin")} />
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => { if (confirm("Delete document + all chunks?")) deleteMut.mutate(doc.id); }}>
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

      {addOpen && <AddDocumentDialog onClose={() => setAddOpen(false)} />}
    </div>
  );
}

function AddDocumentDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("file");
  const [sourceUrl, setSourceUrl] = useState("");
  const [collection, setCollection] = useState("");
  const [tags, setTags] = useState("");

  const createMut = useMutation({
    mutationFn: () => api.knowledge.registerDocument({
      name, source_type: sourceType, source_url: sourceUrl,
      collection: collection || name.toLowerCase().replace(/\s+/g, "-"),
      tags: tags.split(",").map(t => t.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-documents"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md p-5 relative">
        <button onClick={onClose} className="absolute right-3 top-3 text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
        <h2 className="font-semibold mb-4">Add Document</h2>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Name</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nexus Architecture Wiki" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Source type</label>
            <select value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="w-full h-9 rounded-md border border-border bg-transparent px-3 text-sm">
              <option value="file">File / Directory</option>
              <option value="code">Code Package</option>
              <option value="wiki">Wiki Page</option>
              <option value="quip">Quip Document</option>
              <option value="web">Web URL</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Path or URL</label>
            <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="/path/to/dir or https://..." />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Collection (auto-generated if empty)</label>
            <Input value={collection} onChange={(e) => setCollection(e.target.value)} placeholder="nexus-docs" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Tags (comma-separated)</label>
            <Input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="nexus, architecture, docs" />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
            <Button size="sm" onClick={() => createMut.mutate()} disabled={!name.trim() || !sourceUrl.trim() || createMut.isPending}>
              {createMut.isPending ? "Adding..." : "Add Document"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Search Tab ----
function SearchTab() {
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [results, setResults] = useState<any[] | null>(null);
  const { data: tagsData } = useQuery({ queryKey: ["kb-tags"], queryFn: api.knowledge.tags });

  const searchMut = useMutation({
    mutationFn: () => api.memory.search(query, undefined, 20),
    onSuccess: (data) => {
      let filtered = data.results;
      if (tagFilter.length > 0) {
        filtered = filtered.filter((r: any) => {
          const rTags = JSON.parse(r.metadata?.tags || r.tags || "[]");
          return tagFilter.some(t => rTags.includes(t));
        });
      }
      setResults(filtered);
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search knowledge base..."
          onKeyDown={(e) => { if (e.key === "Enter" && query.trim()) searchMut.mutate(); }} />
        <Button onClick={() => searchMut.mutate()} disabled={!query.trim() || searchMut.isPending}>
          <Search className="w-3.5 h-3.5" />
        </Button>
      </div>

      {/* Tag filter chips */}
      {(tagsData?.tags ?? []).length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {(tagsData?.tags ?? []).slice(0, 20).map((t: any) => (
            <button key={t.name} onClick={() => setTagFilter(prev => prev.includes(t.name) ? prev.filter(x => x !== t.name) : [...prev, t.name])}
              className={cn("px-2 py-0.5 rounded text-[10px] transition-colors",
                tagFilter.includes(t.name) ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent")}>
              {t.name} ({t.count})
            </button>
          ))}
        </div>
      )}

      {results && (
        <div className="space-y-2">
          {results.length === 0 ? <p className="text-xs text-muted-foreground">No results</p> : results.map((r: any) => (
            <Card key={r.id}>
              <CardContent className="py-2.5">
                <div className="flex items-start gap-2">
                  <Badge variant="secondary" className="text-[9px] shrink-0">{(r.score * 100).toFixed(0)}%</Badge>
                  <Badge variant="outline" className="text-[9px] shrink-0">{r.collection}</Badge>
                  <div className="min-w-0 flex-1">
                    {r.summary && <div className="text-xs font-medium text-foreground/90">{r.summary}</div>}
                    <div className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{r.text?.slice(0, 200)}</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Graph Tab ----
function GraphTab() {
  const { data } = useQuery({ queryKey: ["kb-graph"], queryFn: api.knowledge.graph });
  const nodes = data?.nodes ?? [];
  const edges = data?.edges ?? [];

  if (nodes.length === 0) {
    return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">
      No knowledge graph yet. Ingest documents to build connections.
    </CardContent></Card>;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">{nodes.length} nodes · {edges.length} edges</p>
      <Card>
        <CardContent className="py-4">
          <div className="space-y-1">
            {edges.map((e: any, i: number) => (
              <div key={i} className="text-xs flex items-center gap-2">
                <span className="text-foreground/80 truncate max-w-[200px]">#{e.source}</span>
                <span className="text-primary font-mono text-[10px]">—{e.relation}→</span>
                <span className="text-foreground/80 truncate max-w-[200px]">#{e.target}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---- Tags Tab ----
function TagsTab() {
  const { data } = useQuery({ queryKey: ["kb-tags"], queryFn: api.knowledge.tags });
  const tags = data?.tags ?? [];

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">{tags.length} tags</p>
      {tags.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">
          No tags yet. Tags are auto-generated during document ingestion.
        </CardContent></Card>
      ) : (
        <div className="flex gap-2 flex-wrap">
          {tags.map((t: any) => (
            <div key={t.name} className="px-3 py-1.5 rounded-lg bg-accent border border-border">
              <div className="text-sm font-medium">{t.name}</div>
              <div className="text-[10px] text-muted-foreground">{t.count} entries</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
