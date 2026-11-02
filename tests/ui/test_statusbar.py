"""TUI-03-01 — status bar: connection, toasts, key hints (ERR-001/002, APP-004)."""

from __future__ import annotations

import asyncio

from prismal_sdk import DoneEvent, PolicyDeniedError, PrismalConnectionError, TokenEvent

from prismal_tui.errors import REQUEST_REFUSED, UNREACHABLE
from tests.fakes import FakeAsyncPrismalClient, FakeTurn
from tests.ui.conftest import AppFactory, settle, submit


def _toasts(app: object) -> list[tuple[str, str]]:
    return [(n.message, n.severity) for n in app._notifications]  # type: ignore[attr-defined]  # noqa: SLF001


async def test_idle_hints_show_help_new_and_quit(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await settle(pilot)
        hints = app.statusbar.hints
        assert "F1 help" in hints and "ctrl+n new" in hints and "ctrl+q quit" in hints
        assert "cancel" not in hints
        assert app.statusbar.hints in app.statusbar.text


async def test_in_flight_shows_answering_and_the_configured_cancel_key(
    make_app: AppFactory,
) -> None:
    gate = asyncio.Event()
    turn = FakeTurn(
        [TokenEvent(delta="a"), DoneEvent(thread_id="thread-1", finish_reason="stop")],
        gate=gate,
    )
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake, cancel_key="ctrl+x")
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "q", wait=False)
        for _ in range(100):
            if "answering" in app.statusbar.text:
                break
            await pilot.pause(0.01)
        assert "answering" in app.statusbar.text
        assert "ctrl+x cancel" in app.statusbar.hints
        gate.set()
        await settle(pilot)
        assert "answering" not in app.statusbar.text
        assert "cancel" not in app.statusbar.hints


async def test_turn_error_is_a_toast_and_a_status_message(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn([PolicyDeniedError(403, "policy_denied", "rule pii-7 matched")]),
            FakeTurn.text("fine"),
        ]
    )
    app = make_app(fake)
    async with app.run_test(notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        assert (REQUEST_REFUSED, "error") in _toasts(app)
        assert REQUEST_REFUSED in app.statusbar.text
        assert "pii-7" not in app.statusbar.text
        await submit(pilot, "again")  # a successful turn clears the error line
        assert REQUEST_REFUSED not in app.statusbar.text


async def test_connection_error_flips_to_disconnected_then_recovers(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([PrismalConnectionError("refused")]), FakeTurn.text("ok")]
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.statusbar.connection == "connected"
        await submit(pilot, "1")
        assert app.statusbar.connection == "disconnected"
        assert UNREACHABLE in app.statusbar.text
        await submit(pilot, "2")
        assert app.statusbar.connection == "connected"


async def test_startup_disconnect_is_a_warning_toast(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(health_error=PrismalConnectionError("x"))
    app = make_app(fake)
    async with app.run_test(notifications=True) as pilot:
        await settle(pilot)
        assert (UNREACHABLE, "warning") in _toasts(app)
