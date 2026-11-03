"""Offline test doubles (SPEC-TUI-NFR-001, ADR-005).

``FakeAsyncPrismalClient`` stands in for ``prismal_sdk.AsyncPrismalClient``
for the subset ``prismal-tui`` uses. Each ``send_message()`` or ``run_agui()``
call consumes the next scripted :class:`FakeTurn`; script items are SDK events
(native or AG-UI, yielded) or exceptions (raised in place, as the real SDK
raises a terminal ``error`` / ``RUN_ERROR``).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from prismal_sdk import (
    ChatEvent,
    DoneEvent,
    HealthStatus,
    ReadyStatus,
    ThreadCreated,
    TokenEvent,
    Usage,
    UsageReport,
)
from prismal_sdk.agui import (
    PRISMAL_USAGE_EVENT,
    AgUiEvent,
    PrismalUsageEvent,
    ResumeEntry,
    RunFinished,
    RunStarted,
    TextMessageContent,
    TextMessageEnd,
    TextMessageStart,
    ToolCallEnd,
    ToolCallStart,
)

ScriptItem = ChatEvent | AgUiEvent | BaseException


def agui_interrupt(
    iid: str = "int-1.ckpt-1",
    message: str | None = "Approve the deploy?",
    reason: str = "human_approval",
) -> dict[str, Any]:
    """One ``RUN_FINISHED.outcome.interrupts[]`` wire entry."""
    entry: dict[str, Any] = {"id": iid, "reason": reason, "metadata": {"value": {}}}
    if message is not None:
        entry["message"] = message
    return entry


@dataclass
class FakeTurn:
    """One scripted streaming turn.

    ``gate`` (optional): before item ``gate_at`` (default: the second one) the
    stream waits for the event to be set — lets a test hold a turn "in
    flight". ``delay`` sleeps between items (slow-stream tests).
    """

    items: Sequence[ScriptItem]
    gate: asyncio.Event | None = None
    delay: float = 0.0
    gate_at: int = 1

    @classmethod
    def text(
        cls,
        *chunks: str,
        thread_id: str = "t",
        usage: Usage | None = None,
        **kw: Any,
    ) -> FakeTurn:
        events: list[ScriptItem] = [TokenEvent(delta=c) for c in chunks]
        events.append(DoneEvent(thread_id=thread_id, finish_reason="stop", usage=usage))
        return cls(events, **kw)

    @classmethod
    def agui(
        cls,
        *chunks: str,
        thread_id: str = "t",
        usage: Usage | None = None,
        tools: Iterable[str] = (),
        interrupts: Sequence[dict[str, Any]] | None = None,
        **kw: Any,
    ) -> FakeTurn:
        """An AG-UI run as host 0.3 streams it (``usage`` → ``prismal.usage``)."""
        events: list[ScriptItem] = [
            RunStarted(type="RUN_STARTED", thread_id=thread_id, run_id="r")
        ]
        for n, name in enumerate(tools):
            events.append(
                ToolCallStart(
                    type="TOOL_CALL_START", tool_call_id=f"c{n}", tool_call_name=name
                )
            )
            events.append(ToolCallEnd(type="TOOL_CALL_END", tool_call_id=f"c{n}"))
        if chunks:
            events.append(TextMessageStart(type="TEXT_MESSAGE_START", message_id="m"))
            events.extend(
                TextMessageContent(type="TEXT_MESSAGE_CONTENT", message_id="m", delta=c)
                for c in chunks
            )
            events.append(TextMessageEnd(type="TEXT_MESSAGE_END", message_id="m"))
        if usage is not None:
            events.append(
                PrismalUsageEvent(type="CUSTOM", name=PRISMAL_USAGE_EVENT, value=usage)
            )
        outcome = (
            {"type": "interrupt", "interrupts": list(interrupts)}
            if interrupts
            else {"type": "success"}
        )
        events.append(
            RunFinished(
                type="RUN_FINISHED", thread_id=thread_id, run_id="r", outcome=outcome
            )
        )
        return cls(events, **kw)


@dataclass
class FakeAsyncPrismalClient:
    turns: list[FakeTurn] = field(default_factory=list)
    health_error: BaseException | None = None
    ready_error: BaseException | None = None
    create_thread_error: BaseException | None = None
    #: ``usage()`` consumes these in order: a report is returned, an exception
    #: raised (e.g. a 404 ``PrismalAPIError`` from a 0.1 host).
    usage_reports: list[UsageReport | BaseException] = field(default_factory=list)
    usage_gate: asyncio.Event | None = None

    created_threads: list[str] = field(default_factory=list)
    sent: list[tuple[str, str]] = field(default_factory=list)
    send_kwargs: list[dict[str, Any]] = field(default_factory=list)
    #: One entry per ``run_agui()`` call: ``thread_id``, ``content``, ``resume``.
    agui_calls: list[dict[str, Any]] = field(default_factory=list)
    streams_closed_early: int = 0
    health_calls: int = 0
    usage_calls: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False

    async def healthz(self) -> HealthStatus:
        self.health_calls += 1
        if self.health_error is not None:
            raise self.health_error
        return HealthStatus(status="ok")

    async def readyz(self) -> ReadyStatus:
        if self.ready_error is not None:
            raise self.ready_error
        return ReadyStatus(status="ready")

    async def create_thread(self) -> ThreadCreated:
        if self.create_thread_error is not None:
            raise self.create_thread_error
        thread_id = f"thread-{len(self.created_threads) + 1}"
        self.created_threads.append(thread_id)
        return ThreadCreated(thread_id=thread_id)

    async def send_message(
        self,
        thread_id: str,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        org_id: str | None = None,
        protocol: str = "prismal",
    ) -> AsyncIterator[ChatEvent]:
        assert self.turns, "FakeAsyncPrismalClient: no scripted turn left"
        turn = self.turns.pop(0)
        self.sent.append((thread_id, content))
        self.send_kwargs.append(
            {"role": role, "metadata": metadata, "org_id": org_id, "protocol": protocol}
        )
        async with contextlib.aclosing(self._play(turn)) as items:
            async for item in items:
                yield item

    async def run_agui(
        self,
        thread_id: str,
        content: str | None = None,
        *,
        resume: Sequence[ResumeEntry] | None = None,
        run_id: str | None = None,
        org_id: str | None = None,
    ) -> AsyncIterator[AgUiEvent]:
        # Same precondition the real SDK checks before any I/O (CS3-RUN-002).
        if (content is None) == (not resume):
            raise ValueError("pass exactly one of content and a non-empty resume")
        assert self.turns, "FakeAsyncPrismalClient: no scripted turn left"
        turn = self.turns.pop(0)
        self.agui_calls.append(
            {
                "thread_id": thread_id,
                "content": content,
                "resume": list(resume) if resume else None,
            }
        )
        async with contextlib.aclosing(self._play(turn)) as items:
            async for item in items:
                yield item

    async def _play(self, turn: FakeTurn) -> AsyncIterator[Any]:
        try:
            for index, item in enumerate(turn.items):
                if index == turn.gate_at and turn.gate is not None:
                    await turn.gate.wait()
                if index and turn.delay:
                    await asyncio.sleep(turn.delay)
                if isinstance(item, BaseException):
                    raise item
                yield item
        except (GeneratorExit, asyncio.CancelledError):
            # The consumer broke out / was cancelled: the real SDK closes the
            # HTTP stream here, which makes the host cancel the run.
            self.streams_closed_early += 1
            raise

    async def usage(
        self,
        *,
        thread_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
        org_id: str | None = None,
    ) -> UsageReport:
        call: dict[str, Any] = {"thread_id": thread_id, "since": since}
        call.update(
            {
                k: v
                for k, v in {
                    "until": until,
                    "cursor": cursor,
                    "org_id": org_id,
                }.items()
                if v is not None
            }
        )
        if limit != 100:
            call["limit"] = limit
        self.usage_calls.append(call)
        if self.usage_gate is not None:
            await self.usage_gate.wait()
        assert self.usage_reports, "FakeAsyncPrismalClient: no scripted usage left"
        item = self.usage_reports.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self) -> None:
        self.closed = True
