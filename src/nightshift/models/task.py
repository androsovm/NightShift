"""Task models."""

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
