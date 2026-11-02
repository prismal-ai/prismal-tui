"""TUI-01-01 — process-wide, lazily built SDK client (SPEC-TUI-APP-003, AUT-001/003)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from prismal_tui import client as client_mod
from prismal_tui.settings import PrismalTuiSettings


class RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.instances: list[FakeSdkClient] = []

    def __call__(self, base_url: str, **kwargs: Any) -> FakeSdkClient:
        self.calls.append({"base_url": base_url, **kwargs})
        inst = FakeSdkClient()
        self.instances.append(inst)
        return inst


class FakeSdkClient:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    client_mod._reset_for_tests()
    yield
    client_mod._reset_for_tests()


def _settings(tmp_path: Path, **kw: Any) -> PrismalTuiSettings:
    return PrismalTuiSettings(store_path=tmp_path / "c.db", **kw)


def test_built_lazily_once_with_settings(tmp_path: Path) -> None:
    factory = RecordingFactory()
    s = _settings(
        tmp_path,
        server_url="https://h.example",
        token=SecretStr("tok"),
        org_id="acme",
    )
    assert factory.calls == []  # nothing built at import / settings time
    first = client_mod.get_client(s, factory=factory)
    second = client_mod.get_client(s, factory=factory)
    assert first is second
    assert factory.calls == [
        {"base_url": "https://h.example", "token": "tok", "org_id": "acme"}
    ]


def test_no_token_and_no_org_pass_none(tmp_path: Path) -> None:
    factory = RecordingFactory()
    client_mod.get_client(_settings(tmp_path), factory=factory)
    assert factory.calls[0]["token"] is None
    assert factory.calls[0]["org_id"] is None


def test_get_client_before_configuration_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        client_mod.get_client()


def test_get_client_without_settings_returns_the_built_one(tmp_path: Path) -> None:
    factory = RecordingFactory()
    built = client_mod.get_client(_settings(tmp_path), factory=factory)
    assert client_mod.get_client() is built


async def test_close_client_closes_once_and_allows_rebuild(tmp_path: Path) -> None:
    factory = RecordingFactory()
    s = _settings(tmp_path)
    client_mod.get_client(s, factory=factory)
    await client_mod.close_client()
    await client_mod.close_client()  # idempotent
    assert factory.instances[0].closed == 1
    client_mod.get_client(s, factory=factory)
    assert len(factory.instances) == 2


def test_default_factory_is_the_real_async_sdk_client(tmp_path: Path) -> None:
    from prismal_sdk import AsyncPrismalClient

    built = client_mod.get_client(_settings(tmp_path))
    assert isinstance(built, AsyncPrismalClient)
