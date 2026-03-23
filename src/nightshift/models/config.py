"""Configuration models."""

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    """Built-in source types.

    Third-party plugins can register additional source types via the
    ``nightshift.sources`` entry point group without modifying this enum.
    The adapter registry accepts any string key, not only members of this enum.
    """

    YAML = "yaml"
    GITHUB = "github"
    YOUTRACK = "youtrack"
    TRELLO = "trello"


class SourceConfig(BaseModel):
    """Configuration for a single task source.

    ``type`` is a free-form string so that third-party plugins can define
    their own source types.  Built-in types are listed in :class:`SourceType`.

    Source-specific options live in the ``options`` dict, keeping the model
    extensible without growing new top-level fields for every integration.
    Built-in fields (repo, labels, etc.) are kept for backward compatibility
    but new sources should use ``options``.
    """

    type: str
    options: dict[str, Any] = Field(default_factory=dict)

    # --- Built-in source fields (backward-compat) ---
    # GitHub
    repo: str | None = None
    labels: list[str] = Field(default_factory=lambda: ["nightshift"])
    # YouTrack
    base_url: str | None = None
    project_id: str | None = None
    tag: str = "nightshift"
    states: list[str] = Field(default_factory=list)
    # Trello
    board_id: str | None = None
    list_name: str = "NightShift Queue"


class ProjectLimits(BaseModel):
    max_tasks_per_run: int = 5
    task_timeout_minutes: int = 45
    max_files_changed: int = 20
    max_lines_changed: int = 500


# Models available in Claude Code CLI.
CLAUDE_MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
]
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


class ProjectConfig(BaseModel):
    """Per-project config stored in .nightshift.yaml."""

    sources: list[SourceConfig] = Field(default_factory=list)
    limits: ProjectLimits = Field(default_factory=ProjectLimits)
    claude_system_prompt: str | None = None
    default_model: str = DEFAULT_CLAUDE_MODEL
    tasks: list[dict] = Field(default_factory=list)


class ScheduleConfig(BaseModel):
    time: str = "04:00"
    timezone: str = "UTC"
    max_duration_hours: int = 4


class ProjectRef(BaseModel):
    path: Path
    sources: list[str] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    """Global config stored in ~/.nightshift/config.yaml."""

    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    projects: list[ProjectRef] = Field(default_factory=list)
    max_prs_per_night: int = 10
