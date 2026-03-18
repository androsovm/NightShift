"""YAML-file task source adapter.

Reads tasks from the ``tasks:`` section of *.nightshift.yaml* and writes
status updates back to the same file.
"""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from slugify import slugify

from nightshift.config.loader import PROJECT_CONFIG_NAME
from nightshift.models.config import SourceConfig
from nightshift.models.task import Task, TaskPriority

log = structlog.get_logger(__name__)


class YAMLSource:
    """Reads / writes tasks stored directly in the project config file."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _config_path(project_path: str) -> Path:
        return Path(project_path) / PROJECT_CONFIG_NAME

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        return yaml.safe_load(raw) or {}

    @staticmethod
    def _save_yaml(path: Path, data: dict) -> None:
        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_tasks(
        self, project_path: str, config: SourceConfig
    ) -> list[Task]:
        """Return all tasks whose status is ``pending``."""
        cfg_path = self._config_path(project_path)
        data = self._load_yaml(cfg_path)
        raw_tasks: list[dict] = data.get("tasks", [])

        tasks: list[Task] = []
        for entry in raw_tasks:
            status = str(entry.get("status", "pending")).lower()
            if status != "pending":
                continue

            task_id = entry.get("id") or slugify(entry.get("title", "untitled"))
            priority_raw = str(entry.get("priority", "medium")).lower()
            try:
                priority = TaskPriority(priority_raw)
            except ValueError:
                priority = TaskPriority.MEDIUM

            task = Task(
                id=task_id,
                title=entry.get("title", task_id),
                source_type="yaml",
                source_ref=str(cfg_path),
                project_path=project_path,
                priority=priority,
                intent=entry.get("intent"),
                scope=entry.get("scope", []),
                constraints=entry.get("constraints", []),
            )
            tasks.append(task)

        log.info(
            "yaml_source.fetched",
            project_path=project_path,
            total=len(raw_tasks),
            pending=len(tasks),
        )
        return tasks

    async def mark_done(self, task: Task, pr_url: str) -> None:
        """Set the matching task's status to ``done`` in the YAML file."""
        cfg_path = Path(task.project_path) / PROJECT_CONFIG_NAME
        data = self._load_yaml(cfg_path)
        raw_tasks: list[dict] = data.get("tasks", [])

        updated = False
        for entry in raw_tasks:
            entry_id = entry.get("id") or slugify(entry.get("title", ""))
            if entry_id == task.id:
                entry["status"] = "done"
                entry["pr_url"] = pr_url
                updated = True
                break

        if not updated:
            log.warning(
                "yaml_source.mark_done.not_found",
                task_id=task.id,
                path=str(cfg_path),
            )
            return

        self._save_yaml(cfg_path, data)
        log.info(
            "yaml_source.marked_done",
            task_id=task.id,
            pr_url=pr_url,
        )
