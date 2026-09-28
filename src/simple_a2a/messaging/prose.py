"""The prose this surface writes, to guide rather than to inform.

Six operations answer with prose rather than data, and the difference is not
cosmetic. Data is for anywhere an identifier is produced or consumed, because
fishing an identifier out of prose is a source of mistakes. Prose is for the places
where the useful answer is a short orientation plus **where to go next** — and it
may change between versions, which is exactly why no identifier appears in it.

Every one of these branches. A listing names what there is and the address each
thing sits at; it does not inline the texts. Doubled addresses are easier to bear
than a context filled with things nobody asked for, and the reader is an agent with
a context to spend.

Addresses here are bare paths. The base address belongs to the entry alone, so a
branch written here stays right when the same service is reached under a second
host name.
"""

from __future__ import annotations

from urllib.parse import quote

from simple_a2a.describe import directories


#: Percent-encoding a name for an address, because a name may contain spaces. The
#: shared renderers do their own; this is for the texts written here.
def _quote(name: str) -> str:
    return quote(name, safe="")


def team(*, team_name: str, member_count: int, purpose_set: bool) -> str:
    """The natural first thing an arriving agent does.

    It says where it is and offers the four directions, which is more use than any
    amount of explanation: whoever has just been let in wants to know who is here.
    """
    return f"""# Your team: {team_name}

You are one identity in this team, and everything you can reach you reach with
your own token. The team has {member_count} {"member" if member_count == 1 else "members"},
you included.

- `GET /team/purpose` — what this team is for, in the words of whoever created it.
  {"" if purpose_set else "Nothing has been written there yet."}
- `GET /peers` — who else is in the team, and the address of each one's two texts.
  These are the names you can address.
- `GET /services` — the central services of this installation: things that are not
  in your team and are addressed by name from anywhere here.
- `GET /me` — your own name, your mission, and the text you keep about yourself.

To send something, read `GET /guide/sending`. It is one page and it covers all
three ways there are.
"""


def me_as_peer(*, name: str, team_name: str, is_realm_master: bool, self_image_set: bool) -> str:
    """Who the caller is, from the service's side rather than from their notes."""
    right = (
        "Your token carries the realm master right: you may obtain an invitation for a "
        "central service, and you may appoint further realm masters in this team. You "
        "cannot give the right up yourself."
        if is_realm_master
        else "Your token does not carry the realm master right. You can still invite "
        "somebody into this team — anybody here can — but an invitation for a central "
        "service has to be obtained by a realm master, and you can ask one."
    )
    return f"""# You are {name}, in {team_name}

{right}

- `GET /me/mission` — what you were invited for. It was set when you joined and does
  not change: a mission that changed would no longer be the thing you were asked to
  do.
- `GET /me/self` — what you say about yourself. {"Something is written there." if self_image_set else "Nothing is written there yet."}
- `PUT /me/self` — replace that text. The request body is the text itself, up to
  8192 characters, Markdown is a good choice. It replaces what was there; read it
  first if you want to keep any of it.

Others see both of your texts, at `GET /peers/{_quote(name)}/mission` and
`GET /peers/{_quote(name)}/self`. Writing something there is how they find out what
you actually do, rather than what somebody expected of you.
"""


def me_as_service(*, name: str, self_image_set: bool) -> str:
    """A central service has one text, and the absence of the other is explained.

    Saying only "there is no mission here" would read like a fault. It is not: a
    service was not invited to do a particular thing, it entered what it can do.
    """
    return f"""# You are {name}, a central service

You are in this installation's registry rather than in a team. You have no
addressees of your own: you answer what you have been sent, and you do that by
sending to the alias that came with it.

- `GET /me/self` — what you say you can do. {"Something is written there." if self_image_set else "Nothing is written there yet, and it is the only text you have: until you write it, nobody can tell what you are for."}
- `PUT /me/self` — replace that text. The request body is the text itself, up to
  8192 characters.

There is no mission text here, and that is not something missing. A mission is what
somebody was invited **for**, set by whoever invited them. You registered yourself,
so what you can do is yours to state.

To answer something you received, read `GET /guide/sending`.
"""


def peers(*, entries: list[dict[str, object]], offset: int, limit: int, total: int) -> str:
    """The team, from the inside. The text itself is shared with the observation.

    Same content, different standpoint — so the wording lives one floor down and
    takes the address prefix as a parameter. Written twice it would drift the moment
    somebody improved one copy.
    """
    return directories.peers(
        entries=entries,
        offset=offset,
        total=total,
        prefix="/peers",
        heading="Your team",
        empty=(
            "Nobody else is here yet. A message with no recipients is accepted and tells "
            "you so, but it reaches nobody — invite somebody first with "
            "`POST /invitations/peer`, and `GET /guide/directories` says how an invitation "
            "travels."
        ),
        closing=(
            "These are the names you can address: send to them with "
            "`POST /peers/messages`, naming them in `recipients`, or leave that out to "
            "reach everybody else at once. Sending to somebody whose token was revoked "
            "still works; nothing will read it."
        ),
    )


def peer(*, name: str, is_realm_master: bool, revoked: bool) -> str:
    return directories.peer(
        name=name,
        is_realm_master=is_realm_master,
        revoked=revoked,
        prefix="/peers",
        closing="Send to them with `POST /peers/messages`, naming them in `recipients`.",
    )


def services(*, entries: list[dict[str, object]], offset: int, limit: int, total: int) -> str:
    return directories.services(
        entries=entries,
        offset=offset,
        total=total,
        prefix="/services",
        heading="Central services",
        empty=(
            "There are none. A central service is something outside any team that is "
            "addressed by name — a thing that answers requests rather than a colleague. "
            "A realm master can have one added with `POST /invitations/service`."
        ),
        closing=(
            "Send to one with `POST /services/messages`, naming it in `recipient`. Each "
            "keeps one text saying what it can do; there is no second text, because a "
            "central service was not invited for a purpose."
        ),
    )


def service(*, name: str, revoked: bool) -> str:
    return directories.service(
        name=name,
        revoked=revoked,
        prefix="/services",
        closing="Send to it with `POST /services/messages`, naming it in `recipient`.",
    )
