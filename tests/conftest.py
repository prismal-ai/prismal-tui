"""Shared fixtures (TUI-00-05). All offline — no network, no live server."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeAsyncPrismalClient


@pytest.fixture
def fake_client() -> FakeAsyncPrismalClient:
    """A fresh fake SDK client; script turns via ``fake_client.turns.append``."""
    return FakeAsyncPrismalClient()


@pytest.fixture
def tmp_store_path(tmp_path: Path) -> Path:
    """Path for a throwaway ``ConversationStore`` SQLite file (not yet created).

    TUI-01-02 adds a ``store`` fixture on top of this path.
    """
    directory = tmp_path / "store"
    directory.mkdir()
    return directory / "conversations.db"
