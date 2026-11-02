"""TUI-04-01 — the bearer token never leaks (SPEC-TUI-AUT-002, NFR-003).

End-to-end through the *real* ``AsyncPrismalClient`` over an in-process
``httpx.MockTransport`` whose "server" is hostile: it echoes the token back
inside error messages. The token must still never appear in:

- anything rendered (every widget, toasts, the help screen, a screenshot),
- the ``ConversationStore`` file (incl. its WAL/SHM side files),
- the log file or any captured log record (at DEBUG),
- the text of any exception the app maps for display.

(``tests/`` may use httpx directly; the boundary guard covers ``prismal_tui/``.)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from prismal_sdk import AsyncPrismalClient
from pydantic import SecretStr
from textual.widgets import Markdown, Static

from prismal_tui import __main__ as entry
from prismal_tui.app import PrismalTuiApp
from prismal_tui.settings import PrismalTuiSettings
from prismal_tui.store.conversation_store import ConversationStore
from tests.ui.conftest import settle, submit

TOKEN = "sk-live-SECRET-0123456789abcdef"


def _sse(*frames: tuple[str, dict[str, object]]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in frames
    ).encode()


class HostileServer:
    """Echoes the caller's credential back in every error it can."""

    def __init__(self) -> None:
        self.auth_headers: list[str] = []
        self.turn = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth_headers.append(request.headers.get("authorization", ""))
        echoed = f"credential {TOKEN} is not allowed here"
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/threads":
            return httpx.Response(201, json={"thread_id": "thr-1"})
        if path == "/threads/thr-1/messages":
            self.turn += 1
            if self.turn == 1:  # mid-stream terminal error echoing the token
                body = _sse(
                    ("token", {"delta": "partial "}),
                    ("tool_call", {"name": "lookup", "args": {"q": TOKEN}}),
                    ("error", {"code": "internal_error", "message": echoed}),
                )
                return httpx.Response(
                    200, content=body, headers={"content-type": "text/event-stream"}
                )
            if self.turn == 2:  # REST error before streaming, echoing the token
                return httpx.Response(
                    401, json={"error": {"code": "unauthorized", "message": echoed}}
                )
            body = _sse(
                ("token", {"delta": "all good"}),
                ("done", {"thread_id": "thr-1", "finish_reason": "stop"}),
            )
            return httpx.Response(
                200, content=body, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(
            404, json={"error": {"code": "not_found", "message": echoed}}
        )


@pytest.fixture
def _isolated_logging() -> Iterator[None]:
    logger = logging.getLogger("prismal_tui")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    for handler in list(logger.handlers):
        if handler not in saved[0]:
            logger.removeHandler(handler)
            handler.close()
    logger.level, logger.propagate = saved[1], saved[2]


def _rendered_text(app: PrismalTuiApp) -> str:
    parts = [str(w.render()) for w in app.screen.query(Static)]
    parts += [md.source for md in app.screen.query(Markdown)]
    parts += [n.message for n in app._notifications]  # noqa: SLF001
    parts.append(app.export_screenshot())
    return "\n".join(parts)


@pytest.mark.usefixtures("_isolated_logging")
async def test_token_never_leaks_anywhere(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store_path = tmp_path / "data" / "conversations.db"
    settings = PrismalTuiSettings(
        server_url="http://prismal.test",
        token=SecretStr(TOKEN),
        store_path=store_path,
        log_level="DEBUG",
    )
    store_path.parent.mkdir(parents=True)
    entry.configure_logging(settings)
    server = HostileServer()
    client = AsyncPrismalClient(
        settings.server_url,
        token=TOKEN,
        transport=httpx.MockTransport(server),
    )
    app = PrismalTuiApp(
        settings=settings, client=client, store=ConversationStore(store_path)
    )
    seen_on_screen: list[str] = []

    with caplog.at_level(logging.DEBUG):
        async with app.run_test(size=(140, 45), notifications=True) as pilot:
            await settle(pilot)
            for text in ("first", "second", "third"):
                await submit(pilot, text)
                seen_on_screen.append(_rendered_text(app))
            await pilot.press("f1")
            await pilot.pause()
            seen_on_screen.append(_rendered_text(app))
            await pilot.press("escape")
            await pilot.pause()
            assert app.transcript().turns[-1].text == "all good"

    # The credential really was sent — so its absence below is meaningful.
    assert server.auth_headers and all(
        h == f"Bearer {TOKEN}" for h in server.auth_headers
    )

    for screen_text in seen_on_screen:
        assert TOKEN not in screen_text

    for path in store_path.parent.glob("conversations.db*"):
        assert TOKEN.encode() not in path.read_bytes(), path.name

    log_file = store_path.parent / "prismal-tui.log"
    assert log_file.exists() and log_file.read_text()
    assert TOKEN not in log_file.read_text()
    assert TOKEN not in caplog.text
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert record.exc_info is None or TOKEN not in str(record.exc_info[1])

    assert TOKEN not in repr(settings) and TOKEN not in str(settings)
