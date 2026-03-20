"""Tests for storage.store module — corrupted JSON handling."""

import time

from nightshift.models.run import RunResult
from nightshift.storage.store import load_latest_run, load_run, load_runs, save_run


class TestLoadRunCorruptedJson:
    def test_load_run_corrupted_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        run_id = "20260318-040000"
        (tmp_path / f"{run_id}.json").write_text("{corrupted data!!")
        result = load_run(run_id)
        assert result is None

    def test_load_run_invalid_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)
        run_id = "20260318-040000"
        (tmp_path / f"{run_id}.json").write_text('{"unexpected_field": true}')
        result = load_run(run_id)
        assert result is None


class TestLoadLatestRunSkipsCorrupted:
    def test_load_latest_run_skips_corrupted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)

        # Write a good file first (older)
        good = RunResult(run_id="20260318-030000")
        good_path = tmp_path / "20260318-030000.json"
        good_path.write_text(good.model_dump_json(indent=2))

        time.sleep(0.05)

        # Write a corrupted file (newer)
        bad_path = tmp_path / "20260318-040000.json"
        bad_path.write_text("{not valid json")

        result = load_latest_run()
        assert result is not None
        assert result.run_id == "20260318-030000"


class TestLoadRunsSkipsCorrupted:
    def test_load_runs_skips_corrupted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nightshift.storage.store.RUNS_DIR", tmp_path)

        good1 = RunResult(run_id="20260318-010000")
        (tmp_path / "20260318-010000.json").write_text(good1.model_dump_json(indent=2))
        time.sleep(0.05)

        (tmp_path / "20260318-020000.json").write_text("CORRUPT")
        time.sleep(0.05)

        good2 = RunResult(run_id="20260318-030000")
        (tmp_path / "20260318-030000.json").write_text(good2.model_dump_json(indent=2))

        results = load_runs(limit=10)
        assert len(results) == 2
        run_ids = {r.run_id for r in results}
        assert run_ids == {"20260318-010000", "20260318-030000"}
