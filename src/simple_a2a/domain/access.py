"""Getting in, getting somebody else in, and taking it away again.

The operations about who exists and who may act. Each one is written once here
because most of them are reachable from **two** surfaces: obtaining an invitation
exists on the administration and on the participant surface, creating a team
likewise. Were each surface to carry its own copy, the copies would drift apart
the moment somebody touched one — which is the incident that earned us a single
description gate, and the same argument applies to the operations themselves.

Nothing here renders anything. A refusal says what went wrong in the words of
teams and names; which rejection type that becomes, and what its text teaches,
is decided where the texts are.
"""

from __future__ import annotations

from dataclasses import dataclass

from simple_a2a.core import limits, names, tokens
from simple_a2a.core.ids import new_id
from simple_a2a.domain import refusals
from simple_a2a.domain.callers import Caller, Observer, Operator, Peer, Service
from simple_a2a.domain.context import Context
from simple_a2a.store.holdings import NameTaken
from simple_a2a.store.layout import State
from simple_a2a.store.records import Kind

#: The kinds of invitation. From above a team has members; from inside it has
#: peers. One thing, two vocabularies, and the vocabulary follows the surface.
MEMBER = "member"
SERVICE = "service"


def _check_name(value: object, field: str) -> str:
    problem = names.check_name(value)
    if problem is not None:
        raise refusals.InvalidInput(field, reason=str(problem))
    assert isinstance(value, str)
    return value


