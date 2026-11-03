"""TUI-I-03 — AG-UI turns and interrupt resume in ``ConversationSession``.

DELTA-2026-11-host-0.3: SPEC-TUI-AGU-001, SES-002 (AG-UI translation),
INT-001..005. Offline: FakeAsyncPrismalClient + a real tmp-file store.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from prismal_sdk import (
    DoneEvent,
    PrismalConnectionError,
    ResumeConflictError,
    TokenEvent,
    ToolCallEvent,
    Usage,
    ValidationError,
)
from prismal_sdk.agui import CustomEvent, StepStarted, TextMessageChunk

from prismal_tui.session import (
    ConversationSession,
    ConversationSessions,
    NothingToResume,
    SessionCancelled,
    TurnInFlightError,
    TurnInterrupted,
)
from prismal_tui.store.conversation_store import ConversationStore
from tests.fakes import FakeAsyncPrismalClient, FakeTurn, agui_interrupt

USAGE = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


@pytest.fixture
async def store(tmp_store_path: Path) -> AsyncIterator[ConversationStore]:
    s = ConversationStore(tmp_store_path)
    yield s
    await s.close()


async def _session(
    store: ConversationStore, fake: FakeAsyncPrismalClient, protocol: str = "ag-ui"
) -> ConversationSession:
    conv = await store.create("c")
    return ConversationSession(fake, store, conv.id, protocol=protocol)  # type: ignore[arg-type]


async def _drain(stream: AsyncIterator[object]) -> list[object]:
    return [e async for e in stream]


# ── AGU-001: protocol selects the SDK call ─────────────────────────────────


async def test_default_protocol_uses_native_send_message(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("hi")])
    conv = await store.create("c")
    events = await _drain(ConversationSession(fake, store, conv.id).stream("x"))
    assert fake.sent == [("thread-1", "x")] and fake.agui_calls == []
    assert isinstance(events[-1], DoneEvent)


async def test_agui_protocol_uses_run_agui_with_unmodified_text(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.agui("ok")])
    session = await _session(store, fake)
    text = "  {{raw}} /etc/hosts\n"
    await _drain(session.stream(text))
    assert fake.sent == []
    assert fake.agui_calls == [
        {"thread_id": "thread-1", "content": text, "resume": None}
    ]


# ── SES-002: AG-UI → UI events ─────────────────────────────────────────────


async def test_agui_events_translate_to_tokens_tools_and_done(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui("Hel", "lo", tools=["search"], usage=USAGE)]
    )
    session = await _session(store, fake)
    events = await _drain(session.stream("x"))
    assert events[0] == ToolCallEvent(name="search")
    assert [e.delta for e in events if isinstance(e, TokenEvent)] == ["Hel", "lo"]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.thread_id == "thread-1" and done.usage == USAGE
    assert session.usage.last == USAGE  # tallied like a native done


async def test_text_chunks_count_and_other_events_are_ignored(
    store: ConversationStore,
) -> None:
    turn = FakeTurn.agui("b")
    turn.items = [
        StepStarted(type="STEP_STARTED"),
        TextMessageChunk(type="TEXT_MESSAGE_CHUNK", delta="a"),
        TextMessageChunk(type="TEXT_MESSAGE_CHUNK"),  # no delta: ignored
        CustomEvent(type="CUSTOM", name="prismal.other", value={"k": 1}),
        *turn.items,
    ]
    session = await _session(store, FakeAsyncPrismalClient(turns=[turn]))
    events = await _drain(session.stream("x"))
    assert [type(e).__name__ for e in events] == [
        "TokenEvent",
        "TokenEvent",
        "DoneEvent",
    ]
    assert "".join(e.delta for e in events if isinstance(e, TokenEvent)) == "ab"


async def test_run_without_usage_event_is_fail_open(store: ConversationStore) -> None:
    session = await _session(store, FakeAsyncPrismalClient(turns=[FakeTurn.agui("a")]))
    events = await _drain(session.stream("x"))
    assert isinstance(events[-1], DoneEvent) and events[-1].usage is None


# ── INT-001/002: interrupted run ───────────────────────────────────────────


async def test_interrupted_run_yields_turn_interrupted_and_remembers_them(
    store: ConversationStore,
) -> None:
    pending = [agui_interrupt("a.ck1", "Deploy?"), agui_interrupt("b.ck1", None)]
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui("partial", usage=USAGE, interrupts=pending)]
    )
    session = await _session(store, fake)
    events = await _drain(session.stream("x"))
    assert isinstance(events[0], TokenEvent)
    last = events[-1]
    assert isinstance(last, TurnInterrupted)
    assert [i.id for i in last.interrupts] == ["a.ck1", "b.ck1"]
    assert [i.message for i in last.interrupts] == ["Deploy?", None]
    assert [i.id for i in session.open_interrupts] == ["a.ck1", "b.ck1"]
    assert session.usage.last == USAGE  # an interrupted run still consumed tokens
    assert not any(isinstance(e, DoneEvent) for e in events)


async def test_a_successful_run_clears_open_interrupts(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui(interrupts=[agui_interrupt()]), FakeTurn.agui("new")]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    assert session.open_interrupts
    await _drain(session.stream("plain message"))  # INT-006: sent as usual
    assert session.open_interrupts == ()


async def test_open_interrupts_are_never_persisted(
    store: ConversationStore, tmp_store_path: Path
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui(interrupts=[agui_interrupt("secret-id.ck", "Q-text")])]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    raw = b"".join(p.read_bytes() for p in tmp_store_path.parent.iterdir())
    assert b"secret-id" not in raw and b"Q-text" not in raw


async def test_logs_never_carry_interrupt_ids_or_messages(
    store: ConversationStore, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="prismal_tui")
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt("int-zz.ck", "Wire money?")]),
            FakeTurn.agui("done"),
        ]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    await _drain(session.resume({"action": "approve"}))
    assert "int-zz" not in caplog.text and "Wire money" not in caplog.text
    assert "approve" not in caplog.text
    assert "interrupts=1" in caplog.text


# ── INT-003: resume ────────────────────────────────────────────────────────


async def test_resume_answers_every_open_interrupt_verbatim_in_order(
    store: ConversationStore,
) -> None:
    pending = [agui_interrupt("a.ck1"), agui_interrupt("b.ck1")]
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui(interrupts=pending), FakeTurn.agui("resumed: ok")]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    payload = {"action": "approve", "modifications": {}}
    events = await _drain(session.resume(payload))
    call = fake.agui_calls[-1]
    assert call["content"] is None and call["thread_id"] == "thread-1"
    assert [(e.interrupt_id, e.status, e.payload) for e in call["resume"]] == [
        ("a.ck1", "resolved", payload),
        ("b.ck1", "resolved", payload),
    ]
    assert isinstance(events[-1], DoneEvent)
    assert session.open_interrupts == ()
    assert len(fake.created_threads) == 1  # same thread, never a new one


async def test_resume_that_interrupts_again_replaces_the_open_set(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt("a.ck1")]),
            FakeTurn.agui(interrupts=[agui_interrupt("a.ck2", "Next action?")]),
        ]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    events = await _drain(session.resume(None))
    assert isinstance(events[-1], TurnInterrupted)
    assert [i.id for i in session.open_interrupts] == ["a.ck2"]


async def test_resume_with_nothing_open_raises_before_any_io(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient()
    session = await _session(store, fake)
    with pytest.raises(NothingToResume):
        await _drain(session.resume("yes"))
    assert fake.agui_calls == [] and fake.created_threads == []


async def test_resume_while_in_flight_is_rejected(store: ConversationStore) -> None:
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn.agui("a", "b", gate=gate, gate_at=3),
        ]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    stream = session.stream("y")
    first = await anext(stream)
    assert first == TokenEvent(delta="a")
    with pytest.raises(TurnInFlightError):
        await _drain(session.resume("yes"))
    gate.set()
    await _drain(stream)


# ── INT-002/005: errors ────────────────────────────────────────────────────


@pytest.mark.parametrize("code", ["no_pending_interrupt", "resume_in_progress"])
async def test_resume_conflict_clears_open_interrupts_and_propagates(
    store: ConversationStore, code: str
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn([ResumeConflictError(409, code, "x")]),
        ]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    with pytest.raises(ResumeConflictError):
        await _drain(session.resume("yes"))
    assert session.open_interrupts == ()
    assert not session.in_flight


@pytest.mark.parametrize(
    "exc",
    [
        PrismalConnectionError("down"),
        ValidationError(422, "invalid_resume", "x"),
    ],
)
async def test_other_resume_errors_keep_open_interrupts_and_never_retry(
    store: ConversationStore, exc: Exception
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.agui(interrupts=[agui_interrupt()]), FakeTurn([exc])]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    with pytest.raises(type(exc)):
        await _drain(session.resume("yes"))
    assert [i.id for i in session.open_interrupts] == ["int-1.ckpt-1"]
    assert len(fake.agui_calls) == 2  # one turn + one resume, no retry


async def test_cancel_during_resume_keeps_open_interrupts(
    store: ConversationStore,
) -> None:
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn.agui(interrupts=[agui_interrupt()]),
            FakeTurn.agui("a", "b", gate=gate, gate_at=3),
        ]
    )
    session = await _session(store, fake)
    await _drain(session.stream("x"))
    closed_before = fake.streams_closed_early
    stream = session.resume("yes")
    await anext(stream)
    session.cancel()
    with pytest.raises(SessionCancelled):
        await _drain(stream)
    assert session.open_interrupts  # a retried /resume is safe (host fences it)
    assert fake.streams_closed_early == closed_before + 1


async def test_sessions_registry_passes_the_protocol(store: ConversationStore) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.agui("x")])
    conv = await store.create("c")
    sessions = ConversationSessions(fake, store, protocol="ag-ui")
    await _drain(sessions.get(conv.id).stream("x"))
    assert len(fake.agui_calls) == 1
