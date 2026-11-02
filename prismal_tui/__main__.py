"""Console-script entrypoint: ``prismal-tui`` / ``python -m prismal_tui``.

SPEC-TUI-APP-001. Settings are validated before anything is mounted, so a
bad ``PRISMAL_TUI_*`` value fails fast with a readable message (exit 2).
The Textual app itself is wired in TUI-02-01.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from prismal_tui.settings import ConfigurationError, load_settings


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # no CLI flags in v0.1 — configuration is env-only
    try:
        load_settings()
    except ConfigurationError as exc:
        print(f"prismal-tui: {exc}", file=sys.stderr)
        return 2
    print(
        "prismal-tui: the terminal app is not wired yet (TUI-02-01).", file=sys.stderr
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
