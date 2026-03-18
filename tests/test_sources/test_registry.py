"""Tests for the source adapter registry and plugin system."""

from __future__ import annotations

from nightshift.models.config import SourceConfig
from nightshift.sources import (
    ADAPTERS,
    available_sources,
    get_adapter,
    register,
)
from nightshift.sources.github_source import GitHubSource
from nightshift.sources.trello_source import TrelloSource
from nightshift.sources.yaml_source import YAMLSource
from nightshift.sources.youtrack_source import YouTrackSource


class TestBuiltinAdapters:
    def test_yaml_registered(self):
        assert get_adapter("yaml") is YAMLSource

    def test_github_registered(self):
        assert get_adapter("github") is GitHubSource

    def test_youtrack_registered(self):
        assert get_adapter("youtrack") is YouTrackSource

    def test_trello_registered(self):
        assert get_adapter("trello") is TrelloSource

    def test_unknown_returns_none(self):
        assert get_adapter("nonexistent") is None

    def test_available_sources_includes_builtins(self):
        sources = available_sources()
        assert "yaml" in sources
        assert "github" in sources
        assert "youtrack" in sources
        assert "trello" in sources

    def test_adapters_dict_matches_registry(self):
        for name in ("yaml", "github", "youtrack", "trello"):
            assert name in ADAPTERS


class TestPluginRegistration:
    def test_register_custom_adapter(self):
        class DummySource:
            async def fetch_tasks(self, project_path, config):
                return []

            async def mark_done(self, task, pr_url):
                pass

        register("dummy", DummySource)
        assert get_adapter("dummy") is DummySource
        assert "dummy" in available_sources()

        # Cleanup
        ADAPTERS.pop("dummy", None)

    def test_register_overwrites_existing(self):
        class NewYAML:
            async def fetch_tasks(self, project_path, config):
                return []

            async def mark_done(self, task, pr_url):
                pass

        original = get_adapter("yaml")
        register("yaml", NewYAML)
        assert get_adapter("yaml") is NewYAML

        # Restore
        register("yaml", original)

    def test_source_config_accepts_custom_type(self):
        """SourceConfig.type is a free-form string, not limited to SourceType enum."""
        cfg = SourceConfig(type="jira", options={"project_key": "PROJ", "jql": "label=nightshift"})
        assert cfg.type == "jira"
        assert cfg.options["project_key"] == "PROJ"
