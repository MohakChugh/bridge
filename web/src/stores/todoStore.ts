import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface Todo {
  id: string;
  text: string;
  done: boolean;
  priority: "low" | "medium" | "high";
  createdAt: number;
  completedAt?: number;
}

interface TodoStore {
  todos: Todo[];
  filter: "all" | "active" | "done";

  addTodo: (text: string, priority?: Todo["priority"]) => void;
  toggleTodo: (id: string) => void;
  removeTodo: (id: string) => void;
  updateTodo: (id: string, text: string) => void;
  setPriority: (id: string, priority: Todo["priority"]) => void;
  setFilter: (filter: TodoStore["filter"]) => void;
  clearCompleted: () => void;
  reorder: (fromIndex: number, toIndex: number) => void;
}

export const useTodoStore = create<TodoStore>()(
  persist(
    (set) => ({
      todos: [],
      filter: "all",

      addTodo: (text, priority = "medium") =>
        set((s) => ({
          todos: [
            { id: crypto.randomUUID(), text, done: false, priority, createdAt: Date.now() },
            ...s.todos,
          ],
        })),

      toggleTodo: (id) =>
        set((s) => ({
          todos: s.todos.map((t) =>
            t.id === id ? { ...t, done: !t.done, completedAt: !t.done ? Date.now() : undefined } : t,
          ),
        })),

      removeTodo: (id) =>
        set((s) => ({ todos: s.todos.filter((t) => t.id !== id) })),

      updateTodo: (id, text) =>
        set((s) => ({
          todos: s.todos.map((t) => (t.id === id ? { ...t, text } : t)),
        })),

      setPriority: (id, priority) =>
        set((s) => ({
          todos: s.todos.map((t) => (t.id === id ? { ...t, priority } : t)),
        })),

      setFilter: (filter) => set({ filter }),

      clearCompleted: () =>
        set((s) => ({ todos: s.todos.filter((t) => !t.done) })),

      reorder: (fromIndex, toIndex) =>
        set((s) => {
          const todos = [...s.todos];
          const [moved] = todos.splice(fromIndex, 1);
          todos.splice(toIndex, 0, moved);
          return { todos };
        }),
    }),
    {
      name: "bridge-todo-store",
      partialize: (s) => ({ todos: s.todos, filter: s.filter }),
    },
  ),
);
