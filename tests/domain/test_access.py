"""Getting in: the invitation, the two checks on a name, and what a token is.

The promises checked here are the ones a participant meets first, and each has a
way of being got wrong that costs somebody their way in.
"""

from __future__ import annotations

import pytest
from conftest import ADMIN_SECRET, World

from simple_a2a.domain import access, refusals
from simple_a2a.domain.callers import Observer, Operator, Peer, Service
from simple_a2a.domain.context import Context


def test_the_administration_secret_works_when_there_is_nothing_else(context: Context) -> None:
    """Which is the point of keeping it outside the holdings."""
    assert isinstance(access.authenticate(context, ADMIN_SECRET), Operator)
    assert context.holdings.realm_ids() == []


@pytest.mark.parametrize("presented", [None, "", "not-a-token", "x" * 43])
def test_nothing_that_cannot_be_resolved_gets_in(context: Context, presented) -> None:
    """Unreadable, unknown and absent are one answer — and so is an empty instance."""
    with pytest.raises(refusals.NoToken):
        access.authenticate(context, presented)


def test_a_revoked_token_is_answered_as_revoked_not_as_unknown(
    context: Context, world: World
) -> None:
    """Two different answers, and only one of them has a way forward."""
    token = world.anna.token
    access.revoke_member_token(context, world.realm_id, world.team_id, "Anna")

    with pytest.raises(refusals.TokenRevoked):
        access.authenticate(context, token)


def test_an_empty_realm_and_an_empty_team_are_legal(context: Context) -> None:
    """Idle, but allowed, and no secret comes out of either."""
    realm = access.create_realm(context, "leer")
    assert realm == "leer"
    assert access.create_team(context, _realm_id(context, "leer"), "still", "") == "still"


def test_a_realm_name_is_taken_only_once(context: Context) -> None:
    access.create_realm(context, "haus")
    with pytest.raises(refusals.NameTaken):
        access.create_realm(context, "HAUS")


@pytest.mark.parametrize("bad", ["", " leer", "zwei  spalten", "x" * 65, "mit/slash", None, 7])
def test_an_unusable_name_is_refused_as_input(context: Context, bad) -> None:
    with pytest.raises(refusals.InvalidInput) as raised:
        access.create_realm(context, bad)
    assert raised.value.field == "realm_name"


def test_redeeming_makes_the_identity_the_invitation_promised(
    context: Context, world: World
) -> None:
    """The operator's invitation always yields a realm master, without a choice.

    That is their way of putting somebody into a team — the first member, and later
    the way back into a team where nobody can act any more.
    """
    assert world.anna.caller.is_realm_master
    assert world.anna.caller.name == "Anna"
    assert world.anna.caller.team_id == world.team_id


def test_an_invitation_from_a_peer_does_not_grant_the_right(
    context: Context, world: World, invite
) -> None:
    clara = invite(world.realm_id, world.team_id, "Clara", by_operator=False).caller

    assert not clara.is_realm_master


def test_an_invitation_is_good_once(context: Context, world: World) -> None:
    voucher = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="Sie deckt.",
        display_name="Zettel Doris",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    access.redeem(context, voucher)

    with pytest.raises(refusals.InvitationUsed):
        access.redeem(context, voucher)


def test_a_voucher_nobody_issued_is_an_unknown_identifier(context: Context) -> None:
    with pytest.raises(refusals.UnknownIdentifier):
        access.redeem(context, "x" * 43)


def test_a_revoked_invitation_cannot_be_redeemed(context: Context, world: World) -> None:
    voucher = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="Sie deckt.",
        display_name="Zettel Doris",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    access.revoke_invitation(context, world.realm_id, "Zettel Doris")

    with pytest.raises(refusals.UnknownIdentifier):
        access.redeem(context, voucher)


def test_the_invited_name_is_checked_when_it_is_issued(context: Context, world: World) -> None:
    with pytest.raises(refusals.NameTaken):
        access.obtain_member_invitation(
            context,
            realm_id=world.realm_id,
            team_id=world.team_id,
            member_name="anna",
            mission="noch eine",
            display_name="Zettel zwei",
            issued_by_kind="operator",
            issued_by_name="operator",
            grants_realm_master=True,
        )


def test_the_invited_name_is_checked_again_when_it_is_redeemed(
    context: Context, world: World, invite
) -> None:
    """Because somebody can take it in between — which is the whole reason for twice."""
    voucher = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="Sie deckt.",
        display_name="Zettel Doris",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    invite(world.realm_id, world.team_id, "Doris")

    with pytest.raises(refusals.NameTaken):
        access.redeem(context, voucher)


