import { useEventStream } from "@/api/ws";
import { useSessionStore } from "@/stores/sessionStore";
import { Sidebar } from "@/components/Sidebar";
import { Dashboard } from "@/components/Dashboard";
import { ChatView } from "@/components/ChatView";
import { RemindersList, SchedulesList, WatchesList } from "@/components/SimpleList";
import { WorkflowList } from "@/components/WorkflowList";
import { WorkflowEditor } from "@/components/WorkflowEditor";
import { WorkflowRunner } from "@/components/WorkflowRunner";

export default function App() {
  useEventStream();
  const { view } = useSessionStore();

  return (
    <div className="h-full flex">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        {view === "dashboard" && <Dashboard />}
        {view === "chat" && <ChatView />}
        {view === "workflows" && <WorkflowList />}
        {view === "workflow-editor" && <WorkflowEditor />}
        {view === "workflow-runner" && <WorkflowRunner />}
        {view === "reminders" && <RemindersList />}
        {view === "schedules" && <SchedulesList />}
        {view === "watches" && <WatchesList />}
      </main>
    </div>
  );
}
