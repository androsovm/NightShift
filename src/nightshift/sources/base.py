"""Protocol definition for task source adapters.

To create a custom source adapter (e.g., for Jira, Linear, Notion),
implement a class that satisfies this protocol::

    from nightshift.models.config import SourceConfig
    from nightshift.models.task import Task

    class JiraSource:
        async def fetch_tasks(self, project_path: str, config: SourceConfig) -> list[Task]:
            # Fetch tasks from Jira API
            # Use config.options for source-specific settings
            ...

        async def mark_done(self, task: Task, pr_url: str) -> None:
            # Transition issue, post comment with PR link
            ...

Then register it via entry point in your plugin's pyproject.toml::

    [project.entry-points."nightshift.sources"]
    jira = "my_plugin.jira_source:JiraSource"

Or register programmatically::

    from nightshift.sources import register
    register("jira", JiraSource)
"""

from __future__ import annotations

from typing import Protocol

from nightshift.models.config import SourceConfig
from nightshift.models.task import Task


class TaskSourceAdapter(Protocol):
    """Any back-end that can supply tasks and acknowledge completion."""

    async def fetch_tasks(self, project_path: str, config: SourceConfig) -> list[Task]:
        """Return outstanding tasks from the source.

        ``config.options`` contains source-specific key-value pairs
        provided by the user in ``.nightshift.yaml``.
        """
        ...

    async def mark_done(self, task: Task, pr_url: str) -> None:
        """Signal that *task* has been completed (with *pr_url*)."""
        ...
