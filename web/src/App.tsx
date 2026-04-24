import { useEventStream } from "@/api/ws";
import { useSessionStore } from "@/stores/sessionStore";
import { Sidebar } from "@/components/Sidebar";
import { Dashboard } from "@/components/Dashboard";
import { ChatView } from "@/components/ChatView";
import { RemindersList, SchedulesList, WatchesList } from "@/components/SimpleList";

export default function App() {
  useEventStream();
  const { view } = useSessionStore();

  return (
    <div className="h-full flex">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        {view === "dashboard" && <Dashboard />}
        {view === "chat" && <ChatView />}
        {view === "reminders" && <RemindersList />}
        {view === "schedules" && <SchedulesList />}
        {view === "watches" && <WatchesList />}
      </main>
    </div>
  );
}
