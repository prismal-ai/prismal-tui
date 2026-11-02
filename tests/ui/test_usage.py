"""TUI-D-05..08 — usage readout and ``/usage`` (SPEC-TUI-USG-002, -005..-010).

Offline: fake SDK client (scripted ``DoneEvent.usage`` + ``usage()``) and a
tmp-file store, driven through Textual's Pilot.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta

from prismal_sdk import (
    BudgetExceededError,
    DoneEvent,
    InvalidRequestError,
    PrismalAPIError,
    PrismalConnectionError,
    TokenEvent,
    Usage,
    UsageReport,
)

from prismal_tui.errors import (
    BUDGET_REACHED,
    UNEXPECTED,
    UNREACHABLE,
    USAGE_BAD_WINDOW,
    USAGE_UNSUPPORTED,
)
from prismal_tui.widgets.usage_modal import UsageScreen
from tests.fakes import FakeAsyncPrismalClient, FakeTurn
from tests.ui.conftest import AppFactory, settle, submit
from tests.usage_payloads import FAKE_USAGE, GATEWAY_USAGE, USAGE_REPORT

FAKE_READOUT = "last: 10/5 tok · cache 0% · $?  session: 15 tok · $?"
WIDE = (220, 40)


def _toasts(app: object) -> list[tuple[str, str]]:
    return [(n.message, n.severity) for n in app._notifications]  # type: ignore[attr-defined]  # noqa: SLF001


def _report() -> UsageReport:
    return UsageReport.model_validate(USAGE_REPORT)


async def _command(pilot: object, text: str) -> None:
    await submit(pilot, text)  # type: ignore[arg-type]
    await settle(pilot)  # type: ignore[arg-type]


# ── readout (USG-002, -005, -009) ──────────────────────────────────────────


async def test_readout_appears_after_a_turn_with_usage(make_app: AppFactory) -> None:
    usage = Usage(**FAKE_USAGE)
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("a", usage=usage), FakeTurn.text("b", usage=usage)]
    )
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        assert "last:" not in app.statusbar.text
        await submit(pilot, "q1")
        assert FAKE_READOUT in app.statusbar.text
        await submit(pilot, "q2")
        assert "session: 30 tok" in app.statusbar.text


async def test_missing_usage_keeps_previous_readout_marked_na(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("a", usage=Usage(**FAKE_USAGE)), FakeTurn.text("v01")]
    )
    app = make_app(fake)
    async with app.run_test(size=WIDE, notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q1")
        await submit(pilot, "q2")
        text = app.statusbar.text
        assert "last: 10/5 tok · cache 0% · $? (n/a)  session: 15 tok" in text
        assert _toasts(app) == []  # fail-open: no error
        assert app.transcript().turns[-1].text == "v01"


async def test_readout_follows_the_active_conversation(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("a", usage=Usage(**GATEWAY_USAGE))]
    )
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        assert "last: 1,200/300 tok" in app.statusbar.text
        await _command(pilot, "/new other")
        assert "last:" not in app.statusbar.text
        await _command(pilot, "/switch default")
        assert "last: 1,200/300 tok" in app.statusbar.text


async def test_show_usage_false_hides_readout_but_keeps_command(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("a", usage=Usage(**FAKE_USAGE))],
        usage_reports=[_report()],
    )
    app = make_app(fake, show_usage=False)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        assert "last:" not in app.statusbar.text
        await _command(pilot, "/usage")
        assert isinstance(app.screen, UsageScreen)


async def test_budget_mid_stream_keeps_partial_text_and_counts_partial_usage(
    make_app: AppFactory,
) -> None:
    partial = Usage(**{**FAKE_USAGE, "completion_tokens": 3, "total_tokens": 13})
    budget = BudgetExceededError(
        402, "budget_exceeded", "turn budget exhausted", usage=partial
    )
    fake = FakeAsyncPrismalClient(turns=[FakeTurn([TokenEvent(delta="half"), budget])])
    app = make_app(fake)
    async with app.run_test(size=WIDE, notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        view = app.transcript()
        assert view.turns[0].markdown_sources() == ["half"]
        assert BUDGET_REACHED in view.notes
        assert (BUDGET_REACHED, "error") in _toasts(app)
        assert "last: 10/3 tok" in app.statusbar.text


# ── /usage (USG-006, -007) ─────────────────────────────────────────────────


async def test_usage_queries_the_active_thread_since_conversation_creation(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("a")], usage_reports=[_report()])
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        await _command(pilot, "/usage")
        conv = await app.store.get(app.active_id or "")
        assert conv is not None
        assert fake.usage_calls == [{"thread_id": "thread-1", "since": conv.created_at}]
        screen = app.screen
        assert isinstance(screen, UsageScreen)
        assert "Usage — 'default'" in screen.text
        assert "Total tokens" in screen.text and "61,100" in screen.text
        assert "Turns: 1" in screen.text
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, UsageScreen)
        assert app.focused is app.composer


async def test_usage_before_any_message_explains_and_does_not_call(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await _command(pilot, "/usage")
        assert fake.usage_calls == []
        assert any("No usage yet" in n for n in app.transcript().notes)


async def test_usage_all_queries_the_tenant_since_local_midnight(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(usage_reports=[_report()])
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await _command(pilot, "/usage all")
        midnight = (
            datetime.now()
            .astimezone()
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        (call,) = fake.usage_calls
        assert call["thread_id"] is None
        assert call["since"] == midnight and call["since"].tzinfo is UTC
        screen = app.screen
        assert isinstance(screen, UsageScreen)
        assert "Turns" not in screen.text and "By model" in screen.text


async def test_usage_never_polls_while_streaming(make_app: AppFactory) -> None:
    gate = asyncio.Event()
    turn = FakeTurn(
        [
            TokenEvent(delta="a"),
            TokenEvent(delta="b"),
            DoneEvent(
                thread_id="thread-1", finish_reason="stop", usage=Usage(**FAKE_USAGE)
            ),
        ],
        gate=gate,
    )
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await submit(pilot, "q", wait=False)
        for _ in range(30):
            await pilot.pause(0.01)
        assert app.sessions.get(app.active_id or "").in_flight
        gate.set()
        await settle(pilot)
        assert fake.usage_calls == []  # readout comes from done.usage only


# ── errors (USG-008) ───────────────────────────────────────────────────────


async def _usage_failure(
    make_app: AppFactory, exc: BaseException
) -> tuple[list[tuple[str, str]], str]:
    """Run ``/usage`` against a failing fake; returns (toasts, status text)."""
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("a")], usage_reports=[exc])
    app = make_app(fake)
    async with app.run_test(size=WIDE, notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        await _command(pilot, "/usage")
        assert not isinstance(app.screen, UsageScreen)
        assert app.composer.disabled is False  # still usable
        return _toasts(app), app.statusbar.text


async def test_usage_on_a_v01_server_toasts_the_upgrade_hint(
    make_app: AppFactory,
) -> None:
    toasts, _ = await _usage_failure(
        make_app, PrismalAPIError(404, "not_found", "nope")
    )
    assert (USAGE_UNSUPPORTED, "warning") in toasts


async def test_usage_bad_window_toasts(make_app: AppFactory) -> None:
    exc = InvalidRequestError(400, "invalid_window", "since > until secret-detail")
    toasts, _ = await _usage_failure(make_app, exc)
    assert (USAGE_BAD_WINDOW, "warning") in toasts
    assert all("secret-detail" not in m for m, _ in toasts)


async def test_usage_connection_error_toasts_and_marks_disconnected(
    make_app: AppFactory,
) -> None:
    toasts, status = await _usage_failure(make_app, PrismalConnectionError("down"))
    assert (UNREACHABLE, "warning") in toasts
    assert "disconnected" in status


async def test_usage_unexpected_error_is_friendly_and_logged_without_text(
    make_app: AppFactory, caplog: object
) -> None:
    toasts, _ = await _usage_failure(make_app, RuntimeError("leaky secret-detail"))
    assert (UNEXPECTED, "warning") in toasts
    assert "secret-detail" not in caplog.text  # type: ignore[attr-defined]


# ── persistence (USG-001) & responsiveness (NFR-004) ───────────────────────


async def test_store_file_holds_no_usage_fields(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("a", usage=Usage(**GATEWAY_USAGE))]
    )
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        path = app.store.path
    with closing(sqlite3.connect(path)) as db:
        cols = {row[1] for row in db.execute("PRAGMA table_info(conversations)")}
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert cols == {"id", "name", "thread_id", "created_at", "last_active_at"}
    assert not any("usage" in t for t in tables)
    for side in path.parent.glob(path.name + "*"):
        raw = side.read_bytes()
        for needle in (b"cost_usd", b"prompt_tokens", b"openrouter", b"0.004321"):
            assert needle not in raw, (side.name, needle)


async def test_slow_usage_does_not_block_the_composer(make_app: AppFactory) -> None:
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("a")], usage_reports=[_report()], usage_gate=gate
    )
    app = make_app(fake)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        await submit(pilot, "/usage", wait=False)
        for _ in range(20):
            if fake.usage_calls:
                break
            await pilot.pause(0.01)
        assert fake.usage_calls  # call is pending on the gate
        start = time.perf_counter()
        await pilot.press(*"still typing")
        assert time.perf_counter() - start < 1.0
        assert app.composer.value == "still typing"
        assert not isinstance(app.screen, UsageScreen)
        gate.set()
        await settle(pilot)
        assert isinstance(app.screen, UsageScreen)


async def test_help_lists_usage(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await pilot.press("f1")
        await pilot.pause()
        assert "/usage [all]" in app.screen.text  # type: ignore[attr-defined]


async def test_since_fallback_is_ninety_days_when_created_at_unknown() -> None:
    from prismal_tui.app import usage_since

    now = datetime(2026, 11, 2, 12, tzinfo=UTC)
    assert usage_since(None, now=now) == now - timedelta(days=90)
    created = datetime(2026, 10, 1, tzinfo=UTC)
    assert usage_since(created, now=now) == created
