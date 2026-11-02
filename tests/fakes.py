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
from typing import Any

from prismal_sdk import (
    ChatEvent,
    DoneEvent,
    HealthStatus,
    ReadyStatus,
    ThreadCreated,
    TokenEvent,
)

ScriptItem = ChatEvent | BaseException


@dataclass
class FakeTurn:
    """One scripted streaming turn.

    ``gate`` (optional): after the first item, the stream waits for the event
    to be set — lets a test hold a turn "in flight". ``delay`` sleeps between
    items (slow-stream / responsiveness tests).
    """

    items: Sequence[ScriptItem]
    gate: asyncio.Event | None = None
    delay: float = 0.0

    @classmethod
    def text(cls, *chunks: str, thread_id: str = "t", **kw: Any) -> FakeTurn:
        events: list[ScriptItem] = [TokenEvent(delta=c) for c in chunks]
        events.append(DoneEvent(thread_id=thread_id, finish_reason="stop"))
        return cls(events, **kw)


@dataclass
class FakeAsyncPrismalClient:
    turns: list[FakeTurn] = field(default_factory=list)
    health_error: BaseException | None = None
    ready_error: BaseException | None = None
    create_thread_error: BaseException | None = None

    created_threads: list[str] = field(default_factory=list)
    sent: list[tuple[str, str]] = field(default_factory=list)
    send_kwargs: list[dict[str, Any]] = field(default_factory=list)
    streams_closed_early: int = 0
    health_calls: int = 0
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
                if index == 1 and turn.gate is not None:
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

    async def aclose(self) -> None:
        self.closed = True
