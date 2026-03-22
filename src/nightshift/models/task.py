"""Task models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DONE = "done"


class Task(BaseModel):
    id: str
    title: str
    source_type: str
    source_ref: str | None = None
    project_path: str
    priority: TaskPriority = TaskPriority.MEDIUM
    intent: str | None = None
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    estimated_minutes: int = 30
    model: str | None = None


class TaskAttempt(BaseModel):
    """Record of a single execution attempt."""

    timestamp: datetime
    status: TaskStatus
    run_id: str | None = None
    branch: str | None = None
    pr_url: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0


class QueuedTask(BaseModel):
    """A task in the local queue with execution history."""

    id: str
    title: str
    source_type: str
    source_ref: str | None = None
    project_path: str
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    intent: str | None = None
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    estimated_minutes: int = 30
    model: str | None = None
    added_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    attempts: list[TaskAttempt] = Field(default_factory=list)

    @classmethod
    def from_task(cls, task: Task) -> QueuedTask:
        """Convert a Task (from source adapter) into a QueuedTask."""
        return cls(
            id=task.id,
            title=task.title,
            source_type=task.source_type,
            source_ref=task.source_ref,
            project_path=task.project_path,
            priority=task.priority,
            intent=task.intent,
            scope=list(task.scope),
            constraints=list(task.constraints),
            estimated_minutes=task.estimated_minutes,
            model=task.model,
        )

    def to_task(self) -> Task:
        """Convert back to a Task for use with the executor."""
        return Task(
            id=self.id,
            title=self.title,
            source_type=self.source_type,
            source_ref=self.source_ref,
            project_path=self.project_path,
            priority=self.priority,
            intent=self.intent,
            scope=list(self.scope),
            constraints=list(self.constraints),
            estimated_minutes=self.estimated_minutes,
            model=self.model,
        )
