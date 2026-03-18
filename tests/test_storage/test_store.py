"""Tests for storage/store.py run persistence."""

import time
from unittest.mock import patch

import pytest

from nightshift.models.run import RunResult, TaskResult
from nightshift.storage.store import (
    get_log_dir,
    load_latest_run,
    load_run,
    load_runs,
    save_run,
)


@pytest.fixture
def runs_dir(tmp_path):
    d = tmp_path / "runs"
    d.mkdir()
    with patch("nightshift.storage.store.RUNS_DIR", d):
        yield d


@pytest.fixture
def logs_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    with patch("nightshift.storage.store.LOGS_DIR", d):
        yield d


def _make_run(run_id: str = "20260318-040000") -> RunResult:
    return RunResult(
        run_id=run_id,
        task_results=[
            TaskResult(
                task_id="task-1",
                task_title="Fix imports",
                project_path="/tmp/proj",
                status="passed",
                files_changed=2,
                duration_seconds=60.0,
            ),
        ],
    )


class TestSaveRun:
    def test_creates_file(self, runs_dir):
        result = _make_run()
        path = save_run(result)
        assert path.exists()
        assert path.name == "20260318-040000.json"

    def test_file_content_roundtrips(self, runs_dir):
        result = _make_run()
        save_run(result)
        loaded = RunResult.model_validate_json(
            (runs_dir / "20260318-040000.json").read_text()
        )
        assert loaded.run_id == result.run_id
        assert len(loaded.task_results) == 1
        assert loaded.task_results[0].task_id == "task-1"

    def test_creates_directory_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "runs"
        with patch("nightshift.storage.store.RUNS_DIR", nested):
            path = save_run(_make_run())
        assert nested.exists()
        assert path.exists()

    def test_overwrites_existing(self, runs_dir):
        save_run(_make_run())
        updated = _make_run()
        updated.task_results = []
        save_run(updated)
        loaded = RunResult.model_validate_json(
            (runs_dir / "20260318-040000.json").read_text()
        )
        assert loaded.task_results == []


class TestLoadRun:
    def test_returns_run(self, runs_dir):
        save_run(_make_run("run-abc"))
        loaded = load_run("run-abc")
        assert loaded is not None
        assert loaded.run_id == "run-abc"

    def test_returns_none_for_missing(self, runs_dir):
        assert load_run("nonexistent") is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        with patch("nightshift.storage.store.RUNS_DIR", tmp_path / "nope"):
            assert load_run("anything") is None


class TestLoadLatestRun:
    def test_returns_most_recent(self, runs_dir):
        save_run(_make_run("run-old"))
        time.sleep(0.05)
        save_run(_make_run("run-new"))
        latest = load_latest_run()
        assert latest is not None
        assert latest.run_id == "run-new"

    def test_returns_none_when_empty(self, runs_dir):
        assert load_latest_run() is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        with patch("nightshift.storage.store.RUNS_DIR", tmp_path / "nope"):
            assert load_latest_run() is None


class TestLoadRuns:
    def test_returns_sorted_newest_first(self, runs_dir):
        for i in range(3):
            save_run(_make_run(f"run-{i}"))
            time.sleep(0.05)
        results = load_runs(limit=10)
        assert len(results) == 3
        assert results[0].run_id == "run-2"
        assert results[2].run_id == "run-0"

    def test_respects_limit(self, runs_dir):
        for i in range(5):
            save_run(_make_run(f"run-{i}"))
            time.sleep(0.05)
        results = load_runs(limit=2)
        assert len(results) == 2

    def test_returns_empty_when_no_runs(self, runs_dir):
        assert load_runs() == []

    def test_returns_empty_when_dir_missing(self, tmp_path):
        with patch("nightshift.storage.store.RUNS_DIR", tmp_path / "nope"):
            assert load_runs() == []


class TestGetLogDir:
    def test_creates_and_returns_dir(self, logs_dir):
        log_dir = get_log_dir("run-123")
        assert log_dir.exists()
        assert log_dir.is_dir()
        assert log_dir == logs_dir / "run-123"

    def test_creates_nested_parents(self, tmp_path):
        deep = tmp_path / "deep" / "logs"
        with patch("nightshift.storage.store.LOGS_DIR", deep):
            log_dir = get_log_dir("run-456")
        assert log_dir.exists()
        assert log_dir == deep / "run-456"

    def test_idempotent(self, logs_dir):
        get_log_dir("run-789")
        get_log_dir("run-789")  # no error on second call
        assert (logs_dir / "run-789").exists()
