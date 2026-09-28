"""One installation, served over HTTP, for the surface tests.

Built the way the process builds it, so that what is tested is what is served: the
same application factory, the same context, the same texts.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", message=".*httpx.*", category=DeprecationWarning)

from fastapi.testclient import TestClient

from simple_a2a.admin.app import build_app as build_admin
from simple_a2a.core import config
from simple_a2a.domain.context import Context
from simple_a2a.messaging.app import build_app as build_messaging
from simple_a2a.observe.app import build_app as build_observe
from simple_a2a.store.holdings import Holdings
from simple_a2a.store.layout import Layout

ADMIN_SECRET = "a" * 40

BUILD = {
    "version": "0.1.0.dev0",
    "build_id": "test-build",
    "built_at": "2026-09-28T00:00:00.000Z",
}


@pytest.fixture
def context(tmp_path: Path) -> Context:
    holdings = Holdings(Layout(root=tmp_path / "data"))
    holdings.prepare()
    return Context(
        holdings=holdings,
        config=config.load({config.DATA_DIR: str(tmp_path / "data")}),
        admin_secret=ADMIN_SECRET,
    )


@pytest.fixture
def admin(context: Context) -> Iterator[TestClient]:
    with TestClient(build_admin(context, build=BUILD), raise_server_exceptions=False) as client:
        client.headers.update({"Authorization": f"Bearer {ADMIN_SECRET}"})
        yield client


@pytest.fixture
def no_token(context: Context) -> Iterator[TestClient]:
    """The same surface with nothing presented, for the answers before an operation."""
    with TestClient(build_admin(context, build=BUILD), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def participants(context: Context) -> Iterator[TestClient]:
    """The participant surface, with nothing presented.

    Tokens go on individual calls rather than on the client, because most of what is
    interesting here is two or three different callers on one installation.
    """
    with TestClient(build_messaging(context, build=BUILD), raise_server_exceptions=False) as client:
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def observation(context: Context) -> Iterator[TestClient]:
    """The observation surface, with nothing presented."""
    with TestClient(build_observe(context, build=BUILD), raise_server_exceptions=False) as client:
        yield client
