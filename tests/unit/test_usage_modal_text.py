"""TUI-D-06 — ``/usage`` modal content (SPEC-TUI-USG-004, -006, -007)."""

from __future__ import annotations

from typing import Any

from prismal_sdk import UsageReport

from prismal_tui.widgets.usage_modal import usage_report_text
from tests.usage_payloads import FAKE_USAGE, USAGE_REPORT


def _report(**overrides: Any) -> UsageReport:
    return UsageReport.model_validate({**USAGE_REPORT, **overrides})


def test_thread_report_shows_every_required_total() -> None:
    text = usage_report_text(_report(), title="Usage — 'default'", show_turns=True)
    lines = text.splitlines()
    assert lines[0] == "Usage — 'default'"
    for label, value in [
        ("Prompt tokens", "52,000"),
        ("cache read", "39,000"),
        ("cache write", "4,000"),
        ("Completion tokens", "9,100"),
        ("Reasoning tokens", "1,200"),
        ("Total tokens", "61,100"),
        ("Calls", "140"),
        ("Cost", "~$0.41*"),
        ("Cost source", "mixed"),
        ("Cache hit ratio", "75%"),
    ]:
        assert any(label in ln and ln.rstrip().endswith(value) for ln in lines), label
    assert "* mixed sources" in text
    assert "anthropic/claude-sonnet-4.5 · openrouter · gateway · $0.39" in text
    assert "Turns: 1" in text and "+ more" not in text


def test_next_cursor_shows_plus_more() -> None:
    text = usage_report_text(_report(next_cursor="c2"), title="t", show_turns=True)
    assert "Turns: 1 (+ more)" in text


def test_org_report_omits_turns() -> None:
    text = usage_report_text(_report(), title="Usage — today", show_turns=False)
    assert "Turns" not in text and "By model" in text


def test_single_source_has_no_mixed_footnote_and_unknown_model_labels() -> None:
    by_model = [{**FAKE_USAGE, "served_model": None, "gateway": None}]
    report = _report(totals=FAKE_USAGE, by_model=by_model, cache_hit_ratio=0.0)
    text = usage_report_text(report, title="t", show_turns=True)
    assert "mixed sources" not in text
    assert "unknown model · direct · none · $?" in text
    assert any(
        "Cache hit ratio" in ln and ln.endswith("0%") for ln in text.splitlines()
    )


def test_empty_report_renders_dashes_and_no_models() -> None:
    empty = {
        k: (0 if isinstance(v, int) and not isinstance(v, bool) else v)
        for k, v in FAKE_USAGE.items()
    }
    report = _report(
        totals={**empty, "cost_usd": 0.0}, by_model=[], turns=[], cache_hit_ratio=0.0
    )
    text = usage_report_text(report, title="t", show_turns=True)
    assert any("Cache hit ratio" in ln and ln.endswith("—") for ln in text.splitlines())
    assert "(no usage in this window)" in text
    assert "Turns: 0" in text
