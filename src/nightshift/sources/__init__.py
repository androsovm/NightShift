"""Task source adapter registry.

Built-in adapters are registered here.  Third-party packages can add
their own adapters by declaring a ``nightshift.sources`` entry point::

    # In the plugin's pyproject.toml:
    [project.entry-points."nightshift.sources"]
    jira = "my_plugin.jira_source:JiraSource"
    linear = "my_plugin.linear_source:LinearSource"

The adapter class must satisfy the :class:`~nightshift.sources.base.TaskSourceAdapter`
protocol (i.e. implement ``fetch_tasks`` and ``mark_done`` async methods).
"""

from __future__ import annotations

import sys

import structlog

from nightshift.sources.base import TaskSourceAdapter
from nightshift.sources.github_source import GitHubSource
from nightshift.sources.trello_source import TrelloSource
from nightshift.sources.yaml_source import YAMLSource
from nightshift.sources.youtrack_source import YouTrackSource

log = structlog.get_logger(__name__)

# Built-in adapters
_BUILTIN_ADAPTERS: dict[str, type] = {
    "yaml": YAMLSource,
    "github": GitHubSource,
    "youtrack": YouTrackSource,
    "trello": TrelloSource,
}

# Mutable registry — plugins and user code can call ``register()`` directly.
_registry: dict[str, type] = dict(_BUILTIN_ADAPTERS)


def register(name: str, adapter_cls: type) -> None:
    """Register a task source adapter under *name*.

    This is the programmatic API for registering adapters.  Plugins can
    also register via the ``nightshift.sources`` entry point group.

    Example::

        from nightshift.sources import register

        class MySource:
            async def fetch_tasks(self, project_path, config): ...
            async def mark_done(self, task, pr_url): ...

        register("my_source", MySource)
    """
    if name in _registry:
        log.warning("source_adapter_overwrite", name=name, cls=adapter_cls.__name__)
    _registry[name] = adapter_cls
    log.debug("source_adapter_registered", name=name, cls=adapter_cls.__name__)


def _load_plugins() -> None:
    """Discover and register adapters from ``nightshift.sources`` entry points."""
    if sys.version_info >= (3, 12):
        from importlib.metadata import entry_points

        eps = entry_points(group="nightshift.sources")
    else:
        from importlib.metadata import entry_points

        eps = entry_points().get("nightshift.sources", [])

    for ep in eps:
        try:
            adapter_cls = ep.load()
            register(ep.name, adapter_cls)
            log.info("plugin_loaded", name=ep.name, module=ep.value)
        except Exception:
            log.exception("plugin_load_error", name=ep.name)


# Load plugins on import
_load_plugins()


def get_adapter(name: str) -> type | None:
    """Return the adapter class for *name*, or ``None`` if unknown."""
    return _registry.get(name)


def available_sources() -> list[str]:
    """Return sorted list of all registered source type names."""
    return sorted(_registry.keys())


# Backward-compatible dict-like access
ADAPTERS = _registry

__all__ = [
    "ADAPTERS",
    "GitHubSource",
    "TaskSourceAdapter",
    "TrelloSource",
    "YAMLSource",
    "YouTrackSource",
    "available_sources",
    "get_adapter",
    "register",
]
