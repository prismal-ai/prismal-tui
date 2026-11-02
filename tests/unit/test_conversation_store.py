"""TUI-01-02/03 — ConversationStore (SPEC-TUI-STO-001..005)."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from prismal_tui.store.conversation_store import (
    ConversationNameTaken,
    ConversationNotFound,
    ConversationStore,
)


class StepClock:
    """Deterministic, strictly increasing timestamps."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def clock() -> StepClock:
    return StepClock()


@pytest.fixture
async def store(
    tmp_store_path: Path, clock: StepClock
) -> AsyncIterator[ConversationStore]:
    s = ConversationStore(tmp_store_path, clock=clock)
    yield s
    await s.close()


# ── STO-004: schema on first run; STO-001: WAL + columns ───────────────────


async def test_schema_and_file_are_created_on_first_use(tmp_store_path: Path) -> None:
    assert not tmp_store_path.exists()
    s = ConversationStore(tmp_store_path)
    assert await s.list() == []
    await s.close()
    assert tmp_store_path.exists()
    conn = sqlite3.connect(tmp_store_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)")]
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert cols == ["id", "name", "thread_id", "created_at", "last_active_at"]
    assert mode == "wal"


async def test_creates_missing_parent_directory(tmp_path: Path) -> None:
    s = ConversationStore(tmp_path / "a" / "b" / "c.db")
    await s.create("x")
    await s.close()
    assert (tmp_path / "a" / "b" / "c.db").exists()


# ── STO-002: CRUD ──────────────────────────────────────────────────────────


async def test_create_returns_a_new_unmapped_conversation(
    store: ConversationStore,
) -> None:
    conv = await store.create("research")
    assert conv.name == "research"
    assert conv.thread_id is None
    assert conv.created_at == conv.last_active_at
    assert conv.created_at.tzinfo is not None
    assert await store.get(conv.id) == conv


async def test_ids_are_unique(store: ConversationStore) -> None:
    a = await store.create("a")
    b = await store.create("b")
    assert a.id != b.id


async def test_get_unknown_is_none(store: ConversationStore) -> None:
    assert await store.get("nope") is None


async def test_get_by_name_is_case_insensitive(store: ConversationStore) -> None:
    conv = await store.create("Research")
    assert await store.get_by_name("research") == conv
    assert await store.get_by_name("other") is None


@pytest.mark.parametrize("bad", ["", "   ", "\n"])
async def test_blank_names_are_rejected(store: ConversationStore, bad: str) -> None:
    with pytest.raises(ValueError):
        await store.create(bad)


async def test_names_are_stripped_and_unique(store: ConversationStore) -> None:
    conv = await store.create("  notes  ")
    assert conv.name == "notes"
    with pytest.raises(ConversationNameTaken):
        await store.create("NOTES")


async def test_put_maps_thread_and_bumps_activity(store: ConversationStore) -> None:
    conv = await store.create("a")
    await store.put(conv.id, "thread-1")
    got = await store.get(conv.id)
    assert got is not None
    assert got.thread_id == "thread-1"
    assert got.last_active_at > conv.last_active_at
    assert got.created_at == conv.created_at


async def test_put_unknown_conversation_raises(store: ConversationStore) -> None:
    with pytest.raises(ConversationNotFound):
        await store.put("ghost", "thread-1")


async def test_touch_bumps_activity_only(store: ConversationStore) -> None:
    conv = await store.create("a")
    await store.put(conv.id, "t1")
    before = await store.get(conv.id)
    await store.touch(conv.id)
    after = await store.get(conv.id)
    assert before is not None and after is not None
    assert after.last_active_at > before.last_active_at
    assert after.thread_id == "t1"


async def test_list_orders_by_last_active_desc(store: ConversationStore) -> None:
    a = await store.create("a")
    b = await store.create("b")
    c = await store.create("c")
    await store.touch(a.id)
    assert [x.name for x in await store.list()] == ["a", "c", "b"]
    await store.put(b.id, "t")
    assert [x.name for x in await store.list()] == ["b", "a", "c"]
    del c


async def test_rename(store: ConversationStore) -> None:
    conv = await store.create("old")
    renamed = await store.rename(conv.id, " new ")
    assert renamed.name == "new"
    assert (await store.get(conv.id)) == renamed
    other = await store.create("other")
    with pytest.raises(ConversationNameTaken):
        await store.rename(other.id, "NEW")
    with pytest.raises(ConversationNotFound):
        await store.rename("ghost", "x")


async def test_rename_to_own_name_in_other_case_is_allowed(
    store: ConversationStore,
) -> None:
    conv = await store.create("notes")
    assert (await store.rename(conv.id, "Notes")).name == "Notes"


async def test_delete_removes_only_the_local_mapping(store: ConversationStore) -> None:
    conv = await store.create("a")
    await store.put(conv.id, "thread-1")
    assert await store.delete(conv.id) is True
    assert await store.get(conv.id) is None
    assert await store.delete(conv.id) is False
    # STO-005: the store has no client — it cannot touch engine history.
    assert not hasattr(store, "client")


async def test_name_is_reusable_after_delete(store: ConversationStore) -> None:
    conv = await store.create("a")
    await store.delete(conv.id)
    assert (await store.create("a")).name == "a"


async def test_operations_after_close_fail(tmp_store_path: Path) -> None:
    s = ConversationStore(tmp_store_path)
    await s.create("a")
    await s.close()
    await s.close()  # idempotent
    with pytest.raises(RuntimeError, match="closed"):
        await s.list()


# ── STO-003 / TUI-01-03: restart continuity on a real SQLite file ──────────


async def test_restart_resolves_the_same_thread(tmp_store_path: Path) -> None:
    first = ConversationStore(tmp_store_path)
    conv = await first.create("project-x")
    await first.put(conv.id, "thread-abc")
    await first.close()

    second = ConversationStore(tmp_store_path)  # simulated process restart
    try:
        again = await second.get_by_name("project-x")
        assert again is not None
        assert again.id == conv.id
        assert again.thread_id == "thread-abc"
        assert [c.id for c in await second.list()] == [conv.id]
    finally:
        await second.close()


async def test_store_file_holds_only_the_mapping(tmp_store_path: Path) -> None:
    """No message content and no secrets ever land in the file (STO, AUT-002)."""
    s = ConversationStore(tmp_store_path)
    conv = await s.create("n")
    await s.put(conv.id, "thread-1")
    await s.close()
    conn = sqlite3.connect(tmp_store_path)
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
    finally:
        conn.close()
    assert tables == ["conversations"]
