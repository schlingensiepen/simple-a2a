"""What the three surfaces share: readable operation identifiers, and unknown fields named.

An identifier is what a generated client — the MCP server beside this service among
them — names a call by. The framework's default is unique and unreadable; ours are
the names in the code, and those are unique only because nobody has repeated one.
"""

from __future__ import annotations

import re
from typing import Any, get_args, get_origin

import pytest
from conftest import bearer
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from simple_a2a.describe.rejections import Type
from simple_a2a.messaging import texts as messaging_texts
from simple_a2a.messaging.models import AttachmentIn, SendToPeers


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


def written(model: type[BaseModel]) -> list[str]:
    """The fields of a model as a caller writes them — the rule the answer uses."""
    return [info.alias or name for name, info in model.model_fields.items()]


def models_in(annotation: Any) -> list[type[BaseModel]]:
    """Every model an annotation holds, through lists, `None` and unions."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for argument in get_args(annotation) for model in models_in(argument)]


def nested(model: type[BaseModel]) -> list[type[BaseModel]]:
    """A model and every model inside it, each once."""
    found = [model]
    for current in found:
        for info in current.model_fields.values():
            for inner in models_in(info.annotation):
                if inner not in found:
                    found.append(inner)
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
            assert listed_fields(body["message"]) == written(model), path
            covered.append(f"{method} {path}")

    assert len(covered) == 11, covered


def test_no_operation_with_a_json_body_ignores_an_unknown_field(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """Read from the routes, so a new operation with a body cannot slip past."""
    ignoring = [
        f"{method} {path}: {inner.__name__}"
        for client in (admin, participants, observation)
        for method, path, model in body_routes(client)
        for inner in nested(model)
        if inner.model_config.get("extra") != "forbid"
    ]

    assert ignoring == []


def test_request_bodies_have_the_shape_read_here(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """The unknown-field answer finds its object through lists and `None` only.

    It reads one body parameter holding one model, steps by field name or list
    index, and lists `alias or name`. A second body parameter, a union of models,
    a dict of models or a `validation_alias` would make it list the wrong fields
    or none; this test is red before that happens, not after.
    """
    wrong = []
    for client in (admin, participants, observation):
        for route in client.app.routes:
            if not isinstance(route, APIRoute) or route.body_field is None:
                continue
            where = route.path_format
            if len(route.dependant.body_params) != 1:
                wrong.append(f"{where}: {len(route.dependant.body_params)} body parameters")
            held = models_in(route.body_field.field_info.annotation)
            if len(held) != 1:
                wrong.append(f"{where}: body holds {held}")
                continue
            for model in nested(held[0]):
                for name, info in model.model_fields.items():
                    if info.validation_alias is not None:
                        wrong.append(f"{where}: {model.__name__}.{name} has validation_alias")
                    if len(models_in(info.annotation)) > 1:
                        wrong.append(f"{where}: {model.__name__}.{name} is a union of models")
                    if dict_of_model(info.annotation):
                        wrong.append(f"{where}: {model.__name__}.{name} is a dict of models")

    assert wrong == []


def dict_of_model(annotation: Any) -> bool:
    if get_origin(annotation) is dict:
        return bool(models_in(annotation))
    return any(dict_of_model(argument) for argument in get_args(annotation))


@pytest.mark.parametrize(
    "name",
    ["a`b", "a\nb", "a\x07b", "x" * 10_000, "a.b", "ä", ""],
    ids=["backtick", "newline", "control", "long", "dotted", "non-ascii", "empty"],
)
def test_a_name_that_is_not_plain_is_not_repeated(
    name: str, participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    """The name is the caller's input: quoted back only when it is short and plain."""
    answer = participants.post(
        "/peers/messages",
        json={"subject": "s", "body": "b", name: True},
        headers=callers["peer"],
    )

    assert answer.status_code == 400
    body = answer.json()
    assert body["type"] == "invalid-input"
    assert body["field"] == "body"
    assert not name or name not in body["message"]
    assert "\n" not in body["message"] and "\x07" not in body["message"]
    assert body["message"].startswith("A name in this request is not a field of this request.")
    assert listed_fields(body["message"]) == written(SendToPeers)
    assert len(answer.content) < 1000


def test_a_name_that_is_not_plain_inside_an_entry_names_only_the_entry(
    participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    answer = participants.post(
        "/peers/messages",
        json={
            "subject": "s",
            "body": "b",
            "attachments": [{"name": "x", "file_id": "f", "a`b\nc": 1}],
        },
        headers=callers["peer"],
    )

    assert answer.status_code == 400
    body = answer.json()
    assert body["type"] == "invalid-input"
    assert body["field"] == "attachments.0"
    assert "a`b" not in body["message"] and "\n" not in body["message"]
    assert body["message"].startswith("A name in `attachments.0` is not a field of this request.")
    assert listed_fields(body["message"], "attachments.0") == written(AttachmentIn)


def test_a_plain_name_at_the_length_limit_is_still_repeated(
    participants: TestClient, callers: dict[str, dict[str, str]]
) -> None:
    name = "n" * 64
    answer = participants.post(
        "/peers/messages",
        json={"subject": "s", "body": "b", name: True},
        headers=callers["peer"],
    )

    assert answer.json()["field"] == name
    assert answer.json()["message"].startswith(f"`{name}` is not a field of this request.")


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
    assert listed_fields(body["message"], "attachments.1") == written(AttachmentIn)


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


# ------------------------------------------------------------- security


def without_a_token(client: TestClient, path: str, verb: str, operation: dict[str, Any]) -> int:
    """The status an operation answers when nothing is presented, with any path filled in."""
    for parameter in operation.get("parameters") or []:
        if parameter.get("in") == "path":
            path = path.replace("{" + parameter["name"] + "}", "x")
    if verb in ("post", "put", "patch"):
        return client.request(verb.upper(), path, json={}).status_code
    return client.request(verb.upper(), path).status_code


@pytest.mark.parametrize("surface", ["participants", "no_token", "observation"])
def test_exactly_the_operations_behind_a_token_declare_security(
    surface: str, request: pytest.FixtureRequest
) -> None:
    """A 401 without a token, and the bearer scheme in the description, go together."""
    client: TestClient = request.getfixturevalue(surface)
    document = client.get("/openapi.json").json()
    scheme = document["components"]["securitySchemes"]["bearer"]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")

    secured, open_ = [], []
    for path, verbs in document["paths"].items():
        for verb, operation in verbs.items():
            status = without_a_token(client, path, verb, operation)
            where = f"{verb.upper()} {path}"
            if "security" in operation:
                assert operation["security"] == [{"bearer": []}], where
                assert status == 401, f"{where} declares security but answered {status}"
                secured.append(where)
            else:
                assert status != 401, f"{where} answers 401 but declares no security"
                open_.append(where)
    assert secured, "no operation behind a token at all"
    assert "GET /health" in open_, "the interface description itself answered above"
    if surface == "participants":
        assert "POST /invitations/redeem" in open_
        assert {"GET /skill.zip", "GET /mcp.zip", "GET /guide"} <= set(open_)
