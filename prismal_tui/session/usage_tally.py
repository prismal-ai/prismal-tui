"""``UsageTally`` and usage formatting (SPEC-TUI-USG-001, -003, -004, -005).

The TUI only **displays** the host's numbers. It never prices, re-computes or
persists them; the server is the source of truth. The tally is a
per-conversation, in-memory sum that resets when the process restarts and is
never written to ``ConversationStore``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prismal_sdk import Usage

#: Summed field-wise across turns (USG-001).
NUMERIC_FIELDS: tuple[str, ...] = (
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
    "calls",
    "cost_usd",
)

MIXED = "mixed"


def _same_or(a: str | None, b: str | None, fallback: str | None) -> str | None:
    return a if a == b else fallback


def add_usage(a: Usage, b: Usage) -> Usage:
    """Field-wise sum. Differing cost sources become ``mixed``."""
    sums = {name: getattr(a, name) + getattr(b, name) for name in NUMERIC_FIELDS}
    return Usage(
        **sums,
        cost_source=_same_or(a.cost_source, b.cost_source, MIXED) or MIXED,
        estimated=a.estimated or b.estimated,
        served_model=_same_or(a.served_model, b.served_model, None),
        gateway=_same_or(a.gateway, b.gateway, None),
    )


@dataclass
class UsageTally:
    """Last turn's usage plus the running session total for one conversation."""

    last: Usage | None = None
    session_totals: Usage = field(default_factory=Usage)
    reported_turns: int = 0
    #: The most recent turn reported no usage (USG-005: shown as ``(n/a)``).
    last_missing: bool = False

    @property
    def has_usage(self) -> bool:
        return self.reported_turns > 0

    def record(self, usage: Usage | None) -> None:
        if usage is None:  # fail-open: keep the previous readout
            self.last_missing = True
            return
        self.last_missing = False
        self.last = usage
        self.session_totals = (
            add_usage(self.session_totals, usage) if self.has_usage else usage
        )
        self.reported_turns += 1


def format_tokens(n: int) -> str:
    return f"{n:,}"


def format_cache(usage: Usage) -> str:
    """Cache % from ``Usage.cache_hit_ratio``; ``—`` with no prompt tokens."""
    if usage.prompt_tokens == 0:
        return "—"
    return f"{usage.cache_hit_ratio * 100:.0f}%"


def _money(x: float) -> str:
    if 0 < x < 0.01:
        return f"{x:.4f}"
    return f"{x:,.2f}"


def format_cost(usage: Usage) -> str:
    source = usage.cost_source
    if source == "none":
        return "$?"
    if source == "subscription":
        return f"~${_money(usage.cost_usd)} (plan)"
    text = f"{'~' if usage.estimated else ''}${_money(usage.cost_usd)}"
    return f"{text}*" if source == MIXED else text


def format_last(usage: Usage) -> str:
    return (
        f"{format_tokens(usage.prompt_tokens)}/"
        f"{format_tokens(usage.completion_tokens)} tok · "
        f"cache {format_cache(usage)} · {format_cost(usage)}"
    )


def format_readout(tally: UsageTally) -> str:
    """The status-bar segment (USG-002); empty before any turn finished."""
    if tally.last is None:
        return "last: (n/a)" if tally.last_missing else ""
    last = format_last(tally.last)
    if tally.last_missing:
        last += " (n/a)"
    totals = tally.session_totals
    session = f"{format_tokens(totals.total_tokens)} tok · {format_cost(totals)}"
    return f"last: {last}  session: {session}"
