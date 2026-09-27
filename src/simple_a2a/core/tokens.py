"""Tokens: the shape of one, and how two are compared.

A token is an identifier — the same 43 characters as everything else, because
there is one identifier space. It names a capability and a place, and it carries
no field saying what its holder may do: whoever presents it is the one entitled.
A token that merely *claimed* a property would be worse than a right that is
kept honestly, and the one right there is does not live in a string that can be
handed over.

Nothing here looks anything up. Which token exists, what it belongs to and
whether it has been revoked is the business of the holdings; this module answers
the two questions that come before that — is this the shape of a token at all,
and are these two the same one.
"""

from __future__ import annotations

import hmac

from simple_a2a.core.ids import is_id, new_id

BEARER = "Bearer"


def new_token() -> str:
    """A fresh token. One identifier space, so: an identifier."""
    return new_id()


def is_token(value: object) -> bool:
    """Whether this has the shape of a token."""
    return is_id(value)


def same_token(presented: str, stored: str) -> bool:
    """Compare in constant time.

    `==` on secrets leaks how much of a guess was right through how long the
    comparison took. The leak is small and the fix is one function, so there is
    no interesting trade-off to weigh here.
    """
    return hmac.compare_digest(presented, stored)


def from_authorization(header: str | None) -> str | None:
    """Pull the token out of an `Authorization` header value.

    A string operation, not an HTTP one: what arrives here is a value, and the
    surfaces are the only place that knows a request exists. It lives down here
    so that three surfaces do not each write their own parser and disagree about
    whether the scheme is case-sensitive — it is not, says the HTTP
    specification, and a service that insisted otherwise would reject a correct
    caller.
    """
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != BEARER.lower():
        return None
    candidate = parts[1].strip()
    return candidate or None
