"""TUI-02-01/04/05/06/07 — Pilot-driven app tests (SPEC-TUI-APP-*, UX-*, SES-*)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from prismal_sdk import (
    BudgetExceededError,
    DoneEvent,
    PrismalConnectionError,
    TokenEvent,
    ToolCallEvent,
)
from textual.widgets import Markdown

from prismal_tui.app import CANCELLED_NOTE, PrismalTuiApp
from prismal_tui.errors import BUDGET_REACHED, STILL_ANSWERING, UNREACHABLE
from prismal_tui.settings import PrismalTuiSettings
from prismal_tui.store.conversation_store import ConversationStore
from prismal_tui.widgets.transcript import ActivityLine, UserMessage
from tests.fakes import FakeAsyncPrismalClient, FakeTurn
from tests.ui.conftest import AppFactory, settle, submit


async def _wait(predicate: object, pilot: object, tries: int = 200) -> None:
    for _ in range(tries):
        if predicate():  # type: ignore[operator]
            return
        await pilot.pause(0.01)  # type: ignore[attr-defined]
    raise AssertionError("condition not reached")


def _gated(*deltas: str) -> tuple[FakeTurn, asyncio.Event]:
    gate = asyncio.Event()
    items = [TokenEvent(delta=d) for d in deltas]
    items.append(DoneEvent(thread_id="thread-1", finish_reason="stop"))  # type: ignore[arg-type]
    return FakeTurn(items, gate=gate), gate  # type: ignore[arg-type]


# ── TUI-02-01: boot, health, shutdown ──────────────────────────────────────


async def test_boots_with_a_default_conversation_and_connects(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        assert fake.health_calls == 1
        assert app.statusbar.connection == "connected"
        assert app.sidebar.names == ["default"]
        assert app.focused is app.composer


async def test_failed_health_check_degrades_but_app_starts(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        health_error=PrismalConnectionError("[Errno 111] refused"),
        turns=[FakeTurn.text("still works")],
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.statusbar.connection == "disconnected"
        assert UNREACHABLE in app.statusbar.text
        assert "Errno" not in app.statusbar.text
        await submit(pilot, "hi")  # retried on the next send
        assert app.transcript().turns[0].text == "still works"
        assert app.statusbar.connection == "connected"


async def test_statusbar_shows_host_only_never_credentials(
    make_app: AppFactory,
) -> None:
    app = make_app(server_url="https://user:pw@prismal.example:8443/x?token=abc")
    async with app.run_test() as pilot:
        await settle(pilot)
        text = app.statusbar.text
        assert "prismal.example:8443" in text
        assert "pw" not in text and "abc" not in text and "user" not in text


async def test_quit_closes_client_and_store(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "/quit", wait=False)
        await pilot.pause()
    assert fake.closed
    assert app.store._closed  # noqa: SLF001


async def test_ctrl_q_quits_cleanly(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("ctrl+q")
        await pilot.pause()
    assert fake.closed


# ── TUI-02-07: a streamed turn renders ─────────────────────────────────────


async def test_message_streams_and_finalizes_as_markdown(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("# Title\n", "- item ", "`code`", thread_id="thread-1")]
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "  exact [b]text[/b]  ")
        view = app.transcript()
        assert [u.text for u in view.query(UserMessage)] == ["  exact [b]text[/b]  "]
        assert fake.sent == [("thread-1", "  exact [b]text[/b]  ")]
        turn = view.turns[0]
        assert turn.finalized
        assert turn.markdown_sources() == ["# Title\n- item `code`"]
        assert len(turn.query(Markdown)) == 1


async def test_tool_calls_render_in_stream_order(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn(
                [
                    TokenEvent(delta="Let me look. "),
                    ToolCallEvent(name="web_search", args={"q": "x"}),
                    TokenEvent(delta="Found it."),
                    DoneEvent(thread_id="thread-1", finish_reason="stop"),
                ]
            )
        ]
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        turn = app.transcript().turns[0]
        kinds = [type(w).__name__ for w in turn.children]
        assert kinds == ["Markdown", "ActivityLine", "Markdown"]
        line = turn.query_one(ActivityLine)
        assert line.tool_name == "web_search"
        assert "⚙" in str(line.render())
        assert turn.text == "Let me look. Found it."


async def test_whitespace_only_input_is_not_sent(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "   ")
        assert fake.sent == []
        assert app.transcript().turns == []


# ── SES-003 in the UI ──────────────────────────────────────────────────────


async def test_second_message_while_answering_is_rejected_inline(
    make_app: AppFactory,
) -> None:
    turn, gate = _gated("a", "b")
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "first", wait=False)
        await _wait(lambda: len(fake.sent) == 1, pilot)
        await submit(pilot, "second", wait=False)
        assert STILL_ANSWERING in app.transcript().notes
        assert len(fake.sent) == 1
        gate.set()
        await settle(pilot)
        assert app.transcript().turns[0].text == "ab"


# ── TUI-02-06: cancel key ──────────────────────────────────────────────────


async def test_escape_cancels_and_keeps_partial_text(make_app: AppFactory) -> None:
    turn, _never = _gated("partial answer", " never shown")
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "q", wait=False)
        view = app.transcript()
        await _wait(
            lambda: view.turns and view.turns[0].text == "partial answer", pilot
        )
        await pilot.press("escape")
        await settle(pilot)
        t = view.turns[0]
        assert t.finalized
        assert t.markdown_sources() == ["partial answer"]
        assert CANCELLED_NOTE in view.notes
        assert fake.streams_closed_early == 1
        assert not app.sessions.get(app.active_id or "").in_flight


async def test_cancel_key_is_configurable_and_beats_input_bindings(
    make_app: AppFactory,
) -> None:
    turn, _never = _gated("x", "y")
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake, cancel_key="ctrl+x")  # Input binds ctrl+x (cut) itself
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "q", wait=False)
        await _wait(lambda: fake.sent and app.transcript().turns[0].text == "x", pilot)
        await pilot.press("ctrl+x")
        await settle(pilot)
        assert CANCELLED_NOTE in app.transcript().notes


async def test_cancel_key_is_inactive_while_idle(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.check_action("cancel_turn", ()) is False
        await pilot.press("escape")
        await settle(pilot)
        assert CANCELLED_NOTE not in app.transcript().notes


async def test_slash_cancel(make_app: AppFactory) -> None:
    turn, _never = _gated("x", "y")
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "/cancel")
        assert "Nothing to cancel." in app.transcript().notes
        await submit(pilot, "q", wait=False)
        await _wait(lambda: bool(fake.sent), pilot)
        await submit(pilot, "/cancel")
        assert CANCELLED_NOTE in app.transcript().notes


# ── Errors keep partial text (ERR-001/003, basic; full matrix in TUI-03-02) ─


async def test_mid_stream_error_keeps_partial_and_shows_friendly_note(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn(
                [
                    TokenEvent(delta="half an answer"),
                    BudgetExceededError(402, "budget_exceeded", "tenant acme over"),
                ]
            )
        ]
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        view = app.transcript()
        assert view.turns[0].markdown_sources() == ["half an answer"]
        assert BUDGET_REACHED in view.notes
        rendered = " ".join(view.notes) + app.statusbar.text
        assert "budget_exceeded" not in rendered and "acme" not in rendered


async def test_unexpected_exception_does_not_crash_the_app(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([RuntimeError("kaboom")]), FakeTurn.text("ok")]
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "1")
        assert "kaboom" not in " ".join(app.transcript().notes)
        await submit(pilot, "2")
        assert app.transcript().turns[1].text == "ok"
        assert app.is_running


# ── Slash commands (UX-001) and the sidebar (UX-003) ───────────────────────


async def test_new_switch_rename_delete(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await settle(pilot)
        default_id = app.active_id

        await submit(pilot, "/new research")
        assert app.sidebar.names[0] == "research"
        research_id = app.active_id
        assert research_id != default_id

        await submit(pilot, "/switch DEFAULT")
        assert app.active_id == default_id

        await submit(pilot, "/rename main")
        assert "main" in app.sidebar.names and "default" not in app.sidebar.names

        await submit(pilot, "/rename research")
        assert (
            "A conversation named 'research' already exists." in app.transcript().notes
        )

        await submit(pilot, "/switch nope")
        assert "No conversation named 'nope'." in app.transcript().notes

        await submit(pilot, "/delete research")
        assert app.sidebar.names == ["main"]
        assert app.active_id == default_id

        await submit(pilot, "/delete")  # the active (last) one → fresh default
        assert app.sidebar.names == ["default"]
        assert app.active_id not in (default_id, research_id)


async def test_new_without_name_picks_a_unique_one(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "/new")
        await submit(pilot, "/new")
        assert sorted(app.sidebar.names) == ["chat-2", "chat-3", "default"]


async def test_unknown_command_is_a_hint_and_never_sent(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "/frobnicate now")
        assert any("Unknown command /frobnicate" in n for n in app.transcript().notes)
        await submit(pilot, "/switch")
        assert "Usage: /switch <name>" in app.transcript().notes
        assert fake.sent == []


async def test_sidebar_orders_by_activity_and_switches_by_keyboard(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("ok")])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "/new second")
        await submit(pilot, "/switch default")
        await submit(pilot, "hello")  # default becomes most recently active
        assert app.sidebar.names == ["default", "second"]

        app.sidebar.focus()
        await pilot.press("down", "enter")
        await settle(pilot)
        second = await app.store.get_by_name("second")
        assert second is not None and app.active_id == second.id
        assert app.focused is app.composer


async def test_background_turn_survives_switching(make_app: AppFactory) -> None:
    turn, gate = _gated("bg ", "done")
    fake = FakeAsyncPrismalClient(turns=[turn])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        first_id = app.active_id
        await submit(pilot, "slow one", wait=False)
        await _wait(lambda: bool(fake.sent), pilot)

        await submit(pilot, "/new other", wait=False)  # bg turn still gated
        await _wait(lambda: app.active_id != first_id, pilot)
        assert app.check_action("cancel_turn", ()) is False  # other is idle
        await pilot.press("escape")  # must not cancel the background turn

        gate.set()
        await settle(pilot)
        bg = app.transcript(first_id).turns[0]
        assert bg.text == "bg done"
        assert CANCELLED_NOTE not in app.transcript(first_id).notes


# ── STO-003 end-to-end: restart resumes the same thread ────────────────────


async def test_restart_resumes_the_same_thread(tmp_store_path: Path) -> None:
    def build(fake: FakeAsyncPrismalClient) -> PrismalTuiApp:
        return PrismalTuiApp(
            settings=PrismalTuiSettings(store_path=tmp_store_path),
            client=fake,
            store=ConversationStore(tmp_store_path),
        )

    first = FakeAsyncPrismalClient(turns=[FakeTurn.text("one")])
    app = build(first)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "hi")
    assert first.created_threads == ["thread-1"]

    second = FakeAsyncPrismalClient(turns=[FakeTurn.text("two")])
    second.created_threads = ["thread-1"]  # nothing new must be created
    app2 = build(second)
    async with app2.run_test() as pilot:
        await settle(pilot)
        assert any("Continuing 'default'" in n for n in app2.transcript().notes)
        await submit(pilot, "again")
    assert second.created_threads == ["thread-1"]
    assert second.sent == [("thread-1", "again")]


async def test_unexpected_error_log_has_no_exception_message(
    make_app: AppFactory, caplog: object
) -> None:
    """NFR-003: exception text may embed message content — log type + frames only."""
    import logging

    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([RuntimeError("user said: MY-PRIVATE-PROMPT")])]
    )
    app = make_app(fake)
    with caplog.at_level(logging.DEBUG, logger="prismal_tui"):  # type: ignore[attr-defined]
        async with app.run_test() as pilot:
            await settle(pilot)
            await submit(pilot, "x")
    text = caplog.text  # type: ignore[attr-defined]
    assert "RuntimeError" in text
    assert "MY-PRIVATE-PROMPT" not in text
    assert "fakes.py" in text  # frame locations kept for debugging


async def test_sidebar_refreshes_never_overlap(make_app: AppFactory) -> None:
    """Regression: overlapping/cancelled ListView rebuilds wedged the app."""
    app = make_app()
    async with app.run_test() as pilot:
        await settle(pilot)
        active = 0
        peak = 0
        calls = 0
        real_show = app.sidebar.show

        async def tracked_show(*a: object, **kw: object) -> None:
            nonlocal active, peak, calls
            active += 1
            calls += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                await real_show(*a, **kw)  # type: ignore[arg-type]
            finally:
                active -= 1

        app.sidebar.show = tracked_show  # type: ignore[method-assign]
        for _ in range(10):
            app._refresh_sidebar_later()  # noqa: SLF001
        await asyncio.gather(*(app._refresh_sidebar() for _ in range(3)))  # noqa: SLF001
        await submit(pilot, "/new x")
        await settle(pilot)
        assert peak == 1
        assert calls <= 6  # 10 deferred requests coalesced into at most two runs
        assert app.sidebar.names[0] == "x"


async def test_double_slash_sends_a_message_starting_with_slash(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("ok")])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        await submit(pilot, "//etc/hosts — what is it?")
        assert fake.sent == [("thread-1", "/etc/hosts — what is it?")]
        users = [w.text for w in app.query(UserMessage)]
        assert users == ["/etc/hosts — what is it?"]
        assert not any("Unknown command" in n for n in app.transcript().notes)


async def test_help_explains_the_slash_escape(make_app: AppFactory) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("f1")
        await pilot.pause()
        assert "//text" in app.screen.text  # type: ignore[attr-defined]
