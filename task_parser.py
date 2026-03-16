"""Parser for NightShift task queue (tasks.yaml)."""

from pathlib import Path
from typing import Optional

import yaml

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def load_tasks(filepath: str = "tasks.yaml") -> list[dict]:
    """Load tasks from a YAML file."""
    path = Path(filepath)
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data or "tasks" not in data:
        return []
    return data["tasks"]


def filter_by_status(tasks: list[dict], status: str) -> list[dict]:
    """Filter tasks by status (pending/done)."""
    return [t for t in tasks if t.get("status") == status]


def next_task(tasks: list[dict]) -> Optional[dict]:
    """Return the next pending task by priority (high > medium > low)."""
    pending = filter_by_status(tasks, "pending")
    if not pending:
        return None
    pending.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority", "low"), 99))
    return pending[0]


def mark_done(tasks: list[dict], task_id: int) -> list[dict]:
    """Mark a task as done by its id."""
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = "done"
            break
    return tasks


def save_tasks(tasks: list[dict], filepath: str = "tasks.yaml") -> None:
    """Save tasks back to a YAML file."""
    with open(filepath, "w") as f:
        yaml.dump({"tasks": tasks}, f, default_flow_style=False, allow_unicode=True)
