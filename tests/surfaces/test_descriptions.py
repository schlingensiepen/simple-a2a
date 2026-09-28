"""What the three descriptions share: readable, unique operation identifiers.

An identifier is what a generated client — the MCP server beside this service among
them — names a call by. The framework's default is unique and unreadable; ours are
the names in the code, and those are unique only because nobody has repeated one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("surface", ["participants", "no_token", "observation"])
def test_every_operation_has_its_own_readable_identifier(
    surface: str, request: pytest.FixtureRequest
) -> None:
    client: TestClient = request.getfixturevalue(surface)
    document = client.get("/openapi.json").json()

    identifiers = [
        operation["operationId"]
        for verbs in document["paths"].values()
        for operation in verbs.values()
    ]

    assert len(identifiers) == len(set(identifiers)), sorted(identifiers)
    for identifier in identifiers:
        assert identifier.isidentifier(), identifier
        assert not identifier.endswith(("_get", "_post", "_put")), identifier


@pytest.mark.parametrize("surface", ["no_token", "observation"])
def test_only_the_participant_surface_offers_the_mcp_package(
    surface: str, request: pytest.FixtureRequest
) -> None:
    """The one form that is not on every surface, and the reason is in its guide."""
    client: TestClient = request.getfixturevalue(surface)

    assert client.get("/mcp.zip").status_code == 404
    assert "mcp" not in client.get("/").text.lower()
