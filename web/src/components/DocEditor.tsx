import React, { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import Image from "@tiptap/extension-image";
import { Markdown } from "tiptap-markdown";
import { common, createLowlight } from "lowlight";
import { MermaidExtension } from "./MermaidNode";
import { api } from "@/api/client";
import { Button, Input, Badge } from "./ui";
import { cn } from "@/lib/utils";
import { useDocStore } from "@/stores/docStore";
import {
  FileEdit,
  Plus,
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  Trash2,
  Save,
  Sparkles,
  Loader2,
  X,
  FolderPlus,
  Brain,
} from "lucide-react";

const lowlight = createLowlight(common);

// ---------- Types ----------
interface DocTreeItem {
  id: string;
  title: string;
  type: "doc" | "folder";
  parent_id: string | null;
  children?: DocTreeItem[];
  tags?: string[];
  updated_at?: number;
}

// ---------- DocSidebar ----------
function DocSidebar() {
  const { activeDocId, setActiveDocId, expandedFolders, toggleFolder } = useDocStore();
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState<{ parentId: string | null; type: "doc" | "folder" } | null>(null);
  const [newName, setNewName] = useState("");

  const { data: tree, isLoading } = useQuery({
    queryKey: ["doc-tree"],
    queryFn: () => api.docs.tree() as Promise<{ tree: any[] }>,
  });

  const createMut = useMutation({
    mutationFn: (body: { title: string; type: string; parent_id: string | null }) => {
      if (body.type === "folder") {
        return api.docs.createFolder(body.parent_id ? `${body.parent_id}/${body.title}` : body.title);
      }
      const filename = body.title.endsWith(".md") ? body.title : `${body.title}.md`;
      return api.docs.create({
        path: body.parent_id ? `${body.parent_id}/${filename}` : filename,
        title: body.title,
        tags: [],
      });
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ["doc-tree"] });
      if (data?.id) setActiveDocId(data.id);
      setCreating(null);
      setNewName("");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.docs.delete(id),
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["doc-tree"] });
      if (activeDocId === deletedId) setActiveDocId(null);
    },
  });

  function handleCreate() {
    if (!newName.trim() || !creating) return;
    createMut.mutate({ title: newName.trim(), type: creating.type, parent_id: creating.parentId });
  }

  function renderItem(item: DocTreeItem, depth: number = 0) {
    const isFolder = item.type === "folder";
    const isExpanded = expandedFolders.has(item.id);
    const isActive = activeDocId === item.id;

    return (
      <div key={item.id}>
        <div
          className={cn(
            "group flex items-center gap-1.5 px-2 py-1 rounded-md text-sm cursor-pointer transition-colors",
            isActive ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
          )}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
          onClick={() => { if (isFolder) toggleFolder(item.id); else setActiveDocId(item.id); }}
        >
          {isFolder ? (isExpanded ? <ChevronDown className="w-3.5 h-3.5 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 shrink-0" />) : <span className="w-3.5" />}
          {isFolder ? <Folder className="w-3.5 h-3.5 shrink-0 text-primary/60" /> : <File className="w-3.5 h-3.5 shrink-0" />}
          <span className="truncate flex-1 text-xs">{item.title || item.name}</span>
          <button
            className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/20 transition-opacity"
            onClick={(e) => { e.stopPropagation(); if (confirm(`Delete "${item.title}"?`)) deleteMut.mutate(item.id); }}
          >
            <Trash2 className="w-3 h-3 text-destructive" />
          </button>
        </div>
        {isFolder && isExpanded && item.children?.map((child) => renderItem(child, depth + 1))}
      </div>
    );
  }

  return (
    <div className="w-60 shrink-0 border-r border-border bg-card/30 flex flex-col h-full overflow-hidden">
      <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileEdit className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold tracking-tight">Documents</span>
        </div>
        <div className="flex gap-0.5">
          <Button variant="ghost" size="icon" className="h-6 w-6" title="New document" onClick={() => setCreating({ parentId: null, type: "doc" })}>
            <Plus className="w-3.5 h-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-6 w-6" title="New folder" onClick={() => setCreating({ parentId: null, type: "folder" })}>
            <FolderPlus className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
      {creating && (
        <div className="px-2 py-2 border-b border-border space-y-1.5">
          <Input
            autoFocus
            placeholder={creating.type === "folder" ? "Folder name" : "Document title"}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); if (e.key === "Escape") { setCreating(null); setNewName(""); } }}
            className="h-7 text-xs"
          />
          <div className="flex gap-1">
            <Button size="sm" className="h-6 text-[10px] flex-1" onClick={handleCreate} disabled={createMut.isPending}>
              {createMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : "Create"}
            </Button>
            <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => { setCreating(null); setNewName(""); }}>Cancel</Button>
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {isLoading && <div className="flex items-center justify-center py-8"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>}
        {tree?.tree?.map((item: any) => renderItem(item))}
        {!isLoading && (!tree?.tree || tree.tree.length === 0) && <p className="text-xs text-muted-foreground text-center py-6">No documents yet</p>}
      </div>
    </div>
  );
}

