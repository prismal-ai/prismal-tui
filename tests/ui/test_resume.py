"""TUI-I-05 — AG-UI turns, interrupt notes and ``/resume`` in the app.

DELTA-2026-11-host-0.3: SPEC-TUI-AGU-001/002, INT-001..005, UX-004.
Offline: FakeAsyncPrismalClient + Textual Pilot.
"""

from __future__ import annotations

import asyncio

from prismal_sdk import (
    ProtocolNotEnabledError,
    ResumeConflictError,
    Usage,
    ValidationError,
)
from textual.widgets import Markdown, Static

from prismal_tui import errors
from prismal_tui.app import INTERRUPT_HINT, NOTHING_TO_RESUME, PrismalTuiApp
from prismal_tui.widgets.help import help_text
from tests.fakes import FakeAsyncPrismalClient, FakeTurn, agui_interrupt
from tests.ui.conftest import AppFactory, settle, submit

USAGE = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
SERVER_MSG = "engine leaked-detail"


def _notes(app: PrismalTuiApp) -> list[str]:
    return app.transcript().notes


def _screen_text(app: PrismalTuiApp) -> str:
    parts = [str(w.render()) for w in app.query(Static)]
    parts += [md.source for md in app.query(Markdown)]
    parts += [n.message for n in app._notifications]  # noqa: SLF001
    return "\n".join(parts)


async def test_default_protocol_never_calls_run_agui(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("hi")])
    async with make_app(fake).run_test() as pilot:
        await submit(pilot, "hello")
        assert fake.sent and fake.agui_calls == []


async def test_agui_turn_renders_like_a_native_turn(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui("Hel", "lo", tools=["search"], usage=USAGE)]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "hello")
        assert fake.agui_calls[0]["content"] == "hello"
        turn = app.transcript().turns[-1]
        assert turn.text == "Hello"
        assert "15" in app.statusbar.text


async def test_interrupt_shows_one_note_per_interrupt_and_the_hint(
    make_app: AppFactory,
) -> None:
    pending = [
        agui_interrupt("a.ck", "Deploy to prod?"),
        agui_interrupt("b.ck", None, reason="input_required"),
    ]
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui("Let me check.", interrupts=pending)]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "deploy")
        notes = _notes(app)
        assert notes[-3:] == [
            "⏸ Waiting for your answer — human_approval: Deploy to prod?",
            "⏸ Waiting for your answer — input_required",
            INTERRUPT_HINT,
        ]
        assert app.transcript().turns[-1].text == "Let me check."  # kept


async def test_resume_round_trip_sends_the_json_payload(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt("a.ck")]),
            FakeTurn.agui('resumed: {"action": "approve"}', usage=USAGE),
        ]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "deploy")
        await submit(pilot, '/resume {"action": "approve"}')
        resume = fake.agui_calls[-1]["resume"]
        assert [(e.interrupt_id, e.payload) for e in resume] == [
            ("a.ck", {"action": "approve"})
        ]
        view = app.transcript()
        assert view.turns[-1].text == 'resumed: {"action": "approve"}'
        assert app.sessions.get(app.active_id or "").open_interrupts == ()
        assert '› {"action": "approve"}' in _screen_text(app)


async def test_resume_with_text_and_without_answer(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt("a.ck1")]),
            FakeTurn.agui(interrupts=[agui_interrupt("a.ck2")]),
            FakeTurn.agui("ok"),
        ]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "go")
        await submit(pilot, "/resume yes, go ahead")
        await submit(pilot, "/resume")
        assert [c["resume"][0].payload for c in fake.agui_calls[1:]] == [
            "yes, go ahead",
            None,
        ]
        assert [c["resume"][0].interrupt_id for c in fake.agui_calls[1:]] == [
            "a.ck1",
            "a.ck2",
        ]


async def test_resume_with_nothing_open_makes_no_call(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient()
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "/resume yes")
        assert _notes(app)[-1] == NOTHING_TO_RESUME
        assert fake.agui_calls == [] and fake.created_threads == []


async def test_resume_on_the_native_protocol_has_nothing_to_answer(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("hi")])
    app = make_app(fake)
    async with app.run_test() as pilot:
        await submit(pilot, "hello")
        await submit(pilot, "/resume yes")
        assert _notes(app)[-1] == NOTHING_TO_RESUME
        assert fake.agui_calls == []


async def test_resume_while_answering_is_rejected(make_app: AppFactory) -> None:
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn.agui("a", "b", gate=gate, gate_at=3),
        ]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "first")
        await submit(pilot, "second", wait=False)
        await pilot.pause()
        await submit(pilot, "/resume yes", wait=False)
        assert _notes(app)[-1] == errors.STILL_ANSWERING
        gate.set()
        await settle(pilot)
        assert len(fake.agui_calls) == 2


async def test_conflict_shows_friendly_copy_and_clears_open_interrupts(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn([ResumeConflictError(409, "no_pending_interrupt", SERVER_MSG)]),
        ]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "go")
        await submit(pilot, "/resume yes")
        text = _screen_text(app)
        assert errors.NOTHING_PENDING_ANYMORE in text
        assert SERVER_MSG not in text and "no_pending_interrupt" not in text
        assert "409" not in text
        await submit(pilot, "/resume again")  # cleared: no second call
        assert _notes(app)[-1] == NOTHING_TO_RESUME
        assert len(fake.agui_calls) == 2


async def test_rejected_answer_keeps_interrupts_and_is_not_retried(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn([ValidationError(422, "invalid_resume", SERVER_MSG)]),
        ]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "go")
        await submit(pilot, "/resume yes")
        assert errors.ANSWER_NOT_ACCEPTED in _screen_text(app)
        assert len(fake.agui_calls) == 2  # no automatic retry
        assert app.sessions.get(app.active_id or "").open_interrupts


async def test_agui_disabled_on_the_host_shows_the_hint(make_app: AppFactory) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([ProtocolNotEnabledError(406, "protocol_not_enabled", "x")])]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "hello")
        text = _screen_text(app)
        assert errors.AGUI_NOT_ENABLED in text and "406" not in text


async def test_cancel_key_stops_a_resume_and_keeps_partial_text(
    make_app: AppFactory,
) -> None:
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn.agui("par", "tial", gate=gate, gate_at=3),
        ]
    )
    app = make_app(fake, protocol="ag-ui")
    async with app.run_test() as pilot:
        await submit(pilot, "go")
        await submit(pilot, "/resume yes", wait=False)
        await pilot.pause()
        await pilot.press("escape")
        await settle(pilot)
        turn = app.transcript().turns[-1]
        assert turn.text == "par"
        assert len(fake.agui_calls) == 2


def test_help_lists_resume() -> None:
    assert "/resume [answer]" in help_text("escape")
