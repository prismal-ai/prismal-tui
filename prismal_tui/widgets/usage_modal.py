"""``UsageScreen`` — the ``/usage`` report modal (SPEC-TUI-USG-006, -007).

Renders a ``prismal_sdk.UsageReport`` as plain text. The numbers are the
server's: nothing here prices or re-computes them, apart from the display
formatting shared with the status bar.
"""

from __future__ import annotations

from prismal_sdk import Usage, UsageReport
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from prismal_tui.session.usage_tally import MIXED, format_cost, format_tokens

_WIDTH = 24


def _row(label: str, value: str) -> str:
    return f"  {label:<{_WIDTH - 2}}{value:>14}"


def _model_row(usage: Usage) -> str:
    model = usage.served_model or "unknown model"
    gateway = usage.gateway or "direct"
    return f"  {model} · {gateway} · {usage.cost_source} · {format_cost(usage)}"


def usage_report_text(report: UsageReport, *, title: str, show_turns: bool) -> str:
    t = report.totals
    cache = "—" if t.prompt_tokens == 0 else f"{report.cache_hit_ratio * 100:.0f}%"
    lines = [title, ""]
    lines += [
        _row("Prompt tokens", format_tokens(t.prompt_tokens)),
        _row("  cache read", format_tokens(t.cache_read_tokens)),
        _row("  cache write", format_tokens(t.cache_write_tokens)),
        _row("Completion tokens", format_tokens(t.completion_tokens)),
        _row("Reasoning tokens", format_tokens(t.reasoning_tokens)),
        _row("Total tokens", format_tokens(t.total_tokens)),
        _row("Calls", format_tokens(t.calls)),
        _row("Cost", format_cost(t)),
        _row("Cost source", str(t.cost_source)),
        _row("Cache hit ratio", cache),
        "",
        "By model",
    ]
    if report.by_model:
        lines += [_model_row(m) for m in report.by_model]
    else:
        lines.append("  (no usage in this window)")
    if show_turns:
        more = " (+ more)" if report.next_cursor else ""
        lines += ["", f"Turns: {len(report.turns)}{more}"]
    if t.cost_source == MIXED:
        lines += ["", "* mixed sources"]
    lines += ["", "Press Esc to close."]
    return "\n".join(lines)


class UsageScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    UsageScreen { align: center middle; }
    UsageScreen > Vertical {
        width: auto; height: auto; max-width: 90%; max-height: 90%;
        padding: 1 2; border: round $accent; background: $surface;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(self, report: UsageReport, *, title: str, show_turns: bool) -> None:
        super().__init__()
        self.text = usage_report_text(report, title=title, show_turns=show_turns)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.text, markup=False, id="usage-text")

    def action_close(self) -> None:
        self.dismiss(None)
