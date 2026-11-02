"""TUI-D-01 — pin the wire shapes the TUI renders, through the *real* SDK.

If the SDK or host contract drifts (field rename, new mapping), these fail
before any TUI rendering test silently goes stale.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from prismal_sdk import (
    AsyncPrismalClient,
    BudgetExceededError,
    DoneEvent,
    InvalidRequestError,
    PrismalAPIError,
    TokenEvent,
    Usage,
    UsageReport,
)

from tests.usage_payloads import (
    BUDGET_402,
    BUDGET_STREAM_ERROR,
    FAKE_USAGE,
    USAGE_REPORT,
)

USAGE_KEYS = [
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
    "calls",
    "cost_usd",
    "cost_source",
    "estimated",
    "served_model",
    "gateway",
]


def _client(handler: httpx.MockTransport) -> AsyncPrismalClient:
    return AsyncPrismalClient("http://h.test", transport=handler)


def _sse(*frames: tuple[str, object]) -> httpx.Response:
    body = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in frames)
    return httpx.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream"}
    )


def test_usage_model_has_exactly_the_12_wire_keys() -> None:
    assert list(Usage.model_fields) == USAGE_KEYS
    assert list(FAKE_USAGE) == USAGE_KEYS


async def test_done_event_carries_usage() -> None:
    transport = httpx.MockTransport(
        lambda r: _sse(
            ("token", {"delta": "echo: hi"}),
            ("done", {"thread_id": "t", "finish_reason": "stop", "usage": FAKE_USAGE}),
        )
    )
    async with _client(transport) as c:
        events = [e async for e in c.send_message("t", "hi")]
    assert isinstance(events[0], TokenEvent)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.usage == Usage(**FAKE_USAGE)


async def test_done_without_usage_is_none_v01_host() -> None:
    transport = httpx.MockTransport(
        lambda r: _sse(("done", {"thread_id": "t", "finish_reason": "stop"}))
    )
    async with _client(transport) as c:
        events = [e async for e in c.send_message("t", "hi")]
    assert isinstance(events[-1], DoneEvent) and events[-1].usage is None


async def test_budget_exceeded_402_before_the_turn() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(402, json=BUDGET_402))
    async with _client(transport) as c:
        with pytest.raises(BudgetExceededError) as info:
            async for _ in c.send_message("t", "hi"):
                pass
    err = info.value
    assert err.code == "budget_exceeded" and err.status_code == 402
    assert err.scope == "tenant"
    assert err.usage is None


async def test_budget_exceeded_mid_stream_carries_partial_usage() -> None:
    transport = httpx.MockTransport(
        lambda r: _sse(("token", {"delta": "par"}), ("error", BUDGET_STREAM_ERROR))
    )
    async with _client(transport) as c:
        seen: list[object] = []
        with pytest.raises(BudgetExceededError) as info:
            async for e in c.send_message("t", "hi"):
                seen.append(e)
    assert seen == [TokenEvent(delta="par")]
    assert info.value.usage is not None
    assert info.value.usage.total_tokens == 13


async def test_usage_report_parses_the_rh2_example() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=USAGE_REPORT)

    async with _client(httpx.MockTransport(handler)) as c:
        report = await c.usage(
            thread_id="t-42", since=datetime(2026, 10, 3, 12, tzinfo=UTC)
        )
    assert isinstance(report, UsageReport)
    assert report.totals.total_tokens == 61100
    assert report.totals.cost_source == "mixed"
    assert report.cache_hit_ratio == 0.75
    assert report.by_model[0].served_model == "anthropic/claude-sonnet-4.5"
    assert len(report.turns) == 1 and report.next_cursor is None
    params = calls[0].url.params
    assert params["thread_id"] == "t-42"
    assert params["since"].startswith("2026-10-03T12:00:00")


async def test_usage_on_a_v01_host_is_a_404_api_error() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(404, json={"detail": "Not Found"})
    )
    async with _client(transport) as c:
        with pytest.raises(PrismalAPIError) as info:
            await c.usage()
    assert info.value.status_code == 404


async def test_bad_usage_window_is_invalid_request_error() -> None:
    body = {"error": {"code": "invalid_window", "message": "since > until"}}
    transport = httpx.MockTransport(lambda r: httpx.Response(400, json=body))
    async with _client(transport) as c:
        with pytest.raises(InvalidRequestError):
            await c.usage()
