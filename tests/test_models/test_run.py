"""Tests for run result models."""

from datetime import datetime

from nightshift.models.run import RunResult, TaskResult


def test_task_result_minimal():
    r = TaskResult(
        task_id="t1",
        task_title="Test",
        project_path="/tmp",
        status="passed",
    )
    assert r.files_changed == 0
    assert r.error is None
    assert r.pr_url is None


def test_run_result_defaults():
    r = RunResult(run_id="20260318-040000")
    assert r.task_results == []
    assert r.finished_at is None
    assert isinstance(r.started_at, datetime)


def test_run_result_with_tasks(sample_run_result):
    assert len(sample_run_result.task_results) == 2
    passed = [t for t in sample_run_result.task_results if t.status == "passed"]
    failed = [t for t in sample_run_result.task_results if t.status == "failed"]
    assert len(passed) == 1
    assert len(failed) == 1
    assert failed[0].error is not None


def test_run_result_roundtrip(sample_run_result):
    json_str = sample_run_result.model_dump_json()
    restored = RunResult.model_validate_json(json_str)
    assert restored.run_id == sample_run_result.run_id
    assert len(restored.task_results) == 2
