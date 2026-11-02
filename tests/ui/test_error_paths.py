"""TUI-03-02/03 — every error path renders the mapped friendly text only.

SPEC-TUI-ERR-001/002/003/004/005: no code, status, server message or
traceback anywhere on screen (transcript, status bar, toasts); partial text
already streamed is kept and followed by a note; nothing is retried.
"""

from __future__ import annotations

import pytest
from prismal_sdk import (
    BudgetExceededError,
    PermissionDeniedError,
    PolicyDeniedError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalTimeoutError,
    TokenEvent,
    ToolCallEvent,
)
from textual.widgets import Markdown, Static

from prismal_tui import errors
from prismal_tui.app import PrismalTuiApp
from tests.fakes import FakeAsyncPrismalClient, FakeTurn
from tests.ui.conftest import AppFactory, settle, submit

SERVER_MSG = "engine/graph.py line 42: tenant acme leaked-detail"

CASES = [
    pytest.param(PrismalConnectionError(SERVER_MSG), errors.UNREACHABLE, id="conn"),
    pytest.param(PrismalTimeoutError(SERVER_MSG), errors.UNREACHABLE, id="timeout"),
    pytest.param(
        BudgetExceededError(402, "budget_exceeded", SERVER_MSG),
        errors.OVER_CAPACITY,
        id="budget",
    ),
    pytest.param(
        PolicyDeniedError(403, "policy_denied", SERVER_MSG),
        errors.REQUEST_REFUSED,
        id="policy",
    ),
    pytest.param(
        PermissionDeniedError(403, "permission_denied", SERVER_MSG),
        errors.REQUEST_REFUSED,
        id="permission",
    ),
    pytest.param(
        PrismalAPIError(401, "unauthorized", SERVER_MSG),
        errors.CREDENTIAL_REJECTED,
        id="401",
    ),
    pytest.param(
        PrismalAPIError(500, "internal_error", SERVER_MSG), errors.GENERIC, id="500"
    ),
]

FORBIDDEN = (
    SERVER_MSG,
    "acme",
    "budget_exceeded",
    "policy_denied",
    "permission_denied",
    "internal_error",
    "unauthorized",
    "402",
    "403",
    "401",
    "500",
    "Traceback",
    "Error(",
)


def _screen_text(app: PrismalTuiApp) -> str:
    parts = [str(w.render()) for w in app.query(Static)]
    parts += [md.source for md in app.query(Markdown)]
    parts += [n.message for n in app._notifications]  # noqa: SLF001
    return "\n".join(parts)


def _assert_clean(app: PrismalTuiApp) -> None:
    text = _screen_text(app)
    for needle in FORBIDDEN:
        assert needle not in text, needle


@pytest.mark.parametrize(("exc", "friendly"), CASES)
async def test_error_before_any_token(
    make_app: AppFactory, exc: Exception, friendly: str
) -> None:
    fake = FakeAsyncPrismalClient(turns=[FakeTurn([exc])])
    app = make_app(fake)
    async with app.run_test(notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        assert friendly in app.transcript().notes
        assert friendly in app.statusbar.text
        _assert_clean(app)
        assert len(fake.sent) == 1  # ERR-004: no automatic retry


@pytest.mark.parametrize(("exc", "friendly"), CASES)
async def test_error_mid_stream_keeps_partial_text_then_note(
    make_app: AppFactory, exc: Exception, friendly: str
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[
            FakeTurn(
                [
                    TokenEvent(delta="first part "),
                    ToolCallEvent(name="lookup", args={}),
                    TokenEvent(delta="second part"),
                    exc,
                ]
            )
        ]
    )
    app = make_app(fake)
    async with app.run_test(notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        turn = app.transcript().turns[0]
        kinds = [type(w).__name__ for w in turn.children]
        assert kinds == ["Markdown", "ActivityLine", "Markdown", "SystemNote"]
        assert turn.markdown_sources() == ["first part ", "second part"]
        assert app.transcript().notes[-1] == friendly
        _assert_clean(app)


async def test_create_thread_failure_is_friendly_and_retry_is_manual(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        create_thread_error=PrismalConnectionError(SERVER_MSG),
        turns=[FakeTurn.text("ok")],
    )
    app = make_app(fake)
    async with app.run_test(notifications=True) as pilot:
        await settle(pilot)
        await submit(pilot, "q")
        assert errors.UNREACHABLE in app.transcript().notes
        assert fake.sent == []
        _assert_clean(app)
        fake.create_thread_error = None
        await submit(pilot, "q again")  # the user retries by sending again
        assert fake.sent == [("thread-1", "q again")]


async def test_error_in_one_conversation_leaves_others_untouched(
    make_app: AppFactory,
) -> None:
    fake = FakeAsyncPrismalClient(
        turns=[FakeTurn.text("first ok"), FakeTurn([PrismalConnectionError("x")])]
    )
    app = make_app(fake)
    async with app.run_test() as pilot:
        await settle(pilot)
        a = app.active_id
        await submit(pilot, "in a")
        await submit(pilot, "/new b")
        await submit(pilot, "in b")
        assert errors.UNREACHABLE in app.transcript().notes
        assert app.transcript(a).turns[0].markdown_sources() == ["first ok"]
        assert errors.UNREACHABLE not in app.transcript(a).notes
