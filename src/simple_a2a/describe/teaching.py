"""The register of teaching texts: one per operation and type, and none missing.

The catalogue says what kind of no it is; this says what *that* no teaches at
*that* operation. Two entries of the same type read differently on purpose —
"a realm master in your own team can appoint" where somebody is appointing, and
"you can ask a realm master for one" where somebody wants a service invitation.
Two actions, one type.

**A missing text is an error, not a blank.** There is no default, and asking for
one that was never written raises. The alternative is a rejection that says the
type and nothing a reader can act on, which is precisely the medium-break this
service exists without: a generic code plus "see the documentation" sends an
agent guessing instead of reading.

`missing_for` turns that into something a test can run over the whole surface
before anybody meets it — the texts are part of the description gate, not a thing
to be noticed in production.
"""

from __future__ import annotations

from dataclasses import dataclass

from simple_a2a.describe.rejections import Rejection, Type, detail_of, type_of
from simple_a2a.domain import refusals


@dataclass(frozen=True)
class Operation:
    """One operation of one surface, as the teaching register knows it.

    `id` is what the register is keyed by — the address and verb, which is what a
    reader sees. `can_refuse` is the set of types this operation is documented to
    produce, and it is the list every text is checked against.
    """

    id: str
    surface: str
    can_refuse: frozenset[Type]


class Register:
    """The texts of one surface, and the operations they belong to."""

    def __init__(self, surface: str) -> None:
        self.surface = surface
        self._operations: dict[str, Operation] = {}
        self._texts: dict[tuple[str, Type], str] = {}

    def operation(self, operation_id: str, *, refuses: set[Type]) -> Operation:
        made = Operation(id=operation_id, surface=self.surface, can_refuse=frozenset(refuses))
        self._operations[operation_id] = made
        return made

    def teach(self, operation_id: str, kind: Type, text: str) -> None:
        if operation_id not in self._operations:
            raise KeyError(f"{operation_id} is not an operation of {self.surface}")
        if kind not in self._operations[operation_id].can_refuse:
            # Written for a type the operation cannot produce: either the text is
            # in the wrong place or the operation's list is wrong, and both are
            # worth stopping for.
            raise KeyError(f"{operation_id} does not refuse with {kind}")
        self._texts[(operation_id, kind)] = text

    def text_for(self, operation_id: str, kind: Type) -> str:
        found = self._texts.get((operation_id, kind))
        if found is None:
            raise KeyError(f"no text for {kind} at {operation_id}")
        return found

    def rejection(self, operation_id: str, refusal: refusals.Refused) -> Rejection:
        """Turn a refusal from the operations into the answer a caller gets."""
        kind = type_of(refusal)
        return Rejection(
            type=kind, message=self.text_for(operation_id, kind), detail=detail_of(refusal)
        )

    def operations(self) -> list[Operation]:
        return list(self._operations.values())

    def missing(self) -> list[tuple[str, Type]]:
        """Every operation-and-type pair that has no text. Empty, or the build is wrong."""
        return [
            (operation.id, kind)
            for operation in self._operations.values()
            for kind in sorted(operation.can_refuse)
            if (operation.id, kind) not in self._texts
        ]


def unknown_field(path: str | None, owner: str, fields: list[str]) -> str:
    """What a field the request does not have teaches, at whatever operation.

    The one `invalid-input` text that is not written per operation, because what
    it has to say is the same everywhere and comes from the request's own shape:
    this name is not one of its fields, and these are. The operation's own text
    explains how its fields fit together, which is the wrong lesson for somebody
    who used a name the request does not have — `to` where it says `recipients` —
    and it sent them looking in the wrong place.

    `owner` is the path of the object the name was found in, empty for the
    request itself, and `fields` are that object's fields as the model has them.
    `path` is `None` for a name that is not repeated back — one that is not a short
    plain name — so the sentence says what was wrong without quoting it.
    """
    listed = ", ".join(f"`{name}`" for name in fields)
    if path is None:
        found = f"`{owner}`" if owner else "this request"
        lead = (
            f"A name in {found} is not a field of this request. It is not repeated "
            "here, since it is not a short plain name of letters, digits, `_` and `-`."
        )
        if owner:
            return f"{lead} The fields of `{owner}` are {listed}."
        return f"{lead} Its fields are {listed}."
    if owner:
        return f"`{path}` is not a field of this request. The fields of `{owner}` are {listed}."
    return f"`{path}` is not a field of this request. Its fields are {listed}."


#: The types every operation behind a token can produce, whatever else it does.
#: Listed once rather than repeated per operation, because repeating them is how
#: one of them goes missing somewhere.
#:
#: `wrong-token` is in here for every surface, including the administration:
#: a participant who presents their own token there is valid and of the wrong
#: kind, and that is a different answer from an unknown one. So is
#: `token-revoked`, because a revoked participant token can be presented
#: anywhere.
BEHIND_A_TOKEN = {Type.NO_TOKEN, Type.TOKEN_REVOKED, Type.WRONG_TOKEN, Type.INTERNAL}

#: And the two that belong to the address rather than to the operation. They are
#: answered before any operation is reached, so they are registered against the
#: surface itself.
OF_THE_ADDRESS = {Type.UNKNOWN_ADDRESS, Type.WRONG_VERB}
