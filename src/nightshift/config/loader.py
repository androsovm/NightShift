"""Config loading, merging, and persistence."""

from __future__ import annotations

from pathlib import Path

import yaml

from nightshift.models.config import GlobalConfig, ProjectConfig

GLOBAL_CONFIG_DIR: Path = Path.home() / ".nightshift"
GLOBAL_CONFIG_PATH: Path = GLOBAL_CONFIG_DIR / "config.yaml"
PROJECT_CONFIG_NAME: str = ".nightshift.yaml"


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------


def load_global_config() -> GlobalConfig:
    """Load the global config from *~/.nightshift/config.yaml*.

    Returns sensible defaults when the file does not exist or is empty.
    """
    if not GLOBAL_CONFIG_PATH.exists():
        return GlobalConfig()

    raw = GLOBAL_CONFIG_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        return GlobalConfig()

    data = yaml.safe_load(raw)
    if data is None:
        return GlobalConfig()

    return GlobalConfig.model_validate(data)


def save_global_config(config: GlobalConfig) -> None:
    """Persist *config* to *~/.nightshift/config.yaml*.

    Creates the parent directory if it does not exist.
    """
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json")
    GLOBAL_CONFIG_PATH.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


def load_project_config(project_path: Path) -> ProjectConfig:
    """Load the project config from *.nightshift.yaml* inside *project_path*.

    Returns defaults when the file is missing or empty.
    """
    config_file = project_path / PROJECT_CONFIG_NAME

    if not config_file.exists():
        return ProjectConfig()

    raw = config_file.read_text(encoding="utf-8")
    if not raw.strip():
        return ProjectConfig()

    data = yaml.safe_load(raw)
    if data is None:
        return ProjectConfig()

    return ProjectConfig.model_validate(data)


def save_project_config(project_path: Path, config: ProjectConfig) -> None:
    """Save *config* as *.nightshift.yaml* inside *project_path*."""
    config_file = project_path / PROJECT_CONFIG_NAME

    data = config.model_dump(mode="json")
    config_file.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