def test_a_name_stays_taken_after_a_revocation(context: Context, world: World) -> None:
    """Whoever lost a token comes back under a new name, and is told so."""
    access.revoke_member_token(context, world.realm_id, world.team_id, "Anna")

    with pytest.raises(refusals.NameTaken):
        access.obtain_member_invitation(
            context,
            realm_id=world.realm_id,
            team_id=world.team_id,
            member_name="Anna",
            mission="wieder da",
            display_name="Zettel drei",
            issued_by_kind="operator",
            issued_by_name="operator",
            grants_realm_master=True,
        )


def test_only_a_realm_master_obtains_a_service_invitation(
    context: Context, world: World, invite
) -> None:
    """A bad team entry costs a team; a bad registry entry costs the realm."""
    clara = invite(world.realm_id, world.team_id, "Clara", by_operator=False).caller

    with pytest.raises(refusals.NotRealmMaster):
        access.obtain_service_invitation(
            context, clara, service_name="Wetter", display_name="Zettel Wetter"
        )

    voucher = access.obtain_service_invitation(
        context, world.anna.caller, service_name="Wetter", display_name="Zettel Wetter"
    )
    assert voucher


def test_a_redeemed_service_is_a_service_with_no_team(
    context: Context, world: World, register
) -> None:
    wetter = register(world.anna.caller, "Wetter").caller

    assert isinstance(wetter, Service)
    assert wetter.name == "Wetter"
    assert not hasattr(wetter, "team_id")


def test_redeeming_never_names_the_realm(context: Context, world: World) -> None:
    """For a participant the realm is the universe, and nothing says otherwise."""
    voucher = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="Sie deckt.",
        display_name="Zettel Doris",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    identity = access.redeem(context, voucher)

    assert not hasattr(identity, "realm_name")
    assert "haus" not in repr(identity)


def test_founding_a_team_carries_the_right_along(context: Context, world: World) -> None:
    """A realm master stays one in the new team: the right travels with the person."""
    identity = access.found_team(context, world.anna.caller, "bad", "Wir waschen.", "Anna wäscht.")

    assert identity.team_name == "bad"
    assert identity.is_realm_master
    assert identity.token != world.anna.token


def test_appointing_needs_the_right_and_stays_in_the_own_team(
    context: Context, world: World, invite
) -> None:
    made = invite(world.realm_id, world.team_id, "Clara", by_operator=False)
    clara, clara_token = made.caller, made.token

    with pytest.raises(refusals.NotRealmMaster):
        access.appoint_realm_master(context, clara, "Berta")

    assert access.appoint_realm_master(context, world.anna.caller, "Clara")
    again = access.authenticate(context, clara_token)
    assert isinstance(again, Peer)
    assert again.is_realm_master


def test_revoking_the_right_leaves_the_token_valid(context: Context, world: World) -> None:
    token = world.anna.token
    access.revoke_realm_master(context, world.realm_id, world.team_id, "Anna")

    caller = access.authenticate(context, token)
    assert isinstance(caller, Peer)
    assert not caller.is_realm_master


def test_revoking_twice_reports_the_first_time(context: Context, world: World) -> None:
    """Which is how a repeated revocation says it has already happened."""
    first = access.revoke_member_token(context, world.realm_id, world.team_id, "Anna")
    second = access.revoke_member_token(context, world.realm_id, world.team_id, "Anna")

    assert first.revoked and second.revoked
    assert first.revoked_at == second.revoked_at


def test_an_observer_token_can_be_issued_again_after_a_revocation(
    context: Context, world: World
) -> None:
    name, token = access.issue_observer_token(context, world.realm_id, "Auge")
    assert isinstance(access.authenticate(context, token), Observer)

    access.revoke_observer_token(context, world.realm_id, name)
    with pytest.raises(refusals.TokenRevoked):
        access.authenticate(context, token)

    # A new one, under a new display name — the old one stays taken like every name.
    again, other = access.issue_observer_token(context, world.realm_id, "Auge zwei")
    assert isinstance(access.authenticate(context, other), Observer)
    assert again == "Auge zwei"


def test_the_note_gives_back_exactly_what_was_put_in(context: Context, world: World) -> None:
    """Deliberately not ours to shape: the service does not know, it keeps."""
    awkward = "# Hinweise\r\n\r\n  Ruf 555.\t\\ Ende\n"
    assert access.write_note(context, awkward) == len(awkward)
    assert access.read_note(context) == awkward

    assert access.read_note(context, world.realm_id) == ""
    access.write_note(context, "Nur hier.", world.realm_id)
    assert access.read_note(context, world.realm_id) == "Nur hier."
    assert access.read_note(context) == awkward, "two notes, two subjects"


def test_writing_a_note_replaces_it(context: Context) -> None:
    access.write_note(context, "erst")
    access.write_note(context, "dann")

    assert access.read_note(context) == "dann"


def _realm_id(context: Context, name: str) -> str:
    found = context.holdings.realm_named(name)
    assert found is not None
    return found.id
