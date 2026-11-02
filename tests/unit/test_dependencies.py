"""SPEC-TUI-NFR-005 (DELTA-2026-10): dependency pins are deliberate.

- ``prismal-sdk>=0.2,<1`` — a lower floor fails this test.
- ``textual`` and ``platformdirs`` pinned to a tested minor (``>=X.Y,<X.Y+1``).
- No engine/host/HTTP dependency is ever declared (SPEC-TUI-APP-002).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _runtime_requirements() -> dict[str, Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    reqs = [Requirement(r) for r in data["project"]["dependencies"]]
    return {r.name.lower(): r for r in reqs}


def test_sdk_floor_is_0_2_and_capped_below_1() -> None:
    sdk = _runtime_requirements()["prismal-sdk"]
    spec = sdk.specifier
    # Every 0.1.x release must be rejected; the 0.2 line (incl. its dev
    # pre-release while unpublished) and later 0.x must be accepted.
    assert not spec.contains(Version("0.1.9"), prereleases=True)
    assert spec.contains(Version("0.2.0.dev0"), prereleases=True)
    assert spec.contains(Version("0.2.0"))
    assert spec.contains(Version("0.9.5"))
    assert not spec.contains(Version("1.0.0"))


def _assert_tested_minor_pin(name: str) -> None:
    req = _runtime_requirements()[name]
    lower = [s for s in req.specifier if s.operator == ">="]
    upper = [s for s in req.specifier if s.operator == "<"]
    assert len(lower) == 1 and len(upper) == 1, f"{name} must be >=X.Y,<X.Y+1"
    lo, hi = Version(lower[0].version), Version(upper[0].version)
    assert (hi.major, hi.minor) == (lo.major, lo.minor + 1), (
        f"{name} must be pinned to a single tested minor, got {req.specifier}"
    )


def test_textual_pinned_to_a_tested_minor() -> None:
    _assert_tested_minor_pin("textual")


def test_platformdirs_pinned_to_a_tested_minor() -> None:
    _assert_tested_minor_pin("platformdirs")


def test_no_engine_host_or_http_dependency_declared() -> None:
    names = set(_runtime_requirements())
    forbidden = {"prismal-ai", "prismal", "prismal-server", "httpx"}
    assert not names & forbidden, f"forbidden runtime deps: {names & forbidden}"
