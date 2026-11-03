"""TUI-I-06 — AG-UI turns and interrupt resume against a live prismal-server 0.3.

DELTA-2026-11-host-0.3 (SPEC-TUI-AGU-001, INT-001..005). Needs a fake-LLM
host with AG-UI enabled (``PRISMAL_SERVER_HOST_AGUI_ENABLED=true`` and
``PRISMAL_AGUI_EVENTS_ENABLED=true``), which the CI contract job starts. The
deterministic ``/interrupt`` script exists only in fake mode, so the
interrupt tests skip against a real-LLM host.
"""

from __future__ import annotations

import pytest
from prismal_sdk import (
    AsyncPrismalClient,
    DoneEvent,
    ProtocolNotEnabledError,
    ResumeConflictError,
    TokenEvent,
)

from prismal_tui.session import ConversationSession, TurnInterrupted
from prismal_tui.store.conversation_store import ConversationStore
from tests.contract.conftest import LiveHost

pytestmark = pytest.mark.contract


async def _session(
    client: AsyncPrismalClient, store: ConversationStore
) -> ConversationSession:
    conv = await store.create("agui")
    return ConversationSession(client, store, conv.id, protocol="ag-ui")


async def _collect(stream: object) -> list[object]:
    return [e async for e in stream]  # type: ignore[attr-defined]


def _text(events: list[object]) -> str:
    return "".join(e.delta for e in events if isinstance(e, TokenEvent))


async def _agui_session_or_skip(
    client: AsyncPrismalClient, store: ConversationStore
) -> tuple[ConversationSession, list[object]]:
    session = await _session(client, store)
    try:
        events = await _collect(session.stream("hello agui"))
    except ProtocolNotEnabledError:
        pytest.skip("AG-UI is not enabled on this host")
    return session, events


async def test_agui_turn_ends_with_done_and_usage(
    client: AsyncPrismalClient, store: ConversationStore, live_host: LiveHost
) -> None:
    _, events = await _agui_session_or_skip(client, store)
    assert isinstance(events[-1], DoneEvent)
    assert _text(events)
    if live_host.fake_llm:
        assert _text(events) == "echo: hello agui"
        assert events[-1].usage is not None


async def test_interrupt_then_resume_round_trip(
    client: AsyncPrismalClient, store: ConversationStore, live_host: LiveHost
) -> None:
    if not live_host.fake_llm:
        pytest.skip("/interrupt is a fake-LLM script")
    session, _ = await _agui_session_or_skip(client, store)

    events = await _collect(session.stream("/interrupt approve the deploy?"))
    last = events[-1]
    assert isinstance(last, TurnInterrupted)
    assert len(last.interrupts) == 1
    assert last.interrupts[0].message == "approve the deploy?"
    assert "." in last.interrupts[0].id  # host 0.3 checkpoint fence, verbatim

    events = await _collect(session.resume({"action": "approve"}))
    assert isinstance(events[-1], DoneEvent)
    # Fake mode echoes the {engine id: payload} map the host resumed with:
    # the payload arrived untouched (SPEC-TUI-SES-004 as amended).
    text = _text(events)
    assert text.startswith("resumed: ")
    assert text.endswith(': {"action": "approve"}}')
    assert session.open_interrupts == ()


async def test_retried_resume_is_a_conflict_never_a_second_resume(
    client: AsyncPrismalClient, store: ConversationStore, live_host: LiveHost
) -> None:
    if not live_host.fake_llm:
        pytest.skip("/interrupt is a fake-LLM script")
    session, _ = await _agui_session_or_skip(client, store)
    events = await _collect(session.stream("/interrupt ok?"))
    assert isinstance(events[-1], TurnInterrupted)
    stale = events[-1].interrupts
    await _collect(session.resume("yes"))

    # Re-send the already-consumed answer, as a user retrying would.
    session._open_interrupts = stale  # noqa: SLF001 — simulate the retry
    with pytest.raises(ResumeConflictError) as info:
        await _collect(session.resume("yes"))
    assert info.value.code == "no_pending_interrupt"
    assert session.open_interrupts == ()
