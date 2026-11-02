"""TUI-01-04..07 — ConversationSession (SPEC-TUI-SES-001..005, UX-002, ERR-003/004).

Offline: FakeAsyncPrismalClient + a real tmp-file ConversationStore; no
Textual event loop.
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
    StateEvent,
    TokenEvent,
    ToolCallEvent,
)

from prismal_tui.session import (
    ConversationSession,
    ConversationSessions,
    SessionCancelled,
    TurnInFlightError,
)
from prismal_tui.store.conversation_store import ConversationNotFound, ConversationStore
from tests.fakes import FakeAsyncPrismalClient, FakeTurn


@pytest.fixture
async def store(tmp_store_path: Path) -> AsyncIterator[ConversationStore]:
    s = ConversationStore(tmp_store_path)
    yield s
    await s.close()


async def _drain(session: ConversationSession, text: str) -> list[object]:
    return [e async for e in session.stream(text)]


async def _until(predicate: object, *, timeout: float = 1.0) -> None:
    async def wait() -> None:
        while not predicate():  # type: ignore[operator]
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


# ── SES-001: thread resolution, put() before the first send ────────────────


async def test_first_turn_creates_and_persists_thread_before_sending(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    order: list[str] = []
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("hi")])

    real_put = store.put
    real_send = fake.send_message

    async def spy_put(cid: str, tid: str) -> None:
        order.append("put")
        await real_put(cid, tid)

    def spy_send(*a: object, **kw: object) -> object:
        order.append("send")
        return real_send(*a, **kw)  # type: ignore[arg-type]

    store.put = spy_put  # type: ignore[method-assign]
    fake.send_message = spy_send  # type: ignore[method-assign]

    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    await _drain(session, "hello")

    assert fake.created_threads == ["thread-1"]
    assert order == ["put", "send"]
    stored = await store.get(conv.id)
    assert stored is not None and stored.thread_id == "thread-1"
    assert fake.sent == [("thread-1", "hello")]


async def test_existing_mapping_is_reused_and_activity_bumped(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    await store.put(conv.id, "thread-old")
    before = await store.get(conv.id)
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("x"), FakeTurn.text("y")])
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    await _drain(session, "one")
    await _drain(session, "two")
    assert fake.created_threads == []
    assert fake.sent == [("thread-old", "one"), ("thread-old", "two")]
    after = await store.get(conv.id)
    assert before is not None and after is not None
    assert after.last_active_at > before.last_active_at


async def test_create_thread_called_exactly_once_across_turns(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("1"), FakeTurn.text("2")])
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    await _drain(session, "a")
    await _drain(session, "b")
    assert fake.created_threads == ["thread-1"]
    assert [t for t, _ in fake.sent] == ["thread-1", "thread-1"]


async def test_crash_mid_turn_keeps_the_mapping(store: ConversationStore) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([TokenEvent(delta="p"), PrismalConnectionError("lost")])]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    with pytest.raises(PrismalConnectionError):
        await _drain(session, "x")
    stored = await store.get(conv.id)
    assert stored is not None and stored.thread_id == "thread-1"


async def test_unknown_conversation_raises(store: ConversationStore) -> None:
    session = ConversationSession(FakeAsyncPrismalClient(), store, "ghost")  # type: ignore[arg-type]
    with pytest.raises(ConversationNotFound):
        await _drain(session, "x")


# ── SES-002: event translation; SES-004: text untouched ────────────────────


async def test_stream_yields_token_toolcall_done_and_drops_state(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    done = DoneEvent(thread_id="thread-1", finish_reason="stop")
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn(
                [
                    TokenEvent(delta="Hel"),
                    StateEvent(data={"node": "x"}),
                    ToolCallEvent(name="search", args={"q": 1}),
                    TokenEvent(delta="lo"),
                    done,
                ]
            )
        ]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    events = await _drain(session, "q")
    assert events == [
        TokenEvent(delta="Hel"),
        ToolCallEvent(name="search", args={"q": 1}),
        TokenEvent(delta="lo"),
        done,
    ]


@pytest.mark.parametrize(
    "text",
    ["  padded  ", "/not-a-command-here", "multi\nline\n", "{{template}} $x %s"],
)
async def test_user_text_reaches_send_message_unmodified(
    store: ConversationStore, text: str
) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("ok")])
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    await _drain(session, text)
    assert fake.sent[0][1] == text
    assert fake.send_kwargs[0]["metadata"] is None
    assert fake.send_kwargs[0]["role"] == "user"


async def test_empty_text_is_rejected_before_any_io(store: ConversationStore) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient()
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await _drain(session, "")
    assert fake.created_threads == [] and fake.sent == []


async def test_logs_never_contain_message_content(
    store: ConversationStore, caplog: pytest.LogCaptureFixture
) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("SECRET-ANSWER")])
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    with caplog.at_level(logging.DEBUG, logger="prismal_tui"):
        await _drain(session, "SECRET-QUESTION")
    assert caplog.records, "turn start/finish should be logged"
    text = caplog.text
    assert "SECRET-QUESTION" not in text and "SECRET-ANSWER" not in text
    assert conv.id in text


# ── SES-003: one in-flight turn per conversation ───────────────────────────


async def test_second_send_while_in_flight_is_rejected_not_queued(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([TokenEvent(delta="a"), TokenEvent(delta="b")], gate=gate)]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    first = asyncio.create_task(_drain(session, "one"))
    await _until(lambda: session.in_flight and fake.sent)

    with pytest.raises(TurnInFlightError):
        await _drain(session, "two")
    assert len(fake.sent) == 1  # not queued, never sent

    gate.set()
    await first
    assert not session.in_flight


async def test_in_flight_clears_after_error(store: ConversationStore) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([PrismalConnectionError("x")]), FakeTurn.text("ok")]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    with pytest.raises(PrismalConnectionError):
        await _drain(session, "1")
    assert not session.in_flight
    # ERR-004: no auto-retry; the next message is a new turn on the same thread.
    await _drain(session, "2")
    assert [t for t, _ in fake.sent] == ["thread-1", "thread-1"]
    assert len(fake.sent) == 2


async def test_in_flight_clears_when_consumer_stops_early(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("a", "b", "c")])
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    stream = session.stream("x")
    async for _ in stream:
        break
    await stream.aclose()
    assert not session.in_flight
    assert fake.streams_closed_early == 1


# ── SES-005: independent per-conversation state ────────────────────────────


async def test_sessions_registry_returns_one_session_per_conversation(
    store: ConversationStore,
) -> None:
    fake = FakeAsyncPrismalClient()
    sessions = ConversationSessions(fake, store)  # type: ignore[arg-type]
    a = await store.create("a")
    b = await store.create("b")
    assert sessions.get(a.id) is sessions.get(a.id)
    assert sessions.get(a.id) is not sessions.get(b.id)


async def test_background_turn_is_unaffected_by_another_conversation(
    store: ConversationStore,
) -> None:
    a = await store.create("a")
    b = await store.create("b")
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn(
                [
                    TokenEvent(delta="bg-1"),
                    TokenEvent(delta="bg-2"),
                    DoneEvent(thread_id="thread-1", finish_reason="stop"),
                ],
                gate=gate,
            ),
            FakeTurn.text("fg"),
        ]
    )
    sessions = ConversationSessions(fake, store)  # type: ignore[arg-type]
    background = asyncio.create_task(_drain(sessions.get(a.id), "slow"))
    await _until(lambda: sessions.get(a.id).in_flight and fake.sent)

    # "switch" to b and run a full turn there while a is still in flight
    fg = await _drain(sessions.get(b.id), "fast")
    assert fg[0] == TokenEvent(delta="fg")
    assert sessions.get(a.id).in_flight and not sessions.get(b.id).in_flight

    gate.set()
    bg = await background
    assert [e.delta for e in bg if isinstance(e, TokenEvent)] == ["bg-1", "bg-2"]
    stored_a, stored_b = await store.get(a.id), await store.get(b.id)
    assert stored_a is not None and stored_b is not None
    assert stored_a.thread_id != stored_b.thread_id


async def test_discard_cancels_an_in_flight_turn(store: ConversationStore) -> None:
    conv = await store.create("a")
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([TokenEvent(delta="a"), TokenEvent(delta="b")], gate=gate)]
    )
    sessions = ConversationSessions(fake, store)  # type: ignore[arg-type]
    session = sessions.get(conv.id)
    task = asyncio.create_task(_drain(session, "x"))
    await _until(lambda: session.in_flight and fake.sent)
    sessions.discard(conv.id)
    with pytest.raises(SessionCancelled):
        await task
    assert sessions.get(conv.id) is not session


# ── TUI-01-07: cancellation ────────────────────────────────────────────────


async def test_cancel_interrupts_a_stream_blocked_on_the_network(
    store: ConversationStore,
) -> None:
    conv = await store.create("a")
    never = asyncio.Event()  # the server never sends the next event
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn([TokenEvent(delta="partial "), TokenEvent(delta="x")], gate=never)
        ]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    seen: list[str] = []

    async def consume() -> None:
        async for e in session.stream("q"):
            assert isinstance(e, TokenEvent)
            seen.append(e.delta)

    task = asyncio.create_task(consume())
    await _until(lambda: seen == ["partial "])
    assert session.cancel() is True

    with pytest.raises(SessionCancelled):
        await asyncio.wait_for(task, 1.0)
    assert seen == ["partial "]  # already-yielded content is never lost
    assert fake.streams_closed_early == 1  # SDK stream closed → host cancels run
    assert not session.in_flight


async def test_cancel_when_idle_is_a_no_op(store: ConversationStore) -> None:
    conv = await store.create("a")
    session = ConversationSession(FakeAsyncPrismalClient(), store, conv.id)  # type: ignore[arg-type]
    assert session.cancel() is False


async def test_session_is_reusable_after_cancel(store: ConversationStore) -> None:
    conv = await store.create("a")
    never = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn([TokenEvent(delta="a"), TokenEvent(delta="b")], gate=never),
            FakeTurn.text("again"),
        ]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    task = asyncio.create_task(_drain(session, "1"))
    await _until(lambda: session.in_flight and fake.sent)
    await asyncio.sleep(0)
    session.cancel()
    with pytest.raises(SessionCancelled):
        await task
    events = await _drain(session, "2")
    assert events[0] == TokenEvent(delta="again")
    assert [t for t, _ in fake.sent] == ["thread-1", "thread-1"]


async def test_cancel_before_first_event(store: ConversationStore) -> None:
    conv = await store.create("a")
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("a")])
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]

    blocker = asyncio.Event()
    real_create = fake.create_thread

    async def slow_create() -> object:
        await blocker.wait()
        return await real_create()

    fake.create_thread = slow_create  # type: ignore[method-assign]
    task = asyncio.create_task(_drain(session, "x"))
    await _until(lambda: session.in_flight)
    session.cancel()
    with pytest.raises(SessionCancelled):
        await asyncio.wait_for(task, 1.0)
    assert fake.sent == []
    assert not session.in_flight


async def test_cancelling_the_consumer_task_closes_the_sdk_stream(
    store: ConversationStore,
) -> None:
    """App shutdown cancels the task driving a turn: nothing may be orphaned."""
    conv = await store.create("a")
    never = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([TokenEvent(delta="a"), TokenEvent(delta="b")], gate=never)]
    )
    session = ConversationSession(fake, store, conv.id)  # type: ignore[arg-type]
    task = asyncio.create_task(_drain(session, "x"))
    await _until(lambda: session.in_flight and fake.sent)
    await asyncio.sleep(0.01)  # let the stream block on the gate
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.streams_closed_early == 1
    assert not session.in_flight
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
