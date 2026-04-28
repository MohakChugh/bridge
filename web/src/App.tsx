import { Component, type ErrorInfo, type ReactNode } from "react";
import { useEventStream } from "@/api/ws";
import { useSessionStore } from "@/stores/sessionStore";
import { Sidebar } from "@/components/Sidebar";
import { Dashboard } from "@/components/Dashboard";
import { ChatView } from "@/components/ChatView";
import { RemindersList, SchedulesList, WatchesList } from "@/components/SimpleList";
import { WorkflowList } from "@/components/WorkflowList";
import { WorkflowAnalytics } from "@/components/WorkflowAnalytics";
import { SettingsPage } from "@/components/SettingsPage";
import { MemoryBrowser } from "@/components/MemoryBrowser";
import { WorkflowEditor } from "@/components/WorkflowEditor";
import { WorkflowRunner } from "@/components/WorkflowRunner";
import { OperationsDashboard } from "@/components/OperationsDashboard";
import { RagChatOverlay } from "@/components/RagChatOverlay";
import { LogViewer } from "@/components/LogViewer";
import { CodeReview } from "@/components/CodeReview";
import { DocEditor } from "@/components/DocEditor";
import { AgentView } from "@/components/AgentView";
import CalendarPage from "@/components/CalendarPage";
import { TodoPage } from "@/components/TodoPage";

/* ------------------------------------------------------------------ */
/*  Error Boundary – catches uncaught render errors so the whole app  */
/*  doesn't white-screen.                                             */
/* ------------------------------------------------------------------ */
interface ErrorBoundaryProps {
  children: ReactNode;
}
interface ErrorBoundaryState {
  hasError: boolean;
}

class ErrorBoundary extends Component<ErrorBoundaryProps & { resetKey?: string }, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps & { resetKey?: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps & { resetKey?: string }) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
    try {
      import("@/api/errorReporter").then(({ reportError }) => {
        reportError("ERROR", error.message, "ErrorBoundary", error.stack || "", "render");
      });
    } catch {}
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-4 text-zinc-400">
          <p className="text-lg font-medium">Something went wrong</p>
          <button
            className="px-4 py-2 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-sm"
            onClick={() => this.setState({ hasError: false })}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/* ------------------------------------------------------------------ */
/*  View resolver – returns the component for the current view,       */
/*  falling back to Dashboard for any unknown/invalid value.          */
/* ------------------------------------------------------------------ */
function ErrorBoundaryWrapper() {
  const { view } = useSessionStore();
  return (
    <ErrorBoundary resetKey={view}>
      <ViewContent />
    </ErrorBoundary>
  );
}

function ViewContent() {
  const { view } = useSessionStore();

  switch (view) {
    case "dashboard":          return <Dashboard />;
    case "operations":         return <OperationsDashboard />;
    case "chat":               return <ChatView />;
    case "workflows":          return <WorkflowList />;
    case "workflow-editor":    return <WorkflowEditor />;
    case "workflow-runner":    return <WorkflowRunner />;
    case "workflow-analytics": return <WorkflowAnalytics />;
    case "reminders":          return <RemindersList />;
    case "schedules":          return <SchedulesList />;
    case "watches":            return <WatchesList />;
    case "memory":             return <MemoryBrowser />;
    case "settings":           return <SettingsPage />;
    case "logs":               return <LogViewer />;
    case "code-review":        return <CodeReview />;
    case "docs":               return <DocEditor />;
    case "agent":              return <AgentView />;
    case "calendar":           return <CalendarPage />;
    case "todos":              return <TodoPage />;
    default:                   return <Dashboard />;
  }
}

export default function App() {
  useEventStream();

  return (
    <div className="h-full flex">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <ErrorBoundaryWrapper />
      </main>
      <RagChatOverlay />
    </div>
  );
}
