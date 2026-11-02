"""TUI-04-02 — ConversationSession (and the app) against a live prismal-server."""

from __future__ import annotations

from pathlib import Path

import pytest
from prismal_sdk import AsyncPrismalClient, DoneEvent, PrismalAPIError, TokenEvent

from prismal_tui.app import PrismalTuiApp
from prismal_tui.errors import GENERIC, friendly_text
from prismal_tui.session import ConversationSession, SessionCancelled
from prismal_tui.settings import PrismalTuiSettings
from prismal_tui.store.conversation_store import ConversationStore
from tests.contract.conftest import LiveHost
from tests.ui.conftest import settle, submit

pytestmark = pytest.mark.contract


async def _turn(session: ConversationSession, text: str) -> tuple[str, list[object]]:
    events = [e async for e in session.stream(text)]
    return "".join(e.delta for e in events if isinstance(e, TokenEvent)), events


async def test_healthz(client: AsyncPrismalClient) -> None:
    assert (await client.healthz()).status == "ok"


async def test_streamed_turn_ends_with_done(
    client: AsyncPrismalClient, store: ConversationStore, live_host: LiveHost
) -> None:
    conv = await store.create("contract")
    text, events = await _turn(
        ConversationSession(client, store, conv.id), "hello there"
    )
    assert text
    assert isinstance(events[-1], DoneEvent)
    if live_host.fake_llm:
        assert text == "echo: hello there"


async def test_thread_is_created_once_and_reused_across_restart(
    client: AsyncPrismalClient, tmp_store_path: Path
) -> None:
    first = ConversationStore(tmp_store_path)
    conv = await first.create("persist")
    _, events = await _turn(ConversationSession(client, first, conv.id), "one")
    done = events[-1]
    assert isinstance(done, DoneEvent)
    mapped = (await first.get(conv.id)).thread_id  # type: ignore[union-attr]
    assert mapped == done.thread_id
    await first.close()

    second = ConversationStore(tmp_store_path)  # simulated restart
    try:
        _, events = await _turn(ConversationSession(client, second, conv.id), "two")
        assert isinstance(events[-1], DoneEvent)
        assert events[-1].thread_id == mapped
        assert (await second.get(conv.id)).thread_id == mapped  # type: ignore[union-attr]
    finally:
        await second.close()


async def test_cancel_then_the_thread_still_works(
    client: AsyncPrismalClient, store: ConversationStore
) -> None:
    """Cancelling closes the SDK stream; the host must accept the next turn."""
    conv = await store.create("cancel")
    session = ConversationSession(client, store, conv.id)
    seen = ""
    try:
        async for event in session.stream("please answer at some length " * 4):
            if isinstance(event, TokenEvent):
                seen += event.delta
                session.cancel()
    except SessionCancelled:
        pass  # a fast host may already have finished — both are fine
    assert not session.in_flight
    text, events = await _turn(session, "still there?")
    assert text and isinstance(events[-1], DoneEvent)


async def test_tool_call_and_error_paths_in_fake_mode(
    client: AsyncPrismalClient, store: ConversationStore, live_host: LiveHost
) -> None:
    if not live_host.fake_llm:
        pytest.skip("deterministic tool/error triggers need host_fake_llm_mode")
    conv = await store.create("fake")
    session = ConversationSession(client, store, conv.id)
    _, events = await _turn(session, "/tool weather")
    assert any(type(e).__name__ == "ToolCallEvent" for e in events)
    with pytest.raises(PrismalAPIError) as info:
        await _turn(session, "/error")
    assert friendly_text(info.value) == GENERIC
    text, _ = await _turn(session, "recovered")  # no auto-retry; manual resend works
    assert text == "echo: recovered"


async def test_app_round_trip_and_restart(
    live_host: LiveHost, tmp_store_path: Path
) -> None:
    def build() -> PrismalTuiApp:
        settings = PrismalTuiSettings(
            server_url=live_host.url, store_path=tmp_store_path
        )
        return PrismalTuiApp(
            settings=settings,
            client=AsyncPrismalClient(live_host.url, token=live_host.token),
            store=ConversationStore(tmp_store_path),
        )

    app = build()
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.statusbar.connection == "connected"
        await submit(pilot, "hi from the tui")
        first = app.transcript().turns[-1]
        assert first.finalized and first.text
        thread = (await app.store.get_by_name("default")).thread_id  # type: ignore[union-attr]

    app2 = build()
    async with app2.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "after restart")
        assert app2.transcript().turns[-1].text
        assert (await app2.store.get_by_name("default")).thread_id == thread  # type: ignore[union-attr]
