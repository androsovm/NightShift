"""Tests for config models."""

from pathlib import Path

from nightshift.models.config import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ProjectRef,
    ScheduleConfig,
    SourceConfig,
    SourceType,
)


def test_source_type_values():
    assert SourceType.YAML == "yaml"
    assert SourceType.GITHUB == "github"
    assert SourceType.YOUTRACK == "youtrack"
    assert SourceType.TRELLO == "trello"


def test_source_config_defaults():
    cfg = SourceConfig(type=SourceType.GITHUB)
    assert cfg.labels == ["nightshift"]
    assert cfg.repo is None


def test_project_limits_defaults():
    limits = ProjectLimits()
    assert limits.max_tasks_per_run == 5
    assert limits.task_timeout_minutes == 45
    assert limits.max_files_changed == 20
    assert limits.max_lines_changed == 500


def test_project_config_minimal():
    cfg = ProjectConfig()
    assert cfg.sources == []
    assert cfg.limits.max_tasks_per_run == 5
    assert cfg.claude_system_prompt is None


def test_schedule_config_defaults():
    cfg = ScheduleConfig()
    assert cfg.time == "04:00"
    assert cfg.timezone == "UTC"
    assert cfg.max_duration_hours == 4


def test_global_config_full():
    cfg = GlobalConfig(
        schedule=ScheduleConfig(time="03:00"),
        projects=[ProjectRef(path=Path("/tmp/proj"), sources=[SourceType.YAML])],
        max_prs_per_night=3,
    )
    assert cfg.max_prs_per_night == 3
    assert len(cfg.projects) == 1
    assert cfg.projects[0].sources == [SourceType.YAML]


def test_project_config_roundtrip():
    cfg = ProjectConfig(
        sources=[SourceConfig(type=SourceType.GITHUB, repo="user/repo")],
        limits=ProjectLimits(max_tasks_per_run=10),
        claude_system_prompt="Be concise",
    )
    data = cfg.model_dump()
    restored = ProjectConfig.model_validate(data)
    assert restored == cfg
