"""Tests for nightshift.executor.runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nightshift.executor.runner import execute_run
from nightshift.models.config import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ProjectRef,
    ScheduleConfig,
    SourceConfig,
)
from nightshift.models.task import QueuedTask, TaskPriority, TaskStatus
from nightshift.storage import task_queue


def _make_queued_task(task_id: str, title: str, project_path: str) -> QueuedTask:
    return QueuedTask(
        id=task_id,
        title=title,
        source_type="yaml",
        project_path=project_path,
        priority=TaskPriority.MEDIUM,
        intent=f"Do {title}",
    )


def _make_global_config(tmp_path: Path, *, max_prs: int = 10) -> GlobalConfig:
    return GlobalConfig(
        schedule=ScheduleConfig(time="03:00", timezone="UTC"),
        projects=[ProjectRef(path=tmp_path, sources=["yaml"])],
        max_prs_per_night=max_prs,
    )


@pytest.mark.asyncio
async def test_max_prs_limit_stops_execution(tmp_path: Path, monkeypatch) -> None:
    """With max_prs_per_night=1, only the first task should get a PR; the rest are skipped."""
    # Set up local queue with 3 tasks
    monkeypatch.setattr(task_queue, "TASKS_FILE", tmp_path / "tasks.yaml")
    proj = str(tmp_path)
    for i in range(3):
        task_queue.add_task(_make_queued_task(f"task-{i}", f"Task {i}", proj))

    global_config = _make_global_config(tmp_path, max_prs=1)

    project_config = ProjectConfig(
        sources=[SourceConfig(type="yaml")],
        limits=ProjectLimits(max_tasks_per_run=10),
    )

    with (
        patch("nightshift.executor.runner.load_project_config", return_value=project_config),
        patch("nightshift.executor.runner.prepare_repo"),
        patch("nightshift.executor.runner.create_branch", return_value=("nightshift/task-0", False)),
        patch("nightshift.executor.runner.run_baseline_tests", return_value=(True, 5, 0)),
        patch("nightshift.executor.runner.build_prompt", return_value="prompt"),
        patch("nightshift.executor.runner.invoke_claude", return_value=(True, "ok")),
        patch("nightshift.executor.runner.autofix_and_commit", return_value=False),
        patch("nightshift.executor.git_ops.get_diff_stats", return_value=(2, 10, 3)),
        patch("nightshift.executor.runner.run_all_gates", return_value=(True, "All gates passed")),
        patch("nightshift.executor.runner.push_branch"),
        patch("nightshift.executor.runner.create_pr", return_value=("https://github.com/pr/1", 1)),
        patch("nightshift.executor.git_ops._run"),
    ):
        result = await execute_run(global_config, project_path=tmp_path)

    statuses = [r.status for r in result.task_results]
    assert statuses.count(TaskStatus.PASSED) == 1
    assert statuses.count(TaskStatus.SKIPPED) == 2

    skipped = [r for r in result.task_results if r.status == TaskStatus.SKIPPED]
    for r in skipped:
        assert r.error == "max_prs_per_night limit reached"


@pytest.mark.asyncio
async def test_max_prs_default_allows_ten() -> None:
    """The default max_prs_per_night should be 10."""
    config = GlobalConfig()
    assert config.max_prs_per_night == 10
