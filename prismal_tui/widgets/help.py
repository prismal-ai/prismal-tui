"""``HelpScreen`` — key-binding cheatsheet + slash commands (SPEC-TUI-UX-004)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from prismal_tui.commands import COMMANDS


def help_text(cancel_key: str) -> str:
    keys = [
        (cancel_key, "Cancel the answer in progress"),
        ("ctrl+n", "New conversation"),
        ("tab", "Move between the sidebar and the composer"),
        ("↑ / ↓, enter", "Pick a conversation in the sidebar"),
        ("f1", "Show / close this help"),
        ("ctrl+q", "Quit"),
    ]
    lines = ["Keys", ""]
    lines += [f"  {key:<16} {what}" for key, what in keys]
    lines += ["", "Commands", ""]
    lines += [f"  {c.usage:<16} {c.summary}" for c in COMMANDS]
    lines += ["", "Press Esc or F1 to close."]
    return "\n".join(lines)


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Vertical {
        width: auto; height: auto; max-width: 90%; max-height: 90%;
        padding: 1 2; border: round $accent; background: $surface;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("f1", "close", "Close", show=False, priority=True),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(self, cancel_key: str) -> None:
        super().__init__()
        self.text = help_text(cancel_key)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.text, markup=False, id="help-text")

    def action_close(self) -> None:
        self.dismiss(None)
