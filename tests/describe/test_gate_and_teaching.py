"""The gate finds what it is for, and a missing teaching text is a red build.

Each of these stages a description that is wrong in exactly one way and checks the
gate says so. A gate is only worth having if it has been shown to catch things —
one that has never failed is indistinguishable from one that always passes.
"""

from __future__ import annotations

import pytest

from simple_a2a.describe import gate
from simple_a2a.describe.rejections import Type
from simple_a2a.describe.teaching import BEHIND_A_TOKEN, Register

RULES = gate.Rules(surface="messaging")


def described(**extra):
    return {
        "paths": {
            "/peers/messages": {
                "post": {
                    "summary": "Send a message to members of your own team.",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "properties": {
                                        "subject": {
                                            "description": "One line, plain text.",
                                            "example": "Shift handover",
                                        }
                                    }
                                }
                            }
                        }
                    },
                    **extra,
                }
            }
        }
    }


def test_a_complete_description_passes() -> None:
    assert gate.check_description(described(), RULES)


def test_a_description_with_no_routes_at_all_fails() -> None:
    """Otherwise the gate passes loudest on the emptiest document."""
    found = gate.check_description({"paths": {}}, RULES)

    assert not found
    assert "no routes" in found.report()


def test_a_route_without_a_description_fails() -> None:
    document = described()
    del document["paths"]["/peers/messages"]["post"]["summary"]

    found = gate.check_description(document, RULES)

    assert not found
    assert "no description" in found.report()


@pytest.mark.parametrize("useless", ["", "   ", "TODO", "TBD", "...", "-"])
def test_a_description_that_says_nothing_counts_as_none(useless: str) -> None:
    """All six pass a "is there a description" check and help nobody."""
    document = described()
    document["paths"]["/peers/messages"]["post"]["summary"] = useless

    assert not gate.check_description(document, RULES)


def test_a_field_without_an_example_fails() -> None:
    """The example is the load-bearing half."""
    document = described()
    schema = document["paths"]["/peers/messages"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    del schema["properties"]["subject"]["example"]

    found = gate.check_description(document, RULES)

    assert not found
    assert "no example" in found.report()


def test_a_nested_field_is_not_missed() -> None:
    """Where a field hides from a check that only looks at the top level."""
    document = described()
    schema = document["paths"]["/peers/messages"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    schema["properties"]["attachments"] = {
        "description": "Files and references.",
        "example": [],
        "items": {"properties": {"name": {"description": "The name."}}},
    }

    found = gate.check_description(document, RULES)

    assert not found
    assert "attachments[].name" in found.report()


def test_a_parameter_without_a_description_or_example_fails() -> None:
    document = described(parameters=[{"name": "limit"}])

    found = gate.check_description(document, RULES)

    assert not found
    assert "limit" in found.report()


def test_a_schema_component_is_checked_too() -> None:
    document = described()
    document["components"] = {
        "schemas": {"Envelope": {"properties": {"sender_name": {"example": "Anna"}}}}
    }

    found = gate.check_description(document, RULES)

    assert not found
    assert "Envelope.sender_name" in found.report()


def test_a_placeholder_left_in_a_rendered_text_fails() -> None:
    """Run on what is served: a placeholder is only wrong once it is rendered."""
    found = gate.check_texts({"entry": "Reach it at %%BASE%%."})

    assert not found
    assert "placeholder" in found.report()


def test_http_outside_the_entry_fails() -> None:
    """A part carrying a host name is wrong as soon as it is served from a second."""
    assert gate.check_texts(
        {"entry": "Reach it at https://example.test.", "sending": "POST /peers/messages"}
    )

    found = gate.check_texts({"sending": "POST http://example.test/peers/messages"})

    assert not found
    assert "sending" in found.report()


def test_a_missing_teaching_text_is_found_before_anybody_meets_it() -> None:
    register = Register("messaging")
    register.operation("POST /peers/messages", refuses={Type.UNKNOWN_NAME, *BEHIND_A_TOKEN})

    register.teach(
        "POST /peers/messages", Type.UNKNOWN_NAME, "No member of your team is called that."
    )

    found = gate.check_teaching(register)
    assert not found
    assert "kein-token" in found.report()


def test_a_register_with_every_text_passes() -> None:
    register = Register("messaging")
    register.operation("GET /inbox", refuses=set(BEHIND_A_TOKEN))
    for kind in BEHIND_A_TOKEN:
        register.teach("GET /inbox", kind, f"something useful about {kind}")

    assert gate.check_teaching(register)
    assert register.rejection("GET /inbox", _no_token()).message.startswith("something useful")


def test_a_text_for_a_type_the_operation_cannot_give_is_refused() -> None:
    """Either the text is in the wrong place or the list is wrong; both are worth stopping for."""
    register = Register("admin")
    register.operation("POST /realms", refuses={Type.NAME_TAKEN})

    with pytest.raises(KeyError):
        register.teach("POST /realms", Type.NOT_REALM_MASTER, "nope")


def test_a_text_for_an_operation_nobody_declared_is_refused() -> None:
    register = Register("admin")

    with pytest.raises(KeyError):
        register.teach("POST /invented", Type.NAME_TAKEN, "nope")


def test_asking_for_a_text_that_was_never_written_raises() -> None:
    """There is no default. A rejection that says only its type helps nobody."""
    register = Register("admin")
    register.operation("POST /realms", refuses={Type.NAME_TAKEN})

    with pytest.raises(KeyError):
        register.text_for("POST /realms", Type.NAME_TAKEN)


def _no_token():
    from simple_a2a.domain import refusals

    return refusals.NoToken()
