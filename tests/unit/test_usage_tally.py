"""TUI-D-03 — ``UsageTally`` + formatting (SPEC-TUI-USG-001, -003, -004, -005)."""

from __future__ import annotations

import random
from typing import Any

import pytest
from prismal_sdk import Usage

from prismal_tui.session.usage_tally import (
    NUMERIC_FIELDS,
    UsageTally,
    add_usage,
    format_cache,
    format_cost,
    format_readout,
    format_tokens,
)
from tests.usage_payloads import FAKE_USAGE, GATEWAY_USAGE


def _u(**kw: Any) -> Usage:
    return Usage(**kw)


# ── tally ──────────────────────────────────────────────────────────────────


def test_empty_tally_has_no_usage() -> None:
    tally = UsageTally()
    assert tally.last is None and not tally.has_usage
    assert tally.session_totals == Usage()
    assert format_readout(tally) == ""


def test_first_turn_becomes_last_and_total() -> None:
    tally = UsageTally()
    usage = Usage(**FAKE_USAGE)
    tally.record(usage)
    assert tally.last == usage and tally.session_totals == usage
    assert tally.has_usage and not tally.last_missing


def test_session_totals_equal_the_field_wise_sum() -> None:
    rng = random.Random(7)
    tally = UsageTally()
    usages = [
        _u(
            **{f: rng.randint(0, 5000) for f in NUMERIC_FIELDS if f != "cost_usd"},
            cost_usd=rng.random(),
            cost_source="gateway",
            estimated=False,
        )
        for _ in range(25)
    ]
    for usage in usages:
        tally.record(usage)
    for name in NUMERIC_FIELDS:
        expected = sum(getattr(u, name) for u in usages)
        assert getattr(tally.session_totals, name) == pytest.approx(expected), name
    assert tally.last == usages[-1]
    assert tally.session_totals.cost_source == "gateway"
    assert tally.session_totals.estimated is False


def test_none_turn_keeps_totals_and_marks_last_missing() -> None:
    tally = UsageTally()
    usage = Usage(**FAKE_USAGE)
    tally.record(usage)
    tally.record(None)
    assert tally.session_totals == usage and tally.last == usage
    assert tally.last_missing
    tally.record(usage)
    assert not tally.last_missing
    assert tally.session_totals.total_tokens == 30


def test_mixed_sources_and_any_estimate_propagate() -> None:
    tally = UsageTally()
    tally.record(Usage(**GATEWAY_USAGE))  # exact, gateway
    tally.record(Usage(**FAKE_USAGE))  # estimated, none
    totals = tally.session_totals
    assert totals.cost_source == "mixed" and totals.estimated is True
    assert totals.served_model is None and totals.gateway is None


def test_same_model_is_kept_in_totals() -> None:
    a = add_usage(Usage(**GATEWAY_USAGE), Usage(**GATEWAY_USAGE))
    assert a.served_model == "anthropic/claude-sonnet-4.5"
    assert a.gateway == "openrouter" and a.cost_source == "gateway"


def test_tally_is_plain_memory_with_no_persistence_hooks() -> None:
    # USG-001: in-memory only — nothing here knows about the store.
    import prismal_tui.session.usage_tally as mod

    assert "store" not in vars(mod) and "sqlite3" not in vars(mod)


# ── formatting goldens ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("n", "text"), [(0, "0"), (15, "15"), (1500, "1,500"), (2000100, "2,000,100")]
)
def test_tokens_use_thousands_separators(n: int, text: str) -> None:
    assert format_tokens(n) == text


@pytest.mark.parametrize(
    ("usage", "text"),
    [
        (_u(prompt_tokens=0, cache_read_tokens=0), "—"),
        (_u(prompt_tokens=1200, cache_read_tokens=800), "67%"),
        (_u(prompt_tokens=10, cache_read_tokens=0), "0%"),
        (_u(prompt_tokens=10, cache_read_tokens=10), "100%"),
    ],
)
def test_cache_percent_comes_from_cache_hit_ratio(usage: Usage, text: str) -> None:
    assert format_cache(usage) == text


@pytest.mark.parametrize(
    ("usage", "text"),
    [
        (_u(cost_usd=0.004321, cost_source="gateway", estimated=False), "$0.0043"),
        (_u(cost_usd=0.004321, cost_source="litellm", estimated=True), "~$0.0043"),
        (_u(cost_usd=0.41234, cost_source="table", estimated=False), "$0.41"),
        (_u(cost_usd=1234.5, cost_source="gateway", estimated=False), "$1,234.50"),
        (_u(cost_usd=0.0, cost_source="gateway", estimated=False), "$0.00"),
        (
            _u(cost_usd=0.02, cost_source="subscription", estimated=False),
            "~$0.02 (plan)",
        ),
        (_u(cost_usd=0.0, cost_source="none", estimated=True), "$?"),
        (_u(cost_usd=0.4123, cost_source="mixed", estimated=True), "~$0.41*"),
        (_u(cost_usd=0.4123, cost_source="mixed", estimated=False), "$0.41*"),
        (_u(cost_usd=0.5, cost_source="some-future-source", estimated=False), "$0.50"),
    ],
)
def test_cost_labels(usage: Usage, text: str) -> None:
    assert format_cost(usage) == text


def test_readout_after_a_fake_mode_turn() -> None:
    tally = UsageTally()
    tally.record(Usage(**FAKE_USAGE))
    assert (
        format_readout(tally) == "last: 10/5 tok · cache 0% · $?  session: 15 tok · $?"
    )


def test_readout_with_large_numbers_and_mixed_session() -> None:
    tally = UsageTally()
    tally.record(Usage(**GATEWAY_USAGE))
    tally.record(
        Usage(**{**GATEWAY_USAGE, "cost_source": "litellm", "estimated": True})
    )
    assert format_readout(tally) == (
        "last: 1,200/300 tok · cache 67% · ~$0.0043  session: 3,000 tok · ~$0.0086*"
    )


def test_readout_reasoning_only_output() -> None:
    tally = UsageTally()
    tally.record(
        _u(
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=42,
            total_tokens=42,
            cost_usd=0.001,
            cost_source="gateway",
            estimated=False,
        )
    )
    assert format_readout(tally) == (
        "last: 0/0 tok · cache — · $0.0010  session: 42 tok · $0.0010"
    )


def test_readout_marks_a_turn_without_usage_na() -> None:
    tally = UsageTally()
    tally.record(None)
    assert format_readout(tally) == "last: (n/a)"
    tally.record(Usage(**FAKE_USAGE))
    tally.record(None)
    assert format_readout(tally) == (
        "last: 10/5 tok · cache 0% · $? (n/a)  session: 15 tok · $?"
    )
