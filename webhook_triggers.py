"""Event-driven triggers — webhooks that fire workflows or sessions on matching events.

Examples:
- "When pipeline fails → auto-diagnose"
- "When CR approved → notify me"
- "When watch alerts → spawn investigation workflow"
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

TRIGGERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "triggers.json")

_instance: Optional[TriggerManager] = None
_lock = threading.Lock()


def get_trigger_manager() -> TriggerManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = TriggerManager()
    return _instance


class Trigger:
    def __init__(self, data: dict):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", "")
        self.event_pattern: str = data.get("event_pattern", "")
        self.data_filter: dict = data.get("data_filter", {})
        self.action: str = data.get("action", "session")
        self.action_config: dict = data.get("action_config", {})
        self.enabled: bool = data.get("enabled", True)
        self.fire_count: int = data.get("fire_count", 0)
        self.last_fired: Optional[float] = data.get("last_fired")
        self.cooldown_seconds: int = data.get("cooldown_seconds", 60)
        self.created_at: float = data.get("created_at", time.time())

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "event_pattern": self.event_pattern,
            "data_filter": self.data_filter,
            "action": self.action, "action_config": self.action_config,
            "enabled": self.enabled, "fire_count": self.fire_count,
            "last_fired": self.last_fired, "cooldown_seconds": self.cooldown_seconds,
            "created_at": self.created_at,
        }

    def matches(self, event_type: str, event_data: dict) -> bool:
        if not self.enabled:
            return False
        if self.last_fired and (time.time() - self.last_fired) < self.cooldown_seconds:
            return False
        if not re.match(self.event_pattern, event_type):
            return False
        for key, expected in self.data_filter.items():
            actual = event_data.get(key)
            if isinstance(expected, str) and expected.startswith("regex:"):
                if not actual or not re.search(expected[6:], str(actual)):
                    return False
            elif actual != expected:
                return False
        return True


class TriggerManager:
    def __init__(self):
        self._triggers: list[Trigger] = []
        self._lock = threading.RLock()
        self._bus_sub_id: Optional[str] = None
        self._session_manager = None
        self._workflow_engine = None
        self._config = None
        self._load()

    def _load(self):
        if os.path.exists(TRIGGERS_FILE):
            try:
                with open(TRIGGERS_FILE, "r") as f:
                    data = json.load(f)
                self._triggers = [Trigger(t) for t in data]
                log.info("Loaded %d triggers", len(self._triggers))
            except Exception as e:
                log.warning("Failed to load triggers: %s", e)

    def _save(self):
        try:
            with open(TRIGGERS_FILE, "w") as f:
                json.dump([t.to_dict() for t in self._triggers], f, indent=2)
        except Exception as e:
            log.warning("Failed to save triggers: %s", e)

    def start(self, session_manager, workflow_engine, config_provider):
        self._session_manager = session_manager
        self._workflow_engine = workflow_engine
        self._config = config_provider

        from event_bus import get_event_bus
        bus = get_event_bus()
        self._bus_sub_id = bus.subscribe()

        thread = threading.Thread(target=self._event_loop, args=(bus,), daemon=True, name="trigger-mgr")
        thread.start()
        log.info("Trigger manager started with %d triggers", len(self._triggers))

    def _event_loop(self, bus):
        while True:
            try:
                event = bus.get(self._bus_sub_id, timeout=5)
                if event:
                    self._check_triggers(event)
            except Exception:
                pass

    def _check_triggers(self, event: dict):
        event_type = event.get("type", "")
        event_data = event.get("data", {})

        for trigger in self._triggers:
            if trigger.matches(event_type, event_data):
                log.info("Trigger '%s' fired on event '%s'", trigger.name, event_type)
                trigger.fire_count += 1
                trigger.last_fired = time.time()
                self._save()
                threading.Thread(
                    target=self._execute_action,
                    args=(trigger, event_type, event_data),
                    daemon=True,
                ).start()

    def _execute_action(self, trigger: Trigger, event_type: str, event_data: dict):
        try:
            config = self._config() if callable(self._config) else self._config
            action = trigger.action
            ac = trigger.action_config

            if action == "session" and self._session_manager:
                prompt = ac.get("prompt", f"Triggered by {event_type}: {json.dumps(event_data)[:500]}")
                tool = ac.get("tool", config.get("cli_tool", "wasabi"))
                cwd = ac.get("cwd", config.get("directories", {}).get("default", "/tmp"))
                s = self._session_manager.create(tool=tool, cwd=cwd, title=f"Trigger: {trigger.name}")
                self._session_manager.execute(s.id, prompt)

            elif action == "workflow" and self._workflow_engine:
                wf_id = ac.get("workflow_id")
                if wf_id:
                    from workflow_store import load_workflows
                    wfs = load_workflows()
                    wf = next((w for w in wfs if w["id"] == wf_id), None)
                    if wf:
                        params = ac.get("params", {})
                        params["_trigger_event"] = event_type
                        params["_trigger_data"] = json.dumps(event_data)[:500]
                        self._workflow_engine.run(wf, params=params)

            elif action == "notify":
                from sender import send_imessage
                msg = ac.get("message", f"Trigger fired: {trigger.name} on {event_type}")
                send_imessage(msg, config.get("reply_chat_guid", ""))

            from event_bus import get_event_bus
            get_event_bus().publish("trigger.fired", {
                "trigger_id": trigger.id, "trigger_name": trigger.name,
                "event_type": event_type, "action": action,
            })
        except Exception as e:
            log.error("Trigger action failed for '%s': %s", trigger.name, e)

    # ---- CRUD ----

    def add(self, name: str, event_pattern: str, action: str = "session",
            action_config: Optional[dict] = None, data_filter: Optional[dict] = None,
            cooldown_seconds: int = 60) -> Trigger:
        import uuid
        t = Trigger({
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "event_pattern": event_pattern,
            "data_filter": data_filter or {},
            "action": action,
            "action_config": action_config or {},
            "cooldown_seconds": cooldown_seconds,
            "created_at": time.time(),
        })
        with self._lock:
            self._triggers.append(t)
            self._save()
        log.info("Added trigger '%s' matching '%s'", name, event_pattern)
        return t

    def remove(self, trigger_id: str) -> bool:
        with self._lock:
            before = len(self._triggers)
            self._triggers = [t for t in self._triggers if t.id != trigger_id]
            if len(self._triggers) < before:
                self._save()
                return True
        return False

    def list_all(self) -> list[dict]:
        return [t.to_dict() for t in self._triggers]

    def toggle(self, trigger_id: str, enabled: bool) -> bool:
        with self._lock:
            for t in self._triggers:
                if t.id == trigger_id:
                    t.enabled = enabled
                    self._save()
                    return True
        return False
