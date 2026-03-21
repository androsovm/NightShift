"""Tests for storage.task_queue — local task queue persistence."""

from datetime import datetime, timezone

import pytest

from nightshift.models.task import (
    QueuedTask,
    Task,
    TaskAttempt,
    TaskPriority,
    TaskStatus,
)
from nightshift.storage import task_queue


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


class TestLoadSave:
    def test_load_empty(self):
        assert task_queue.load_tasks() == []

    def test_save_and_load(self):
        tasks = [_make_task("a"), _make_task("b")]
        task_queue.save_tasks(tasks)
        loaded = task_queue.load_tasks()
        assert len(loaded) == 2
        assert loaded[0].id == "a"
        assert loaded[1].id == "b"

    def test_round_trip_preserves_fields(self):
        task = _make_task(
            "full",
            intent="Do the thing\nwith multiline",
            scope=["src/foo.py"],
            constraints=["no breaking changes"],
            source_ref="https://example.com/issue/1",
        )
        task_queue.save_tasks([task])
        loaded = task_queue.load_tasks()[0]
        assert loaded.intent == task.intent
        assert loaded.scope == task.scope
        assert loaded.constraints == task.constraints
        assert loaded.source_ref == task.source_ref


class TestGetTask:
    def test_found(self):
        task_queue.save_tasks([_make_task("x")])
        assert task_queue.get_task("x") is not None
        assert task_queue.get_task("x").id == "x"

    def test_not_found(self):
        task_queue.save_tasks([_make_task("x")])
        assert task_queue.get_task("y") is None


class TestAddTask:
    def test_add(self):
        task_queue.add_task(_make_task("first"))
        task_queue.add_task(_make_task("second"))
        assert len(task_queue.load_tasks()) == 2


class TestUpdateTask:
    def test_update_priority(self):
        task_queue.save_tasks([_make_task("t1")])
        updated = task_queue.update_task("t1", priority=TaskPriority.HIGH)
        assert updated is not None
        assert updated.priority == TaskPriority.HIGH
        assert task_queue.get_task("t1").priority == TaskPriority.HIGH

    def test_update_not_found(self):
        task_queue.save_tasks([_make_task("t1")])
        assert task_queue.update_task("missing", priority=TaskPriority.HIGH) is None


class TestRemoveTask:
    def test_remove(self):
        task_queue.save_tasks([_make_task("a"), _make_task("b")])
        assert task_queue.remove_task("a") is True
        assert len(task_queue.load_tasks()) == 1
        assert task_queue.load_tasks()[0].id == "b"

    def test_remove_not_found(self):
        task_queue.save_tasks([_make_task("a")])
        assert task_queue.remove_task("missing") is False
        assert len(task_queue.load_tasks()) == 1


class TestFindBySourceRef:
    def test_found(self):
        task = _make_task("yt-1", source_type="youtrack", source_ref="https://yt.com/issue/PROJ-1")
        task_queue.save_tasks([task])
        found = task_queue.find_by_source_ref("youtrack", "https://yt.com/issue/PROJ-1")
        assert found is not None
        assert found.id == "yt-1"

    def test_not_found_wrong_type(self):
        task = _make_task("yt-1", source_type="youtrack", source_ref="https://yt.com/issue/PROJ-1")
        task_queue.save_tasks([task])
        assert task_queue.find_by_source_ref("github", "https://yt.com/issue/PROJ-1") is None

    def test_not_found_wrong_ref(self):
        task = _make_task("yt-1", source_type="youtrack", source_ref="https://yt.com/issue/PROJ-1")
        task_queue.save_tasks([task])
        assert task_queue.find_by_source_ref("youtrack", "https://yt.com/issue/PROJ-2") is None


class TestGetPendingTasks:
    def test_filters_pending(self):
        tasks = [
            _make_task("a", status=TaskStatus.PENDING),
            _make_task("b", status=TaskStatus.PASSED),
            _make_task("c", status=TaskStatus.PENDING),
        ]
        task_queue.save_tasks(tasks)
        pending = task_queue.get_pending_tasks()
        assert len(pending) == 2

    def test_sorted_by_priority(self):
        tasks = [
            _make_task("low", priority=TaskPriority.LOW),
            _make_task("high", priority=TaskPriority.HIGH),
            _make_task("med", priority=TaskPriority.MEDIUM),
        ]
        task_queue.save_tasks(tasks)
        pending = task_queue.get_pending_tasks()
        assert [t.id for t in pending] == ["high", "med", "low"]

    def test_filter_by_project(self):
        tasks = [
            _make_task("a", project_path="/proj/A"),
            _make_task("b", project_path="/proj/B"),
        ]
        task_queue.save_tasks(tasks)
        assert len(task_queue.get_pending_tasks(project_path="/proj/A")) == 1


class TestRecordAttempt:
    def test_record_passed(self):
        task_queue.save_tasks([_make_task("t1")])
        attempt = TaskAttempt(
            timestamp=datetime.now(tz=timezone.utc),
            status=TaskStatus.PASSED,
            run_id="20260321-020000",
            branch="nightshift/t1-20260321",
            pr_url="https://github.com/pr/1",
        )
        updated = task_queue.record_attempt("t1", attempt)
        assert updated is not None
        assert updated.status == TaskStatus.PASSED
        assert len(updated.attempts) == 1
        assert updated.attempts[0].pr_url == "https://github.com/pr/1"

    def test_record_failed(self):
        task_queue.save_tasks([_make_task("t1")])
        attempt = TaskAttempt(
            timestamp=datetime.now(tz=timezone.utc),
            status=TaskStatus.FAILED,
            error="Quality gates failed",
        )
        updated = task_queue.record_attempt("t1", attempt)
        assert updated.status == TaskStatus.FAILED
        assert updated.attempts[0].error == "Quality gates failed"

    def test_multiple_attempts(self):
        task_queue.save_tasks([_make_task("t1")])
        for i in range(3):
            task_queue.record_attempt("t1", TaskAttempt(
                timestamp=datetime.now(tz=timezone.utc),
                status=TaskStatus.FAILED,
                error=f"attempt {i}",
            ))
        task = task_queue.get_task("t1")
        assert len(task.attempts) == 3

    def test_record_not_found(self):
        assert task_queue.record_attempt("missing", TaskAttempt(
            timestamp=datetime.now(tz=timezone.utc),
            status=TaskStatus.FAILED,
        )) is None


class TestFromTask:
    def test_converts_task_to_queued(self):
        task = Task(
            id="gh-123",
            title="Fix bug",
            source_type="github",
            source_ref="https://github.com/owner/repo/issues/123",
            project_path="/proj",
            priority=TaskPriority.HIGH,
            intent="Fix the bug",
            scope=["src/main.py"],
            constraints=["no new deps"],
        )
        qt = QueuedTask.from_task(task)
        assert qt.id == "gh-123"
        assert qt.source_type == "github"
        assert qt.priority == TaskPriority.HIGH
        assert qt.status == TaskStatus.PENDING
        assert qt.attempts == []
