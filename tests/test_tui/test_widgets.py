"""Tests for TUI widget data logic (no rendering, pure data)."""

from datetime import datetime, timezone
from pathlib import Path

from nightshift.models.config import ProjectRef
from nightshift.models.run import RunResult, TaskResult
from nightshift.models.task import QueuedTask, TaskPriority, TaskStatus
from nightshift.tui.widgets.run_history_panel import _format_duration, _sparkline


class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(45) == "45s"

    def test_minutes(self):
        assert _format_duration(150) == "2m"

    def test_hours(self):
        assert _format_duration(3700) == "1h1m"

    def test_zero(self):
        assert _format_duration(0) == "0s"


class TestSparkline:
    def test_empty(self):
        assert _sparkline([]) == ""

    def test_single_value(self):
        result = _sparkline([50.0])
        assert len(result) == 1

    def test_multiple_values(self):
        result = _sparkline([0, 25, 50, 75, 100])
        assert len(result) == 5

    def test_all_zeros(self):
        result = _sparkline([0, 0, 0])
        assert len(result) == 3

    def test_width_limit(self):
        values = list(range(20))
        result = _sparkline(values, width=5)
        assert len(result) == 5


class TestTaskQueueFingerprint:
    def test_same_tasks_same_fingerprint(self):
        from nightshift.tui.widgets.task_queue_panel import TaskQueuePanel

        tasks = [
            QueuedTask(id="a", title="A", source_type="yaml", project_path="/p"),
            QueuedTask(id="b", title="B", source_type="yaml", project_path="/p"),
        ]
        fp1 = TaskQueuePanel._make_fingerprint(tasks)
        fp2 = TaskQueuePanel._make_fingerprint(tasks)
        assert fp1 == fp2

    def test_different_tasks_different_fingerprint(self):
        from nightshift.tui.widgets.task_queue_panel import TaskQueuePanel

        tasks1 = [QueuedTask(id="a", title="A", source_type="yaml", project_path="/p")]
        tasks2 = [QueuedTask(id="b", title="B", source_type="yaml", project_path="/p")]
        assert TaskQueuePanel._make_fingerprint(tasks1) != TaskQueuePanel._make_fingerprint(tasks2)

    def test_status_change_changes_fingerprint(self):
        from nightshift.tui.widgets.task_queue_panel import TaskQueuePanel

        t1 = [QueuedTask(id="a", title="A", source_type="yaml", project_path="/p", status=TaskStatus.PENDING)]
        t2 = [QueuedTask(id="a", title="A", source_type="yaml", project_path="/p", status=TaskStatus.RUNNING)]
        assert TaskQueuePanel._make_fingerprint(t1) != TaskQueuePanel._make_fingerprint(t2)

    def test_empty_list(self):
        from nightshift.tui.widgets.task_queue_panel import TaskQueuePanel

        assert TaskQueuePanel._make_fingerprint([]) == ""


class TestRunHistoryFingerprint:
    def test_same_runs_same_fingerprint(self):
        from nightshift.tui.widgets.run_history_panel import RunHistoryPanel

        runs = [RunResult(run_id="run-1"), RunResult(run_id="run-2")]
        fp1 = RunHistoryPanel._make_fingerprint(runs)
        fp2 = RunHistoryPanel._make_fingerprint(runs)
        assert fp1 == fp2

    def test_different_runs_different_fingerprint(self):
        from nightshift.tui.widgets.run_history_panel import RunHistoryPanel

        r1 = [RunResult(run_id="run-1")]
        r2 = [RunResult(run_id="run-2")]
        assert RunHistoryPanel._make_fingerprint(r1) != RunHistoryPanel._make_fingerprint(r2)
