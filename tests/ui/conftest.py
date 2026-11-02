"""Pilot harness helpers (offline: fake SDK client + tmp-file store)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from textual.pilot import Pilot

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


async def settle(pilot: Pilot[Any]) -> None:
    await pilot.app.workers.wait_for_complete()
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
