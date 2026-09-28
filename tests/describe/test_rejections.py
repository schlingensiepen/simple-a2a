"""Thirteen types, a status that follows from the type, and no refusal unmapped.

The catalogue is closed, and "closed" only means something if something checks it.
Two of these tests are that check: one counts the types against the number written
down, the other walks every refusal the operations can raise and insists it has a
type — so a new refusal cannot quietly answer as somebody else's.
"""

from __future__ import annotations

import inspect

import pytest

from simple_a2a.describe import rejections
from simple_a2a.domain import refusals


def test_there_are_thirteen_types_and_no_fourteenth() -> None:
    """The number is the promise; a test is what keeps it one."""
    assert len(list(rejections.Type)) == 13
    assert len(rejections.STATUS) == 13
    assert set(rejections.STATUS) == set(rejections.Type)


def test_success_is_always_the_same_status() -> None:
    """One success status is one rule fewer for whoever builds a tool."""
    assert rejections.SUCCESS == 200


@pytest.mark.parametrize("kind", list(rejections.Type))
def test_every_type_has_exactly_one_status(kind: rejections.Type) -> None:
    """Derived from the type, never chosen at the call site."""
    assert 400 <= rejections.STATUS[kind] <= 599


def test_the_statuses_are_the_ones_the_catalogue_names() -> None:
    assert rejections.STATUS[rejections.Type.UNKNOWN_ADDRESS] == 404
    assert rejections.STATUS[rejections.Type.WRONG_VERB] == 405
    assert rejections.STATUS[rejections.Type.NO_TOKEN] == 401
    assert rejections.STATUS[rejections.Type.TOKEN_REVOKED] == 401
    assert rejections.STATUS[rejections.Type.WRONG_TOKEN] == 403
    assert rejections.STATUS[rejections.Type.NOT_REALM_MASTER] == 403
    assert rejections.STATUS[rejections.Type.UNKNOWN_NAME] == 404
    assert rejections.STATUS[rejections.Type.UNKNOWN_IDENTIFIER] == 404
    assert rejections.STATUS[rejections.Type.INVITATION_USED] == 409
    assert rejections.STATUS[rejections.Type.NAME_TAKEN] == 409
    assert rejections.STATUS[rejections.Type.INVALID_INPUT] == 400
    assert rejections.STATUS[rejections.Type.TOO_LARGE] == 413
    assert rejections.STATUS[rejections.Type.INTERNAL] == 500


def test_every_refusal_the_operations_can_raise_has_a_type() -> None:
    """A new refusal has to be mapped deliberately, not inherit somebody's type.

    Walks the module rather than a hand-kept list, so adding a refusal and
    forgetting the mapping is a red run rather than a rejection that says the wrong
    thing.
    """
    raisable = {
        found
        for _, found in inspect.getmembers(refusals, inspect.isclass)
        if issubclass(found, refusals.Refused) and found is not refusals.Refused
    }

    unmapped = sorted(found.__name__ for found in raisable if found not in rejections.OF_REFUSAL)

    assert not unmapped, f"no type in the catalogue for {unmapped}"


def test_the_type_of_a_refusal_is_its_own_and_not_a_parent_s() -> None:
    assert rejections.type_of(refusals.NoToken()) is rejections.Type.NO_TOKEN
    assert rejections.type_of(refusals.TokenRevoked()) is rejections.Type.TOKEN_REVOKED
    assert (
        rejections.type_of(refusals.NameTaken("Otto", namespace="member"))
        is rejections.Type.NAME_TAKEN
    )


def test_a_refusal_nobody_mapped_is_an_error_rather_than_a_guess() -> None:
    class Invented(refusals.Refused):
        pass

    with pytest.raises(KeyError):
        rejections.type_of(Invented())


def test_the_detail_carries_the_facts_a_text_will_name() -> None:
    """As named fields, not as prose a reader has to parse back out."""
    too_large = refusals.TooLarge("body", limit=1024, actual=2048, unit="bytes")
    assert rejections.detail_of(too_large) == {
        "field": "body",
        "limit": 1024,
        "actual": 2048,
        "unit": "bytes",
    }
    assert rejections.detail_of(refusals.InvalidInput("subject", reason="text")) == {
        "field": "subject"
    }
    assert rejections.detail_of(refusals.UnknownName("Niemand", namespace="member")) == {
        "name": "Niemand"
    }
    assert rejections.detail_of(refusals.WrongToken("observer")) == {"needed": "observer"}
    assert rejections.detail_of(refusals.NotRealmMaster()) == {}


def test_the_body_is_the_type_the_text_and_the_facts() -> None:
    made = rejections.Rejection(
        type=rejections.Type.TOO_LARGE,
        message="The body is over the limit. Attach it as a file instead.",
        detail={"field": "body", "limit": 1024},
    )

    assert made.status == 413
    assert made.body() == {
        "type": "zu-groß",
        "message": "The body is over the limit. Attach it as a file instead.",
        "field": "body",
        "limit": 1024,
    }


def test_a_type_is_written_the_way_it_goes_over_the_wire() -> None:
    """The value is the wire value; nothing translates it on the way out."""
    assert str(rejections.Type.NO_TOKEN) == "kein-token"
    assert str(rejections.Type.TOO_LARGE) == "zu-groß"
