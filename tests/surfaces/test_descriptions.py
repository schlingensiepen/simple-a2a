"""What the three surfaces share: readable operation identifiers, and unknown fields named.

An identifier is what a generated client — the MCP server beside this service among
them — names a call by. The framework's default is unique and unreadable; ours are
the names in the code, and those are unique only because nobody has repeated one.
"""

from __future__ import annotations

import re

import pytest
from conftest import bearer
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from simple_a2a.describe.rejections import Type
from simple_a2a.messaging import texts as messaging_texts
from simple_a2a.messaging.models import AttachmentIn


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


# ------------------------------------------------------------- unknown fields


def body_routes(client: TestClient) -> list[tuple[str, str, type[BaseModel]]]:
    """Every operation of a surface that takes a JSON body, with the model it reads."""
    found = []
    for route in client.app.routes:
        if isinstance(route, APIRoute) and route.body_field is not None:
            model = route.body_field.field_info.annotation
            assert isinstance(model, type) and issubclass(model, BaseModel), route.path_format
            for method in sorted(route.methods):
                found.append((method, route.path_format, model))
    return found


def listed_fields(message: str, owner: str = "") -> list[str]:
    lead = f"The fields of `{owner}` are " if owner else "Its fields are "
    assert lead in message, message
    return re.findall(r"`([^`]+)`", message.split(lead, 1)[1])


@pytest.fixture
def callers(admin: TestClient, participants: TestClient) -> dict[str, dict[str, str]]:
    """A realm master in a team, and a central service, for the operations behind a token."""
    admin.post("/realms", json={"realm_name": "household"})
    admin.post("/realms/household/teams", json={"team_name": "kitchen"})
    voucher = admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "display_name": "for Anna"},
    ).json()["invitation"]
    anna = participants.post("/invitations/redeem", json={"invitation": voucher}).json()["token"]
    voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna),
    ).json()["invitation"]
    weather = participants.post(
        "/invitations/redeem",
        json={"invitation": voucher, "member_self_image": "I answer about weather."},
    ).json()["token"]
    return {"peer": bearer(anna), "service": bearer(weather)}


def test_a_field_the_request_does_not_have_is_named_with_the_fields_it_has(
    admin: TestClient,
    participants: TestClient,
    observation: TestClient,
    callers: dict[str, dict[str, str]],
) -> None:
    """On every surface, for every body that refuses an unknown field.

    The fields in the answer are compared with the model the operation reads, so a
    field added to a request and missing from the answer — or the other way round —
    is a red test rather than a reader sent looking.
    """
    covered = []
    for surface, client in (
        ("admin", admin),
        ("messaging", participants),
        ("observe", observation),
    ):
        for method, path, model in body_routes(client):
            if model.model_config.get("extra") != "forbid":
                continue
            headers = {}
            if surface == "messaging" and path != "/invitations/redeem":
                headers = callers["service" if path.startswith("/aliases/") else "peer"]
            address = re.sub(r"\{[^}]+\}", "x", path)

            answer = client.request(method, address, json={"no_such_field": True}, headers=headers)

            assert answer.status_code == 400, (path, answer.text)
            body = answer.json()
            assert body["type"] == "invalid-input", path
            assert body["field"] == "no_such_field", path
            assert body["message"].startswith("`no_such_field` is not a field of this request."), (
                path
            )
            assert listed_fields(body["message"]) == list(model.model_fields), path
            covered.append(f"{method} {path}")

    assert len(covered) == 11, covered


def test_no_operation_with_a_json_body_ignores_an_unknown_field(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """Read from the routes, so a new operation with a body cannot slip past."""
    ignoring = [
        f"{method} {path}"
        for client in (admin, participants, observation)
        for method, path, model in body_routes(client)
        if model.model_config.get("extra") != "forbid"
    ]

    assert ignoring == []


def test_to_instead_of_recipients_says_so_rather_than_explaining_the_body(
    participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    answer = participants.post(
        "/peers/messages",
        json={"to": ["Berta"], "subject": "s", "body": "b"},
        headers=callers["peer"],
    )

    assert answer.status_code == 400
    assert answer.json() == {
        "type": "invalid-input",
        "message": "`to` is not a field of this request. Its fields are `subject`, `body`, "
        "`body_file_id`, `attachments`, `in_reply_to`, `recipients`.",
        "field": "to",
    }


def test_an_unknown_field_wins_over_the_missing_one_it_stands_for(
    participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    """`to` for `recipient` is two errors, and the unknown name is the one to act on."""
    answer = participants.post(
        "/services/messages",
        json={"to": "weather", "subject": "s", "body": "b"},
        headers=callers["peer"],
    )

    assert answer.json()["field"] == "to"
    assert "`recipient`" in answer.json()["message"]


def test_an_unknown_field_inside_an_entry_is_named_by_its_path(
    participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    answer = participants.post(
        "/peers/messages",
        json={
            "subject": "s",
            "body": "b",
            "attachments": [
                {"name": "x", "file_id": "f"},
                {"name": "y", "file_id": "f", "size": 1},
            ],
        },
        headers=callers["peer"],
    )

    assert answer.status_code == 400
    body = answer.json()
    assert body["field"] == "attachments.1.size"
    assert body["message"].startswith("`attachments.1.size` is not a field of this request.")
    assert listed_fields(body["message"], "attachments.1") == list(AttachmentIn.model_fields)


def test_every_other_input_error_keeps_the_operation_s_own_text(
    participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    own = messaging_texts.build().text_for("POST /peers/messages", Type.INVALID_INPUT)

    for wrong in (
        {"subject": ["not", "a", "line"], "body": "b"},
        {"body": "b"},
        {"subject": "s", "body": "b", "attachments": [{"file_id": "f"}]},
    ):
        answer = participants.post("/peers/messages", json=wrong, headers=callers["peer"])
        assert answer.status_code == 400, wrong
        assert answer.json()["message"] == own, wrong
