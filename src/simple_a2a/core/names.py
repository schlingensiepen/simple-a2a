"""Names: what a caller may choose, and why a rejection beats a repair.

A name is chosen by whoever creates something, and it has to be usable in a
path, comparable without surprises, and readable by a person looking at a
listing. Three rules do that, and each one exists because of a way it goes
wrong:

- **Character set and length.** Letters, digits, underscore, hyphen, space,
  1 to 64 characters. Enough for a sentence fragment, not enough for a payload.
- **Compared case-insensitively.** Otherwise `Otto` and `otto` sit in one team
  as two participants, and every message to either of them is a coin toss.
- **Edge and double spaces are refused, not trimmed.** Trimming is the tempting
  option and the wrong one: the caller keeps the name they typed, the service
  keeps a different one, and the two disagree forever after. Refusing hands the
  problem back while the caller still knows what they meant.

What this module does *not* do is decide what to answer. It reports which rule
was broken, as a plain reason, and the surface turns that into a rejection with
a text. A module down here that knew the rejection catalogue would be one `if`
away from growing an entry of its own.
"""

from __future__ import annotations

import re
from enum import StrEnum

NAME_MIN_LENGTH = 1
NAME_MAX_LENGTH = 64

#: The allowed characters. Written as an explicit class rather than as `\w`,
#: which under Unicode also matches letters from scripts nobody has asked for
#: and, worse, changes meaning with the locale of whoever reads the pattern.
NAME_PATTERN = re.compile(r"\A[A-Za-z0-9_\- ]+\Z")


class NameProblem(StrEnum):
    """Why a name was refused. One value per rule, so the answer can be exact."""

    EMPTY = "empty"
    TOO_LONG = "too-long"
    CHARACTERS = "characters"
    EDGE_SPACE = "edge-space"
    DOUBLE_SPACE = "double-space"


def check_name(value: object) -> NameProblem | None:
    """The problem with this name, or `None` when there is none."""
    if not isinstance(value, str) or not value:
        return NameProblem.EMPTY
    if len(value) > NAME_MAX_LENGTH:
        return NameProblem.TOO_LONG
    if value != value.strip(" "):
        return NameProblem.EDGE_SPACE
    if "  " in value:
        return NameProblem.DOUBLE_SPACE
    if NAME_PATTERN.match(value) is None:
        return NameProblem.CHARACTERS
    return None


def is_name(value: object) -> bool:
    return check_name(value) is None


def comparison_key(name: str) -> str:
    """The form two names are compared in.

    `casefold` rather than `lower`: it is the one meant for comparison, and it
    folds the cases `lower` leaves alone. Uniqueness is decided on this value,
    while the name that is stored and shown stays the one the caller chose.
    """
    return name.casefold()


def same_name(left: str, right: str) -> bool:
    return comparison_key(left) == comparison_key(right)
