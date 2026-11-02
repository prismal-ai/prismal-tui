"""Offline test doubles (SPEC-TUI-NFR-001, ADR-005).

``FakeAsyncPrismalClient`` stands in for ``prismal_sdk.AsyncPrismalClient``
for the subset ``prismal-tui`` uses. Each ``send_message()`` call consumes the
next scripted :class:`FakeTurn`; script items are SDK events (yielded) or
exceptions (raised in place, as the real SDK raises a terminal ``error``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
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

ScriptItem = ChatEvent | BaseException


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
