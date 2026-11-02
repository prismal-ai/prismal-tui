"""TUI-03-04 — /help and F1 show the cheatsheet without leaving the app (UX-004)."""

from __future__ import annotations

import asyncio

from prismal_sdk import DoneEvent, TokenEvent

from prismal_tui.commands import COMMANDS
from prismal_tui.widgets.help import HelpScreen
from tests.fakes import FakeAsyncPrismalClient, FakeTurn
from tests.ui.conftest import AppFactory, settle, submit


async def test_slash_help_opens_the_cheatsheet(make_app: AppFactory) -> None:
    app = make_app(cancel_key="f2")
    async with app.run_test(size=(100, 40)) as pilot:
        await settle(pilot)
        await submit(pilot, "/help")
        assert isinstance(app.screen, HelpScreen)
        text = app.screen.text
        for spec in COMMANDS:
            assert spec.usage in text and spec.summary in text
        for key in ("f2", "ctrl+n", "ctrl+q", "f1", "tab"):
            assert key in text
        assert app.transcript().notes == []  # not dumped into the transcript


async def test_f1_opens_and_escape_closes(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        await settle(pilot)
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)
        assert app.focused is app.composer


async def test_escape_closes_help_without_cancelling_a_running_turn(
    make_app: AppFactory,
) -> None:
    gate = asyncio.Event()
    turn = FakeTurn(
        [TokenEvent(delta="a"), DoneEvent(thread_id="thread-1", finish_reason="stop")],
        gate=gate,
    )
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake)
    async with app.run_test(size=(100, 40)) as pilot:
        await settle(pilot)
        await submit(pilot, "q", wait=False)
        for _ in range(100):
            if fake.sent:
                break
            await pilot.pause(0.01)
        await pilot.press("f1")
        await pilot.pause()
        await pilot.press("escape")  # closes help; must not cancel the turn
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)
        assert app.sessions.get(app.active_id or "").in_flight
        gate.set()
        await settle(pilot)
        assert app.transcript().turns[0].text == "a"
        assert "— cancelled —" not in app.transcript().notes
