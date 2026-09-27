"""One identifier space, three name rules, one time format.

Small things, each with a failure that is expensive later: an identifier that
needs escaping in a path, two participants in one team whose names differ only in
case, and a clock too coarse to order what the holdings are ordered by.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from simple_a2a.core import clock, ids
from simple_a2a.core.names import (
    NAME_MAX_LENGTH,
    NameProblem,
    check_name,
    comparison_key,
    is_name,
    same_name,
)


def test_an_identifier_is_43_characters_of_url_safe_text() -> None:
    made = ids.new_id()

    assert len(made) == ids.ID_LENGTH == 43
    assert ids.is_id(made)
    # Nothing here needs escaping in a path or a header, which is why the
    # padding is dropped.
    assert "=" not in made and "/" not in made and "+" not in made


def test_identifiers_do_not_repeat() -> None:
    assert len({ids.new_id() for _ in range(2000)}) == 2000


@pytest.mark.parametrize(
    "value",
    ["", "short", "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "/", None, 43, "a" * 42 + " "],
)
def test_what_is_not_an_identifier_is_not_mistaken_for_one(value: object) -> None:
    assert not ids.is_id(value)


@pytest.mark.parametrize("value", ["a", "Otto", "team one", "a-b_c", "A" * NAME_MAX_LENGTH, "42"])
def test_a_usable_name_is_accepted(value: str) -> None:
    assert is_name(value)
    assert check_name(value) is None


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("", NameProblem.EMPTY),
        ("a" * (NAME_MAX_LENGTH + 1), NameProblem.TOO_LONG),
        (" leading", NameProblem.EDGE_SPACE),
        ("trailing ", NameProblem.EDGE_SPACE),
        ("two  spaces", NameProblem.DOUBLE_SPACE),
        ("tab\there", NameProblem.CHARACTERS),
        ("new\nline", NameProblem.CHARACTERS),
        ("slash/es", NameProblem.CHARACTERS),
        ("dot.ted", NameProblem.CHARACTERS),
        ("emoji \N{SNOWMAN}", NameProblem.CHARACTERS),
    ],
)
def test_each_broken_rule_is_reported_as_itself(value: str, problem: NameProblem) -> None:
    """One reason per rule, so the answer can say which one it was."""
    assert check_name(value) == problem


def test_edge_and_double_spaces_are_refused_rather_than_repaired() -> None:
    """Trimming would leave the caller and the service holding different names."""
    assert check_name(" Otto ") is NameProblem.EDGE_SPACE
    assert check_name("Otto  Meyer") is NameProblem.DOUBLE_SPACE


def test_names_are_compared_without_regard_to_case() -> None:
    assert same_name("Otto", "otto")
    assert comparison_key("OTTO") == comparison_key("otto")
    assert not same_name("Otto", "Otto Meyer")


def test_a_timestamp_is_utc_with_milliseconds() -> None:
    written = clock.to_iso(datetime(2026, 9, 27, 14, 3, 11, 482_913, tzinfo=UTC))

    assert written == "2026-09-27T14:03:11.482Z"
    assert len(clock.now_iso()) == len(clock.EXAMPLE)


def test_a_moment_elsewhere_is_written_in_utc() -> None:
    elsewhere = datetime(2026, 9, 27, 16, 3, 11, 0, tzinfo=timezone(timedelta(hours=2)))

    assert clock.to_iso(elsewhere) == "2026-09-27T14:03:11.000Z"


def test_a_moment_without_a_timezone_is_refused() -> None:
    """Guessing a zone is how a service ends up an hour out for half the year."""
    with pytest.raises(ValueError, match="without a timezone"):
        clock.to_iso(datetime(2026, 9, 27, 14, 3, 11))  # noqa: DTZ001
