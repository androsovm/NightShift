"""Tests for nightshift sync command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nightshift.cli.sync_cmd import _content_changed, _do_sync
from nightshift.models.config import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ProjectRef,
    ScheduleConfig,
    SourceConfig,
)
from nightshift.models.task import QueuedTask, Task, TaskPriority, TaskStatus
from nightshift.storage import task_queue


def _make_task(task_id: str, title: str, project_path: str = "/tmp/proj") -> Task:
    return Task(
        id=task_id,
        title=title,
        source_type="youtrack",
        source_ref=f"https://yt.com/issue/{task_id}",
        project_path=project_path,
        priority=TaskPriority.MEDIUM,
        intent=f"Do {title}",
    )


def _make_global_config(tmp_path) -> GlobalConfig:
    return GlobalConfig(
        schedule=ScheduleConfig(time="02:00", timezone="UTC"),
        projects=[ProjectRef(path=tmp_path, sources=["youtrack"])],
    )


def _make_project_config() -> ProjectConfig:
    return ProjectConfig(
        sources=[SourceConfig(type="youtrack", base_url="https://yt.com", project_id="PROJ")],
        limits=ProjectLimits(),
    )


@pytest.fixture(autouse=True)
def _use_tmp_tasks_file(tmp_path, monkeypatch):
    monkeypatch.setattr(task_queue, "TASKS_FILE", tmp_path / "tasks.yaml")


class TestContentChanged:
    def test_same_content(self):
        a = QueuedTask(id="t1", title="Fix bug", source_type="yt", project_path="/p", intent="Do it")
        b = QueuedTask(id="t1", title="Fix bug", source_type="yt", project_path="/p", intent="Do it")
        assert _content_changed(a, b) is False

    def test_title_changed(self):
        a = QueuedTask(id="t1", title="Fix bug", source_type="yt", project_path="/p")
        b = QueuedTask(id="t1", title="Fix bug v2", source_type="yt", project_path="/p")
        assert _content_changed(a, b) is True

    def test_intent_changed(self):
        a = QueuedTask(id="t1", title="X", source_type="yt", project_path="/p", intent="old")
        b = QueuedTask(id="t1", title="X", source_type="yt", project_path="/p", intent="new")
        assert _content_changed(a, b) is True

    def test_priority_changed(self):
        a = QueuedTask(id="t1", title="X", source_type="yt", project_path="/p", priority=TaskPriority.LOW)
        b = QueuedTask(id="t1", title="X", source_type="yt", project_path="/p", priority=TaskPriority.HIGH)
        assert _content_changed(a, b) is True


class TestSyncAddsNewTasks:
    @pytest.mark.asyncio
    async def test_adds_fetched_tasks(self, tmp_path):
        tasks = [_make_task("PROJ-1", "Fix auth"), _make_task("PROJ-2", "Add logging")]

        mock_adapter = MagicMock()
        mock_adapter.return_value = MagicMock(
            fetch_tasks=AsyncMock(return_value=tasks),
        )

        with (
            patch("nightshift.cli.sync_cmd.load_global_config", return_value=_make_global_config(tmp_path)),
            patch("nightshift.cli.sync_cmd.load_project_config", return_value=_make_project_config()),
            patch("nightshift.cli.sync_cmd.ADAPTERS", {"youtrack": mock_adapter}),
        ):
            await _do_sync(project_filter=None)

        loaded = task_queue.load_tasks()
        assert len(loaded) == 2
        assert loaded[0].title == "Fix auth"
        assert loaded[1].title == "Add logging"
        assert loaded[0].source_type == "youtrack"
        assert loaded[0].status == TaskStatus.PENDING


class TestSyncDedup:
    @pytest.mark.asyncio
    async def test_skips_existing_same_content(self, tmp_path):
        """Sync twice with same tasks — second run adds nothing."""
        tasks = [_make_task("PROJ-1", "Fix auth")]

        mock_adapter = MagicMock()
        mock_adapter.return_value = MagicMock(
            fetch_tasks=AsyncMock(return_value=tasks),
        )

        with (
            patch("nightshift.cli.sync_cmd.load_global_config", return_value=_make_global_config(tmp_path)),
            patch("nightshift.cli.sync_cmd.load_project_config", return_value=_make_project_config()),
            patch("nightshift.cli.sync_cmd.ADAPTERS", {"youtrack": mock_adapter}),
        ):
            await _do_sync(project_filter=None)
            await _do_sync(project_filter=None)

        loaded = task_queue.load_tasks()
        assert len(loaded) == 1

    @pytest.mark.asyncio
    async def test_no_source_ref_duplicate_id_prevented(self, tmp_path):
        """Tasks with duplicate IDs are rejected by add_task even without source_ref."""
        task = Task(
            id="manual-1",
            title="Manual task",
            source_type="manual",
            source_ref=None,
            project_path=str(tmp_path),
        )

        mock_adapter = MagicMock()
        mock_adapter.return_value = MagicMock(
            fetch_tasks=AsyncMock(return_value=[task]),
        )

        with (
            patch("nightshift.cli.sync_cmd.load_global_config", return_value=_make_global_config(tmp_path)),
            patch("nightshift.cli.sync_cmd.load_project_config", return_value=_make_project_config()),
            patch("nightshift.cli.sync_cmd.ADAPTERS", {"youtrack": mock_adapter}),
        ):
            await _do_sync(project_filter=None)
            await _do_sync(project_filter=None)

        loaded = task_queue.load_tasks()
        assert len(loaded) == 1


class TestSyncProjectFilter:
    @pytest.mark.asyncio
    async def test_unknown_project_exits(self, tmp_path):
        from click.exceptions import Exit

        with (
            patch("nightshift.cli.sync_cmd.load_global_config", return_value=_make_global_config(tmp_path)),
            pytest.raises(Exit),
        ):
            await _do_sync(project_filter="nonexistent-project")


class TestSyncFetchError:
    @pytest.mark.asyncio
    async def test_continues_on_fetch_error(self, tmp_path):
        """Sync should continue if one source adapter fails."""
        mock_adapter = MagicMock()
        mock_adapter.return_value = MagicMock(
            fetch_tasks=AsyncMock(side_effect=RuntimeError("API error")),
        )

        with (
            patch("nightshift.cli.sync_cmd.load_global_config", return_value=_make_global_config(tmp_path)),
            patch("nightshift.cli.sync_cmd.load_project_config", return_value=_make_project_config()),
            patch("nightshift.cli.sync_cmd.ADAPTERS", {"youtrack": mock_adapter}),
        ):
            await _do_sync(project_filter=None)  # should not raise

        assert task_queue.load_tasks() == []
