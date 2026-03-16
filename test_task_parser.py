"""Tests for task_parser module."""

import os
import tempfile

import yaml
import pytest

from task_parser import load_tasks, filter_by_status, next_task, mark_done, save_tasks


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
