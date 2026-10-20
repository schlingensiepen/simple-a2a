"""The prose of the observation surface: teams, and what happened in one.

The natural path of an observer is "give me the teams", then "give me the traffic in
that one" — so the teams come first and each one points at its own traffic. That is
also why the traffic hangs on a team and not on the installation: a list across all
teams would have no reader, and it was the reason the meaning of a filter once
depended on another field.

The directories themselves — a team's members, the registry — are rendered by the
shared texts one floor down, with this surface's addresses put in. Same content,
different standpoint.
"""

from __future__ import annotations

from urllib.parse import quote


def _quote(name: str) -> str:
    return quote(name, safe="")


def teams(*, entries: list[dict[str, object]], offset: int, total: int) -> str:
    """The one thing no participant may have, and the reason this surface exists."""
    if not entries:
        return """# Teams

There are none yet. Nothing has happened here that could be watched.
"""
    lines = [
        f"- **{entry['team_name']}** ({entry['member_count']} "
        f"{'member' if entry['member_count'] == 1 else 'members'}) — "
        f"`GET /teams/{_quote(str(entry['team_name']))}/traffic`"
        for entry in entries
    ]
    note = (
        f"\nShowing {offset + 1} to {offset + len(entries)} of {total}. Ask for a different "
        "window with `offset` and `limit`.\n"
        if total > len(entries)
        else ""
    )
    return f"""# Teams

Everything that is watched here happens inside one of these. Start with a team's
traffic, and go from there to a message, its body and its attachments.

{chr(10).join(lines)}
{note}
You read and nothing else: there is no operation on this surface that changes
anything. Nobody in a team can tell that you are here, and no answer you get will
help you tell them.
"""


def team(*, team_name: str, member_count: int, purpose_set: bool) -> str:
    return f"""# {team_name}

{member_count} {"member" if member_count == 1 else "members"}.

- `GET /teams/{_quote(team_name)}/purpose` — what this team is for, in the words of
  whoever created it.{"" if purpose_set else " Nothing has been written there yet."}
- `GET /teams/{_quote(team_name)}/peers` — who is in it, with a mark for the one
  stored right and a mark where a token has been revoked.
- `GET /teams/{_quote(team_name)}/traffic` — what has been said in it, newest first.
"""


def moments(
    *,
    joined: str,
    token_revoked: str | None,
    is_realm_master: bool,
    granted: str | None,
    deposed: str | None,
) -> str:
    """When a member arrived, and when what they carry changed — as far as it is known.

    A moment the holdings do not have is said to be unknown rather than left out: a
    missing line would read as "it never happened".
    """
    lines = [f"- Joined: {joined}."]
    if is_realm_master or granted or deposed:
        lines.append(f"- Realm master right last given: {granted or 'not recorded'}.")
        if deposed:
            lines.append(f"- Realm master right last taken: {deposed}.")
    if token_revoked:
        lines.append(f"- Token revoked: {token_revoked}.")
    return "\n".join(lines) + "\n\n"
