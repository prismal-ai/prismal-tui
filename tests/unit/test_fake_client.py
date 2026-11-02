"""The test seam itself — ``FakeAsyncPrismalClient`` (SPEC-TUI-NFR-001, ADR-005).

Session-layer tests rely on it behaving like ``AsyncPrismalClient`` for the
subset ``prismal-tui`` uses, so its contract is pinned here.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from prismal_sdk import (
    AsyncPrismalClient,
    DoneEvent,
    PrismalConnectionError,
    TokenEvent,
    ToolCallEvent,
)

from tests.fakes import FakeAsyncPrismalClient, FakeTurn


def test_fake_mirrors_the_real_client_signatures() -> None:
    for name in (
        "healthz",
        "readyz",
        "create_thread",
        "send_message",
        "usage",
        "aclose",
    ):
        real = inspect.signature(getattr(AsyncPrismalClient, name))
        fake = inspect.signature(getattr(FakeAsyncPrismalClient, name))
        real_params = [p for p in real.parameters if p != "self"]
        fake_params = [p for p in fake.parameters if p != "self"]
        assert set(real_params) <= set(fake_params) | {"protocol"}, name


async def test_create_thread_mints_distinct_ids() -> None:
    fake = FakeAsyncPrismalClient()
    a = await fake.create_thread()
    b = await fake.create_thread()
    assert a.thread_id != b.thread_id
    assert fake.created_threads == [a.thread_id, b.thread_id]


async def test_send_message_replays_the_scripted_turn_and_records_the_call() -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn(
                [
                    TokenEvent(delta="Hel"),
                    ToolCallEvent(name="search", args={"q": "x"}),
                    TokenEvent(delta="lo"),
                    DoneEvent(thread_id="t-1", finish_reason="stop"),
                ]
            )
        ]
    )
    events = [e async for e in fake.send_message("t-1", "  raw text  ")]
    assert [type(e).__name__ for e in events] == [
        "TokenEvent",
        "ToolCallEvent",
        "TokenEvent",
        "DoneEvent",
    ]
    assert fake.sent == [("t-1", "  raw text  ")]


async def test_turns_are_consumed_in_order() -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("one", thread_id="t"), FakeTurn.text("two", thread_id="t")]
    )
    first = [e async for e in fake.send_message("t", "a")]
    second = [e async for e in fake.send_message("t", "b")]
    assert isinstance(first[0], TokenEvent) and first[0].delta == "one"
    assert isinstance(second[0], TokenEvent) and second[0].delta == "two"


async def test_script_can_raise_mid_stream() -> None:
    boom = PrismalConnectionError("connection lost")
    fake = FakeAsyncPrismalClient(turns=[FakeTurn([TokenEvent(delta="par"), boom])])
    seen: list[str] = []
    with pytest.raises(PrismalConnectionError):
        async for e in fake.send_message("t", "x"):
            assert isinstance(e, TokenEvent)
            seen.append(e.delta)
    assert seen == ["par"]


async def test_send_message_without_a_scripted_turn_fails_loudly() -> None:
    fake = FakeAsyncPrismalClient()
    with pytest.raises(AssertionError, match="no scripted turn"):
        async for _ in fake.send_message("t", "x"):
            pass


async def test_breaking_out_of_the_stream_marks_it_closed() -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([TokenEvent(delta=str(i)) for i in range(10)])]
    )
    stream = fake.send_message("t", "x")
    async for _ in stream:
        break
    await stream.aclose()  # what `async for ... break` + GC does in practice
    assert fake.streams_closed_early == 1


async def test_gated_turn_waits_for_release() -> None:
    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn([TokenEvent(delta="a"), TokenEvent(delta="b")], gate=gate)]
    )
    got: list[str] = []

    async def consume() -> None:
        async for e in fake.send_message("t", "x"):
            assert isinstance(e, TokenEvent)
            got.append(e.delta)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert got == ["a"]  # first event flows, the rest waits on the gate
    gate.set()
    await task
    assert got == ["a", "b"]


async def test_healthz_ok_and_scripted_failure() -> None:
    assert (await FakeAsyncPrismalClient().healthz()).status == "ok"
    down = FakeAsyncPrismalClient(health_error=PrismalConnectionError("down"))
    with pytest.raises(PrismalConnectionError):
        await down.healthz()


async def test_aclose_is_recorded() -> None:
    fake = FakeAsyncPrismalClient()
    await fake.aclose()
    assert fake.closed


def test_tmp_store_path_fixture_points_into_tmp(tmp_store_path: Path) -> None:
    assert tmp_store_path.name == "conversations.db"
    assert tmp_store_path.parent.is_dir()
    assert not tmp_store_path.exists()


# ── TUI-D-02: usage scripts ────────────────────────────────────────────────


async def test_text_turn_can_carry_done_usage() -> None:
    from prismal_sdk import Usage

    from tests.usage_payloads import FAKE_USAGE

    usage = Usage(**FAKE_USAGE)
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("hi", usage=usage)])
    events = [e async for e in fake.send_message("t", "q")]
    assert isinstance(events[-1], DoneEvent) and events[-1].usage == usage


async def test_text_turn_usage_defaults_to_none() -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn.text("hi")])
    events = [e async for e in fake.send_message("t", "q")]
    assert isinstance(events[-1], DoneEvent) and events[-1].usage is None


async def test_usage_returns_scripted_reports_and_records_calls() -> None:
    from datetime import UTC, datetime

    from prismal_sdk import UsageReport

    from tests.usage_payloads import USAGE_REPORT

    report = UsageReport.model_validate(USAGE_REPORT)
    fake = FakeAsyncPrismalClient(usage_reports=[report])
    since = datetime(2026, 11, 1, tzinfo=UTC)
    assert await fake.usage(thread_id="thread-1", since=since) is report
    assert fake.usage_calls == [{"thread_id": "thread-1", "since": since}]


async def test_usage_raises_scripted_errors() -> None:
    from prismal_sdk import InvalidRequestError, PrismalAPIError

    not_found = PrismalAPIError(404, "not_found", "Not Found")
    bad = InvalidRequestError(400, "invalid_window", "since > until")
    fake = FakeAsyncPrismalClient(usage_reports=[not_found, bad])
    with pytest.raises(PrismalAPIError) as info:
        await fake.usage()
    assert info.value.status_code == 404
    with pytest.raises(InvalidRequestError):
        await fake.usage()


async def test_usage_without_a_script_fails_loudly() -> None:
    with pytest.raises(AssertionError, match="no scripted usage"):
        await FakeAsyncPrismalClient().usage()


async def test_usage_gate_holds_the_call() -> None:
    from prismal_sdk import UsageReport

    from tests.usage_payloads import USAGE_REPORT

    gate = asyncio.Event()
    fake = FakeAsyncPrismalClient(
        usage_reports=[UsageReport.model_validate(USAGE_REPORT)], usage_gate=gate
    )
    task = asyncio.ensure_future(fake.usage())
    await asyncio.sleep(0.01)
    assert not task.done() and len(fake.usage_calls) == 1
    gate.set()
    assert (await task).totals.total_tokens == 61100
