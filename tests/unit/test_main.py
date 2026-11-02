"""Console entrypoint fails fast on bad configuration (SPEC-TUI-CFG-001/003)."""

from __future__ import annotations

import pytest

from prismal_tui.__main__ import main


def test_invalid_config_exits_2_with_readable_error_before_any_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRISMAL_TUI_SERVER_URL", "localhost:8000")
    monkeypatch.setenv("PRISMAL_TUI_TOKEN", "tok-never-printed")
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "PRISMAL_TUI_SERVER_URL" in err
    assert "tok-never-printed" not in err
    assert "Traceback" not in err
