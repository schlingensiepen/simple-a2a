"""What this surface says when it says no, operation by operation.

The catalogue gives the type; this gives the sentence. Four of the thirteen say the
same thing at every operation of this surface, because the answer really is the
same — where the administration secret goes, and what to do about a token of the
wrong kind. They are registered from one place so that they cannot go missing at
one operation, and any operation may still say something of its own.

The rest differ per operation, and that is the rule rather than an exception:
`unknown-name` at "create a team" is about the realm in the path, and at
"revoke a member's token" it is about either the team or the member. Telling a
caller which listing shows the names that would have worked is the whole job.

**Every way named here has to be walkable from this surface.** A text that points
at something the operator cannot do costs them an attempt before they find out.
"""

from __future__ import annotations

from simple_a2a.describe.rejections import Type
from simple_a2a.describe.teaching import BEHIND_A_TOKEN, Register

#: Where an operator gets the secret, said once. The three ways back are in the
#: guide; this names the shortest one and where to read the rest.
NO_TOKEN = (
    "The administration secret goes in an Authorization header, as `Bearer <secret>`. "
    "If you have not got it: it was written to the log exactly once, the first time this "
    "installation started, and it is kept in a file in the data directory. If neither is "
    "reachable, set SIMPLE_A2A_ADMIN_SECRET to the value `new` and restart to have another "
    "made, then remove that value again. The guide at /guide/first-access says it in full."
)

TOKEN_REVOKED = (
    "That secret is known here and has been revoked. The administration secret itself is "
    "never revoked, so what you presented is a participant's or an observer's token, and it "
    "no longer works anywhere. The administration secret is the one this surface takes."
)

WRONG_TOKEN = (
    "That is a valid secret of another kind. This surface takes the administration secret, "
    "the one this installation generated or was given on start."
)

INTERNAL = (
    "Something went wrong on our side, and nothing was written that you can see. Send the "
    "same request again."
)


def common(register: Register, operation_id: str) -> None:
    """The four that read the same at every operation of this surface."""
    register.teach(operation_id, Type.NO_TOKEN, NO_TOKEN)
    register.teach(operation_id, Type.TOKEN_REVOKED, TOKEN_REVOKED)
    register.teach(operation_id, Type.WRONG_TOKEN, WRONG_TOKEN)
    register.teach(operation_id, Type.INTERNAL, INTERNAL)


def _op(register: Register, operation_id: str, *specific: Type) -> None:
    register.operation(operation_id, refuses={*BEHIND_A_TOKEN, *specific})
    common(register, operation_id)


