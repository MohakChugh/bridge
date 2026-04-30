"""Custom logging.Handler that writes to SQLite log store with correlation context."""

from __future__ import annotations

import json
import logging
import threading
import traceback

# ---------------------------------------------------------------------------
# Correlation context (thread-local)
# ---------------------------------------------------------------------------

_ctx = threading.local()


def set_correlation_id(cid: str) -> None:
    _ctx.correlation_id = cid


def get_correlation_id() -> str | None:
    return getattr(_ctx, "correlation_id", None)


def clear_correlation_id() -> None:
    _ctx.correlation_id = None


# ---------------------------------------------------------------------------
# SQLiteLogHandler
# ---------------------------------------------------------------------------

_WARNING_LEVEL = logging.WARNING


class SQLiteLogHandler(logging.Handler):
    """Logging handler that persists records to the SQLite log store."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp = record.created
            level = record.levelname
            logger_name = record.name
            message = record.getMessage()

            data = None
            if record.exc_info:
                try:
                    tb = "".join(traceback.format_exception(*record.exc_info))
                    data = json.dumps({"traceback": tb})
                except Exception:
                    pass

            correlation_id = get_correlation_id()

            # Deferred import to avoid circular dependency
            from log_store import get_log_store  # type: ignore[import-untyped]

            get_log_store().write_log(
                timestamp=timestamp,
                level=level,
                logger=logger_name,
                message=message,
                data=data,
                correlation_id=correlation_id,
            )

            # Publish WARNING+ entries to the event bus
            if record.levelno >= _WARNING_LEVEL:
                try:
                    from event_bus import get_event_bus

                    get_event_bus().publish(
                        "log.entry",
                        {
                            "level": level,
                            "logger": logger_name,
                            "message": message,
                            "correlation_id": correlation_id,
                        },
                    )
                except Exception:
                    pass
        except Exception:
            # NEVER let exceptions escape emit().
            # NEVER call logging functions here — infinite recursion.
            pass
