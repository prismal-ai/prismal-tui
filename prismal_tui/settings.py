"""``PrismalTuiSettings`` — all configuration via ``PRISMAL_TUI_*`` env vars.

SPEC-TUI-CFG-001..003, SPEC-TUI-AUT-001/003, ``SPEC.md`` §8. The token is a
``SecretStr`` handed only to the SDK client constructor; configuration errors
are reported per env var and never echo input values (SPEC-TUI-AUT-002).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import platformdirs
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from textual.keys import ASCII_KEY_NAMES, KEY_ALIASES, Keys

ENV_PREFIX = "PRISMAL_TUI_"
APP_NAME = "prismal-tui"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_MODIFIERS = frozenset({"ctrl", "shift", "alt", "meta", "super", "hyper"})


class ConfigurationError(Exception):
    """A readable, secret-free startup configuration error (fail fast)."""


def default_store_path() -> Path:
    """``<platformdirs user-data dir>/conversations.db``."""
    return platformdirs.user_data_path(APP_NAME, appauthor=False) / "conversations.db"


def _known_base_keys() -> frozenset[str]:
    names: set[str] = set()
    for key in Keys:
        names.add(key.value.split("+")[-1])
    names.update(ASCII_KEY_NAMES.values())
    names.update(KEY_ALIASES)
    for alias_list in KEY_ALIASES.values():
        names.update(alias_list)
    names.update(f"f{i}" for i in range(1, 25))
    names.update(chr(c) for c in range(ord("a"), ord("z") + 1))
    names.update(str(d) for d in range(10))
    return frozenset(n for n in names if n)


_KNOWN_BASE_KEYS = _known_base_keys()


def is_valid_cancel_key(key: str) -> bool:
    """A Textual key name, optionally modifier-prefixed (``ctrl+shift+c``).

    A bare printable character is rejected: bound app-wide it would be
    swallowed from every message typed into the composer.
    """
    if not key or key != key.strip():
        return False
    *mods, base = key.split("+")
    if not base or base not in _KNOWN_BASE_KEYS:
        return False
    if any(m not in _MODIFIERS for m in mods) or len(set(mods)) != len(mods):
        return False
    return not (not mods and len(base) == 1)


class PrismalTuiSettings(BaseSettings):
    """Settings table from ``SPEC.md`` §8 (prefix ``PRISMAL_TUI_``)."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, extra="ignore", frozen=True
    )

    server_url: str = "http://localhost:8000"
    token: SecretStr | None = None
    org_id: str | None = None
    store_path: Path = Field(default_factory=default_store_path)
    cancel_key: str = "escape"
    log_level: LogLevel = "INFO"

    @field_validator("server_url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("must be an absolute http:// or https:// URL")
        return value

    @field_validator("cancel_key")
    @classmethod
    def _known_key(cls, value: str) -> str:
        if not is_valid_cancel_key(value):
            raise ValueError(
                "must be a Textual key name such as 'escape', 'ctrl+x' or 'f2' "
                "(a bare printable character is not allowed)"
            )
        return value

    @field_validator("org_id")
    @classmethod
    def _blank_org_is_none(cls, value: str | None) -> str | None:
        return value or None


def _env_name(loc: tuple[int | str, ...]) -> str:
    field = str(loc[0]) if loc else "?"
    return f"{ENV_PREFIX}{field.upper()}"


def ensure_store_parent(path: Path) -> None:
    """Create the store's parent dir on first run (SPEC-TUI-CFG-002)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(
            f"{ENV_PREFIX}STORE_PATH: cannot create directory {path.parent} "
            f"({exc.strerror or type(exc).__name__})"
        ) from None


def load_settings() -> PrismalTuiSettings:
    """Build and validate settings, failing fast with a readable error.

    Called before the Textual app mounts (SPEC-TUI-CFG-001/003). Messages
    name the env var and the rule broken, never the offending value — so a
    misplaced token can never leak through an error (SPEC-TUI-AUT-002).
    """
    try:
        settings = PrismalTuiSettings()
    except ValidationError as exc:
        lines = [
            f"{_env_name(err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
            for err in exc.errors(include_input=False, include_url=False)
        ]
        raise ConfigurationError(
            "invalid configuration:\n  " + "\n  ".join(lines)
        ) from None
    ensure_store_parent(settings.store_path)
    return settings
