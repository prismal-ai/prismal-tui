"""``ConversationSession`` — the UI-independent turn lifecycle (RF-TUI-001).

One session per local conversation (SPEC-TUI-SES-005). A turn:

1. resolve the conversation's ``thread_id`` from the ``ConversationStore``;
   on a miss call ``create_thread()`` once and ``put()`` the mapping
   **before** the first ``send_message()`` (SPEC-TUI-SES-001, ADR-002);
2. stream ``send_message(thread_id, text)`` with the user's text untouched
   (SPEC-TUI-SES-004), yielding ``TokenEvent`` / ``ToolCallEvent`` /
   ``DoneEvent`` and dropping ``StateEvent`` (SPEC-TUI-SES-002); a
   ``DoneEvent``'s ``usage`` is recorded in the session's in-memory
   :class:`UsageTally` before it is yielded;
3. honour :meth:`cancel` even while blocked waiting on the network: the SDK
   iterator is closed (the host then cancels the run) and
   :class:`SessionCancelled` is raised (SPEC-TUI-UX-002, ADR-004).

WHERE the session's protocol is ``ag-ui`` (DELTA-2026-11-host-0.3,
SPEC-TUI-AGU-001) step 2 uses ``run_agui(thread_id, text)`` instead and
translates AG-UI events into the same UI events (SES-002). A run that ends
interrupted yields :class:`TurnInterrupted`; its interrupts are kept in memory
only until the next finished run, and :meth:`resume` answers them with the
user's payload, untouched (SPEC-TUI-INT-001..003).

SDK exceptions propagate unchanged — they are caught and mapped only at the
``app.py`` call site (SPEC-TUI-ERR-001). Nothing here retries
(SPEC-TUI-ERR-004) or logs message content (SPEC-TUI-NFR-003).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from prismal_sdk import (
    ChatEvent,
    DoneEvent,
    ResumeConflictError,
    StateEvent,
    ThreadCreated,
    TokenEvent,
    ToolCallEvent,
    Usage,
)
from prismal_sdk.agui import (
    AgUiEvent,
    AgUiInterrupt,
    PrismalUsageEvent,
    ResumeEntry,
    RunFinished,
    TextMessageChunk,
    TextMessageContent,
    ToolCallStart,
)

from prismal_tui.session.models import (
    ConversationNotFound,
    NothingToResume,
    SessionCancelled,
    TurnInFlightError,
)
from prismal_tui.session.usage_tally import UsageTally

if TYPE_CHECKING:
    from prismal_tui.store.conversation_store import ConversationStore

log = logging.getLogger("prismal_tui.session")

T = TypeVar("T")

Protocol_ = Literal["prismal", "ag-ui"]


@dataclass(frozen=True, slots=True)
class TurnInterrupted:
    """Terminal: the AG-UI run paused on interrupts (SPEC-TUI-INT-001)."""

    interrupts: tuple[AgUiInterrupt, ...]
    usage: Usage | None = None


SessionEvent = TokenEvent | ToolCallEvent | DoneEvent | TurnInterrupted
RawEvent = ChatEvent | AgUiEvent


class ChatClient(Protocol):
    """The slice of ``AsyncPrismalClient`` a session needs."""

    async def create_thread(self) -> ThreadCreated: ...

    def send_message(
        self, thread_id: str, content: str
    ) -> AsyncIterator[ChatEvent]: ...

    def run_agui(
        self,
        thread_id: str,
        content: str | None = None,
        *,
        resume: Sequence[ResumeEntry] | None = None,
    ) -> AsyncIterator[AgUiEvent]: ...


class _Translator:
    """Raw SDK event → UI event, or ``None`` to skip (SPEC-TUI-SES-002)."""

    def __init__(self, thread_id: str) -> None:
        self._thread_id = thread_id
        self._usage: Usage | None = None
        self.counts = {"token": 0, "tool_call": 0, "skipped": 0}

    def __call__(self, event: RawEvent) -> SessionEvent | None:
        out = self._translate(event)
        if isinstance(out, TokenEvent):
            self.counts["token"] += 1
        elif isinstance(out, ToolCallEvent):
            self.counts["tool_call"] += 1
        elif out is None:
            self.counts["skipped"] += 1
        return out

    def _translate(self, event: RawEvent) -> SessionEvent | None:
        if isinstance(event, TokenEvent | ToolCallEvent | DoneEvent):
            return event
        if isinstance(event, TextMessageContent):
            return TokenEvent(delta=event.delta)
        if isinstance(event, TextMessageChunk):
            delta = getattr(event, "delta", None)
            return TokenEvent(delta=delta) if isinstance(delta, str) and delta else None
        if isinstance(event, ToolCallStart):
            return ToolCallEvent(name=event.tool_call_name)
        if isinstance(event, PrismalUsageEvent):
            self._usage = event.value
            return None
        if isinstance(event, RunFinished):
            if event.is_interrupted:
                return TurnInterrupted(tuple(event.interrupts), self._usage)
            # The locally resolved thread is authoritative (SES-001).
            return DoneEvent(
                thread_id=self._thread_id,
                finish_reason="stop",
                usage=self._usage,
            )
        return None  # StateEvent and every other AG-UI event


async def _abandon(work: asyncio.Future[Any]) -> None:
    """Cancel ``work`` and wait for it to unwind, discarding its outcome."""
    work.cancel()
    await asyncio.gather(work, return_exceptions=True)


class ConversationSession:
    def __init__(
        self,
        client: ChatClient,
        store: ConversationStore,
        conversation_id: str,
        *,
        protocol: Protocol_ = "prismal",
    ) -> None:
        self._client = client
        self._store = store
        self.conversation_id = conversation_id
        self.protocol: Protocol_ = protocol
        self._in_flight = False
        self._cancel = asyncio.Event()
        #: In-memory only, never persisted (SPEC-TUI-USG-001).
        self.usage = UsageTally()
        #: In-memory only, never persisted or logged (SPEC-TUI-INT-002).
        self._open_interrupts: tuple[AgUiInterrupt, ...] = ()

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    @property
    def open_interrupts(self) -> tuple[AgUiInterrupt, ...]:
        """The interrupts the last finished run left open (``()`` if none)."""
        return self._open_interrupts

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

        def start(thread_id: str) -> AsyncIterator[RawEvent]:
            if self.protocol == "ag-ui":
                return self._client.run_agui(thread_id, text)
            return self._client.send_message(thread_id, text)

        # aclosing: a consumer that stops early must still run _run's cleanup.
        async with contextlib.aclosing(self._run(start, kind="turn")) as events:
            async for event in events:
                yield event

    async def resume(self, payload: Any) -> AsyncIterator[SessionEvent]:
        """Answer every open interrupt with ``payload`` (SPEC-TUI-INT-003).

        ``payload`` goes to the engine untouched. Raises
        :class:`NothingToResume` before any I/O when nothing is open
        (INT-004). Never retried (INT-005).
        """
        if self._in_flight:
            raise TurnInFlightError()
        if not self._open_interrupts:
            raise NothingToResume()
        entries = [i.resolve(payload) for i in self._open_interrupts]

        def start(thread_id: str) -> AsyncIterator[RawEvent]:
            return self._client.run_agui(thread_id, resume=entries)

        async with contextlib.aclosing(self._run(start, kind="resume")) as events:
            async for event in events:
                yield event

    async def _run(
        self, start: Callable[[str], AsyncIterator[RawEvent]], *, kind: str
    ) -> AsyncGenerator[SessionEvent]:
        self._in_flight = True
        self._cancel.clear()
        outcome = "error"
        thread_id: str | None = None
        events: AsyncIterator[RawEvent] | None = None
        translate = _Translator("")
        try:
            thread_id = await self._resolve_thread()
            if self._cancel.is_set():
                raise SessionCancelled()
            log.info(
                "%s started conversation=%s thread=%s",
                kind,
                self.conversation_id,
                thread_id,
            )
            translate = _Translator(thread_id)
            events = start(thread_id)
            iterator = aiter(events)
            while True:
                try:
                    raw = await self._or_cancel(lambda: anext(iterator))
                except StopAsyncIteration:
                    break
                if isinstance(raw, StateEvent):
                    log.debug(
                        "state event ignored conversation=%s", self.conversation_id
                    )
                event = translate(raw)
                if event is None:
                    continue
                if isinstance(event, DoneEvent):
                    # SES-002 (DELTA-2026-10): tally before signalling completion.
                    self.usage.record(event.usage)
                    self._open_interrupts = ()
                elif isinstance(event, TurnInterrupted):
                    self.usage.record(event.usage)
                    self._open_interrupts = event.interrupts
                    outcome = f"interrupted interrupts={len(event.interrupts)}"
                yield event
                if isinstance(event, DoneEvent | TurnInterrupted):
                    break
            if not outcome.startswith("interrupted"):
                outcome = "done"
        except SessionCancelled:
            outcome = "cancelled"
            raise
        except ResumeConflictError:
            # INT-002: the host says nothing (or nothing we hold) is pending.
            self._open_interrupts = ()
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
                "%s %s conversation=%s thread=%s tokens=%d tool_calls=%d skipped=%d",
                kind,
                outcome,
                self.conversation_id,
                thread_id,
                translate.counts["token"],
                translate.counts["tool_call"],
                translate.counts["skipped"],
            )


class ConversationSessions:
    """One independent :class:`ConversationSession` per conversation id."""

    def __init__(
        self,
        client: ChatClient,
        store: ConversationStore,
        *,
        protocol: Protocol_ = "prismal",
    ) -> None:
        self._client = client
        self._store = store
        self._protocol: Protocol_ = protocol
        self._sessions: dict[str, ConversationSession] = {}

    def get(self, conversation_id: str) -> ConversationSession:
        session = self._sessions.get(conversation_id)
        if session is None:
            session = ConversationSession(
                self._client, self._store, conversation_id, protocol=self._protocol
            )
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