def _check_text(value: str, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise refusals.InvalidInput(field, reason="not text")
    if len(value) > limit:
        raise refusals.TooLarge(field, limit=limit, actual=len(value), unit="characters")
    return value


# --------------------------------------------------------------------- who calls


def authenticate(context: Context, presented: str | None) -> Caller:
    """Work out who is calling from the one thing they presented.

    The administration secret is checked first and separately: it is not in the
    holdings, so that it works on an instance where nothing else exists yet.

    An unresolvable token and no token at all are the same answer, and so is a
    token presented to an instance with empty holdings — where there is nothing,
    no token can be right.
    """
    if not presented:
        raise refusals.NoToken

    if context.admin_secret is not None and tokens.same_token(presented, context.admin_secret):
        return Operator()

    pointer = context.holdings.token_pointer(presented)
    if pointer is None:
        raise refusals.NoToken

    if pointer.kind == Kind.PEER:
        located = context.holdings.member(
            pointer.realm_id, pointer.team_id or "", pointer.subject_id
        )
        if located is None:
            raise refusals.NoToken
        if located.state is State.REVOKED:
            raise refusals.TokenRevoked
        return Peer(
            realm_id=pointer.realm_id,
            team_id=pointer.team_id or "",
            member_id=pointer.subject_id,
            name=located.record.name,
            is_realm_master=located.record.is_realm_master,
        )

    if pointer.kind == Kind.SERVICE:
        found = context.holdings.service(pointer.realm_id, pointer.subject_id)
        if found is None:
            raise refusals.NoToken
        if found.state is State.REVOKED:
            raise refusals.TokenRevoked
        return Service(
            realm_id=pointer.realm_id, service_id=pointer.subject_id, name=found.record.name
        )

    if pointer.kind == "observer":
        watcher = context.holdings.observer(pointer.realm_id, pointer.subject_id)
        if watcher is None:
            raise refusals.NoToken
        if watcher.state is State.REVOKED:
            raise refusals.TokenRevoked
        return Observer(
            realm_id=pointer.realm_id,
            observer_id=pointer.subject_id,
            display_name=watcher.record.display_name,
        )

    # An invitation is a voucher, not a standing token: it legitimises exactly
    # one operation, and presenting it anywhere else is presenting a non-token.
    raise refusals.NoToken


def as_operator(caller: Caller) -> Operator:
    if not isinstance(caller, Operator):
        raise refusals.WrongToken("administration")
    return caller


def as_peer(caller: Caller) -> Peer:
    if not isinstance(caller, Peer):
        raise refusals.WrongToken("agent-in-team")
    return caller


def as_service(caller: Caller) -> Service:
    if not isinstance(caller, Service):
        raise refusals.WrongToken("service-in-realm")
    return caller


def as_observer(caller: Caller) -> Observer:
    if not isinstance(caller, Observer):
        raise refusals.WrongToken("observer")
    return caller


# ------------------------------------------------------------------- containers


def create_realm(context: Context, realm_name: object) -> str:
    """A realm is a container, and an empty one is allowed.

    No secret comes back, because nothing was created that needs one: idleness is
    not a state to be fixed.
    """
    name = _check_name(realm_name, "realm_name")
    try:
        return context.holdings.create_realm(new_id(), name).name
    except NameTaken:
        raise refusals.NameTaken(name, namespace="realm") from None


def realm_by_name(context: Context, realm_name: str):
    found = context.holdings.realm_named(realm_name)
    if found is None:
        raise refusals.UnknownName(realm_name, namespace="realm")
    return found


def create_team(context: Context, realm_id: str, team_name: object, purpose: object) -> str:
    """A team is a container too, and an empty one is allowed.

    Used by the operator, who gets no token out of it, and by a participant, who
    does — the difference is the caller's, not the container's.
    """
    name = _check_name(team_name, "team_name")
    text = _check_text(
        purpose if isinstance(purpose, str) else "", "team_purpose", limits.TEAM_PURPOSE_MAX_CHARS
    )
    try:
        return context.holdings.create_team(realm_id, new_id(), name, text).name
    except NameTaken:
        raise refusals.NameTaken(name, namespace="team") from None


def team_by_name(context: Context, realm_id: str, team_name: str):
    found = context.holdings.team_named(realm_id, team_name)
    if found is None:
        raise refusals.UnknownName(team_name, namespace="team")
    return found


@dataclass(frozen=True)
class NewIdentity:
    """What comes back from redeeming, and from founding a team.

    The token is in here and is shown exactly once: there is no operation that
    hands out an existing one, so this is the only moment it exists outside the
    holdings.
    """

    token: str
    kind: str
    name: str
    team_name: str | None = None
    is_realm_master: bool = False


def found_team(
    context: Context, peer: Peer, team_name: object, purpose: object, mission: object
) -> NewIdentity:
    """A participant creates a team and is its first member.

    Teams come into being freely — anybody in a team may make another — which is
    why a realm is not a general boundary of permission. A realm master stays one
    in the new team: the right travels with the person, not with the team.
    """
    name = create_team(context, peer.realm_id, team_name, purpose)
    team = context.holdings.team_named(peer.realm_id, name)
    assert team is not None
    text = _check_text(
        mission if isinstance(mission, str) else "",
        "member_mission",
        limits.MEMBER_MISSION_MAX_CHARS,
    )
    token = tokens.new_token()
    context.holdings.create_member(
        peer.realm_id,
        team.id,
        new_id(),
        peer.name,
        token=token,
        mission=text,
        is_realm_master=peer.is_realm_master,
    )
    return NewIdentity(
        token=token,
        kind=Kind.PEER,
        name=peer.name,
        team_name=name,
        is_realm_master=peer.is_realm_master,
    )


# ------------------------------------------------------------------ invitations


def obtain_member_invitation(
    context: Context,
    *,
    realm_id: str,
    team_id: str,
    member_name: object,
    mission: object,
    display_name: object,
    issued_by_kind: str,
    issued_by_name: str,
    grants_realm_master: bool,
) -> str:
    """Issue a voucher for a place in a team, and hand it over once.

    The invited name is fixed here, because whoever invites has to give them a
    mission — you cannot write an assignment for a person you cannot name. It is
    checked here **and** again at redemption, because somebody can take it in
    between.
    """
    name = _check_name(member_name, "member_name")
    shown = _check_name(display_name, "display_name")
    text = _check_text(
        mission if isinstance(mission, str) else "",
        "member_mission",
        limits.MEMBER_MISSION_MAX_CHARS,
    )
    # Asked of the claim, not of the records: the claim is what the redemption will
    # collide with. Asking whether a member *exists* gets one case wrong — a claim
    # whose record never made it — and then the invitation is issued for a name that
    # cannot be redeemed, and the one who finds out is the invited person.
    if context.holdings.member_name_taken(realm_id, team_id, name):
        raise refusals.NameTaken(name, namespace="member")

    voucher = new_id()
    try:
        context.holdings.create_invitation(
            realm_id,
            voucher=voucher,
            kind=MEMBER,
            display_name=shown,
            invited_name=name,
            issued_by_kind=issued_by_kind,
            issued_by_name=issued_by_name,
            team_id=team_id,
            mission=text,
            grants_realm_master=grants_realm_master,
        )
    except NameTaken:
        raise refusals.NameTaken(shown, namespace="invitation") from None
    return voucher


def obtain_service_invitation(
    context: Context, peer: Peer, *, service_name: object, display_name: object
) -> str:
    """Issue a voucher for a place in the realm's registry.

    Only a realm master may: a bad team entry costs a team, a bad registry entry
    costs the whole realm.
    """
    if not peer.is_realm_master:
        raise refusals.NotRealmMaster
    name = _check_name(service_name, "service_name")
    shown = _check_name(display_name, "display_name")
    if context.holdings.service_name_taken(peer.realm_id, name):
        raise refusals.NameTaken(name, namespace="service")

    voucher = new_id()
    try:
        context.holdings.create_invitation(
            peer.realm_id,
            voucher=voucher,
            kind=SERVICE,
            display_name=shown,
            invited_name=name,
            issued_by_kind=Kind.MEMBER,
            issued_by_name=peer.name,
        )
    except NameTaken:
        raise refusals.NameTaken(shown, namespace="invitation") from None
    return voucher


def _mission_of(context: Context, realm_id: str, digest: str, state: State) -> str | None:
    """The mission an invitation carried, read while it is still in that state.

    Read before the voucher is used up, because using it up renames the directory
    the text lives in.
    """
    return context.holdings.invitation_mission(realm_id, digest, state)


def redeem(context: Context, voucher: object, *, self_image: object = None) -> NewIdentity:
    """Exchange a voucher for a token. The one operation without a standing token.

    Once. Afterwards the answer is "already redeemed", which is a different thing
    from "unknown": it tells the rightful holder to ask for a new one, where "not
    found" would leave them stuck.

    The realm is not asked for and is never named back. A participant's token
    carries their context; for them the realm is the universe.
    """
    if not isinstance(voucher, str) or not voucher:
        raise refusals.InvalidInput("invitation", reason="missing")

    pointer = context.holdings.token_pointer(voucher)
    if pointer is None or pointer.kind != "invitation":
        raise refusals.UnknownIdentifier("invitation")

    located = context.holdings.invitation_for(pointer.realm_id, voucher)
    if located is None:
        raise refusals.UnknownIdentifier("invitation")
    if located.state is State.CONSUMED:
        raise refusals.InvitationUsed
    if located.state is State.REVOKED:
        raise refusals.UnknownIdentifier("invitation")

    invitation = located.record
    realm_id = pointer.realm_id
    token = tokens.new_token()

    # Everything the caller sent is checked, and everything the invitation needs is
    # read, *before* the voucher is used up. Otherwise a mistyped field costs
    # somebody their invitation.
    self_image_text = (
        _check_text(
            self_image if isinstance(self_image, str) else "",
            "member_self_image",
            limits.MEMBER_SELF_IMAGE_MAX_CHARS,
        )
        if invitation.kind == SERVICE
        else ""
    )
    mission = _mission_of(context, realm_id, pointer.subject_id, located.state) or ""
    team = (
        context.holdings.team(realm_id, invitation.team_id or "")
        if invitation.kind != SERVICE
        else None
    )
    if invitation.kind != SERVICE and team is None:
        raise refusals.UnknownIdentifier("invitation")

    # The voucher is used up **before** the identity is made, and the order is the
    # whole point. There is no journal here, so one of the two has to be first, and
    # a crash between them has to leave the better wreck.
    #
    # This way round: a consumed voucher and no identity. Whoever presents it again
    # is told "already redeemed, ask for a new one" — the answer that gets a
    # rightful holder somewhere — and the invited name is still free, so the new
    # invitation can use it.
    #
    # The other way round left an identity whose token had never reached anybody,
    # a voucher still showing as open, and a second attempt answered with
    # "name taken": the holder's token was gone for good, and the answer told them
    # nothing they could act on.
    if not context.holdings.consume_invitation(realm_id, voucher):
        raise refusals.InvitationUsed

    if invitation.kind == SERVICE:
        # The name is checked a second time here, because somebody can have taken
        # it between issuing and redeeming. Checked by *trying*: the claim is what
        # makes it atomic, so asking first and creating after would reopen the gap
        # it closes.
        try:
            created = context.holdings.create_service(
                realm_id,
                new_id(),
                invitation.invited_name,
                token=token,
                self_image=self_image_text,
            )
        except NameTaken:
            raise refusals.NameTaken(invitation.invited_name, namespace="service") from None
        return NewIdentity(token=token, kind=Kind.SERVICE, name=created.name)

    assert team is not None
    team_id = invitation.team_id or ""
    invited = invitation.invited_name
    try:
        context.holdings.create_member(
            realm_id,
            team_id,
            new_id(),
            invited,
            token=token,
            mission=mission,
            is_realm_master=invitation.grants_realm_master,
        )
    except NameTaken:
        raise refusals.NameTaken(invited, namespace="member") from None
    return NewIdentity(
        token=token,
        kind=Kind.PEER,
        name=invited,
        team_name=team.name,
        is_realm_master=invitation.grants_realm_master,
    )


# ------------------------------------------------------------------ revocations


@dataclass(frozen=True)
class Revocation:
    """What a revocation says back.

    The subject keeps being named, because nothing disappeared — a revocation ends
    a permission, not a content.

    `revoked` is read from the record afterwards rather than assumed from the fact
    that the call was made. There is a case where the two differ: revoking an
    invitation that has already been redeemed changes nothing, and saying "done"
    there would report something that did not happen.
    """

    name: str
    revoked: bool
    revoked_at: str | None


def _revoked_at(record) -> str | None:
    return getattr(record, "revoked_at", None)


def _as_revoked(name: str, record) -> Revocation:
    """Report what the record says, not what the call intended."""
    at = _revoked_at(record)
    return Revocation(name=name, revoked=at is not None, revoked_at=at)


def revoke_member_token(
    context: Context, realm_id: str, team_id: str, member_name: str
) -> Revocation:
    """Take a member's token away. Repeatable, and the second time says so.

    The timestamp is the one of the **first** revocation, which is how a repeated
    one tells the caller it has already happened — without a warning and without a
    second rejection type.

    What it does not do: delete. The identity stays visible and readable, because
    messages from them are in somebody's inbox and one has to be able to look up
    who that was. Their invitations stay redeemable and have to be revoked one by
    one; the listing names the issuer so the operator can find them.
    """
    located = context.holdings.member_named(realm_id, team_id, member_name)
    if located is None:
        raise refusals.UnknownName(member_name, namespace="member")
    context.holdings.revoke_member(realm_id, team_id, located.record.id)
    again = context.holdings.member(realm_id, team_id, located.record.id)
    assert again is not None
    return _as_revoked(again.record.name, again.record)


def revoke_service_token(context: Context, realm_id: str, service_name: str) -> Revocation:
    located = context.holdings.service_named(realm_id, service_name)
    if located is None:
        raise refusals.UnknownName(service_name, namespace="service")
    context.holdings.revoke_service(realm_id, located.record.id)
    again = context.holdings.service(realm_id, located.record.id)
    assert again is not None
    return _as_revoked(again.record.name, again.record)


def revoke_observer_token(context: Context, realm_id: str, display_name: str) -> Revocation:
    located = context.holdings.observer_named(realm_id, display_name)
    if located is None:
        raise refusals.UnknownName(display_name, namespace="observer token")
    context.holdings.revoke_observer(realm_id, located.record.id)
    again = context.holdings.observer(realm_id, located.record.id)
    assert again is not None
    return _as_revoked(again.record.display_name, again.record)


def revoke_invitation(context: Context, realm_id: str, display_name: str) -> Revocation:
    """Revoke a voucher over its display name. Never over the secret.

    Both kinds are looked in, because a display name is unique per kind and the
    operator's listing does not separate them.
    """
    for kind in (MEMBER, SERVICE):
        located = context.holdings.invitation_named(realm_id, kind, display_name)
        if located is None:
            continue
        context.holdings.revoke_invitation_named(realm_id, kind, display_name)
        again = context.holdings.invitation_named(realm_id, kind, display_name)
        assert again is not None
        return _as_revoked(again.record.display_name, again.record)
    raise refusals.UnknownName(display_name, namespace="invitation")


# -------------------------------------------------------- the one stored right


def appoint_realm_master(context: Context, peer: Peer, member_name: str) -> bool:
    """Make somebody in one's own team a realm master.

    Only a realm master may, and only in their own team — because they cannot see
    anything else. Appointing and revoking are deliberately asymmetric: whoever
    may appoint may not depose, or two realm masters can unseat each other and
    then there has to be an arbitration rule, which is exactly the apparatus this
    avoids.
    """
    if not peer.is_realm_master:
        raise refusals.NotRealmMaster
    located = context.holdings.member_named(peer.realm_id, peer.team_id, member_name)
    if located is None:
        raise refusals.UnknownName(member_name, namespace="member")
    context.holdings.set_realm_master(peer.realm_id, peer.team_id, located.record.id, True)
    return True


def revoke_realm_master(context: Context, realm_id: str, team_id: str, member_name: str) -> bool:
    """Take the right away. Administration only, and the token stays valid.

    The identity stays in the team; only the one stored right goes. There is no
    way to give it up oneself — deposing runs over the administration surface.
    """
    located = context.holdings.member_named(realm_id, team_id, member_name)
    if located is None:
        raise refusals.UnknownName(member_name, namespace="member")
    context.holdings.set_realm_master(realm_id, team_id, located.record.id, False)
    return False


def issue_observer_token(context: Context, realm_id: str, display_name: object) -> tuple[str, str]:
    """Issue a token for watching one realm. Whenever the operator wants.

    Also again after a revocation, and several may exist at once — each one
    addressable by its display name, because a token is not something to be named
    by and nothing ever hands one back.
    """
    shown = _check_name(display_name, "display_name")
    token = tokens.new_token()
    try:
        context.holdings.create_observer(realm_id, new_id(), shown, token=token)
    except NameTaken:
        raise refusals.NameTaken(shown, namespace="observer token") from None
    return shown, token


# ------------------------------------------------------------------------ notes


def read_note(context: Context, realm_id: str | None = None) -> str:
    """Whatever somebody wrote in it, or nothing at all.

    Deliberately not under our control. The service does not know where the other
    surfaces are reachable, but it can offer a place to write it down: it does not
    *know*, it *keeps*.
    """
    text = (
        context.holdings.global_note()
        if realm_id is None
        else context.holdings.realm_note(realm_id)
    )
    return text or ""


def write_note(context: Context, text: object, realm_id: str | None = None) -> int:
    """Replace it. Always — there is no appending and no second write behaviour.

    Losing what was there is named rather than prevented: the description says
    "read first, then write". A version marker for concurrent writers would be a
    rule every caller has to keep, to a situation nobody could describe.
    """
    body = _check_text(
        text if isinstance(text, str) else "", "setup_note", limits.SETUP_NOTE_MAX_CHARS
    )
    if realm_id is None:
        context.holdings.set_global_note(body)
    else:
        context.holdings.set_realm_note(realm_id, body)
    return len(body)
