"""Parser for NightShift task queue (tasks.yaml)."""

from datetime import datetime, timedelta
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


def schedule_tasks(tasks: list[dict], start_time: datetime) -> list[dict]:
    """Schedule pending tasks into 30-minute slots sorted by priority."""
    pending = filter_by_status(tasks, "pending")
    pending.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority", "low"), 99))
    schedule = []
    current = start_time
    for t in pending:
        end = current + timedelta(minutes=30)
        schedule.append({
            "task_id": t["id"],
            "title": t["title"],
            "priority": t.get("priority", "low"),
            "start_time": current,
            "end_time": end,
        })
        current = end
    return schedule


def format_schedule(schedule: list[dict]) -> str:
    """Format a schedule into a readable string."""
    lines = []
    for entry in schedule:
        start = entry["start_time"].strftime("%H:%M")
        end = entry["end_time"].strftime("%H:%M")
        lines.append(f"[{start} - {end}] {entry['title']} ({entry['priority']})")
    return "\n".join(lines)
