"""Local task queue persistence — ~/.nightshift/tasks.yaml."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import structlog
import yaml

from nightshift.models.task import (
    QueuedTask,
    TaskAttempt,
    TaskCategory,
    TaskFrequency,
    TaskPriority,
    TaskStatus,
)

log = structlog.get_logger(__name__)

TASKS_FILE = Path.home() / ".nightshift" / "tasks.yaml"
RUN_PID_FILE = Path.home() / ".nightshift" / "run.pid"

_PRIORITY_ORDER = {
    TaskPriority.HIGH: 0,
    TaskPriority.MEDIUM: 1,
    TaskPriority.LOW: 2,
}


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def load_tasks() -> list[QueuedTask]:
    """Read all tasks from the queue file."""
    if not TASKS_FILE.exists():
        return []
    raw = TASKS_FILE.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = yaml.safe_load(raw)
    if not data or "tasks" not in data:
        return []
    tasks: list[QueuedTask] = []
    for entry in data["tasks"]:
        try:
            tasks.append(QueuedTask.model_validate(entry))
        except Exception:
            log.warning("task_queue.invalid_entry", entry_id=entry.get("id"))
            continue
    return tasks


def save_tasks(tasks: list[QueuedTask]) -> None:
    """Atomically write all tasks to the queue file."""
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"tasks": [t.model_dump(mode="json") for t in tasks]}
    # Atomic write: temp file + rename
    fd, tmp_path = tempfile.mkstemp(
        dir=TASKS_FILE.parent, suffix=".tmp", prefix="tasks_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, TASKS_FILE)
    except BaseException:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def get_task(task_id: str) -> QueuedTask | None:
    """Find a task by ID."""
    for t in load_tasks():
        if t.id == task_id:
            return t
    return None


def add_task(task: QueuedTask) -> None:
    """Append a task to the queue."""
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    log.info("task_queue.added", task_id=task.id, title=task.title)


def update_task(task_id: str, **fields: object) -> QueuedTask | None:
    """Update fields on a task. Returns the updated task or None if not found."""
    tasks = load_tasks()
    for i, t in enumerate(tasks):
        if t.id == task_id:
            updated = t.model_copy(update=fields)
            tasks[i] = updated
            save_tasks(tasks)
            log.info("task_queue.updated", task_id=task_id, fields=list(fields.keys()))
            return updated
    return None


def remove_task(task_id: str) -> bool:
    """Remove a task by ID. Returns True if found and removed."""
    tasks = load_tasks()
    before = len(tasks)
    tasks = [t for t in tasks if t.id != task_id]
    if len(tasks) == before:
        return False
    save_tasks(tasks)
    log.info("task_queue.removed", task_id=task_id)
    return True


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def find_by_source_ref(source_type: str, source_ref: str) -> QueuedTask | None:
    """Find an existing task by source origin (for dedup)."""
    for t in load_tasks():
        if t.source_type == source_type and t.source_ref == source_ref:
            return t
    return None


def deactivate_task(task_id: str) -> QueuedTask | None:
    """Move a task to the INACTIVE category."""
    return update_task(task_id, category=TaskCategory.INACTIVE)


def activate_task(task_id: str) -> QueuedTask | None:
    """Move a task back to ACTIVE and reset to PENDING."""
    return update_task(task_id, category=TaskCategory.ACTIVE, status=TaskStatus.PENDING)


def requeue_recurring_builtins() -> int:
    """Requeue recurring built-in tasks whose interval has elapsed.

    Only requeues PASSED/DONE tasks (not FAILED). Returns count requeued.
    """
    from datetime import datetime, timezone

    tasks = load_tasks()
    now = datetime.now(tz=timezone.utc)
    requeued = 0
    for i, t in enumerate(tasks):
        if t.category != TaskCategory.BUILTIN:
            continue
        if t.frequency in (None, TaskFrequency.ONCE):
            continue
        if t.status not in (TaskStatus.PASSED, TaskStatus.DONE):
            continue
        if t.last_completed_at is None:
            continue
        days = (now - t.last_completed_at).days
        threshold = 7 if t.frequency == TaskFrequency.WEEKLY else 30
        if days >= threshold:
            tasks[i] = t.model_copy(update={"status": TaskStatus.PENDING})
            requeued += 1
    if requeued:
        save_tasks(tasks)
        log.info("task_queue.requeued_recurring", count=requeued)
    return requeued


def write_run_pid() -> None:
    """Write current PID to the run lock file."""
    RUN_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def clear_run_pid() -> None:
    """Remove the run lock file."""
    RUN_PID_FILE.unlink(missing_ok=True)


def _is_runner_alive() -> bool:
    """Check if a runner process is still alive based on the PID file."""
    if not RUN_PID_FILE.exists():
        return False
    try:
        pid = int(RUN_PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)  # signal 0 = check existence
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def recover_stale_running() -> int:
    """Reset any stuck 'running' tasks back to 'pending'.

    This handles the case where the process was killed while a task was
    mid-execution and the status was never updated to a terminal state.
    Skips recovery if the runner process is still alive.
    Returns the number of tasks recovered.
    """
    if _is_runner_alive():
        return 0

    tasks = load_tasks()
    recovered = 0
    for i, t in enumerate(tasks):
        if t.status == TaskStatus.RUNNING:
            tasks[i] = t.model_copy(update={"status": TaskStatus.PENDING})
            recovered += 1
    if recovered:
        save_tasks(tasks)
        log.info("task_queue.recovered_stale", count=recovered)
    # Clean up stale PID file
    clear_run_pid()
    return recovered


def get_pending_tasks(project_path: str | None = None) -> list[QueuedTask]:
    """Return pending tasks sorted by priority (high first).

    Only returns ACTIVE and BUILTIN tasks — INACTIVE are excluded.
    """
    tasks = load_tasks()
    pending = [
        t for t in tasks
        if t.status == TaskStatus.PENDING
        and t.category in (TaskCategory.ACTIVE, TaskCategory.BUILTIN)
    ]
    if project_path is not None:
        pending = [t for t in pending if t.project_path == project_path]
    pending.sort(key=lambda t: _PRIORITY_ORDER.get(t.priority, 99))
    return pending


# ---------------------------------------------------------------------------
# Execution tracking
# ---------------------------------------------------------------------------


def record_attempt(task_id: str, attempt: TaskAttempt) -> QueuedTask | None:
    """Append an execution attempt and update the task status."""
    tasks = load_tasks()
    for i, t in enumerate(tasks):
        if t.id == task_id:
            t.attempts.append(attempt)
            t.status = attempt.status
            if attempt.status in (TaskStatus.PASSED, TaskStatus.DONE):
                t.last_completed_at = attempt.timestamp
            tasks[i] = t
            save_tasks(tasks)
            log.info(
                "task_queue.attempt_recorded",
                task_id=task_id,
                status=str(attempt.status),
                attempt_number=len(t.attempts),
            )
            return t
    return None
