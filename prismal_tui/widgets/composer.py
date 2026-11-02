"""``Composer`` — message entry + slash-command recognition (SPEC-TUI-UX-001).

The submitted text is forwarded **exactly as typed** (SPEC-TUI-SES-004);
whitespace-only input is simply not sent. Anything starting with ``/`` is a
command and never reaches the engine.
"""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input

from prismal_tui.commands import Command, CommandError, is_command, parse_command


class Composer(Input):
    DEFAULT_CSS = """
    Composer { dock: bottom; margin: 0 1; }
    """

    class MessageSubmitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class CommandIssued(Message):
        def __init__(self, command: Command) -> None:
            super().__init__()
            self.command = command

    class Hint(Message):
        """A friendly inline note (unknown command, bad usage)."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__(
            placeholder="Message prismal…  (/help for commands)", id="composer"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value
        self.clear()
        if not value.strip():
            return
        if is_command(value):
            try:
                self.post_message(self.CommandIssued(parse_command(value)))
            except CommandError as exc:
                self.post_message(self.Hint(str(exc)))
            return
        self.post_message(self.MessageSubmitted(value))