// ---------- CommandPalette ----------
function CommandPalette({ docId, onClose, selectedText, selectionRange }: {
  docId: string;
  onClose: () => void;
  selectedText?: string;
  selectionRange?: { from: number; to: number } | null;
}) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isEditMode = !!selectedText;

  useEffect(() => { textareaRef.current?.focus(); }, []);

  async function handleSubmit() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    try {
      if (isEditMode) {
        await api.docs.editSelection(docId, {
          selected_text: selectedText!,
          line_start: 0,
          line_end: 0,
          feedback: prompt.trim(),
        });
      } else {
        await api.docs.generate(docId, prompt.trim());
      }
      onClose();
    } catch (err: any) {
      useDocStore.getState().failGeneration(err?.message || (isEditMode ? "Edit failed" : "Generation failed"));
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/50" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl border border-border bg-card shadow-2xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className={cn("w-4 h-4", isEditMode ? "text-amber-400" : "text-primary")} />
            <span className="text-sm font-semibold">{isEditMode ? "AI Edit Selection" : "AI Generate"}</span>
          </div>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}><X className="w-3.5 h-3.5" /></Button>
        </div>
        {isEditMode && (
          <div className="rounded-md border border-border bg-muted/50 px-3 py-2 max-h-32 overflow-y-auto">
            <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words">{selectedText}</pre>
          </div>
        )}
        <textarea
          ref={textareaRef}
          className="flex min-h-[100px] w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary resize-none"
          placeholder={isEditMode ? "Describe how to change this section..." : "Describe what to generate... e.g. 'Write an overview of our auth system' or 'Add a mermaid sequence diagram for the API flow'"}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); handleSubmit(); }
            if (e.key === "Escape") onClose();
          }}
        />
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground">⌘+Enter to {isEditMode ? "edit" : "generate"} · Escape to close</span>
          <Button size="sm" disabled={!prompt.trim() || loading} onClick={handleSubmit} className="gap-1">
            {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
            {isEditMode ? "Edit" : "Generate"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------- GenerationOverlay ----------
function GenerationOverlay() {
  const gen = useDocStore((s) => s.activeGeneration);
  const clearGeneration = useDocStore((s) => s.clearGeneration);

  if (!gen || gen.status === "complete") return null;

  return (
    <div className="absolute bottom-0 left-0 right-0 border-t border-border bg-card/95 backdrop-blur px-3 py-2 flex items-center gap-2 z-10">
      {gen.status === "streaming" && (
        <>
          <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
          <span className="text-xs text-muted-foreground">AI is writing...</span>
          <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden ml-2">
            <div className="h-full bg-primary/60 rounded-full animate-pulse" style={{ width: "60%" }} />
          </div>
        </>
      )}
      {gen.status === "error" && (
        <>
          <span className="text-xs text-destructive">{gen.error || "Generation failed"}</span>
          <Button variant="ghost" size="sm" className="ml-auto h-6 text-[10px]" onClick={clearGeneration}>Dismiss</Button>
        </>
      )}
    </div>
  );
}

// ---------- EmptyDocState ----------
function EmptyDocState() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center space-y-3">
        <FileEdit className="w-12 h-12 text-muted-foreground/20 mx-auto" />
        <p className="text-sm text-muted-foreground">Select or create a document</p>
        <p className="text-xs text-muted-foreground/60">Use the sidebar to browse, or press + to create</p>
      </div>
    </div>
  );
}

