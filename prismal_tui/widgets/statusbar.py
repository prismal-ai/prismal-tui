"""``StatusBar`` — connection state + a short status message (SPEC-TUI-APP-004).

Phase 2 keeps it minimal (connection + last status line); error toasts and
key-binding hints are TUI-03-01. Only friendly text and the server's
host:port ever reach it — never a URL with credentials, a token or a code.
"""

from __future__ import annotations

from typing import Literal

from textual.widgets import Static

Connection = Literal["connecting", "connected", "disconnected"]

_ICONS: dict[Connection, str] = {
    "connecting": "◌ connecting",
    "connected": "● connected",
    "disconnected": "○ disconnected",
}


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; padding: 0 1; background: $panel; }
    """

    def __init__(self, server: str) -> None:
        super().__init__("", markup=False, id="statusbar")
        self.server = server
        self.connection: Connection = "connecting"
        self.message = ""
        self._render_line()

    def set_connection(self, connection: Connection) -> None:
        self.connection = connection
        self._render_line()

    def set_message(self, message: str) -> None:
        self.message = message
        self._render_line()

    def _render_line(self) -> None:
        line = f"{_ICONS[self.connection]} · {self.server}"
        if self.message:
            line += f" · {self.message}"
        self.update(line)

    @property
    def text(self) -> str:
        return str(self.render())
