"""Tests for adding/removing built-in tasks via templates."""

from pathlib import Path

import pytest

from nightshift.models.task import QueuedTask, TaskPriority, TaskStatus
from nightshift.storage.task_queue import (
    TASKS_FILE,
    add_task,
    find_by_source_ref,
    load_tasks,
    remove_task,
    save_tasks,
)
from nightshift.tui.task_templates import TEMPLATE_BY_KEY


@pytest.fixture(autouse=True)
def _clean_tasks(tmp_path, monkeypatch):
    """Redirect task queue to tmp_path so tests don't touch real data."""
    tasks_file = tmp_path / "tasks.yaml"
    monkeypatch.setattr("nightshift.storage.task_queue.TASKS_FILE", tasks_file)
    yield


class TestBuiltinTaskCreation:
    def test_create_task_from_template(self):
        tmpl = TEMPLATE_BY_KEY["docs"]
        task = QueuedTask(
            id="docs-myproject",
            title=f"{tmpl.title} (myproject)",
            source_type="builtin",
            source_ref="builtin:docs:myproject",
            project_path="/tmp/myproject",
            priority=TaskPriority(tmpl.priority),
            intent=tmpl.intent,
            scope=list(tmpl.scope),
            constraints=list(tmpl.constraints),
            estimated_minutes=tmpl.estimated_minutes,
        )
        add_task(task)

        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "docs-myproject"
        assert tasks[0].source_type == "builtin"
        assert tasks[0].intent == tmpl.intent
        assert tasks[0].scope == tmpl.scope
        assert tasks[0].constraints == tmpl.constraints

    def test_dedup_by_source_ref(self):
        tmpl = TEMPLATE_BY_KEY["tests"]
        task = QueuedTask(
            id="tests-proj",
            title=f"{tmpl.title} (proj)",
            source_type="builtin",
            source_ref="builtin:tests:proj",
            project_path="/tmp/proj",
            priority=TaskPriority(tmpl.priority),
            intent=tmpl.intent,
        )
        add_task(task)

        existing = find_by_source_ref("builtin", "builtin:tests:proj")
        assert existing is not None
        assert existing.id == "tests-proj"

    def test_remove_builtin_task(self):
        task = QueuedTask(
            id="lint-proj",
            title="Fix linter warnings (proj)",
            source_type="builtin",
            source_ref="builtin:lint:proj",
            project_path="/tmp/proj",
        )
        add_task(task)
        assert len(load_tasks()) == 1

        removed = remove_task("lint-proj")
        assert removed is True
        assert len(load_tasks()) == 0

    def test_remove_nonexistent_task(self):
        removed = remove_task("does-not-exist")
        assert removed is False

    def test_multiple_templates_for_same_project(self):
        for key in ["docs", "tests", "lint"]:
            tmpl = TEMPLATE_BY_KEY[key]
            task = QueuedTask(
                id=f"{key}-proj",
                title=f"{tmpl.title} (proj)",
                source_type="builtin",
                source_ref=f"builtin:{key}:proj",
                project_path="/tmp/proj",
                priority=TaskPriority(tmpl.priority),
                intent=tmpl.intent,
            )
            add_task(task)

        tasks = load_tasks()
        assert len(tasks) == 3
        ids = {t.id for t in tasks}
        assert ids == {"docs-proj", "tests-proj", "lint-proj"}

    def test_same_template_different_projects(self):
        tmpl = TEMPLATE_BY_KEY["security"]
        for name in ["proj-a", "proj-b"]:
            task = QueuedTask(
                id=f"security-{name}",
                title=f"{tmpl.title} ({name})",
                source_type="builtin",
                source_ref=f"builtin:security:{name}",
                project_path=f"/tmp/{name}",
                priority=TaskPriority(tmpl.priority),
                intent=tmpl.intent,
            )
            add_task(task)

        tasks = load_tasks()
        assert len(tasks) == 2

    def test_builtin_task_has_model_field(self):
        tmpl = TEMPLATE_BY_KEY["docs"]
        task = QueuedTask(
            id="docs-proj",
            title="Update docs",
            source_type="builtin",
            source_ref="builtin:docs:proj",
            project_path="/tmp/proj",
            model="claude-opus-4-6",
        )
        add_task(task)

        loaded = load_tasks()
        assert loaded[0].model == "claude-opus-4-6"
