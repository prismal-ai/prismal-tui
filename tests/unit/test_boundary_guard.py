"""AST boundary guard — SPEC-TUI-APP-002 and SPEC-TUI-APP-005.

- Nothing under ``prismal_tui/`` imports ``prismal`` (engine) or
  ``prismal_server`` (host), and nothing uses ``httpx`` directly.
- Nothing imports private ``prismal_sdk._*`` transport internals.
- ``prismal_tui/widgets/`` additionally never imports ``httpx``, ``_sse`` or
  ``_transport`` in any form (it only sees ``ConversationSession`` and the
  SDK's re-exported typed models).

Dynamic imports with a literal module name (``importlib.import_module("x")``,
``__import__("x")``) are checked too. The guard is itself tested against
synthetic trees so it can never pass vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "prismal_tui"

FORBIDDEN_TOP_LEVEL = {"prismal", "prismal_server", "httpx"}
WIDGET_FORBIDDEN_PARTS = {"httpx", "_sse", "_transport"}


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, a.name) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append((node.lineno, node.module))
                found.extend(
                    (node.lineno, f"{node.module}.{a.name}") for a in node.names
                )
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if (
                name in {"import_module", "__import__"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.append((node.lineno, node.args[0].value))
    return found


def find_violations(package: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package)
        in_widgets = rel.parts[0] == "widgets"
        tree = ast.parse(path.read_text(), filename=str(path))
        for lineno, module in _imported_modules(tree):
            parts = module.split(".")
            where = f"{rel}:{lineno} imports {module!r}"
            if parts[0] in FORBIDDEN_TOP_LEVEL:
                violations.append(f"{where} (APP-002)")
            elif parts[0] == "prismal_sdk" and any(
                p.startswith("_") for p in parts[1:]
            ):
                violations.append(f"{where} (SDK internals)")
            if in_widgets and WIDGET_FORBIDDEN_PARTS & set(parts):
                violations.append(f"{where} (APP-005)")
    return violations


def test_package_respects_the_boundary() -> None:
    assert PACKAGE.is_dir()
    assert find_violations(PACKAGE) == []


# ── The guard guards itself ────────────────────────────────────────────────


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "pkg"
    for rel, src in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(src)
    return root


@pytest.mark.parametrize(
    "src",
    [
        "import prismal\n",
        "import prismal.agents as a\n",
        "from prismal import Engine\n",
        "from prismal_server.app import app\n",
        "import httpx\n",
        "from httpx import AsyncClient\n",
        "import importlib\nimportlib.import_module('prismal_server')\n",
        "__import__('httpx')\n",
        "from prismal_sdk._transport import raise_for_response\n",
        "from prismal_sdk import _sse\n",
    ],
)
def test_guard_flags_forbidden_imports(tmp_path: Path, src: str) -> None:
    assert find_violations(_tree(tmp_path, {"mod.py": src}))


@pytest.mark.parametrize(
    "src",
    [
        "from prismal_sdk import AsyncPrismalClient, TokenEvent\n",
        "from prismal_sdk.models import DoneEvent\n",
        "import prismal_sdk\n",
        "import prismalish\n",  # prefix match must not false-positive
        "from textual.app import App\n",
    ],
)
def test_guard_allows_public_sdk_and_unrelated_imports(
    tmp_path: Path, src: str
) -> None:
    assert find_violations(_tree(tmp_path, {"mod.py": src})) == []


def test_guard_flags_transport_names_only_in_widgets(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "widgets/transcript.py": "from somewhere import _sse\n",
            "session/conversation_session.py": "from somewhere import _sse\n",
        },
    )
    violations = find_violations(root)
    assert len(violations) == 1
    assert "widgets" in violations[0] and "APP-005" in violations[0]
