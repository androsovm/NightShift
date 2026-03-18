"""Tests for nightshift.config.secrets."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

from nightshift.config.secrets import (
    _ensure_secrets_file,
    get_secret,
    load_secrets,
    save_secret,
)


class TestEnsureSecretsFile:
    def test_creates_file_and_parent(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "sub" / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            result = _ensure_secrets_file()

        assert result == fake_path
        assert fake_path.exists()
        mode = fake_path.stat().st_mode
        assert mode & 0o777 == 0o600

    def test_sets_permissions_on_existing_file(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        fake_path.write_text("KEY=val\n", encoding="utf-8")
        fake_path.chmod(0o644)
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            _ensure_secrets_file()

        mode = fake_path.stat().st_mode
        assert mode & 0o777 == 0o600


class TestLoadSecrets:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "nonexistent" / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            secrets = load_secrets()
        assert secrets == {}

    def test_loads_key_value_pairs(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        fake_path.write_text("ALPHA=one\nBRAVO=two\n", encoding="utf-8")
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            secrets = load_secrets()
        assert secrets == {"ALPHA": "one", "BRAVO": "two"}

    def test_filters_none_values(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        # A key without '=' in dotenv is typically parsed as None value.
        fake_path.write_text("GOOD=yes\n", encoding="utf-8")
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            secrets = load_secrets()
        assert "GOOD" in secrets
        for v in secrets.values():
            assert v is not None


class TestSaveSecret:
    def test_save_and_get_roundtrip(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            save_secret("API_KEY", "test-key-12345")
            result = get_secret("API_KEY")

        assert result == "test-key-12345"

    def test_updates_existing_key(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            save_secret("TOKEN", "old")
            save_secret("TOKEN", "new")
            result = get_secret("TOKEN")
        assert result == "new"

    def test_multiple_keys(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            save_secret("A", "1")
            save_secret("B", "2")
            assert get_secret("A") == "1"
            assert get_secret("B") == "2"

    def test_file_permissions_after_save(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            save_secret("SECRET", "value")
        mode = fake_path.stat().st_mode
        assert mode & 0o777 == 0o600


class TestGetSecret:
    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        fake_path = tmp_path / ".env"
        fake_path.write_text("OTHER=val\n", encoding="utf-8")
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            assert get_secret("NONEXISTENT") is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "nope" / ".env"
        with patch("nightshift.config.secrets.SECRETS_PATH", fake_path):
            assert get_secret("ANYTHING") is None
