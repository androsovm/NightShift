"""Tests for nightshift.config.loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from nightshift.config.loader import (
    PROJECT_CONFIG_NAME,
    load_global_config,
    load_project_config,
    save_global_config,
    save_project_config,
)
from nightshift.models.config import (
    GlobalConfig,
    ProjectConfig,
    ProjectLimits,
    ScheduleConfig,
    SourceConfig,
    SourceType,
)


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------


class TestLoadGlobalConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".nightshift" / "config.yaml"
        with patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path):
            cfg = load_global_config()
        assert isinstance(cfg, GlobalConfig)
        assert cfg.max_prs_per_night == 10
        assert cfg.schedule.time == "04:00"
        assert cfg.projects == []

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "config.yaml"
        fake_path.write_text("", encoding="utf-8")
        with patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path):
            cfg = load_global_config()
        assert isinstance(cfg, GlobalConfig)
        assert cfg.max_prs_per_night == 10

    def test_whitespace_only_file_returns_defaults(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "config.yaml"
        fake_path.write_text("   \n\n  ", encoding="utf-8")
        with patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path):
            cfg = load_global_config()
        assert isinstance(cfg, GlobalConfig)

    def test_yaml_with_only_null_returns_defaults(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "config.yaml"
        fake_path.write_text("null\n", encoding="utf-8")
        with patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path):
            cfg = load_global_config()
        assert isinstance(cfg, GlobalConfig)

    def test_loads_custom_values(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "config.yaml"
        data = {
            "schedule": {"time": "03:00", "timezone": "America/New_York"},
            "max_prs_per_night": 7,
        }
        fake_path.write_text(yaml.dump(data), encoding="utf-8")
        with patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path):
            cfg = load_global_config()
        assert cfg.max_prs_per_night == 7
        assert cfg.schedule.time == "03:00"
        assert cfg.schedule.timezone == "America/New_York"


class TestSaveGlobalConfig:
    def test_creates_parent_dir_and_saves(self, tmp_path: Path) -> None:
        fake_dir = tmp_path / ".nightshift"
        fake_path = fake_dir / "config.yaml"
        cfg = GlobalConfig(
            schedule=ScheduleConfig(time="02:00"),
            max_prs_per_night=3,
        )
        with (
            patch("nightshift.config.loader.GLOBAL_CONFIG_DIR", fake_dir),
            patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path),
        ):
            save_global_config(cfg)

        assert fake_path.exists()
        loaded = yaml.safe_load(fake_path.read_text(encoding="utf-8"))
        assert loaded["max_prs_per_night"] == 3
        assert loaded["schedule"]["time"] == "02:00"

    def test_roundtrip(self, tmp_path: Path) -> None:
        fake_dir = tmp_path / ".nightshift"
        fake_path = fake_dir / "config.yaml"
        original = GlobalConfig(
            schedule=ScheduleConfig(time="05:00", timezone="US/Eastern"),
            max_prs_per_night=12,
        )
        with (
            patch("nightshift.config.loader.GLOBAL_CONFIG_DIR", fake_dir),
            patch("nightshift.config.loader.GLOBAL_CONFIG_PATH", fake_path),
        ):
            save_global_config(original)
            restored = load_global_config()

        assert restored.max_prs_per_night == original.max_prs_per_night
        assert restored.schedule.time == original.schedule.time
        assert restored.schedule.timezone == original.schedule.timezone


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


class TestLoadProjectConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_project_config(tmp_path)
        assert isinstance(cfg, ProjectConfig)
        assert cfg.sources == []
        assert cfg.limits.max_tasks_per_run == 5

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        (tmp_path / PROJECT_CONFIG_NAME).write_text("", encoding="utf-8")
        cfg = load_project_config(tmp_path)
        assert isinstance(cfg, ProjectConfig)

    def test_loads_custom_values(self, tmp_path: Path) -> None:
        data = {
            "sources": [{"type": "yaml"}],
            "limits": {"max_tasks_per_run": 2, "task_timeout_minutes": 20},
            "claude_system_prompt": "Be concise.",
        }
        (tmp_path / PROJECT_CONFIG_NAME).write_text(
            yaml.dump(data), encoding="utf-8"
        )
        cfg = load_project_config(tmp_path)
        assert len(cfg.sources) == 1
        assert cfg.sources[0].type == SourceType.YAML
        assert cfg.limits.max_tasks_per_run == 2
        assert cfg.claude_system_prompt == "Be concise."


class TestSaveProjectConfig:
    def test_saves_and_reloads(self, tmp_path: Path) -> None:
        original = ProjectConfig(
            sources=[SourceConfig(type=SourceType.YAML)],
            limits=ProjectLimits(max_tasks_per_run=8),
            claude_system_prompt="Custom prompt.",
        )
        save_project_config(tmp_path, original)

        restored = load_project_config(tmp_path)
        assert restored.limits.max_tasks_per_run == 8
        assert restored.claude_system_prompt == "Custom prompt."
        assert len(restored.sources) == 1

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        save_project_config(
            tmp_path, ProjectConfig(limits=ProjectLimits(max_tasks_per_run=1))
        )
        save_project_config(
            tmp_path, ProjectConfig(limits=ProjectLimits(max_tasks_per_run=99))
        )
        cfg = load_project_config(tmp_path)
        assert cfg.limits.max_tasks_per_run == 99
