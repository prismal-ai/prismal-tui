"""``StatusBar`` — connection, activity, last message and key hints.

SPEC-TUI-APP-004 (connection state), SPEC-TUI-ERR-001/002 (friendly error
line — the app also raises a toast), TUI-03-01 (key-binding hints),
SPEC-TUI-USG-002/009 (usage readout, hidden with ``show_usage=False``). Only
friendly text and the server's ``host:port`` ever reach it — never a URL
with credentials, a token, an error code or a server message.
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

    def __init__(
        self, server: str, *, cancel_key: str, show_usage: bool = True
    ) -> None:
        super().__init__("", markup=False, id="statusbar")
        self.server = server
        self.cancel_key = cancel_key
        self.connection: Connection = "connecting"
        self.message = ""
        self.busy = False
        self.show_usage = show_usage
        self.usage = ""
        self._render_line()

    def set_connection(self, connection: Connection) -> None:
        self.connection = connection
        self._render_line()

    def set_message(self, message: str) -> None:
        self.message = message
        self._render_line()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._render_line()

    def set_usage(self, readout: str) -> None:
        self.usage = readout
        self._render_line()

    @property
    def hints(self) -> str:
        if self.busy:
            return f"{self.cancel_key} cancel · F1 help"
        return "F1 help · ctrl+n new · ctrl+q quit"

    def _render_line(self) -> None:
        parts = [f"{_ICONS[self.connection]} {self.server}"]
        if self.busy:
            parts.append("answering…")
        if self.message:
            parts.append(self.message)
        if self.show_usage and self.usage:
            parts.append(self.usage)
        parts.append(self.hints)
        self.update(" · ".join(parts))

    @property
    def text(self) -> str:
        return str(self.render())
