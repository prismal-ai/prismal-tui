"""Value types shared by the session and store layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Conversation:
    """A user-named local conversation and the engine thread it maps to.

    Only the mapping lives here — message content is owned by the engine's
    checkpointer under ``thread_id`` (ARCHITECTURE §4.4, ADR-002).
    """

    id: str
    name: str
    thread_id: str | None
    created_at: datetime
    last_active_at: datetime


class SessionCancelled(Exception):
    """The in-flight turn was cancelled by the user (cancel key / ``/cancel``)."""


class TurnInFlightError(Exception):
    """A turn is already streaming on this conversation (SPEC-TUI-SES-003)."""


class NothingToResume(Exception):
    """``/resume`` with no open interrupt on this conversation (SPEC-TUI-INT-004)."""


class ConversationNotFound(LookupError):
    """No local conversation with that id."""


class ConversationNameTaken(ValueError):
    """Another conversation already uses that name (case-insensitive)."""
