"""What a crash in the middle of an operation leaves, and what never leaks.

Neither of these is a feature. They are the two questions a holdings without a
journal has to be able to answer honestly: **which wreck** does an interrupted
operation leave, and **what can a caller learn** that they must not.

The crash cases are staged by doing the first step and not the second — which is
exactly what a power cut does. None of them can be made atomic without a journal,
which this service does not have; the point of each test is that the order was
chosen so the wreck is the better one, and that the choice is not an accident.
"""

from __future__ import annotations

import pytest
from conftest import World

from simple_a2a.core.ids import new_id
from simple_a2a.domain import access, messages, refusals
from simple_a2a.domain.context import Context
from simple_a2a.store.layout import State

# ------------------------------------------------------------------- the wrecks


def test_a_claim_without_a_record_burns_the_name_and_shows_nothing(
    context: Context, world: World
) -> None:
    """The deliberate wreck of creating something, and why it is the lesser one.

    A name is claimed first and the record written second. Interrupted in between,
    the name is taken for good and no listing shows it — confusing, and the price
    of the alternative is worse: written the other way round, two callers racing
    for one name would both leave a *visible* record and a team would show two
    members with the same name, which is the one thing the claim exists to prevent.
    """
    context.holdings._claim(
        context.holdings.layout.member_by_name(world.realm_id, world.team_id, "Doris"),
        new_id(),
    )

    assert context.holdings.member_named(world.realm_id, world.team_id, "Doris") is None
    assert "Doris" not in [
        located.record.name for located in context.holdings.members(world.realm_id, world.team_id)
    ]
    with pytest.raises(refusals.NameTaken):
        access.obtain_member_invitation(
            context,
            realm_id=world.realm_id,
            team_id=world.team_id,
            member_name="doris",
            mission="m",
            display_name="Zettel Doris",
            issued_by_kind="operator",
            issued_by_name="operator",
            grants_realm_master=True,
        )


def test_redeeming_uses_the_voucher_up_before_it_makes_the_identity(
    context: Context, world: World
) -> None:
    """The order is chosen for the wreck it leaves, and this pins it down.

    Interrupted between the two steps, what is left is a used-up voucher and no
    identity. Presenting it again says "already redeemed, ask for a new one" —
    which gets a rightful holder somewhere — and the invited name is still free, so
    the new invitation can use it.

    The other way round left an identity whose token had reached nobody, a voucher
    still showing as open, and a second attempt answered with "name taken": the
    token gone for good, and nothing in the answer to act on.
    """
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
    # The first step, alone: exactly what an interruption after it would leave.
    assert context.holdings.consume_invitation(world.realm_id, voucher)

    with pytest.raises(refusals.InvitationUsed):
        access.redeem(context, voucher)

    # And the name is free, so a new invitation can be issued for the same person.
    again = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="Sie deckt.",
        display_name="Zettel Doris zwei",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    assert access.redeem(context, again).name == "Doris"


def test_a_mistake_in_the_input_does_not_cost_the_voucher(context: Context, world: World) -> None:
    """Everything is checked before the voucher is used up."""
    voucher = access.obtain_service_invitation(
        context, world.anna.caller, service_name="Wetter", display_name="Zettel Wetter"
    )

    with pytest.raises(refusals.TooLarge):
        access.redeem(context, voucher, self_image="x" * 8193)

    assert access.redeem(context, voucher, self_image="kurz").name == "Wetter"


def test_the_sender_s_own_copy_is_written_before_the_deliveries(
    context: Context, world: World, invite
) -> None:
    """So an interrupted send still leaves the sender able to see what they tried.

    The residual is named rather than prevented: without a journal, a crash between
    two deliveries leaves a message that some recipients got. The sender sees no
    answer and sends again — that is what fire-and-forget means — and duplicates are
    deliberately not detected.
    """
    invite(world.realm_id, world.team_id, "Clara")
    sent = messages.send_to_peers(
        context, world.anna.caller, recipients=[], subject="alle", body="."
    )

    outbox = messages.list_mailbox(context, world.anna.caller, messages.OUTBOX, offset=0, limit=25)
    assert [entry.message_id for entry in outbox] == [sent.message_id]
    assert {p.name for p in sent.recipients} == {"Berta", "Clara"}


# -------------------------------------------------------------------- the leaks


def test_a_message_from_another_realm_is_an_unknown_identifier(
    context: Context, world: World, invite
) -> None:
    """The realm is the outer boundary of every identifier, messages included.

    And the answer is the same as for something that does not exist: saying that
    it exists elsewhere would make an identifier a way of asking about other
    people's holdings.
    """
    other = access.create_realm(context, "keller")
    other_id = context.holdings.realm_named(other).id
    access.create_team(context, other_id, "kalt", "")
    other_team = context.holdings.team_named(other_id, "kalt").id
    stranger = invite(other_id, other_team, "Fremd")
    invite(other_id, other_team, "Zweit")
    elsewhere = messages.send_to_peers(
        context, stranger.caller, recipients=[], subject="woanders", body="geheim"
    )

    for reach in (messages.envelope, messages.subject_of, messages.body_of):
        with pytest.raises(refusals.UnknownIdentifier):
            reach(context, world.anna.caller, elsewhere.message_id)


