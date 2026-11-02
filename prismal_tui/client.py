"""Process-wide ``AsyncPrismalClient`` (SPEC-TUI-APP-003, AUT-001/003).

Built lazily from :class:`~prismal_tui.settings.PrismalTuiSettings` on first
use and closed once on shutdown. This is the only place the bearer token is
unwrapped — straight into the SDK constructor, nowhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prismal_sdk import AsyncPrismalClient

from prismal_tui.settings import PrismalTuiSettings

ClientFactory = Callable[..., Any]

_client: Any = None


def get_client(
    settings: PrismalTuiSettings | None = None,
    *,
    factory: ClientFactory = AsyncPrismalClient,
) -> AsyncPrismalClient:
    """Return the shared client, building it from ``settings`` the first time.

    ``factory`` exists for tests; production always uses the SDK client.
    """
    global _client
    if _client is None:
        if settings is None:
            raise RuntimeError("SDK client not configured: call get_client(settings)")
        token = settings.token.get_secret_value() if settings.token else None
        _client = factory(settings.server_url, token=token, org_id=settings.org_id)
    client: AsyncPrismalClient = _client
    return client


async def close_client() -> None:
    """Close the shared client (idempotent); a later ``get_client`` rebuilds."""
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()


def _reset_for_tests() -> None:
    global _client
    _client = None
