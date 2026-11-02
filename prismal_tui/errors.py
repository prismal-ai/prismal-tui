"""SDK exception → friendly text (SPEC-TUI-ERR-001..005, ARCHITECTURE §6).

``friendly_text`` is what the transcript and status bar show: no error codes,
status codes, server messages or tracebacks ever reach it (SPEC-TUI-ERR-002).
``log_detail`` is the log-file-only counterpart (type, status, code).
"""

from __future__ import annotations

from prismal_sdk import (
    BudgetExceededError,
    ForbiddenError,
    PermissionDeniedError,
    PolicyDeniedError,
    PrismalAPIError,
    PrismalSDKError,
    PrismalTransportError,
    RuntimeCompositionError,
    TurnCancelledError,
)

from prismal_tui.session.models import SessionCancelled, TurnInFlightError

UNREACHABLE = "Can't reach prismal-server — check PRISMAL_TUI_SERVER_URL and try again."
OVER_CAPACITY = "The assistant is over capacity for now."
REQUEST_REFUSED = "That request can't be processed."
CREDENTIAL_REJECTED = "The server rejected the credential — check PRISMAL_TUI_TOKEN."
SERVER_NOT_READY = "prismal-server isn't ready yet — try again in a moment."
CANCELLED = "Cancelled."
STILL_ANSWERING = "Still answering — press Esc to cancel first."
GENERIC = "Something went wrong on the server — try again."
UNEXPECTED = "Something went wrong — details are in the log file."

# Order matters: the first matching type wins (subclasses before bases).
_BY_TYPE: tuple[tuple[type[BaseException], str], ...] = (
    (SessionCancelled, CANCELLED),
    (TurnInFlightError, STILL_ANSWERING),
    (PrismalTransportError, UNREACHABLE),
    (BudgetExceededError, OVER_CAPACITY),
    (PolicyDeniedError, REQUEST_REFUSED),
    (PermissionDeniedError, REQUEST_REFUSED),
    (ForbiddenError, REQUEST_REFUSED),
    (RuntimeCompositionError, SERVER_NOT_READY),
    (TurnCancelledError, CANCELLED),
)


def friendly_text(exc: BaseException) -> str:
    """User-facing copy for any exception raised during a turn."""
    for exc_type, text in _BY_TYPE:
        if isinstance(exc, exc_type):
            return text
    if isinstance(exc, PrismalAPIError) and exc.status_code == 401:
        return CREDENTIAL_REJECTED
    if isinstance(exc, PrismalSDKError):
        return GENERIC
    return UNEXPECTED


def log_detail(exc: BaseException) -> str:
    """Log-only detail: exception type, plus status and code for API errors."""
    name = type(exc).__name__
    if isinstance(exc, PrismalAPIError):
        return f"{name} status={exc.status_code} code={exc.code}"
    return name