// ---------- Safe TipTap wrapper — prevents React removeChild crash ----------
function SafeEditorContent({ editor }: { editor: any }) {
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el || !editor) return;
    try {
      const dom = editor.view?.dom;
      if (!dom) return;
      while (el.firstChild) el.removeChild(el.firstChild);
      el.appendChild(dom);
    } catch { return; }
    return () => {
      try {
        const dom = editor.view?.dom;
        if (dom && el.contains(dom)) el.removeChild(dom);
      } catch {}
    };
  }, [editor]);

  return <div ref={containerRef} className="h-full doc-markdown outline-none min-h-full px-8 py-6 max-w-none" />;
}

// ---------- Tiptap DocEditorPane ----------
function DocEditorPane({ docId }: { docId: string }) {
  const queryClient = useQueryClient();
  const { isDirty, setIsDirty, commandPaletteOpen, setCommandPaletteOpen, activeGeneration, clearGeneration } = useDocStore();
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const contentInitializedRef = useRef(false);
  const suppressUpdateRef = useRef(false);
  const preGenContentRef = useRef("");
  const pendingReloadRef = useRef(false);
  const loadedDocIdRef = useRef<string | null>(null);

  // Feature 1: Selection tracking
  const [selectedText, setSelectedText] = useState("");
  const [selectionRange, setSelectionRange] = useState<{from: number; to: number} | null>(null);
  const editSelectionRef = useRef<string>("");

  // Feature 3: Save to Memory
  const [saveToMemoryResult, setSaveToMemoryResult] = useState<string | null>(null);
  const saveToMemoryMut = useMutation({
    mutationFn: () => api.docs.saveToMemory(docId),
    onSuccess: (data: any) => {
      setSaveToMemoryResult(`Indexed: ${data.chunks} chunks`);
      setTimeout(() => setSaveToMemoryResult(null), 5000);
    },
    onError: () => setSaveToMemoryResult(null),
  });

  const { data: doc, isLoading } = useQuery({
    queryKey: ["doc", docId],
    queryFn: () => api.docs.get(docId),
  });

  const saveMut = useMutation({
    mutationFn: (body: { content: string }) => api.docs.update(docId, body),
    onSuccess: () => {
      setIsDirty(false);
      queryClient.invalidateQueries({ queryKey: ["doc", docId] });
      queryClient.invalidateQueries({ queryKey: ["doc-tree"] });
    },
  });

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        codeBlock: false,
        heading: { levels: [1, 2, 3, 4] },
      }),
      Placeholder.configure({ placeholder: "Start writing... Type # for headings, - for lists, ``` for code blocks" }),
      CodeBlockLowlight.configure({ lowlight }),
      MermaidExtension,
      TaskList,
      TaskItem.configure({ nested: true }),
      Image,
      Markdown.configure({
        html: true,
        transformPastedText: true,
        transformCopiedText: true,
      }),
    ],
    editorProps: {
      attributes: {
        class: "doc-markdown outline-none min-h-[200px] px-8 py-6 max-w-none",
      },
      handleDrop: (view, event, slice, moved) => {
        if (!moved && event.dataTransfer?.files?.length) {
          const file = event.dataTransfer.files[0];
          if (file.type.startsWith("image/")) {
            event.preventDefault();
            handleImageUpload(file);
            return true;
          }
        }
        return false;
      },
      handlePaste: (view, event) => {
        const items = event.clipboardData?.items;
        if (!items) return false;
        const hasText = Array.from(items).some(
          (i) => i.kind === "string" && (i.type === "text/plain" || i.type === "text/html"),
        );
        if (hasText) return false;
        for (const item of Array.from(items)) {
          if (item.type.startsWith("image/")) {
            event.preventDefault();
            const file = item.getAsFile();
            if (file) handleImageUpload(file);
            return true;
          }
        }
        return false;
      },
    },
    onUpdate: () => {
      if (contentInitializedRef.current && !suppressUpdateRef.current) {
        setIsDirty(true);
      }
    },
    onSelectionUpdate: ({ editor: e }) => {
      if (e.isDestroyed) return;
      const { from, to } = e.state.selection;
      if (from !== to) {
        const text = e.state.doc.textBetween(from, to, "\n");
        setSelectedText(text);
        setSelectionRange({ from, to });
      } else {
        setSelectedText("");
        setSelectionRange(null);
      }
    },
  });

  // Initialize editor content when doc loads, switches, or reloads after edit
  useEffect(() => {
    if (!editor || doc?.content === undefined) return;
    const docChanged = loadedDocIdRef.current !== docId;
    if (docChanged || !contentInitializedRef.current || pendingReloadRef.current) {
      suppressUpdateRef.current = true;
      editor.commands.setContent(doc.content || "");
      suppressUpdateRef.current = false;
      setIsDirty(false);
      contentInitializedRef.current = true;
      pendingReloadRef.current = false;
      loadedDocIdRef.current = docId;
    }
  }, [editor, doc, docId]);

  // Auto-save with 2s debounce
  useEffect(() => {
    if (!isDirty || !contentInitializedRef.current || !editor) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      try {
        if (editor.isDestroyed) return;
        const md = editor.storage.markdown.getMarkdown();
        saveMut.mutate({ content: md });
      } catch {}
    }, 2000);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
  }, [isDirty, editor]);

  // Live typewriter: append streaming chunks (generate) or replace selection (edit)
  useEffect(() => {
    if (!activeGeneration || !editor) return;
    const isEdit = activeGeneration.mode === "edit_selection";

    if (activeGeneration.status === "streaming") {
      if (activeGeneration.chunks.length === 1) {
        preGenContentRef.current = editor.storage.markdown.getMarkdown();
      }
      if (!activeGeneration.fullText) return;

      if (isEdit && editSelectionRef.current) {
        const base = preGenContentRef.current;
        const combined = base.replace(editSelectionRef.current, activeGeneration.fullText);
        suppressUpdateRef.current = true;
        editor.commands.setContent(combined);
        suppressUpdateRef.current = false;
      } else if (!isEdit) {
        const base = preGenContentRef.current;
        const combined = base ? base + "\n\n" + activeGeneration.fullText : activeGeneration.fullText;
        suppressUpdateRef.current = true;
        editor.commands.setContent(combined);
        suppressUpdateRef.current = false;
      }
    }
    if (activeGeneration.status === "complete") {
      if (isEdit) {
        editSelectionRef.current = "";
        pendingReloadRef.current = true;
        clearGeneration();
        queryClient.invalidateQueries({ queryKey: ["doc", docId] });
        return;
      }
      if (!activeGeneration.fullText) {
        clearGeneration();
        return;
      }
      const base = preGenContentRef.current;
      const final = base ? base + "\n\n" + activeGeneration.fullText : activeGeneration.fullText;
      suppressUpdateRef.current = true;
      editor.commands.setContent(final);
      suppressUpdateRef.current = false;
      saveMut.mutate({ content: final });
      clearGeneration();
    }
  }, [activeGeneration?.fullText, activeGeneration?.status]);

  // Destroy editor on unmount to prevent stale DOM + duplicate extension errors
  useEffect(() => {
    return () => {
      try { if (editor && !editor.isDestroyed) editor.destroy(); } catch {}
    };
  }, [editor]);

  // Feature 2: Image upload handler
  const handleImageUpload = useCallback(async (file: File) => {
    if (!editor) return;
    try {
      const result = await api.docs.uploadImage(docId, file);
      editor.chain().focus().setImage({ src: result.url, alt: file.name }).run();
      setIsDirty(true);
    } catch (err) {
      console.error("Image upload failed:", err);
    }
  }, [editor, docId]);

  // Keyboard shortcuts
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (isDirty && editor) {
          const md = editor.storage.markdown.getMarkdown();
          saveMut.mutate({ content: md });
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "/") {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "e" && selectedText) {
        e.preventDefault();
        editSelectionRef.current = selectedText;
        setCommandPaletteOpen(true);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isDirty, commandPaletteOpen, editor, selectedText]);

  const handleSave = useCallback(() => {
    if (editor) {
      const md = editor.storage.markdown.getMarkdown();
      saveMut.mutate({ content: md });
    }
  }, [editor]);

  // Feature 3: Save to Memory handler
  const handleSaveToMemory = useCallback(() => {
    if (isDirty && editor) {
      const md = editor.storage.markdown.getMarkdown();
      saveMut.mutate({ content: md });
    }
    saveToMemoryMut.mutate();
  }, [isDirty, editor, docId]);

  if (isLoading || !editor) {
    return <div className="flex-1 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>;
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        <h2 className="text-sm font-semibold truncate flex-1">{doc?.title || "Untitled"}</h2>
        {saveMut.isPending && <Badge variant="warning" className="text-[9px] animate-pulse">Saving...</Badge>}
        {!isDirty && !saveMut.isPending && contentInitializedRef.current && <Badge variant="success" className="text-[9px]">Saved</Badge>}
        {isDirty && !saveMut.isPending && <Badge variant="outline" className="text-[9px]">Unsaved</Badge>}
        {doc?.tags?.map((tag: string) => <Badge key={tag} variant="secondary" className="text-[9px]">{tag}</Badge>)}
        <Button variant="outline" size="sm" className="h-7 gap-1 text-primary border-primary/30" onClick={() => setCommandPaletteOpen(true)}>
          <Sparkles className="w-3 h-3" />
          AI Generate
          <span className="text-[9px] text-muted-foreground ml-1">⌘/</span>
        </Button>
        {selectedText && (
          <Button variant="outline" size="sm" className="h-7 gap-1 text-amber-400 border-amber-400/30"
            onClick={() => { editSelectionRef.current = selectedText; setCommandPaletteOpen(true); }}>
            <Sparkles className="w-3 h-3" />
            AI Edit Selection
            <span className="text-[9px] text-muted-foreground ml-1">⌘E</span>
          </Button>
        )}
        <Button variant="ghost" size="sm" className="h-7 gap-1" disabled={!isDirty || saveMut.isPending} onClick={handleSave}>
          {saveMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
          Save
        </Button>
        <Button variant="ghost" size="sm" className="h-7 gap-1" onClick={handleSaveToMemory}
          disabled={saveToMemoryMut.isPending}>
          {saveToMemoryMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
          Save to Memory
        </Button>
        {saveToMemoryResult && (
          <Badge variant="success" className="text-[9px]">{saveToMemoryResult}</Badge>
        )}
      </div>

      {/* Tiptap Editor — Typora-style WYSIWYG */}
      <div className="flex-1 overflow-y-auto">
        <SafeEditorContent editor={editor} />
      </div>

      <GenerationOverlay />
      {commandPaletteOpen && (
        <CommandPalette
          docId={docId}
          onClose={() => { setCommandPaletteOpen(false); }}
          selectedText={selectedText}
          selectionRange={selectionRange}
        />
      )}
    </div>
  );
}

// ---------- DocEditor (main) ----------
export function DocEditor() {
  const activeDocId = useDocStore((s) => s.activeDocId);

  return (
    <div className="flex h-full overflow-hidden">
      <DocSidebar />
      {activeDocId ? <DocEditorPane docId={activeDocId} /> : <EmptyDocState />}
    </div>
  );
}
