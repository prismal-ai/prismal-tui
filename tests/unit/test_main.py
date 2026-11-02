"""Console entrypoint (SPEC-TUI-APP-001, CFG-001/003, NFR-003)."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from prismal_tui import __main__ as entry
from prismal_tui import client as client_mod

TOKEN = "tok-never-printed"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("PRISMAL_TUI_"):
            monkeypatch.delenv(key)
    client_mod._reset_for_tests()
    root = logging.getLogger("prismal_tui")
    saved = list(root.handlers)
    yield
    for h in list(root.handlers):
        if h not in saved:
            root.removeHandler(h)
            h.close()
    client_mod._reset_for_tests()


def test_invalid_config_exits_2_with_readable_error_before_any_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_SERVER_URL", "localhost:8000")
    monkeypatch.setenv("PRISMAL_TUI_TOKEN", TOKEN)
    built: list[Any] = []
    monkeypatch.setattr(entry, "PrismalTuiApp", lambda **kw: built.append(kw))
    assert entry.main([]) == 2
    err = capsys.readouterr().err
    assert "PRISMAL_TUI_SERVER_URL" in err
    assert TOKEN not in err
    assert "Traceback" not in err
    assert built == []  # failed fast: no app constructed


def test_valid_config_builds_one_client_store_and_app_then_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store_path = tmp_path / "data" / "conversations.db"
    monkeypatch.setenv("PRISMAL_TUI_STORE_PATH", str(store_path))
    monkeypatch.setenv("PRISMAL_TUI_TOKEN", TOKEN)
    runs: list[dict[str, Any]] = []

    class FakeApp:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

        def run(self) -> None:
            runs.append(self.kw)
            logging.getLogger("prismal_tui.app").info("hello from the app")

    monkeypatch.setattr(entry, "PrismalTuiApp", FakeApp)
    assert entry.main([]) == 0
    assert len(runs) == 1
    kw = runs[0]
    assert kw["client"] is client_mod.get_client()
    assert kw["store"].path == store_path
    assert kw["settings"].store_path == store_path

    log_file = store_path.parent / "prismal-tui.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "hello from the app" in content
    assert TOKEN not in content
    assert (log_file.stat().st_mode & 0o777) == 0o600
