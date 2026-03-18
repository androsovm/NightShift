"""Run result models."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class TaskResult(BaseModel):
    task_id: str
    task_title: str
    project_path: str
    status: str  # passed / failed / skipped
    branch: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
    log_file: str | None = None


class RunResult(BaseModel):
    run_id: str  # YYYYMMDD-HHMMSS
    started_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    finished_at: datetime | None = None
    task_results: list[TaskResult] = Field(default_factory=list)
