"""The prose about a team and a registry, written once for two surfaces.

A team is a directory of agents and the registry is a directory of services, and
two surfaces show the same thing from different standpoints: a participant sees
their own team, an observer sees any team of the installation. The specification says
"prose as on the participant surface" for exactly this reason.

So the text lives here and takes the **address prefix** as a parameter — the same
device as the one gate with a rule per surface. Written twice it would drift the
moment somebody improved one copy, which is the incident that earned this service a
single gate in the first place.

What it renders is values, not records: names, marks and counts. Nothing here knows
how the holdings are laid out, and nothing here reads them.
"""

from __future__ import annotations

from urllib.parse import quote

#: The marks a listing can carry. Words rather than symbols: a reader that has never
#: seen this service cannot look up what a dagger means.
REALM_MASTER = "realm master"
REVOKED = "token revoked"


def _quote(name: str) -> str:
    """A name in an address, percent-encoded, because a name may contain spaces."""
    return quote(name, safe="")


def _window_note(*, offset: int, shown: int, total: int) -> str:
    if total <= shown:
        return ""
    return (
        f"\nShowing {offset + 1} to {offset + shown} of {total}. Ask for a different "
        "window with `offset` and `limit`.\n"
    )


def peers(
    *,
    entries: list[dict[str, object]],
    offset: int,
    total: int,
    prefix: str,
    heading: str,
    empty: str,
    closing: str,
) -> str:
    """The members of a team, by name, with a mark where one is due.

    Names first and in order, because the names are what anybody does anything with.
    """
    if not entries:
        return f"# {heading}\n\n{empty}\n"
    lines = []
    for entry in entries:
        name = str(entry["member_name"])
        marks = []
        if entry["is_realm_master"]:
            marks.append(REALM_MASTER)
        if entry["token_revoked"]:
            marks.append(REVOKED)
        suffix = f" ({', '.join(marks)})" if marks else ""
        lines.append(
            f"- **{name}**{suffix} — `GET {prefix}/{_quote(name)}/mission`, "
            f"`GET {prefix}/{_quote(name)}/self`"
        )
    note = _window_note(offset=offset, shown=len(entries), total=total)
    return f"""# {heading}

{chr(10).join(lines)}
{note}
{closing}
"""


def peer(*, name: str, is_realm_master: bool, revoked: bool, prefix: str, closing: str) -> str:
    marks = []
    if is_realm_master:
        marks.append(
            f"Carries the {REALM_MASTER} right: may add a central service to the "
            "installation and appoint further realm masters in this team."
        )
    if revoked:
        marks.append(
            "Their token has been revoked. They stay here and stay readable, because "
            "messages from them are in other mailboxes and somebody has to be able to look "
            "up who that was."
        )
    return f"""# {name}

{" ".join(marks) if marks else "One identity in this team."}

- `GET {prefix}/{_quote(name)}/mission` — what they were invited for, set by whoever
  invited them and unchanged since.
- `GET {prefix}/{_quote(name)}/self` — what they say about themselves. They keep this
  one, so it says what they actually do rather than what was expected of them.

{closing}
"""


def services(
    *,
    entries: list[dict[str, object]],
    offset: int,
    total: int,
    prefix: str,
    heading: str,
    empty: str,
    closing: str,
) -> str:
    """The registry: the same questions, the same shape, one word different."""
    if not entries:
        return f"# {heading}\n\n{empty}\n"
    lines = [
        f"- **{entry['service_name']}**"
        f"{f' ({REVOKED})' if entry['token_revoked'] else ''} — "
        f"`GET {prefix}/{_quote(str(entry['service_name']))}/self`"
        for entry in entries
    ]
    note = _window_note(offset=offset, shown=len(entries), total=total)
    return f"""# {heading}

{chr(10).join(lines)}
{note}
{closing}
"""


def service(*, name: str, revoked: bool, prefix: str, closing: str) -> str:
    return f"""# {name}

A central service of this installation, addressed by name rather than through a team.
{"Its token has been revoked; it will not read anything more." if revoked else ""}

- `GET {prefix}/{_quote(name)}/self` — what it says it can do.

There is no mission text here, and that is not something missing: a central service
registered itself, so what it can do is its own statement rather than somebody's
expectation of it.

{closing}
"""
