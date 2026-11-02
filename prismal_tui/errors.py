"""SDK exception → friendly text (SPEC-TUI-ERR-001..005, ARCHITECTURE §6).

``friendly_text`` is what the transcript and status bar show: no error codes,
status codes, server messages or tracebacks ever reach it (SPEC-TUI-ERR-002).
``log_detail`` is the log-file-only counterpart (type, status, code).
"""

from __future__ import annotations

import traceback

from prismal_sdk import (
    BudgetExceededError,
    ForbiddenError,
    InvalidRequestError,
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
# DELTA-2026-10 SPEC-TUI-ERR-002: refined budget copy.
BUDGET_REACHED = "Budget limit reached on the server — run /usage for details"
REQUEST_REFUSED = "That request can't be processed."
CREDENTIAL_REJECTED = "The server rejected the credential — check PRISMAL_TUI_TOKEN."
SERVER_NOT_READY = "prismal-server isn't ready yet — try again in a moment."
CANCELLED = "Cancelled."
STILL_ANSWERING = "Still answering — press Esc to cancel first."
GENERIC = "Something went wrong on the server — try again."
UNEXPECTED = "Something went wrong — details are in the log file."
# SPEC-TUI-USG-008: /usage failures.
USAGE_UNSUPPORTED = "usage reporting requires prismal-server ≥ 0.2"
USAGE_BAD_WINDOW = "The server rejected that usage time window."

# Order matters: the first matching type wins (subclasses before bases).
_BY_TYPE: tuple[tuple[type[BaseException], str], ...] = (
    (SessionCancelled, CANCELLED),
    (TurnInFlightError, STILL_ANSWERING),
    (PrismalTransportError, UNREACHABLE),
    (BudgetExceededError, BUDGET_REACHED),
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
    if isinstance(exc, PrismalAPIError):
        if exc.code == "budget_exceeded":
            return BUDGET_REACHED
        if exc.status_code == 401:
            return CREDENTIAL_REJECTED
    if isinstance(exc, PrismalSDKError):
        return GENERIC
    return UNEXPECTED


def usage_friendly_text(exc: BaseException) -> str:
    """Toast copy for a failed ``usage()`` call (SPEC-TUI-USG-008)."""
    if isinstance(exc, InvalidRequestError):
        return USAGE_BAD_WINDOW
    if isinstance(exc, PrismalAPIError) and exc.status_code == 404:
        return USAGE_UNSUPPORTED  # a 0.1 host has no /v1/usage
    return friendly_text(exc)


def log_detail(exc: BaseException) -> str:
    """Log-only detail: exception type, plus status and code for API errors."""
    name = type(exc).__name__
    if isinstance(exc, PrismalAPIError):
        return f"{name} status={exc.status_code} code={exc.code}"
    return name


def log_traceback(exc: BaseException) -> str:
    """Frame locations only (file:line in function) — never the exception text.

    An exception's message can embed user or model content, which must not
    reach the log file (SPEC-TUI-NFR-003).
    """
    frames = traceback.extract_tb(exc.__traceback__)
    lines = [f"  {f.filename}:{f.lineno} in {f.name}" for f in frames]
    return "\n".join([log_detail(exc), *lines])
