"""Identifiers: 256 bits of randomness, one space, no second kind.

Every identifier in the service has the same shape — messages, files,
invitations, tokens and aliases alike. There is exactly one identifier space and
nothing is ever minted beside it: a second kind of identifier is a second set of
rules about what may be compared with what, and those rules are not written down
anywhere until something breaks.

43 characters of base64url without padding is what 32 random bytes come to. The
padding is dropped because an identifier travels in a path and in a header, and
`=` has to be escaped in both.
"""

from __future__ import annotations

import re
import secrets

#: Bytes of randomness behind one identifier.
ID_BYTES = 32

#: Characters an identifier is written with. 32 bytes base64-encoded are 44
#: characters, the last of which is always padding, so 43 remain.
ID_LENGTH = 43

ID_PATTERN = re.compile(rf"\A[A-Za-z0-9_-]{{{ID_LENGTH}}}\Z")


def new_id() -> str:
    """A fresh identifier. Unguessable, because guessing one is reading."""
    return secrets.token_urlsafe(ID_BYTES)[:ID_LENGTH]


def is_id(value: object) -> bool:
    """Whether this is an identifier of ours, by shape alone.

    Shape, not existence: this says nothing about whether anything is stored
    under it. It is here so that a caller's typo is answered as a typo rather
    than looked up.
    """
    return isinstance(value, str) and ID_PATTERN.match(value) is not None
