"""Who is calling, worked out from the one thing they presented.

A token names a capability and a place, and it carries no field saying what its
holder may do — so everything about a caller is looked up rather than believed.
What comes out is one of four things, and which one it is decides what is even
reachable:

- the **operator**, on the administration surface;
- a **peer**: an agent in a team, who has a team and a realm;
- a **service**: in a realm's registry, with no team and no addressee;
- an **observer**: reading one realm, writing nothing.

The place comes with it. A participant never names their realm and never names
their team — both are in the token, which is why no path carries what the token
already says.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    OPERATOR = "operator"
    PEER = "peer"
    SERVICE = "service"
    OBSERVER = "observer"


@dataclass(frozen=True)
class Operator:
    """The holder of the administration secret. Nothing is implicit for them."""

    role: Role = Role.OPERATOR


@dataclass(frozen=True)
class Peer:
    """An agent in a team: the ordinary participant.

    `is_realm_master` is read from the identity, not from the token. A token that
    merely claimed the property would be worse than a right kept honestly, and
    this one cannot be handed out.
    """

    realm_id: str
    team_id: str
    member_id: str
    name: str
    is_realm_master: bool
    role: Role = Role.PEER


@dataclass(frozen=True)
class Service:
    """A central service: one realm, no team, no addressee.

    It can only answer what it has received, and that is the shape of the
    interface rather than a rule written on top of it.
    """

    realm_id: str
    service_id: str
    name: str
    role: Role = Role.SERVICE


@dataclass(frozen=True)
class Observer:
    """Reads one realm and writes nothing. Not an identity: no texts, no mailbox."""

    realm_id: str
    observer_id: str
    display_name: str
    role: Role = Role.OBSERVER


Caller = Operator | Peer | Service | Observer

#: The kinds named in a `wrong-token` refusal. A caller is told what they
#: need, in the words of the surface they are on.
NEEDED = {
    Role.OPERATOR: "administration",
    Role.PEER: "agent-in-team",
    Role.SERVICE: "service-in-realm",
    Role.OBSERVER: "observer",
}
