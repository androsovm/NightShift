"""Tests for nightshift tasks CLI subcommands."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from nightshift.cli.app import app
from nightshift.models.task import QueuedTask, TaskAttempt, TaskPriority, TaskStatus
from nightshift.storage import task_queue

runner = CliRunner()


def _make_task(task_id: str = "test-task", **kwargs) -> QueuedTask:
    defaults = dict(
        id=task_id,
        title=f"Task {task_id}",
        source_type="manual",
        project_path="/tmp/project",
        priority=TaskPriority.MEDIUM,
    )
    defaults.update(kwargs)
    return QueuedTask(**defaults)


@pytest.fixture(autouse=True)
def _use_tmp_tasks_file(tmp_path, monkeypatch):
    monkeypatch.setattr(task_queue, "TASKS_FILE", tmp_path / "tasks.yaml")


class TestTasksList:
    def test_empty_queue(self):
        result = runner.invoke(app, ["tasks", "list"])
        assert result.exit_code == 0
        assert "No tasks" in result.output

    def test_shows_tasks(self):
        task_queue.save_tasks([_make_task("t1"), _make_task("t2")])
        result = runner.invoke(app, ["tasks", "list"])
        assert result.exit_code == 0
        assert "t1" in result.output
        assert "t2" in result.output
        assert "2 task(s)" in result.output

    def test_filter_by_status(self):
        task_queue.save_tasks([
            _make_task("t1", status=TaskStatus.PENDING),
            _make_task("t2", status=TaskStatus.PASSED),
        ])
        result = runner.invoke(app, ["tasks", "list", "--status", "pending"])
        assert result.exit_code == 0
        assert "t1" in result.output
        assert "t2" not in result.output

    def test_filter_by_priority(self):
        task_queue.save_tasks([
            _make_task("high-task", priority=TaskPriority.HIGH),
            _make_task("low-task", priority=TaskPriority.LOW),
        ])
        result = runner.invoke(app, ["tasks", "list", "--priority", "high"])
        assert result.exit_code == 0
        assert "high-task" in result.output
        assert "low-task" not in result.output


class TestTasksRemove:
    def test_remove_with_yes(self):
        task_queue.save_tasks([_make_task("t1")])
        result = runner.invoke(app, ["tasks", "remove", "t1", "--yes"])
        assert result.exit_code == 0
        assert "Removed" in result.output
        assert task_queue.load_tasks() == []

    def test_remove_not_found(self):
        result = runner.invoke(app, ["tasks", "remove", "nonexistent", "--yes"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestTasksPrioritize:
    def test_change_priority(self):
        task_queue.save_tasks([_make_task("t1", priority=TaskPriority.LOW)])
        result = runner.invoke(app, ["tasks", "prioritize", "t1", "high"])
        assert result.exit_code == 0
        assert "high" in result.output
        assert task_queue.get_task("t1").priority == TaskPriority.HIGH

    def test_prioritize_not_found(self):
        result = runner.invoke(app, ["tasks", "prioritize", "nonexistent", "high"])
        assert result.exit_code == 1


class TestTasksSkip:
    def test_skip(self):
        task_queue.save_tasks([_make_task("t1")])
        result = runner.invoke(app, ["tasks", "skip", "t1"])
        assert result.exit_code == 0
        assert "Skipped" in result.output
        assert task_queue.get_task("t1").status == TaskStatus.SKIPPED


class TestTasksRequeue:
    def test_requeue(self):
        task_queue.save_tasks([_make_task("t1", status=TaskStatus.FAILED)])
        result = runner.invoke(app, ["tasks", "requeue", "t1"])
        assert result.exit_code == 0
        assert "Requeued" in result.output
        assert task_queue.get_task("t1").status == TaskStatus.PENDING


class TestTasksHistory:
    def test_no_attempts(self):
        task_queue.save_tasks([_make_task("t1")])
        result = runner.invoke(app, ["tasks", "history", "t1"])
        assert result.exit_code == 0
        assert "No execution attempts" in result.output

    def test_with_attempts(self):
        task = _make_task("t1")
        task.attempts = [
            TaskAttempt(
                timestamp=datetime(2026, 3, 21, 2, 0, tzinfo=timezone.utc),
                status=TaskStatus.FAILED,
                run_id="20260321-020000",
                branch="nightshift/t1-20260321",
                error="Quality gates failed",
                duration_seconds=120.0,
            ),
            TaskAttempt(
                timestamp=datetime(2026, 3, 22, 2, 0, tzinfo=timezone.utc),
                status=TaskStatus.PASSED,
                run_id="20260322-020000",
                branch="nightshift/t1-20260322",
                pr_url="https://github.com/pr/1",
                duration_seconds=90.0,
            ),
        ]
        task_queue.save_tasks([task])
        result = runner.invoke(app, ["tasks", "history", "t1"])
        assert result.exit_code == 0
        assert "failed" in result.output
        assert "passed" in result.output
        assert "Quality gates" in result.output or "Quality" in result.output

    def test_history_not_found(self):
        result = runner.invoke(app, ["tasks", "history", "nonexistent"])
        assert result.exit_code == 1


class TestTasksEdit:
    def test_edit_with_flags(self):
        task_queue.save_tasks([_make_task("t1", title="Old title")])
        result = runner.invoke(app, ["tasks", "edit", "t1", "--title", "New title", "--priority", "high"])
        assert result.exit_code == 0
        assert "Updated" in result.output
        task = task_queue.get_task("t1")
        assert task.title == "New title"
        assert task.priority == TaskPriority.HIGH

    def test_edit_not_found(self):
        result = runner.invoke(app, ["tasks", "edit", "nonexistent", "--title", "X"])
        assert result.exit_code == 1


class TestRunnerRecordsAttempts:
    """Verify the runner writes attempt history to the queue."""

    @pytest.mark.asyncio
    async def test_attempt_recorded_on_success(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from nightshift.executor.runner import execute_run
        from nightshift.models.config import (
            GlobalConfig,
            ProjectConfig,
            ProjectLimits,
            ProjectRef,
            ScheduleConfig,
            SourceConfig,
        )

        proj = str(tmp_path)
        task_queue.add_task(_make_task("t1", project_path=proj))

        global_config = GlobalConfig(
            schedule=ScheduleConfig(time="02:00", timezone="UTC"),
            projects=[ProjectRef(path=tmp_path, sources=["yaml"])],
        )
        project_config = ProjectConfig(
            sources=[SourceConfig(type="yaml")],
            limits=ProjectLimits(max_tasks_per_run=5),
        )

        with (
            patch("nightshift.executor.runner.load_project_config", return_value=project_config),
            patch("nightshift.executor.runner.prepare_repo"),
            patch("nightshift.executor.runner.create_branch", return_value=("nightshift/t1", False)),
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
            run_result = await execute_run(global_config, project_path=tmp_path)

        # Check run result
        assert len(run_result.task_results) == 1
        assert run_result.task_results[0].status == TaskStatus.PASSED

        # Check attempt was recorded in the queue
        task = task_queue.get_task("t1")
        assert task.status == TaskStatus.PASSED
        assert len(task.attempts) == 1
        assert task.attempts[0].pr_url == "https://github.com/pr/1"

    @pytest.mark.asyncio
    async def test_attempt_recorded_on_failure(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from nightshift.executor.runner import execute_run
        from nightshift.models.config import (
            GlobalConfig,
            ProjectConfig,
            ProjectLimits,
            ProjectRef,
            ScheduleConfig,
            SourceConfig,
        )

        proj = str(tmp_path)
        task_queue.add_task(_make_task("t1", project_path=proj))

        global_config = GlobalConfig(
            schedule=ScheduleConfig(time="02:00", timezone="UTC"),
            projects=[ProjectRef(path=tmp_path, sources=["yaml"])],
        )
        project_config = ProjectConfig(
            sources=[SourceConfig(type="yaml")],
            limits=ProjectLimits(max_tasks_per_run=5),
        )

        with (
            patch("nightshift.executor.runner.load_project_config", return_value=project_config),
            patch("nightshift.executor.runner.prepare_repo"),
            patch("nightshift.executor.runner.create_branch", return_value=("nightshift/t1", False)),
            patch("nightshift.executor.runner.run_baseline_tests", return_value=(True, 5, 0)),
            patch("nightshift.executor.runner.build_prompt", return_value="prompt"),
            patch("nightshift.executor.runner.invoke_claude", return_value=(False, "Claude failed")),
            patch("nightshift.executor.runner.cleanup_branch"),
            patch("nightshift.executor.git_ops._run"),
        ):
            run_result = await execute_run(global_config, project_path=tmp_path)

        assert run_result.task_results[0].status == TaskStatus.FAILED

        task = task_queue.get_task("t1")
        assert task.status == TaskStatus.FAILED
        assert len(task.attempts) == 1
        assert "Claude" in task.attempts[0].error
