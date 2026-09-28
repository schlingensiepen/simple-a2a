"""Why an operation cannot be carried out, said in the words of the subject.

These are not the rejection types a caller sees. The catalogue of types, their
statuses and the teaching texts live one floor up, because the text belongs to
the *operation*: the same type says different things at different operations, and
that is the rule rather than an exception. What lives here is what went wrong, in
terms of teams and names and vouchers, plus the facts a text will need to be
useful — the name that collided, the limit that was exceeded, the field that was
wrong.

Raised rather than returned. An operation that fails has nothing to hand back,
and a caller who forgets to look at a returned status carries on with a value
that was never valid.
"""

from __future__ import annotations


class Refused(Exception):
    """Base of everything that stops an operation."""


class NoToken(Refused):
    """Nothing presented, or something that cannot be resolved to anything.

    Unreadable and unknown are the same answer on purpose, and so is a token
    presented to an instance whose holdings are empty: where there is nothing, no
    token can be right.
    """


class TokenRevoked(Refused):
    """Known, and revoked. A different answer from unknown, and it has a way on."""


class WrongToken(Refused):
    """Valid, and the wrong kind for this operation.

    Carries the kind that *is* needed. Never the other surface — a caller learns
    what they need, not what exists elsewhere.
    """

    def __init__(self, needed: str) -> None:
        super().__init__(f"this operation needs a {needed} token")
        self.needed = needed


class NotRealmMaster(Refused):
    """The one right that sits on an identity is missing."""


class UnknownName(Refused):
    """A name that nothing answers to in the namespace that applies here."""

    def __init__(self, name: str, *, namespace: str) -> None:
        super().__init__(f"no {namespace} is called {name!r}")
        self.name = name
        self.namespace = namespace


class UnknownIdentifier(Refused):
    """A message, file, invitation or alias that is unknown — or in another realm.

    Deliberately one answer for both. Telling a caller that something exists
    elsewhere would make an identifier a way of asking about other people's
    holdings.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(f"no {kind} is known under that identifier")
        self.kind = kind


class InvitationUsed(Refused):
    """Already redeemed. Separate from unknown, because it has a way forward.

    "Already redeemed, ask for a new one" gets the rightful holder somewhere;
    "not found" leaves them stuck.
    """


class NameTaken(Refused):
    """A name collision. Names stay taken, revoked or not."""

    def __init__(self, name: str, *, namespace: str) -> None:
        super().__init__(f"the {namespace} name {name!r} is taken")
        self.name = name
        self.namespace = namespace


class TooLarge(Refused):
    """A limit was exceeded. Carries the limit, because the text names it."""

    def __init__(self, field: str, *, limit: int, actual: int, unit: str) -> None:
        super().__init__(f"{field} is {actual} {unit}, the limit is {limit}")
        self.field = field
        self.limit = limit
        self.actual = actual
        self.unit = unit


class InvalidInput(Refused):
    """A field is missing or has the wrong shape.

    Carries the field and, where there is one, a short reason — the text has to
    name the field, the right shape and an example, and it cannot do that from a
    bare failure.
    """

    def __init__(self, field: str, *, reason: str = "") -> None:
        super().__init__(f"{field} is not usable" + (f": {reason}" if reason else ""))
        self.field = field
        self.reason = reason


#: The one warning there is: a success that probably did not do what the caller
#: wanted. Kept here rather than with the refusals' catalogue because it is
#: produced by an operation, and closed for the same reason the types are.
NO_RECIPIENT = "no-recipient"
