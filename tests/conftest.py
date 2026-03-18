"""Shared test fixtures."""

from pathlib import Path

import pytest

from nightshift.models.config import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ProjectRef,
    ScheduleConfig,
    SourceConfig,
    SourceType,
)
from nightshift.models.run import RunResult, TaskResult
from nightshift.models.task import Task, TaskPriority


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id="test-remove-dead-code",
        title="Remove dead code in utils.py",
        source_type="yaml",
        project_path="/tmp/test-project",
        priority=TaskPriority.MEDIUM,
        intent="Remove unused functions from utils.py",
        scope=["src/utils.py"],
        constraints=["Do not remove any exported functions"],
    )


@pytest.fixture
def sample_project_config() -> ProjectConfig:
    return ProjectConfig(
        sources=[SourceConfig(type=SourceType.YAML)],
        limits=ProjectLimits(max_tasks_per_run=3, task_timeout_minutes=30),
    )


@pytest.fixture
def sample_global_config(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(
        schedule=ScheduleConfig(time="03:00", timezone="America/New_York"),
        projects=[
            ProjectRef(path=tmp_path / "project1", sources=[SourceType.YAML]),
        ],
        max_prs_per_night=5,
    )


@pytest.fixture
def sample_run_result() -> RunResult:
    return RunResult(
        run_id="20260318-040000",
        task_results=[
            TaskResult(
                task_id="task-1",
                task_title="Fix imports",
                project_path="/tmp/proj",
                status="passed",
                branch="nightshift/fix-imports-20260318",
                pr_url="https://github.com/user/repo/pull/1",
                pr_number=1,
                files_changed=2,
                lines_added=5,
                lines_removed=3,
                duration_seconds=120.5,
            ),
            TaskResult(
                task_id="task-2",
                task_title="Remove dead code",
                project_path="/tmp/proj",
                status="failed",
                error="Tests regressed: 2 new failures",
                duration_seconds=180.0,
            ),
        ],
    )
