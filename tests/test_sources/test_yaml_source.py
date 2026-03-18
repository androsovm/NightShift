"""Tests for nightshift.sources.yaml_source."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nightshift.config.loader import PROJECT_CONFIG_NAME
from nightshift.models.config import SourceConfig, SourceType
from nightshift.models.task import Task, TaskPriority
from nightshift.sources.yaml_source import YAMLSource


@pytest.fixture
def source() -> YAMLSource:
    return YAMLSource()


@pytest.fixture
def source_config() -> SourceConfig:
    return SourceConfig(type=SourceType.YAML)


def _write_config(project: Path, data: dict) -> None:
    (project / PROJECT_CONFIG_NAME).write_text(
        yaml.dump(data, default_flow_style=False), encoding="utf-8"
    )


def _read_config(project: Path) -> dict:
    return yaml.safe_load(
        (project / PROJECT_CONFIG_NAME).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# fetch_tasks
# ---------------------------------------------------------------------------


class TestFetchTasks:
    @pytest.mark.asyncio
    async def test_returns_pending_tasks(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {
                "tasks": [
                    {"id": "t1", "title": "Fix bug", "status": "pending"},
                    {"id": "t2", "title": "Add feature", "status": "pending"},
                ]
            },
        )
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        assert len(tasks) == 2
        assert tasks[0].id == "t1"
        assert tasks[1].id == "t2"

    @pytest.mark.asyncio
    async def test_skips_non_pending(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {
                "tasks": [
                    {"id": "t1", "title": "Done task", "status": "done"},
                    {"id": "t2", "title": "Pending task", "status": "pending"},
                    {"id": "t3", "title": "Running", "status": "running"},
                ]
            },
        )
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        assert len(tasks) == 1
        assert tasks[0].id == "t2"

    @pytest.mark.asyncio
    async def test_default_status_is_pending(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {"tasks": [{"id": "t1", "title": "No status field"}]},
        )
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_generates_id_from_title_slug(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {"tasks": [{"title": "Fix the broken tests"}]},
        )
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        assert len(tasks) == 1
        assert tasks[0].id == "fix-the-broken-tests"

    @pytest.mark.asyncio
    async def test_priority_parsing(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {
                "tasks": [
                    {"id": "h", "title": "High", "priority": "high"},
                    {"id": "l", "title": "Low", "priority": "low"},
                    {"id": "bad", "title": "Bad", "priority": "urgent"},
                ]
            },
        )
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        by_id = {t.id: t for t in tasks}
        assert by_id["h"].priority == TaskPriority.HIGH
        assert by_id["l"].priority == TaskPriority.LOW
        assert by_id["bad"].priority == TaskPriority.MEDIUM  # fallback

    @pytest.mark.asyncio
    async def test_preserves_intent_scope_constraints(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {
                "tasks": [
                    {
                        "id": "t1",
                        "title": "Refactor",
                        "intent": "Simplify code",
                        "scope": ["src/main.py"],
                        "constraints": ["No breaking changes"],
                    }
                ]
            },
        )
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        t = tasks[0]
        assert t.intent == "Simplify code"
        assert t.scope == ["src/main.py"]
        assert t.constraints == ["No breaking changes"]

    @pytest.mark.asyncio
    async def test_missing_file_returns_empty(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        assert tasks == []

    @pytest.mark.asyncio
    async def test_no_tasks_section_returns_empty(
        self, source: YAMLSource, source_config: SourceConfig, tmp_path: Path
    ) -> None:
        _write_config(tmp_path, {"sources": [{"type": "yaml"}]})
        tasks = await source.fetch_tasks(str(tmp_path), source_config)
        assert tasks == []


# ---------------------------------------------------------------------------
# mark_done
# ---------------------------------------------------------------------------


class TestMarkDone:
    @pytest.mark.asyncio
    async def test_sets_status_and_pr_url(
        self, source: YAMLSource, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {
                "tasks": [
                    {"id": "t1", "title": "Task 1", "status": "pending"},
                ]
            },
        )
        task = Task(
            id="t1",
            title="Task 1",
            source_type="yaml",
            project_path=str(tmp_path),
        )
        await source.mark_done(task, "https://github.com/o/r/pull/42")

        data = _read_config(tmp_path)
        entry = data["tasks"][0]
        assert entry["status"] == "done"
        assert entry["pr_url"] == "https://github.com/o/r/pull/42"

    @pytest.mark.asyncio
    async def test_only_updates_matching_task(
        self, source: YAMLSource, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {
                "tasks": [
                    {"id": "t1", "title": "T1", "status": "pending"},
                    {"id": "t2", "title": "T2", "status": "pending"},
                ]
            },
        )
        task = Task(
            id="t2",
            title="T2",
            source_type="yaml",
            project_path=str(tmp_path),
        )
        await source.mark_done(task, "https://example.com/pull/1")

        data = _read_config(tmp_path)
        assert data["tasks"][0]["status"] == "pending"
        assert data["tasks"][1]["status"] == "done"

    @pytest.mark.asyncio
    async def test_nonexistent_task_is_noop(
        self, source: YAMLSource, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            {"tasks": [{"id": "t1", "title": "T1", "status": "pending"}]},
        )
        task = Task(
            id="nonexistent",
            title="Ghost",
            source_type="yaml",
            project_path=str(tmp_path),
        )
        await source.mark_done(task, "https://example.com/pull/99")

        data = _read_config(tmp_path)
        assert data["tasks"][0]["status"] == "pending"
