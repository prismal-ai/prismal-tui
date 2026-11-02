"""Pilot harness helpers (offline: fake SDK client + tmp-file store)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from textual.pilot import Pilot
from textual.worker import WorkerState

from prismal_tui.app import PrismalTuiApp
from prismal_tui.settings import PrismalTuiSettings
from prismal_tui.store.conversation_store import ConversationStore
from tests.fakes import FakeAsyncPrismalClient

AppFactory = Callable[..., PrismalTuiApp]


@pytest.fixture
def make_app(tmp_store_path: Path) -> AppFactory:
    def build(
        client: FakeAsyncPrismalClient | None = None, **settings: Any
    ) -> PrismalTuiApp:
        cfg = PrismalTuiSettings(store_path=tmp_store_path, **settings)
        return PrismalTuiApp(
            settings=cfg,
            client=client or FakeAsyncPrismalClient(),
            store=ConversationStore(tmp_store_path),
        )

    return build


SETTLE_TIMEOUT = 10.0


def _dump_tasks() -> str:
    import io

    out = io.StringIO()
    for task in asyncio.all_tasks():
        out.write(f"--- {task.get_name()} {task.get_coro()!r}\n")
        task.print_stack(file=out)
    return out.getvalue()


async def _all_workers_done(pilot: Pilot[Any]) -> None:
    # Exclusive workers (sidebar refresh) may be replaced/cancelled mid-wait,
    # and pending ones can't be awaited yet: poll until none is active.
    while True:
        active = [
            w
            for w in pilot.app.workers
            if w.state in (WorkerState.PENDING, WorkerState.RUNNING)
        ]
        if not active:
            return
        running = [w for w in active if w.state == WorkerState.RUNNING]
        if running:
            await asyncio.gather(*(w.wait() for w in running), return_exceptions=True)
        else:
            await pilot.pause()


async def settle(pilot: Pilot[Any]) -> None:
    """Wait for all workers, failing loudly (with task stacks) if one hangs."""
    try:
        await asyncio.wait_for(_all_workers_done(pilot), SETTLE_TIMEOUT)
    except TimeoutError:
        raise AssertionError("workers did not settle:\n" + _dump_tasks()) from None
    await pilot.pause()


async def submit(pilot: Pilot[Any], text: str, *, wait: bool = True) -> None:
    app = pilot.app
    assert isinstance(app, PrismalTuiApp)
    app.composer.focus()
    app.composer.value = text
    await pilot.press("enter")
    if wait:
        await settle(pilot)
    else:
        await pilot.pause()