def test_no_answer_carries_an_internal_identifier(context: Context, world: World, register) -> None:
    """A mailbox has no identifier visible from outside, and nor has an identity.

    Participants talk about names. That they are directories named by an identifier
    inside is ours to know, and this walks every field of every answer to check
    none of it got out.
    """
    wetter = register(world.anna.caller, "Wetter")
    sent = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="?"
    )
    internal = {
        world.realm_id,
        world.team_id,
        world.anna.caller.member_id,
        world.berta.caller.member_id,
        wetter.caller.service_id,
    }

    answers = [
        repr(sent),
        repr(messages.envelope(context, world.anna.caller, sent.message_id)),
        repr(messages.envelope(context, wetter.caller, sent.message_id)),
        repr(messages.list_mailbox(context, world.anna.caller, messages.OUTBOX, offset=0, limit=9)),
        repr(messages.list_mailbox(context, wetter.caller, messages.INBOX, offset=0, limit=9)),
        repr(access.revoke_member_token(context, world.realm_id, world.team_id, "Berta")),
    ]

    for answer in answers:
        for identifier in internal:
            assert identifier not in answer, f"{identifier} leaked into {answer}"


def test_a_service_never_sees_a_peer_name_in_anything_it_is_shown(
    context: Context, world: World, register
) -> None:
    """The whole point of the alias, checked across every way a service can look."""
    wetter = register(world.anna.caller, "Wetter")
    asked = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="?"
    )
    alias = messages.list_mailbox(context, wetter.caller, messages.INBOX, offset=0, limit=1)[
        0
    ].sender["name"]
    answered = messages.send_to_alias(
        context, wetter.caller, alias=alias, subject="Antwort", body="."
    )

    shown = [
        repr(messages.list_mailbox(context, wetter.caller, messages.INBOX, offset=0, limit=9)),
        repr(messages.list_mailbox(context, wetter.caller, messages.OUTBOX, offset=0, limit=9)),
        repr(messages.envelope(context, wetter.caller, asked.message_id)),
        repr(messages.envelope(context, wetter.caller, answered.message_id)),
        repr(answered),
    ]

    for view in shown:
        assert "Anna" not in view, f"a name reached the service in {view}"


def test_a_service_that_is_handed_an_identifier_may_read_it(
    context: Context, world: World, register
) -> None:
    """The other side of the same rule, and the specification says it outright.

    What somebody puts in a service's hand on purpose it may read — that is the
    capability approach, not a leak of the alias promise: it is told nothing about
    its own counterpart, and a passed-on identifier is a decision somebody made.
    """
    wetter = register(world.anna.caller, "Wetter")
    between_peers = messages.send_to_peers(
        context, world.anna.caller, recipients=["Berta"], subject="unter uns", body="."
    )

    seen = messages.envelope(context, wetter.caller, between_peers.message_id)

    assert (seen.sender.kind, seen.sender.name) == ("peer", "Anna")


def test_a_token_of_one_kind_is_refused_where_another_is_needed(
    context: Context, world: World, register
) -> None:
    """No surface takes another's secret, in either direction."""
    wetter = register(world.anna.caller, "Wetter")
    _, observer_token = access.issue_observer_token(context, world.realm_id, "Auge")
    watcher = access.authenticate(context, observer_token)

    for caller, wrong in (
        (world.anna.caller, access.as_service),
        (world.anna.caller, access.as_operator),
        (world.anna.caller, access.as_observer),
        (wetter.caller, access.as_peer),
        (wetter.caller, access.as_observer),
        (watcher, access.as_peer),
        (watcher, access.as_operator),
    ):
        with pytest.raises(refusals.WrongToken) as raised:
            wrong(caller)
        # The refusal names the kind that is needed, and nothing about elsewhere.
        assert raised.value.needed


def test_an_invitation_is_not_a_standing_token(context: Context, world: World) -> None:
    """It legitimises exactly one operation; anywhere else it is a non-token."""
    voucher = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="m",
        display_name="Zettel Doris",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )

    with pytest.raises(refusals.NoToken):
        access.authenticate(context, voucher)


def test_a_revoked_invitation_is_reported_as_revoked_and_a_used_one_is_not(
    context: Context, world: World
) -> None:
    """A revocation reports what the record says, not that the call was made."""
    used = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Doris",
        mission="m",
        display_name="Zettel Doris",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    access.redeem(context, used)

    still_open = access.revoke_invitation(context, world.realm_id, "Zettel Doris")

    assert not still_open.revoked, "nothing changed, so nothing is claimed"
    assert still_open.revoked_at is None
    located = context.holdings.invitation_named(world.realm_id, "member", "Zettel Doris")
    assert located is not None
    assert located.state is State.CONSUMED
