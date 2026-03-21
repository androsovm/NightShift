"""Tests for storage.store corrupted JSON handling."""

import time
from pathlib import Path

from nightshift.models.run import RunResult
from nightshift.storage.store import (
    RUNS_DIR,
    load_latest_run,
    load_run,
    load_runs,
    save_run,
)


def _make_run(run_id: str) -> RunResult:
    return RunResult(run_id=run_id)


class TestLoadRunCorruptedJson:
    def test_returns_none_for_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        path = tmp_path / "bad-run.json"
        path.write_text("{not valid json!!!")

        result = load_run("bad-run")
        assert result is None

    def test_returns_none_for_invalid_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        path = tmp_path / "bad-schema.json"
        path.write_text('{"unknown_field": true}')

        result = load_run("bad-schema")
        assert result is None

    def test_returns_valid_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        run = _make_run("good-run")
        save_run(run)

        result = load_run("good-run")
        assert result is not None
        assert result.run_id == "good-run"


class TestLoadLatestRunSkipsCorrupted:
    def test_skips_corrupted_returns_good(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)

        # Write a good file first (older)
        run = _make_run("good-run")
        good_path = tmp_path / "good-run.json"
        good_path.write_text(run.model_dump_json(indent=2))

        time.sleep(0.05)

        # Write a corrupted file second (newer)
        bad_path = tmp_path / "bad-run.json"
        bad_path.write_text("{corrupted!!!")

        result = load_latest_run()
        assert result is not None
        assert result.run_id == "good-run"

    def test_returns_none_when_all_corrupted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        (tmp_path / "a.json").write_text("nope")
        (tmp_path / "b.json").write_text("also nope")

        assert load_latest_run() is None


class TestLoadRunsSkipsCorrupted:
    def test_skips_corrupted_returns_good_ones(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)

        # Write 2 good files and 1 bad
        for rid in ("run-1", "run-2"):
            run = _make_run(rid)
            p = tmp_path / f"{rid}.json"
            p.write_text(run.model_dump_json(indent=2))
            time.sleep(0.05)

        bad_path = tmp_path / "run-bad.json"
        bad_path.write_text("not json")

        results = load_runs(limit=10)
        assert len(results) == 2
        assert all(isinstance(r, RunResult) for r in results)

    def test_returns_empty_when_all_corrupted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        (tmp_path / "a.json").write_text("{bad}")

        assert load_runs() == []
