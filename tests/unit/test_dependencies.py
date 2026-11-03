"""SPEC-TUI-NFR-005 (DELTA-2026-11-host-0.3): dependency pins are deliberate.

- ``prismal-ai-sdk>=0.3,<1`` (the SDK's PyPI distribution name; the import
  module is still ``prismal_sdk``) — a lower floor fails this test.
- The SDK resolves from PyPI, never from a sibling checkout.
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


def test_sdk_is_the_pypi_distribution_floor_0_3_capped_below_1() -> None:
    reqs = _runtime_requirements()
    assert "prismal-sdk" not in reqs, "the SDK is published as prismal-ai-sdk"
    spec = reqs["prismal-ai-sdk"].specifier
    # run_agui / interrupt resume arrived in 0.3.0 (the first PyPI release).
    assert not spec.contains(Version("0.2.9"), prereleases=True)
    assert spec.contains(Version("0.3.0"))
    assert spec.contains(Version("0.9.5"))
    assert not spec.contains(Version("1.0.0"))


def test_sdk_resolves_from_pypi_not_a_sibling_checkout() -> None:
    data = tomllib.loads(PYPROJECT.read_text())
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    assert not {"prismal-sdk", "prismal-ai-sdk"} & set(sources), sources


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
