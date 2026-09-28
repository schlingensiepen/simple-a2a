"""What the observation surface says when it says no.

`kein-token` here is an **action and not an address**, and that is the one thing
about this surface that has to be said carefully: only the operator issues an
observer token, and there is no address here — or anywhere a reader of this text can
reach — where one can be had. Pointing at one would be pointing at something they
cannot walk to.

Nothing here names another surface. That an administration exists is not inferable
from these texts; what they say is that somebody set this installation up and that
person hands out the tokens.
"""

from __future__ import annotations

from simple_a2a.describe.rejections import Type
from simple_a2a.describe.teaching import BEHIND_A_TOKEN, Register

NO_TOKEN = (
    "Your token goes in an Authorization header, as `Bearer <token>`. There is no address "
    "here that issues one and no way to ask for one: whoever set this installation up "
    "issues them, and you get one from them. If you have a token and it was refused, check "
    "that you are at the right installation — the same refusal comes back for a token that "
    "belongs somewhere else. GET / names the address this one answers on."
)

TOKEN_REVOKED = (
    "That token is known here and has been revoked. Ask whoever set this installation up "
    "for a new one; they may issue another whenever they like, and several may exist at the "
    "same time."
)

WRONG_TOKEN = (
    "That is a valid token of another kind. This surface takes an observer's token, which "
    "belongs to one installation and reads everything in it."
)

INTERNAL = (
    "Something went wrong on our side. Nothing here changes anything, so asking again is "
    "always safe."
)

WINDOW_TOO_LARGE = (
    "limit may be at most 100. Asking for more is refused rather than quietly shortened, "
    "because a shortened answer looks like the end of the list."
)

WINDOW_INVALID = (
    "offset and limit are whole numbers, not negative. offset counts from 0, limit defaults to 25."
)

UNKNOWN_TEAM = (
    "No team of that name exists here. GET /teams lists them, and each entry points at its "
    "own traffic."
)

UNKNOWN_IDENTIFIER = (
    "No message or file is known under that identifier. It may be unknown or from another "
    "installation — both answer the same, because telling you which would make an "
    "identifier a way of asking about other people's holdings. Identifiers are 43 "
    "characters; check you copied it whole. You find the ones that exist through a team's "
    "traffic."
)


def _op(register: Register, operation_id: str, *specific: Type) -> None:
    register.operation(operation_id, refuses={*BEHIND_A_TOKEN, *specific})
    register.teach(operation_id, Type.NO_TOKEN, NO_TOKEN)
    register.teach(operation_id, Type.TOKEN_REVOKED, TOKEN_REVOKED)
    register.teach(operation_id, Type.WRONG_TOKEN, WRONG_TOKEN)
    register.teach(operation_id, Type.INTERNAL, INTERNAL)


def build() -> Register:
    register = Register("observe")

    _op(register, "GET /teams", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("GET /teams", Type.TOO_LARGE, WINDOW_TOO_LARGE)
    register.teach("GET /teams", Type.INVALID_INPUT, WINDOW_INVALID)

    for address in ("GET /teams/{team}", "GET /teams/{team}/purpose"):
        _op(register, address, Type.UNKNOWN_NAME)
        register.teach(address, Type.UNKNOWN_NAME, UNKNOWN_TEAM)

    _op(register, "GET /teams/{team}/peers", Type.UNKNOWN_NAME, Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("GET /teams/{team}/peers", Type.UNKNOWN_NAME, UNKNOWN_TEAM)
    register.teach("GET /teams/{team}/peers", Type.TOO_LARGE, WINDOW_TOO_LARGE)
    register.teach("GET /teams/{team}/peers", Type.INVALID_INPUT, WINDOW_INVALID)

    for address in (
        "GET /teams/{team}/peers/{name}",
        "GET /teams/{team}/peers/{name}/mission",
        "GET /teams/{team}/peers/{name}/self",
    ):
        _op(register, address, Type.UNKNOWN_NAME)
        register.teach(
            address,
            Type.UNKNOWN_NAME,
            "Either the team or the member is unknown. GET /teams lists the teams, and a "
            "team's peers list its members — the ones whose token was revoked included, "
            "because their messages are still there and somebody has to be able to look up "
            "who that was.",
        )

    _op(register, "GET /services", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("GET /services", Type.TOO_LARGE, WINDOW_TOO_LARGE)
    register.teach("GET /services", Type.INVALID_INPUT, WINDOW_INVALID)

    for address in ("GET /services/{name}", "GET /services/{name}/self"):
        _op(register, address, Type.UNKNOWN_NAME)
        register.teach(
            address,
            Type.UNKNOWN_NAME,
            "No central service of that name exists here. GET /services lists them.",
        )

    _op(
        register,
        "GET /teams/{team}/traffic",
        Type.UNKNOWN_NAME,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach(
        "GET /teams/{team}/traffic",
        Type.UNKNOWN_NAME,
        "Either the team is unknown, or a name you filtered by is not in it. GET /teams "
        "lists the teams; a team's peers and the registry list the names that can appear "
        "here. A filter always takes a kind **and** a name together — `peer` for somebody in "
        "the team, `service` for a central service — because inside one team the other side "
        "can be either, and the kind says which.",
    )
    register.teach("GET /teams/{team}/traffic", Type.TOO_LARGE, WINDOW_TOO_LARGE)
    register.teach(
        "GET /teams/{team}/traffic",
        Type.INVALID_INPUT,
        "A filter takes a kind and a name together: sender_kind with sender_name, "
        "recipient_kind with recipient_name. A kind is `peer` or `service` — never `alias`, "
        "because you are shown the real participant. `from` and `to` are timestamps like "
        "2026-09-28T09:12:44.081Z, in UTC with milliseconds, and both ends are included.",
    )

    for address in (
        "GET /messages/{message_id}",
        "GET /messages/{message_id}/subject",
        "GET /messages/{message_id}/body",
    ):
        _op(register, address, Type.UNKNOWN_IDENTIFIER)
        register.teach(address, Type.UNKNOWN_IDENTIFIER, UNKNOWN_IDENTIFIER)

    _op(register, "GET /files/{file_id}/{file_name}", Type.UNKNOWN_IDENTIFIER, Type.INVALID_INPUT)
    register.teach("GET /files/{file_id}/{file_name}", Type.UNKNOWN_IDENTIFIER, UNKNOWN_IDENTIFIER)
    register.teach(
        "GET /files/{file_id}/{file_name}",
        Type.INVALID_INPUT,
        "The name in the address carries no control characters and no directory parts. It is "
        "the name the file is saved under and it is yours to choose — a browser will use it, "
        "and the media type is derived from its extension.",
    )

    register.operation("GET /guide/{part}", refuses={Type.UNKNOWN_NAME})
    register.teach(
        "GET /guide/{part}",
        Type.UNKNOWN_NAME,
        "There is no guide part of that name. GET / lists every part there is, each with one "
        "sentence saying what it covers.",
    )

    return register
