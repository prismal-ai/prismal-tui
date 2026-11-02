"""TUI-D-09 — usage readout and ``/usage`` against a live prismal-server 0.2.

In ``host_fake_llm_mode`` every turn ends with the RH2 FAK-002 usage
(10/5 tokens, total 15, ``cost_source = none`` → ``$?``), so the readout and
the ``/v1/usage`` totals are exact. Against a real LLM only shapes are checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from prismal_sdk import AsyncPrismalClient, DoneEvent

from prismal_tui.app import PrismalTuiApp
from prismal_tui.session import ConversationSession
from prismal_tui.settings import PrismalTuiSettings
from prismal_tui.store.conversation_store import ConversationStore
from prismal_tui.widgets.usage_modal import UsageScreen
from tests.contract.conftest import LiveHost
from tests.ui.conftest import settle, submit

pytestmark = pytest.mark.contract


async def test_done_usage_is_tallied_from_the_live_stream(
    client: AsyncPrismalClient, store: ConversationStore, live_host: LiveHost
) -> None:
    conv = await store.create("usage-tally")
    session = ConversationSession(client, store, conv.id)
    events = [e async for e in session.stream("count me")]
    done = events[-1]
    assert isinstance(done, DoneEvent) and done.usage is not None
    assert session.usage.last == done.usage
    if live_host.fake_llm:
        assert done.usage.total_tokens == 15
        assert done.usage.cost_source == "none"


async def test_readout_and_usage_report_include_the_turn(
    live_host: LiveHost, tmp_store_path: Path
) -> None:
    settings = PrismalTuiSettings(server_url=live_host.url, store_path=tmp_store_path)
    app = PrismalTuiApp(
        settings=settings,
        client=AsyncPrismalClient(live_host.url, token=live_host.token),
        store=ConversationStore(tmp_store_path),
    )
    async with app.run_test(size=(220, 40), notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "usage please")
        status = app.statusbar.text
        assert "last:" in status and "session:" in status
        if live_host.fake_llm:
            assert "last: 10/5 tok · cache 0% · $?  session: 15 tok · $?" in status

        await submit(pilot, "/usage")
        screen = app.screen
        assert isinstance(screen, UsageScreen), [
            n.message
            for n in app._notifications  # noqa: SLF001
        ]
        assert "Total tokens" in screen.text and "Turns: 1" in screen.text
        if live_host.fake_llm:
            total_line = next(
                ln for ln in screen.text.splitlines() if "Total tokens" in ln
            )
            assert total_line.rstrip().endswith("15")
            assert "fake/echo" in screen.text
        await pilot.press("escape")
        await pilot.pause()

        await submit(pilot, "/usage all")
        assert isinstance(app.screen, UsageScreen)
        assert "whole tenant" in app.screen.text
