import { useSessionStore } from "@/stores/sessionStore";
import { cn } from "@/lib/utils";
import { LayoutDashboard, MessageSquare, Bell, Calendar, Eye, Zap, GitBranch, Activity, History } from "lucide-react";

const items = [
  { view: "dashboard" as const, label: "Dashboard", icon: LayoutDashboard },
  { view: "operations" as const, label: "Operations", icon: Activity },
  { view: "chat" as const, label: "Chat", icon: MessageSquare },
  { view: "sessions" as const, label: "Sessions", icon: History },
  { view: "workflows" as const, label: "Workflows", icon: GitBranch },
  { view: "reminders" as const, label: "Reminders", icon: Bell },
  { view: "schedules" as const, label: "Schedules", icon: Calendar },
  { view: "watches" as const, label: "Watches", icon: Eye },
];

export function Sidebar() {
  const { view, setView } = useSessionStore();
  return (
    <aside className="w-52 shrink-0 border-r border-border bg-card/30 flex flex-col">
      <div className="px-4 h-14 flex items-center gap-2 border-b border-border">
        <div className="w-7 h-7 rounded bg-primary/20 flex items-center justify-center">
          <Zap className="w-4 h-4 text-primary" />
        </div>
        <span className="font-semibold tracking-tight">Bridge</span>
      </div>
      <nav className="p-2 space-y-0.5">
        {items.map((item) => {
          const Icon = item.icon;
          const active = view === item.view;
          return (
            <button
              key={item.view}
              onClick={() => setView(item.view)}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
                active
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <Icon className="w-4 h-4" />
              {item.label}
            </button>
          );
        })}
      </nav>
      <div className="mt-auto p-4 text-[10px] text-muted-foreground border-t border-border">
        localhost:7777
      </div>
    </aside>
  );
}
