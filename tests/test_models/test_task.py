"""Tests for task models."""

from nightshift.models.task import Task, TaskPriority, TaskStatus


def test_task_priority_ordering():
    assert TaskPriority.HIGH == "high"
    assert TaskPriority.MEDIUM == "medium"
    assert TaskPriority.LOW == "low"


def test_task_status_values():
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.PASSED == "passed"
    assert TaskStatus.FAILED == "failed"
    assert TaskStatus.SKIPPED == "skipped"


def test_task_defaults():
    task = Task(
        id="t1",
        title="Test task",
        source_type="yaml",
        project_path="/tmp/proj",
    )
    assert task.priority == TaskPriority.MEDIUM
    assert task.scope == []
    assert task.constraints == []
    assert task.estimated_minutes == 30
    assert task.intent is None


def test_task_full(sample_task):
    assert sample_task.id == "test-remove-dead-code"
    assert sample_task.priority == TaskPriority.MEDIUM
    assert len(sample_task.scope) == 1
    assert len(sample_task.constraints) == 1


def test_task_roundtrip():
    task = Task(
        id="t1",
        title="Fix bug",
        source_type="github",
        source_ref="https://github.com/user/repo/issues/42",
        project_path="/tmp/proj",
        priority=TaskPriority.HIGH,
        intent="Fix the null pointer exception",
        scope=["src/main.py"],
        constraints=["Don't change the API"],
    )
    data = task.model_dump()
    restored = Task.model_validate(data)
    assert restored == task