def build() -> Register:
    """The register of this surface: every operation and every text it can need."""
    register = Register("admin")

    # -- realms ------------------------------------------------------------

    _op(register, "POST /realms", Type.NAME_TAKEN, Type.INVALID_INPUT)
    register.teach(
        "POST /realms",
        Type.NAME_TAKEN,
        "A realm of that name already exists, compared without regard to case. Names stay "
        "taken here, so pick another. GET /realms lists the ones there are.",
    )
    register.teach(
        "POST /realms",
        Type.INVALID_INPUT,
        "realm_name has to be 1 to 64 characters of letters, digits, underscore, hyphen and "
        "spaces, with no space at either end and no double space. Those are refused rather "
        "than tidied up, so that the name you sent is the name you get. Example: household",
    )

    _op(register, "GET /realms", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach(
        "GET /realms",
        Type.TOO_LARGE,
        "limit may be at most 100. Asking for more is refused rather than quietly shortened, "
        "which would look like the end of the list.",
    )
    register.teach(
        "GET /realms",
        Type.INVALID_INPUT,
        "offset and limit are whole numbers, not negative. offset counts from 0, limit "
        "defaults to 25.",
    )

    # -- teams -------------------------------------------------------------

    _op(
        register,
        "POST /realms/{realm}/teams",
        Type.UNKNOWN_NAME,
        Type.NAME_TAKEN,
        Type.INVALID_INPUT,
        Type.TOO_LARGE,
    )
    register.teach(
        "POST /realms/{realm}/teams",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them. Create the realm first: "
        "POST /realms takes nothing but a name.",
    )
    register.teach(
        "POST /realms/{realm}/teams",
        Type.NAME_TAKEN,
        "A team of that name already exists in this realm. Team names are unique per realm "
        "and stay taken. GET /realms/{realm}/teams lists them.",
    )
    register.teach(
        "POST /realms/{realm}/teams",
        Type.INVALID_INPUT,
        "team_name has to be 1 to 64 characters of letters, digits, underscore, hyphen and "
        "spaces, with no space at either end and no double space. team_purpose is text and "
        "may be left out: an empty team is idle, not broken.",
    )
    register.teach(
        "POST /realms/{realm}/teams",
        Type.TOO_LARGE,
        "team_purpose may be up to 8192 characters. This surface takes texts inline only, so "
        "shorten it here; the participant surface can point at a stored file instead.",
    )

    _op(
        register, "GET /realms/{realm}/teams", Type.UNKNOWN_NAME, Type.TOO_LARGE, Type.INVALID_INPUT
    )
    register.teach(
        "GET /realms/{realm}/teams",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them.",
    )
    register.teach(
        "GET /realms/{realm}/teams",
        Type.TOO_LARGE,
        "limit may be at most 100.",
    )
    register.teach(
        "GET /realms/{realm}/teams",
        Type.INVALID_INPUT,
        "offset and limit are whole numbers, not negative.",
    )

    _op(
        register,
        "GET /realms/{realm}/teams/{team}/members",
        Type.UNKNOWN_NAME,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach(
        "GET /realms/{realm}/teams/{team}/members",
        Type.UNKNOWN_NAME,
        "Either the realm or the team is unknown. GET /realms lists the realms, "
        "GET /realms/{realm}/teams the teams of one.",
    )
    register.teach(
        "GET /realms/{realm}/teams/{team}/members", Type.TOO_LARGE, "limit may be at most 100."
    )
    register.teach(
        "GET /realms/{realm}/teams/{team}/members",
        Type.INVALID_INPUT,
        "offset and limit are whole numbers, not negative.",
    )

    # -- the registry ------------------------------------------------------

    _op(
        register,
        "GET /realms/{realm}/services",
        Type.UNKNOWN_NAME,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach(
        "GET /realms/{realm}/services",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them.",
    )
    register.teach("GET /realms/{realm}/services", Type.TOO_LARGE, "limit may be at most 100.")
    register.teach(
        "GET /realms/{realm}/services",
        Type.INVALID_INPUT,
        "offset and limit are whole numbers, not negative.",
    )

    # -- invitations -------------------------------------------------------

    _op(
        register,
        "POST /realms/{realm}/teams/{team}/invitations",
        Type.UNKNOWN_NAME,
        Type.NAME_TAKEN,
        Type.INVALID_INPUT,
        Type.TOO_LARGE,
    )
    register.teach(
        "POST /realms/{realm}/teams/{team}/invitations",
        Type.UNKNOWN_NAME,
        "Either the realm or the team is unknown. GET /realms lists the realms, "
        "GET /realms/{realm}/teams the teams of one. A team has to exist before somebody can "
        "be invited into it.",
    )
    register.teach(
        "POST /realms/{realm}/teams/{team}/invitations",
        Type.NAME_TAKEN,
        "Either member_name is already taken in this team, or display_name is already taken "
        "among the invitations of this realm. Both stay taken for good, because nothing here "
        "is deleted: whoever lost a token comes back under a **new** name. "
        "GET /realms/{realm}/teams/{team}/members shows the names in use, "
        "GET /realms/{realm}/invitations the handles.",
    )
    register.teach(
        "POST /realms/{realm}/teams/{team}/invitations",
        Type.INVALID_INPUT,
        "member_name and display_name both have to be 1 to 64 characters of letters, digits, "
        "underscore, hyphen and spaces, with no space at either end and no double space. "
        "member_name is who the person will be; display_name is how you refer to the "
        "invitation afterwards.",
    )
    register.teach(
        "POST /realms/{realm}/teams/{team}/invitations",
        Type.TOO_LARGE,
        "member_mission may be up to 8192 characters, inline on this surface.",
    )

    _op(
        register,
        "GET /realms/{realm}/invitations",
        Type.UNKNOWN_NAME,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach(
        "GET /realms/{realm}/invitations",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them.",
    )
    register.teach("GET /realms/{realm}/invitations", Type.TOO_LARGE, "limit may be at most 100.")
    register.teach(
        "GET /realms/{realm}/invitations",
        Type.INVALID_INPUT,
        "offset and limit are whole numbers, not negative.",
    )

    _op(register, "DELETE /realms/{realm}/invitations/{display_name}", Type.UNKNOWN_NAME)
    register.teach(
        "DELETE /realms/{realm}/invitations/{display_name}",
        Type.UNKNOWN_NAME,
        "Either the realm is unknown, or no invitation of this realm has that handle. "
        "GET /realms/{realm}/invitations lists them, the used-up and revoked ones included — "
        "a handle is a name, not the secret, and the secret is never an address here.",
    )

    # -- revocations -------------------------------------------------------

    _op(register, "DELETE /realms/{realm}/teams/{team}/members/{name}/token", Type.UNKNOWN_NAME)
    register.teach(
        "DELETE /realms/{realm}/teams/{team}/members/{name}/token",
        Type.UNKNOWN_NAME,
        "The realm, the team or the member is unknown. "
        "GET /realms/{realm}/teams/{team}/members lists the identities of one team, revoked "
        "ones included. Revoking one that is already revoked is allowed and tells you when it "
        "first happened.",
    )

    _op(register, "DELETE /realms/{realm}/services/{name}/token", Type.UNKNOWN_NAME)
    register.teach(
        "DELETE /realms/{realm}/services/{name}/token",
        Type.UNKNOWN_NAME,
        "The realm or the central service is unknown. GET /realms/{realm}/services lists the "
        "registry of one realm.",
    )

    _op(
        register,
        "DELETE /realms/{realm}/teams/{team}/members/{name}/realmmaster",
        Type.UNKNOWN_NAME,
    )
    register.teach(
        "DELETE /realms/{realm}/teams/{team}/members/{name}/realmmaster",
        Type.UNKNOWN_NAME,
        "The realm, the team or the member is unknown. "
        "GET /realms/{realm}/teams/{team}/members shows who carries the right. Taking it away "
        "leaves the token valid and the identity in its team.",
    )

    # -- observer tokens ---------------------------------------------------

    _op(
        register,
        "POST /realms/{realm}/observer-tokens",
        Type.UNKNOWN_NAME,
        Type.NAME_TAKEN,
        Type.INVALID_INPUT,
    )
    register.teach(
        "POST /realms/{realm}/observer-tokens",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them. An observer token belongs to "
        "one realm, so the realm comes first.",
    )
    register.teach(
        "POST /realms/{realm}/observer-tokens",
        Type.NAME_TAKEN,
        "An observer token of this realm already has that handle, and handles stay taken. "
        "GET /realms/{realm}/observer-tokens lists them. Handles are unique per kind, so this "
        "one does not clash with an invitation of the same name.",
    )
    register.teach(
        "POST /realms/{realm}/observer-tokens",
        Type.INVALID_INPUT,
        "display_name has to be 1 to 64 characters of letters, digits, underscore, hyphen and "
        "spaces, with no space at either end and no double space. Example: the reading eye",
    )

    _op(
        register,
        "GET /realms/{realm}/observer-tokens",
        Type.UNKNOWN_NAME,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach(
        "GET /realms/{realm}/observer-tokens",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them.",
    )
    register.teach(
        "GET /realms/{realm}/observer-tokens", Type.TOO_LARGE, "limit may be at most 100."
    )
    register.teach(
        "GET /realms/{realm}/observer-tokens",
        Type.INVALID_INPUT,
        "offset and limit are whole numbers, not negative.",
    )

    _op(register, "DELETE /realms/{realm}/observer-tokens/{display_name}", Type.UNKNOWN_NAME)
    register.teach(
        "DELETE /realms/{realm}/observer-tokens/{display_name}",
        Type.UNKNOWN_NAME,
        "Either the realm is unknown, or no observer token of this realm has that handle. "
        "GET /realms/{realm}/observer-tokens lists them.",
    )

    # -- the two notes -----------------------------------------------------

    _op(register, "GET /setup-note")
    _op(register, "PUT /setup-note", Type.TOO_LARGE, Type.INVALID_INPUT)
    register.teach(
        "PUT /setup-note",
        Type.TOO_LARGE,
        "The note may be up to 8192 characters. It is a place to write down what you did, not "
        "a place to keep documents.",
    )
    register.teach(
        "PUT /setup-note",
        Type.INVALID_INPUT,
        "The request body is the note itself, as UTF-8 text; Markdown is a good choice and "
        "nothing reads it either way. It was not valid UTF-8.",
    )

    _op(register, "GET /realms/{realm}/setup-note", Type.UNKNOWN_NAME)
    register.teach(
        "GET /realms/{realm}/setup-note",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them.",
    )

    _op(
        register,
        "PUT /realms/{realm}/setup-note",
        Type.UNKNOWN_NAME,
        Type.TOO_LARGE,
        Type.INVALID_INPUT,
    )
    register.teach(
        "PUT /realms/{realm}/setup-note",
        Type.UNKNOWN_NAME,
        "No realm of that name exists. GET /realms lists them.",
    )
    register.teach(
        "PUT /realms/{realm}/setup-note",
        Type.TOO_LARGE,
        "The note may be up to 8192 characters.",
    )
    register.teach(
        "PUT /realms/{realm}/setup-note",
        Type.INVALID_INPUT,
        "The request body is the note itself, as UTF-8 text. It was not valid UTF-8.",
    )

    # -- the guide part that does not exist here ---------------------------

    register.operation("GET /guide/{part}", refuses={Type.UNKNOWN_NAME})
    register.teach(
        "GET /guide/{part}",
        Type.UNKNOWN_NAME,
        "This surface has no guide part of that name. GET / lists every part it has, each "
        "with one sentence saying what it covers.",
    )

    return register
