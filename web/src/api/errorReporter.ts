const DEBOUNCE_MS = 5_000;
const CIRCUIT_BREAKER_THRESHOLD = 5;
const CIRCUIT_BREAKER_PAUSE_MS = 60_000;

const recentMessages = new Map<string, number>();
let consecutiveFailures = 0;
let circuitOpenUntil = 0;

export function reportError(
  level: string,
  message: string,
  component?: string,
  stack?: string,
  userAction?: string,
): void {
  const now = Date.now();

  // Debounce: skip if identical message reported within last 5s
  const lastTime = recentMessages.get(message);
  if (lastTime !== undefined && now - lastTime < DEBOUNCE_MS) {
    return;
  }

  // Circuit breaker: pause if too many consecutive failures
  if (now < circuitOpenUntil) {
    return;
  }

  recentMessages.set(message, now);

  fetch("/api/logs/frontend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      level,
      message,
      component,
      stack,
      user_action: userAction,
      url: window.location.href,
      timestamp: Date.now() / 1000,
    }),
  })
    .then(() => {
      consecutiveFailures = 0;
    })
    .catch(() => {
      consecutiveFailures++;
      if (consecutiveFailures >= CIRCUIT_BREAKER_THRESHOLD) {
        circuitOpenUntil = Date.now() + CIRCUIT_BREAKER_PAUSE_MS;
        consecutiveFailures = 0;
      }
    });
}

export function initErrorReporter(): void {
  window.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    const message = reason instanceof Error ? reason.message : String(reason);
    const stack = reason instanceof Error ? reason.stack : undefined;
    reportError("error", message, "unhandledrejection", stack);
  });

  window.addEventListener("error", (event: ErrorEvent) => {
    reportError(
      "error",
      event.message,
      "uncaughterror",
      event.error?.stack,
    );
  });
}
