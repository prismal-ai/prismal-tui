"""``TranscriptView`` — one conversation's scrollable transcript (RF-TUI-003).

Streaming render rules (SPEC-TUI-REN-001..005, ADR-003):

- ``feed(delta)`` appends to a buffer and schedules **at most one** redraw,
  tied to Textual's own refresh cycle (``call_after_refresh``) — frame-based
  coalescing, never a time/char-interval throttle.
- Every delta lands in the next redraw; the final text is always the exact
  concatenation of all deltas (REN-002).
- Tool calls render as a dimmed ``⚙`` line in stream order (REN-003).
- In-flight text renders as plain text (never parsed as markup); on
  ``finalize`` each text segment is re-rendered as Markdown (REN-004).
- ``finalize(note=...)`` after an error/cancel keeps the partial text and
  appends a system note — it never blanks the answer (SPEC-TUI-ERR-003).

Widgets only see SDK typed models / plain values, never transport
(SPEC-TUI-APP-005).
"""

from __future__ import annotations

from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, Static


class UserMessage(Static):
    DEFAULT_CSS = """
    UserMessage { margin: 1 0 0 0; color: $text; text-style: bold; }
    """

    def __init__(self, text: str) -> None:
        super().__init__(f"› {text}", markup=False)
        self.text = text


class SystemNote(Static):
    DEFAULT_CSS = """
    SystemNote { color: $text-muted; text-style: italic; }
    """

    def __init__(self, text: str) -> None:
        super().__init__(text, markup=False)
        self.text = text


class ActivityLine(Static):
    DEFAULT_CSS = """
    ActivityLine { color: $text-muted; text-style: dim; }
    """

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"⚙ using {tool_name}…", markup=False)
        self.tool_name = tool_name


class StreamingText(Static):
    """In-flight assistant text, rendered as plain (non-markup) text."""

    def __init__(self) -> None:
        super().__init__("", markup=False)
        self.buffer = ""


class AssistantTurn(Vertical):
    """One assistant answer: text segments interleaved with activity lines."""

    DEFAULT_CSS = """
    AssistantTurn { height: auto; margin: 0 0 0 2; }
    AssistantTurn Markdown { margin: 0; padding: 0; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._segments: list[StreamingText] = []
        self._current: StreamingText | None = None
        self._redraw_pending = False
        self.redraw_count = 0
        self.finalized = False

    @property
    def text(self) -> str:
        """Everything streamed so far — the exact concatenation of deltas."""
        return "".join(s.buffer for s in self._segments)

    def feed(self, delta: str) -> None:
        if self.finalized or not delta:
            return
        if self._current is None:
            self._current = StreamingText()
            self._segments.append(self._current)
            self.mount(self._current)
        self._current.buffer += delta
        if not self._redraw_pending:
            self._redraw_pending = True
            self.call_after_refresh(self._redraw)

    def activity(self, tool_name: str) -> None:
        if self.finalized:
            return
        self._current = None  # text after the tool call starts a new segment
        self.mount(ActivityLine(tool_name))

    def _redraw(self) -> None:
        self._redraw_pending = False
        if self.finalized:
            return
        self.redraw_count += 1
        for segment in self._segments:
            segment.update(segment.buffer)

    async def finalize(self, note: str | None = None) -> None:
        """Freeze the turn: Markdown-render its text, optionally add a note."""
        if self.finalized:
            return
        self.finalized = True
        for segment in self._segments:
            await self.mount(Markdown(segment.buffer), before=segment)
            await segment.remove()
        if note:
            await self.mount(SystemNote(note))

    def markdown_sources(self) -> list[str]:
        return [md.source for md in self.query(Markdown)]


class TranscriptView(VerticalScroll):
    DEFAULT_CSS = """
    TranscriptView { height: 1fr; padding: 0 1; }
    """

    def on_mount(self) -> None:
        self.anchor()  # stay pinned to the newest output while streaming

    def add_user(self, text: str) -> None:
        self.mount(UserMessage(text))

    def add_note(self, text: str) -> None:
        self.mount(SystemNote(text))

    def begin_turn(self) -> AssistantTurn:
        turn = AssistantTurn()
        self.mount(turn)
        return turn

    @property
    def turns(self) -> list[AssistantTurn]:
        return list(self.query(AssistantTurn))

    @property
    def notes(self) -> list[str]:
        return [n.text for n in self.query(SystemNote)]
