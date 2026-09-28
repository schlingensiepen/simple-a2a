"""What the participant surface says when it says no, operation by operation.

Two of the per-operation differences here are the reason the rule exists at all.

**`falsches-token` names a way the caller can walk.** A central service that tries a
team operation is not told "get an agent-in-team token" — it cannot get one. It is
told what it *can* do. And a team member at the alias operation is not told to get a
service token; they are told to send to a name and set `in_reply_to`, which is the
same act by the means they have.

**`kein-realmmaster` says two different things.** Appointing: a realm master in your
own team can do it. Obtaining a service invitation: you can **ask** one. Two actions,
one type.

Nothing here makes another surface recognisable. There is no hint that an
administration or an observation exists — not in a path, not in a suggestion, not in
a difference of wording somebody could infer one from.
"""

from __future__ import annotations

from simple_a2a.describe.rejections import Type
from simple_a2a.describe.teaching import BEHIND_A_TOKEN, Register

NO_TOKEN = (
    "Your token goes in an Authorization header, as `Bearer <token>`. If you have not got "
    "one, whoever set this up gives you an invitation and the base address together, and "
    "you exchange the invitation once at POST /invitations/redeem. If you do have one and "
    "it was refused: check that you are at the right installation — the same refusal comes "
    "back for a token that belongs somewhere else, and nothing here will tell you that is "
    "what happened. GET / names the address this installation answers on."
)

TOKEN_REVOKED = (
    "That token is known here and has been revoked. It will not come back, and there is no "
    "replacement for it: ask to be invited again **under a new name** and introduce "
    "yourself to the others, because your old name stays taken."
)

INTERNAL = (
    "Something went wrong on our side, and nothing was stored that you can see. Send the "
    "same request again: sending is fire-and-forget here, so a missing answer means send "
    "again."
)

#: What a central service is told at an operation of a team. Its own addresses, not
#: an instruction it cannot follow.
NOT_FOR_A_SERVICE = (
    "This operation belongs to somebody in a team, and you are a central service: you have "
    "no team and no addressees of your own. What you have is GET /me and PUT /me/self, your "
    "inbox and outbox, fetching messages and files, depositing files, and answering what you "
    "received by sending to the alias that came with it."
)

#: And what a team member is told at the alias operation. The same act, their means.
NOT_FOR_A_PEER = (
    "Sending to an alias is how a central service answers what it received, and you are in a "
    "team. You answer the ordinary way: send to the name with POST /peers/messages or "
    "POST /services/messages and set `in_reply_to` to the message you are answering. Two "
    "ways of doing one thing would be one too many."
)

WINDOW_TOO_LARGE = (
    "limit may be at most 100. Asking for more is refused rather than quietly shortened, "
    "because a shortened answer looks like the end of the list."
)

WINDOW_INVALID = (
    "offset and limit are whole numbers, not negative. offset counts from 0, limit defaults to 25."
)

UNKNOWN_MESSAGE = (
    "No message, file, invitation or alias is known under that identifier. It may be "
    "unknown, used up, revoked, or from somewhere this token cannot reach — all four "
    "answer the same, because telling you which would make an identifier a way of asking "
    "about other people's messages. Check you copied it whole; identifiers are 43 "
    "characters."
)


def _op(register: Register, operation_id: str, *specific: Type, needs_token: bool = True) -> None:
    common = set(BEHIND_A_TOKEN) if needs_token else {Type.INTERNAL}
    register.operation(operation_id, refuses={*common, *specific})
    register.teach(operation_id, Type.INTERNAL, INTERNAL)
    if needs_token:
        register.teach(operation_id, Type.NO_TOKEN, NO_TOKEN)
        register.teach(operation_id, Type.TOKEN_REVOKED, TOKEN_REVOKED)


