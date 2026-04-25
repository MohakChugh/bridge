import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle, Badge, Button, Input, Textarea } from "./ui";
import { formatRelativeTime } from "@/lib/utils";
import { Brain, Search, Plus, Trash2, Database, Upload, X } from "lucide-react";

export function MemoryBrowser() {
  const qc = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchCollections, setSearchCollections] = useState<string[]>([]);
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [newCollection, setNewCollection] = useState("");
  const [addText, setAddText] = useState("");
  const [addCollection, setAddCollection] = useState("");
  const [browseCollection, setBrowseCollection] = useState<string | null>(null);

  const { data: collectionsData } = useQuery({ queryKey: ["memory-collections"], queryFn: api.memory.collections });
  const { data: statsData } = useQuery({ queryKey: ["memory-stats"], queryFn: api.memory.stats });
  const { data: entriesData } = useQuery({
    queryKey: ["memory-entries", browseCollection],
    queryFn: () => browseCollection ? api.memory.entries(browseCollection) : null,
    enabled: !!browseCollection,
  });

  const collections = collectionsData?.collections ?? [];
  const stats = statsData ?? { total_entries: 0, db_size_bytes: 0 };

  const searchMut = useMutation({
    mutationFn: () => api.memory.search(searchQuery, searchCollections.length ? searchCollections : undefined, 10),
    onSuccess: (data) => setSearchResults(data.results),
  });

  const createMut = useMutation({
    mutationFn: () => api.memory.createCollection(newCollection),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory-collections"] });
      qc.invalidateQueries({ queryKey: ["memory-stats"] });
      setNewCollection("");
    },
  });

  const addMut = useMutation({
    mutationFn: () => api.memory.add(addText, addCollection),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory-stats"] });
      qc.invalidateQueries({ queryKey: ["memory-collections"] });
      qc.invalidateQueries({ queryKey: ["memory-entries", addCollection] });
      setAddText("");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.memory.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory-stats"] });
      qc.invalidateQueries({ queryKey: ["memory-collections"] });
      if (browseCollection) qc.invalidateQueries({ queryKey: ["memory-entries", browseCollection] });
    },
  });

  const deleteCollMut = useMutation({
    mutationFn: (name: string) => api.memory.deleteCollection(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory-collections"] });
      qc.invalidateQueries({ queryKey: ["memory-stats"] });
      if (browseCollection) setBrowseCollection(null);
    },
  });

  return (
    <div className="p-6 max-w-5xl space-y-6 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-5 h-5 text-primary" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Shared Memory</h1>
            <p className="text-xs text-muted-foreground">
              {stats.total_entries} entries · {(stats.db_size_bytes / 1024).toFixed(0)}KB
            </p>
          </div>
        </div>
      </div>

      {/* Search */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-2">
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search across all memory..."
              onKeyDown={(e) => { if (e.key === "Enter" && searchQuery.trim()) searchMut.mutate(); }}
            />
            <Button onClick={() => searchMut.mutate()} disabled={!searchQuery.trim() || searchMut.isPending}>
              <Search className="w-3.5 h-3.5" />
              {searchMut.isPending ? "..." : "Search"}
            </Button>
          </div>
          {searchResults && (
            <div className="mt-3 space-y-2">
              {searchResults.length === 0 ? (
                <p className="text-xs text-muted-foreground">No results</p>
              ) : searchResults.map((r) => (
                <div key={r.id} className="flex items-start gap-2 text-xs border-l-2 border-primary/30 pl-2 py-1">
                  <Badge variant="secondary" className="text-[9px] shrink-0">{(r.score * 100).toFixed(0)}%</Badge>
                  <Badge variant="outline" className="text-[9px] shrink-0">{r.collection}</Badge>
                  <span className="text-foreground/80 line-clamp-2">{r.text}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Collections */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="w-4 h-4" />
              Collections
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {collections.map((c: any) => (
              <div key={c.name} className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
                <button onClick={() => setBrowseCollection(c.name)} className="text-left min-w-0">
                  <div className="text-sm font-medium">{c.name}</div>
                  <div className="text-[10px] text-muted-foreground">{c.entry_count} entries · {c.description}</div>
                </button>
                <Button size="icon" variant="ghost" onClick={() => { if (confirm(`Delete collection "${c.name}"?`)) deleteCollMut.mutate(c.name); }}>
                  <Trash2 className="w-3 h-3 text-destructive" />
                </Button>
              </div>
            ))}
            <div className="flex gap-2 pt-2">
              <Input value={newCollection} onChange={(e) => setNewCollection(e.target.value)} placeholder="New collection" className="h-8 text-xs" />
              <Button size="sm" onClick={() => createMut.mutate()} disabled={!newCollection.trim()}>
                <Plus className="w-3 h-3" />
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Add entry */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="w-4 h-4" />
              Add to Memory
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              value={addCollection}
              onChange={(e) => setAddCollection(e.target.value)}
              className="w-full h-8 rounded border border-border bg-transparent px-2 text-xs"
            >
              <option value="">Select collection...</option>
              {collections.map((c: any) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
            <Textarea
              value={addText}
              onChange={(e) => setAddText(e.target.value)}
              placeholder="Enter text to remember..."
              rows={3}
            />
            <Button size="sm" onClick={() => addMut.mutate()} disabled={!addText.trim() || !addCollection || addMut.isPending}>
              <Plus className="w-3 h-3" />
              {addMut.isPending ? "Adding..." : "Add"}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Browse entries */}
      {browseCollection && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>{browseCollection} entries</CardTitle>
              <button onClick={() => setBrowseCollection(null)} className="text-muted-foreground hover:text-foreground">
                <X className="w-4 h-4" />
              </button>
            </div>
          </CardHeader>
          <CardContent>
            {(entriesData?.entries ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">No entries</p>
            ) : (
              <div className="space-y-2">
                {(entriesData?.entries ?? []).map((e: any) => (
                  <div key={e.id} className="flex items-start gap-2 text-xs py-1.5 border-b border-border/50">
                    <Badge variant="secondary" className="text-[9px] shrink-0">{e.source}</Badge>
                    <span className="flex-1 text-foreground/80 line-clamp-2">{e.text}</span>
                    <span className="text-muted-foreground shrink-0">{formatRelativeTime(e.created_at)}</span>
                    <button onClick={() => deleteMut.mutate(e.id)}>
                      <Trash2 className="w-3 h-3 text-destructive" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
