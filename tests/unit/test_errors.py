"""TUI-01-08 — SDK exception → friendly text (SPEC-TUI-ERR-001..005).

The friendly text never contains an error code, a server message, a status
code or a traceback; those go to the log via ``log_detail`` only.
"""

from __future__ import annotations

import pytest
from prismal_sdk import (
    BudgetExceededError,
    ForbiddenError,
    PermissionDeniedError,
    PolicyDeniedError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalSDKError,
    PrismalTimeoutError,
    RuntimeCompositionError,
    TurnCancelledError,
    ValidationError,
)

from prismal_tui.errors import (
    CANCELLED,
    CREDENTIAL_REJECTED,
    GENERIC,
    OVER_CAPACITY,
    REQUEST_REFUSED,
    SERVER_NOT_READY,
    STILL_ANSWERING,
    UNEXPECTED,
    UNREACHABLE,
    friendly_text,
    log_detail,
)
from prismal_tui.session import SessionCancelled, TurnInFlightError

SERVER_MSG = "internal: stack frame at engine/graph.py:42 secret-ish detail"


def _api(cls: type[PrismalAPIError], status: int, code: str) -> PrismalAPIError:
    return cls(status, code, SERVER_MSG)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PrismalConnectionError(SERVER_MSG), UNREACHABLE),
        (PrismalTimeoutError(SERVER_MSG), UNREACHABLE),
        (_api(BudgetExceededError, 402, "budget_exceeded"), OVER_CAPACITY),
        (_api(PolicyDeniedError, 403, "policy_denied"), REQUEST_REFUSED),
        (_api(PermissionDeniedError, 403, "permission_denied"), REQUEST_REFUSED),
        (_api(ForbiddenError, 403, "forbidden_tenant"), REQUEST_REFUSED),
        (_api(PrismalAPIError, 401, "unauthorized"), CREDENTIAL_REJECTED),
        (_api(RuntimeCompositionError, 503, "runtime_unavailable"), SERVER_NOT_READY),
        (_api(TurnCancelledError, 200, "cancelled"), CANCELLED),
        (_api(ValidationError, 422, "validation_error"), GENERIC),
        (_api(PrismalAPIError, 500, "internal_error"), GENERIC),
        (PrismalSDKError(SERVER_MSG), GENERIC),
        (SessionCancelled(), CANCELLED),
        (TurnInFlightError(), STILL_ANSWERING),
        (RuntimeError(SERVER_MSG), UNEXPECTED),
        (KeyError("boom"), UNEXPECTED),
    ],
)
def test_mapping(exc: BaseException, expected: str) -> None:
    assert friendly_text(exc) == expected


def test_messages_are_the_spec_copy() -> None:
    assert "PRISMAL_TUI_SERVER_URL" in UNREACHABLE
    assert "over capacity" in OVER_CAPACITY
    assert "can't be processed" in REQUEST_REFUSED
    assert "Esc" in STILL_ANSWERING
    assert "PRISMAL_TUI_TOKEN" in CREDENTIAL_REJECTED


@pytest.mark.parametrize(
    "exc",
    [
        _api(PrismalAPIError, 500, "internal_error"),
        _api(BudgetExceededError, 402, "budget_exceeded"),
        PrismalConnectionError(SERVER_MSG),
        RuntimeError(SERVER_MSG),
    ],
)
def test_friendly_text_never_leaks_codes_or_server_messages(exc: BaseException) -> None:
    text = friendly_text(exc)
    assert SERVER_MSG not in text
    assert "internal_error" not in text and "budget_exceeded" not in text
    assert "500" not in text and "402" not in text
    assert "Traceback" not in text


def test_log_detail_carries_type_status_and_code() -> None:
    detail = log_detail(_api(BudgetExceededError, 402, "budget_exceeded"))
    assert "BudgetExceededError" in detail
    assert "402" in detail and "budget_exceeded" in detail


def test_log_detail_for_non_api_errors_is_the_type_name() -> None:
    assert log_detail(PrismalConnectionError("x")) == "PrismalConnectionError"
