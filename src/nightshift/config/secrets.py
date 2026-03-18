"""Secrets management backed by *~/.nightshift/.env*."""

from __future__ import annotations

import stat
from pathlib import Path

from dotenv import dotenv_values, set_key

SECRETS_PATH: Path = Path.home() / ".nightshift" / ".env"


def _ensure_secrets_file() -> Path:
    """Create the secrets file (and parent dir) if it does not exist.

    The file is always set to mode 600 (owner read/write only).
    """
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not SECRETS_PATH.exists():
        SECRETS_PATH.touch()

    SECRETS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    return SECRETS_PATH


def load_secrets() -> dict[str, str]:
    """Read all key-value pairs from the .env file.

    Returns an empty dict when the file does not exist.
    """
    if not SECRETS_PATH.exists():
        return {}

    values = dotenv_values(SECRETS_PATH)
    # dotenv_values may return None values for keys without a value;
    # filter those out so the return type stays dict[str, str].
    return {k: v for k, v in values.items() if v is not None}


def save_secret(key: str, value: str) -> None:
    """Set (or update) *key* in the .env file and ensure mode 600."""
    path = _ensure_secrets_file()
    # python-dotenv's set_key handles both insert and update.
    success, _key, _value = set_key(
        str(path),
        key,
        value,
        quote_mode="auto",
    )
    if not success:
        raise RuntimeError(f"Failed to write secret {key!r} to {path}")

    # Re-apply permissions in case set_key recreated the file.
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def get_secret(key: str) -> str | None:
    """Return the value of *key*, or ``None`` if it is not set."""
    secrets = load_secrets()
    return secrets.get(key)
