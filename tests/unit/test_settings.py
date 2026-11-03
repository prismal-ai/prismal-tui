"""PrismalTuiSettings — SPEC-TUI-CFG-001..003, SPEC-TUI-AUT-001/003, §8 defaults."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr

from prismal_tui.settings import (
    ConfigurationError,
    PrismalTuiSettings,
    default_store_path,
    load_settings,
)

TOKEN = "tok-super-secret-123"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PRISMAL_TUI_"):
            monkeypatch.delenv(key)


def test_defaults_match_spec_table() -> None:
    s = PrismalTuiSettings()
    assert s.server_url == "http://localhost:8000"
    assert s.token is None
    assert s.org_id is None
    assert s.store_path == default_store_path()
    assert s.store_path.name == "conversations.db"
    assert s.cancel_key == "escape"
    assert s.log_level == "INFO"


def test_reads_prefixed_env_vars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_SERVER_URL", "https://prismal.example:9000")
    monkeypatch.setenv("PRISMAL_TUI_TOKEN", TOKEN)
    monkeypatch.setenv("PRISMAL_TUI_ORG_ID", "acme")
    monkeypatch.setenv("PRISMAL_TUI_STORE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("PRISMAL_TUI_CANCEL_KEY", "ctrl+x")
    monkeypatch.setenv("PRISMAL_TUI_LOG_LEVEL", "DEBUG")
    s = PrismalTuiSettings()
    assert s.server_url == "https://prismal.example:9000"
    assert isinstance(s.token, SecretStr)
    assert s.token.get_secret_value() == TOKEN
    assert s.org_id == "acme"
    assert s.store_path == tmp_path / "c.db"
    assert s.cancel_key == "ctrl+x"
    assert s.log_level == "DEBUG"


def test_token_is_never_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISMAL_TUI_TOKEN", TOKEN)
    s = PrismalTuiSettings()
    assert TOKEN not in repr(s)
    assert TOKEN not in str(s)
    assert TOKEN not in s.model_dump_json()


@pytest.mark.parametrize(
    "url",
    ["localhost:8000", "ftp://host", "/relative/path", "http://", "not a url", ""],
)
def test_server_url_must_be_absolute_http_url(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_SERVER_URL", url)
    with pytest.raises(ConfigurationError, match="PRISMAL_TUI_SERVER_URL"):
        load_settings()


@pytest.mark.parametrize("url", ["http://localhost:8000", "https://a.b/prefix/"])
def test_server_url_accepts_http_and_https(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_SERVER_URL", url)
    monkeypatch.setenv("PRISMAL_TUI_STORE_PATH", str(tmp_path / "c.db"))
    assert load_settings().server_url == url


@pytest.mark.parametrize("key", ["escape", "ctrl+x", "f2", "ctrl+shift+c", "shift+tab"])
def test_cancel_key_accepts_known_textual_key_names(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_CANCEL_KEY", key)
    assert PrismalTuiSettings().cancel_key == key


@pytest.mark.parametrize(
    "key", ["esc4pe", "ctrl+", "hyperdrive", "", "a", "ctrl+banana"]
)
def test_cancel_key_rejects_unknown_or_printable_keys(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_CANCEL_KEY", key)
    with pytest.raises(ConfigurationError, match="PRISMAL_TUI_CANCEL_KEY"):
        load_settings()


def test_load_settings_creates_missing_store_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "deep" / "nested" / "conversations.db"
    monkeypatch.setenv("PRISMAL_TUI_STORE_PATH", str(target))
    s = load_settings()
    assert s.store_path == target
    assert target.parent.is_dir()
    assert not target.exists()  # only the directory; the store creates the file


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_store_parent_permission_failure_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        monkeypatch.setenv("PRISMAL_TUI_STORE_PATH", str(locked / "sub" / "c.db"))
        with pytest.raises(ConfigurationError, match="PRISMAL_TUI_STORE_PATH"):
            load_settings()
    finally:
        locked.chmod(stat.S_IRWXU)


def test_configuration_error_never_echoes_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_TOKEN", TOKEN)
    monkeypatch.setenv("PRISMAL_TUI_SERVER_URL", "nope")
    monkeypatch.setenv("PRISMAL_TUI_CANCEL_KEY", "nope")
    with pytest.raises(ConfigurationError) as info:
        load_settings()
    assert TOKEN not in str(info.value)
    assert TOKEN not in repr(info.value)


def test_invalid_log_level_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISMAL_TUI_LOG_LEVEL", "LOUD")
    with pytest.raises(ConfigurationError, match="PRISMAL_TUI_LOG_LEVEL"):
        load_settings()


# ── TUI-D-05: PRISMAL_TUI_SHOW_USAGE (SPEC-TUI-USG-009) ────────────────────


def test_show_usage_defaults_to_true() -> None:
    assert PrismalTuiSettings().show_usage is True


@pytest.mark.parametrize(
    ("raw", "value"), [("false", False), ("0", False), ("true", True)]
)
def test_show_usage_reads_the_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, value: bool
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_SHOW_USAGE", raw)
    assert PrismalTuiSettings().show_usage is value


# ── TUI-I-01: PRISMAL_TUI_PROTOCOL (SPEC-TUI-AGU-001) ──────────────────────


def test_protocol_defaults_to_native_prismal() -> None:
    assert PrismalTuiSettings().protocol == "prismal"


@pytest.mark.parametrize("raw", ["prismal", "ag-ui"])
def test_protocol_reads_the_env(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("PRISMAL_TUI_PROTOCOL", raw)
    assert PrismalTuiSettings().protocol == raw


def test_unknown_protocol_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISMAL_TUI_PROTOCOL", "websocket")
    with pytest.raises(ConfigurationError, match="PRISMAL_TUI_PROTOCOL") as info:
        load_settings()
    assert "websocket" not in str(info.value)  # never echo input values
