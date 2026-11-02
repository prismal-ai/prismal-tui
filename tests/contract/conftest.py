"""Opt-in contract suite against a running prismal-server (SPEC-TUI-NFR-001).

Run with ``uv run pytest -m contract``. Target: ``PRISMAL_TUI_SERVER_URL``
(default ``http://localhost:8000``), optional ``PRISMAL_TUI_TOKEN``.

If ``PRISMAL_TUI_SERVER_URL`` is set explicitly and the host is unreachable
the suite **fails** (CI asked for it); with no URL set it is skipped.
Fake-LLM-only checks (deterministic ``echo:`` replies, ``/tool``, ``/error``)
run only when the host advertises ``X-Prismal-Fake-LLM: 1``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from prismal_sdk import AsyncPrismalClient

from prismal_tui.store.conversation_store import ConversationStore

pytestmark = pytest.mark.contract


@dataclass(frozen=True)
class LiveHost:
    url: str
    token: str | None
    fake_llm: bool


@pytest.fixture(scope="session")
def live_host() -> LiveHost:
    explicit = os.environ.get("PRISMAL_TUI_SERVER_URL")
    url = explicit or "http://localhost:8000"
    try:
        # Probe only (headers aren't exposed by the SDK); tests/ may use httpx.
        response = httpx.get(f"{url.rstrip('/')}/healthz", timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        message = f"prismal-server not reachable at {url}: {type(exc).__name__}"
        if explicit:
            pytest.fail(message)
        pytest.skip(message)
    return LiveHost(
        url=url,
        token=os.environ.get("PRISMAL_TUI_TOKEN") or None,
        fake_llm=response.headers.get("x-prismal-fake-llm") == "1",
    )


@pytest.fixture
async def client(live_host: LiveHost) -> AsyncIterator[AsyncPrismalClient]:
    c = AsyncPrismalClient(live_host.url, token=live_host.token)
    yield c
    await c.aclose()


@pytest.fixture
async def store(tmp_store_path: Path) -> AsyncIterator[ConversationStore]:
    s = ConversationStore(tmp_store_path)
    yield s
    await s.close()
