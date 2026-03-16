"""Tests for task_parser module."""

import os
import tempfile
from datetime import datetime

import yaml
import pytest

from task_parser import (
    load_tasks, filter_by_status, next_task, mark_done, save_tasks,
    schedule_tasks, format_schedule, estimate_completion,
)


SAMPLE_TASKS = [
    {"id": 1, "title": "Task A", "status": "pending", "priority": "high", "context": "ctx"},
    {"id": 2, "title": "Task B", "status": "done", "priority": "low", "context": "ctx"},
    {"id": 3, "title": "Task C", "status": "pending", "priority": "low", "context": "ctx"},
    {"id": 4, "title": "Task D", "status": "pending", "priority": "medium", "context": "ctx"},
]


@pytest.fixture
def yaml_file(tmp_path):
    filepath = tmp_path / "tasks.yaml"
    with open(filepath, "w") as f:
        yaml.dump({"tasks": SAMPLE_TASKS}, f)
    return str(filepath)


def test_load_tasks(yaml_file):
    tasks = load_tasks(yaml_file)
    assert len(tasks) == 4
    assert tasks[0]["title"] == "Task A"


def test_load_tasks_missing_file():
    assert load_tasks("/nonexistent/path.yaml") == []


def test_load_tasks_empty_file(tmp_path):
    filepath = tmp_path / "empty.yaml"
    filepath.write_text("")
    assert load_tasks(str(filepath)) == []


def test_filter_by_status_pending():
    result = filter_by_status(SAMPLE_TASKS, "pending")
    assert len(result) == 3
    assert all(t["status"] == "pending" for t in result)


def test_filter_by_status_done():
    result = filter_by_status(SAMPLE_TASKS, "done")
    assert len(result) == 1
    assert result[0]["id"] == 2


def test_next_task_returns_highest_priority():
    task = next_task(SAMPLE_TASKS)
    assert task is not None
    assert task["priority"] == "high"
    assert task["id"] == 1


def test_next_task_respects_priority_order():
    tasks = [
        {"id": 10, "title": "Low", "status": "pending", "priority": "low"},
        {"id": 11, "title": "Med", "status": "pending", "priority": "medium"},
    ]
    task = next_task(tasks)
    assert task["id"] == 11


def test_next_task_no_pending():
    tasks = [{"id": 1, "title": "Done", "status": "done", "priority": "high"}]
    assert next_task(tasks) is None


def test_next_task_empty_list():
    assert next_task([]) is None


def test_mark_done():
    tasks = [{"id": 1, "status": "pending"}, {"id": 2, "status": "pending"}]
    mark_done(tasks, 1)
    assert tasks[0]["status"] == "done"
    assert tasks[1]["status"] == "pending"


def test_mark_done_nonexistent_id():
    tasks = [{"id": 1, "status": "pending"}]
    mark_done(tasks, 999)
    assert tasks[0]["status"] == "pending"


def test_save_and_reload(tmp_path):
    filepath = str(tmp_path / "out.yaml")
    save_tasks(SAMPLE_TASKS, filepath)
    reloaded = load_tasks(filepath)
    assert len(reloaded) == len(SAMPLE_TASKS)
    assert reloaded[0]["title"] == SAMPLE_TASKS[0]["title"]


def test_roundtrip_mark_done(yaml_file):
    tasks = load_tasks(yaml_file)
    mark_done(tasks, 1)
    save_tasks(tasks, yaml_file)
    reloaded = load_tasks(yaml_file)
    t1 = next(t for t in reloaded if t["id"] == 1)
    assert t1["status"] == "done"


# --- schedule_tasks tests ---

class TestScheduleTasks:
    def test_basic_scheduling(self):
        start = datetime(2026, 3, 16, 22, 0)
        schedule = schedule_tasks(SAMPLE_TASKS, start)
        assert len(schedule) == 3  # 3 pending tasks
        assert schedule[0]["task_id"] == 1  # high priority first
        assert schedule[0]["start_time"] == datetime(2026, 3, 16, 22, 0)
        assert schedule[0]["end_time"] == datetime(2026, 3, 16, 22, 30)
        assert schedule[1]["start_time"] == datetime(2026, 3, 16, 22, 30)
        assert schedule[2]["start_time"] == datetime(2026, 3, 16, 23, 0)

    def test_priority_order(self):
        start = datetime(2026, 3, 16, 22, 0)
        schedule = schedule_tasks(SAMPLE_TASKS, start)
        priorities = [e["priority"] for e in schedule]
        assert priorities == ["high", "medium", "low"]

    def test_empty_list(self):
        start = datetime(2026, 3, 16, 22, 0)
        assert schedule_tasks([], start) == []

    def test_all_done(self):
        tasks = [
            {"id": 1, "title": "Done1", "status": "done", "priority": "high"},
            {"id": 2, "title": "Done2", "status": "done", "priority": "low"},
        ]
        start = datetime(2026, 3, 16, 22, 0)
        assert schedule_tasks(tasks, start) == []

    def test_single_task(self):
        tasks = [{"id": 5, "title": "Solo", "status": "pending", "priority": "medium"}]
        start = datetime(2026, 3, 16, 23, 0)
        schedule = schedule_tasks(tasks, start)
        assert len(schedule) == 1
        assert schedule[0]["task_id"] == 5
        assert schedule[0]["end_time"] == datetime(2026, 3, 16, 23, 30)

    def test_schedule_contains_required_fields(self):
        tasks = [{"id": 1, "title": "T", "status": "pending", "priority": "low"}]
        start = datetime(2026, 3, 16, 22, 0)
        entry = schedule_tasks(tasks, start)[0]
        assert set(entry.keys()) >= {"task_id", "title", "start_time", "end_time"}


# --- format_schedule tests ---

class TestFormatSchedule:
    def test_basic_format(self):
        start = datetime(2026, 3, 16, 22, 0)
        schedule = schedule_tasks(SAMPLE_TASKS, start)
        result = format_schedule(schedule)
        lines = result.strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "[22:00 - 22:30] Task A (high)"
        assert lines[1] == "[22:30 - 23:00] Task D (medium)"
        assert lines[2] == "[23:00 - 23:30] Task C (low)"

    def test_empty_schedule(self):
        assert format_schedule([]) == ""

    def test_midnight_crossing(self):
        tasks = [
            {"id": 1, "title": "Late", "status": "pending", "priority": "high"},
            {"id": 2, "title": "After", "status": "pending", "priority": "low"},
        ]
        start = datetime(2026, 3, 16, 23, 45)
        schedule = schedule_tasks(tasks, start)
        result = format_schedule(schedule)
        assert "[23:45 - 00:15] Late (high)" in result
        assert "[00:15 - 00:45] After (low)" in result


# --- estimate_completion tests ---

def test_estimate_completion_basic():
    tasks = [
        {"id": 1, "title": "A", "status": "pending", "priority": "high"},
        {"id": 2, "title": "B", "status": "pending", "priority": "low"},
        {"id": 3, "title": "C", "status": "done", "priority": "high"},
    ]
    history = {3: 60, 10: 20}
    start = datetime(2024, 1, 1, 22, 0)
    result = estimate_completion(tasks, history, start)
    assert result["total_minutes"] == 75  # task1: 60 (avg high from history), task2: 15 (default low)
    assert result["estimated_finish"] == datetime(2024, 1, 1, 23, 15)
    assert len(result["per_task"]) == 2
