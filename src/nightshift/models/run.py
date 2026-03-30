"""Run result models."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class TaskResult(BaseModel):
    task_id: str
    task_title: str
    project_path: str
    status: str  # passed / failed / skipped
    model: str | None = None
    branch: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    duration_seconds: float = 0.0
    claude_cost_usd: float | None = None
    claude_duration_ms: int | None = None
    claude_api_duration_ms: int | None = None
    claude_num_turns: int | None = None
    claude_input_tokens: int | None = None
    claude_output_tokens: int | None = None
    claude_cache_creation_tokens: int | None = None
    claude_cache_read_tokens: int | None = None
    error: str | None = None
    log_file: str | None = None


class RunResult(BaseModel):
    run_id: str  # YYYYMMDD-HHMMSS
    started_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    finished_at: datetime | None = None
    task_results: list[TaskResult] = Field(default_factory=list)