def build() -> Register:
    register = Register("messaging")

    # -- orientation -------------------------------------------------------

    for address in ("GET /team", "GET /team/purpose"):
        _op(register, address)
        register.teach(address, Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)

    _op(register, "GET /me")
    register.teach("GET /me", Type.WRONG_TOKEN, "This surface takes a participant's token.")

    _op(register, "GET /me/mission")
    register.teach(
        "GET /me/mission",
        Type.WRONG_TOKEN,
        "You are a central service, and a central service carries no mission. A mission is "
        "what somebody was invited **for**, given by whoever invited them; you registered "
        "yourself, so what you can do is your own statement. That text is at GET /me/self, "
        "and PUT /me/self replaces it.",
    )

    _op(register, "GET /me/self")
    register.teach("GET /me/self", Type.WRONG_TOKEN, "This surface takes a participant's token.")

    _op(register, "PUT /me/self", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("PUT /me/self", Type.WRONG_TOKEN, "This surface takes a participant's token.")
    register.teach(
        "PUT /me/self",
        Type.TOO_LARGE,
        "The text may be up to 8192 characters. If what you want to say is longer than that, "
        "it is probably a message rather than a description of yourself.",
    )
    register.teach(
        "PUT /me/self",
        Type.INVALID_INPUT,
        "The request body is the text itself, as UTF-8; Markdown is a good choice and nothing "
        "here reads it. It was not valid UTF-8.",
    )

    # -- the two directories ----------------------------------------------

    _op(register, "GET /peers", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("GET /peers", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach("GET /peers", Type.TOO_LARGE, WINDOW_TOO_LARGE)
    register.teach("GET /peers", Type.INVALID_INPUT, WINDOW_INVALID)

    for address in ("GET /peers/{name}", "GET /peers/{name}/mission", "GET /peers/{name}/self"):
        _op(register, address, Type.UNKNOWN_NAME)
        register.teach(address, Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
        register.teach(
            address,
            Type.UNKNOWN_NAME,
            "Nobody in your team is called that. GET /peers lists the names there are, "
            "compared without regard to case. Somebody whose token was revoked is still in "
            "that list and still readable.",
        )

    _op(register, "GET /services", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("GET /services", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach("GET /services", Type.TOO_LARGE, WINDOW_TOO_LARGE)
    register.teach("GET /services", Type.INVALID_INPUT, WINDOW_INVALID)

    for address in ("GET /services/{name}", "GET /services/{name}/self"):
        _op(register, address, Type.UNKNOWN_NAME)
        register.teach(address, Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
        register.teach(
            address,
            Type.UNKNOWN_NAME,
            "No central service of that name exists here. GET /services lists them.",
        )

    # -- sending -----------------------------------------------------------

    _op(
        register,
        "POST /peers/messages",
        Type.UNKNOWN_NAME,
        Type.UNKNOWN_IDENTIFIER,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach("POST /peers/messages", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach(
        "POST /peers/messages",
        Type.UNKNOWN_NAME,
        "One of the names in `recipients` is not in your team. GET /peers lists the names "
        "there are. Leave `recipients` out entirely to send to everybody else in the team.",
    )
    register.teach("POST /peers/messages", Type.UNKNOWN_IDENTIFIER, UNKNOWN_MESSAGE)
    register.teach(
        "POST /peers/messages",
        Type.TOO_LARGE,
        "Something is over its limit: the subject 256 characters, the body 1 MiB, the "
        "attachment list 64 entries, an attachment name 256 characters. For a body that is "
        "too long there are three ways on — attach it as a file, split it across several "
        "messages, or deposit the text with POST /files and send `body_file_id` instead.",
    )
    register.teach(
        "POST /peers/messages",
        Type.INVALID_INPUT,
        "Exactly one of `body` and `body_file_id` is filled, and each attachment entry has "
        "exactly one of `file_id` and `message_id`. `size` is never sent in: we know the "
        "bytes of a file and the total of a referenced message, and you cannot. An "
        "attachment name is not a path and carries no control characters.",
    )

    _op(
        register,
        "POST /services/messages",
        Type.UNKNOWN_NAME,
        Type.UNKNOWN_IDENTIFIER,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach("POST /services/messages", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach(
        "POST /services/messages",
        Type.UNKNOWN_NAME,
        "No central service of that name exists here. GET /services lists them. `recipient` "
        "is one name, not a list: central services are addressed one at a time.",
    )
    register.teach("POST /services/messages", Type.UNKNOWN_IDENTIFIER, UNKNOWN_MESSAGE)
    register.teach(
        "POST /services/messages",
        Type.TOO_LARGE,
        "Something is over its limit: the subject 256 characters, the body 1 MiB, the "
        "attachment list 64 entries. For a body that is too long: attach it as a file, split "
        "it across several messages, or deposit the text with POST /files and send "
        "`body_file_id`.",
    )
    register.teach(
        "POST /services/messages",
        Type.INVALID_INPUT,
        "`recipient` is one name. Exactly one of `body` and `body_file_id` is filled, and "
        "each attachment entry has exactly one of `file_id` and `message_id`. `size` is "
        "never sent in.",
    )

    _op(
        register,
        "POST /aliases/{alias}/messages",
        Type.UNKNOWN_IDENTIFIER,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach("POST /aliases/{alias}/messages", Type.WRONG_TOKEN, NOT_FOR_A_PEER)
    register.teach(
        "POST /aliases/{alias}/messages",
        Type.UNKNOWN_IDENTIFIER,
        "That alias is not one of yours. An alias comes with a message you received and "
        "belongs to that one delivery: GET /inbox shows the ones you have, in `sender_name` "
        "where a name would otherwise be. A message identifier somebody passed you is not an "
        "alias and will not work here, and there is no alias for a message you sent "
        "yourself.",
    )
    register.teach(
        "POST /aliases/{alias}/messages",
        Type.TOO_LARGE,
        "Something is over its limit: the subject 256 characters, the body 1 MiB, the "
        "attachment list 64 entries. For a body that is too long: attach it as a file, split "
        "it across several messages, or deposit the text with POST /files and send "
        "`body_file_id`.",
    )
    register.teach(
        "POST /aliases/{alias}/messages",
        Type.INVALID_INPUT,
        "There is no recipient field here: the alias in the address is the recipient, and we "
        "set `in_reply_to` for you to the message it belongs to. Exactly one of `body` and "
        "`body_file_id` is filled.",
    )

    # -- receiving ---------------------------------------------------------

    for address in ("GET /inbox", "GET /outbox"):
        _op(register, address, Type.TOO_LARGE, Type.INVALID_INPUT)
        register.teach(address, Type.WRONG_TOKEN, "This surface takes a participant's token.")
        register.teach(address, Type.TOO_LARGE, WINDOW_TOO_LARGE)
        register.teach(address, Type.INVALID_INPUT, WINDOW_INVALID)

    for address in (
        "GET /messages/{message_id}",
        "GET /messages/{message_id}/subject",
        "GET /messages/{message_id}/body",
    ):
        _op(register, address, Type.UNKNOWN_IDENTIFIER)
        register.teach(address, Type.WRONG_TOKEN, "This surface takes a participant's token.")
        register.teach(address, Type.UNKNOWN_IDENTIFIER, UNKNOWN_MESSAGE)

    # -- files -------------------------------------------------------------

    _op(register, "POST /files", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach("POST /files", Type.WRONG_TOKEN, "This surface takes a participant's token.")
    register.teach(
        "POST /files",
        Type.TOO_LARGE,
        "A file may be up to 50 MiB. If you and the other side are on the same machine, agree "
        "to read each other's directories and send a path instead: content that has been "
        "through a context window does not come back byte for byte.",
    )
    register.teach(
        "POST /files",
        Type.INVALID_INPUT,
        "The request body is the file's bytes and nothing else — no multipart form, because "
        "that would bring a second file name along and the name belongs on the envelope.",
    )

    _op(register, "GET /files/{file_id}/{file_name}", Type.UNKNOWN_IDENTIFIER, Type.INVALID_INPUT)
    register.teach(
        "GET /files/{file_id}/{file_name}",
        Type.WRONG_TOKEN,
        "This surface takes a participant's token.",
    )
    register.teach("GET /files/{file_id}/{file_name}", Type.UNKNOWN_IDENTIFIER, UNKNOWN_MESSAGE)
    register.teach(
        "GET /files/{file_id}/{file_name}",
        Type.INVALID_INPUT,
        "The name in the address carries no control characters and no directory parts. It is "
        "the name the file is saved under, and it is yours to choose: it need not match what "
        "any message called it.",
    )

    # -- inviting, founding, appointing ------------------------------------

    _op(
        register,
        "POST /invitations/peer",
        Type.NAME_TAKEN,
        Type.UNKNOWN_IDENTIFIER,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach("POST /invitations/peer", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach(
        "POST /invitations/peer",
        Type.NAME_TAKEN,
        "Either `member_name` is taken in your team or `display_name` is taken among the "
        "invitations here. Both stay taken for good, because nothing is deleted: somebody "
        "who lost a token comes back under a new name. GET /peers shows the names in use.",
    )
    register.teach("POST /invitations/peer", Type.UNKNOWN_IDENTIFIER, UNKNOWN_MESSAGE)
    register.teach(
        "POST /invitations/peer",
        Type.TOO_LARGE,
        "`member_mission` may be up to 8192 characters. Longer than that and it is probably a "
        "first message rather than a mission.",
    )
    register.teach(
        "POST /invitations/peer",
        Type.INVALID_INPUT,
        "`member_name` and `display_name` are both 1 to 64 characters of letters, digits, "
        "underscore, hyphen and spaces, with no space at either end and no double space. "
        "Exactly one of `member_mission` and `member_mission_file_id` is filled.",
    )

    _op(
        register,
        "POST /invitations/service",
        Type.NOT_REALM_MASTER,
        Type.NAME_TAKEN,
        Type.INVALID_INPUT,
    )
    register.teach("POST /invitations/service", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach(
        "POST /invitations/service",
        Type.NOT_REALM_MASTER,
        "Your token does not carry the realm master right, and only it may add a central "
        "service: a bad member costs a team, a bad central service costs everybody here. "
        "**Ask** somebody who has it — GET /peers marks who does.",
    )
    register.teach(
        "POST /invitations/service",
        Type.NAME_TAKEN,
        "Either `service_name` is taken among the central services or `display_name` is taken "
        "among the invitations. GET /services shows the service names in use.",
    )
    register.teach(
        "POST /invitations/service",
        Type.INVALID_INPUT,
        "`service_name` and `display_name` are both 1 to 64 characters of letters, digits, "
        "underscore, hyphen and spaces, with no space at either end and no double space.",
    )

    _op(
        register,
        "POST /invitations/redeem",
        Type.UNKNOWN_IDENTIFIER,
        Type.INVITATION_USED,
        Type.NAME_TAKEN,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
        needs_token=False,
    )
    register.teach(
        "POST /invitations/redeem",
        Type.UNKNOWN_IDENTIFIER,
        "That invitation is not known here. Check you copied it whole — it is 43 characters — "
        "and that you are at the installation it was issued for: the two travel together and "
        "neither half works alone. If it was revoked, ask whoever gave it to you for another.",
    )
    register.teach(
        "POST /invitations/redeem",
        Type.INVITATION_USED,
        "That invitation has already been redeemed, and an invitation is good once. Ask "
        "whoever gave it to you for a new one. If you never got a token from it, say so: it "
        "will have to be a new invitation under a new name, because the old name is taken.",
    )
    register.teach(
        "POST /invitations/redeem",
        Type.NAME_TAKEN,
        "The name this invitation was issued for has been taken since it was issued — names "
        "are checked when an invitation is made **and** when it is redeemed, because somebody "
        "can take one in between. Ask for a new invitation under a different name.",
    )
    register.teach(
        "POST /invitations/redeem",
        Type.TOO_LARGE,
        "`member_self_image` may be up to 8192 characters.",
    )
    register.teach(
        "POST /invitations/redeem",
        Type.INVALID_INPUT,
        "`invitation` is the voucher you were given, 43 characters. If you are becoming a "
        "central service, `member_self_image` comes with it and inline only: you have no "
        "token yet, so you cannot deposit a file first.",
    )

    _op(
        register,
        "POST /teams",
        Type.NAME_TAKEN,
        Type.UNKNOWN_IDENTIFIER,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach("POST /teams", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach(
        "POST /teams",
        Type.NAME_TAKEN,
        "A team of that name already exists here, and team names stay taken. Pick another.",
    )
    register.teach("POST /teams", Type.UNKNOWN_IDENTIFIER, UNKNOWN_MESSAGE)
    register.teach(
        "POST /teams",
        Type.TOO_LARGE,
        "`team_purpose` and `member_mission` may each be up to 8192 characters.",
    )
    register.teach(
        "POST /teams",
        Type.INVALID_INPUT,
        "`team_name` is 1 to 64 characters of letters, digits, underscore, hyphen and spaces, "
        "with no space at either end and no double space. Exactly one of `team_purpose` and "
        "`team_purpose_file_id` is filled, and the same for the two mission fields — you are "
        "the new team's first member, so you give yourself a mission.",
    )

    _op(register, "POST /peers/{name}/realmmaster", Type.NOT_REALM_MASTER, Type.UNKNOWN_NAME)
    register.teach("POST /peers/{name}/realmmaster", Type.WRONG_TOKEN, NOT_FOR_A_SERVICE)
    register.teach(
        "POST /peers/{name}/realmmaster",
        Type.NOT_REALM_MASTER,
        "Only a realm master can appoint another, and only in their own team. GET /peers "
        "marks who carries the right; ask one of them.",
    )
    register.teach(
        "POST /peers/{name}/realmmaster",
        Type.UNKNOWN_NAME,
        "Nobody in your team is called that. GET /peers lists the names there are. You can "
        "only appoint inside your own team, because there is nothing else you can see.",
    )

    # -- the guide part that does not exist here ---------------------------

    register.operation("GET /guide/{part}", refuses={Type.UNKNOWN_NAME})
    register.teach(
        "GET /guide/{part}",
        Type.UNKNOWN_NAME,
        "There is no guide part of that name. GET / lists every part there is, each with one "
        "sentence saying what it covers.",
    )

    return register
