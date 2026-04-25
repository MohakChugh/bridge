"""Variable resolver — evaluate expressions and substitute {{var}} placeholders.

Supports:
  - Static strings: returned as-is
  - Date expressions: today, yesterday, tomorrow, today-Nd, today+Nd,
    start_of_week, end_of_week, start_of_month, end_of_month,
    last_monday..last_sunday, next_monday..next_sunday, now
  - Number expressions: evaluated as Python literals
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta


WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def resolve_variables(variables: list[dict], overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    resolved = {}
    for var in variables:
        name = var.get("name", "")
        if not name:
            continue
        if name in overrides and overrides[name] is not None and overrides[name] != "":
            val = overrides[name]
            if var.get("type") == "date" and _is_expression(str(val)):
                val = evaluate_expression(str(val), "date")
            resolved[name] = str(val)
        else:
            default = var.get("default", "")
            resolved[name] = evaluate_expression(str(default), var.get("type", "string"))
    return resolved


def evaluate_expression(expr: str, var_type: str = "string") -> str:
    expr = expr.strip()
    if not expr:
        return ""

    if var_type == "date" or _is_expression(expr):
        result = _eval_date(expr)
        if result is not None:
            return result

    if var_type == "number":
        try:
            return str(int(expr)) if "." not in expr else str(float(expr))
        except ValueError:
            pass

    return expr


def substitute_variables(text: str, resolved: dict) -> str:
    def replacer(match: re.Match) -> str:
        name = match.group(1).strip()
        return resolved.get(name, match.group(0))
    return re.sub(r"\{\{(\s*\w+\s*)\}\}", replacer, text)


def _is_expression(s: str) -> bool:
    s_lower = s.lower().strip()
    keywords = [
        "today", "yesterday", "tomorrow", "now",
        "start_of_week", "end_of_week", "start_of_month", "end_of_month",
        "last_", "next_",
    ]
    return any(s_lower.startswith(k) or s_lower == k for k in keywords)


def _eval_date(expr: str) -> str | None:
    expr = expr.strip().lower()
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if expr == "now":
        return now.strftime("%Y-%m-%d %H:%M:%S")
    if expr == "today":
        return today.strftime("%Y-%m-%d")
    if expr == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if expr == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # today - Nd, today + Nd
    m = re.match(r"today\s*([+-])\s*(\d+)\s*d?", expr)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        days = int(m.group(2))
        return (today + timedelta(days=sign * days)).strftime("%Y-%m-%d")

    # now - Nd, now + Nd
    m = re.match(r"now\s*([+-])\s*(\d+)\s*d?", expr)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        days = int(m.group(2))
        return (now + timedelta(days=sign * days)).strftime("%Y-%m-%d %H:%M:%S")

    # start_of_week, end_of_week
    if expr == "start_of_week":
        return (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    if expr == "end_of_week":
        return (today + timedelta(days=6 - today.weekday())).strftime("%Y-%m-%d")

    # start_of_month, end_of_month
    if expr == "start_of_month":
        return today.replace(day=1).strftime("%Y-%m-%d")
    if expr == "end_of_month":
        if today.month == 12:
            last = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        return last.strftime("%Y-%m-%d")

    # last_tuesday, next_friday, etc.
    m = re.match(r"(last|next)_(\w+)", expr)
    if m:
        direction = m.group(1)
        day_name = m.group(2)
        target_wd = WEEKDAYS.get(day_name)
        if target_wd is not None:
            current_wd = today.weekday()
            if direction == "last":
                diff = (current_wd - target_wd) % 7
                if diff == 0:
                    diff = 7
                return (today - timedelta(days=diff)).strftime("%Y-%m-%d")
            else:
                diff = (target_wd - current_wd) % 7
                if diff == 0:
                    diff = 7
                return (today + timedelta(days=diff)).strftime("%Y-%m-%d")

    return None
