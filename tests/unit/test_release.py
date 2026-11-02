"""TUI-04-06 — release readiness: version, changelog and release workflow agree."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return str(data["project"]["version"])


def test_version_is_a_final_release() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version()), _version()


def test_changelog_has_an_entry_for_the_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert re.search(
        rf"^## \[{re.escape(_version())}\] — \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M
    )


def test_release_workflow_gates_on_tag_and_checks() -> None:
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert "tags:" in wf and "v*" in wf
    assert 'tag_version="${GITHUB_REF_NAME#v}"' in wf  # tag must equal version
    for step in (
        "ruff check",
        "mypy prismal_tui",
        "pytest",
        "uv build",
        "scripts/smoke_test.py",
        "gh release create",
    ):
        assert step in wf, step
    assert "uv publish" not in wf  # PyPI is TUI-FUTURE-01
    # Third-party actions stay pinned to a commit SHA, like ci.yml.
    for ref in re.findall(r"uses: (\S+)", wf):
        assert re.search(r"@[0-9a-f]{40}$", ref), ref


def test_smoke_script_lives_outside_tests() -> None:
    assert (ROOT / "scripts/smoke_test.py").is_file()
