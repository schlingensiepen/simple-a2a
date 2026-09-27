"""A reader never sees half a file, and a token is checked before it is looked up.

The first half is what lets the holdings do without locks: a write is complete or
absent, and a state change is a rename. The second is the shape check that keeps
a typo from becoming a lookup.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from simple_a2a.core import atomic, tokens


def test_a_write_arrives_whole_and_private(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "down" / "thing"

    atomic.write_text(target, "content")

    assert target.read_text(encoding="utf-8") == "content"
    assert stat.S_IMODE(target.stat().st_mode) == atomic.PRIVATE_MODE


def test_a_write_leaves_nothing_behind(tmp_path: Path) -> None:
    """Not even on the way: the temporary is in the target's own directory."""
    target = tmp_path / "thing"

    atomic.write_bytes(target, b"x")

    assert [p.name for p in sorted(tmp_path.iterdir())] == ["thing"]


def test_a_failed_write_removes_its_temporary_and_leaves_the_old_content(tmp_path: Path) -> None:
    target = tmp_path / "thing"
    atomic.write_text(target, "old")

    class Unwritable:
        def __len__(self) -> int:
            raise OSError("no room")

    with pytest.raises((OSError, TypeError)):
        atomic.write_bytes(target, Unwritable())  # type: ignore[arg-type]

    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in sorted(tmp_path.iterdir())] == ["thing"]


def test_overwriting_replaces_in_one_step(tmp_path: Path) -> None:
    target = tmp_path / "thing"
    atomic.write_text(target, "first")

    atomic.write_text(target, "second")

    assert target.read_text(encoding="utf-8") == "second"


def test_moving_is_how_a_state_changes(tmp_path: Path) -> None:
    source = tmp_path / "new" / "item"
    atomic.write_text(source, "payload")
    target = tmp_path / "done" / "item"

    atomic.move(source, target)

    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "payload"


def test_moving_onto_an_existing_target_succeeds(tmp_path: Path) -> None:
    """A state change that failed only sometimes would be worse than one that never does."""
    source = tmp_path / "a"
    target = tmp_path / "b"
    atomic.write_text(source, "new")
    atomic.write_text(target, "old")

    atomic.move(source, target)

    assert target.read_text(encoding="utf-8") == "new"


def test_a_private_directory_is_private_whatever_the_umask(tmp_path: Path) -> None:
    """`mkdir`'s mode is masked by the umask, quietly."""
    directory = tmp_path / "holdings"

    atomic.ensure_private_directory(directory)
    atomic.ensure_private_directory(directory)

    assert stat.S_IMODE(directory.stat().st_mode) == atomic.PRIVATE_DIR_MODE


def test_a_token_is_an_identifier() -> None:
    made = tokens.new_token()

    assert tokens.is_token(made)
    assert len(made) == 43


@pytest.mark.parametrize("value", ["", "nope", None, "a" * 44])
def test_what_is_not_a_token_is_not_mistaken_for_one(value: object) -> None:
    assert not tokens.is_token(value)


def test_two_tokens_are_compared_as_secrets() -> None:
    made = tokens.new_token()

    assert tokens.same_token(made, made)
    assert not tokens.same_token(made, tokens.new_token())


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER abc", "abc"),
        ("Bearer   abc  ", "abc"),
        ("Bearer\tabc", "abc"),
        (None, None),
        ("", None),
        ("abc", None),
        ("Basic abc", None),
        ("Bearer", None),
        ("Bearer ", None),
    ],
)
def test_the_scheme_is_read_the_way_http_defines_it(
    header: str | None, expected: str | None
) -> None:
    """Case-insensitive: a service that insisted otherwise would reject a correct caller."""
    assert tokens.from_authorization(header) == expected
