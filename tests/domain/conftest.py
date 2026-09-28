"""A small world to run the operations against: one realm, one team, two peers.

Built through the operations themselves rather than by writing files, so the
fixtures walk the path an operator really walks — obtain an invitation, hand it
over, redeem it — and a break in that path breaks the fixtures first.

The tokens are kept here because there is nowhere else to get them: a token is
shown exactly once, at the moment it comes into being, and stored only as a hash.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from simple_a2a.core import config
from simple_a2a.domain import access
from simple_a2a.domain.callers import Peer, Service
from simple_a2a.domain.context import Context
from simple_a2a.store.holdings import Holdings
from simple_a2a.store.layout import Layout

ADMIN_SECRET = "a" * 40


@dataclass(frozen=True)
class Member:
    """A peer and the one copy of their token there will ever be."""

    caller: Peer
    token: str


@dataclass(frozen=True)
class Registered:
    caller: Service
    token: str


@dataclass(frozen=True)
class World:
    realm_id: str
    team_id: str
    anna: Member
    berta: Member


@pytest.fixture
def admin_secret() -> str:
    return ADMIN_SECRET


@pytest.fixture
def context(tmp_path: Path) -> Context:
    holdings = Holdings(Layout(root=tmp_path / "data"))
    holdings.prepare()
    return Context(
        holdings=holdings,
        config=config.load({config.DATA_DIR: str(tmp_path / "data")}),
        admin_secret=ADMIN_SECRET,
    )


@pytest.fixture
def invite(context: Context) -> Callable[..., Member]:
    def make(realm_id: str, team_id: str, name: str, *, by_operator: bool = True) -> Member:
        voucher = access.obtain_member_invitation(
            context,
            realm_id=realm_id,
            team_id=team_id,
            member_name=name,
            mission=f"{name} arbeitet.",
            display_name=f"Zettel fuer {name}",
            issued_by_kind="operator" if by_operator else "member",
            issued_by_name="operator",
            grants_realm_master=by_operator,
        )
        identity = access.redeem(context, voucher)
        caller = access.authenticate(context, identity.token)
        assert isinstance(caller, Peer)
        return Member(caller=caller, token=identity.token)

    return make


@pytest.fixture
def register(context: Context) -> Callable[..., Registered]:
    def make(inviter: Peer, name: str) -> Registered:
        voucher = access.obtain_service_invitation(
            context, inviter, service_name=name, display_name=f"Zettel fuer {name}"
        )
        identity = access.redeem(context, voucher, self_image=f"{name} kann rechnen.")
        caller = access.authenticate(context, identity.token)
        assert isinstance(caller, Service)
        return Registered(caller=caller, token=identity.token)

    return make


@pytest.fixture
def world(context: Context, invite: Callable[..., Member]) -> World:
    realm_name = access.create_realm(context, "haus")
    realm = context.holdings.realm_named(realm_name)
    assert realm is not None
    team_name = access.create_team(context, realm.id, "kueche", "Wir kochen.")
    team = context.holdings.team_named(realm.id, team_name)
    assert team is not None
    return World(
        realm_id=realm.id,
        team_id=team.id,
        anna=invite(realm.id, team.id, "Anna"),
        berta=invite(realm.id, team.id, "Berta"),
    )
