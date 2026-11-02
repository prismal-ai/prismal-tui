"""Post-build smoke test for a built distribution (TUI-04-06).

The release workflow runs it against the freshly built wheel and sdist, in an
isolated environment holding only the distribution and its runtime
dependencies:

    uv run --isolated --no-project --with dist/*.whl \
        --with ../prismal-sdk scripts/smoke_test.py

It catches packaging failures the test suite cannot see: a module left out
of the artifact, a missing console script, or a broken entry point. It does
no network I/O and never draws the terminal UI.

It lives outside ``tests/`` so pytest never collects it.
"""

from __future__ import annotations

import importlib.metadata
import os
import pathlib
import sys

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


import prismal_tui  # noqa: E402
from prismal_tui.__main__ import main  # noqa: E402
from prismal_tui.app import PrismalTuiApp  # noqa: E402
from prismal_tui.widgets.usage_modal import UsageScreen  # noqa: E402

# Imported from the installed artifact, not from a source checkout.
location = pathlib.Path(prismal_tui.__file__).resolve()
check("site-packages" in location.parts, f"imported from a checkout: {location}")
check(PrismalTuiApp is not None and UsageScreen is not None, "app not importable")

dist = importlib.metadata.distribution("prismal-tui")
scripts = {
    ep.name: ep.value for ep in dist.entry_points if ep.group == "console_scripts"
}
check(
    scripts.get("prismal-tui") == "prismal_tui.__main__:main",
    f"console script missing or wrong: {scripts}",
)
check(
    dist.version == os.environ.get("EXPECTED_VERSION", dist.version),
    f"version {dist.version} != {os.environ.get('EXPECTED_VERSION')}",
)

# The entry point validates settings before drawing anything: an invalid URL
# must exit 2 without starting Textual.
os.environ["PRISMAL_TUI_SERVER_URL"] = "not-a-url"
check(main([]) == 2, "invalid configuration did not exit with status 2")

if failures:
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    sys.exit(1)
print(f"smoke test OK: prismal-tui {dist.version}")
