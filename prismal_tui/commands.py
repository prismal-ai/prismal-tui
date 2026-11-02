"""Slash-command registry and parser (SPEC-TUI-UX-001).

Pure parsing only — dispatch lives in ``app.py``. Input that starts with
``/`` is always treated as a command: an unknown one produces a friendly
hint and is never sent to the engine as a message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ArgSpec = Literal["none", "optional", "required"]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    arg: ArgSpec
    usage: str
    summary: str
    #: Allowed (lower-case) argument values, when the argument is a keyword.
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    arg: str | None = None


class CommandError(ValueError):
    """Friendly, user-facing parse error (unknown command / bad usage)."""


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("new", "optional", "/new [name]", "Start a new conversation"),
    CommandSpec("switch", "required", "/switch <name>", "Switch to a conversation"),
    CommandSpec("rename", "required", "/rename <name>", "Rename this conversation"),
    CommandSpec(
        "delete",
        "optional",
        "/delete [name]",
        "Forget a conversation locally (server history is kept)",
    ),
    CommandSpec(
        "usage",
        "optional",
        "/usage [all]",
        "Token usage and cost from the server (all = whole tenant, today)",
        choices=("all",),
    ),
    CommandSpec("cancel", "none", "/cancel", "Cancel the answer in progress"),
    CommandSpec("quit", "none", "/quit", "Quit prismal-tui"),
    CommandSpec("help", "none", "/help", "Show keys and commands"),
)

_BY_NAME = {spec.name: spec for spec in COMMANDS}


def is_command(text: str) -> bool:
    return text.startswith("/")


def parse_command(text: str) -> Command:
    """Parse ``/name [arg]``; raises :class:`CommandError` with a hint."""
    body = text[1:]
    name, _, rest = body.partition(" ")
    spec = _BY_NAME.get(name.lower())
    if spec is None:
        shown = f"/{name}" if name else "/"
        raise CommandError(f"Unknown command {shown} — type /help for the list.")
    arg = rest.strip() or None
    if spec.arg == "required" and arg is None:
        raise CommandError(f"Usage: {spec.usage}")
    if spec.arg == "none" and arg is not None:
        raise CommandError(f"Usage: {spec.usage}")
    if spec.choices and arg is not None:
        arg = arg.lower()
        if arg not in spec.choices:
            raise CommandError(f"Usage: {spec.usage}")
    return Command(spec.name, arg)
