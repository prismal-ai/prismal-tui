"""``ConversationStore`` — local name ↔ ``thread_id`` mapping (SPEC-TUI-STO-*).

SQLite in WAL mode, schema created on first use. Every call runs in a worker
thread (``asyncio.to_thread``) behind a lock, so the Textual event loop is
never blocked by disk I/O (SPEC-TUI-NFR-004). Holds no message content and
no credentials — only ``(id, name, thread_id, created_at, last_active_at)``.
``delete`` removes only the local mapping; it never calls the engine/host
(SPEC-TUI-STO-005).
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from prismal_tui.session.models import (
    Conversation,
    ConversationNameTaken,
    ConversationNotFound,
)

__all__ = ["ConversationNameTaken", "ConversationNotFound", "ConversationStore"]

T = TypeVar("T")
Clock = Callable[[], datetime]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    thread_id TEXT,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS conversations_name_nocase
    ON conversations (name COLLATE NOCASE);
"""

_COLUMNS = "id, name, thread_id, created_at, last_active_at"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("conversation name must not be blank")
    return cleaned


def _row(row: tuple[Any, ...]) -> Conversation:
    return Conversation(
        id=row[0],
        name=row[1],
        thread_id=row[2],
        created_at=datetime.fromisoformat(row[3]),
        last_active_at=datetime.fromisoformat(row[4]),
    )


class ConversationStore:
    def __init__(self, path: Path, *, clock: Clock = _utcnow) -> None:
        self._path = path
        self._clock = clock
        self._conn: sqlite3.Connection | None = None
        self._closed = False
        self._thread_lock = threading.Lock()
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # ── plumbing ───────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self._closed:
            raise RuntimeError("ConversationStore is closed")

        def work() -> T:
            with self._thread_lock:
                conn = self._connect()
                try:
                    result = fn(conn)
                except BaseException:
                    conn.rollback()
                    raise
                conn.commit()
                return result

        async with self._lock:
            return await asyncio.to_thread(work)

    def _now(self) -> str:
        # Fixed-width UTC ISO-8601 so ORDER BY on the text column is chronological.
        return self._clock().astimezone(UTC).isoformat(timespec="microseconds")

    # ── public API (STO-002) ───────────────────────────────────────────────

    async def list(self) -> list[Conversation]:
        """All conversations, most recently active first (SPEC-TUI-UX-003)."""

        def q(conn: sqlite3.Connection) -> list[Conversation]:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM conversations "
                "ORDER BY last_active_at DESC, created_at DESC"
            ).fetchall()
            return [_row(r) for r in rows]

        return await self._run(q)

    async def create(self, name: str) -> Conversation:
        cleaned = _clean_name(name)

        def q(conn: sqlite3.Connection) -> Conversation:
            now = self._now()
            conv_id = str(uuid.uuid4())
            try:
                conn.execute(
                    f"INSERT INTO conversations ({_COLUMNS}) VALUES (?, ?, NULL, ?, ?)",
                    (conv_id, cleaned, now, now),
                )
            except sqlite3.IntegrityError:
                raise ConversationNameTaken(cleaned) from None
            return _row((conv_id, cleaned, None, now, now))

        return await self._run(q)

    async def get(self, conversation_id: str) -> Conversation | None:
        def q(conn: sqlite3.Connection) -> Conversation | None:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            return _row(row) if row else None

        return await self._run(q)

    async def get_by_name(self, name: str) -> Conversation | None:
        def q(conn: sqlite3.Connection) -> Conversation | None:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM conversations WHERE name = ? COLLATE NOCASE",
                (name.strip(),),
            ).fetchone()
            return _row(row) if row else None

        return await self._run(q)

    async def put(self, conversation_id: str, thread_id: str) -> None:
        """Map a conversation to its engine thread (and mark it active)."""

        def q(conn: sqlite3.Connection) -> None:
            cur = conn.execute(
                "UPDATE conversations SET thread_id = ?, last_active_at = ? "
                "WHERE id = ?",
                (thread_id, self._now(), conversation_id),
            )
            if cur.rowcount == 0:
                raise ConversationNotFound(conversation_id)

        await self._run(q)

    async def touch(self, conversation_id: str) -> None:
        """Bump ``last_active_at`` (a new turn on an already-mapped thread)."""

        def q(conn: sqlite3.Connection) -> None:
            cur = conn.execute(
                "UPDATE conversations SET last_active_at = ? WHERE id = ?",
                (self._now(), conversation_id),
            )
            if cur.rowcount == 0:
                raise ConversationNotFound(conversation_id)

        await self._run(q)

    async def rename(self, conversation_id: str, name: str) -> Conversation:
        cleaned = _clean_name(name)

        def q(conn: sqlite3.Connection) -> Conversation:
            try:
                cur = conn.execute(
                    "UPDATE conversations SET name = ? WHERE id = ?",
                    (cleaned, conversation_id),
                )
            except sqlite3.IntegrityError:
                raise ConversationNameTaken(cleaned) from None
            if cur.rowcount == 0:
                raise ConversationNotFound(conversation_id)
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            return _row(row)

        return await self._run(q)

    async def delete(self, conversation_id: str) -> bool:
        """Forget the local mapping. Engine history is left untouched."""

        def q(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            return cur.rowcount > 0

        return await self._run(q)

    async def close(self) -> None:
        if self._closed:
            return

        def work() -> None:
            with self._thread_lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None

        async with self._lock:
            self._closed = True
            await asyncio.to_thread(work)
