"""How the service says no: thirteen types, and a text that belongs to the operation.

The catalogue is **closed**. There is no rejection outside this list, and the
status follows from the type rather than being chosen — so a caller can learn the
thirteen answers once and be done, and nobody can quietly add a fourteenth
because a new case felt special.

**The type is not the message.** Each type says *what kind* of no it is; what a
particular no *teaches* belongs to the operation that gave it. The same type says
different things in different places, and that is the rule rather than an
exception: `not-realm-master` tells whoever is appointing that a realm master in
their own team can do it, and tells whoever wants a service invitation that they
can *ask* one. Two actions, one type.

**Every rejection names a way forward that this surface can walk.** Not a
plausible-sounding one — a walkable one. A text that points at something the
reader cannot do is worse than no text, because it costs them an attempt before
they find out.

**Two types are deliberately blunt.** `unknown-identifier` covers unknown, used
up, revoked and *in another realm*, because a reach across a realm boundary has
to look exactly like a reach for something that does not exist — otherwise an
identifier becomes a way of asking about other people's holdings. There the
vagueness is the promise.

**And one is deliberately separated** although it is formally just an unusable
identifier: `invitation-used`. An invitation is usually held by its rightful
recipient, and "already redeemed, ask for a new one" gets them somewhere where
"not found" leaves them stuck. Nothing is given away, because invitations cannot
be guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from simple_a2a.domain import refusals


class Type(StrEnum):
    """The thirteen, and there is no fourteenth."""

    UNKNOWN_ADDRESS = "unknown-address"
    WRONG_VERB = "wrong-verb"
    NO_TOKEN = "no-token"
    TOKEN_REVOKED = "token-revoked"
    WRONG_TOKEN = "wrong-token"
    NOT_REALM_MASTER = "not-realm-master"
    UNKNOWN_NAME = "unknown-name"
    UNKNOWN_IDENTIFIER = "unknown-identifier"
    INVITATION_USED = "invitation-used"
    NAME_TAKEN = "name-taken"
    INVALID_INPUT = "invalid-input"
    TOO_LARGE = "too-large"
    INTERNAL = "internal-error"


#: The status of each type. Derived, never chosen at the call site: a type that
#: answered 404 in one place and 409 in another would make the catalogue useless
#: for anybody writing a client.
STATUS: dict[Type, int] = {
    Type.UNKNOWN_ADDRESS: 404,
    Type.WRONG_VERB: 405,
    Type.NO_TOKEN: 401,
    Type.TOKEN_REVOKED: 401,
    Type.WRONG_TOKEN: 403,
    Type.NOT_REALM_MASTER: 403,
    Type.UNKNOWN_NAME: 404,
    Type.UNKNOWN_IDENTIFIER: 404,
    Type.INVITATION_USED: 409,
    Type.NAME_TAKEN: 409,
    Type.INVALID_INPUT: 400,
    Type.TOO_LARGE: 413,
    Type.INTERNAL: 500,
}

#: Success is 200 everywhere, creating included. Returning the created thing in
#: the body rather than an address to fetch it from makes 201 pointless, and one
#: success status is one rule fewer for whoever builds a tool.
SUCCESS = 200

#: Which refusal from the operations becomes which type. The mapping lives here
#: because this is where the catalogue lives; the operations speak of teams and
#: names and know nothing of it.
OF_REFUSAL: dict[type[refusals.Refused], Type] = {
    refusals.NoToken: Type.NO_TOKEN,
    refusals.TokenRevoked: Type.TOKEN_REVOKED,
    refusals.WrongToken: Type.WRONG_TOKEN,
    refusals.NotRealmMaster: Type.NOT_REALM_MASTER,
    refusals.UnknownName: Type.UNKNOWN_NAME,
    refusals.UnknownIdentifier: Type.UNKNOWN_IDENTIFIER,
    refusals.InvitationUsed: Type.INVITATION_USED,
    refusals.NameTaken: Type.NAME_TAKEN,
    refusals.InvalidInput: Type.INVALID_INPUT,
    refusals.TooLarge: Type.TOO_LARGE,
}


@dataclass(frozen=True)
class Rejection:
    """One no, ready to be answered with.

    `message` is the teaching text, written for the operation this came from.
    `detail` carries the facts a reader needs to act — the field that was wrong,
    the limit that was exceeded, the name that collided — as named fields rather
    than as prose to be parsed back out.
    """

    type: Type
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> int:
        return STATUS[self.type]

    def body(self) -> dict[str, Any]:
        """The wire shape: the type, the text, and the facts.

        Data, so `application/json` like every other data answer — not a separate
        error media type, which would be a second convention for a caller to
        learn about the same service.
        """
        return {"type": str(self.type), "message": self.message, **self.detail}


def type_of(refusal: refusals.Refused) -> Type:
    """The catalogue type for a refusal from the operations.

    Exact class rather than `isinstance`, so a new refusal has to be mapped
    deliberately instead of silently inheriting somebody else's type.
    """
    found = OF_REFUSAL.get(type(refusal))
    if found is None:
        raise KeyError(f"{type(refusal).__name__} has no type in the catalogue")
    return found


def detail_of(refusal: refusals.Refused) -> dict[str, Any]:
    """The facts a text will want to name, pulled off the refusal."""
    if isinstance(refusal, refusals.TooLarge):
        return {
            "field": refusal.field,
            "limit": refusal.limit,
            "actual": refusal.actual,
            "unit": refusal.unit,
        }
    if isinstance(refusal, refusals.InvalidInput):
        return {"field": refusal.field}
    if isinstance(refusal, refusals.NameTaken | refusals.UnknownName):
        return {"name": refusal.name}
    if isinstance(refusal, refusals.WrongToken):
        return {"needed": refusal.needed}
    return {}
