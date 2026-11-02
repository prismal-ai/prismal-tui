"""TUI-02-04 — slash-command parsing (SPEC-TUI-UX-001)."""

from __future__ import annotations

import pytest

from prismal_tui.commands import (
    COMMANDS,
    Command,
    CommandError,
    is_command,
    parse_command,
)


@pytest.mark.parametrize(
    ("text", "name", "arg"),
    [
        ("/new", "new", None),
        ("/new  research notes ", "new", "research notes"),
        ("/switch research", "switch", "research"),
        ("/rename  better name", "rename", "better name"),
        ("/delete", "delete", None),
        ("/delete old", "delete", "old"),
        ("/cancel", "cancel", None),
        ("/quit", "quit", None),
        ("/help", "help", None),
        ("/HELP", "help", None),
    ],
)
def test_parses_known_commands(text: str, name: str, arg: str | None) -> None:
    assert parse_command(text) == Command(name, arg)


@pytest.mark.parametrize("text", ["/switch", "/switch   ", "/rename"])
def test_missing_required_argument_is_a_usage_hint(text: str) -> None:
    with pytest.raises(CommandError, match="Usage: /"):
        parse_command(text)


@pytest.mark.parametrize("text", ["/cancel now", "/quit please", "/help me"])
def test_unexpected_argument_is_a_usage_hint(text: str) -> None:
    with pytest.raises(CommandError, match="Usage: /"):
        parse_command(text)


@pytest.mark.parametrize("text", ["/frobnicate", "/", "/ new", "/new-ish"])
def test_unknown_command_is_a_friendly_hint_not_a_message(text: str) -> None:
    with pytest.raises(CommandError, match="Unknown command.*?/help"):
        parse_command(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("/new", True), ("  /new", False), ("hello /new", False), ("", False)],
)
def test_is_command_only_for_a_leading_slash(text: str, expected: bool) -> None:
    assert is_command(text) is expected


def test_registry_covers_the_spec_set_with_help_text() -> None:
    assert [c.name for c in COMMANDS] == [
        "new",
        "switch",
        "rename",
        "delete",
        "cancel",
        "quit",
        "help",
    ]
    assert all(c.summary and c.usage.startswith(f"/{c.name}") for c in COMMANDS)
