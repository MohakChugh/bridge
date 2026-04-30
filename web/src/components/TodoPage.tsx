import { useState, useRef, useEffect } from "react";
import {
  CheckCircle2, Circle, Plus, Trash2, ListTodo,
  ArrowUp, ArrowDown, Minus,
} from "lucide-react";
import { Button, Badge, Input } from "@/components/ui";
import { useTodoStore, type Todo } from "@/stores/todoStore";

const PRIORITY_COLORS = {
  high: "text-red-400 bg-red-500/10 border-red-500/30",
  medium: "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  low: "text-blue-400 bg-blue-500/10 border-blue-500/30",
};

const PRIORITY_ICONS = {
  high: ArrowUp,
  medium: Minus,
  low: ArrowDown,
};

function TodoItem({ todo }: { todo: Todo }) {
  const { toggleTodo, removeTodo, updateTodo, setPriority } = useTodoStore();
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(todo.text);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.focus();
  }, [editing]);

  const PriorityIcon = PRIORITY_ICONS[todo.priority];
  const nextPriority: Record<string, Todo["priority"]> = { high: "medium", medium: "low", low: "high" };

  const age = Date.now() - todo.createdAt;
  const ageStr = age < 3600000 ? `${Math.floor(age / 60000)}m` :
    age < 86400000 ? `${Math.floor(age / 3600000)}h` : `${Math.floor(age / 86400000)}d`;

  return (
    <div className={`group flex items-start gap-3 px-4 py-3 rounded-lg border transition-all ${
      todo.done ? "bg-accent/30 border-border/30 opacity-60" : "bg-card border-border hover:border-primary/30"
    }`}>
      <button onClick={() => toggleTodo(todo.id)} className="mt-0.5 shrink-0">
        {todo.done ? (
          <CheckCircle2 className="w-5 h-5 text-green-400" />
        ) : (
          <Circle className="w-5 h-5 text-muted-foreground hover:text-primary transition-colors" />
        )}
      </button>

      <div className="flex-1 min-w-0">
        {editing ? (
          <input ref={inputRef} value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { updateTodo(todo.id, editText); setEditing(false); }
              if (e.key === "Escape") { setEditText(todo.text); setEditing(false); }
            }}
            onBlur={() => { updateTodo(todo.id, editText); setEditing(false); }}
            className="w-full bg-transparent text-sm border-b border-primary/50 focus:outline-none py-0.5"
          />
        ) : (
          <p className={`text-sm cursor-pointer ${todo.done ? "line-through text-muted-foreground" : ""}`}
            onClick={() => setEditing(true)}>
            {todo.text}
          </p>
        )}
        <div className="flex items-center gap-2 mt-1">
          <button onClick={() => setPriority(todo.id, nextPriority[todo.priority])}
            className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${PRIORITY_COLORS[todo.priority]} hover:opacity-80 transition-opacity`}>
            <PriorityIcon className="w-2.5 h-2.5" />
            {todo.priority}
          </button>
          <span className="text-[10px] text-muted-foreground">{ageStr} ago</span>
          {todo.done && todo.completedAt && (
            <Badge variant="success" className="text-[9px] px-1 py-0">done</Badge>
          )}
        </div>
      </div>

      <button onClick={() => removeTodo(todo.id)}
        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-1 p-1 rounded hover:bg-destructive/20">
        <Trash2 className="w-3.5 h-3.5 text-destructive" />
      </button>
    </div>
  );
}

export function TodoPage() {
  const { todos, filter, addTodo, setFilter, clearCompleted } = useTodoStore();
  const [input, setInput] = useState("");
  const [priority, setPriority] = useState<Todo["priority"]>("medium");
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = todos.filter((t) =>
    filter === "all" ? true : filter === "active" ? !t.done : t.done,
  );

  const activeCount = todos.filter((t) => !t.done).length;
  const doneCount = todos.filter((t) => t.done).length;

  const handleAdd = () => {
    if (!input.trim()) return;
    addTodo(input.trim(), priority);
    setInput("");
    setPriority("medium");
    inputRef.current?.focus();
  };

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-2xl mx-auto py-8 px-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <ListTodo className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold">Todos</h1>
              <p className="text-xs text-muted-foreground">
                {activeCount} active · {doneCount} done
              </p>
            </div>
          </div>
          {doneCount > 0 && (
            <Button variant="ghost" size="sm" className="text-xs" onClick={clearCompleted}>
              Clear completed
            </Button>
          )}
        </div>

        {/* Add todo */}
        <div className="flex gap-2 mb-6">
          <div className="flex-1 flex gap-2">
            <Input ref={inputRef} value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              placeholder="What needs to be done?"
              className="flex-1"
            />
            <button onClick={() => {
              const next: Record<string, Todo["priority"]> = { high: "medium", medium: "low", low: "high" };
              setPriority(next[priority]);
            }}
              className={`flex items-center gap-1 text-xs px-3 rounded-md border ${PRIORITY_COLORS[priority]} shrink-0`}>
              {(() => { const I = PRIORITY_ICONS[priority]; return <I className="w-3 h-3" />; })()}
              {priority}
            </button>
          </div>
          <Button onClick={handleAdd} disabled={!input.trim()}>
            <Plus className="w-4 h-4 mr-1" /> Add
          </Button>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 mb-4 p-0.5 rounded-lg bg-accent/50 w-fit">
          {(["all", "active", "done"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 text-xs rounded-md transition-colors capitalize ${
                filter === f ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}>
              {f} {f === "all" ? `(${todos.length})` : f === "active" ? `(${activeCount})` : `(${doneCount})`}
            </button>
          ))}
        </div>

        {/* Todo list */}
        <div className="space-y-2">
          {filtered.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <ListTodo className="w-10 h-10 mx-auto mb-3 opacity-20" />
              <p className="text-sm">
                {filter === "all" ? "No todos yet. Add one above." :
                  filter === "active" ? "All done! Nothing active." : "No completed todos."}
              </p>
            </div>
          )}
          {filtered.map((todo) => (
            <TodoItem key={todo.id} todo={todo} />
          ))}
        </div>
      </div>
    </div>
  );
}
