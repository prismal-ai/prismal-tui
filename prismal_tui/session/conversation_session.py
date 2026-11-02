"""``ConversationSession`` — the UI-independent turn lifecycle (RF-TUI-001).

One session per local conversation (SPEC-TUI-SES-005). A turn:

1. resolve the conversation's ``thread_id`` from the ``ConversationStore``;
   on a miss call ``create_thread()`` once and ``put()`` the mapping
   **before** the first ``send_message()`` (SPEC-TUI-SES-001, ADR-002);
2. stream ``send_message(thread_id, text)`` with the user's text untouched
   (SPEC-TUI-SES-004), yielding ``TokenEvent`` / ``ToolCallEvent`` /
   ``DoneEvent`` and dropping ``StateEvent`` (SPEC-TUI-SES-002);
3. honour :meth:`cancel` even while blocked waiting on the network: the SDK
   iterator is closed (the host then cancels the run) and
   :class:`SessionCancelled` is raised (SPEC-TUI-UX-002, ADR-004).

SDK exceptions propagate unchanged — they are caught and mapped only at the
``app.py`` call site (SPEC-TUI-ERR-001). Nothing here retries
(SPEC-TUI-ERR-004) or logs message content (SPEC-TUI-NFR-003).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from prismal_sdk import (
    ChatEvent,
    DoneEvent,
    StateEvent,
    ThreadCreated,
    TokenEvent,
    ToolCallEvent,
)

from prismal_tui.session.models import (
    ConversationNotFound,
    SessionCancelled,
    TurnInFlightError,
)

if TYPE_CHECKING:
    from prismal_tui.store.conversation_store import ConversationStore

log = logging.getLogger("prismal_tui.session")

T = TypeVar("T")

SessionEvent = TokenEvent | ToolCallEvent | DoneEvent


class ChatClient(Protocol):
    """The slice of ``AsyncPrismalClient`` a session needs."""

    async def create_thread(self) -> ThreadCreated: ...

    def send_message(
        self, thread_id: str, content: str
    ) -> AsyncIterator[ChatEvent]: ...


async def _abandon(work: asyncio.Future[Any]) -> None:
    """Cancel ``work`` and wait for it to unwind, discarding its outcome."""
    work.cancel()
    await asyncio.gather(work, return_exceptions=True)


class ConversationSession:
    def __init__(
        self, client: ChatClient, store: ConversationStore, conversation_id: str
    ) -> None:
        self._client = client
        self._store = store
        self.conversation_id = conversation_id
        self._in_flight = False
        self._cancel = asyncio.Event()

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    def cancel(self) -> bool:
        """Cancel the in-flight turn. Returns ``False`` when idle (no-op)."""
        if not self._in_flight:
            return False
        self._cancel.set()
        return True

    async def _or_cancel(self, start: Callable[[], Awaitable[T]]) -> T:
        """Await ``start()`` unless :meth:`cancel` fires first.

        Takes a factory so nothing is created (and left un-awaited) when the
        turn was already cancelled.
        """
        if self._cancel.is_set():
            raise SessionCancelled()
        work = asyncio.ensure_future(start())
        stop = asyncio.ensure_future(self._cancel.wait())
        try:
            await asyncio.wait({work, stop}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            # The task driving this turn was itself cancelled (e.g. shutdown):
            # stop the pending SDK call too, so its stream is not orphaned.
            await _abandon(work)
            raise
        finally:
            stop.cancel()
        if work.done():
            return work.result()
        await _abandon(work)
        raise SessionCancelled()

    async def _resolve_thread(self) -> str:
        conv = await self._store.get(self.conversation_id)
        if conv is None:
            raise ConversationNotFound(self.conversation_id)
        if conv.thread_id is not None:
            await self._store.touch(self.conversation_id)
            return conv.thread_id
        created = await self._or_cancel(self._client.create_thread)
        # Never interrupted: once the host minted a thread, the mapping is
        # persisted so a crash/cancel cannot fork the conversation.
        await self._store.put(self.conversation_id, created.thread_id)
        log.info(
            "thread created conversation=%s thread=%s",
            self.conversation_id,
            created.thread_id,
        )
        return created.thread_id

    async def stream(self, text: str) -> AsyncIterator[SessionEvent]:
        """Run one turn, yielding UI-facing events.

        Raises :class:`TurnInFlightError` if a turn is already streaming on
        this conversation, :class:`SessionCancelled` on cancel, and any SDK
        exception unchanged.
        """
        if self._in_flight:
            raise TurnInFlightError()
        if not text:
            raise ValueError("message text must not be empty")
        self._in_flight = True
        self._cancel.clear()
        counts = {"token": 0, "tool_call": 0, "state": 0}
        outcome = "error"
        thread_id: str | None = None
        events: AsyncIterator[ChatEvent] | None = None
        try:
            thread_id = await self._resolve_thread()
            if self._cancel.is_set():
                raise SessionCancelled()
            log.info(
                "turn started conversation=%s thread=%s",
                self.conversation_id,
                thread_id,
            )
            events = self._client.send_message(thread_id, text)
            iterator = aiter(events)
            while True:
                try:
                    event = await self._or_cancel(lambda: anext(iterator))
                except StopAsyncIteration:
                    break
                if isinstance(event, StateEvent):
                    counts["state"] += 1
                    log.debug(
                        "state event ignored conversation=%s", self.conversation_id
                    )
                    continue
                if isinstance(event, TokenEvent):
                    counts["token"] += 1
                elif isinstance(event, ToolCallEvent):
                    counts["tool_call"] += 1
                yield event
                if isinstance(event, DoneEvent):
                    break
            outcome = "done"
        except SessionCancelled:
            outcome = "cancelled"
            raise
        finally:
            if events is not None:
                closer = getattr(events, "aclose", None)
                if closer is not None:
                    try:
                        await closer()
                    except Exception as exc:  # noqa: BLE001
                        # Type only: exception text may embed content (NFR-003).
                        log.debug("stream close failed: %s", type(exc).__name__)
            self._in_flight = False
            self._cancel.clear()
            log.info(
                "turn %s conversation=%s thread=%s tokens=%d tool_calls=%d states=%d",
                outcome,
                self.conversation_id,
                thread_id,
                counts["token"],
                counts["tool_call"],
                counts["state"],
            )


class ConversationSessions:
    """One independent :class:`ConversationSession` per conversation id."""

    def __init__(self, client: ChatClient, store: ConversationStore) -> None:
        self._client = client
        self._store = store
        self._sessions: dict[str, ConversationSession] = {}

    def get(self, conversation_id: str) -> ConversationSession:
        session = self._sessions.get(conversation_id)
        if session is None:
            session = ConversationSession(self._client, self._store, conversation_id)
            self._sessions[conversation_id] = session
        return session

    def discard(self, conversation_id: str) -> None:
        """Forget a session (e.g. its conversation was deleted), cancelling it."""
        session = self._sessions.pop(conversation_id, None)
        if session is not None:
            session.cancel()

    def in_flight_ids(self) -> frozenset[str]:
        return frozenset(cid for cid, s in self._sessions.items() if s.in_flight)

    def cancel_all(self) -> None:
        for session in self._sessions.values():
            session.cancel()
