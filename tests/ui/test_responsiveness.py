"""TUI-04-03 — the app stays responsive while a turn streams (SPEC-TUI-NFR-004)."""

from __future__ import annotations

import asyncio
import time

from prismal_sdk import DoneEvent, TokenEvent

from tests.fakes import FakeAsyncPrismalClient, FakeTurn
from tests.ui.conftest import AppFactory, settle, submit

TOKENS = 40
DELAY = 0.03  # ~1.2 s of streaming


def _slow_turn(finish: asyncio.Event) -> FakeTurn:
    """Tokens trickle in; the turn only completes once ``finish`` is set."""
    items: list[object] = [TokenEvent(delta=f"t{i} ") for i in range(TOKENS)]
    items.append(DoneEvent(thread_id="thread-1", finish_reason="stop"))
    return FakeTurn(items, delay=DELAY, gate=finish, gate_at=TOKENS)  # type: ignore[arg-type]


async def test_input_commands_and_loop_stay_responsive_while_streaming(
    make_app: AppFactory,
) -> None:
    finish = asyncio.Event()
    fake = FakeAsyncPrismalClient(turns=[_slow_turn(finish)])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        first_id = app.active_id

        lags: list[float] = []
        stop = asyncio.Event()

        async def probe() -> None:  # measures event-loop scheduling delay
            while not stop.is_set():
                start = time.perf_counter()
                await asyncio.sleep(0.005)
                lags.append(time.perf_counter() - start - 0.005)

        prober = asyncio.create_task(probe())
        await submit(pilot, "long answer please", wait=False)

        # Typing into the composer works mid-stream…
        app.composer.focus()
        await pilot.press("h", "e", "y")
        assert app.composer.value == "hey"
        app.composer.value = ""
        turn = app.transcript(first_id).turns[0]
        assert not turn.finalized, "stream should still be running"

        # …so do slash commands and the status bar / sidebar redraws.
        await submit(pilot, "/new side", wait=False)
        for _ in range(100):
            if app.active_id != first_id:
                break
            await pilot.pause(0.01)
        assert app.active_id != first_id
        assert not turn.finalized
        assert "side" in app.sidebar.names

        finish.set()
        await settle(pilot)
        stop.set()
        await prober

        assert turn.finalized
        assert turn.text == "".join(f"t{i} " for i in range(TOKENS))
        assert lags, "probe never ran"
        # No blocking call on the loop: worst scheduling delay stays far below
        # the stream's own pacing would reveal (generous for slow CI boxes).
        assert max(lags) < 0.25, f"event loop blocked for {max(lags):.3f}s"
