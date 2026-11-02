"""Console-script entrypoint: ``prismal-tui`` / ``python -m prismal_tui``.

SPEC-TUI-APP-001: build ``PrismalTuiSettings`` (failing fast, before anything
mounts, on a bad ``PRISMAL_TUI_*`` value — exit 2), one ``AsyncPrismalClient``,
one ``ConversationStore`` and one ``PrismalTuiApp``, then run it.

Logs go to a file next to the store (ARCHITECTURE §7) — never to the
terminal the app is drawing on, and never with message content or secrets
(SPEC-TUI-NFR-003).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from prismal_tui.app import PrismalTuiApp
from prismal_tui.client import get_client
from prismal_tui.settings import ConfigurationError, PrismalTuiSettings, load_settings
from prismal_tui.store.conversation_store import ConversationStore

LOG_FILE_NAME = "prismal-tui.log"


def configure_logging(settings: PrismalTuiSettings) -> None:
    path = settings.store_path.parent / LOG_FILE_NAME
    # Owner-only (0600): the log holds conversation/thread ids. Created before
    # the handler opens it so it is never briefly world-readable.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger = logging.getLogger("prismal_tui")
    logger.setLevel(settings.log_level)
    logger.addHandler(handler)
    logger.propagate = False


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # no CLI flags in v0.1 — configuration is env-only
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"prismal-tui: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings)
    app = PrismalTuiApp(
        settings=settings,
        client=get_client(settings),
        store=ConversationStore(settings.store_path),
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
